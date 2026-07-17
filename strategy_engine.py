#!/usr/bin/env python3
"""Apply Finance agent portfolio strategies to an E*TRADE account."""

from __future__ import annotations

import json
import os
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from etrade_api.client import ETradeClient
from etrade_api.config import ETradeConfig, load_config
from app_paths import OUTPUT, ROOT
from portfolio_generator import generate_portfolio, save_portfolio
PORTFOLIO_FILE = OUTPUT / "portfolio.json"
PLAN_FILE = OUTPUT / "strategy_plan.json"

DEFAULT_CASH_BUFFER_PCT = 5.0
DEFAULT_MIN_DRIFT_PCT = 1.5
DEFAULT_MIN_TRADE_USD = 50.0
DEFAULT_GROWTH_MODE = True
DEFAULT_PRIORITIZE_BUYS = True
DEFAULT_OPTIMIZE_PROFIT_HORIZONS = True
DEFAULT_AGENT_CONTROLLED = True
DEFAULT_SMALL_ACCOUNT_THRESHOLD_USD = 500.0
DEFAULT_SMALL_ACCOUNT_MAX_HOLDINGS = 6
DEFAULT_SMALL_ACCOUNT_MIN_HOLDINGS = 3
DEFAULT_PREFER_AFFORDABLE_TICKERS = True
AGENT_RUN_TIMEOUT_SEC = max(60, int(os.environ.get("FINANCE_AGENT_TIMEOUT_SEC", "180")))
ETRADE_ENHANCE_TIMEOUT_SEC = max(60, int(os.environ.get("FINANCE_ETRADE_ENHANCE_TIMEOUT_SEC", "120")))
BENCHMARK_TIMEOUT_SEC = max(120, int(os.environ.get("FINANCE_BENCHMARK_TIMEOUT_SEC", "900")))


@dataclass
class TradeOrder:
    symbol: str
    action: str
    quantity: int
    target_weight_pct: float
    current_weight_pct: float
    target_value_usd: float
    current_value_usd: float
    estimated_price: float
    rationale: str = ""
    price_type: str = "MARKET"
    limit_price: float | None = None
    stop_price: float | None = None
    order_term: str = ""
    preview_id: int | None = None
    status: str = "proposed"
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "symbol": self.symbol,
            "action": self.action,
            "quantity": self.quantity,
            "target_weight_pct": round(self.target_weight_pct, 2),
            "current_weight_pct": round(self.current_weight_pct, 2),
            "target_value_usd": round(self.target_value_usd, 2),
            "current_value_usd": round(self.current_value_usd, 2),
            "estimated_price": round(self.estimated_price, 4),
            "price_type": self.price_type,
            "rationale": self.rationale,
            "preview_id": self.preview_id,
            "status": self.status,
            "message": self.message,
        }
        if self.limit_price is not None:
            payload["limit_price"] = round(self.limit_price, 2)
        if self.stop_price is not None:
            payload["stop_price"] = round(self.stop_price, 2)
        if self.order_term:
            payload["order_term"] = self.order_term
        return payload


@dataclass
class StrategyPlan:
    generated_at: str
    account_id_key: str
    account_name: str
    sandbox: bool
    total_account_value: float
    investable_usd: float
    cash_buffer_pct: float
    regime: dict[str, Any]
    target_holdings: list[dict[str, Any]]
    current_positions: list[dict[str, Any]]
    orders: list[TradeOrder] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "account_id_key": self.account_id_key,
            "account_name": self.account_name,
            "sandbox": self.sandbox,
            "total_account_value": round(self.total_account_value, 2),
            "investable_usd": round(self.investable_usd, 2),
            "cash_buffer_pct": self.cash_buffer_pct,
            "regime": self.regime,
            "target_holdings": self.target_holdings,
            "current_positions": self.current_positions,
            "orders": [o.to_dict() for o in self.orders],
            "meta": self.meta,
        }


def _quote_price(client: ETradeClient, symbol: str) -> float:
    try:
        payload = client.get_quotes(symbol)
        response = payload.get("QuoteResponse", payload)
        data = response.get("QuoteData")
        if isinstance(data, list):
            quote = data[0] if data else {}
        else:
            quote = data or {}
        product = quote.get("Product", {}) or {}
        all_data = quote.get("All", {}) or {}
        price = (
            all_data.get("lastTrade")
            or quote.get("lastTrade")
            or all_data.get("ask")
            or all_data.get("bid")
        )
        if price:
            return float(price)
        if product.get("symbol"):
            return 0.0
    except Exception:
        pass
    return 0.0


def load_strategy_settings(config_path: Path | None = None) -> dict[str, Any]:
    path = config_path or (ROOT / "etrade_config.json")
    settings = {
        "cash_buffer_pct": DEFAULT_CASH_BUFFER_PCT,
        "min_drift_pct": DEFAULT_MIN_DRIFT_PCT,
        "min_trade_usd": DEFAULT_MIN_TRADE_USD,
        "growth_mode": DEFAULT_GROWTH_MODE,
        "prioritize_buys": DEFAULT_PRIORITIZE_BUYS,
        "optimize_profit_horizons": DEFAULT_OPTIMIZE_PROFIT_HORIZONS,
        "agent_controlled": DEFAULT_AGENT_CONTROLLED,
        "prefer_affordable_tickers": DEFAULT_PREFER_AFFORDABLE_TICKERS,
        "small_account_threshold_usd": DEFAULT_SMALL_ACCOUNT_THRESHOLD_USD,
        "small_account_max_holdings": DEFAULT_SMALL_ACCOUNT_MAX_HOLDINGS,
        "small_account_min_holdings": DEFAULT_SMALL_ACCOUNT_MIN_HOLDINGS,
        "min_buy_return_pct": 0.05,
        "min_sell_return_pct": -0.10,
        "max_deploy_pct": 0.94,
        "trading_gate": {},
        "domain_constraints": {},
        "temperature_control": {},
    }
    if not path.exists():
        try:
            from trading_gate import load_trading_gate_settings

            settings["trading_gate"] = load_trading_gate_settings(path)
        except Exception:
            pass
        try:
            from agent_constraints import load_domain_constraint_settings

            settings["domain_constraints"] = load_domain_constraint_settings(path)
        except Exception:
            pass
        try:
            from agent_temperature import load_temperature_settings

            settings["temperature_control"] = load_temperature_settings(path)
        except Exception:
            pass
        return settings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        user = raw.get("strategy", {})
        settings.update({k: user[k] for k in settings if k in user})
        try:
            from trading_gate import load_trading_gate_settings

            settings["trading_gate"] = load_trading_gate_settings(path)
        except Exception:
            pass
        try:
            from agent_constraints import load_domain_constraint_settings

            settings["domain_constraints"] = load_domain_constraint_settings(path)
        except Exception:
            pass
        try:
            from agent_temperature import load_temperature_settings

            settings["temperature_control"] = load_temperature_settings(path)
        except Exception:
            pass
        if user.get("agent_controlled"):
            settings["optimize_profit_horizons"] = False
    except (json.JSONDecodeError, OSError):
        pass
    return settings


def resolve_trade_thresholds(
    settings: dict[str, Any],
    *,
    investable: float,
    price: float = 0.0,
) -> tuple[float, float]:
    """Return (min_drift_pct, min_trade_usd) for the current account and order."""
    min_drift = float(settings.get("min_drift_pct", DEFAULT_MIN_DRIFT_PCT))
    min_trade = float(settings.get("min_trade_usd", DEFAULT_MIN_TRADE_USD))
    if not settings.get("agent_controlled", DEFAULT_AGENT_CONTROLLED):
        return min_drift, min_trade

    min_drift = min(min_drift, 0.25)
    if price > 0:
        min_trade = min(min_trade, max(5.0, price))
    else:
        min_trade = min(min_trade, max(5.0, investable * 0.08))
    return min_drift, min_trade


def _prioritize_growth_orders(
    orders: list[TradeOrder],
    *,
    portfolio: dict[str, Any],
    total_value: float,
) -> list[TradeOrder]:
    """Reorder trades to grow account value: high-conviction buys first, weak sells last."""
    settings = load_strategy_settings()
    if not settings.get("growth_mode", True):
        orders.sort(key=lambda o: abs(o.target_value_usd - o.current_value_usd), reverse=True)
        return orders

    target_map = {h["symbol"].upper(): h for h in portfolio.get("holdings", [])}
    persistent: set[str] = set()
    try:
        from analysis_history import get_persistent_bullish_tickers

        persistent = {row["symbol"] for row in get_persistent_bullish_tickers(top_n=30)}
    except Exception:
        pass

    def sort_key(order: TradeOrder) -> tuple:
        sym = order.symbol.upper()
        holding = target_map.get(sym, {})
        growth_score = float(holding.get("score", 0))
        if sym in persistent:
            growth_score += 0.35
        projected = float(holding.get("projected_return_pct") or 0)
        trade_usd = abs(order.target_value_usd - order.current_value_usd)
        if order.action == "BUY":
            # Lower sort key = earlier execution; buys with growth upside first.
            return (0, -growth_score, -projected, -trade_usd)
        if order.rationale.startswith("Trim position not in agent portfolio"):
            return (2, trade_usd, sym)
        return (1, -trade_usd, sym)

    orders.sort(key=sort_key)

    if settings.get("prioritize_buys", True):
        buys = [o for o in orders if o.action == "BUY"]
        others = [o for o in orders if o.action != "BUY"]
        if buys and total_value > 0:
            buy_notional = sum(
                max(0.0, o.target_value_usd - o.current_value_usd) for o in buys
            )
            # Keep some cash for opportunities but deploy capital toward growth names.
            max_buy_pct = 0.92 if settings.get("growth_mode", True) else 0.85
            max_buy_notional = total_value * max_buy_pct
            if buy_notional > max_buy_notional > 0:
                scale = max_buy_notional / buy_notional
                for order in buys:
                    order.quantity = max(1, int(order.quantity * scale))
        orders = buys + others

    return orders


def _position_map(positions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Long-sleeve position map only (shorts isolated for Short Trader)."""
    try:
        from sleeve_policy import long_position_map

        return long_position_map(positions)
    except Exception:
        out: dict[str, dict[str, Any]] = {}
        for pos in positions:
            sym = str(pos.get("symbol", "")).upper()
            if not sym:
                continue
            ptype = str(pos.get("position_type") or "LONG").upper()
            qty = float(pos.get("quantity") or 0)
            if ptype == "SHORT" or qty < 0:
                continue
            if sym in out:
                out[sym]["quantity"] = float(out[sym].get("quantity") or 0) + qty
                out[sym]["market_value"] = float(out[sym].get("market_value") or 0) + float(
                    pos.get("market_value") or 0
                )
            else:
                row = dict(pos)
                row["symbol"] = sym
                row["position_type"] = "LONG"
                out[sym] = row
        return out


def build_strategy_plan(
    client: ETradeClient,
    account_id_key: str,
    account_name: str = "",
    *,
    portfolio: dict[str, Any] | None = None,
    cash_buffer_pct: float = DEFAULT_CASH_BUFFER_PCT,
    min_drift_pct: float = DEFAULT_MIN_DRIFT_PCT,
    min_trade_usd: float = DEFAULT_MIN_TRADE_USD,
) -> StrategyPlan:
    balance = client.get_balance(account_id_key)
    positions = client.get_portfolio(account_id_key)
    pos_map = _position_map(positions)

    total_value = balance.get("total_account_value") or 0.0
    if total_value <= 0:
        total_value = sum(p.get("market_value", 0) for p in positions)
        total_value += balance.get("cash_available_for_investment") or balance.get("net_cash") or 0
    if total_value <= 0:
        raise ValueError("Could not determine account value from E*TRADE balance/portfolio.")

    # Shared capital + joint profit coordination with short sleeve
    try:
        from sleeve_coordinator import coordinate_sleeves
        from sleeve_policy import (
            blocked_symbols_for_new_entry,
            save_sleeve_snapshot,
            shared_capital_budget,
        )

        coordinate_sleeves(total_account_value=float(total_value))
        budget = shared_capital_budget(float(total_value), sleeve="long", balance=balance)
        # Use full sleeve ceiling for target sizing (not BP-clipped deployable),
        # so a $5k capital cap allocates against $5k even when cash is low
        # because existing long holdings already use part of the budget.
        investable_cap = float(
            budget.get("sleeve_ceiling_usd") or budget.get("deployable_usd") or 0
        )
        blocked_new = blocked_symbols_for_new_entry("long", positions)
        save_sleeve_snapshot(positions=positions, total_account_value=float(total_value))
    except Exception:
        investable_cap = 0.0
        blocked_new = set()
        budget = {}

    if portfolio is None:
        portfolio = generate_portfolio(OUTPUT, notional_usd=total_value)
        save_portfolio(portfolio, PORTFOLIO_FILE)

    settings = load_strategy_settings()
    if settings.get("agent_controlled", DEFAULT_AGENT_CONTROLLED):
        cash_buffer_pct = float(settings.get("cash_buffer_pct", cash_buffer_pct))
        min_drift_pct, _ = resolve_trade_thresholds(settings, investable=total_value)
        min_trade_usd = float(settings.get("min_trade_usd", min_trade_usd))

    investable = total_value * (1 - cash_buffer_pct / 100)
    if investable_cap > 0:
        investable = min(investable, investable_cap)
    targets = portfolio.get("holdings", [])
    symbols = {h["symbol"].upper() for h in targets} | set(pos_map.keys())
    prices: dict[str, float] = {}
    for sym in sorted(symbols):
        if sym in pos_map and pos_map[sym].get("price"):
            prices[sym] = float(pos_map[sym]["price"])
        else:
            px = _quote_price(client, sym)
            if px > 0:
                prices[sym] = px

    orders: list[TradeOrder] = []
    handled: set[str] = set()

    for holding in targets:
        sym = holding["symbol"].upper()
        handled.add(sym)
        weight = float(holding.get("weight_pct", 0))
        target_value = investable * weight / 100
        current = pos_map.get(sym, {})
        current_value = float(current.get("market_value", 0))
        current_qty = int(current.get("quantity", 0))
        current_weight = (current_value / total_value * 100) if total_value else 0
        price = prices.get(sym) or holding.get("price") or 0
        order_min_drift, order_min_trade = resolve_trade_thresholds(
            settings, investable=investable, price=price
        )
        drift = abs(target_value - current_value) / investable * 100 if investable else 0

        if drift < order_min_drift:
            continue

        if price <= 0:
            continue

        delta = target_value - current_value
        if abs(delta) < order_min_trade:
            continue

        if delta > 0:
            # Shared capital OK — but never open long against short sleeve
            if sym in blocked_new:
                continue
            qty = int(delta // price)
            action = "BUY"
        else:
            qty = min(current_qty, int(abs(delta) // price))
            action = "SELL"

        if qty <= 0:
            continue

        order = TradeOrder(
            symbol=sym,
            action=action,
            quantity=qty,
            target_weight_pct=weight,
            current_weight_pct=current_weight,
            target_value_usd=target_value,
            current_value_usd=current_value,
            estimated_price=price,
            rationale=holding.get("rationale", "Agent portfolio target"),
        )
        try:
            from order_type_selector import apply_to_trade_order, resolve_order_type

            horizon = "24h" if action == "SELL" and "day trade" in order.rationale.lower() else "1wk"
            decision = resolve_order_type(
                sym,
                action,
                price=price,
                rationale=order.rationale,
                horizon=horizon,
                confidence=float(holding.get("confidence", 0.55)),
                holding=holding,
            )
            apply_to_trade_order(order, decision)
        except Exception:
            pass
        orders.append(order)

    try:
        from trade_history import append_stop_target_exit_orders

        orders = append_stop_target_exit_orders(
            orders,
            pos_map=pos_map,
            prices=prices,
            settings=settings,
            total_value=total_value,
        )
    except Exception:
        pass

    for sym, pos in pos_map.items():
        if sym in handled:
            continue
        current_value = float(pos.get("market_value", 0))
        price = prices.get(sym) or float(pos.get("price", 0))
        _, trim_min_trade = resolve_trade_thresholds(settings, investable=investable, price=price)
        if current_value < trim_min_trade:
            continue
        qty = int(pos.get("quantity", 0))
        if qty <= 0 or price <= 0:
            continue
        trim_order = TradeOrder(
            symbol=sym,
            action="SELL",
            quantity=qty,
            target_weight_pct=0.0,
            current_weight_pct=(current_value / total_value * 100) if total_value else 0,
            target_value_usd=0.0,
            current_value_usd=current_value,
            estimated_price=price,
            rationale="Trim position not in agent portfolio",
        )
        try:
            from order_type_selector import apply_to_trade_order, resolve_order_type

            decision = resolve_order_type(
                sym,
                "SELL",
                price=price,
                rationale=trim_order.rationale,
                horizon="1wk",
            )
            apply_to_trade_order(trim_order, decision)
        except Exception:
            trim_order.price_type = "MARKET"
        orders.append(trim_order)

    agent_controlled = settings.get("agent_controlled", DEFAULT_AGENT_CONTROLLED)
    if agent_controlled:
        orders = _prioritize_growth_orders(orders, portfolio=portfolio, total_value=total_value)
    else:
        try:
            from profit_optimizer import (
                build_profit_profiles,
                filter_orders_for_profit,
                prioritize_orders_for_profit,
            )

            profiles = build_profit_profiles(OUTPUT, holdings=targets, settings=settings)
            orders = filter_orders_for_profit(orders, profiles, settings)
            orders = prioritize_orders_for_profit(
                orders,
                profiles,
                portfolio=portfolio,
                total_value=total_value,
                settings=settings,
            )
        except Exception:
            orders = _prioritize_growth_orders(orders, portfolio=portfolio, total_value=total_value)

    plan_meta = dict(portfolio.get("meta", {}))
    plan_meta["objective"] = "agent_controlled_selection" if agent_controlled else "maximize_multi_horizon_profit"
    plan_meta["agent_controlled"] = agent_controlled
    plan_meta["growth_mode"] = settings.get("growth_mode", True)
    plan_meta["optimize_profit_horizons"] = settings.get("optimize_profit_horizons", True)
    plan_meta["sleeve"] = "long"
    if budget:
        plan_meta["shared_capital_budget"] = budget
    try:
        from profit_optimizer import load_horizon_weights

        plan_meta["horizon_weights"] = load_horizon_weights(settings)
    except Exception:
        pass

    try:
        from analysis_history import record_account_value

        record_account_value(
            total_value,
            account_id_key=account_id_key,
            cash_buying_power=balance.get("cash_buying_power") or balance.get("cash_available_for_investment"),
            source="plan",
        )
    except Exception:
        pass

    # Plan inventory is long sleeve only so UI/trims never see shorts as longs
    long_positions_list = list(pos_map.values())
    plan = StrategyPlan(
        generated_at=datetime.now(timezone.utc).isoformat(),
        account_id_key=account_id_key,
        account_name=account_name,
        sandbox=client.config.sandbox,
        total_account_value=total_value,
        investable_usd=investable,
        cash_buffer_pct=cash_buffer_pct,
        regime=portfolio.get("regime", {}),
        target_holdings=targets,
        current_positions=long_positions_list,
        orders=orders,
        meta=plan_meta,
    )
    try:
        from sleeve_policy import apply_sleeve_to_plan

        apply_sleeve_to_plan(plan, sleeve="long", positions=positions)
    except Exception:
        pass
    try:
        from trading_gate import apply_trading_gates_to_plan, load_trading_gate_settings

        apply_trading_gates_to_plan(plan, settings=load_trading_gate_settings())
    except Exception:
        pass
    try:
        from trade_guards import apply_trade_guards_to_plan

        apply_trade_guards_to_plan(plan, balance)
    except Exception:
        pass
    return plan


def save_strategy_plan(plan: StrategyPlan, path: Path = PLAN_FILE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")
    return path


def load_strategy_plan(path: Path = PLAN_FILE) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def plan_from_dict(data: dict[str, Any]) -> StrategyPlan:
    orders = [
        TradeOrder(
            symbol=o["symbol"],
            action=o["action"],
            quantity=int(o["quantity"]),
            target_weight_pct=float(o.get("target_weight_pct", 0)),
            current_weight_pct=float(o.get("current_weight_pct", 0)),
            target_value_usd=float(o.get("target_value_usd", 0)),
            current_value_usd=float(o.get("current_value_usd", 0)),
            estimated_price=float(o.get("estimated_price", 0)),
            rationale=o.get("rationale", ""),
            price_type=str(o.get("price_type", "MARKET")).upper(),
            limit_price=float(o["limit_price"]) if o.get("limit_price") is not None else None,
            stop_price=float(o["stop_price"]) if o.get("stop_price") is not None else None,
            order_term=str(o.get("order_term") or ""),
            preview_id=o.get("preview_id"),
            status=o.get("status", "proposed"),
            message=o.get("message", ""),
        )
        for o in data.get("orders", [])
    ]
    return StrategyPlan(
        generated_at=data.get("generated_at", ""),
        account_id_key=data.get("account_id_key", ""),
        account_name=data.get("account_name", ""),
        sandbox=bool(data.get("sandbox", True)),
        total_account_value=float(data.get("total_account_value", 0)),
        investable_usd=float(data.get("investable_usd", 0)),
        cash_buffer_pct=float(data.get("cash_buffer_pct", DEFAULT_CASH_BUFFER_PCT)),
        regime=data.get("regime", {}),
        target_holdings=data.get("target_holdings", []),
        current_positions=data.get("current_positions", []),
        orders=orders,
        meta=data.get("meta", {}),
    )


def _order_body(client: ETradeClient, order: TradeOrder) -> dict[str, Any]:
    price_type = (order.price_type or "MARKET").upper()
    limit_px = order.limit_price if price_type in {"LIMIT", "STOP_LIMIT"} else None
    stop_px = getattr(order, "stop_price", None)
    if price_type in {"STOP", "STOP_LIMIT"} and stop_px is None and limit_px is not None:
        stop_px = limit_px
    order_term = (getattr(order, "order_term", None) or "").strip() or "GOOD_FOR_DAY"
    return client.build_equity_order(
        order.symbol,
        order.quantity,
        order.action,
        price_type=price_type,
        order_term=order_term,
        limit_price=limit_px,
        stop_price=stop_px,
    )


def preview_orders(client: ETradeClient, plan: StrategyPlan) -> StrategyPlan:
    try:
        from trade_guards import apply_trade_guards_to_plan

        balance = client.get_balance(plan.account_id_key)
        day_state = None
        if (plan.meta or {}).get("mode") == "day_trading":
            try:
                from day_trader import load_day_state

                day_state = load_day_state()
            except Exception:
                pass
        apply_trade_guards_to_plan(plan, balance, day_state=day_state)
    except Exception:
        pass

    for order in plan.orders:
        if order.status == "blocked":
            continue
        if order.quantity <= 0:
            order.status = "skipped"
            order.message = "Zero quantity"
            continue
        try:
            body = _order_body(client, order)
            preview = client.preview_equity_order(plan.account_id_key, body)
            preview_response = preview.get("PreviewOrderResponse", preview)
            preview_ids = preview_response.get("PreviewIds", [])
            preview_id = None
            if isinstance(preview_ids, list) and preview_ids:
                preview_id = preview_ids[0].get("previewId")
            elif isinstance(preview_ids, dict):
                preview_id = preview_ids.get("previewId")
            order.preview_id = preview_id
            order.status = "previewed"
            type_note = order.price_type
            if order.price_type == "LIMIT" and order.limit_price is not None:
                type_note = f"LIMIT @ ${order.limit_price:.2f}"
            order.message = f"Preview OK ({type_note})"
        except Exception as exc:
            order.status = "error"
            order.message = str(exc)
    return plan


def execute_orders(
    client: ETradeClient,
    plan: StrategyPlan,
    *,
    dry_run: bool = False,
) -> StrategyPlan:
    try:
        from trade_guards import apply_trade_guards_to_plan

        balance = client.get_balance(plan.account_id_key)
        day_state = None
        if (plan.meta or {}).get("mode") == "day_trading":
            try:
                from day_trader import load_day_state

                day_state = load_day_state()
            except Exception:
                pass
        apply_trade_guards_to_plan(plan, balance, day_state=day_state)
    except Exception:
        pass

    # Final sleeve isolation: never let long path touch shorts (or vice versa if meta says short)
    try:
        from sleeve_policy import apply_sleeve_to_plan

        positions = client.get_portfolio(plan.account_id_key)
        sleeve = str((plan.meta or {}).get("sleeve") or (plan.meta or {}).get("side") or "long")
        if sleeve not in {"long", "short"}:
            sleeve = "short" if str((plan.meta or {}).get("mode") or "").startswith("short") else "long"
        apply_sleeve_to_plan(plan, sleeve=sleeve, positions=positions)  # type: ignore[arg-type]
    except Exception:
        pass

    for order in plan.orders:
        if order.status in {"error", "blocked"} or order.quantity <= 0:
            continue
        try:
            body = _order_body(client, order)
            if order.preview_id is None:
                preview = client.preview_equity_order(plan.account_id_key, body)
                preview_response = preview.get("PreviewOrderResponse", preview)
                preview_ids = preview_response.get("PreviewIds", [])
                preview_id = None
                if isinstance(preview_ids, list) and preview_ids:
                    preview_id = preview_ids[0].get("previewId")
                elif isinstance(preview_ids, dict):
                    preview_id = preview_ids.get("previewId")
                order.preview_id = preview_id
            if dry_run:
                order.status = "dry_run"
                type_note = order.price_type
                if order.price_type == "LIMIT" and order.limit_price is not None:
                    type_note = f"LIMIT @ ${order.limit_price:.2f}"
                order.message = f"Dry run — {type_note} order not sent"
                continue
            if order.preview_id is None:
                order.status = "error"
                order.message = "Missing preview ID"
                continue
            placed = client.place_equity_order(plan.account_id_key, body, int(order.preview_id))
            order.status = "placed"
            type_note = order.price_type
            if order.price_type == "LIMIT" and order.limit_price is not None:
                type_note = f"LIMIT @ ${order.limit_price:.2f}"
            elif order.price_type in {"STOP", "STOP_LIMIT"} and getattr(order, "stop_price", None):
                type_note = f"{order.price_type} @ ${float(order.stop_price):.2f}"
            order.message = f"{type_note} order submitted"
            _ = placed
            if not dry_run and order.action == "BUY" and (plan.meta or {}).get("mode") != "day_trading":
                _place_swing_protective_orders(client, plan, order)
        except Exception as exc:
            order.status = "error"
            order.message = str(exc)

    try:
        from trade_guards import prune_old_pdt_records, record_placed_orders_for_pdt

        if not dry_run:
            record_placed_orders_for_pdt(plan.orders)
            prune_old_pdt_records()
    except Exception:
        pass

    try:
        from trade_history import record_executed_orders

        record_executed_orders(plan, dry_run=dry_run)
    except Exception:
        pass
    return plan


def _place_swing_protective_orders(client: ETradeClient, plan: StrategyPlan, buy_order: TradeOrder) -> None:
    """After a swing BUY fill, optionally place GTC stop-limit and limit take-profit sells."""
    try:
        from trade_history import compute_stop_target_prices, load_swing_stop_settings

        cfg = load_swing_stop_settings()
        if not cfg.get("place_protective_orders", True):
            return
        price = float(buy_order.estimated_price or 0)
        qty = int(buy_order.quantity or 0)
        if price <= 0 or qty <= 0:
            return
        stop_px, target_px = compute_stop_target_prices(price, settings=cfg)
        sym = buy_order.symbol.upper()

        if stop_px is not None and cfg.get("use_stop_orders", True):
            limit_px = round(stop_px * 0.995, 2)
            stop_body = client.build_equity_order(
                sym,
                qty,
                "SELL",
                price_type="STOP_LIMIT",
                order_term="GOOD_UNTIL_CANCEL",
                stop_price=stop_px,
                limit_price=limit_px,
            )
            try:
                preview = client.preview_equity_order(plan.account_id_key, stop_body)
                preview_response = preview.get("PreviewOrderResponse", preview)
                preview_ids = preview_response.get("PreviewIds", [])
                preview_id = preview_ids[0].get("previewId") if isinstance(preview_ids, list) and preview_ids else None
                if preview_id is not None:
                    client.place_equity_order(plan.account_id_key, stop_body, int(preview_id))
            except Exception:
                pass

        if target_px is not None:
            target_body = client.build_equity_order(
                sym,
                qty,
                "SELL",
                price_type="LIMIT",
                order_term="GOOD_UNTIL_CANCEL",
                limit_price=target_px,
            )
            try:
                preview = client.preview_equity_order(plan.account_id_key, target_body)
                preview_response = preview.get("PreviewOrderResponse", preview)
                preview_ids = preview_response.get("PreviewIds", [])
                preview_id = preview_ids[0].get("previewId") if isinstance(preview_ids, list) and preview_ids else None
                if preview_id is not None:
                    client.place_equity_order(plan.account_id_key, target_body, int(preview_id))
            except Exception:
                pass
    except Exception:
        pass


def _parse_analyzed_at(data: dict[str, Any]) -> datetime | None:
    meta = data.get("meta") or {}
    raw = (
        meta.get("analyzed_at")
        or data.get("analyzed_at")
        or meta.get("generated_at")
        or data.get("generated_at")
    )
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def validate_agent_output(out_path: Path, *, started_at: datetime) -> str | None:
    """Return an error message when agent output is missing or stale; else None."""
    if not out_path.exists():
        return "output file missing"
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"invalid JSON: {exc}"
    if not isinstance(data, dict):
        return "output is not a JSON object"
    if not data:
        return "output is empty"
    analyzed = _parse_analyzed_at(data)
    if analyzed is None:
        return "missing analyzed_at/generated_at timestamp"
    slack = started_at - timedelta(seconds=5)
    if analyzed < slack:
        return f"stale output (timestamp {analyzed.isoformat()} before pipeline start)"
    return None


def _format_pipeline_exception(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _run_timed_pipeline_step(
    fn: Callable[[], Any],
    *,
    timeout_sec: int,
    label: str,
    on_progress: Callable[[str], None] | None,
) -> Any:
    """Run a pipeline sub-step with a hard wall-clock timeout."""
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(fn)
    try:
        return future.result(timeout=timeout_sec)
    except FuturesTimeoutError:
        if on_progress:
            on_progress(f"{label} timed out after {timeout_sec}s — skipped.")
        return None
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _run_platform_agent_body(
    *,
    runner: Callable[..., Any],
    agent_id: str,
    label: str,
    out_path: Path,
    started_at: datetime,
    cycle_id: str | None,
    on_progress: Callable[[str], None] | None,
) -> dict[str, Any]:
    """Inner agent execution used under a wall-clock timeout guard."""
    result: dict[str, Any] = {
        "agent_id": agent_id,
        "label": label,
        "ok": False,
        "degraded": False,
        "error": "",
        "traceback": "",
    }
    invoke_error: BaseException | None = None
    try:
        try:
            from agents.pipeline_memory import invoke_agent_runner

            invoke_agent_runner(runner, agent_id=agent_id, output=out_path)
        except Exception as exc:
            invoke_error = exc
            runner(output=out_path)
            result["degraded"] = True

        try:
            from agents.optimize_output import optimize_agent_output

            optimize_agent_output(out_path, agent_id)
        except Exception as exc:
            if on_progress:
                on_progress(f"Output optimize skipped for {label}: {exc}")

        try:
            from agents.enhancement import patch_agent_output_enhance_symbols

            patch_agent_output_enhance_symbols(out_path)
        except Exception as exc:
            if on_progress:
                on_progress(f"Enhancement patch skipped for {label}: {exc}")

        try:
            from agent_personality import patch_agent_output_personality

            patch_agent_output_personality(out_path, agent_id)
        except Exception as exc:
            if on_progress:
                on_progress(f"Personality patch skipped for {label}: {exc}")

        validation_error = validate_agent_output(out_path, started_at=started_at)
        if validation_error:
            raise RuntimeError(validation_error)

        result["ok"] = True
        if result["degraded"] and on_progress:
            invoke_msg = _format_pipeline_exception(invoke_error) if invoke_error else "memory steering unavailable"
            on_progress(f"Agent degraded: {label} — {invoke_msg}")

        try:
            from analysis_history import archive_agent_output

            archive_agent_output(agent_id, out_path, cycle_id=cycle_id)
        except Exception as exc:
            if on_progress:
                on_progress(f"Archive skipped for {label}: {exc}")

        try:
            loaded = json.loads(out_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                result["agent_data"] = loaded
        except (OSError, json.JSONDecodeError):
            pass
    except Exception as exc:
        result["error"] = _format_pipeline_exception(exc)
        result["traceback"] = traceback.format_exc()
        if on_progress:
            on_progress(f"Agent failed: {label} — {result['error']}")
    return result


def _run_platform_agent(
    *,
    runner: Callable[..., Any],
    agent_id: str,
    label: str,
    out_path: Path,
    started_at: datetime,
    cycle_id: str | None,
    on_progress: Callable[[str], None] | None,
) -> dict[str, Any]:
    """Execute one platform agent with validation and non-silent error reporting."""
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(
        _run_platform_agent_body,
        runner=runner,
        agent_id=agent_id,
        label=label,
        out_path=out_path,
        started_at=started_at,
        cycle_id=cycle_id,
        on_progress=on_progress,
    )
    try:
        return future.result(timeout=AGENT_RUN_TIMEOUT_SEC)
    except FuturesTimeoutError:
        msg = f"timed out after {AGENT_RUN_TIMEOUT_SEC}s"
        if on_progress:
            on_progress(f"Agent timed out: {label} — {msg}")
        return {
            "agent_id": agent_id,
            "label": label,
            "ok": False,
            "degraded": False,
            "error": msg,
            "traceback": "",
        }
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _run_market_predictor(
    *,
    started_at: datetime,
    cycle_id: str | None,
    on_progress: Callable[[str], None] | None,
) -> dict[str, Any]:
    """Fuse market predictor output with validation and error reporting."""
    from agents.market_predictor import run_market_predictor_analysis

    predictor_path = OUTPUT / "market_predictions.json"
    result: dict[str, Any] = {
        "agent_id": "market-predictor",
        "label": "Market Predictor",
        "ok": False,
        "degraded": False,
        "error": "",
        "traceback": "",
    }
    invoke_error: BaseException | None = None
    try:
        try:
            from agents.pipeline_memory import invoke_agent_runner

            invoke_agent_runner(
                run_market_predictor_analysis,
                agent_id="market-predictor",
                output=predictor_path,
            )
        except Exception as exc:
            invoke_error = exc
            run_market_predictor_analysis(output=predictor_path)
            result["degraded"] = True

        try:
            from agent_personality import patch_agent_output_personality

            patch_agent_output_personality(predictor_path, "market-predictor")
        except Exception as exc:
            if on_progress:
                on_progress(f"Personality patch skipped for Market Predictor: {exc}")

        validation_error = validate_agent_output(predictor_path, started_at=started_at)
        if validation_error:
            raise RuntimeError(validation_error)

        result["ok"] = True
        if result["degraded"] and on_progress:
            invoke_msg = _format_pipeline_exception(invoke_error) if invoke_error else "memory steering unavailable"
            on_progress(f"Market Predictor degraded — {invoke_msg}")

        try:
            from analysis_history import archive_agent_output

            archive_agent_output("market-predictor", predictor_path, cycle_id=cycle_id)
        except Exception as exc:
            if on_progress:
                on_progress(f"Archive skipped for Market Predictor: {exc}")
    except Exception as exc:
        result["error"] = _format_pipeline_exception(exc)
        result["traceback"] = traceback.format_exc()
        if on_progress:
            on_progress(f"Market Predictor failed — {result['error']}")
    return result


def _reapply_pipeline_patches(sources: list[dict[str, str]]) -> None:
    """Apply fresh personality and learning after pipeline memory is finalized."""
    for src in sources:
        aid = src["id"]
        out_path = OUTPUT / src["file"]
        if not out_path.exists():
            continue
        try:
            from agents.optimize_output import optimize_agent_output

            optimize_agent_output(out_path, aid)
        except Exception:
            pass
        try:
            from agent_personality import patch_agent_output_personality

            patch_agent_output_personality(out_path, aid)
        except Exception:
            pass
        try:
            from agent_learning import patch_agent_output_learning

            patch_agent_output_learning(out_path, aid)
        except Exception:
            pass


def run_agent_pipeline(
    runners: dict[str, Callable[..., Any]] | None = None,
    on_progress: Callable[[str], None] | None = None,
    *,
    check_remote: bool = True,
    reload_runners: bool = True,
    benchmark_profile: str = "routine",
) -> int:
    from agents.platform_catalog import active_agent_sources, log_catalog_changes, resolve_runner

    if runners is None:
        from finance_runners import load_finance_runners

        runners = load_finance_runners(reload=reload_runners)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    try:
        from agents.pipeline_memory import begin_pipeline_memory_session, end_pipeline_memory_session

        begin_pipeline_memory_session()
    except Exception:
        pass
    try:
        from analysis_history import new_pipeline_cycle_id

        cycle_id = new_pipeline_cycle_id()
    except Exception:
        cycle_id = None
    log_catalog_changes(on_progress, check_remote=check_remote)
    try:
        from agent_groups import register_groups_into_fusion, all_groups_summary

        register_groups_into_fusion()
        if on_progress:
            groups = all_groups_summary()
            on_progress(
                f"Agent groups: {len(groups)} teams organizing "
                f"{sum(g['member_count'] for g in groups)} specialists by role."
            )
    except Exception as exc:
        if on_progress:
            on_progress(f"Agent group registration note: {exc}")
    try:
        from etrade_market_enhancer import run_proactive_etrade_enhancement

        run_proactive_etrade_enhancement(on_progress=on_progress)
    except Exception as exc:
        if on_progress:
            on_progress(f"Proactive E*TRADE enhancement skipped: {exc}")
    sources = active_agent_sources(check_remote=check_remote)
    # Prefer group order: risk first, then short mechanics, then core alpha, platform last
    try:
        from agent_groups import agent_trading_role

        role_rank = {
            "risk_gate": 0,
            "risk_overlay": 1,
            "short_alpha": 2,
            "regime": 3,
            "sector_specialist": 4,
            "alpha": 5,
            "intraday": 6,
            "allocator": 7,
            "execution": 8,
            "platform": 9,
            "fusion": 10,
        }
        sources = sorted(
            sources,
            key=lambda s: (
                role_rank.get(agent_trading_role(str(s.get("id") or "")), 5),
                str(s.get("category") or ""),
                str(s.get("label") or ""),
            ),
        )
    except Exception:
        pass
    pipeline_started_at = datetime.now(timezone.utc)
    ok = 0
    skipped = 0
    agent_failures: list[dict[str, Any]] = []
    agent_degraded: list[dict[str, Any]] = []
    for index, src in enumerate(sources, start=1):
        aid = src["id"]
        label = str(src.get("label") or aid)
        if on_progress:
            on_progress(f"Agent {index}/{len(sources)}: {label}")
        runner = resolve_runner(aid, runners)
        if runner is None:
            skipped += 1
            if on_progress:
                on_progress(f"Agent skipped: {label} — no runner")
            continue
        out_path = OUTPUT / src["file"]
        outcome = _run_platform_agent(
            runner=runner,
            agent_id=aid,
            label=label,
            out_path=out_path,
            started_at=pipeline_started_at,
            cycle_id=cycle_id,
            on_progress=on_progress,
        )
        if outcome.get("ok"):
            ok += 1
            try:
                from agents.pipeline_memory import register_same_cycle_agent_output

                agent_data = outcome.get("agent_data")
                if isinstance(agent_data, dict):
                    register_same_cycle_agent_output(aid, agent_data)
                elif out_path.exists():
                    loaded = json.loads(out_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        register_same_cycle_agent_output(aid, loaded)
            except Exception:
                pass
            if outcome.get("degraded"):
                agent_degraded.append(
                    {
                        "agent_id": aid,
                        "label": label,
                        "error": outcome.get("error") or "memory steering fallback",
                    }
                )
            continue
        agent_failures.append(
            {
                "agent_id": aid,
                "label": label,
                "error": outcome.get("error") or "unknown error",
                "traceback": str(outcome.get("traceback") or "")[-2000:],
            }
        )
    if skipped and on_progress:
        on_progress(f"Skipped {skipped} agent(s) without runners.")
    if agent_failures and on_progress:
        preview = "; ".join(
            f"{row.get('label') or row.get('agent_id')}: {row.get('error')}"
            for row in agent_failures[:4]
        )
        extra = len(agent_failures) - 4
        if extra > 0:
            preview += f"; and {extra} more"
        on_progress(f"Pipeline agent failures ({len(agent_failures)}): {preview}")
    try:
        from agents.pipeline_memory import restore_same_cycle_agent_outputs

        restored = restore_same_cycle_agent_outputs(sources)
        if restored and on_progress:
            on_progress(f"Restored {restored} agent output(s) from pipeline memory.")
    except Exception:
        pass
    try:
        from etrade_market_enhancer import run_etrade_enhancement

        etrade_stats = _run_timed_pipeline_step(
            lambda: run_etrade_enhancement(on_progress=on_progress),
            timeout_sec=ETRADE_ENHANCE_TIMEOUT_SEC,
            label="E*TRADE enhancement",
            on_progress=on_progress,
        )
        if etrade_stats is None:
            etrade_stats = {"skipped": True, "reason": "timeout"}
        try:
            from agents.pipeline_memory import sync_same_cycle_from_disk

            sync_same_cycle_from_disk(sources)
            if on_progress and isinstance(etrade_stats, dict) and etrade_stats.get("agent_files_updated"):
                on_progress(
                    f"Synced {etrade_stats['agent_files_updated']} E*TRADE-enhanced agent file(s) to pipeline memory."
                )
        except Exception:
            pass
        try:
            from agents.pipeline_memory import restore_same_cycle_agent_outputs

            restore_same_cycle_agent_outputs(sources)
        except Exception:
            pass
    except Exception as exc:
        if on_progress:
            on_progress(f"E*TRADE enhancement skipped: {exc}")
    bench: dict[str, Any] | None = None
    try:
        from historical_simulation import run_pipeline_accuracy_benchmark

        bench = _run_timed_pipeline_step(
            lambda: run_pipeline_accuracy_benchmark(
                on_progress=on_progress,
                profile=benchmark_profile,
            ),
            timeout_sec=BENCHMARK_TIMEOUT_SEC,
            label=f"Backtest ({benchmark_profile})",
            on_progress=on_progress,
        )
        if on_progress and isinstance(bench, dict):
            metrics = bench.get("metrics") or {}
            board = bench.get("leaderboard") or []
            top = board[0] if board else {}
            on_progress(
                f"Backtest complete — {metrics.get('total_trials', 0):,} trials, "
                f"{(bench.get('meta') or {}).get('universe_size', 0)} symbols"
                + (
                    f" · top {top.get('agent_id')} {top.get('accuracy_pct')}%"
                    if top.get("agent_id")
                    else ""
                )
            )
    except Exception as exc:
        if on_progress:
            on_progress(f"Pipeline backtest skipped: {exc}")
    try:
        from agents.pipeline_memory import restore_same_cycle_agent_outputs

        restore_same_cycle_agent_outputs(sources)
    except Exception:
        pass
    if on_progress:
        on_progress("Fusing Market Predictor…")
    predictor_outcome = _run_market_predictor(
        started_at=pipeline_started_at,
        cycle_id=cycle_id,
        on_progress=on_progress,
    )
    predictor_ok = bool(predictor_outcome.get("ok"))
    predictor_failure: dict[str, Any] | None = None
    if not predictor_ok:
        predictor_failure = {
            "agent_id": "market-predictor",
            "label": "Market Predictor",
            "error": predictor_outcome.get("error") or "unknown error",
            "traceback": str(predictor_outcome.get("traceback") or "")[-2000:],
        }
    elif predictor_outcome.get("degraded"):
        agent_degraded.append(
            {
                "agent_id": "market-predictor",
                "label": "Market Predictor",
                "error": "memory steering fallback",
            }
        )
    if cycle_id is None:
        try:
            from analysis_history import new_pipeline_cycle_id

            cycle_id = new_pipeline_cycle_id()
        except Exception:
            cycle_id = None
    try:
        from agents.pipeline_memory import restore_same_cycle_agent_outputs

        restore_same_cycle_agent_outputs(sources)
    except Exception:
        pass
    try:
        from analysis_history import archive_pipeline_cycle

        archive_pipeline_cycle(cycle_id=cycle_id, refresh_context=False)
        if on_progress and cycle_id:
            on_progress(f"Analysis history saved (cycle {cycle_id}).")
    except Exception as exc:
        if on_progress:
            on_progress(f"Analysis history skipped: {exc}")
    stats: dict[str, int] = {}
    try:
        from prediction_accuracy import run_accuracy_cycle

        stats = run_accuracy_cycle(
            cycle_id=cycle_id,
            skip_simulation=True,
            rebuild_learning=False,
        )
        if on_progress and stats.get("recorded"):
            on_progress(f"Recorded {stats['recorded']} prediction(s) from this pipeline run.")
        if on_progress and stats.get("scored"):
            on_progress(f"Scored {stats['scored']} matured prediction(s) for accuracy tracking.")
        if on_progress and stats.get("simulated"):
            on_progress(
                f"Historical simulation: {stats['simulated']} walk-forward trial(s) scored."
            )
    except Exception:
        pass
    try:
        from analysis_history import finalize_pipeline_cycle, record_pipeline_agent_errors

        if cycle_id:
            if agent_failures or agent_degraded or predictor_failure:
                record_pipeline_agent_errors(
                    cycle_id,
                    failures=agent_failures,
                    degraded=agent_degraded,
                    predictor_failure=predictor_failure,
                )
            finalize_pipeline_cycle(
                cycle_id,
                agents_ok=ok,
                agents_total=len(sources),
                agents_failed=len(agent_failures),
                agent_failures=agent_failures,
                predictor_ok=predictor_ok,
                accuracy_stats=stats,
                benchmark=bench,
            )
            _reapply_pipeline_patches(sources)
            try:
                from agents.pipeline_memory import (
                    restore_same_cycle_agent_outputs,
                    sync_same_cycle_from_disk,
                )

                sync_same_cycle_from_disk(sources)
                restored_final = restore_same_cycle_agent_outputs(sources)
                if restored_final and on_progress:
                    on_progress(
                        f"Finalized {restored_final} agent output(s) with market-impact signals."
                    )
            except Exception:
                pass
            if on_progress:
                on_progress("Pipeline memory updated — future runs will use this cycle.")
                if agent_failures or not predictor_ok:
                    on_progress(
                        f"Pipeline finished with issues — agents {ok}/{len(sources)}, "
                        f"predictor {'ok' if predictor_ok else 'failed'}"
                    )
    except Exception:
        pass
    try:
        from agents.pipeline_memory import end_pipeline_memory_session

        end_pipeline_memory_session()
    except Exception:
        pass
    return ok