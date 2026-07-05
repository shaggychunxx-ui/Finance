"""Multi-horizon profit scoring for daily, weekly, monthly, and yearly trades."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"

HORIZON_KEYS = ("daily", "weekly", "monthly", "yearly")
PREDICTION_HORIZON_MAP = {
    "daily": "24h",
    "weekly": "1wk",
    "monthly": "1mo",
    "yearly": "1yr",
}
DEFAULT_HORIZON_WEIGHTS = {
    "daily": 0.25,
    "weekly": 0.25,
    "monthly": 0.25,
    "yearly": 0.25,
}
DEFAULT_MIN_BUY_RETURN_PCT = 0.05
DEFAULT_MIN_SELL_RETURN_PCT = -0.10


@dataclass
class ProfitProfile:
    symbol: str
    horizon_returns: dict[str, float] = field(default_factory=dict)
    horizon_confidence: dict[str, float] = field(default_factory=dict)
    composite_return_pct: float = 0.0
    composite_score: float = 0.0
    action_bias: str = "hold"

    def expected_profit_usd(self, trade_usd: float, action: str) -> float:
        if trade_usd <= 0:
            return 0.0
        if action == "BUY":
            return trade_usd * self.composite_return_pct / 100.0
        if action == "SELL":
            # Selling frees capital; benefit when outlook is weak.
            return trade_usd * (-self.composite_return_pct) / 100.0
        return 0.0


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def load_horizon_weights(settings: dict[str, Any] | None = None) -> dict[str, float]:
    weights = dict(DEFAULT_HORIZON_WEIGHTS)
    if not settings:
        return weights
    raw = settings.get("profit_horizons") or settings.get("horizon_weights") or {}
    if isinstance(raw, dict):
        for key in HORIZON_KEYS:
            entry = raw.get(key)
            if isinstance(entry, dict) and "weight" in entry:
                weights[key] = float(entry["weight"])
            elif isinstance(entry, (int, float)):
                weights[key] = float(entry)
    total = sum(weights.values()) or 1.0
    return {k: weights[k] / total for k in HORIZON_KEYS}


def _account_horizon_tilt() -> dict[str, float]:
    """Boost horizon weights that are currently delivering account growth."""
    data = _load_json(OUTPUT / "history" / "account_values.json")
    if not isinstance(data, dict):
        return {k: 0.0 for k in HORIZON_KEYS}
    points = data.get("points", [])
    if len(points) < 2:
        return {k: 0.0 for k in HORIZON_KEYS}

    latest = float(points[-1].get("total_account_value", 0))
    if latest <= 0:
        return {k: 0.0 for k in HORIZON_KEYS}

    def pct_change(steps_back: int) -> float:
        if len(points) <= steps_back:
            return 0.0
        old = float(points[-1 - steps_back].get("total_account_value", 0))
        if old <= 0:
            return 0.0
        return (latest - old) / old * 100.0

    return {
        "daily": pct_change(min(3, len(points) - 1)),
        "weekly": pct_change(min(10, len(points) - 1)),
        "monthly": pct_change(min(30, len(points) - 1)),
        "yearly": pct_change(min(120, len(points) - 1)),
    }


def load_prediction_table(output_dir: Path | None = None) -> dict[str, dict[str, dict[str, Any]]]:
    """symbol -> horizon_key -> {return_pct, direction, confidence}."""
    output_dir = output_dir or OUTPUT
    data = _load_json(output_dir / "market_predictions.json") or {}
    preds = data.get("predictions", {})
    table: dict[str, dict[str, dict[str, Any]]] = {}

    for horizon_key, pred_key in PREDICTION_HORIZON_MAP.items():
        rows = preds.get(pred_key, [])
        for row in rows or []:
            sym = str(row.get("symbol", "")).strip().upper()
            if not sym:
                continue
            direction = str(row.get("predicted_direction", "")).lower()
            ret = float(row.get("predicted_return_pct", 0))
            if direction == "down":
                ret = -abs(ret)
            elif direction == "flat":
                ret = ret * 0.15
            conf = float(row.get("confidence", 0.5))
            table.setdefault(sym, {})[horizon_key] = {
                "return_pct": ret,
                "direction": direction,
                "confidence": conf,
            }
    return table


def build_profit_profiles(
    output_dir: Path | None = None,
    *,
    holdings: list[dict[str, Any]] | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, ProfitProfile]:
    output_dir = output_dir or OUTPUT
    weights = load_horizon_weights(settings)
    tilt = _account_horizon_tilt()
    for key in HORIZON_KEYS:
        weights[key] *= 1.0 + max(-0.2, min(0.2, tilt[key] / 50.0))
    total_w = sum(weights.values()) or 1.0
    weights = {k: weights[k] / total_w for k in HORIZON_KEYS}

    pred_table = load_prediction_table(output_dir)
    holding_map = {str(h.get("symbol", "")).upper(): h for h in (holdings or [])}

    history_scores: dict[str, float] = {}
    try:
        from analysis_history import get_persistent_bullish_tickers

        for row in get_persistent_bullish_tickers(top_n=40):
            history_scores[row["symbol"]] = float(row.get("composite", 0))
    except Exception:
        pass

    symbols = set(pred_table) | set(holding_map) | set(history_scores)
    profiles: dict[str, ProfitProfile] = {}

    for sym in symbols:
        horizon_returns: dict[str, float] = {}
        horizon_confidence: dict[str, float] = {}
        for horizon_key in HORIZON_KEYS:
            pred = pred_table.get(sym, {}).get(horizon_key, {})
            ret = float(pred.get("return_pct", 0))
            conf = float(pred.get("confidence", 0.45))
            holding = holding_map.get(sym, {})
            if holding:
                proj = float(holding.get("projected_return_pct") or 0)
                score = float(holding.get("score") or 0)
                ret += proj * 0.15 + score * 0.05
            hist = history_scores.get(sym, 0.0)
            if hist:
                ret += hist * 0.08 * (1.0 if horizon_key in ("monthly", "yearly") else 0.5)
            horizon_returns[horizon_key] = round(ret, 3)
            horizon_confidence[horizon_key] = round(conf, 3)

        composite = sum(
            horizon_returns[h] * weights[h] * (0.5 + 0.5 * horizon_confidence.get(h, 0.5))
            for h in HORIZON_KEYS
        )
        composite_score = composite * (1.0 + history_scores.get(sym, 0.0) * 0.1)
        if composite > 0.2:
            bias = "buy"
        elif composite < -0.15:
            bias = "sell"
        else:
            bias = "hold"

        profiles[sym] = ProfitProfile(
            symbol=sym,
            horizon_returns=horizon_returns,
            horizon_confidence=horizon_confidence,
            composite_return_pct=round(composite, 3),
            composite_score=round(composite_score, 3),
            action_bias=bias,
        )

    return profiles


def filter_orders_for_profit(
    orders: list[Any],
    profiles: dict[str, ProfitProfile],
    settings: dict[str, Any] | None = None,
) -> list[Any]:
    """Drop trades that work against multi-horizon profit goals."""
    settings = settings or {}
    min_buy = float(settings.get("min_buy_return_pct", DEFAULT_MIN_BUY_RETURN_PCT))
    min_sell = float(settings.get("min_sell_return_pct", DEFAULT_MIN_SELL_RETURN_PCT))
    optimize = settings.get("optimize_profit_horizons", True)
    if not optimize:
        return orders

    kept = []
    for order in orders:
        sym = order.symbol.upper()
        profile = profiles.get(sym)
        if profile is None:
            kept.append(order)
            continue
        if order.action == "BUY" and profile.composite_return_pct < min_buy:
            continue
        if order.action == "SELL":
            trim = order.rationale.startswith("Trim position not in agent portfolio")
            if trim and profile.composite_return_pct > abs(min_sell) * 2:
                continue
            if not trim and profile.composite_return_pct > min_sell and profile.action_bias != "sell":
                continue
        kept.append(order)
    return kept


def prioritize_orders_for_profit(
    orders: list[Any],
    profiles: dict[str, ProfitProfile],
    *,
    portfolio: dict[str, Any],
    total_value: float,
    settings: dict[str, Any] | None = None,
) -> list[Any]:
    """Sort and scale orders to maximize expected profit across all horizons."""
    settings = settings or {}
    if not settings.get("optimize_profit_horizons", True):
        orders.sort(key=lambda o: abs(o.target_value_usd - o.current_value_usd), reverse=True)
        return orders

    enriched: list[tuple[float, Any]] = []
    for order in orders:
        sym = order.symbol.upper()
        profile = profiles.get(sym)
        trade_usd = abs(order.target_value_usd - order.current_value_usd)
        if order.action == "BUY":
            trade_usd = max(trade_usd, order.quantity * order.estimated_price)
        elif order.action == "SELL":
            trade_usd = max(trade_usd, order.quantity * order.estimated_price)

        if profile:
            profit = profile.expected_profit_usd(trade_usd, order.action)
            horizons = profile.horizon_returns
            note = (
                f"Profit d/w/m/y: {horizons.get('daily', 0):+.2f}%/"
                f"{horizons.get('weekly', 0):+.2f}%/"
                f"{horizons.get('monthly', 0):+.2f}%/"
                f"{horizons.get('yearly', 0):+.2f}%"
            )
            if note not in order.rationale:
                order.rationale = f"{order.rationale} | {note}" if order.rationale else note
        else:
            profit = 0.0 if order.action == "SELL" else trade_usd * 0.01

        priority = 0 if order.action == "BUY" else 1 if profit > 0 else 2
        enriched.append((priority, -profit, -trade_usd, order))

    enriched.sort(key=lambda row: (row[0], row[1], row[2]))
    result = [row[3] for row in enriched]

    if settings.get("prioritize_buys", True) and total_value > 0:
        buys = [o for o in result if o.action == "BUY"]
        sells = [o for o in result if o.action == "SELL"]
        buy_notional = sum(max(0, o.quantity * o.estimated_price) for o in buys)
        max_pct = float(settings.get("max_deploy_pct", 0.94))
        cap = total_value * max_pct
        if buy_notional > cap > 0:
            scale = cap / buy_notional
            for order in buys:
                order.quantity = max(1, int(order.quantity * scale))
        result = buys + sells

    return result


def apply_profit_weights_to_holdings(holdings: list[dict[str, Any]], profiles: dict[str, ProfitProfile]) -> None:
    """Adjust holding weights toward maximum multi-horizon profit."""
    for row in holdings:
        sym = str(row.get("symbol", "")).upper()
        profile = profiles.get(sym)
        if not profile:
            continue
        row["horizon_returns"] = profile.horizon_returns
        row["profit_score"] = profile.composite_score
        row["profit_bias"] = profile.action_bias
        boost = 1.0 + max(0.0, profile.composite_return_pct) / 20.0
        row["weight_pct"] = round(float(row.get("weight_pct", 0)) * boost, 2)