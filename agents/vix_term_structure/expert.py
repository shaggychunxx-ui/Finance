"""
VIX Term Structure Expert Agent
================================
Maps the mathematical relationship between expected S&P 500 volatility and
time — Spot VIX vs. VIX9D/VIX3M — and classifies the curve as contango
(baseline/insurance-premium state) or backwardation (crisis state), with the
resulting roll-yield mechanics for short- and long-volatility ETPs.

Data: Yahoo Finance chart API. CBOE VX futures (VX1, VX2, ...) contract
prices are not available via a free public feed, so the curve is proxied
with the CBOE-calculated spot benchmarks (^VIX, ^VIX9D, ^VIX3M) plus the
short-term (VXX) and mid-term (VIXM) VIX futures ETPs, which is disclosed
in every report.
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

SPOT_SYMBOL = "^VIX"
NEAR_SYMBOL = "^VIX9D"
MID_SYMBOL = "^VIX3M"
SHORT_TERM_ETP = "VXX"
MID_TERM_ETP = "VIXM"

SYMBOLS: dict[str, str] = {
    SPOT_SYMBOL: "Spot VIX (CBOE Volatility Index, 30-day SPX option-implied vol)",
    NEAR_SYMBOL: "VIX9D (9-day ultra-near-term implied vol)",
    MID_SYMBOL: "VIX3M / VXV (90-day implied vol)",
    SHORT_TERM_ETP: "iPath Series B S&P 500 VIX Short-Term Futures ETN (M1/M2 blend proxy)",
    MID_TERM_ETP: "ProShares VIX Mid-Term Futures ETF (M4-M7 blend proxy)",
}

# Historical base rate: the VIX term structure sits in contango roughly
# 80%-85% of trading days, flipping to backwardation only during systemic shocks.
CONTANGO_HISTORICAL_FREQUENCY_PCT = 82.5

VIX_VXV_DEEP_CONTANGO = 0.90
VIX_VXV_BACKWARDATION = 1.00

REGIME_PLAYBOOK: list[dict[str, Any]] = [
    {
        "id": "contango",
        "name": "Contango (Baseline State)",
        "historical_frequency": "~80%-85% of trading days",
        "curve_shape": "Upward sloping — Spot VIX < M1 < M2 < M4 < M7",
        "drivers": [
            "Insurance premium: uncertainty compounds further out, so market "
            "makers demand a higher premium to underwrite longer-dated volatility protection.",
            "Variance Risk Premium (VRP): implied volatility is statistically "
            "overpriced relative to realized volatility, embedding a structural "
            "upward tilt into the futures curve.",
        ],
        "roll_yield": "Negative roll yield for long-volatility ETPs — daily rolling "
        "sells the cheaper front-month contract and buys the pricier second-month "
        "contract ('selling low, buying high').",
        "etp_impact": (
            "Structural performance drag on UVXY/VXX-style products from "
            "compounding daily decay."
        ),
        "risk_note": (
            "Short-volatility strategies harvest steady income here, but a sudden "
            "intraday VIX spike can wipe out years of collected premium if positions "
            "are uncorrelated or over-leveraged."
        ),
    },
    {
        "id": "backwardation",
        "name": "Backwardation (Crisis State)",
        "historical_frequency": "~15%-20% of trading days",
        "curve_shape": "Downward sloping — Spot VIX > M1 > M2 > M4 > M7",
        "drivers": [
            "Physics of a volatility spike: institutional managers rush to buy "
            "immediate SPX put protection, bidding up near-term implied vol and "
            "Spot VIX violently.",
            "Front-month futures track the spike closely (imminent expiration); "
            "longer-dated contracts rise far less because traders expect the "
            "panic to subside (e.g. Fed intervention) before those contracts settle.",
        ],
        "roll_yield": "Positive roll yield for long-volatility ETPs — the fund sells "
        "the inflated front-month contract and buys cheaper, longer-dated contracts.",
        "etp_impact": (
            "Additional performance engine for long-volatility traders capturing "
            "convex returns during a sustained market crash."
        ),
        "risk_note": (
            "Risk of short-volatility margin liquidation as near-term contracts "
            "spike faster than the hedge book can absorb."
        ),
    },
]

INDICATOR_PLAYBOOK: list[dict[str, Any]] = [
    {
        "id": "vix_vxv_ratio",
        "name": "VIX / VXV Ratio",
        "equation": "Spot VIX (30-day) / VIX3M (90-day)",
        "thresholds": {
            "< 0.90": "Deep Contango (Strong Bull Market)",
            ">= 1.00": "Cross-over into Backwardation (Risk-off Alarm)",
        },
    },
    {
        "id": "m1_m2_spread",
        "name": "The M1-M2 Spread",
        "equation": "Price of VX2 - Price of VX1",
        "thresholds": {
            "Positive": "Market is normal; short-volatility strategies are highly profitable.",
            "Negative": "Near-term panic; risk of short-volatility margin liquidation.",
        },
    },
    {
        "id": "vix9d_convergence",
        "name": "VIX9D Convergence",
        "equation": "VIX9D - VIX",
        "thresholds": {
            "> 0 and widening": (
                "Localized event (election, CPI print, banking failure) causing "
                "immediate hedging distress in the ultra-near-term."
            ),
        },
    },
]

EXECUTION_GUARDRAILS: list[str] = [
    "Short-volatility volatility-squeezes: steady, consistent income in steep "
    "contango, but a sudden 100% intraday VIX spike can wipe out years of "
    "collected premium in minutes if positions are uncorrelated or over-leveraged.",
    "Long-volatility timing drag: buying long-volatility products to hedge a "
    "stock portfolio acts as a capital bleed via contango — treat as temporary "
    "insurance, not a buy-and-hold position.",
    "Mean reversion caps: VIX rarely drops below 9-10, and historically hits "
    "structural ceilings near 80-90 during panics (2008 Financial Crisis, 2020 Pandemic).",
]

ROLL_WINDOW_TRADING_DAYS = 21


@dataclass
class TermStructurePoint:
    symbol: str
    name: str
    price: float | None
    day_chg_pct: float | None
    week_chg_pct: float | None


@dataclass
class TermStructureAssessment:
    regime: str
    regime_entry: dict[str, Any]
    vix_vix3m_ratio: float | None
    ratio_signal: str
    vix9d_convergence: float | None
    convergence_signal: str
    curve_steepness_proxy: float | None
    roll_drag_1m_pct: float | None
    roll_signal: str


@dataclass
class VixTermStructureReport:
    points: list[TermStructurePoint]
    assessment: TermStructureAssessment
    contango_probability_score: float
    stress_score: float
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class VixTermStructureExpert(BaseExpert):
    """Expert market analyst — VIX term structure regime, roll yield, and guardrails."""

    def __init__(
        self,
        delay_seconds: float = 0.35,
        *,
        pipeline_context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="vix-term-structure")
        self.delay_seconds = delay_seconds

    def _fetch_point(self, symbol: str, name: str) -> TermStructurePoint | None:
        meta = self.fetch_yahoo_chart_meta(symbol, range_="3mo", interval="1d")
        if not meta or meta.get("price") is None:
            return None
        return TermStructurePoint(
            symbol=symbol,
            name=name,
            price=round(float(meta["price"]), 2),
            day_chg_pct=meta.get("day_chg_pct"),
            week_chg_pct=meta.get("week_chg_pct"),
        )

    def _roll_drag_1m_pct(self) -> float | None:
        """Cumulative 1-month return spread between the short-term VIX ETP and Spot VIX.

        A more negative spread reflects the negative roll yield ("drag") that
        contango imposes on daily-rolling short-term VIX futures ETPs relative
        to the spot index they are meant to track.
        """
        vix_closes = self.fetch_yahoo_closes(SPOT_SYMBOL, range_="2mo", interval="1d")
        etp_closes = self.fetch_yahoo_closes(SHORT_TERM_ETP, range_="2mo", interval="1d")
        if len(vix_closes) <= ROLL_WINDOW_TRADING_DAYS or len(etp_closes) <= ROLL_WINDOW_TRADING_DAYS:
            return None
        vix_ret = (vix_closes[-1] / vix_closes[-ROLL_WINDOW_TRADING_DAYS] - 1) * 100
        etp_ret = (etp_closes[-1] / etp_closes[-ROLL_WINDOW_TRADING_DAYS] - 1) * 100
        return round(etp_ret - vix_ret, 2)

    @staticmethod
    def _ratio_signal(ratio: float | None) -> str:
        if ratio is None:
            return "VIX/VXV ratio unavailable"
        if ratio < VIX_VXV_DEEP_CONTANGO:
            return f"Deep Contango (Strong Bull Market) — ratio {ratio:.2f} < {VIX_VXV_DEEP_CONTANGO:.2f}"
        if ratio >= VIX_VXV_BACKWARDATION:
            return f"Cross-over into Backwardation (Risk-off Alarm) — ratio {ratio:.2f} >= {VIX_VXV_BACKWARDATION:.2f}"
        return f"Normal Contango — ratio {ratio:.2f}"

    @staticmethod
    def _convergence_signal(convergence: float | None) -> str:
        if convergence is None:
            return "VIX9D convergence unavailable"
        if convergence > 1.0:
            return (
                f"VIX9D running {convergence:+.2f} pts above VIX — localized "
                "near-term hedging distress (event risk)"
            )
        if convergence < -1.0:
            return f"VIX9D running {convergence:+.2f} pts below VIX — near-term calm relative to the 30-day window"
        return f"VIX9D broadly converged with VIX ({convergence:+.2f} pts)"

    @staticmethod
    def _roll_signal(roll_drag: float | None) -> str:
        if roll_drag is None:
            return "Roll-yield proxy unavailable"
        if roll_drag <= -3.0:
            return (
                f"Negative roll yield drag of {roll_drag:+.2f}% over the trailing month — "
                f"{SHORT_TERM_ETP} underperforming Spot VIX as contango decay compounds"
            )
        if roll_drag >= 3.0:
            return (
                f"Positive roll yield of {roll_drag:+.2f}% over the trailing month — "
                f"{SHORT_TERM_ETP} outperforming Spot VIX, consistent with backwardation"
            )
        return f"Roll-yield proxy roughly flat ({roll_drag:+.2f}% over the trailing month)"

    def _assessment(
        self,
        by_sym: dict[str, TermStructurePoint],
    ) -> TermStructureAssessment:
        spot = by_sym.get(SPOT_SYMBOL)
        mid = by_sym.get(MID_SYMBOL)
        near = by_sym.get(NEAR_SYMBOL)
        short_etp = by_sym.get(SHORT_TERM_ETP)
        mid_etp = by_sym.get(MID_TERM_ETP)

        ratio = (
            round(spot.price / mid.price, 3)
            if spot and mid and spot.price and mid.price
            else None
        )
        convergence = (
            round(near.price - spot.price, 2) if near and spot and near.price is not None and spot.price is not None else None
        )
        curve_steepness = (
            round(mid_etp.day_chg_pct - short_etp.day_chg_pct, 2)
            if mid_etp
            and short_etp
            and mid_etp.day_chg_pct is not None
            and short_etp.day_chg_pct is not None
            else None
        )
        roll_drag = self._roll_drag_1m_pct()

        if ratio is not None and ratio >= VIX_VXV_BACKWARDATION:
            regime = "Backwardation"
        else:
            regime = "Contango"
        regime_entry = next(
            (r for r in REGIME_PLAYBOOK if r["id"] == regime.lower()), REGIME_PLAYBOOK[0]
        )

        return TermStructureAssessment(
            regime=regime,
            regime_entry=regime_entry,
            vix_vix3m_ratio=ratio,
            ratio_signal=self._ratio_signal(ratio),
            vix9d_convergence=convergence,
            convergence_signal=self._convergence_signal(convergence),
            curve_steepness_proxy=curve_steepness,
            roll_drag_1m_pct=roll_drag,
            roll_signal=self._roll_signal(roll_drag),
        )

    def _expert_summary(
        self, assessment: TermStructureAssessment, spot: TermStructurePoint | None
    ) -> str:
        level = f"Spot VIX at {spot.price:.2f}" if spot and spot.price is not None else "Spot VIX level unavailable"
        return (
            f"{level}. Term structure regime: {assessment.regime} "
            f"({assessment.regime_entry.get('curve_shape')}). "
            f"{assessment.ratio_signal}. {assessment.convergence_signal}. {assessment.roll_signal}."
        )

    def _market_signals(self, assessment: TermStructureAssessment) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal

        signals: list[dict[str, Any]] = []
        if assessment.regime == "Backwardation":
            bias = "BULLISH"
            reason = f"Term structure flipped to backwardation ({assessment.ratio_signal})"
            confidence = 0.68
        elif assessment.vix_vix3m_ratio is not None and assessment.vix_vix3m_ratio < VIX_VXV_DEEP_CONTANGO:
            bias = "BEARISH"
            reason = f"Deep contango — {assessment.ratio_signal}"
            confidence = 0.55
        else:
            bias = "NEUTRAL"
            reason = assessment.ratio_signal
            confidence = 0.45
        signals.append(
            build_market_signal(
                sector="Volatility / VIX Term Structure",
                tickers=["VXX", "UVXY", "VIXM", "SVXY"],
                bias=bias,
                reason=reason,
                confidence=self.adjust_signal_confidence("VXX", bias, confidence),
                evidence={
                    "regime": assessment.regime,
                    "vix_vix3m_ratio": assessment.vix_vix3m_ratio,
                    "vix9d_convergence": assessment.vix9d_convergence,
                    "roll_drag_1m_pct": assessment.roll_drag_1m_pct,
                },
            )
        )
        if assessment.vix9d_convergence is not None and assessment.vix9d_convergence > 1.5:
            signals.append(
                build_market_signal(
                    sector="Ultra-near-term event risk",
                    tickers=["SPY", "VXX"],
                    bias="BEARISH",
                    reason=assessment.convergence_signal,
                    confidence=self.adjust_signal_confidence("SPY", "BEARISH", 0.5),
                )
            )
        return signals

    def _recommendations(self, assessment: TermStructureAssessment) -> list[str]:
        recs = [
            f"Regime: {assessment.regime} — {assessment.regime_entry.get('curve_shape')}",
            assessment.ratio_signal,
            assessment.convergence_signal,
            assessment.roll_signal,
            assessment.regime_entry.get("risk_note", ""),
        ]
        recs.extend(EXECUTION_GUARDRAILS)
        return [r for r in recs if r]

    def analyze(self) -> VixTermStructureReport:
        points: list[TermStructurePoint] = []
        for symbol, name in SYMBOLS.items():
            point = self._fetch_point(symbol, name)
            if point:
                points.append(point)
            time.sleep(self.delay_seconds)

        if not any(p.symbol == SPOT_SYMBOL for p in points):
            raise RuntimeError("Unable to fetch VIX data for vix-term-structure analysis")

        by_sym = {p.symbol: p for p in points}
        assessment = self._assessment(by_sym)
        spot = by_sym.get(SPOT_SYMBOL)

        contango_probability_score = (
            round(min(1.0, max(0.0, 1.0 - (assessment.vix_vix3m_ratio - 0.75))), 3)
            if assessment.vix_vix3m_ratio is not None
            else round(CONTANGO_HISTORICAL_FREQUENCY_PCT / 100, 3)
        )
        stress_parts = [
            v
            for v in (
                assessment.vix9d_convergence,
                -(assessment.roll_drag_1m_pct) if assessment.roll_drag_1m_pct is not None else None,
            )
            if v is not None
        ]
        stress_score = round(statistics.mean(stress_parts), 2) if stress_parts else 0.0

        summary = self._expert_summary(assessment, spot)
        signals = self._market_signals(assessment)
        recs = self.append_memory_recommendations(self._recommendations(assessment))

        return VixTermStructureReport(
            points=points,
            assessment=assessment,
            contango_probability_score=contango_probability_score,
            stress_score=stress_score,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source=(
                "Yahoo Finance API (^VIX, ^VIX9D, ^VIX3M spot benchmarks; "
                "VXX/VIXM ETPs as VX futures curve proxies)"
            ),
        )

    def to_dict(self, report: VixTermStructureReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "VIX Term Structure Expert",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
                "temperature": self.temperature,
                "methodology_note": (
                    "CBOE VX futures contract prices (VX1, VX2, ...) are not available "
                    "via a free public feed. The curve is proxied with the CBOE-calculated "
                    "spot benchmarks (^VIX, ^VIX9D, ^VIX3M) plus VXX/VIXM ETP price action."
                ),
                "pipeline_memory": {
                    "posture": self.pipeline_context.get("posture"),
                    "lessons": self.pipeline_memory_notes(),
                    "preferred_horizon": self.pipeline_context.get("preferred_horizon"),
                },
            },
            "regime_playbook": REGIME_PLAYBOOK,
            "indicator_playbook": INDICATOR_PLAYBOOK,
            "execution_guardrails": EXECUTION_GUARDRAILS,
            "term_structure_points": [
                {
                    "symbol": p.symbol,
                    "name": p.name,
                    "price": p.price,
                    "day_chg_pct": p.day_chg_pct,
                    "week_chg_pct": p.week_chg_pct,
                }
                for p in report.points
            ],
            "assessment": {
                "regime": a.regime,
                "regime_entry": a.regime_entry,
                "vix_vix3m_ratio": a.vix_vix3m_ratio,
                "ratio_signal": a.ratio_signal,
                "vix9d_convergence": a.vix9d_convergence,
                "convergence_signal": a.convergence_signal,
                "curve_steepness_proxy": a.curve_steepness_proxy,
                "roll_drag_1m_pct": a.roll_drag_1m_pct,
                "roll_signal": a.roll_signal,
            },
            "metrics": {
                "contango_probability_score": report.contango_probability_score,
                "stress_score": report.stress_score,
                "contango_historical_frequency_pct": CONTANGO_HISTORICAL_FREQUENCY_PCT,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "vix_term_structure_indicators.json"
            catalog.write_text(
                json.dumps(INDICATOR_PLAYBOOK, indent=2),
                encoding="utf-8",
            )
        return result


def run_vix_term_structure_analysis(
    output: Path | None = None,
    pipeline_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return VixTermStructureExpert(pipeline_context=pipeline_context).run(output=output)
