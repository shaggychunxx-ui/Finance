"""
Institutional Dedicated Bear Thesis Expert Agent
=================================================
A professional short thesis goes beyond "overvalued" — it targets systemic
vulnerabilities where a structural decline cannot easily be averted: macro/
micro disconnects, forensic accounting divergences, and flawed capital
allocation.

Data: Yahoo Finance chart API (3-month daily OHLCV). Real fundamental filings
(10-K/10-Q line items for FCF, goodwill, gross margin trend) are not
reachable from this sandbox, so the per-symbol "priced-for-perfection" flag
is a transparent, disclosed proxy built from price momentum/valuation-style
extension — not a live fundamentals feed.
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

WATCHLIST: dict[str, str] = {
    "SPY": "S&P 500 (deep liquidity proxy)",
    "AAPL": "Mega-cap tech (mature, cash-generative)",
    "MSFT": "Mega-cap tech (mature, cash-generative)",
    "QQQ": "Nasdaq 100 (growth-tilted benchmark)",
    "IWM": "Russell 2000 (small-cap, weaker balance sheets)",
    "GME": "Retail-driven small/mid cap (thesis-contested)",
    "COIN": "Crypto-adjacent equity (cyclical revenue)",
    "PLTR": "High-beta growth name (high multiple)",
}

BEAR_THESIS_PLAYBOOK: list[dict[str, str]] = [
    {
        "pillar": "Macro/Micro Disconnects",
        "description": (
            "Companies trading at exorbitant multiples based on temporary pandemic, "
            "cyclical, or regulatory anomalies that are actively reversing."
        ),
    },
    {
        "pillar": "Accounting & Forensic Scrubbing",
        "description": (
            "Divergence between Net Income and Free Cash Flow; aggressive revenue "
            "recognition, capitalized operating expenses, or off-balance-sheet SPVs."
        ),
    },
    {
        "pillar": "Flawed Capital Allocation",
        "description": (
            "High-interest debt funding share buybacks or unprofitable acquisitions "
            "instead of organic R&D or operational maintenance."
        ),
    },
]

VALUATION_DISCONNECT_TABLE: list[dict[str, str]] = [
    {
        "vulnerability_category": "Cash Burn Runway",
        "metric_signal": "Negative FCF vs Total Liquidity",
        "structural_risk": "Dilutive equity raises or high-interest debt issuance within 6–12 months.",
    },
    {
        "vulnerability_category": "Asset Quality",
        "metric_signal": "Unusually high Goodwill/Intangibles",
        "structural_risk": "Impairment charges that wipe out book value and breach debt covenants.",
    },
    {
        "vulnerability_category": "Product Obsolescence",
        "metric_signal": "Declining Gross Margins",
        "structural_risk": "Loss of pricing power indicating a commoditized or failing product line.",
    },
]


@dataclass
class SymbolBearProfile:
    symbol: str
    name: str
    last_close: float
    return_60d_pct: float
    realized_vol_pct: float
    drawdown_from_high_pct: float
    priced_for_perfection_score: float
    priced_for_perfection_flag: bool
    rationale: str


@dataclass
class BearAssessment:
    flagged_count: int
    average_score: float
    top_candidate: str
    disconnect_signal: str
    conclusion: str


@dataclass
class BearThesisReport:
    symbols: list[SymbolBearProfile]
    assessment: BearAssessment
    bear_conviction_score: float
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class BearThesisExpert(BaseExpert):
    """Expert market analyst — institutional dedicated bear thesis screening."""

    def __init__(
        self,
        delay_seconds: float = 0.35,
        *,
        pipeline_context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="bear-thesis")
        self.delay_seconds = delay_seconds

    def _analyze_symbol(self, symbol: str, name: str) -> SymbolBearProfile | None:
        data = self.fetch_yahoo_ohlcv(symbol, range_="3mo", interval="1d")
        closes = data.get("close", [])
        highs = data.get("high", [])
        if len(closes) < 15:
            return None

        last_close = closes[-1]
        lookback = min(len(closes), 60)
        recent_closes = closes[-lookback:]
        recent_highs = highs[-lookback:]

        return_60d_pct = round((closes[-1] / recent_closes[0] - 1) * 100, 2) if recent_closes[0] else 0.0

        daily_returns = [
            abs(recent_closes[i] / recent_closes[i - 1] - 1) * 100
            for i in range(1, len(recent_closes))
            if recent_closes[i - 1]
        ]
        realized_vol_pct = round(statistics.mean(daily_returns) if daily_returns else 0.0, 2)

        period_high = max(recent_highs) if recent_highs else last_close
        drawdown_from_high_pct = round((last_close / period_high - 1) * 100, 2) if period_high else 0.0

        # "Priced-for-perfection" proxy: large extended rally + elevated volatility
        # + shallow pullback from highs is the closest observable footprint of a
        # valuation disconnect without access to real fundamentals filings.
        rally_component = max(0.0, min(return_60d_pct, 60)) * 0.7
        vol_component = min(realized_vol_pct / 8.0 * 20, 20)
        drawdown_component = max(0.0, 20 - abs(drawdown_from_high_pct))
        priced_for_perfection_score = round(
            min(rally_component + vol_component + drawdown_component, 100), 1
        )
        flag = priced_for_perfection_score >= 55

        rationale = (
            f"60d return {return_60d_pct:+.2f}%, realized vol {realized_vol_pct:.2f}%/day, "
            f"{drawdown_from_high_pct:+.2f}% off high → priced-for-perfection score "
            f"{priced_for_perfection_score:.0f}/100."
        )

        return SymbolBearProfile(
            symbol=symbol,
            name=name,
            last_close=round(last_close, 2),
            return_60d_pct=return_60d_pct,
            realized_vol_pct=realized_vol_pct,
            drawdown_from_high_pct=drawdown_from_high_pct,
            priced_for_perfection_score=priced_for_perfection_score,
            priced_for_perfection_flag=flag,
            rationale=rationale,
        )

    def _assessment(self, symbols: list[SymbolBearProfile]) -> BearAssessment:
        flagged = [s for s in symbols if s.priced_for_perfection_flag]
        top = max(symbols, key=lambda s: s.priced_for_perfection_score) if symbols else None
        avg_score = round(
            statistics.mean([s.priced_for_perfection_score for s in symbols]), 1
        ) if symbols else 0.0

        disconnect_signal = (
            f"{len(flagged)}/{len(symbols)} symbols proxy a macro/micro valuation disconnect "
            "worth forensic follow-up on FCF, goodwill, and margin trend."
        )
        if top and top.priced_for_perfection_flag:
            conclusion = (
                f"{top.symbol} screens as the strongest bear-thesis candidate — validate against "
                "the Valuation Disconnect Table before sizing a position."
            )
        elif flagged:
            conclusion = "Select names show early bear-thesis footprints — monitor for confirmation."
        else:
            conclusion = "No name currently screens as an extended, priced-for-perfection candidate."

        return BearAssessment(
            flagged_count=len(flagged),
            average_score=avg_score,
            top_candidate=top.symbol if top else "",
            disconnect_signal=disconnect_signal,
            conclusion=conclusion,
        )

    def _expert_summary(self, assessment: BearAssessment) -> str:
        return (
            f"Bear-thesis scan: avg priced-for-perfection score {assessment.average_score:.1f}/100. "
            f"{assessment.disconnect_signal} {assessment.conclusion}"
        )

    def _market_signals(self, symbols: list[SymbolBearProfile]) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        def _keep(symbol: str) -> bool:
            return not self.pipeline_should_skip_symbol(symbol)

        flagged = [s.symbol for s in symbols if s.priced_for_perfection_flag and _keep(s.symbol)]
        if flagged:
            signals.append(
                {
                    "sector": "Bear Thesis",
                    "bias": "priced-for-perfection",
                    "tickers": flagged,
                    "reason": "Extended rally + elevated volatility proxy a valuation disconnect.",
                }
            )
        stable = [
            s.symbol
            for s in symbols
            if s.priced_for_perfection_score < 25 and _keep(s.symbol)
        ]
        if stable:
            signals.append(
                {
                    "sector": "Bear Thesis",
                    "bias": "no-disconnect",
                    "tickers": stable,
                    "reason": "No valuation-disconnect footprint detected.",
                }
            )
        return signals

    def _recommendations(
        self, symbols: list[SymbolBearProfile], assessment: BearAssessment
    ) -> list[str]:
        recs = [assessment.conclusion]
        for s in sorted(symbols, key=lambda x: -x.priced_for_perfection_score)[:6]:
            flag = "Bear-thesis candidate" if s.priced_for_perfection_flag else "Not flagged"
            recs.append(f"{s.symbol} [{flag}]: {s.rationale}")
        return recs

    def analyze(self) -> BearThesisReport:
        symbols: list[SymbolBearProfile] = []
        for symbol, name in WATCHLIST.items():
            row = self._analyze_symbol(symbol, name)
            if row:
                symbols.append(row)
            time.sleep(self.delay_seconds)

        if not any(s.symbol == BENCHMARK for s in symbols):
            raise RuntimeError("Unable to fetch SPY data for bear-thesis analysis")

        assessment = self._assessment(symbols)
        expert_summary = self._expert_summary(assessment)
        bear_conviction_score = round(
            statistics.mean([s.priced_for_perfection_score for s in symbols]) / 10, 1
        )

        return BearThesisReport(
            symbols=symbols,
            assessment=assessment,
            bear_conviction_score=bear_conviction_score,
            expert_summary=expert_summary,
            market_signals=self._market_signals(symbols),
            recommendations=self._recommendations(symbols, assessment),
            data_source=(
                "Yahoo Finance Chart API (3mo daily OHLCV) — valuation-disconnect flag is a "
                "price momentum/volatility proxy, not a fundamentals feed"
            ),
        )

    def to_dict(self, report: BearThesisReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Institutional Dedicated Bear Thesis Expert",
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
            "bear_thesis_playbook": BEAR_THESIS_PLAYBOOK,
            "valuation_disconnect_table": VALUATION_DISCONNECT_TABLE,
            "symbol_bear_profiles": [
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "last_close": s.last_close,
                    "return_60d_pct": s.return_60d_pct,
                    "realized_vol_pct": s.realized_vol_pct,
                    "drawdown_from_high_pct": s.drawdown_from_high_pct,
                    "priced_for_perfection_score": s.priced_for_perfection_score,
                    "priced_for_perfection_flag": s.priced_for_perfection_flag,
                    "rationale": s.rationale,
                }
                for s in report.symbols
            ],
            "bear_assessment": {
                "flagged_count": a.flagged_count,
                "average_score": a.average_score,
                "top_candidate": a.top_candidate,
                "disconnect_signal": a.disconnect_signal,
                "conclusion": a.conclusion,
            },
            "metrics": {"bear_conviction_score": report.bear_conviction_score},
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "valuation_disconnect_table.json"
            catalog.write_text(json.dumps(VALUATION_DISCONNECT_TABLE, indent=2), encoding="utf-8")
        return result


def run_bear_thesis_analysis(
    output: Path | None = None,
    pipeline_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return BearThesisExpert(pipeline_context=pipeline_context).run(output=output)
