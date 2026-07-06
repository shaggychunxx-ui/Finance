"""Agent-driven market vs limit order decisions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.platform_catalog import active_agent_sources

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"

MARKET_STRATEGIES = frozenset(
    {"momentum_continuation", "breakout_reversal", "urgent", "stop_loss", "flatten", "exit"}
)
LIMIT_STRATEGIES = frozenset(
    {"mean_reversion", "swing_trade", "patient_entry", "pullback", "value_entry"}
)
URGENT_SELL_KEYWORDS = (
    "stop loss",
    "flatten",
    "exit",
    "bearish",
    "trim position not in agent portfolio",
    "dropped from",
    "take profit",
)


@dataclass
class OrderTypeDecision:
    price_type: str
    limit_price: float | None = None
    reason: str = ""
    sources: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "price_type": self.price_type,
            "limit_price": self.limit_price,
            "reason": self.reason,
            "sources": self.sources or [],
        }


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _normalize_symbol(symbol: str) -> str:
    return (symbol or "").strip().upper().replace(".", "-")


def _limit_offset(confidence: float, *, action: str, horizon: str) -> float:
    """Agent patience → limit distance from last price (fraction)."""
    patience = max(0.0, min(1.0, 1.0 - confidence))
    base = 0.003 + patience * 0.010
    if horizon in {"24h", "daily"}:
        base *= 0.65
    elif horizon in {"1yr", "yearly"}:
        base *= 1.25
    if action == "SELL":
        base *= 0.85
    return base


def compute_limit_price(
    price: float,
    action: str,
    *,
    confidence: float = 0.55,
    horizon: str = "1wk",
) -> float | None:
    if price <= 0:
        return None
    offset = _limit_offset(confidence, action=action, horizon=horizon)
    if action == "BUY":
        return round(price * (1.0 - offset), 2)
    return round(price * (1.0 + offset), 2)


def _vote(price_type: str, weight: float, source: str, note: str, votes: list[tuple[str, float, str, str]]) -> None:
    votes.append((price_type.upper(), weight, source, note))


def collect_agent_votes(
    symbol: str,
    action: str,
    *,
    output_dir: Path | None = None,
    rationale: str = "",
    horizon: str = "1wk",
    confidence: float = 0.55,
) -> list[tuple[str, float, str, str]]:
    """Gather market/limit votes from agent artifacts for *symbol*."""
    output_dir = output_dir or OUTPUT
    sym = _normalize_symbol(symbol)
    action = action.upper()
    votes: list[tuple[str, float, str, str]] = []
    rationale_l = rationale.lower()

    if action == "SELL" and any(k in rationale_l for k in URGENT_SELL_KEYWORDS):
        _vote("MARKET", 1.0, "exit-urgency", "Agent exit — immediate fill", votes)

    finance = _load_json(output_dir / "finance.json") or {}
    for opp in finance.get("trading_opportunities", []):
        if _normalize_symbol(opp.get("symbol", "")) != sym:
            continue
        strategy = str(opp.get("strategy", "")).lower()
        score = float(opp.get("opportunity_score", 0.5))
        if strategy in MARKET_STRATEGIES or opp.get("order_type", "").upper() == "MARKET":
            _vote("MARKET", 0.55 + score * 0.35, "finance", f"{strategy} → market", votes)
        elif strategy in LIMIT_STRATEGIES or opp.get("order_type", "").upper() == "LIMIT":
            _vote("LIMIT", 0.55 + score * 0.35, "finance", f"{strategy} → limit", votes)

    predictions = _load_json(output_dir / "market_predictions.json") or {}
    pred_rows = (predictions.get("predictions") or {}).get(horizon if horizon in {"24h", "1wk", "1mo", "1yr"} else "1wk", [])
    for row in pred_rows or []:
        if _normalize_symbol(row.get("symbol", "")) != sym:
            continue
        conf = float(row.get("confidence", confidence))
        ret = abs(float(row.get("predicted_return_pct", 0)))
        explicit = str(row.get("order_type", "")).upper()
        if explicit in {"MARKET", "LIMIT"}:
            _vote(explicit, 0.7 + conf * 0.25, "market-predictor", f"Fused agent order type: {explicit.lower()}", votes)
        elif horizon == "24h" and ret >= 1.0 and conf >= 0.7:
            _vote("MARKET", 0.65 + conf * 0.2, "market-predictor", "Strong 24h momentum — market entry", votes)
        elif ret < 0.8 or conf < 0.6:
            _vote("LIMIT", 0.55 + conf * 0.2, "market-predictor", "Patient agent entry — limit", votes)
        else:
            _vote("MARKET", 0.5 + conf * 0.15, "market-predictor", "Agent momentum signal", votes)
        confidence = max(confidence, conf)
        break

    for src in active_agent_sources():
        data = _load_json(output_dir / src["file"])
        if not data:
            continue
        source_id = src["id"]

        for pick in data.get("top_picks", []):
            if _normalize_symbol(pick.get("symbol", "")) != sym:
                continue
            explicit = str(pick.get("order_type", "")).upper()
            conf = float(pick.get("confidence", 0.5))
            if explicit in {"MARKET", "LIMIT"}:
                _vote(explicit, 0.5 + conf * 0.3, source_id, f"{source_id} order preference", votes)
            elif float(pick.get("score", 0)) >= 0.75:
                _vote("MARKET", 0.45 + conf * 0.25, source_id, f"{source_id} high-conviction pick", votes)
            else:
                _vote("LIMIT", 0.4 + conf * 0.25, source_id, f"{source_id} selective entry", votes)

        for sig in data.get("market_signals", []):
            tickers = {_normalize_symbol(t) for t in sig.get("tickers", [])}
            if sym not in tickers:
                continue
            bias = str(sig.get("bias", "")).upper()
            urgency = str(sig.get("order_type", sig.get("urgency", ""))).upper()
            if urgency in {"MARKET", "LIMIT"}:
                _vote(urgency, 0.55, source_id, sig.get("reason", f"{source_id} signal"), votes)
            elif bias == "BULLISH" and action == "BUY" and horizon == "24h":
                _vote("MARKET", 0.45, source_id, sig.get("reason", "Bullish intraday signal"), votes)
            elif bias == "BEARISH" and action == "SELL":
                _vote("MARKET", 0.6, source_id, sig.get("reason", "Bearish exit signal"), votes)

    if not votes:
        if action == "SELL":
            _vote("MARKET", 0.6, "default", "Agent exit — market sell", votes)
        elif horizon in {"24h", "daily"}:
            _vote("MARKET", 0.55, "default", "Intraday agent trade — market", votes)
        else:
            _vote("LIMIT", 0.55, "default", "Swing agent trade — limit entry", votes)

    return votes


def resolve_order_type(
    symbol: str,
    action: str,
    *,
    price: float = 0.0,
    output_dir: Path | None = None,
    rationale: str = "",
    horizon: str = "1wk",
    confidence: float = 0.55,
    holding: dict[str, Any] | None = None,
) -> OrderTypeDecision:
    """Resolve agent-voted market vs limit for one order."""
    if holding:
        explicit = str(holding.get("order_type", holding.get("price_type", ""))).upper()
        if explicit in {"MARKET", "LIMIT"}:
            limit_px = holding.get("limit_price")
            if explicit == "LIMIT" and limit_px is None and price > 0:
                limit_px = compute_limit_price(
                    price,
                    action,
                    confidence=float(holding.get("confidence", confidence)),
                    horizon=horizon,
                )
            return OrderTypeDecision(
                price_type=explicit,
                limit_price=float(limit_px) if limit_px is not None else None,
                reason=holding.get("order_type_reason", f"Agent portfolio: {explicit.lower()}"),
                sources=list(holding.get("order_type_sources", [])),
            )

    votes = collect_agent_votes(
        symbol,
        action,
        output_dir=output_dir,
        rationale=rationale,
        horizon=horizon,
        confidence=confidence,
    )
    market_score = sum(w for pt, w, _, _ in votes if pt == "MARKET")
    limit_score = sum(w for pt, w, _, _ in votes if pt == "LIMIT")
    price_type = "MARKET" if market_score >= limit_score else "LIMIT"

    notes = [note for pt, _, _, note in votes if pt == price_type]
    top_sources = sorted({src for pt, _, src, _ in votes if pt == price_type})
    reason = notes[0] if notes else f"Agents chose {price_type.lower()}"

    limit_price = None
    if price_type == "LIMIT" and price > 0:
        limit_price = compute_limit_price(price, action, confidence=confidence, horizon=horizon)

    return OrderTypeDecision(
        price_type=price_type,
        limit_price=limit_price,
        reason=reason,
        sources=top_sources,
    )


def apply_to_trade_order(order: Any, decision: OrderTypeDecision) -> None:
    order.price_type = decision.price_type
    order.limit_price = decision.limit_price
    tag = f"{decision.price_type}"
    if decision.price_type == "LIMIT" and decision.limit_price is not None:
        tag = f"LIMIT @ ${decision.limit_price:.2f}"
    if decision.reason and tag not in (order.rationale or ""):
        order.rationale = f"{order.rationale} | {tag}: {decision.reason}".strip(" |")