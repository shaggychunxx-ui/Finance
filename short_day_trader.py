#!/usr/bin/env python3
"""Intraday short day-trading: SELL_SHORT on strong down signals, BUY_TO_COVER exits."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from etrade_api.client import ETradeClient
from short_paths import SHORT_DAY_PLAN_FILE, SHORT_DAY_STATE_FILE, SHORT_OUTPUT, ensure_short_dirs
from short_strategy_engine import _short_positions
from strategy_engine import StrategyPlan, TradeOrder, _quote_price

ET_TZ = ZoneInfo("America/New_York")

DEFAULT_SHORT_DAY = {
    "enabled": True,
    "interval_minutes": 5,
    "max_positions": 2,
    "capital_pct": 15.0,
    "min_daily_drop_pct": 0.35,
    "min_confidence": 0.55,
    "take_profit_pct": 0.6,
    "stop_loss_pct": 0.45,
    "flatten_minutes_before_close": 20,
    "max_trade_usd": 500.0,
    "min_trade_usd": 75.0,
}


@dataclass
class ShortDayPosition:
    symbol: str
    quantity: int
    entry_price: float
    entry_at: str
    take_profit_pct: float
    stop_loss_pct: float
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "entry_price": round(self.entry_price, 4),
            "entry_at": self.entry_at,
            "take_profit_pct": self.take_profit_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "rationale": self.rationale,
            "side": "SHORT",
        }


def load_short_day_settings(config_path: Path | None = None) -> dict[str, Any]:
    from short_paths import SHORT_CONFIG

    path = config_path or SHORT_CONFIG
    settings = dict(DEFAULT_SHORT_DAY)
    if not path.exists():
        return settings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        user = raw.get("short_day_trading", {})
        if isinstance(user, dict):
            settings.update({k: user[k] for k in user})
        worker = raw.get("background_worker", {})
        if "day_trading" in worker:
            settings["enabled"] = bool(worker["day_trading"]) and bool(settings.get("enabled", True))
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


def load_short_day_state() -> dict[str, Any]:
    ensure_short_dirs()
    state = _load_json(SHORT_DAY_STATE_FILE)
    if not state:
        state = {"session_date": "", "positions": [], "closed": []}
    return state


def save_short_day_state(state: dict[str, Any]) -> None:
    ensure_short_dirs()
    _write_json(SHORT_DAY_STATE_FILE, state)


def minutes_to_market_close(now: datetime | None = None) -> float | None:
    now = now or datetime.now(ET_TZ)
    if now.weekday() >= 5:
        return None
    close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    open_ = now.replace(hour=9, minute=30, second=0, microsecond=0)
    if now < open_ or now > close:
        return None
    return (close - now).total_seconds() / 60.0


def _session_date(now: datetime | None = None) -> str:
    now = now or datetime.now(ET_TZ)
    return now.strftime("%Y-%m-%d")


def _position_objects(state: dict[str, Any]) -> list[ShortDayPosition]:
    out: list[ShortDayPosition] = []
    for raw in state.get("positions") or []:
        if not raw.get("symbol"):
            continue
        out.append(
            ShortDayPosition(
                symbol=str(raw["symbol"]).upper(),
                quantity=int(raw.get("quantity") or 0),
                entry_price=float(raw.get("entry_price") or 0),
                entry_at=str(raw.get("entry_at") or ""),
                take_profit_pct=float(raw.get("take_profit_pct") or DEFAULT_SHORT_DAY["take_profit_pct"]),
                stop_loss_pct=float(raw.get("stop_loss_pct") or DEFAULT_SHORT_DAY["stop_loss_pct"]),
                rationale=str(raw.get("rationale") or ""),
            )
        )
    return out


def _down_candidates(output_dir: Path | None = None) -> list[dict[str, Any]]:
    """24h predictions with negative expected return / down direction."""
    from app_paths import OUTPUT

    root = output_dir or OUTPUT
    data = _load_json(root / "market_predictions.json")
    rows = (data.get("predictions") or {}).get("24h") or []
    out: list[dict[str, Any]] = []
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if not sym:
            continue
        direction = str(row.get("predicted_direction") or "").lower()
        ret = float(row.get("predicted_return_pct") or 0)
        conf = float(row.get("confidence") or row.get("probability") or 0.5)
        if direction == "down" or ret < 0:
            out.append(
                {
                    "symbol": sym,
                    "predicted_return_pct": ret,
                    "confidence": conf,
                    "direction": direction or "down",
                    "rationale": row.get("rationale") or "24h down signal",
                }
            )
    out.sort(key=lambda r: (r["predicted_return_pct"], -r["confidence"]))
    return out


def build_short_day_trade_plan(
    client: ETradeClient,
    account_id_key: str,
    account_name: str = "",
    *,
    settings: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
) -> StrategyPlan:
    ensure_short_dirs()
    settings = settings or load_short_day_settings()
    state = state if state is not None else load_short_day_state()
    session = _session_date()
    if state.get("session_date") != session:
        state = {"session_date": session, "positions": [], "closed": state.get("closed") or []}

    balance = client.get_balance(account_id_key)
    positions = client.get_portfolio(account_id_key)
    short_map = _short_positions(positions)
    total_value = float(balance.get("total_account_value") or 0)
    margin_bp = float(balance.get("margin_buying_power") or balance.get("cash_buying_power") or 0)
    if total_value <= 0:
        total_value = margin_bp or 1.0

    capital_pct = float(settings.get("capital_pct", 15.0))
    sleeve = total_value * capital_pct / 100.0
    # Shared capital pool — soft short ceiling from sleeve policy
    try:
        from sleeve_policy import blocked_symbols_for_new_entry, shared_capital_budget

        budget = shared_capital_budget(total_value, sleeve="short", balance=balance)
        deployable = float(budget.get("deployable_usd") or 0)
        if deployable > 0:
            sleeve = min(sleeve, deployable)
        blocked_new = blocked_symbols_for_new_entry("short", positions)
    except Exception:
        blocked_new = set()
        budget = {}
    max_trade = float(settings.get("max_trade_usd", 500.0))
    min_trade = float(settings.get("min_trade_usd", 75.0))
    max_positions = int(settings.get("max_positions", 2))
    min_drop = float(settings.get("min_daily_drop_pct", 0.35))
    min_conf = float(settings.get("min_confidence", 0.55))
    take_profit = float(settings.get("take_profit_pct", 0.6))
    stop_loss = float(settings.get("stop_loss_pct", 0.45))

    day_positions = _position_objects(state)
    held = {p.symbol for p in day_positions}
    orders: list[TradeOrder] = []

    minutes_left = minutes_to_market_close()
    flatten_window = float(settings.get("flatten_minutes_before_close", 20))
    should_flatten = minutes_left is not None and minutes_left <= flatten_window

    # Manage open short day positions — P&L inverted vs long
    remaining_positions: list[ShortDayPosition] = []
    for pos in day_positions:
        price = _quote_price(client, pos.symbol) or pos.entry_price
        if price <= 0:
            remaining_positions.append(pos)
            continue
        # Short profit when price falls
        pnl_pct = (pos.entry_price - price) / pos.entry_price * 100 if pos.entry_price else 0.0
        cover_reason = ""
        if should_flatten:
            cover_reason = f"Flatten short before close ({int(minutes_left or 0)} min left)"
        elif pnl_pct >= pos.take_profit_pct:
            cover_reason = f"Short take-profit +{pnl_pct:.2f}%"
        elif pnl_pct <= -pos.stop_loss_pct:
            cover_reason = f"Short stop-loss {pnl_pct:.2f}%"
        if cover_reason:
            qty = min(pos.quantity, int(short_map.get(pos.symbol, {}).get("quantity") or pos.quantity))
            if qty > 0:
                orders.append(
                    TradeOrder(
                        symbol=pos.symbol,
                        action="BUY_TO_COVER",
                        quantity=qty,
                        target_weight_pct=0.0,
                        current_weight_pct=0.0,
                        target_value_usd=0.0,
                        current_value_usd=qty * price,
                        estimated_price=price,
                        rationale=cover_reason,
                    )
                )
                state.setdefault("closed", []).append({**pos.to_dict(), "exit_reason": cover_reason, "exit_price": price})
            continue
        remaining_positions.append(pos)

    state["positions"] = [p.to_dict() for p in remaining_positions]
    held = {p.symbol for p in remaining_positions}

    # New short entries
    if not should_flatten and len(remaining_positions) < max_positions:
        slots = max_positions - len(remaining_positions)
        for cand in _down_candidates():
            if slots <= 0:
                break
            sym = cand["symbol"]
            if sym in held:
                continue
            if sym in blocked_new:
                continue
            ret = float(cand.get("predicted_return_pct") or 0)
            conf = float(cand.get("confidence") or 0)
            # Need predicted drop of at least min_drop (ret is negative when bearish)
            if ret > -min_drop:
                continue
            if conf < min_conf:
                continue
            price = _quote_price(client, sym)
            if price <= 0:
                continue
            budget = min(max_trade, sleeve / max(1, max_positions))
            if budget < min_trade:
                continue
            qty = int(budget // price)
            if qty <= 0:
                continue
            orders.append(
                TradeOrder(
                    symbol=sym,
                    action="SELL_SHORT",
                    quantity=qty,
                    target_weight_pct=0.0,
                    current_weight_pct=0.0,
                    target_value_usd=qty * price,
                    current_value_usd=0.0,
                    estimated_price=price,
                    rationale=f"Day short: 24h {ret:.2f}% conf {conf:.2f} — {cand.get('rationale', '')}",
                )
            )
            remaining_positions.append(
                ShortDayPosition(
                    symbol=sym,
                    quantity=qty,
                    entry_price=price,
                    entry_at=datetime.now(timezone.utc).isoformat(),
                    take_profit_pct=take_profit,
                    stop_loss_pct=stop_loss,
                    rationale=str(cand.get("rationale") or "day short"),
                )
            )
            held.add(sym)
            slots -= 1

    state["positions"] = [p.to_dict() for p in remaining_positions]
    state["session_date"] = session
    save_short_day_state(state)

    plan = StrategyPlan(
        generated_at=datetime.now(timezone.utc).isoformat(),
        account_id_key=account_id_key,
        account_name=account_name,
        sandbox=bool(getattr(client.config, "sandbox", True)),
        total_account_value=total_value,
        investable_usd=sleeve,
        cash_buffer_pct=0.0,
        regime={},
        target_holdings=[],
        current_positions=[p.to_dict() for p in remaining_positions],
        orders=orders,
        meta={
            "mode": "short_day_trading",
            "side": "short",
            "sleeve": "short",
            "session_date": session,
            "shared_capital_budget": budget,
        },
    )
    try:
        from sleeve_policy import apply_sleeve_to_plan

        apply_sleeve_to_plan(plan, sleeve="short", positions=positions)
    except Exception:
        pass
    _write_json(SHORT_DAY_PLAN_FILE, plan.to_dict())
    return plan
