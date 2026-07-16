#!/usr/bin/env python3
"""Short-book strategy: SELL_SHORT targets, BUY_TO_COVER trims/exits, protective covers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from etrade_api.client import ETradeClient
from short_paths import SHORT_PLAN_FILE, ensure_short_dirs
from short_portfolio import generate_short_portfolio, load_short_strategy_settings, save_short_portfolio
from strategy_engine import StrategyPlan, TradeOrder, _quote_price

PLAN_FILE = SHORT_PLAN_FILE


def _short_positions(positions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map symbol -> short position (absolute quantity)."""
    out: dict[str, dict[str, Any]] = {}
    for pos in positions:
        sym = str(pos.get("symbol", "")).upper()
        if not sym:
            continue
        ptype = str(pos.get("position_type") or "LONG").upper()
        qty = float(pos.get("quantity") or 0)
        # SHORT type or negative quantity
        if ptype == "SHORT" or qty < 0:
            abs_qty = int(abs(qty))
            if abs_qty <= 0:
                continue
            mv = float(pos.get("market_value") or 0)
            out[sym] = {
                "symbol": sym,
                "quantity": abs_qty,
                "market_value": abs(mv),
                "price": float(pos.get("price") or 0),
                "cost_basis": float(pos.get("cost_basis") or 0),
                "position_type": "SHORT",
            }
    return out


def build_short_strategy_plan(
    client: ETradeClient,
    account_id_key: str,
    account_name: str = "",
    *,
    portfolio: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> StrategyPlan:
    """Rebalance short book toward agent bearish targets."""
    ensure_short_dirs()
    settings = settings or load_short_strategy_settings()
    balance = client.get_balance(account_id_key)
    positions = client.get_portfolio(account_id_key)
    short_map = _short_positions(positions)

    total_value = float(balance.get("total_account_value") or 0)
    if total_value <= 0:
        total_value = sum(abs(float(p.get("market_value") or 0)) for p in positions)
        total_value += float(
            balance.get("cash_available_for_investment")
            or balance.get("net_cash")
            or 0
        )
    if total_value <= 0:
        raise ValueError("Could not determine account value for short plan.")

    cash_buffer = float(settings.get("cash_buffer_pct", 20.0))
    max_book_pct = float(settings.get("max_short_book_pct", 40.0))
    investable = total_value * (1 - cash_buffer / 100) * (max_book_pct / 100)
    min_drift = float(settings.get("min_drift_pct", 2.0))
    min_trade = float(settings.get("min_trade_usd", 75.0))

    if portfolio is None:
        portfolio = generate_short_portfolio(notional_usd=total_value, settings=settings)
        save_short_portfolio(portfolio)

    targets = portfolio.get("holdings") or []
    target_by_sym = {str(h["symbol"]).upper(): h for h in targets if h.get("symbol")}
    symbols = set(target_by_sym) | set(short_map)

    prices: dict[str, float] = {}
    for sym in sorted(symbols):
        if sym in short_map and short_map[sym].get("price"):
            prices[sym] = float(short_map[sym]["price"])
        else:
            px = _quote_price(client, sym)
            if px > 0:
                prices[sym] = px

    orders: list[TradeOrder] = []
    handled: set[str] = set()

    for sym, holding in target_by_sym.items():
        handled.add(sym)
        weight = float(holding.get("weight_pct") or 0)
        target_value = investable * weight / 100 if investable else 0
        current = short_map.get(sym, {})
        current_qty = int(current.get("quantity") or 0)
        current_value = float(current.get("market_value") or 0)
        if current_value <= 0 and current_qty and prices.get(sym):
            current_value = current_qty * prices[sym]
        price = prices.get(sym) or float(holding.get("price") or 0)
        if price <= 0:
            continue
        current_weight = (current_value / total_value * 100) if total_value else 0
        drift = abs(target_value - current_value) / investable * 100 if investable else 0
        if drift < min_drift:
            continue
        delta = target_value - current_value
        if abs(delta) < min_trade:
            continue
        if delta > 0:
            qty = int(delta // price)
            action = "SELL_SHORT"
            rationale = holding.get("rationale") or "Open/add short from bearish agents"
        else:
            qty = min(current_qty, int(abs(delta) // price))
            action = "BUY_TO_COVER"
            rationale = holding.get("rationale") or "Reduce short toward target"
        if qty <= 0:
            continue
        orders.append(
            TradeOrder(
                symbol=sym,
                action=action,
                quantity=qty,
                target_weight_pct=weight,
                current_weight_pct=current_weight,
                target_value_usd=target_value,
                current_value_usd=current_value,
                estimated_price=price,
                rationale=str(rationale),
            )
        )

    # Cover shorts no longer in the target book
    for sym, pos in short_map.items():
        if sym in handled:
            continue
        qty = int(pos.get("quantity") or 0)
        price = prices.get(sym) or float(pos.get("price") or 0)
        if qty <= 0 or price <= 0:
            continue
        value = qty * price
        if value < min_trade:
            continue
        orders.append(
            TradeOrder(
                symbol=sym,
                action="BUY_TO_COVER",
                quantity=qty,
                target_weight_pct=0.0,
                current_weight_pct=(value / total_value * 100) if total_value else 0,
                target_value_usd=0.0,
                current_value_usd=value,
                estimated_price=price,
                rationale="Cover short not in agent short book",
            )
        )

    # Optional stop/target cover injects based on cost basis
    if settings.get("use_stop_orders", True):
        stop_pct = float(settings.get("stop_loss_pct", 6.0))
        tp_pct = float(settings.get("take_profit_pct", 10.0))
        for sym, pos in short_map.items():
            entry = float(pos.get("cost_basis") or 0)
            price = prices.get(sym) or float(pos.get("price") or 0)
            qty = int(pos.get("quantity") or 0)
            if entry <= 0 or price <= 0 or qty <= 0:
                continue
            # Short P&L: profit when price falls
            pnl_pct = (entry - price) / entry * 100
            if pnl_pct <= -stop_pct:
                orders.append(
                    TradeOrder(
                        symbol=sym,
                        action="BUY_TO_COVER",
                        quantity=qty,
                        target_weight_pct=0.0,
                        current_weight_pct=0.0,
                        target_value_usd=0.0,
                        current_value_usd=qty * price,
                        estimated_price=price,
                        rationale=f"Short stop-loss hit ({pnl_pct:.2f}% vs entry)",
                    )
                )
            elif pnl_pct >= tp_pct:
                orders.append(
                    TradeOrder(
                        symbol=sym,
                        action="BUY_TO_COVER",
                        quantity=qty,
                        target_weight_pct=0.0,
                        current_weight_pct=0.0,
                        target_value_usd=0.0,
                        current_value_usd=qty * price,
                        estimated_price=price,
                        rationale=f"Short take-profit hit (+{pnl_pct:.2f}%)",
                    )
                )

    # Prioritize covers before new shorts
    covers = [o for o in orders if o.action == "BUY_TO_COVER"]
    shorts = [o for o in orders if o.action == "SELL_SHORT"]
    other = [o for o in orders if o.action not in {"BUY_TO_COVER", "SELL_SHORT"}]
    orders = covers + shorts + other

    plan = StrategyPlan(
        generated_at=datetime.now(timezone.utc).isoformat(),
        account_id_key=account_id_key,
        account_name=account_name,
        sandbox=bool(getattr(client.config, "sandbox", True)),
        total_account_value=total_value,
        investable_usd=investable,
        cash_buffer_pct=cash_buffer,
        regime=portfolio.get("regime") or {},
        target_holdings=targets,
        current_positions=list(short_map.values()),
        orders=orders,
        meta={
            "mode": "short_swing",
            "side": "short",
            "max_short_book_pct": max_book_pct,
            "margin_buying_power": balance.get("margin_buying_power"),
            "cash_buying_power": balance.get("cash_buying_power"),
        },
    )
    return plan


def save_short_strategy_plan(plan: StrategyPlan, path: Path | None = None) -> Path:
    ensure_short_dirs()
    path = path or SHORT_PLAN_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")
    return path


def load_short_strategy_plan(path: Path | None = None) -> dict[str, Any] | None:
    path = path or SHORT_PLAN_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _place_short_protective_orders(
    client: ETradeClient,
    plan: StrategyPlan,
    short_order: TradeOrder,
    settings: dict[str, Any],
) -> None:
    """After SELL_SHORT fill: GTC stop BUY_TO_COVER (stop-loss) + limit BUY_TO_COVER (target)."""
    if not settings.get("place_protective_orders", True):
        return
    entry = float(short_order.estimated_price or 0)
    qty = int(short_order.quantity)
    if entry <= 0 or qty <= 0:
        return
    stop_pct = float(settings.get("stop_loss_pct", 6.0))
    tp_pct = float(settings.get("take_profit_pct", 10.0))
    # Short stop: price rises
    stop_px = round(entry * (1 + stop_pct / 100), 2)
    # Short target: price falls
    target_px = round(entry * (1 - tp_pct / 100), 2)
    try:
        stop_body = client.build_equity_order(
            short_order.symbol,
            qty,
            "BUY_TO_COVER",
            price_type="STOP",
            order_term="GOOD_UNTIL_CANCEL",
            stop_price=stop_px,
        )
        preview = client.preview_equity_order(plan.account_id_key, stop_body)
        preview_ids = (preview.get("PreviewOrderResponse") or preview).get("PreviewIds") or []
        preview_id = None
        if isinstance(preview_ids, list) and preview_ids:
            preview_id = preview_ids[0].get("previewId")
        if preview_id:
            client.place_equity_order(plan.account_id_key, stop_body, int(preview_id))
    except Exception:
        pass
    try:
        target_body = client.build_equity_order(
            short_order.symbol,
            qty,
            "BUY_TO_COVER",
            price_type="LIMIT",
            order_term="GOOD_UNTIL_CANCEL",
            limit_price=target_px,
        )
        preview = client.preview_equity_order(plan.account_id_key, target_body)
        preview_ids = (preview.get("PreviewOrderResponse") or preview).get("PreviewIds") or []
        preview_id = None
        if isinstance(preview_ids, list) and preview_ids:
            preview_id = preview_ids[0].get("previewId")
        if preview_id:
            client.place_equity_order(plan.account_id_key, target_body, int(preview_id))
    except Exception:
        pass


def execute_short_orders(
    client: ETradeClient,
    plan: StrategyPlan,
    *,
    dry_run: bool = True,
    settings: dict[str, Any] | None = None,
) -> StrategyPlan:
    """Preview/place short-book orders. Defaults to dry_run for safety."""
    from strategy_engine import execute_orders, preview_orders

    settings = settings or load_short_strategy_settings()
    if dry_run:
        return preview_orders(client, plan)

    result = execute_orders(client, plan, dry_run=False)
    for order in result.orders:
        if order.status in {"placed", "filled", "submitted"} and order.action == "SELL_SHORT":
            try:
                _place_short_protective_orders(client, result, order, settings)
            except Exception:
                pass
    try:
        _append_short_trade_log(result, dry_run=False)
    except Exception:
        pass
    return result


def preview_short_orders(client: ETradeClient, plan: StrategyPlan) -> StrategyPlan:
    from strategy_engine import preview_orders

    return preview_orders(client, plan)


def _append_short_trade_log(plan: StrategyPlan, *, dry_run: bool) -> None:
    from short_paths import SHORT_TRADE_HISTORY, ensure_short_dirs

    ensure_short_dirs()
    path = SHORT_TRADE_HISTORY
    rows: list[dict[str, Any]] = []
    if path.exists():
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(rows, list):
                rows = []
        except (json.JSONDecodeError, OSError):
            rows = []
    now = datetime.now(timezone.utc).isoformat()
    for order in plan.orders:
        if order.status in {"error", "blocked", "skipped"}:
            continue
        if dry_run and order.status not in {"previewed", "proposed"}:
            continue
        rows.append(
            {
                "at": now,
                "symbol": order.symbol,
                "action": order.action,
                "quantity": order.quantity,
                "price": order.estimated_price,
                "status": order.status,
                "message": order.message,
                "rationale": order.rationale,
                "mode": "short",
                "dry_run": dry_run,
            }
        )
    path.write_text(json.dumps(rows[-2000:], indent=2), encoding="utf-8")
