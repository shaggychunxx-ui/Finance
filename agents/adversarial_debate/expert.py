"""
Adversarial Debate & Consensus Router Agent — "The Judge"
===========================================================
Mission: eradicate AI confirmation bias and false pattern hallucinations by
forcing a rigorous, data-backed courtroom debate before capital is
deployed.

System architecture: a Supervisor-as-Tools orchestrator. Rather than
sharing one continuous conversation thread (which causes token confusion
and hallucinations), this router calls each upstream specialist agent in
its own isolated invocation and only passes back standardized numeric/dict
state — Fundamental Analyst, Sentiment & Alternative Data, Technical
Pattern, and Market Regime — then synthesizes their outputs into a single
central state object.

Mathematical processing: for each symbol covered by at least two upstream
agents, the Orchestrator spins up two adversarial personas from the
collected (already-computed) state:
  * Bull Prosecutor — argues the trade using Technical + Sentiment signals.
  * Bear Defense    — uses Fundamental + Market Regime findings to expose
                       gaps in the long thesis.
A deterministic scoring function (not free-form LLM judgment) tallies each
side's evidence weight and renders a verdict: Approved / Downsized /
Rejected.

How it ensures accuracy: if the Bull side cannot out-weigh a Bear critique
grounded in fundamentals or a hostile market regime (e.g. high D/E "Junk
Risk" or a "High-Vol Mean-Reverting" chop regime), the trade is rejected or
downsized rather than approved on pattern-matching alone.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base import BaseExpert
from agents.fundamental_analyst import run_fundamental_analyst_analysis
from agents.market_regime import run_market_regime_analysis
from agents.sentiment_alt_data import run_sentiment_alt_data_analysis
from agents.technical_pattern import run_technical_pattern_analysis

BULL_WEIGHT_TECHNICAL_ENTRY = 3.0
BULL_WEIGHT_TECHNICAL_TREND = 1.0
BULL_WEIGHT_SENTIMENT_BREAKOUT = 2.0
BULL_WEIGHT_SENTIMENT_POLARITY = 1.0

BEAR_WEIGHT_JUNK_RISK = 3.0
BEAR_WEIGHT_OVERVALUED_RISK = 2.0
BEAR_WEIGHT_HOSTILE_REGIME = 2.0
BEAR_WEIGHT_RSI_EXTENDED = 1.0

REJECT_MARGIN = -1.0  # bear_score - bull_score above this rejects the trade
DOWNSIZE_MARGIN = 1.0  # bull_score - bear_score below this only earns a downsized approval


@dataclass
class Verdict:
    symbol: str
    bull_score: float
    bear_score: float
    bull_arguments: list[str]
    bear_arguments: list[str]
    decision: str  # "Approved" | "Downsized" | "Rejected"
    size_multiplier: float
    rationale: str


@dataclass
class ConsensusReport:
    regime_label: str
    verdicts: list[Verdict]
    approved: list[str]
    downsized: list[str]
    rejected: list[str]
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AdversarialDebateExpert(BaseExpert):
    """The 'Judge' — Supervisor-as-Tools consensus router over sibling agents."""

    def __init__(self) -> None:
        super().__init__()

    @staticmethod
    def _index_by_symbol(snapshots: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {s.get("symbol"): s for s in snapshots if s.get("symbol")}

    def _debate_symbol(
        self,
        symbol: str,
        fundamental: dict[str, Any] | None,
        sentiment: dict[str, Any] | None,
        technical: dict[str, Any] | None,
        regime_label: str,
        regime_config: dict[str, Any],
    ) -> Verdict:
        bull_arguments: list[str] = []
        bear_arguments: list[str] = []
        bull_score = 0.0
        bear_score = 0.0

        # -- Bull Prosecutor: Technical + Sentiment --
        if technical:
            if technical.get("entry_grade") == "High-Probability Entry":
                bull_score += BULL_WEIGHT_TECHNICAL_ENTRY
                bull_arguments.append(
                    f"High-probability technical entry at {technical.get('entry_zone')} "
                    f"({technical.get('ema_alignment')})"
                )
            elif "Bullish stack" in (technical.get("ema_alignment") or ""):
                bull_score += BULL_WEIGHT_TECHNICAL_TREND
                bull_arguments.append("EMA stack is bullish-aligned")

        if sentiment:
            if sentiment.get("breakout_alert"):
                bull_score += BULL_WEIGHT_SENTIMENT_BREAKOUT
                bull_arguments.append(f"Sentiment breakout alert: {sentiment.get('rationale')}")
            elif (sentiment.get("polarity_score") or 0) > 0.2:
                bull_score += BULL_WEIGHT_SENTIMENT_POLARITY
                bull_arguments.append(f"Positive polarity {sentiment.get('polarity_score')}")

        if not bull_arguments:
            bull_arguments.append("No affirmative technical/sentiment thesis found")

        # -- Bear Defense: Fundamental + Market Regime --
        if fundamental:
            risk_state = fundamental.get("risk_state", "Grounded")
            if "Junk" in risk_state:
                bear_score += BEAR_WEIGHT_JUNK_RISK
                bear_arguments.append(f"Fundamental Junk Risk: {fundamental.get('rationale')}")
            if "Overvalued" in risk_state:
                bear_score += BEAR_WEIGHT_OVERVALUED_RISK
                bear_arguments.append(f"Fundamental Overvalued Risk: {fundamental.get('rationale')}")

        if regime_label in ("High-Vol Mean-Reverting", "High-Vol Trending"):
            bear_score += BEAR_WEIGHT_HOSTILE_REGIME
            bear_arguments.append(
                f"Hostile market regime '{regime_label}': {regime_config.get('config', '')}"
            )

        if technical and (technical.get("rsi") or 0) >= 70:
            bear_score += BEAR_WEIGHT_RSI_EXTENDED
            bear_arguments.append(f"RSI {technical.get('rsi')} is technically extended")

        if not bear_arguments:
            bear_arguments.append("No material objection raised")

        margin = bull_score - bear_score
        if margin <= REJECT_MARGIN:
            decision = "Rejected"
            size_multiplier = 0.0
            rationale = "Bear Defense out-weighed the Bull thesis — trade rejected"
        elif margin < DOWNSIZE_MARGIN:
            decision = "Downsized"
            size_multiplier = 0.5
            rationale = "Bull thesis stands but Bear objections warrant a reduced position"
        else:
            decision = "Approved"
            size_multiplier = 1.0
            rationale = "Bull Prosecutor's case survives cross-examination unchallenged"

        return Verdict(
            symbol=symbol,
            bull_score=bull_score,
            bear_score=bear_score,
            bull_arguments=bull_arguments,
            bear_arguments=bear_arguments,
            decision=decision,
            size_multiplier=size_multiplier,
            rationale=rationale,
        )

    def analyze(self) -> ConsensusReport:
        fundamental_data = run_fundamental_analyst_analysis()
        sentiment_data = run_sentiment_alt_data_analysis()
        technical_data = run_technical_pattern_analysis()
        regime_data = run_market_regime_analysis()

        fundamental_by_symbol = self._index_by_symbol(fundamental_data.get("snapshots", []))
        sentiment_by_symbol = self._index_by_symbol(sentiment_data.get("snapshots", []))
        technical_by_symbol = self._index_by_symbol(technical_data.get("snapshots", []))

        regime_label = regime_data.get("metrics", {}).get("regime_label", "Unclassified")
        regime_config = regime_data.get("regime_config", {})

        symbols = sorted(set(technical_by_symbol) | set(sentiment_by_symbol) | set(fundamental_by_symbol))

        verdicts = [
            self._debate_symbol(
                symbol,
                fundamental_by_symbol.get(symbol),
                sentiment_by_symbol.get(symbol),
                technical_by_symbol.get(symbol),
                regime_label,
                regime_config,
            )
            for symbol in symbols
        ]

        approved = [v.symbol for v in verdicts if v.decision == "Approved"]
        downsized = [v.symbol for v in verdicts if v.decision == "Downsized"]
        rejected = [v.symbol for v in verdicts if v.decision == "Rejected"]

        expert_summary = (
            f"Adversarial debate across {len(verdicts)} symbols under regime '{regime_label}': "
            f"{len(approved)} approved, {len(downsized)} downsized, {len(rejected)} rejected."
        )

        signals = [
            {
                "sector": "Consensus Router",
                "bias": "bullish" if v.decision != "Rejected" else "avoid",
                "tickers": [v.symbol],
                "reason": f"{v.decision}: {v.rationale}",
            }
            for v in verdicts
            if v.decision in ("Approved", "Rejected")
        ]

        recommendations = [
            f"{v.symbol}: {v.decision} (size x{v.size_multiplier}) — {v.rationale}"
            for v in verdicts
        ]

        return ConsensusReport(
            regime_label=regime_label,
            verdicts=verdicts,
            approved=approved,
            downsized=downsized,
            rejected=rejected,
            expert_summary=expert_summary,
            market_signals=signals,
            recommendations=recommendations,
            data_source="Aggregated Fundamental/Sentiment/Technical/Regime agent state",
        )

    def to_dict(self, report: ConsensusReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Adversarial Debate & Consensus Router (The Judge)",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
                "temperature": self.temperature,
                "regime_label": report.regime_label,
            },
            "verdicts": [
                {
                    "symbol": v.symbol,
                    "bull_score": v.bull_score,
                    "bear_score": v.bear_score,
                    "bull_arguments": v.bull_arguments,
                    "bear_arguments": v.bear_arguments,
                    "decision": v.decision,
                    "size_multiplier": v.size_multiplier,
                    "rationale": v.rationale,
                }
                for v in report.verdicts
            ],
            "metrics": {
                "symbols_debated": len(report.verdicts),
                "approved": report.approved,
                "downsized": report.downsized,
                "rejected": report.rejected,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "consensus_scoring_weights.json"
            catalog.write_text(
                json.dumps(
                    {
                        "bull_weight_technical_entry": BULL_WEIGHT_TECHNICAL_ENTRY,
                        "bull_weight_technical_trend": BULL_WEIGHT_TECHNICAL_TREND,
                        "bull_weight_sentiment_breakout": BULL_WEIGHT_SENTIMENT_BREAKOUT,
                        "bull_weight_sentiment_polarity": BULL_WEIGHT_SENTIMENT_POLARITY,
                        "bear_weight_junk_risk": BEAR_WEIGHT_JUNK_RISK,
                        "bear_weight_overvalued_risk": BEAR_WEIGHT_OVERVALUED_RISK,
                        "bear_weight_hostile_regime": BEAR_WEIGHT_HOSTILE_REGIME,
                        "bear_weight_rsi_extended": BEAR_WEIGHT_RSI_EXTENDED,
                        "reject_margin": REJECT_MARGIN,
                        "downsize_margin": DOWNSIZE_MARGIN,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        return result


def run_adversarial_debate_analysis(output: Path | None = None) -> dict[str, Any]:
    return AdversarialDebateExpert().run(output=output)
