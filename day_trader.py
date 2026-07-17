"""Intraday day-trading layer — same growth goals, shorter holding period."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from etrade_api.client import ETradeClient
from strategy_engine import (
    DEFAULT_AGENT_CONTROLLED,
    DEFAULT_CASH_BUFFER_PCT,
    StrategyPlan,
    TradeOrder,
    _quote_price,
    load_strategy_settings,
    resolve_trade_thresholds,
    save_strategy_plan,
)

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
DAY_STATE_FILE = OUTPUT / "day_trade_state.json"
DAY_PLAN_FILE = OUTPUT / "day_trade_plan.json"
ET_TZ = ZoneInfo("America/New_York")

DEFAULT_DAY_TRADING = {
    "enabled": True,
    "interval_minutes": 5,
    "max_positions": 3,
    "capital_pct": 25.0,
    "min_daily_return_pct": 0.35,
    "min_confidence": 0.52,
    "take_profit_pct": 0.75,
    "stop_loss_pct": 0.5,
    "flatten_minutes_before_close": 15,
    "max_trade_usd": 750.0,
    "min_trade_usd": 75.0,
}


@dataclass
class DayPosition:
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
        }


def load_day_trade_settings(config_path: Path | None = None) -> dict[str, Any]:
    path = config_path or (ROOT / "etrade_config.json")
    settings = dict(DEFAULT_DAY_TRADING)
    if not path.exists():
        return settings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        user = raw.get("day_trading", {})
        if isinstance(user, dict):
            settings.update({k: user[k] for k in settings if k in user})
        worker = raw.get("background_worker", {})
        if "day_trading" in worker:
            settings["enabled"] = bool(worker["day_trading"])
    except (json.JSONDecodeError, OSError):
        pass
    return settings


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _session_date(now: datetime | None = None) -> str:
    now = now or datetime.now(ET_TZ)
    return now.strftime("%Y-%m-%d")


def minutes_to_market_close(now: datetime | None = None) -> float | None:
    now = now or datetime.now(ET_TZ)
    if now.weekday() >= 5:
        return None
    close = datetime.combine(now.date(), dt_time(16, 0), tzinfo=ET_TZ)
    if now >= close:
        return 0.0
    return (close - now).total_seconds() / 60.0


def is_day_trading_session(now: datetime | None = None) -> bool:
    """Regular US session with enough time to enter (after 9:45, before flatten window)."""
    now = now or datetime.now(ET_TZ)
    if now.weekday() >= 5:
        return False
    t = now.time()
    if t < dt_time(9, 45) or t >= dt_time(16, 0):
        return False
    return True


def load_day_state() -> dict[str, Any]:
    data = _load_json(DAY_STATE_FILE)
    today = _session_date()
    if data.get("session_date") != today:
        archived = data if data.get("positions") or data.get("closed_trades") else None
        if archived:
            _archive_session(archived)
        return {
            "session_date": today,
            "positions": [],
            "closed_trades": [],
            "stats": {"wins": 0, "losses": 0, "realized_pnl_usd": 0.0},
        }
    data.setdefault("positions", [])
    data.setdefault("closed_trades", [])
    data.setdefault("stats", {"wins": 0, "losses": 0, "realized_pnl_usd": 0.0})
    return data


def save_day_state(state: dict[str, Any]) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(DAY_STATE_FILE, state)


def _archive_session(data: dict[str, Any]) -> None:
    history_dir = OUTPUT / "history" / "day_trades"
    history_dir.mkdir(parents=True, exist_ok=True)
    stamp = data.get("session_date", "unknown")
    path = history_dir / f"session_{stamp}.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _daily_candidates(output_dir: Path | None = None) -> list[dict[str, Any]]:
    output_dir = output_dir or OUTPUT
    data = _load_json(output_dir / "market_predictions.json")
    rows = (data.get("predictions") or {}).get("24h", []) or []
    candidates = []
    for row in rows:
        direction = str(row.get("predicted_direction", "")).lower()
        if direction != "up":
            continue
        ret = float(row.get("predicted_return_pct", 0))
        conf = float(row.get("confidence", 0))
        candidates.append(
            {
                "symbol": str(row.get("symbol", "")).upper(),
                "predicted_return_pct": ret,
                "confidence": conf,
                "composite_score": float(row.get("composite_score", 0)),
                "rationale": row.get("rationale", "24h agent signal"),
                "rank": int(row.get("rank", 99)),
            }
        )
    candidates.sort(
        key=lambda r: (
            -r["predicted_return_pct"] * r["confidence"],
            -r["composite_score"],
            r["rank"],
        )
    )
    return candidates


def _agent_portfolio_candidates() -> list[dict[str, Any]]:
    """Day-trade entries from the agent-built portfolio (not system overlays)."""
    portfolio = _load_json(OUTPUT / "portfolio.json")
    holdings = portfolio.get("holdings", []) if isinstance(portfolio, dict) else []
    candidates: list[dict[str, Any]] = []
    for row in holdings:
        sym = str(row.get("symbol", "")).upper()
        if not sym:
            continue
        candidates.append(
            {
                "symbol": sym,
                "predicted_return_pct": float(row.get("projected_return_pct") or row.get("score") or 0),
                "confidence": float(row.get("confidence") or 0.75),
                "composite_score": float(row.get("score") or 0),
                "rationale": row.get("rationale", "Agent portfolio pick"),
                "order_type": row.get("order_type"),
                "limit_price": row.get("limit_price"),
                "order_type_reason": row.get("order_type_reason"),
                "order_type_sources": row.get("order_type_sources"),
                "rank": len(candidates) + 1,
            }
        )
    return candidates


def _position_objects(state: dict[str, Any]) -> list[DayPosition]:
    out: list[DayPosition] = []
    for raw in state.get("positions", []):
        if not raw.get("symbol"):
            continue
        out.append(
            DayPosition(
                symbol=str(raw["symbol"]).upper(),
                quantity=int(raw.get("quantity", 0)),
                entry_price=float(raw.get("entry_price", 0)),
                entry_at=str(raw.get("entry_at", "")),
                take_profit_pct=float(raw.get("take_profit_pct", DEFAULT_DAY_TRADING["take_profit_pct"])),
                stop_loss_pct=float(raw.get("stop_loss_pct", DEFAULT_DAY_TRADING["stop_loss_pct"])),
                rationale=str(raw.get("rationale", "")),
            )
        )
    return out


def _daily_signal(symbol: str, output_dir: Path | None = None) -> dict[str, Any] | None:
    output_dir = output_dir or OUTPUT
    data = _load_json(output_dir / "market_predictions.json")
    sym = symbol.upper()
    for row in (data.get("predictions") or {}).get("24h", []) or []:
        if str(row.get("symbol", "")).upper() == sym:
            return row
    return None


def build_day_trade_plan(
    client: ETradeClient,
    account_id_key: str,
    account_name: str = "",
    *,
    settings: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
) -> StrategyPlan:
    """Build intraday buy/sell orders from 24h signals and open day positions."""
    settings = settings or load_day_trade_settings()
    state = state if state is not None else load_day_state()
    strategy = load_strategy_settings()
    agent_controlled = bool(strategy.get("agent_controlled", DEFAULT_AGENT_CONTROLLED))

    balance = client.get_balance(account_id_key)
    positions = client.get_portfolio(account_id_key)
    total_value = balance.get("total_account_value") or 0.0
    buying_power = (
        balance.get("cash_buying_power")
        or balance.get("cash_available_for_investment")
        or balance.get("net_cash")
        or 0.0
    )
    if total_value <= 0:
        total_value = sum(float(p.get("market_value", 0)) for p in positions) + float(buying_power or 0)

    # Shared capital + long-only qty map (never treat shorts as sellable longs)
    try:
        from sleeve_policy import (
            blocked_symbols_for_new_entry,
            long_position_map,
            shared_capital_budget,
        )

        long_map = long_position_map(positions)
        pos_qty = {
            sym: int(float(p.get("quantity") or 0)) for sym, p in long_map.items()
        }
        blocked_new = blocked_symbols_for_new_entry("long", positions)
        budget = shared_capital_budget(float(total_value), sleeve="long", balance=balance)
        shared_deploy = float(budget.get("deployable_usd") or 0)
        sleeve_ceiling = float(budget.get("sleeve_ceiling_usd") or shared_deploy or 0)
        long_mv = sum(float(p.get("market_value") or 0) for p in long_map.values())
        # Remaining room under the buy-app capital cap (USD or %)
        capital_headroom = max(0.0, sleeve_ceiling - long_mv) if sleeve_ceiling > 0 else 0.0
        if shared_deploy > 0:
            buying_power = min(float(buying_power or shared_deploy), shared_deploy)
        if capital_headroom > 0 or sleeve_ceiling > 0:
            buying_power = min(float(buying_power or 0), capital_headroom)
    except Exception:
        pos_qty = {
            str(p.get("symbol", "")).upper(): int(float(p.get("quantity") or 0))
            for p in positions
            if str(p.get("position_type") or "LONG").upper() != "SHORT"
            and float(p.get("quantity") or 0) > 0
        }
        blocked_new = set()
        budget = {}

    candidates = _agent_portfolio_candidates() if agent_controlled else _daily_candidates()
    if agent_controlled and not candidates:
        candidates = _daily_candidates()
    day_positions = _position_objects(state)
    held_symbols = {p.symbol for p in day_positions}

    orders: list[TradeOrder] = []
    minutes_left = minutes_to_market_close()
    flatten_window = float(settings.get("flatten_minutes_before_close", 15))
    should_flatten = minutes_left is not None and minutes_left <= flatten_window

    take_profit = float(settings.get("take_profit_pct", DEFAULT_DAY_TRADING["take_profit_pct"]))
    stop_loss = float(settings.get("stop_loss_pct", DEFAULT_DAY_TRADING["stop_loss_pct"]))
    min_return = float(settings.get("min_daily_return_pct", DEFAULT_DAY_TRADING["min_daily_return_pct"]))
    min_conf = float(settings.get("min_confidence", DEFAULT_DAY_TRADING["min_confidence"]))

    for pos in day_positions:
        price = _quote_price(client, pos.symbol) or pos.entry_price
        if price <= 0:
            continue
        pnl_pct = (price - pos.entry_price) / pos.entry_price * 100 if pos.entry_price else 0.0
        signal = _daily_signal(pos.symbol)
        sell_reason = ""

        if should_flatten:
            sell_reason = f"Flatten before close ({int(minutes_left or 0)} min left)"
        elif pnl_pct >= pos.take_profit_pct:
            sell_reason = f"Take profit +{pnl_pct:.2f}%"
        elif pnl_pct <= -pos.stop_loss_pct:
            sell_reason = f"Stop loss {pnl_pct:.2f}%"
        elif signal and str(signal.get("predicted_direction", "")).lower() == "down":
            sell_reason = "24h signal turned bearish"
        elif signal and float(signal.get("predicted_return_pct", 0)) < min_return * 0.35:
            sell_reason = "24h upside faded"
        elif signal is None and pnl_pct < 0.15:
            sell_reason = "Dropped from 24h movers"

        if not sell_reason:
            continue

        qty = min(pos.quantity, pos_qty.get(pos.symbol, pos.quantity))
        if qty <= 0:
            continue
        exit_order = TradeOrder(
            symbol=pos.symbol,
            action="SELL",
            quantity=qty,
            target_weight_pct=0.0,
            current_weight_pct=0.0,
            target_value_usd=0.0,
            current_value_usd=qty * price,
            estimated_price=price,
            rationale=f"Day trade exit: {sell_reason}",
        )
        try:
            from order_type_selector import apply_to_trade_order, resolve_order_type

            decision = resolve_order_type(
                pos.symbol,
                "SELL",
                price=price,
                rationale=exit_order.rationale,
                horizon="24h",
            )
            apply_to_trade_order(exit_order, decision)
        except Exception:
            exit_order.price_type = "MARKET"
        orders.append(exit_order)

    if is_day_trading_session() and not should_flatten:
        max_positions = int(settings.get("max_positions", DEFAULT_DAY_TRADING["max_positions"]))
        open_slots = max(0, max_positions - len(day_positions) + len([o for o in orders if o.action == "SELL"]))
        capital_pct = float(settings.get("capital_pct", DEFAULT_DAY_TRADING["capital_pct"])) / 100.0
        day_budget = min(buying_power, total_value * capital_pct)
        max_trade = float(settings.get("max_trade_usd", DEFAULT_DAY_TRADING["max_trade_usd"]))
        min_trade = float(settings.get("min_trade_usd", DEFAULT_DAY_TRADING["min_trade_usd"]))
        _, budget_min_trade = resolve_trade_thresholds(strategy, investable=day_budget)
        entry_min_trade = min(min_trade, budget_min_trade) if agent_controlled else min_trade

        if open_slots > 0 and day_budget >= entry_min_trade:
            per_slot = min(max_trade, day_budget / open_slots)
            for cand in candidates:
                if open_slots <= 0:
                    break
                sym = cand["symbol"]
                if not sym or sym in held_symbols:
                    continue
                if sym in blocked_new:
                    continue
                if not agent_controlled and (
                    cand["predicted_return_pct"] < min_return or cand["confidence"] < min_conf
                ):
                    continue
                price = _quote_price(client, sym)
                if price <= 0:
                    continue
                _, order_min_trade = resolve_trade_thresholds(
                    strategy, investable=day_budget, price=price
                )
                effective_min_trade = min(min_trade, order_min_trade) if agent_controlled else min_trade
                trade_usd = max(effective_min_trade, min(per_slot, day_budget))
                qty = int(trade_usd // price)
                if qty <= 0 or qty * price < effective_min_trade:
                    continue
                entry_order = TradeOrder(
                    symbol=sym,
                    action="BUY",
                    quantity=qty,
                    target_weight_pct=0.0,
                    current_weight_pct=0.0,
                    target_value_usd=qty * price,
                    current_value_usd=0.0,
                    estimated_price=price,
                    rationale=(
                        f"Day trade entry: 24h +{cand['predicted_return_pct']:.2f}% "
                        f"(conf {cand['confidence']:.2f}) — {cand['rationale']}"
                    ),
                )
                try:
                    from order_type_selector import apply_to_trade_order, resolve_order_type

                    holding = {
                        "order_type": cand.get("order_type"),
                        "limit_price": cand.get("limit_price"),
                        "confidence": cand.get("confidence"),
                        "order_type_reason": cand.get("order_type_reason"),
                        "order_type_sources": cand.get("order_type_sources"),
                    }
                    decision = resolve_order_type(
                        sym,
                        "BUY",
                        price=price,
                        rationale=entry_order.rationale,
                        horizon="24h",
                        confidence=float(cand.get("confidence", 0.55)),
                        holding=holding,
                    )
                    apply_to_trade_order(entry_order, decision)
                except Exception:
                    entry_order.price_type = "MARKET"
                orders.append(entry_order)
                held_symbols.add(sym)
                day_budget -= qty * price
                open_slots -= 1

    cash_buffer = float(strategy.get("cash_buffer_pct", DEFAULT_CASH_BUFFER_PCT))
    investable = total_value * (1 - cash_buffer / 100)
    try:
        ceiling = float((budget or {}).get("sleeve_ceiling_usd") or 0)
        if ceiling > 0:
            investable = min(investable, ceiling)
        if budget:
            meta_budget = budget
        else:
            meta_budget = {}
    except Exception:
        meta_budget = {}
    meta = {
        "mode": "day_trading",
        "sleeve": "long",
        "objective": "grow_account_value_intraday",
        "session_date": state.get("session_date"),
        "open_day_positions": len(day_positions),
        "candidates_scanned": len(candidates),
        "flatten_before_close": should_flatten,
        "minutes_to_close": minutes_left,
    }
    if meta_budget:
        meta["shared_capital_budget"] = meta_budget

    plan = StrategyPlan(
        generated_at=datetime.now(timezone.utc).isoformat(),
        account_id_key=account_id_key,
        account_name=account_name,
        sandbox=client.config.sandbox,
        total_account_value=total_value,
        investable_usd=investable,
        cash_buffer_pct=cash_buffer,
        regime={"session": "day_trading", "market_open": is_day_trading_session()},
        target_holdings=[],
        current_positions=[
            {"symbol": s, "quantity": q, "position_type": "LONG"} for s, q in pos_qty.items()
        ],
        orders=orders,
        meta=meta,
    )
    try:
        from sleeve_policy import apply_sleeve_to_plan

        apply_sleeve_to_plan(plan, sleeve="long", positions=positions)
    except Exception:
        pass
    try:
        from trade_guards import apply_trade_guards_to_plan

        apply_trade_guards_to_plan(plan, balance, day_state=state)
    except Exception:
        pass
    save_strategy_plan(plan, DAY_PLAN_FILE)
    return plan


def apply_day_trade_executions(
    plan: StrategyPlan,
    *,
    state: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Update day-trade state after orders are placed."""
    settings = settings or load_day_trade_settings()
    state = state if state is not None else load_day_state()
    positions = _position_objects(state)
    by_symbol = {p.symbol: p for p in positions}
    take_profit = float(settings.get("take_profit_pct", DEFAULT_DAY_TRADING["take_profit_pct"]))
    stop_loss = float(settings.get("stop_loss_pct", DEFAULT_DAY_TRADING["stop_loss_pct"]))
    stats = state.setdefault("stats", {"wins": 0, "losses": 0, "realized_pnl_usd": 0.0})

    for order in plan.orders:
        if order.status not in {"placed", "dry_run"}:
            continue
        sym = order.symbol.upper()
        if order.action == "BUY":
            by_symbol[sym] = DayPosition(
                symbol=sym,
                quantity=order.quantity,
                entry_price=order.estimated_price,
                entry_at=datetime.now(timezone.utc).isoformat(),
                take_profit_pct=take_profit,
                stop_loss_pct=stop_loss,
                rationale=order.rationale,
            )
        elif order.action == "SELL" and sym in by_symbol:
            entry = by_symbol[sym]
            pnl = (order.estimated_price - entry.entry_price) * order.quantity
            stats["realized_pnl_usd"] = round(float(stats.get("realized_pnl_usd", 0)) + pnl, 2)
            if pnl >= 0:
                stats["wins"] = int(stats.get("wins", 0)) + 1
            else:
                stats["losses"] = int(stats.get("losses", 0)) + 1
            closed_row = {
                "symbol": sym,
                "quantity": order.quantity,
                "entry_price": entry.entry_price,
                "exit_price": order.estimated_price,
                "pnl_usd": round(pnl, 2),
                "closed_at": datetime.now(timezone.utc).isoformat(),
                "rationale": order.rationale,
            }
            state.setdefault("closed_trades", []).append(closed_row)
            remaining = entry.quantity - order.quantity
            if remaining > 0:
                by_symbol[sym] = DayPosition(
                    symbol=sym,
                    quantity=remaining,
                    entry_price=entry.entry_price,
                    entry_at=entry.entry_at,
                    take_profit_pct=entry.take_profit_pct,
                    stop_loss_pct=entry.stop_loss_pct,
                    rationale=entry.rationale,
                )
            else:
                del by_symbol[sym]

    state["positions"] = [p.to_dict() for p in by_symbol.values()]
    save_day_state(state)
    try:
        from analysis_history import record_day_trade_session

        record_day_trade_session(state)
    except Exception:
        pass
    return state