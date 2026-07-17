"""
Crowding vs. Quality Expert Agent
=================================
Institutional short-selling framework that scores names on two independent
axes: Crowding (structural mechanics/liquidity constraints of the equity
lending market) and Quality (the fundamental validity and stability of the
short thesis). Classifies each watchlist symbol into one of four quadrants:

    Sweet Spot        — high quality, uncrowded  (orderly structural decay)
    Crowded Quality    — high quality, crowded    (fee-decay risk)
    Squeeze Zone       — low quality, crowded     (capital-ruin risk)
    Low-Conviction Noise — low quality, uncrowded (technical/hedge flow)

Data: Yahoo Finance chart API (3-month daily OHLCV). There is no public,
free feed for real-time short interest, utilization, or borrow fees, so
Utilization Rate, Cost to Borrow, and Days to Cover are calibrated proxies
derived from realized volatility, volume intensity, and liquidity tier —
not live equity-lending market data.
"""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base import BaseExpert

BENCHMARK = "SPY"

# Shared watchlist mix (deep-liquidity mega caps through retail-dominated,
# thin-float names) so the crowding/quality contrast is grounded in real,
# current market data spanning the full spectrum of the framework.
WATCHLIST: dict[str, str] = {
    "SPY": "S&P 500 (index, deep liquidity)",
    "AAPL": "Mega-cap tech (institutional-led float)",
    "MSFT": "Mega-cap tech (institutional-led float)",
    "QQQ": "Nasdaq 100 (index, deep liquidity)",
    "IWM": "Russell 2000 (index, moderate liquidity)",
    "GME": "Retail-driven small/mid cap (thin float)",
    "COIN": "Crypto-adjacent equity (retail-led float)",
    "PLTR": "High-beta growth name (retail-led float)",
}

# Structural stability proxy: who holds the long side of the float.
# Institutional/passive-dominated float rarely gets recalled abruptly;
# retail-dominated float is fragmented and can be pulled from lending
# programs on short notice.
OWNERSHIP_TAG: dict[str, str] = {
    "SPY": "Institutional-led",
    "AAPL": "Institutional-led",
    "MSFT": "Institutional-led",
    "QQQ": "Institutional-led",
    "IWM": "Mixed",
    "GME": "Retail-led",
    "COIN": "Retail-led",
    "PLTR": "Retail-led",
}
OWNERSHIP_SCORE: dict[str, float] = {
    "Institutional-led": 8.5,
    "Mixed": 5.0,
    "Retail-led": 2.0,
}

# Alpha-origin baseline classification. Index/ETF short interest is mostly
# price-insensitive hedging flow; single names default to a fundamental
# directional bucket unless recent price action looks parabolic/technical.
ALPHA_ORIGIN_TAG: dict[str, str] = {
    "SPY": "Index/Pair-Trading Hedge",
    "QQQ": "Index/Pair-Trading Hedge",
    "IWM": "Index/Pair-Trading Hedge",
    "AAPL": "Fundamental Directional",
    "MSFT": "Fundamental Directional",
    "GME": "Retail Momentum/Technical",
    "COIN": "Retail Momentum/Technical",
    "PLTR": "Fundamental Directional",
}
ALPHA_ORIGIN_SCORE: dict[str, float] = {
    "Index/Pair-Trading Hedge": 6.0,
    "Fundamental Directional": 8.0,
    "Retail Momentum/Technical": 2.0,
}
PARABOLIC_5D_RETURN_THRESHOLD_PCT = 15.0  # override to "technical" alpha origin above this

TRADING_DAYS_PER_YEAR = 252

DEEP_LIQUIDITY_USD = 200_000_000
MODERATE_LIQUIDITY_USD = 25_000_000

UTILIZATION_DEEP_THRESHOLD_PCT = 50.0
UTILIZATION_SPECIAL_THRESHOLD_PCT = 85.0
GC_RATE_BPS = 25.0          # general collateral baseline (~0.25%)
SPECIAL_RATE_FLOOR_BPS = 500.0  # ~5% annualized, entry point into "specials"

CROWDING_THRESHOLD = 6.0
QUALITY_THRESHOLD = 6.0

QUADRANT_LABELS: dict[tuple[bool, bool], str] = {
    (True, False): "Sweet Spot — Orderly Structural Decay",
    (True, True): "Crowded Quality — Fee-Decay Risk",
    (False, True): "Squeeze Zone — Capital-Ruin Risk",
    (False, False): "Low-Conviction Noise — Technical/Hedge Flow",
}


@dataclass
class SymbolCrowdingQuality:
    symbol: str
    name: str
    last_close: float
    ownership: str
    alpha_origin: str
    liquidity_tier: str
    utilization_pct: float
    cost_to_borrow_bps: float
    days_to_cover: float
    pct_from_high: float
    realized_vol_pct: float
    crowding_score: float
    quality_score: float
    fundamental_decay_score: float
    quadrant: str
    rationale: str


@dataclass
class CrowdingQualityAssessment:
    crowding_regime: str
    quality_regime: str
    squeeze_watch: str
    sweet_spot_watch: str
    conclusion: str


@dataclass
class CrowdingQualityReport:
    symbols: list[SymbolCrowdingQuality]
    assessment: CrowdingQualityAssessment
    avg_crowding_score: float
    avg_quality_score: float
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CrowdingQualityExpert(BaseExpert):
    """Expert market analyst — short-crowding mechanics vs. short-thesis quality."""

    def __init__(
        self,
        delay_seconds: float = 0.35,
        *,
        pipeline_context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="crowding-quality")
        self.delay_seconds = delay_seconds

    @staticmethod
    def _liquidity_tier(avg_dollar_volume: float) -> str:
        if avg_dollar_volume >= DEEP_LIQUIDITY_USD:
            return "Deep"
        if avg_dollar_volume >= MODERATE_LIQUIDITY_USD:
            return "Moderate"
        return "Thin"

    @staticmethod
    def _utilization_pct(volume_ratio: float) -> float:
        # ratio == 1.0 (recent volume in line with trailing average) maps to
        # a baseline ~40% utilization; sustained volume spikes push toward
        # (and past) the 85%+ "special" bottleneck threshold.
        return round(max(0.0, min(100.0, 40.0 + volume_ratio * 20.0)), 1)

    @staticmethod
    def _cost_to_borrow_bps(utilization_pct: float) -> float:
        if utilization_pct < UTILIZATION_DEEP_THRESHOLD_PCT:
            return GC_RATE_BPS
        if utilization_pct < UTILIZATION_SPECIAL_THRESHOLD_PCT:
            span = UTILIZATION_SPECIAL_THRESHOLD_PCT - UTILIZATION_DEEP_THRESHOLD_PCT
            progress = (utilization_pct - UTILIZATION_DEEP_THRESHOLD_PCT) / span
            return round(GC_RATE_BPS + progress * (SPECIAL_RATE_FLOOR_BPS - GC_RATE_BPS), 1)
        overshoot = utilization_pct - UTILIZATION_SPECIAL_THRESHOLD_PCT
        return round(SPECIAL_RATE_FLOOR_BPS + overshoot * 50.0, 1)

    @staticmethod
    def _days_to_cover(liquidity_tier: str, utilization_pct: float) -> float:
        baseline = {"Deep": 1.5, "Moderate": 3.5, "Thin": 7.0}[liquidity_tier]
        return round(baseline * (0.7 + (utilization_pct / 100.0) * 0.6), 2)

    @staticmethod
    def _fundamental_decay_score(pct_from_high: float, realized_vol_pct: float) -> float:
        decline_component = min(1.0, pct_from_high / 40.0)
        chaos_penalty = min(1.0, max(0.0, realized_vol_pct - 60.0) / 100.0)
        return round(10.0 * decline_component * (1.0 - chaos_penalty), 1)

    def _analyze_symbol(self, symbol: str, name: str) -> SymbolCrowdingQuality | None:
        data = self.fetch_yahoo_ohlcv(symbol, range_="3mo", interval="1d")
        closes = data.get("close", [])
        volumes = data.get("volume", [])
        if len(closes) < 25:
            return None

        last_close = closes[-1]
        returns = [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes))
            if closes[i - 1]
        ]
        realized_vol_pct = (
            round(statistics.pstdev(returns) * (TRADING_DAYS_PER_YEAR ** 0.5) * 100, 2) if len(returns) >= 2 else 0.0
        )

        period_high = max(closes)
        pct_from_high = round((period_high - last_close) / period_high * 100, 2) if period_high else 0.0

        window = min(len(closes), 20)
        avg_dollar_volume = statistics.mean(
            [c * v for c, v in zip(closes[-window:], volumes[-window:])]
        )
        liquidity_tier = self._liquidity_tier(avg_dollar_volume)

        recent_avg_vol = statistics.mean(volumes[-5:]) if len(volumes) >= 5 else statistics.mean(volumes)
        base_window = volumes[-65:-5] if len(volumes) >= 65 else volumes[:-5] or volumes
        base_avg_vol = statistics.mean(base_window) if base_window else recent_avg_vol
        volume_ratio = (recent_avg_vol / base_avg_vol) if base_avg_vol else 1.0

        max_5d_return_pct = (
            round((closes[-1] - closes[-6]) / closes[-6] * 100, 2) if len(closes) >= 6 and closes[-6] else 0.0
        )

        utilization_pct = self._utilization_pct(volume_ratio)
        cost_to_borrow_bps = self._cost_to_borrow_bps(utilization_pct)
        days_to_cover = self._days_to_cover(liquidity_tier, utilization_pct)

        ownership = OWNERSHIP_TAG.get(symbol, "Mixed")
        alpha_origin = ALPHA_ORIGIN_TAG.get(symbol, "Fundamental Directional")
        if max_5d_return_pct >= PARABOLIC_5D_RETURN_THRESHOLD_PCT:
            alpha_origin = "Retail Momentum/Technical"

        fundamental_decay_score = self._fundamental_decay_score(pct_from_high, realized_vol_pct)

        crowding_score = round(
            10.0 * (
                0.45 * (utilization_pct / 100.0)
                + 0.35 * min(1.0, cost_to_borrow_bps / 1000.0)
                + 0.20 * min(1.0, days_to_cover / 10.0)
            ),
            1,
        )
        quality_score = round(
            0.4 * OWNERSHIP_SCORE.get(ownership, 5.0)
            + 0.3 * fundamental_decay_score
            + 0.3 * ALPHA_ORIGIN_SCORE.get(alpha_origin, 5.0),
            1,
        )

        is_crowded = crowding_score >= CROWDING_THRESHOLD
        is_high_quality = quality_score >= QUALITY_THRESHOLD
        quadrant = QUADRANT_LABELS[(is_high_quality, is_crowded)]

        rationale = (
            f"Utilization≈{utilization_pct:.0f}%, CTB≈{cost_to_borrow_bps:.0f}bps, "
            f"DTC≈{days_to_cover:.1f}d ({liquidity_tier} liquidity) vs. {ownership.lower()} "
            f"float and {alpha_origin.lower()} — {pct_from_high:.1f}% off highs at "
            f"{realized_vol_pct:.0f}% realized vol."
        )

        return SymbolCrowdingQuality(
            symbol=symbol,
            name=name,
            last_close=round(last_close, 2),
            ownership=ownership,
            alpha_origin=alpha_origin,
            liquidity_tier=liquidity_tier,
            utilization_pct=utilization_pct,
            cost_to_borrow_bps=cost_to_borrow_bps,
            days_to_cover=days_to_cover,
            pct_from_high=pct_from_high,
            realized_vol_pct=realized_vol_pct,
            crowding_score=crowding_score,
            quality_score=quality_score,
            fundamental_decay_score=fundamental_decay_score,
            quadrant=quadrant,
            rationale=rationale,
        )

    @staticmethod
    def _assessment(symbols: list[SymbolCrowdingQuality]) -> CrowdingQualityAssessment:
        avg_crowding = statistics.mean([s.crowding_score for s in symbols])
        avg_quality = statistics.mean([s.quality_score for s in symbols])
        squeeze = [s.symbol for s in symbols if s.quadrant.startswith("Squeeze Zone")]
        sweet_spot = [s.symbol for s in symbols if s.quadrant.startswith("Sweet Spot")]

        crowding_regime = (
            f"Average crowding score {avg_crowding:.1f}/10 — "
            + ("borrow supply is broadly tight across the watchlist." if avg_crowding >= CROWDING_THRESHOLD
               else "borrow supply is broadly ample across the watchlist.")
        )
        quality_regime = (
            f"Average quality score {avg_quality:.1f}/10 — "
            + ("thesis structure skews toward orderly, institutionally-anchored setups."
               if avg_quality >= QUALITY_THRESHOLD
               else "thesis structure skews toward fragile, retail-anchored setups.")
        )
        squeeze_watch = (
            f"Squeeze Zone (crowded + low quality): {', '.join(squeeze)}."
            if squeeze else "No names currently sit in the Squeeze Zone quadrant."
        )
        sweet_spot_watch = (
            f"Sweet Spot (uncrowded + high quality): {', '.join(sweet_spot)}."
            if sweet_spot else "No names currently sit in the Sweet Spot quadrant."
        )
        if squeeze:
            conclusion = (
                "Prioritize de-risking or hedging Squeeze Zone names — high utilization and "
                "borrow-fee spikes there raise the odds of a forced buy-in cascade regardless "
                "of how bearish the fundamental narrative looks."
            )
        elif sweet_spot:
            conclusion = (
                "Sweet Spot names offer the best risk-adjusted short carry — orderly decay, "
                "stable institutional float, and ample borrow supply."
            )
        else:
            conclusion = (
                "No extreme quadrant readings — monitor utilization and cost-to-borrow trends "
                "for regime shifts before sizing up any short book."
            )
        return CrowdingQualityAssessment(
            crowding_regime=crowding_regime,
            quality_regime=quality_regime,
            squeeze_watch=squeeze_watch,
            sweet_spot_watch=sweet_spot_watch,
            conclusion=conclusion,
        )

    def _expert_summary(self, assessment: CrowdingQualityAssessment) -> str:
        return (
            f"Crowding vs. Quality scan: {assessment.crowding_regime} {assessment.quality_regime} "
            f"{assessment.squeeze_watch} {assessment.sweet_spot_watch} {assessment.conclusion}"
        )

    def _market_signals(self, symbols: list[SymbolCrowdingQuality]) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        def _keep(symbol: str) -> bool:
            return not self.pipeline_should_skip_symbol(symbol)

        squeeze = [s for s in symbols if s.quadrant.startswith("Squeeze Zone") and _keep(s.symbol)]
        if squeeze:
            signals.append(
                {
                    "sector": "Short Crowding",
                    "bias": "squeeze-risk",
                    "tickers": [s.symbol for s in squeeze],
                    "reason": (
                        "High utilization/borrow-fee crowding paired with low-quality, "
                        "retail-anchored float — elevated forced buy-in risk."
                    ),
                }
            )
        sweet_spot = [s for s in symbols if s.quadrant.startswith("Sweet Spot") and _keep(s.symbol)]
        if sweet_spot:
            signals.append(
                {
                    "sector": "Short Thesis Quality",
                    "bias": "BEARISH",
                    "tickers": [s.symbol for s in sweet_spot],
                    "reason": (
                        "Orderly structural decay with ample borrow supply — favorable "
                        "risk-adjusted short carry."
                    ),
                }
            )
        crowded_quality = [
            s for s in symbols if s.quadrant.startswith("Crowded Quality") and _keep(s.symbol)
        ]
        if crowded_quality:
            signals.append(
                {
                    "sector": "Short Crowding",
                    "bias": "fee-decay-risk",
                    "tickers": [s.symbol for s in crowded_quality],
                    "reason": (
                        "Valid thesis but tight borrow — net-of-fee alpha decays quickly; "
                        "size down or use synthetic shorts."
                    ),
                }
            )
        return signals

    def _recommendations(
        self, symbols: list[SymbolCrowdingQuality], assessment: CrowdingQualityAssessment
    ) -> list[str]:
        recs = [assessment.conclusion, assessment.squeeze_watch, assessment.sweet_spot_watch]
        for s in sorted(symbols, key=lambda x: -x.crowding_score)[:6]:
            recs.append(f"{s.symbol} [{s.quadrant}]: {s.rationale}")
        return recs

    def analyze(self) -> CrowdingQualityReport:
        symbols: list[SymbolCrowdingQuality] = []
        for symbol, name in WATCHLIST.items():
            row = self._analyze_symbol(symbol, name)
            if row:
                symbols.append(row)
            time.sleep(self.delay_seconds)

        if not any(s.symbol == BENCHMARK for s in symbols):
            raise RuntimeError("Unable to fetch SPY data for crowding-quality analysis")

        assessment = self._assessment(symbols)
        expert_summary = self._expert_summary(assessment)

        return CrowdingQualityReport(
            symbols=symbols,
            assessment=assessment,
            avg_crowding_score=round(statistics.mean([s.crowding_score for s in symbols]), 1),
            avg_quality_score=round(statistics.mean([s.quality_score for s in symbols]), 1),
            expert_summary=expert_summary,
            market_signals=self._market_signals(symbols),
            recommendations=self._recommendations(symbols, assessment),
            data_source=(
                "Yahoo Finance Chart API (3mo daily OHLCV) — utilization/cost-to-borrow/"
                "days-to-cover are calibrated proxies, not a live equity-lending feed."
            ),
        )

    def to_dict(self, report: CrowdingQualityReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Crowding vs. Quality Expert",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
                "temperature": self.temperature,
                "pipeline_memory": {
                    "posture": self.pipeline_context.get("posture"),
                    "lessons": self.pipeline_memory_notes(),
                    "preferred_horizon": self.pipeline_context.get("preferred_horizon"),
                },
            },
            "framework": {
                "axes": ["Crowding (structural mechanics/liquidity)", "Quality (thesis validity/stability)"],
                "quadrants": sorted(set(QUADRANT_LABELS.values())),
                "crowding_threshold": CROWDING_THRESHOLD,
                "quality_threshold": QUALITY_THRESHOLD,
            },
            "symbol_crowding_quality": [
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "last_close": s.last_close,
                    "ownership": s.ownership,
                    "alpha_origin": s.alpha_origin,
                    "liquidity_tier": s.liquidity_tier,
                    "utilization_pct": s.utilization_pct,
                    "cost_to_borrow_bps": s.cost_to_borrow_bps,
                    "days_to_cover": s.days_to_cover,
                    "pct_from_high": s.pct_from_high,
                    "realized_vol_pct": s.realized_vol_pct,
                    "crowding_score": s.crowding_score,
                    "quality_score": s.quality_score,
                    "fundamental_decay_score": s.fundamental_decay_score,
                    "quadrant": s.quadrant,
                    "rationale": s.rationale,
                }
                for s in report.symbols
            ],
            "crowding_quality_assessment": {
                "crowding_regime": a.crowding_regime,
                "quality_regime": a.quality_regime,
                "squeeze_watch": a.squeeze_watch,
                "sweet_spot_watch": a.sweet_spot_watch,
                "conclusion": a.conclusion,
            },
            "metrics": {
                "avg_crowding_score": report.avg_crowding_score,
                "avg_quality_score": report.avg_quality_score,
            },
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "crowding_quality_framework.json"
            catalog.write_text(
                json.dumps(result["framework"], indent=2),
                encoding="utf-8",
            )
        return result


def run_crowding_quality_analysis(
    output: Path | None = None,
    pipeline_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return CrowdingQualityExpert(pipeline_context=pipeline_context).run(output=output)
