#!/usr/bin/env python3
"""Apply Finance agent portfolio strategies to an E*TRADE account."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from etrade_api.client import ETradeClient
from etrade_api.config import ETradeConfig, load_config
from portfolio_generator import generate_portfolio, save_portfolio

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
PORTFOLIO_FILE = OUTPUT / "portfolio.json"
PLAN_FILE = OUTPUT / "strategy_plan.json"

DEFAULT_CASH_BUFFER_PCT = 5.0
DEFAULT_MIN_DRIFT_PCT = 1.5
DEFAULT_MIN_TRADE_USD = 50.0
DEFAULT_GROWTH_MODE = True
DEFAULT_PRIORITIZE_BUYS = True
DEFAULT_OPTIMIZE_PROFIT_HORIZONS = True


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
    preview_id: int | None = None
    status: str = "proposed"
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "quantity": self.quantity,
            "target_weight_pct": round(self.target_weight_pct, 2),
            "current_weight_pct": round(self.current_weight_pct, 2),
            "target_value_usd": round(self.target_value_usd, 2),
            "current_value_usd": round(self.current_value_usd, 2),
            "estimated_price": round(self.estimated_price, 4),
            "rationale": self.rationale,
            "preview_id": self.preview_id,
            "status": self.status,
            "message": self.message,
        }


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
        "min_buy_return_pct": 0.05,
        "min_sell_return_pct": -0.10,
        "max_deploy_pct": 0.94,
    }
    if not path.exists():
        return settings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        user = raw.get("strategy", {})
        settings.update({k: user[k] for k in settings if k in user})
    except (json.JSONDecodeError, OSError):
        pass
    return settings


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
    out: dict[str, dict[str, Any]] = {}
    for pos in positions:
        sym = pos.get("symbol", "").upper()
        if not sym:
            continue
        if sym in out:
            out[sym]["quantity"] += pos.get("quantity", 0)
            out[sym]["market_value"] += pos.get("market_value", 0)
        else:
            out[sym] = dict(pos)
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
    if portfolio is None:
        portfolio = generate_portfolio(OUTPUT, notional_usd=None)
        save_portfolio(portfolio, PORTFOLIO_FILE)

    balance = client.get_balance(account_id_key)
    positions = client.get_portfolio(account_id_key)
    pos_map = _position_map(positions)

    total_value = balance.get("total_account_value") or 0.0
    if total_value <= 0:
        total_value = sum(p.get("market_value", 0) for p in positions)
        total_value += balance.get("cash_available_for_investment") or balance.get("net_cash") or 0
    if total_value <= 0:
        raise ValueError("Could not determine account value from E*TRADE balance/portfolio.")

    investable = total_value * (1 - cash_buffer_pct / 100)
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
        drift = abs(target_value - current_value) / investable * 100 if investable else 0

        if drift < min_drift_pct:
            continue

        price = prices.get(sym) or holding.get("price") or 0
        if price <= 0:
            continue

        delta = target_value - current_value
        if abs(delta) < min_trade_usd:
            continue

        if delta > 0:
            qty = int(delta // price)
            action = "BUY"
        else:
            qty = min(current_qty, int(abs(delta) // price))
            action = "SELL"

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
                rationale=holding.get("rationale", "Agent portfolio target"),
            )
        )

    for sym, pos in pos_map.items():
        if sym in handled:
            continue
        current_value = float(pos.get("market_value", 0))
        if current_value < min_trade_usd:
            continue
        price = prices.get(sym) or float(pos.get("price", 0))
        qty = int(pos.get("quantity", 0))
        if qty <= 0 or price <= 0:
            continue
        orders.append(
            TradeOrder(
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
        )

    settings = load_strategy_settings()
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
    plan_meta["objective"] = "maximize_multi_horizon_profit"
    plan_meta["growth_mode"] = settings.get("growth_mode", True)
    plan_meta["optimize_profit_horizons"] = settings.get("optimize_profit_horizons", True)
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

    return StrategyPlan(
        generated_at=datetime.now(timezone.utc).isoformat(),
        account_id_key=account_id_key,
        account_name=account_name,
        sandbox=client.config.sandbox,
        total_account_value=total_value,
        investable_usd=investable,
        cash_buffer_pct=cash_buffer_pct,
        regime=portfolio.get("regime", {}),
        target_holdings=targets,
        current_positions=positions,
        orders=orders,
        meta=plan_meta,
    )


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


def preview_orders(client: ETradeClient, plan: StrategyPlan) -> StrategyPlan:
    for order in plan.orders:
        if order.quantity <= 0:
            order.status = "skipped"
            order.message = "Zero quantity"
            continue
        try:
            result = client.preview_and_place_equity_order(
                plan.account_id_key,
                order.symbol,
                order.quantity,
                order.action,
                dry_run=True,
            )
            order.preview_id = result.get("preview_id")
            order.status = "previewed"
            order.message = "Preview OK"
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
    for order in plan.orders:
        if order.status == "error" or order.quantity <= 0:
            continue
        try:
            if order.preview_id is None:
                preview = client.preview_and_place_equity_order(
                    plan.account_id_key,
                    order.symbol,
                    order.quantity,
                    order.action,
                    dry_run=True,
                )
                order.preview_id = preview.get("preview_id")
            if dry_run:
                order.status = "dry_run"
                order.message = "Dry run — order not sent"
                continue
            if order.preview_id is None:
                order.status = "error"
                order.message = "Missing preview ID"
                continue
            body = client.build_equity_order(order.symbol, order.quantity, order.action)
            placed = client.place_equity_order(plan.account_id_key, body, int(order.preview_id))
            order.status = "placed"
            order.message = "Order submitted"
            _ = placed
        except Exception as exc:
            order.status = "error"
            order.message = str(exc)
    return plan


def run_agent_pipeline(
    runners: dict[str, Callable[..., Any]] | None = None,
    on_progress: Callable[[str], None] | None = None,
    *,
    check_remote: bool = True,
) -> int:
    from agents.platform_catalog import active_agent_sources, log_catalog_changes, resolve_runner

    OUTPUT.mkdir(parents=True, exist_ok=True)
    log_catalog_changes(on_progress, check_remote=check_remote)
    sources = active_agent_sources(check_remote=check_remote)
    ok = 0
    skipped = 0
    for index, src in enumerate(sources, start=1):
        aid = src["id"]
        if on_progress:
            on_progress(f"Agent {index}/{len(sources)}: {src.get('label', aid)}")
        runner = resolve_runner(aid, runners)
        if runner is None:
            skipped += 1
            continue
        try:
            out_path = OUTPUT / src["file"]
            runner(output=out_path)
            try:
                from agents.enhancement import patch_agent_output_enhance_symbols

                patch_agent_output_enhance_symbols(out_path)
            except Exception:
                pass
            ok += 1
            try:
                from analysis_history import archive_agent_output

                archive_agent_output(aid, out_path)
            except Exception:
                pass
        except Exception:
            pass
    if skipped and on_progress:
        on_progress(f"Skipped {skipped} agent(s) without runners.")
    try:
        from etrade_market_enhancer import run_etrade_enhancement

        run_etrade_enhancement(on_progress=on_progress)
    except Exception as exc:
        if on_progress:
            on_progress(f"E*TRADE enhancement skipped: {exc}")
    if on_progress:
        on_progress("Fusing Market Predictor…")
    from agents.market_predictor import run_market_predictor_analysis

    run_market_predictor_analysis(output=OUTPUT / "market_predictions.json")
    try:
        from analysis_history import archive_agent_output, archive_pipeline_cycle

        archive_agent_output("market-predictor", OUTPUT / "market_predictions.json")
        cycle_id = archive_pipeline_cycle()
        if on_progress:
            on_progress(f"Analysis history saved (cycle {cycle_id}).")
    except Exception:
        pass
    return ok