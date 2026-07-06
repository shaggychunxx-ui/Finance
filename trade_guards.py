"""Pre-preview guards: buying power and PDT / day-trade limits."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
PDT_TRACKER_FILE = OUTPUT / "pdt_tracker.json"
ET_TZ = ZoneInfo("America/New_York")

DEFAULT_TRADE_GUARDS = {
    "enabled": True,
    "pdt_equity_threshold_usd": 25000.0,
    "pdt_max_day_trades_5d": 3,
    "buying_power_buffer_pct": 2.0,
}


def load_trade_guard_settings(config_path: Path | None = None) -> dict[str, Any]:
    settings = dict(DEFAULT_TRADE_GUARDS)
    path = config_path or (ROOT / "etrade_config.json")
    if not path.exists():
        return settings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        user = raw.get("trade_guards", {})
        if isinstance(user, dict):
            settings.update({k: user[k] for k in settings if k in user})
    except (json.JSONDecodeError, OSError):
        pass
    return settings


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _session_date(now: datetime | None = None) -> str:
    now = now or datetime.now(ET_TZ)
    return now.strftime("%Y-%m-%d")


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _business_day_window(as_of: date, days: int = 5) -> set[str]:
    """Last N US market business days including as_of."""
    found: list[str] = []
    cursor = as_of
    while len(found) < days:
        if cursor.weekday() < 5:
            found.append(cursor.strftime("%Y-%m-%d"))
        cursor -= timedelta(days=1)
        if (as_of - cursor).days > 14:
            break
    return set(found)


def resolve_buying_power(balance: dict[str, Any]) -> float:
    for key in (
        "cash_buying_power",
        "cash_available_for_investment",
        "margin_buying_power",
        "net_cash",
    ):
        value = balance.get(key)
        if value is not None:
            try:
                amount = float(value)
            except (TypeError, ValueError):
                continue
            if amount > 0:
                return amount
    return 0.0


def order_notional(order: Any) -> float:
    if order.quantity <= 0:
        return 0.0
    price = order.estimated_price
    if (order.price_type or "MARKET").upper() == "LIMIT" and order.limit_price is not None:
        price = float(order.limit_price)
    return max(0.0, float(order.quantity) * float(price))


def load_pdt_tracker() -> dict[str, Any]:
    data = _load_json(PDT_TRACKER_FILE)
    data.setdefault("day_trades", [])
    data.setdefault("same_day_activity", {})
    return data


def save_pdt_tracker(data: dict[str, Any]) -> None:
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(PDT_TRACKER_FILE, data)


def count_day_trades_in_window(
    tracker: dict[str, Any],
    *,
    as_of: date | None = None,
    window_days: int = 5,
) -> int:
    as_of = as_of or datetime.now(ET_TZ).date()
    window = _business_day_window(as_of, window_days)
    total = 0
    for row in tracker.get("day_trades", []) or []:
        trade_date = str(row.get("date", ""))
        if trade_date in window:
            total += 1
    return total


def _position_qty_map(positions: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for pos in positions or []:
        sym = str(pos.get("symbol", "")).upper()
        if not sym:
            continue
        out[sym] = out.get(sym, 0) + int(pos.get("quantity", 0) or 0)
    return out


def _today_activity(tracker: dict[str, Any], session_date: str) -> dict[str, dict[str, int]]:
    raw = tracker.get("same_day_activity", {}) or {}
    today = raw.get(session_date, {}) or {}
    out: dict[str, dict[str, int]] = {}
    for sym, row in today.items():
        if not isinstance(row, dict):
            continue
        out[str(sym).upper()] = {
            "buy_qty": int(row.get("buy_qty", 0) or 0),
            "sell_qty": int(row.get("sell_qty", 0) or 0),
        }
    return out


def _intraday_buy_qty(day_state: dict[str, Any] | None) -> dict[str, int]:
    out: dict[str, int] = {}
    if not day_state:
        return out
    for pos in day_state.get("positions", []) or []:
        sym = str(pos.get("symbol", "")).upper()
        if not sym:
            continue
        out[sym] = out.get(sym, 0) + int(pos.get("quantity", 0) or 0)
    return out


def _sell_is_day_trade(
    order: Any,
    *,
    activity: dict[str, dict[str, int]],
    intraday_buys: dict[str, int],
    held_qty: dict[str, int],
) -> bool:
    sym = order.symbol.upper()
    sell_qty = int(order.quantity)
    if sell_qty <= 0:
        return False

    bought_today = int(activity.get(sym, {}).get("buy_qty", 0)) + int(intraday_buys.get(sym, 0))
    if bought_today <= 0:
        return False

    overnight_qty = max(0, int(held_qty.get(sym, 0)) - bought_today)
    return sell_qty > overnight_qty


def _buy_is_day_trade(order: Any, *, activity: dict[str, dict[str, int]]) -> bool:
    sym = order.symbol.upper()
    sold_today = int(activity.get(sym, {}).get("sell_qty", 0))
    return sold_today > 0 and int(order.quantity) > 0


def _order_needs_day_trade_slot(
    order: Any,
    *,
    activity: dict[str, dict[str, int]],
    intraday_buys: dict[str, int],
    held_qty: dict[str, int],
    is_day_trading_plan: bool,
) -> tuple[bool, str]:
    sym = order.symbol.upper()
    if is_day_trading_plan:
        # Entry reserves one PDT slot; same-day exit is the closing leg (no extra slot).
        if order.action == "BUY":
            return True, f"intraday BUY {sym} (same-day exit expected)"
        return False, ""

    if order.action == "SELL" and _sell_is_day_trade(
        order,
        activity=activity,
        intraday_buys=intraday_buys,
        held_qty=held_qty,
    ):
        return True, f"SELL {sym} of shares bought today"
    if order.action == "BUY" and _buy_is_day_trade(order, activity=activity):
        return True, f"BUY {sym} after same-day SELL"
    return False, ""


def apply_buying_power_guard(
    orders: list[Any],
    *,
    buying_power: float,
    buffer_pct: float,
) -> dict[str, Any]:
    available = max(0.0, float(buying_power) * (1 - float(buffer_pct) / 100))
    spent = 0.0
    blocked = 0
    for order in orders:
        if order.status == "blocked" or order.action != "BUY" or order.quantity <= 0:
            continue
        cost = order_notional(order)
        if cost <= 0:
            order.status = "blocked"
            order.message = "Blocked — invalid order price for buying-power check"
            blocked += 1
            continue
        if spent + cost > available + 1e-6:
            order.status = "blocked"
            order.message = (
                f"Blocked — insufficient buying power "
                f"(${available:,.2f} available after {buffer_pct:.0f}% buffer, "
                f"need ${cost:,.2f})"
            )
            blocked += 1
            continue
        spent += cost
    return {
        "buying_power": round(buying_power, 2),
        "available_usd": round(available, 2),
        "planned_buy_usd": round(spent, 2),
        "blocked_buys": blocked,
    }


def apply_pdt_guard(
    orders: list[Any],
    *,
    total_equity: float,
    positions: list[dict[str, Any]],
    day_state: dict[str, Any] | None,
    settings: dict[str, Any],
    tracker: dict[str, Any] | None = None,
    session_date: str | None = None,
    is_day_trading_plan: bool = False,
) -> dict[str, Any]:
    threshold = float(settings.get("pdt_equity_threshold_usd", DEFAULT_TRADE_GUARDS["pdt_equity_threshold_usd"]))
    max_trades = int(settings.get("pdt_max_day_trades_5d", DEFAULT_TRADE_GUARDS["pdt_max_day_trades_5d"]))
    session_date = session_date or _session_date()
    as_of = _parse_date(session_date) or datetime.now(ET_TZ).date()
    tracker = tracker if tracker is not None else load_pdt_tracker()

    current = count_day_trades_in_window(tracker, as_of=as_of)
    if total_equity >= threshold:
        return {
            "pdt_applies": False,
            "equity_usd": round(total_equity, 2),
            "day_trades_5d": current,
            "blocked_day_trades": 0,
        }

    activity = deepcopy(_today_activity(tracker, session_date))
    intraday_buys = _intraday_buy_qty(day_state)
    held_qty = _position_qty_map(positions)
    slots_remaining = max(0, max_trades - current)
    blocked = 0
    reserved = 0

    for order in orders:
        if order.quantity <= 0 or order.status == "blocked":
            continue
        sym = order.symbol.upper()
        activity.setdefault(sym, {"buy_qty": 0, "sell_qty": 0})

        needs_slot, reason = _order_needs_day_trade_slot(
            order,
            activity=activity,
            intraday_buys=intraday_buys,
            held_qty=held_qty,
            is_day_trading_plan=is_day_trading_plan,
        )
        if needs_slot:
            if slots_remaining <= 0:
                order.status = "blocked"
                order.message = (
                    f"Blocked — PDT limit ({current}/{max_trades} day trades in 5 business days, "
                    f"equity ${total_equity:,.0f} < ${threshold:,.0f}): {reason}"
                )
                blocked += 1
            else:
                slots_remaining -= 1
                reserved += 1

        if order.action == "BUY":
            activity[sym]["buy_qty"] += int(order.quantity)
            if is_day_trading_plan:
                intraday_buys[sym] = intraday_buys.get(sym, 0) + int(order.quantity)
        elif order.action == "SELL":
            activity[sym]["sell_qty"] += int(order.quantity)

    return {
        "pdt_applies": True,
        "equity_usd": round(total_equity, 2),
        "day_trades_5d": current,
        "reserved_day_trades": reserved,
        "max_day_trades_5d": max_trades,
        "blocked_day_trades": blocked,
    }


def apply_trade_guards_to_plan(
    plan: Any,
    balance: dict[str, Any],
    *,
    settings: dict[str, Any] | None = None,
    day_state: dict[str, Any] | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Block orders that violate buying power or PDT rules before E*TRADE preview."""
    guard_settings = settings or load_trade_guard_settings(config_path)
    if not guard_settings.get("enabled", True):
        return {"enabled": False}

    buying_power = resolve_buying_power(balance)
    total_equity = float(
        plan.total_account_value
        or balance.get("total_account_value")
        or 0.0
    )
    buffer_pct = float(guard_settings.get("buying_power_buffer_pct", 2.0))

    bp_summary = apply_buying_power_guard(
        plan.orders,
        buying_power=buying_power,
        buffer_pct=buffer_pct,
    )
    is_day_trading_plan = (plan.meta or {}).get("mode") == "day_trading"
    pdt_summary = apply_pdt_guard(
        plan.orders,
        total_equity=total_equity,
        positions=plan.current_positions,
        day_state=day_state,
        settings=guard_settings,
        is_day_trading_plan=is_day_trading_plan,
    )

    summary = {
        "enabled": True,
        "session_date": _session_date(),
        **bp_summary,
        **pdt_summary,
    }
    plan.meta.setdefault("trade_guards", summary)
    return summary


def record_placed_orders_for_pdt(
    orders: list[Any],
    *,
    session_date: str | None = None,
) -> None:
    """Persist same-day activity and completed day trades after live fills."""
    session_date = session_date or _session_date()
    tracker = load_pdt_tracker()
    activity = tracker.setdefault("same_day_activity", {})
    today = activity.setdefault(session_date, {})

    for order in orders:
        if order.status not in {"placed", "dry_run"} or order.quantity <= 0:
            continue
        sym = order.symbol.upper()
        row = today.setdefault(sym, {"buy_qty": 0, "sell_qty": 0})
        if order.action == "BUY":
            row["buy_qty"] = int(row.get("buy_qty", 0)) + int(order.quantity)
        elif order.action == "SELL":
            row["sell_qty"] = int(row.get("sell_qty", 0)) + int(order.quantity)

    existing = {
        (str(row.get("date", "")), str(row.get("symbol", "")).upper())
        for row in tracker.get("day_trades", []) or []
    }
    for sym, row in list(today.items()):
        buy_qty = int(row.get("buy_qty", 0) or 0)
        sell_qty = int(row.get("sell_qty", 0) or 0)
        key = (session_date, str(sym).upper())
        if buy_qty > 0 and sell_qty > 0 and key not in existing:
            tracker.setdefault("day_trades", []).append(
                {
                    "date": session_date,
                    "symbol": str(sym).upper(),
                    "buy_qty": buy_qty,
                    "sell_qty": sell_qty,
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            existing.add(key)

    save_pdt_tracker(tracker)


def prune_old_pdt_records(*, keep_days: int = 30) -> None:
    tracker = load_pdt_tracker()
    cutoff = datetime.now(ET_TZ).date() - timedelta(days=keep_days)
    trades = []
    for row in tracker.get("day_trades", []) or []:
        trade_date = _parse_date(str(row.get("date", "")))
        if trade_date and trade_date >= cutoff:
            trades.append(row)
    tracker["day_trades"] = trades[-500:]

    activity = tracker.get("same_day_activity", {}) or {}
    trimmed: dict[str, Any] = {}
    for day_key, rows in activity.items():
        day = _parse_date(day_key)
        if day and day >= cutoff:
            trimmed[day_key] = rows
    tracker["same_day_activity"] = trimmed
    save_pdt_tracker(tracker)