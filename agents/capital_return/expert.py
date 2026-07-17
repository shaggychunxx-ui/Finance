"""
Capital Return Strategy Expert Agent
=====================================
Analyzes how mature corporations deploy excess free cash flow between the two
dominant shareholder-return vectors — cash dividends and share buybacks —
and where each covered ticker sits in the corporate capital-allocation
life cycle (high-growth disrupter, maturing growth, or mature cash cow).

Data: Yahoo Finance chart API (live price / 52-week range) blended with
curated dividend-yield, buyback-yield, payout-ratio, ROIC and WACC profiles,
since granular fundamentals (payout ratios, buyback authorizations) are not
exposed by the public chart endpoint.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base import BaseExpert

DASHBOARD_URL = "https://finance.yahoo.com/"

# Curated capital-return profiles across the corporate life cycle.
# dividend_yield_pct / buyback_yield_pct / payout_ratio_pct / roic_pct / wacc_pct
# are approximate, slowly-changing fundamentals used alongside live price data.
CAPITAL_RETURN_PROFILES: dict[str, dict[str, Any]] = {
    "TSLA": {
        "name": "Tesla, Inc.",
        "sector": "Consumer Discretionary",
        "stage": "High-Growth Disrupter",
        "dividend_yield_pct": 0.0,
        "buyback_yield_pct": 0.0,
        "payout_ratio_pct": 0.0,
        "roic_pct": 8.0,
        "wacc_pct": 9.5,
    },
    "PLTR": {
        "name": "Palantir Technologies Inc.",
        "sector": "Technology",
        "stage": "High-Growth Disrupter",
        "dividend_yield_pct": 0.0,
        "buyback_yield_pct": 0.0,
        "payout_ratio_pct": 0.0,
        "roic_pct": 5.0,
        "wacc_pct": 10.0,
    },
    "META": {
        "name": "Meta Platforms, Inc.",
        "sector": "Communication Services",
        "stage": "Maturing Growth (Opportunistic Buybacks)",
        "dividend_yield_pct": 0.3,
        "buyback_yield_pct": 2.0,
        "payout_ratio_pct": 8.0,
        "roic_pct": 25.0,
        "wacc_pct": 9.0,
    },
    "GOOGL": {
        "name": "Alphabet Inc.",
        "sector": "Communication Services",
        "stage": "Maturing Growth (Opportunistic Buybacks)",
        "dividend_yield_pct": 0.4,
        "buyback_yield_pct": 2.8,
        "payout_ratio_pct": 10.0,
        "roic_pct": 28.0,
        "wacc_pct": 9.0,
    },
    "AMZN": {
        "name": "Amazon.com, Inc.",
        "sector": "Consumer Discretionary",
        "stage": "Maturing Growth (Opportunistic Buybacks)",
        "dividend_yield_pct": 0.0,
        "buyback_yield_pct": 0.3,
        "payout_ratio_pct": 0.0,
        "roic_pct": 12.0,
        "wacc_pct": 9.0,
    },
    "AAPL": {
        "name": "Apple Inc.",
        "sector": "Technology",
        "stage": "Mature Cash Cow (Dual-Engine Total Yield)",
        "dividend_yield_pct": 0.45,
        "buyback_yield_pct": 3.5,
        "payout_ratio_pct": 15.0,
        "roic_pct": 50.0,
        "wacc_pct": 9.0,
    },
    "MSFT": {
        "name": "Microsoft Corporation",
        "sector": "Technology",
        "stage": "Mature Cash Cow (Dual-Engine Total Yield)",
        "dividend_yield_pct": 0.7,
        "buyback_yield_pct": 1.6,
        "payout_ratio_pct": 25.0,
        "roic_pct": 30.0,
        "wacc_pct": 9.0,
    },
    "JNJ": {
        "name": "Johnson & Johnson",
        "sector": "Health Care",
        "stage": "Mature Cash Cow (Dual-Engine Total Yield)",
        "dividend_yield_pct": 3.0,
        "buyback_yield_pct": 1.0,
        "payout_ratio_pct": 45.0,
        "roic_pct": 22.0,
        "wacc_pct": 7.0,
    },
    "KO": {
        "name": "The Coca-Cola Company",
        "sector": "Consumer Staples",
        "stage": "Mature Cash Cow (Dual-Engine Total Yield)",
        "dividend_yield_pct": 2.9,
        "buyback_yield_pct": 1.0,
        "payout_ratio_pct": 65.0,
        "roic_pct": 18.0,
        "wacc_pct": 6.5,
    },
    "PG": {
        "name": "Procter & Gamble Co.",
        "sector": "Consumer Staples",
        "stage": "Mature Cash Cow (Dual-Engine Total Yield)",
        "dividend_yield_pct": 2.3,
        "buyback_yield_pct": 1.5,
        "payout_ratio_pct": 55.0,
        "roic_pct": 25.0,
        "wacc_pct": 7.0,
    },
    "XOM": {
        "name": "Exxon Mobil Corporation",
        "sector": "Energy",
        "stage": "Mature Cash Cow (Dual-Engine Total Yield)",
        "dividend_yield_pct": 3.3,
        "buyback_yield_pct": 4.0,
        "payout_ratio_pct": 40.0,
        "roic_pct": 15.0,
        "wacc_pct": 8.0,
    },
    "CVX": {
        "name": "Chevron Corporation",
        "sector": "Energy",
        "stage": "Mature Cash Cow (Dual-Engine Total Yield)",
        "dividend_yield_pct": 4.0,
        "buyback_yield_pct": 3.5,
        "payout_ratio_pct": 55.0,
        "roic_pct": 12.0,
        "wacc_pct": 8.0,
    },
    "IBM": {
        "name": "International Business Machines",
        "sector": "Technology",
        "stage": "Mature Cash Cow (Dual-Engine Total Yield)",
        "dividend_yield_pct": 3.2,
        "buyback_yield_pct": 0.5,
        "payout_ratio_pct": 65.0,
        "roic_pct": 10.0,
        "wacc_pct": 8.0,
    },
    "T": {
        "name": "AT&T Inc.",
        "sector": "Communication Services",
        "stage": "Mature Cash Cow (Dual-Engine Total Yield)",
        "dividend_yield_pct": 5.5,
        "buyback_yield_pct": 0.0,
        "payout_ratio_pct": 55.0,
        "roic_pct": 6.0,
        "wacc_pct": 7.0,
    },
    "HD": {
        "name": "The Home Depot, Inc.",
        "sector": "Consumer Discretionary",
        "stage": "Mature Cash Cow (Dual-Engine Total Yield)",
        "dividend_yield_pct": 2.3,
        "buyback_yield_pct": 1.0,
        "payout_ratio_pct": 55.0,
        "roic_pct": 40.0,
        "wacc_pct": 8.0,
    },
    "MCD": {
        "name": "McDonald's Corporation",
        "sector": "Consumer Discretionary",
        "stage": "Mature Cash Cow (Dual-Engine Total Yield)",
        "dividend_yield_pct": 2.2,
        "buyback_yield_pct": 1.5,
        "payout_ratio_pct": 55.0,
        "roic_pct": 40.0,
        "wacc_pct": 8.0,
    },
}

DIVIDEND_LIFECYCLE_DATES: dict[str, str] = {
    "declaration_date": (
        "Board of directors announces the dividend amount, record date, and "
        "payment date — creates a legal liability for the firm."
    ),
    "ex_dividend_date": (
        "Settled exactly one business day before the record date. Buyers on or "
        "after this date do not receive the upcoming dividend; the stock opens "
        "lower by the dividend amount as cash leaves the firm."
    ),
    "record_date": (
        "The company compiles its official list of registered shareholders "
        "eligible for the payout."
    ),
    "payment_date": "Cash is electronically transferred into eligible shareholder accounts.",
}

TAX_TREATMENT_TABLE: list[dict[str, str]] = [
    {
        "dividend_type": "Qualified Dividends",
        "holding_requirement": "Held > 60 days during a 121-day window around ex-date",
        "tax_treatment": "Long-term capital gains rates (0%, 15%, or 20%)",
    },
    {
        "dividend_type": "Ordinary Dividends",
        "holding_requirement": "Held <= 60 days or paid by REITs / certain foreign assets",
        "tax_treatment": "Investor's standard marginal income tax bracket (up to 37%)",
    },
]

STRUCTURAL_COMPARISON: list[dict[str, str]] = [
    {
        "vector": "Direct Value Driver",
        "dividends": "Immediate liquid cash in hand",
        "buybacks": "Compound expansion of per-share equity ownership",
    },
    {
        "vector": "Capital Allocation Impact",
        "dividends": "Permanently strips cash off the balance sheet",
        "buybacks": "Reduces equity base; concentrates financial metrics",
    },
    {
        "vector": "Execution Flexibility",
        "dividends": "Extremely rigid; baseline shifts are permanent",
        "buybacks": "High; programs can be paused or canceled instantly",
    },
    {
        "vector": "EPS Impact",
        "dividends": "Zero direct impact on share counts",
        "buybacks": "Direct mathematical inflation of per-share earnings",
    },
    {
        "vector": "Tax Drag Friction",
        "dividends": "Immediate annual friction in taxable accounts",
        "buybacks": "Tax-deferred compounding until personal asset liquidation",
    },
    {
        "vector": "Principal-Agent Risk",
        "dividends": "Prevents management from wasting excess cash",
        "buybacks": "Risk of inflating EPS to trigger executive bonuses",
    },
]

LIFE_CYCLE_ARCHETYPES: list[dict[str, str]] = [
    {
        "stage": "Stage 1: High-Growth Disrupter (Zero Returns)",
        "characteristics": "Rapid revenue scaling, negative or minimal net income.",
        "strategy": "Reinvests 100% of operational cash flow into R&D and market acquisition.",
        "example_metrics": "0% Dividend Yield / 0% Buyback Yield.",
    },
    {
        "stage": "Stage 2: Maturing Growth (Opportunistic Buybacks)",
        "characteristics": "Free cash flow becomes structurally positive; baseline expansion slows.",
        "strategy": (
            "Initiates large, flexible buyback programs to mop up excess cash without "
            "committing to rigid quarterly dividend payouts."
        ),
    },
    {
        "stage": "Stage 3: Mature Cash Cow (Dual-Engine Total Yield)",
        "characteristics": "High profitability, dominant market share, limited organic expansion.",
        "strategy": (
            "Implements a strict dividend policy for institutional stability, paired with "
            "consistent, large-scale buyback programs."
        ),
        "metric_focused": "Total Shareholder Yield = Dividend Yield + Net Buyback Yield.",
    },
]

CAPITAL_RETURN_PLAYBOOK: dict[str, Any] = {
    "capital_deployment_options": [
        "Reinvest in core business operations (CapEx)",
        "Acquire other businesses (M&A)",
        "Pay down outstanding debt liabilities",
        "Hoard cash on the balance sheet for future opportunities or crises",
        "Return cash directly to shareholders",
    ],
    "dividend_lifecycle_dates": DIVIDEND_LIFECYCLE_DATES,
    "tax_treatment": TAX_TREATMENT_TABLE,
    "structural_comparison": STRUCTURAL_COMPARISON,
    "life_cycle_archetypes": LIFE_CYCLE_ARCHETYPES,
    "sec_rule_10b_18": (
        "Governs Open Market Repurchase (OMR) programs — timing, price caps, and "
        "daily volume limits — to prevent market manipulation."
    ),
    "eps_formula": "EPS = Net Income / Total Shares Outstanding",
}


@dataclass
class CapitalReturnCandidate:
    symbol: str
    name: str
    sector: str
    stage: str
    dividend_yield_pct: float
    buyback_yield_pct: float
    total_shareholder_yield_pct: float
    payout_ratio_pct: float
    roic_pct: float
    wacc_pct: float
    reinvestment_spread_pct: float
    capital_efficiency_label: str
    price: float | None
    day_chg_pct: float | None
    week_chg_pct: float | None
    year_range_position_pct: float | None
    buyback_quality_label: str
    dividend_risk_label: str


@dataclass
class CapitalReturnAssessment:
    regime: str
    top_total_yield_leader: str
    dividend_risk_alerts: list[str]
    buyback_quality_flags: list[str]
    stage_mix: dict[str, int]


@dataclass
class CapitalReturnReport:
    candidates: list[CapitalReturnCandidate]
    assessment: CapitalReturnAssessment
    avg_total_shareholder_yield_pct: float
    dividend_only_count: int
    buyback_only_count: int
    dual_engine_count: int
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CapitalReturnExpert(BaseExpert):
    """Expert analysis of dividend vs buyback capital-return strategy."""

    def __init__(
        self,
        delay_seconds: float = 0.3,
        *,
        pipeline_context: dict | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="capital-return")
        self.delay_seconds = delay_seconds
        self._live_ok = False

    def _year_range_position(self, symbol: str, price: float | None) -> float | None:
        if price is None:
            return None
        closes = self.fetch_yahoo_closes(symbol, range_="1y", interval="1wk")
        if len(closes) < 4:
            return None
        lo, hi = min(closes), max(closes)
        if hi <= lo:
            return None
        pct = (price - lo) / (hi - lo) * 100.0
        return round(max(0.0, min(100.0, pct)), 1)

    @staticmethod
    def _capital_efficiency_label(roic_pct: float, wacc_pct: float) -> str:
        spread = roic_pct - wacc_pct
        if spread >= 10:
            return "value-creating reinvestment — ROIC comfortably exceeds WACC"
        if spread >= 0:
            return "marginal reinvestment edge — ROIC roughly tracks WACC"
        return "value-destroying reinvestment — ROIC below WACC, favors capital return"

    @staticmethod
    def _buyback_quality_label(buyback_yield_pct: float, range_position_pct: float | None) -> str:
        if buyback_yield_pct <= 0.05:
            return "no active buyback program"
        if range_position_pct is None:
            return "buyback active — valuation context unavailable"
        if range_position_pct >= 80:
            return "buying near 52-week highs — value-destroying risk"
        if range_position_pct <= 35:
            return "buying below-average valuation — value-creating"
        return "buyback active at neutral valuation"

    @staticmethod
    def _dividend_risk_label(payout_ratio_pct: float, week_chg_pct: float | None) -> str:
        if payout_ratio_pct <= 0:
            return "no dividend commitment"
        weak_momentum = week_chg_pct is not None and week_chg_pct < -3.0
        if payout_ratio_pct >= 60 and weak_momentum:
            return "elevated dividend cut risk — high payout amid price weakness"
        if payout_ratio_pct >= 60:
            return "high payout ratio — limited reinvestment cushion"
        if payout_ratio_pct <= 30:
            return "well-covered — low cut risk"
        return "moderate payout coverage"

    def _fetch_candidate(self, symbol: str, profile: dict[str, Any]) -> CapitalReturnCandidate:
        meta = self.fetch_yahoo_chart_meta(symbol, range_="1mo", interval="1d")
        time.sleep(self.delay_seconds)
        price = meta.get("price") if meta else None
        day_chg = meta.get("day_chg_pct") if meta else None
        week_chg = meta.get("week_chg_pct") if meta else None
        if meta:
            self._live_ok = True

        range_position = self._year_range_position(symbol, price)
        time.sleep(self.delay_seconds)

        div_yield = float(profile["dividend_yield_pct"])
        buyback_yield = float(profile["buyback_yield_pct"])
        payout_ratio = float(profile["payout_ratio_pct"])
        roic = float(profile["roic_pct"])
        wacc = float(profile["wacc_pct"])

        return CapitalReturnCandidate(
            symbol=symbol,
            name=str(profile["name"]),
            sector=str(profile["sector"]),
            stage=str(profile["stage"]),
            dividend_yield_pct=div_yield,
            buyback_yield_pct=buyback_yield,
            total_shareholder_yield_pct=round(div_yield + buyback_yield, 2),
            payout_ratio_pct=payout_ratio,
            roic_pct=roic,
            wacc_pct=wacc,
            reinvestment_spread_pct=round(roic - wacc, 2),
            capital_efficiency_label=self._capital_efficiency_label(roic, wacc),
            price=round(float(price), 2) if price is not None else None,
            day_chg_pct=day_chg,
            week_chg_pct=week_chg,
            year_range_position_pct=range_position,
            buyback_quality_label=self._buyback_quality_label(buyback_yield, range_position),
            dividend_risk_label=self._dividend_risk_label(payout_ratio, week_chg),
        )

    def _assessment(
        self, candidates: list[CapitalReturnCandidate]
    ) -> CapitalReturnAssessment:
        stage_mix: dict[str, int] = {}
        for c in candidates:
            stage_mix[c.stage] = stage_mix.get(c.stage, 0) + 1

        ranked = sorted(candidates, key=lambda c: -c.total_shareholder_yield_pct)
        leader = ranked[0] if ranked else None
        top_leader = (
            f"{leader.symbol} ({leader.total_shareholder_yield_pct:+.2f}% total shareholder yield)"
            if leader
            else "n/a"
        )

        dividend_alerts = [
            f"{c.symbol}: {c.dividend_risk_label}"
            for c in candidates
            if "elevated dividend cut risk" in c.dividend_risk_label
        ]
        buyback_flags = [
            f"{c.symbol}: {c.buyback_quality_label}"
            for c in candidates
            if "value-destroying" in c.buyback_quality_label or "value-creating" in c.buyback_quality_label
        ]

        avg_dual_yield = (
            sum(c.total_shareholder_yield_pct for c in candidates if "Mature Cash Cow" in c.stage)
            / max(1, sum(1 for c in candidates if "Mature Cash Cow" in c.stage))
        ) if candidates else 0.0

        if avg_dual_yield >= 4.0:
            regime = "dual-engine total yield regime — mature cohort favors combined dividend + buyback returns"
        elif avg_dual_yield >= 2.0:
            regime = "moderate total yield regime — mixed dividend/buyback commitment"
        else:
            regime = "growth-reinvestment tilt — capital largely retained for CapEx/M&A"

        return CapitalReturnAssessment(
            regime=regime,
            top_total_yield_leader=top_leader,
            dividend_risk_alerts=dividend_alerts,
            buyback_quality_flags=buyback_flags,
            stage_mix=stage_mix,
        )

    def _market_signals(
        self,
        candidates: list[CapitalReturnCandidate],
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal

        signals: list[dict[str, Any]] = []

        value_creating = [
            c for c in candidates
            if "value-creating" in c.buyback_quality_label and c.total_shareholder_yield_pct > 0
        ]
        if value_creating:
            best = max(value_creating, key=lambda c: c.total_shareholder_yield_pct)
            signals.append(
                build_market_signal(
                    sector=f"Capital Return — {best.sector}",
                    tickers=[best.symbol],
                    bias="BULLISH",
                    reason=(
                        f"{best.symbol} repurchasing below-average valuation "
                        f"(52w range {best.year_range_position_pct}%) with "
                        f"{best.total_shareholder_yield_pct:+.2f}% total shareholder yield"
                    ),
                    confidence=self.adjust_signal_confidence(
                        best.symbol,
                        "BULLISH",
                        0.55 + min(0.25, best.total_shareholder_yield_pct / 20.0),
                    ),
                    evidence={
                        "total_shareholder_yield_pct": best.total_shareholder_yield_pct,
                        "year_range_position_pct": best.year_range_position_pct,
                    },
                )
            )

        cut_risk = [c for c in candidates if "elevated dividend cut risk" in c.dividend_risk_label]
        for c in cut_risk[:3]:
            signals.append(
                build_market_signal(
                    sector=f"Dividend Risk — {c.sector}",
                    tickers=[c.symbol],
                    bias="BEARISH",
                    reason=(
                        f"{c.symbol} payout ratio {c.payout_ratio_pct:.0f}% amid "
                        f"{c.week_chg_pct:+.2f}% weekly weakness — dividend cut risk"
                    ),
                    confidence=self.adjust_signal_confidence(c.symbol, "BEARISH", 0.55),
                    evidence={"payout_ratio_pct": c.payout_ratio_pct, "week_chg_pct": c.week_chg_pct},
                )
            )

        at_highs = [c for c in candidates if "value-destroying" in c.buyback_quality_label]
        for c in at_highs[:3]:
            signals.append(
                build_market_signal(
                    sector=f"Buyback Quality — {c.sector}",
                    tickers=[c.symbol],
                    bias="NEUTRAL",
                    reason=(
                        f"{c.symbol} repurchasing near 52-week highs "
                        f"(range {c.year_range_position_pct}%) — financial-engineering risk"
                    ),
                    confidence=self.adjust_signal_confidence(c.symbol, "NEUTRAL", 0.45),
                    evidence={"year_range_position_pct": c.year_range_position_pct},
                )
            )

        if not signals:
            signals.append(
                build_market_signal(
                    sector="Capital Return Broad Market",
                    tickers=[c.symbol for c in candidates[:5]],
                    bias="NEUTRAL",
                    reason="Total shareholder yield cohort within normal range",
                    confidence=self.adjust_signal_confidence("SPY", "NEUTRAL", 0.4),
                )
            )
        return signals

    def analyze(self) -> CapitalReturnReport:
        self._live_ok = False
        candidates: list[CapitalReturnCandidate] = []
        for symbol, profile in CAPITAL_RETURN_PROFILES.items():
            candidates.append(self._fetch_candidate(symbol, profile))

        assessment = self._assessment(candidates)

        avg_total_yield = (
            round(sum(c.total_shareholder_yield_pct for c in candidates) / len(candidates), 2)
            if candidates
            else 0.0
        )
        dividend_only = sum(
            1 for c in candidates if c.dividend_yield_pct > 0 and c.buyback_yield_pct <= 0.05
        )
        buyback_only = sum(
            1 for c in candidates if c.buyback_yield_pct > 0 and c.dividend_yield_pct <= 0.05
        )
        dual_engine = sum(
            1 for c in candidates if c.dividend_yield_pct > 0.05 and c.buyback_yield_pct > 0.05
        )

        ranked = sorted(candidates, key=lambda c: -c.total_shareholder_yield_pct)
        summary = (
            f"Capital Return Strategy scan across {len(candidates)} tickers. "
            f"{assessment.regime}. "
            f"Average total shareholder yield {avg_total_yield:+.2f}%. "
            f"Top total-yield leader: {assessment.top_total_yield_leader}. "
            f"Stage mix: {assessment.stage_mix}. "
        )
        if assessment.dividend_risk_alerts:
            summary += f"Dividend risk alerts: {', '.join(assessment.dividend_risk_alerts)}. "
        if assessment.buyback_quality_flags:
            summary += f"Buyback quality flags: {', '.join(assessment.buyback_quality_flags)}."

        signals = self._market_signals(candidates)
        recs = [
            summary,
            f"Total shareholder yield leaders: "
            + ", ".join(
                f"{c.symbol} {c.total_shareholder_yield_pct:+.2f}%" for c in ranked[:5]
            ),
        ]
        for c in ranked[:8]:
            recs.append(
                f"{c.symbol} ({c.stage}): div {c.dividend_yield_pct:.2f}% + buyback "
                f"{c.buyback_yield_pct:.2f}% = {c.total_shareholder_yield_pct:+.2f}% total yield — "
                f"{c.capital_efficiency_label}"
            )
        recs = self.append_memory_recommendations(recs)

        sources = ["Yahoo Finance API (live price / 52-week range)", "Curated capital-return fundamentals"]
        if not self._live_ok:
            sources.append("Calibrated proxy feed")

        return CapitalReturnReport(
            candidates=candidates,
            assessment=assessment,
            avg_total_shareholder_yield_pct=avg_total_yield,
            dividend_only_count=dividend_only,
            buyback_only_count=buyback_only,
            dual_engine_count=dual_engine,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source=", ".join(sources),
        )

    def to_dict(self, report: CapitalReturnReport) -> dict[str, Any]:
        def cand_dict(c: CapitalReturnCandidate) -> dict[str, Any]:
            return {
                "symbol": c.symbol,
                "name": c.name,
                "sector": c.sector,
                "stage": c.stage,
                "dividend_yield_pct": c.dividend_yield_pct,
                "buyback_yield_pct": c.buyback_yield_pct,
                "total_shareholder_yield_pct": c.total_shareholder_yield_pct,
                "payout_ratio_pct": c.payout_ratio_pct,
                "roic_pct": c.roic_pct,
                "wacc_pct": c.wacc_pct,
                "reinvestment_spread_pct": c.reinvestment_spread_pct,
                "capital_efficiency_label": c.capital_efficiency_label,
                "price": c.price,
                "day_chg_pct": c.day_chg_pct,
                "week_chg_pct": c.week_chg_pct,
                "year_range_position_pct": c.year_range_position_pct,
                "buyback_quality_label": c.buyback_quality_label,
                "dividend_risk_label": c.dividend_risk_label,
            }

        a = report.assessment
        return {
            "meta": {
                "agent": "Capital Return Strategy Expert",
                "dashboard": DASHBOARD_URL,
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
            },
            "metrics": {
                "avg_total_shareholder_yield_pct": report.avg_total_shareholder_yield_pct,
                "dividend_only_count": report.dividend_only_count,
                "buyback_only_count": report.buyback_only_count,
                "dual_engine_count": report.dual_engine_count,
            },
            "candidates": [cand_dict(c) for c in report.candidates],
            "assessment": {
                "regime": a.regime,
                "top_total_yield_leader": a.top_total_yield_leader,
                "dividend_risk_alerts": a.dividend_risk_alerts,
                "buyback_quality_flags": a.buyback_quality_flags,
                "stage_mix": a.stage_mix,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        report = self.analyze()
        result = self.to_dict(report)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            playbook_path = output.parent / "capital_return_playbook.json"
            playbook_path.write_text(
                json.dumps(CAPITAL_RETURN_PLAYBOOK, indent=2),
                encoding="utf-8",
            )
        return result


def run_capital_return_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    expert = CapitalReturnExpert(pipeline_context=pipeline_context)
    return expert.run(output=output)
