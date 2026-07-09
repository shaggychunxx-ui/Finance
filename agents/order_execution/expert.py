"""
Order Execution & Market Microstructure Expert Agent
=====================================================
Market analyst view of order types: shifts focus from simple execution
mechanics to managing execution risk vs. price risk, order-book/order-queue
dynamics, and estimated transaction costs (slippage + fees).

Data: Yahoo Finance chart API (3-month daily OHLCV).
"""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agents.base import BaseExpert

CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Finance-Order-Execution/1.0 (shaggychunxx@gmail.com)"}

BENCHMARK = "SPY"
VOLATILITY_SYMBOL = "^VIX"

# Mix of liquidity tiers so the microstructure comparison (deep book vs thin
# book) is grounded in real, current market data rather than only mega-caps.
WATCHLIST: dict[str, str] = {
    "SPY": "S&P 500 (deep liquidity proxy)",
    "AAPL": "Mega-cap tech (deep liquidity)",
    "MSFT": "Mega-cap tech (deep liquidity)",
    "QQQ": "Nasdaq 100 (deep liquidity)",
    "IWM": "Russell 2000 (moderate liquidity)",
    "GME": "Retail-driven small/mid cap (volatile)",
    "COIN": "Crypto-adjacent equity (volatile)",
    "PLTR": "High-beta growth name (moderate-thin liquidity)",
}

# Assumed venue fee schedule used purely to illustrate the maker/taker
# transaction-cost trade-off described by the "typical fees" row of the
# market/limit comparison table. Expressed in basis points (bps) of notional.
TAKER_FEE_BPS = 3.0   # market orders consume liquidity -> pay taker fee
MAKER_FEE_BPS = 0.5   # limit orders that add resting liquidity -> lower/maker fee

DEEP_LIQUIDITY_USD = 200_000_000     # avg daily dollar volume threshold
MODERATE_LIQUIDITY_USD = 25_000_000

GAP_RISK_THRESHOLD_PCT = 3.0  # overnight gap beyond this favors stop-limit over stop-market

ORDER_TYPE_PLAYBOOK: list[dict[str, Any]] = [
    {
        "id": "market_order",
        "name": "Market Order",
        "role": "Liquidity consumer — accepts price risk",
        "primary_objective": "Immediate execution certainty",
        "order_book_role": "Consumes existing liquidity",
        "execution_risk": "Zero (if market is open/liquid)",
        "price_risk": "High (susceptible to slippage)",
        "market_impact": "Can push prices in illiquid markets",
        "typical_fee": "Often higher (taker fee)",
        "key_risks": ["Slippage", "Gapping"],
        "strategic_use_case": (
            "Fast-moving macro catalysts (e.g. surprise rate decisions) where "
            "missing the move is costlier than a few cents of slippage."
        ),
    },
    {
        "id": "limit_order",
        "name": "Limit Order",
        "role": "Liquidity provider — accepts execution risk",
        "primary_objective": "Absolute price protection",
        "order_book_role": "Adds new liquidity",
        "execution_risk": "High (may never execute)",
        "price_risk": "Zero (executed at price or better)",
        "market_impact": "Acts as a support/resistance barrier",
        "typical_fee": "Often lower (maker fee)",
        "key_risks": ["Adverse selection (picked off)", "Opportunity cost"],
        "strategic_use_case": (
            "Large blocks, illiquid small caps, or volatile assets — prevents "
            "HFT front-running and artificial slippage."
        ),
    },
    {
        "id": "stop_market",
        "name": "Stop-Market Order",
        "role": "Conditional liquidity consumer",
        "primary_objective": "Trigger-based exit/entry certainty",
        "order_book_role": "Becomes a market order once triggered",
        "execution_risk": "Zero once triggered",
        "price_risk": "High — no protection from gaps past the trigger",
        "market_impact": "Can accelerate moves during cascading stop-outs",
        "typical_fee": "Taker fee once triggered",
        "key_risks": ["Gapping through the stop", "Slippage on trigger"],
        "strategic_use_case": "Fast stop-loss execution when speed matters more than price.",
    },
    {
        "id": "stop_limit",
        "name": "Stop-Limit Order",
        "role": "Conditional liquidity provider",
        "primary_objective": "Trigger-based price protection",
        "order_book_role": "Becomes a limit order once triggered",
        "execution_risk": "High — may not fill if price crashes past the limit",
        "price_risk": "Zero beyond the limit price",
        "market_impact": "Bounded",
        "typical_fee": "Maker fee if it rests, taker fee if marketable",
        "key_risks": ["Non-execution during a gap/crash"],
        "strategic_use_case": (
            "Protects against catastrophic slippage on an overnight gap, at the "
            "risk of not executing if price crashes past the limit."
        ),
    },
]

MICROSTRUCTURE_COMPARISON: dict[str, dict[str, str]] = {
    row["id"]: {
        "primary_objective": row["primary_objective"],
        "order_book_role": row["order_book_role"],
        "execution_risk": row["execution_risk"],
        "price_risk": row["price_risk"],
        "market_impact": row["market_impact"],
        "typical_fee": row["typical_fee"],
    }
    for row in ORDER_TYPE_PLAYBOOK
}


@dataclass
class SymbolMicrostructure:
    symbol: str
    name: str
    last_close: float
    atr_pct: float
    avg_range_pct: float
    max_overnight_gap_pct: float
    avg_dollar_volume: float
    liquidity_tier: str
    estimated_slippage_bps: float
    market_order_cost_bps: float
    limit_order_cost_bps: float
    recommended_order_type: str
    rationale: str


@dataclass
class OrderExecutionAssessment:
    volatility_regime: str
    execution_risk_signal: str
    price_risk_signal: str
    gap_risk_signal: str
    fee_signal: str
    order_routing_conclusion: str


@dataclass
class OrderExecutionReport:
    vix_level: float | None
    symbols: list[SymbolMicrostructure]
    assessment: OrderExecutionAssessment
    execution_risk_score: float
    price_risk_score: float
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class OrderExecutionExpert(BaseExpert):
    """Expert market analyst — order types, microstructure, and execution cost."""

    def __init__(
        self,
        delay_seconds: float = 0.35,
        *,
        pipeline_context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="order-execution")
        self.delay_seconds = delay_seconds

    def _fetch_ohlcv(self, symbol: str) -> dict[str, list[float]]:
        try:
            resp = requests.get(
                CHART_API.format(symbol=symbol),
                params={"interval": "1d", "range": "3mo"},
                headers=HEADERS,
                timeout=25,
            )
            if resp.status_code == 429:
                time.sleep(3)
                resp = requests.get(
                    CHART_API.format(symbol=symbol),
                    params={"interval": "1d", "range": "3mo"},
                    headers=HEADERS,
                    timeout=25,
                )
            resp.raise_for_status()
            quote = resp.json()["chart"]["result"][0]["indicators"]["quote"][0]
            rows = zip(
                quote.get("open", []),
                quote.get("high", []),
                quote.get("low", []),
                quote.get("close", []),
                quote.get("volume", []),
            )
            opens, highs, lows, closes, volumes = [], [], [], [], []
            for o, h, l, c, v in rows:
                if o is None or h is None or l is None or c is None:
                    continue
                opens.append(float(o))
                highs.append(float(h))
                lows.append(float(l))
                closes.append(float(c))
                volumes.append(float(v) if v is not None else 0.0)
            return {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes}
        except Exception:
            return {"open": [], "high": [], "low": [], "close": [], "volume": []}

    def _fetch_last_close(self, symbol: str) -> float | None:
        data = self._fetch_ohlcv(symbol)
        closes = data["close"]
        return closes[-1] if closes else None

    @staticmethod
    def _true_ranges(data: dict[str, list[float]]) -> list[float]:
        highs, lows, closes = data["high"], data["low"], data["close"]
        ranges: list[float] = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            ranges.append(tr)
        return ranges

    @staticmethod
    def _liquidity_tier(avg_dollar_volume: float) -> str:
        if avg_dollar_volume >= DEEP_LIQUIDITY_USD:
            return "Deep"
        if avg_dollar_volume >= MODERATE_LIQUIDITY_USD:
            return "Moderate"
        return "Thin"

    def _analyze_symbol(self, symbol: str, name: str) -> SymbolMicrostructure | None:
        data = self._fetch_ohlcv(symbol)
        closes = data["close"]
        if len(closes) < 15:
            return None

        last_close = closes[-1]
        window = min(len(closes), 20)
        recent_closes = closes[-window:]
        recent_opens = data["open"][-window:]
        recent_highs = data["high"][-window:]
        recent_lows = data["low"][-window:]
        recent_volumes = data["volume"][-window:]

        true_ranges = self._true_ranges(data)
        atr = statistics.mean(true_ranges[-14:]) if len(true_ranges) >= 1 else 0.0
        atr_pct = (atr / last_close) * 100 if last_close else 0.0

        avg_range_pct = statistics.mean(
            [(h - l) / c * 100 for h, l, c in zip(recent_highs, recent_lows, recent_closes) if c]
        )

        gaps = [
            abs(recent_opens[i] - recent_closes[i - 1]) / recent_closes[i - 1] * 100
            for i in range(1, len(recent_closes))
            if recent_closes[i - 1]
        ]
        max_overnight_gap_pct = max(gaps) if gaps else 0.0

        avg_dollar_volume = statistics.mean(
            [c * v for c, v in zip(recent_closes, recent_volumes)]
        )
        liquidity_tier = self._liquidity_tier(avg_dollar_volume)

        # Slippage proxy: half the average high/low range, scaled up for
        # thinner books where a market order is more likely to "walk the book".
        tier_multiplier = {"Deep": 0.5, "Moderate": 1.0, "Thin": 1.8}[liquidity_tier]
        estimated_slippage_bps = round(avg_range_pct / 2 * tier_multiplier * 100, 2)

        market_order_cost_bps = round(TAKER_FEE_BPS + estimated_slippage_bps, 2)
        limit_order_cost_bps = MAKER_FEE_BPS

        gap_risk = max_overnight_gap_pct >= GAP_RISK_THRESHOLD_PCT
        if liquidity_tier == "Deep" and not gap_risk:
            recommended = "Market order acceptable"
            rationale = (
                f"Deep book (${avg_dollar_volume / 1e6:,.0f}M avg $ volume) with "
                f"low gap risk ({max_overnight_gap_pct:.2f}% max) — slippage cost is minimal."
            )
        elif gap_risk:
            recommended = "Stop-limit over stop-market"
            rationale = (
                f"Max overnight gap of {max_overnight_gap_pct:.2f}% exceeds the "
                f"{GAP_RISK_THRESHOLD_PCT:.1f}% threshold — a stop-market order risks "
                "executing far past the trigger; use a stop-limit to bound price risk."
            )
        elif liquidity_tier == "Thin":
            recommended = "Limit order recommended"
            rationale = (
                f"Thin book (${avg_dollar_volume / 1e6:,.1f}M avg $ volume) — a market "
                f"order would likely walk the book, costing an estimated "
                f"{estimated_slippage_bps:.1f} bps of slippage."
            )
        else:
            recommended = "Marketable limit order recommended"
            rationale = (
                f"Moderate liquidity (${avg_dollar_volume / 1e6:,.1f}M avg $ volume) — "
                "cap slippage with a limit priced at/near the touch."
            )

        return SymbolMicrostructure(
            symbol=symbol,
            name=name,
            last_close=round(last_close, 2),
            atr_pct=round(atr_pct, 2),
            avg_range_pct=round(avg_range_pct, 2),
            max_overnight_gap_pct=round(max_overnight_gap_pct, 2),
            avg_dollar_volume=round(avg_dollar_volume, 0),
            liquidity_tier=liquidity_tier,
            estimated_slippage_bps=estimated_slippage_bps,
            market_order_cost_bps=market_order_cost_bps,
            limit_order_cost_bps=limit_order_cost_bps,
            recommended_order_type=recommended,
            rationale=rationale,
        )

    @staticmethod
    def _volatility_regime(vix: float | None) -> str:
        if vix is None:
            return "Unknown (VIX unavailable)"
        if vix >= 25:
            return "High volatility — elevated slippage/gap risk"
        if vix >= 18:
            return "Moderate volatility — normal execution risk"
        return "Low volatility — calm order books"

    def _assessment(
        self, symbols: list[SymbolMicrostructure], vix: float | None
    ) -> OrderExecutionAssessment:
        regime = self._volatility_regime(vix)
        thin_count = sum(1 for s in symbols if s.liquidity_tier == "Thin")
        gap_flags = sum(1 for s in symbols if s.max_overnight_gap_pct >= GAP_RISK_THRESHOLD_PCT)

        execution_risk_signal = (
            f"{thin_count}/{len(symbols)} symbols in thin books — limit orders there "
            "carry meaningfully higher execution (unfilled) risk."
        )
        price_risk_signal = (
            f"Average estimated market-order slippage of "
            f"{statistics.mean([s.estimated_slippage_bps for s in symbols]):.1f} bps across the watchlist."
        )
        gap_risk_signal = (
            f"{gap_flags}/{len(symbols)} symbols showed an overnight gap ≥ "
            f"{GAP_RISK_THRESHOLD_PCT:.1f}% in the last month — stop-market orders on "
            "these names risk executing far beyond the trigger."
        )
        fee_signal = (
            f"Assumed taker fee {TAKER_FEE_BPS:.1f} bps vs maker fee {MAKER_FEE_BPS:.1f} bps — "
            "limit orders that add liquidity are structurally cheaper when they fill."
        )
        if vix is not None and vix >= 25:
            conclusion = (
                "High-volatility regime: favor limit/stop-limit orders to cap price risk; "
                "reserve market orders for macro catalysts where missing the move is costlier "
                "than slippage."
            )
        elif thin_count >= len(symbols) / 2:
            conclusion = (
                "Book depth is mixed-to-thin across the watchlist: default to limit orders "
                "except in the deepest, most liquid names."
            )
        else:
            conclusion = (
                "Calm, liquid regime: market orders are viable in deep names; limit orders "
                "remain the safer default for thinner or gap-prone names."
            )
        return OrderExecutionAssessment(
            volatility_regime=regime,
            execution_risk_signal=execution_risk_signal,
            price_risk_signal=price_risk_signal,
            gap_risk_signal=gap_risk_signal,
            fee_signal=fee_signal,
            order_routing_conclusion=conclusion,
        )

    def _expert_summary(self, assessment: OrderExecutionAssessment) -> str:
        return (
            f"Order execution scan: {assessment.volatility_regime}. "
            f"{assessment.execution_risk_signal} {assessment.price_risk_signal} "
            f"{assessment.gap_risk_signal} {assessment.fee_signal} "
            f"{assessment.order_routing_conclusion}"
        )

    def _market_signals(self, symbols: list[SymbolMicrostructure]) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        def _keep(symbol: str) -> bool:
            return not self.pipeline_should_skip_symbol(symbol)

        thin = [s.symbol for s in symbols if s.liquidity_tier == "Thin" and _keep(s.symbol)]
        if thin:
            signals.append(
                {
                    "sector": "Microstructure",
                    "bias": "execution-risk",
                    "tickers": thin,
                    "reason": "Thin order books — prefer limit orders over market orders to avoid slippage.",
                }
            )
        gap_prone = [
            s.symbol
            for s in symbols
            if s.max_overnight_gap_pct >= GAP_RISK_THRESHOLD_PCT and _keep(s.symbol)
        ]
        if gap_prone:
            signals.append(
                {
                    "sector": "Microstructure",
                    "bias": "gap-risk",
                    "tickers": gap_prone,
                    "reason": "Elevated overnight gap risk — use stop-limit rather than stop-market orders.",
                }
            )
        deep = [s.symbol for s in symbols if s.liquidity_tier == "Deep" and _keep(s.symbol)]
        if deep:
            signals.append(
                {
                    "sector": "Microstructure",
                    "bias": "execution-safe",
                    "tickers": deep,
                    "reason": "Deep liquidity — market orders carry minimal slippage cost here.",
                }
            )
        return signals

    def _recommendations(
        self, symbols: list[SymbolMicrostructure], assessment: OrderExecutionAssessment
    ) -> list[str]:
        recs = [assessment.order_routing_conclusion]
        for s in sorted(symbols, key=lambda x: -x.estimated_slippage_bps)[:6]:
            recs.append(
                f"{s.symbol} ({s.liquidity_tier} liquidity): {s.recommended_order_type} — "
                f"{s.rationale}"
            )
        return recs

    def analyze(self) -> OrderExecutionReport:
        symbols: list[SymbolMicrostructure] = []
        for symbol, name in WATCHLIST.items():
            row = self._analyze_symbol(symbol, name)
            if row:
                symbols.append(row)
            time.sleep(self.delay_seconds)

        if not any(s.symbol == BENCHMARK for s in symbols):
            raise RuntimeError("Unable to fetch SPY data for order execution analysis")

        vix = self._fetch_last_close(VOLATILITY_SYMBOL)

        assessment = self._assessment(symbols, vix)
        expert_summary = self._expert_summary(assessment)

        execution_risk_score = round(
            sum(1 for s in symbols if s.liquidity_tier != "Deep") / len(symbols) * 10, 1
        )
        price_risk_score = round(
            min(statistics.mean([s.estimated_slippage_bps for s in symbols]) / 5, 10), 1
        )

        return OrderExecutionReport(
            vix_level=round(vix, 2) if vix is not None else None,
            symbols=symbols,
            assessment=assessment,
            execution_risk_score=execution_risk_score,
            price_risk_score=price_risk_score,
            expert_summary=expert_summary,
            market_signals=self._market_signals(symbols),
            recommendations=self._recommendations(symbols, assessment),
            data_source="Yahoo Finance Chart API (3mo daily OHLCV)",
        )

    def to_dict(self, report: OrderExecutionReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Order Execution & Market Microstructure Expert",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
                "temperature": self.temperature,
                "vix_level": report.vix_level,
                "pipeline_memory": {
                    "posture": self.pipeline_context.get("posture"),
                    "lessons": self.pipeline_memory_notes(),
                    "preferred_horizon": self.pipeline_context.get("preferred_horizon"),
                },
            },
            "order_type_playbook": ORDER_TYPE_PLAYBOOK,
            "microstructure_comparison": MICROSTRUCTURE_COMPARISON,
            "symbol_microstructure": [
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "last_close": s.last_close,
                    "atr_pct": s.atr_pct,
                    "avg_range_pct": s.avg_range_pct,
                    "max_overnight_gap_pct": s.max_overnight_gap_pct,
                    "avg_dollar_volume": s.avg_dollar_volume,
                    "liquidity_tier": s.liquidity_tier,
                    "estimated_slippage_bps": s.estimated_slippage_bps,
                    "market_order_cost_bps": s.market_order_cost_bps,
                    "limit_order_cost_bps": s.limit_order_cost_bps,
                    "recommended_order_type": s.recommended_order_type,
                    "rationale": s.rationale,
                }
                for s in report.symbols
            ],
            "execution_assessment": {
                "volatility_regime": a.volatility_regime,
                "execution_risk_signal": a.execution_risk_signal,
                "price_risk_signal": a.price_risk_signal,
                "gap_risk_signal": a.gap_risk_signal,
                "fee_signal": a.fee_signal,
                "order_routing_conclusion": a.order_routing_conclusion,
            },
            "fee_assumptions_bps": {"taker": TAKER_FEE_BPS, "maker": MAKER_FEE_BPS},
            "metrics": {
                "execution_risk_score": report.execution_risk_score,
                "price_risk_score": report.price_risk_score,
            },
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "order_type_playbook.json"
            catalog.write_text(
                json.dumps(ORDER_TYPE_PLAYBOOK, indent=2),
                encoding="utf-8",
            )
        return result


def run_order_execution_analysis(
    output: Path | None = None,
    pipeline_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return OrderExecutionExpert(pipeline_context=pipeline_context).run(output=output)
