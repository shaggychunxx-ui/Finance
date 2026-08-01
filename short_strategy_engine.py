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
    """Map symbol -> short position (absolute quantity). Longs never included."""
    try:
        from sleeve_policy import short_position_map

        return short_position_map(positions)
    except Exception:
        out: dict[str, dict[str, Any]] = {}
        for pos in positions:
            sym = str(pos.get("symbol", "")).upper()
            if not sym:
                continue
            ptype = str(pos.get("position_type") or "LONG").upper()
            qty = float(pos.get("quantity") or 0)
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
    """Rebalance short book toward agent bearish targets (short sleeve only)."""
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

    # Shared capital + joint profit coordination with long sleeve
    try:
        from sleeve_coordinator import coordinate_sleeves
        from sleeve_policy import (
            blocked_symbols_for_new_entry,
            save_sleeve_snapshot,
            shared_capital_budget,
        )

        coordinate_sleeves(total_account_value=total_value)
        budget = shared_capital_budget(
            total_value,
            sleeve="short",
            balance=balance,
            positions=positions,
        )
        # Size short book to shared-account sleeve ceiling (net of long exposure)
        investable = float(
            budget.get("sleeve_ceiling_usd") or budget.get("deployable_usd") or 0
        )
        blocked_new = blocked_symbols_for_new_entry("short", positions)
        save_sleeve_snapshot(positions=positions, total_account_value=total_value)
    except Exception:
        cash_buffer = float(settings.get("cash_buffer_pct", 20.0))
        max_book_pct = float(settings.get("max_short_book_pct", 40.0))
        investable = total_value * (1 - cash_buffer / 100) * (max_book_pct / 100)
        blocked_new = set()
        budget = {}

    cash_buffer = float(settings.get("cash_buffer_pct", 20.0))
    max_book_pct = float(settings.get("max_short_book_pct", 40.0))
    # Honor short book % as additional soft cap on the shared pool
    investable = min(investable, total_value * (1 - cash_buffer / 100) * (max_book_pct / 100))
    min_drift = float(settings.get("min_drift_pct", 2.0))
    min_trade = float(settings.get("min_trade_usd", 75.0))
    # Practice / small-account: allow 1-share simulated shorts when capital can't size normally.
    force_min_share = bool(settings.get("force_min_share_dry_run") or settings.get("simulate_min_share"))

    if portfolio is None:
        portfolio = generate_short_portfolio(notional_usd=total_value, settings=settings)
        save_short_portfolio(portfolio)

    targets = portfolio.get("holdings") or []
    # Drop targets blocked by long sleeve positions/claims
    target_by_sym = {
        str(h["symbol"]).upper(): h
        for h in targets
        if h.get("symbol") and str(h["symbol"]).upper() not in blocked_new
    }
    symbols = set(target_by_sym) | set(short_map)

    prices: dict[str, float] = {}
    for sym in sorted(symbols):
        if sym in short_map and short_map[sym].get("price"):
            prices[sym] = float(short_map[sym]["price"])
        else:
            px = _quote_price(client, sym)
            if px > 0:
                prices[sym] = px
            elif force_min_share:
                # Yahoo fallback for practice simulation when E*TRADE quotes fail
                try:
                    import urllib.request

                    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1d&interval=1d"
                    req = urllib.request.Request(url, headers={"User-Agent": "FinanceShortDryRun/1.0"})
                    with urllib.request.urlopen(req, timeout=12) as resp:
                        payload = json.loads(resp.read().decode())
                    meta = (payload.get("chart") or {}).get("result") or []
                    if meta:
                        last = meta[0].get("meta", {}).get("regularMarketPrice") or meta[0].get("meta", {}).get(
                            "previousClose"
                        )
                        if last:
                            prices[sym] = float(last)
                except Exception:
                    pass

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
        if not force_min_share and drift < min_drift:
            continue
        delta = target_value - current_value
        if not force_min_share and abs(delta) < min_trade:
            continue
        if delta > 0 or (force_min_share and current_qty <= 0):
            qty = int(delta // price) if delta > 0 else 0
            if qty <= 0 and force_min_share and current_qty <= 0:
                qty = 1  # 1-share practice short
            action = "SELL_SHORT"
            rationale = holding.get("rationale") or "Open/add short from bearish agents"
            if force_min_share and qty == 1 and (delta // price if price else 0) < 1:
                rationale = f"[sim 1-share] {rationale}"
        else:
            qty = min(current_qty, int(abs(delta) // price)) if price else 0
            if qty <= 0 and force_min_share and current_qty > 0:
                qty = 1
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
                target_value_usd=target_value if target_value > 0 else qty * price,
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
        target_holdings=list(target_by_sym.values()),
        current_positions=list(short_map.values()),
        orders=orders,
        meta={
            "mode": "short_swing",
            "side": "short",
            "sleeve": "short",
            "max_short_book_pct": max_book_pct,
            "shared_capital_budget": budget,
            "margin_buying_power": balance.get("margin_buying_power"),
            "cash_buying_power": balance.get("cash_buying_power"),
        },
    )
    try:
        from sleeve_policy import apply_sleeve_to_plan

        apply_sleeve_to_plan(plan, sleeve="short", positions=positions)
    except Exception:
        pass
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
    """Preview/place short-book orders. Defaults to dry_run for safety.

    Dry-run marks fills as simulated, appends short trade history, and tracks
    simulated open short lots for later success-rate measurement.
    """
    from strategy_engine import execute_orders, preview_orders

    settings = settings or load_short_strategy_settings()
    if dry_run:
        # Prefer strategy_engine dry_run when available; else local simulate.
        try:
            result = execute_orders(client, plan, dry_run=True)
        except TypeError:
            result = preview_orders(client, plan)
        for order in result.orders:
            if order.status in {"error", "blocked", "skipped"}:
                continue
            if order.status in {"previewed", "proposed", "", None} or not order.status:
                order.status = "dry_run"
            if not order.message:
                order.message = "Simulated short fill (practice mode)"
        try:
            _append_short_trade_log(result, dry_run=True)
            _update_short_sim_book(result, dry_run=True)
        except Exception:
            pass
        return result

    result = execute_orders(client, plan, dry_run=False)
    for order in result.orders:
        if order.status in {"placed", "filled", "submitted"} and order.action == "SELL_SHORT":
            try:
                _place_short_protective_orders(client, result, order, settings)
            except Exception:
                pass
    try:
        _append_short_trade_log(result, dry_run=False)
        _update_short_sim_book(result, dry_run=False)
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
        # Accept dry_run / previewed / placed statuses for journaling
        if dry_run and order.status not in {"previewed", "proposed", "dry_run", "placed", "filled"}:
            # still log if quantity present (local sim)
            if not (order.quantity and order.symbol):
                continue
        rows.append(
            {
                "at": now,
                "symbol": order.symbol,
                "action": order.action,
                "quantity": order.quantity,
                "price": order.estimated_price,
                "value_usd": round(float(order.quantity or 0) * float(order.estimated_price or 0), 2),
                "status": order.status or ("dry_run" if dry_run else "placed"),
                "message": order.message,
                "rationale": order.rationale,
                "mode": "short",
                "dry_run": dry_run,
            }
        )
    path.write_text(json.dumps(rows[-2000:], indent=2), encoding="utf-8")


def _update_short_sim_book(plan: StrategyPlan, *, dry_run: bool) -> None:
    """Track simulated short lots + realized cover PnL for success-rate stats."""
    from short_paths import SHORT_OUTPUT, ensure_short_dirs

    ensure_short_dirs()
    path = SHORT_OUTPUT / "short_sim_book.json"
    store: dict[str, Any] = {"open_shorts": {}, "closed": [], "stats": {"wins": 0, "losses": 0, "flat": 0, "realized_pnl_usd": 0.0}}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                store.update(raw)
                store.setdefault("open_shorts", {})
                store.setdefault("closed", [])
                store.setdefault("stats", {"wins": 0, "losses": 0, "flat": 0, "realized_pnl_usd": 0.0})
        except (json.JSONDecodeError, OSError):
            pass

    open_shorts: dict[str, Any] = dict(store.get("open_shorts") or {})
    closed: list[dict[str, Any]] = list(store.get("closed") or [])
    stats: dict[str, Any] = dict(store.get("stats") or {})
    now = datetime.now(timezone.utc).isoformat()

    for order in plan.orders:
        if order.status in {"error", "blocked", "skipped"}:
            continue
        sym = str(order.symbol or "").upper()
        qty = int(order.quantity or 0)
        px = float(order.estimated_price or 0)
        if not sym or qty <= 0 or px <= 0:
            continue
        action = str(order.action or "").upper()
        if action == "SELL_SHORT":
            lot = open_shorts.get(sym) or {"symbol": sym, "quantity": 0, "avg_entry": 0.0, "entries": []}
            prev_q = int(lot.get("quantity") or 0)
            prev_avg = float(lot.get("avg_entry") or 0)
            new_q = prev_q + qty
            lot["avg_entry"] = ((prev_avg * prev_q) + (px * qty)) / new_q if new_q else px
            lot["quantity"] = new_q
            lot["last_price"] = px
            lot["updated_at"] = now
            lot["dry_run"] = dry_run
            entries = list(lot.get("entries") or [])
            entries.append({"at": now, "qty": qty, "price": px, "dry_run": dry_run})
            lot["entries"] = entries[-50:]
            open_shorts[sym] = lot
        elif action == "BUY_TO_COVER":
            lot = open_shorts.get(sym)
            if not lot:
                continue
            open_q = int(lot.get("quantity") or 0)
            entry = float(lot.get("avg_entry") or 0)
            take = min(open_q, qty)
            if take <= 0 or entry <= 0:
                continue
            # Short PnL: entry - exit
            pnl = (entry - px) * take
            closed.append(
                {
                    "at": now,
                    "symbol": sym,
                    "quantity": take,
                    "entry_price": entry,
                    "exit_price": px,
                    "realized_pnl_usd": round(pnl, 2),
                    "dry_run": dry_run,
                    "win": pnl > 0,
                }
            )
            if pnl > 0:
                stats["wins"] = int(stats.get("wins", 0)) + 1
            elif pnl < 0:
                stats["losses"] = int(stats.get("losses", 0)) + 1
            else:
                stats["flat"] = int(stats.get("flat", 0)) + 1
            stats["realized_pnl_usd"] = round(float(stats.get("realized_pnl_usd", 0)) + pnl, 2)
            left = open_q - take
            if left <= 0:
                open_shorts.pop(sym, None)
            else:
                lot["quantity"] = left
                lot["updated_at"] = now
                open_shorts[sym] = lot

    store["open_shorts"] = open_shorts
    store["closed"] = closed[-2000:]
    store["stats"] = stats
    store["updated_at"] = now
    path.write_text(json.dumps(store, indent=2), encoding="utf-8")
