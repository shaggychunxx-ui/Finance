"""Trade journal, P&L, performance attribution, and tax export."""

from __future__ import annotations

import csv
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app_paths import OUTPUT

HISTORY_FILE = OUTPUT / "history" / "trade_history.json"
MAX_TRADES = 5000

DEFAULT_SWING_STOPS = {
    "stop_loss_pct": 8.0,
    "take_profit_pct": 15.0,
    "use_stop_orders": True,
    "place_protective_orders": True,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def load_swing_stop_settings(config_path: Path | None = None) -> dict[str, Any]:
    settings = dict(DEFAULT_SWING_STOPS)
    path = config_path or (Path(__file__).resolve().parent / "etrade_config.json")
    if not path.exists():
        return settings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        block = raw.get("strategy", {})
        if isinstance(block, dict):
            for key in settings:
                if key in block:
                    settings[key] = block[key]
    except (json.JSONDecodeError, OSError):
        pass
    return settings


def _empty_store() -> dict[str, Any]:
    return {
        "trades": [],
        "open_lots": {},
        "stats": {
            "swing_realized_pnl_usd": 0.0,
            "day_realized_pnl_usd": 0.0,
            "total_realized_pnl_usd": 0.0,
            "wins": 0,
            "losses": 0,
        },
        "updated_at": _now_iso(),
    }


def load_trade_history() -> dict[str, Any]:
    data = _load_json(HISTORY_FILE)
    if not data:
        return _empty_store()
    data.setdefault("trades", [])
    data.setdefault("open_lots", {})
    data.setdefault("stats", _empty_store()["stats"])
    return data


def save_trade_history(data: dict[str, Any]) -> None:
    data["updated_at"] = _now_iso()
    trades = data.get("trades", [])
    if isinstance(trades, list) and len(trades) > MAX_TRADES:
        data["trades"] = trades[-MAX_TRADES:]
    _write_json(HISTORY_FILE, data)


def _holding_sources(plan: Any, symbol: str) -> list[str]:
    sym = symbol.upper()
    for holding in getattr(plan, "target_holdings", []) or []:
        if str(holding.get("symbol", "")).upper() == sym:
            sources = holding.get("sources") or []
            if isinstance(sources, list):
                return [str(s) for s in sources if s]
    return []


def compute_stop_target_prices(
    entry_price: float,
    *,
    settings: dict[str, Any] | None = None,
) -> tuple[float | None, float | None]:
    if entry_price <= 0:
        return None, None
    cfg = settings or load_swing_stop_settings()
    stop_pct = float(cfg.get("stop_loss_pct", DEFAULT_SWING_STOPS["stop_loss_pct"]))
    target_pct = float(cfg.get("take_profit_pct", DEFAULT_SWING_STOPS["take_profit_pct"]))
    stop = round(entry_price * (1.0 - stop_pct / 100.0), 2)
    target = round(entry_price * (1.0 + target_pct / 100.0), 2)
    return stop, target


def _update_stats(stats: dict[str, Any], pnl: float, *, mode: str) -> None:
    if pnl >= 0:
        stats["wins"] = int(stats.get("wins", 0)) + 1
    else:
        stats["losses"] = int(stats.get("losses", 0)) + 1
    key = "day_realized_pnl_usd" if mode == "day" else "swing_realized_pnl_usd"
    stats[key] = round(float(stats.get(key, 0)) + pnl, 2)
    stats["total_realized_pnl_usd"] = round(
        float(stats.get("swing_realized_pnl_usd", 0)) + float(stats.get("day_realized_pnl_usd", 0)),
        2,
    )


def _apply_sell_to_lots(
    store: dict[str, Any],
    *,
    symbol: str,
    quantity: int,
    exit_price: float,
    mode: str,
) -> float:
    """FIFO realized P&L for a sell. Returns total realized on this fill."""
    sym = symbol.upper()
    lots: list[dict[str, Any]] = list((store.get("open_lots") or {}).get(sym) or [])
    remaining = quantity
    realized = 0.0
    kept: list[dict[str, Any]] = []

    for lot in lots:
        if remaining <= 0:
            kept.append(lot)
            continue
        lot_qty = int(lot.get("quantity", 0))
        if lot_qty <= 0:
            continue
        take = min(remaining, lot_qty)
        entry = float(lot.get("entry_price", 0))
        realized += (exit_price - entry) * take
        remaining -= take
        left = lot_qty - take
        if left > 0:
            kept.append({**lot, "quantity": left})

    store.setdefault("open_lots", {})[sym] = kept
    if not kept:
        store["open_lots"].pop(sym, None)
    if realized != 0:
        _update_stats(store.setdefault("stats", {}), realized, mode=mode)
    return round(realized, 2)


def record_executed_orders(plan: Any, *, dry_run: bool = False) -> None:
    """Persist swing/day fills from a strategy plan after execute_orders."""
    mode = "day" if (getattr(plan, "meta", None) or {}).get("mode") == "day_trading" else "swing"
    store = load_trade_history()
    trades: list[dict[str, Any]] = store.setdefault("trades", [])
    stop_settings = load_swing_stop_settings()

    for order in getattr(plan, "orders", []) or []:
        if getattr(order, "status", "") not in {"placed", "dry_run"}:
            continue
        sym = str(getattr(order, "symbol", "")).upper()
        qty = int(getattr(order, "quantity", 0))
        price = float(getattr(order, "estimated_price", 0))
        action = str(getattr(order, "action", "")).upper()
        if not sym or qty <= 0 or price <= 0:
            continue

        sources = _holding_sources(plan, sym)
        trade_id = uuid.uuid4().hex[:12]
        stop_px, target_px = (None, None)
        realized: float | None = None

        if action == "BUY" and mode == "swing":
            stop_px, target_px = compute_stop_target_prices(price, settings=stop_settings)
            lots = store.setdefault("open_lots", {}).setdefault(sym, [])
            lots.append(
                {
                    "trade_id": trade_id,
                    "quantity": qty,
                    "entry_price": price,
                    "entry_at": _now_iso(),
                    "stop_loss_price": stop_px,
                    "take_profit_price": target_px,
                    "agent_sources": sources,
                }
            )
        elif action == "SELL":
            realized = _apply_sell_to_lots(
                store, symbol=sym, quantity=qty, exit_price=price, mode=mode,
            )

        trades.append(
            {
                "id": trade_id,
                "executed_at": _now_iso(),
                "symbol": sym,
                "action": action,
                "quantity": qty,
                "price": round(price, 4),
                "value_usd": round(price * qty, 2),
                "price_type": getattr(order, "price_type", "MARKET"),
                "limit_price": getattr(order, "limit_price", None),
                "mode": mode,
                "status": getattr(order, "status", "placed"),
                "dry_run": dry_run or getattr(order, "status", "") == "dry_run",
                "account_id_key": getattr(plan, "account_id_key", ""),
                "account_name": getattr(plan, "account_name", ""),
                "rationale": getattr(order, "rationale", ""),
                "agent_sources": sources,
                "stop_loss_price": stop_px,
                "take_profit_price": target_px,
                "realized_pnl_usd": realized,
            }
        )

    save_trade_history(store)


def record_day_closed_trade(row: dict[str, Any]) -> None:
    """Append a closed day-trade round-trip from day_trader state."""
    store = load_trade_history()
    sym = str(row.get("symbol", "")).upper()
    qty = int(row.get("quantity", 0))
    entry = float(row.get("entry_price", 0))
    exit_px = float(row.get("exit_price", 0))
    pnl = float(row.get("pnl_usd", (exit_px - entry) * qty))
    trade_id = uuid.uuid4().hex[:12]

    store.setdefault("trades", []).append(
        {
            "id": trade_id,
            "executed_at": row.get("closed_at") or _now_iso(),
            "symbol": sym,
            "action": "ROUND_TRIP",
            "quantity": qty,
            "price": exit_px,
            "entry_price": entry,
            "value_usd": round(exit_px * qty, 2),
            "price_type": "MARKET",
            "mode": "day",
            "status": "closed",
            "dry_run": False,
            "rationale": row.get("rationale", ""),
            "agent_sources": [],
            "realized_pnl_usd": round(pnl, 2),
        }
    )
    _apply_sell_to_lots(store, symbol=sym, quantity=qty, exit_price=exit_px, mode="day")
    save_trade_history(store)


def append_stop_target_exit_orders(
    orders: list[Any],
    *,
    pos_map: dict[str, dict[str, Any]],
    prices: dict[str, float],
    settings: dict[str, Any] | None = None,
    total_value: float,
) -> list[Any]:
    """Inject swing SELL orders when price hits stop-loss or take-profit levels."""
    from strategy_engine import TradeOrder

    cfg = settings or load_swing_stop_settings()
    if not cfg.get("use_stop_orders", True):
        return orders

    store = load_trade_history()
    open_lots: dict[str, list[dict[str, Any]]] = store.get("open_lots") or {}
    existing_sells = {
        str(getattr(o, "symbol", "")).upper()
        for o in orders
        if str(getattr(o, "action", "")).upper() == "SELL"
    }
    injected: list[Any] = []

    for sym, lots in open_lots.items():
        if sym in existing_sells:
            continue
        price = prices.get(sym) or float((pos_map.get(sym) or {}).get("price", 0))
        qty = int((pos_map.get(sym) or {}).get("quantity", 0))
        if price <= 0 or qty <= 0 or not lots:
            continue

        total_qty = sum(int(lot.get("quantity", 0)) for lot in lots)
        if total_qty <= 0:
            continue

        # Weighted average entry and combined stops from oldest lots.
        entry = sum(float(lot.get("entry_price", 0)) * int(lot.get("quantity", 0)) for lot in lots) / total_qty
        stop_px, target_px = compute_stop_target_prices(entry, settings=cfg)
        sources: list[str] = []
        for lot in lots:
            for src in lot.get("agent_sources") or []:
                if src not in sources:
                    sources.append(str(src))

        sell_qty = min(qty, total_qty)
        rationale = ""
        if stop_px is not None and price <= stop_px:
            rationale = f"Swing stop-loss @ ${stop_px:.2f} (entry ${entry:.2f})"
        elif target_px is not None and price >= target_px:
            rationale = f"Swing take-profit @ ${target_px:.2f} (entry ${entry:.2f})"
        else:
            continue

        current_value = float((pos_map.get(sym) or {}).get("market_value", price * sell_qty))
        current_weight = (current_value / total_value * 100) if total_value else 0
        order = TradeOrder(
            symbol=sym,
            action="SELL",
            quantity=sell_qty,
            target_weight_pct=0.0,
            current_weight_pct=current_weight,
            target_value_usd=0.0,
            current_value_usd=current_value,
            estimated_price=price,
            rationale=rationale,
            price_type="MARKET",
        )
        try:
            from order_type_selector import apply_to_trade_order, resolve_order_type

            decision = resolve_order_type(sym, "SELL", price=price, rationale=rationale, horizon="1wk")
            apply_to_trade_order(order, decision)
        except Exception:
            order.price_type = "MARKET"
        injected.append(order)

    if injected:
        return injected + orders
    return orders


def get_pnl_summary() -> dict[str, Any]:
    store = load_trade_history()
    stats = dict(store.get("stats") or {})
    trades = store.get("trades") or []
    closed = [t for t in trades if t.get("realized_pnl_usd") is not None]
    return {
        **stats,
        "trade_count": len(trades),
        "closed_count": len(closed),
        "open_lot_symbols": sorted((store.get("open_lots") or {}).keys()),
    }


def get_attribution_summary() -> list[dict[str, Any]]:
    """Aggregate realized P&L and trade count by agent source."""
    store = load_trade_history()
    by_source: dict[str, dict[str, Any]] = {}

    for trade in store.get("trades") or []:
        pnl = trade.get("realized_pnl_usd")
        sources = trade.get("agent_sources") or []
        if not sources:
            sources = ["unattributed"]
        for src in sources:
            row = by_source.setdefault(
                str(src),
                {"source": str(src), "trades": 0, "realized_pnl_usd": 0.0, "wins": 0, "losses": 0},
            )
            row["trades"] += 1
            if pnl is not None:
                row["realized_pnl_usd"] = round(float(row["realized_pnl_usd"]) + float(pnl), 2)
                if float(pnl) >= 0:
                    row["wins"] += 1
                else:
                    row["losses"] += 1

    ranked = sorted(by_source.values(), key=lambda r: float(r.get("realized_pnl_usd", 0)), reverse=True)
    for row in ranked:
        total = int(row.get("wins", 0)) + int(row.get("losses", 0))
        row["win_rate_pct"] = round(100.0 * int(row.get("wins", 0)) / total, 1) if total else None
    return ranked


def export_trades_csv(path: Path | str) -> int:
    """Write tax-friendly trade log CSV. Returns row count."""
    store = load_trade_history()
    trades = list(store.get("trades") or [])
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    fields = [
        "executed_at",
        "symbol",
        "action",
        "quantity",
        "price",
        "value_usd",
        "entry_price",
        "realized_pnl_usd",
        "price_type",
        "limit_price",
        "mode",
        "status",
        "dry_run",
        "account_name",
        "agent_sources",
        "rationale",
        "stop_loss_price",
        "take_profit_price",
        "trade_id",
    ]
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for trade in trades:
            row = dict(trade)
            row["trade_id"] = trade.get("id", "")
            row["agent_sources"] = ";".join(trade.get("agent_sources") or [])
            writer.writerow(row)
    return len(trades)