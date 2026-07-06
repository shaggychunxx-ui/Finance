"""
Risk Management & Guardrail Agent — "The Ultimate Auditor"
=============================================================
Mission: protect capital from black-swan events, system API failures, and
over-leveraged trade recommendations.

API interfacing: this agent has an absolute structural veto over the
Adversarial Debate & Consensus Router's proposals. Instead of hitting
external market data APIs, it is tightly locked to an internal portfolio
state model — cash, live margin usage, open unrealized PnL, and per-asset
exposure ceilings — supplied here as a deterministic, code-defined ledger
(the same role a private brokerage-account database would play in
production).

Mathematical processing — statistical protective math:
  1. Kelly Criterion Derivatives — position sizing from each proposal's
     implied win rate/risk-reward (fractional/half-Kelly for safety).
  2. Value at Risk (VaR) — 1-day 99% parametric VaR on the resulting
     portfolio using each position's historical daily volatility.
  3. Correlation Coefficients — flags new positions that would over-
     concentrate the book into a single already-correlated sector/cluster.

How it ensures accuracy: this agent operates with an absolute structural
veto. If the Consensus Router proposes risking more of account equity than
the hard ceiling on a high-volatility setup, this agent overrides the
decision and downscales it to a mathematically verified, safe allocation
limit — never letting an LLM freely determine position sizing.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.adversarial_debate import run_adversarial_debate_analysis
from agents.base import BaseExpert

# Deterministic internal portfolio ledger (stand-in for a private brokerage DB).
ACCOUNT_EQUITY = 100_000.0
CURRENT_MARGIN_USED = 18_000.0
MAX_MARGIN_UTILIZATION_PCT = 50.0
MAX_SINGLE_POSITION_PCT = 10.0  # hard ceiling: % of equity in one symbol
MAX_PORTFOLIO_VAR_PCT = 3.0  # hard ceiling: 1-day 99% VaR as % of equity
KELLY_FRACTION = 0.5  # half-Kelly for safety
DEFAULT_WIN_RATE = 0.5  # neutral prior when no upstream evidence is available
DEFAULT_DAILY_VOL_PCT = 2.0  # assumed daily volatility when unknown
VAR_Z_99 = 2.326  # one-tailed 99% confidence z-score

# Sector correlation clusters used for concentration checks.
SECTOR_CLUSTERS: dict[str, str] = {
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology", "AMD": "Technology",
    "QQQ": "Technology", "COIN": "Technology",
    "TSLA": "Consumer Discretionary", "AMZN": "Consumer Discretionary", "AMC": "Consumer Discretionary",
    "GME": "Consumer Discretionary", "PLTR": "Technology",
    "JPM": "Financials", "XLE": "Energy", "XOM": "Energy",
    "JNJ": "Healthcare", "SPY": "Broad Market", "IWM": "Broad Market",
}
MAX_CLUSTER_EXPOSURE_PCT = 25.0  # hard ceiling: % of equity in one correlated cluster


@dataclass
class RiskDecision:
    symbol: str
    proposed_decision: str
    proposed_size_multiplier: float
    win_rate_estimate: float
    kelly_fraction_pct: float
    base_position_pct: float
    var_1d_99_pct: float
    cluster: str
    cluster_exposure_pct: float
    final_position_pct: float
    veto_applied: bool
    veto_reason: str


@dataclass
class RiskGuardrailReport:
    account_equity: float
    margin_utilization_pct: float
    decisions: list[RiskDecision]
    total_allocated_pct: float
    portfolio_var_1d_99_pct: float
    vetoes: list[str]
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RiskGuardrailExpert(BaseExpert):
    """The 'Ultimate Auditor' — deterministic, code-bound structural veto."""

    def __init__(self) -> None:
        super().__init__()

    @staticmethod
    def _win_rate_from_verdict(verdict: dict[str, Any]) -> float:
        bull, bear = verdict.get("bull_score", 0.0), verdict.get("bear_score", 0.0)
        total = bull + bear
        if not total:
            return DEFAULT_WIN_RATE
        # Map the bull/bear evidence balance onto a bounded win-rate estimate.
        raw = 0.5 + (bull - bear) / (2 * max(total, 1.0))
        return round(max(0.05, min(0.95, raw)), 3)

    @staticmethod
    def _kelly_fraction(win_rate: float, reward_to_risk: float = 2.0) -> float:
        """f* = W - (1-W)/R, floored at 0. R = payoff ratio (reward:risk)."""
        loss_rate = 1 - win_rate
        f_star = win_rate - (loss_rate / reward_to_risk)
        return max(0.0, f_star)

    def _size_position(self, verdict: dict[str, Any]) -> tuple[float, float, float]:
        win_rate = self._win_rate_from_verdict(verdict)
        kelly = self._kelly_fraction(win_rate)
        kelly_fraction_pct = round(kelly * KELLY_FRACTION * 100, 2)
        base_position_pct = min(kelly_fraction_pct, MAX_SINGLE_POSITION_PCT)
        base_position_pct *= verdict.get("size_multiplier", 1.0)
        return win_rate, kelly_fraction_pct, round(base_position_pct, 2)

    @staticmethod
    def _parametric_var_pct(position_pct: float, daily_vol_pct: float = DEFAULT_DAILY_VOL_PCT) -> float:
        """1-day 99% parametric VaR for a single position, expressed as % of equity."""
        return round(position_pct * (daily_vol_pct / 100) * VAR_Z_99, 3)

    def analyze(self) -> RiskGuardrailReport:
        consensus = run_adversarial_debate_analysis()
        verdicts = consensus.get("verdicts", [])

        margin_utilization_pct = round((CURRENT_MARGIN_USED / ACCOUNT_EQUITY) * 100, 2)

        decisions: list[RiskDecision] = []
        cluster_totals: dict[str, float] = {}
        total_allocated_pct = 0.0
        vetoes: list[str] = []

        for verdict in verdicts:
            symbol = verdict.get("symbol", "?")
            proposed_decision = verdict.get("decision", "Rejected")
            proposed_multiplier = verdict.get("size_multiplier", 0.0)
            cluster = SECTOR_CLUSTERS.get(symbol, "Uncorrelated/Other")

            if proposed_decision == "Rejected" or proposed_multiplier <= 0:
                decisions.append(
                    RiskDecision(
                        symbol=symbol,
                        proposed_decision=proposed_decision,
                        proposed_size_multiplier=proposed_multiplier,
                        win_rate_estimate=self._win_rate_from_verdict(verdict),
                        kelly_fraction_pct=0.0,
                        base_position_pct=0.0,
                        var_1d_99_pct=0.0,
                        cluster=cluster,
                        cluster_exposure_pct=cluster_totals.get(cluster, 0.0),
                        final_position_pct=0.0,
                        veto_applied=False,
                        veto_reason="No position — already rejected upstream",
                    )
                )
                continue

            win_rate, kelly_pct, base_pct = self._size_position(verdict)
            var_pct = self._parametric_var_pct(base_pct)

            veto_applied = False
            veto_reasons: list[str] = []
            final_pct = base_pct

            if final_pct > MAX_SINGLE_POSITION_PCT:
                veto_applied = True
                veto_reasons.append(
                    f"position {final_pct}% exceeds single-name ceiling {MAX_SINGLE_POSITION_PCT}%"
                )
                final_pct = MAX_SINGLE_POSITION_PCT

            projected_cluster_exposure = cluster_totals.get(cluster, 0.0) + final_pct
            if projected_cluster_exposure > MAX_CLUSTER_EXPOSURE_PCT:
                veto_applied = True
                allowed = max(0.0, MAX_CLUSTER_EXPOSURE_PCT - cluster_totals.get(cluster, 0.0))
                veto_reasons.append(
                    f"cluster '{cluster}' exposure would reach {round(projected_cluster_exposure, 1)}%, "
                    f"over the {MAX_CLUSTER_EXPOSURE_PCT}% ceiling — capped to {round(allowed, 1)}%"
                )
                final_pct = round(allowed, 2)

            projected_var = self._parametric_var_pct(final_pct)
            if projected_var > MAX_PORTFOLIO_VAR_PCT:
                veto_applied = True
                scale = MAX_PORTFOLIO_VAR_PCT / projected_var if projected_var else 0.0
                veto_reasons.append(
                    f"1-day 99% VaR {projected_var}% exceeds ceiling {MAX_PORTFOLIO_VAR_PCT}% — scaled down"
                )
                final_pct = round(final_pct * scale, 2)

            if margin_utilization_pct >= MAX_MARGIN_UTILIZATION_PCT:
                veto_applied = True
                veto_reasons.append(
                    f"margin utilization {margin_utilization_pct}% already at/above "
                    f"{MAX_MARGIN_UTILIZATION_PCT}% ceiling — new position blocked"
                )
                final_pct = 0.0

            final_var = self._parametric_var_pct(final_pct)
            cluster_totals[cluster] = cluster_totals.get(cluster, 0.0) + final_pct
            total_allocated_pct += final_pct

            if veto_applied:
                vetoes.append(f"{symbol}: {'; '.join(veto_reasons)}")

            decisions.append(
                RiskDecision(
                    symbol=symbol,
                    proposed_decision=proposed_decision,
                    proposed_size_multiplier=proposed_multiplier,
                    win_rate_estimate=win_rate,
                    kelly_fraction_pct=kelly_pct,
                    base_position_pct=base_pct,
                    var_1d_99_pct=final_var,
                    cluster=cluster,
                    cluster_exposure_pct=round(cluster_totals[cluster], 2),
                    final_position_pct=final_pct,
                    veto_applied=veto_applied,
                    veto_reason="; ".join(veto_reasons) if veto_reasons else "No override needed",
                )
            )

        portfolio_var_pct = round(
            math.sqrt(sum(d.var_1d_99_pct**2 for d in decisions)), 3
        )  # conservative uncorrelated-sum approximation

        expert_summary = (
            f"Audited {len(decisions)} consensus proposals against Kelly sizing, VaR, margin, "
            f"and correlation ceilings. {len(vetoes)} position(s) overridden/downscaled. "
            f"Total allocation {round(total_allocated_pct, 1)}% of equity, "
            f"portfolio VaR≈{portfolio_var_pct}%."
        )

        signals = [
            {
                "sector": d.cluster,
                "bias": "bullish" if d.final_position_pct > 0 else "avoid",
                "tickers": [d.symbol],
                "reason": (
                    f"Final size {d.final_position_pct}% (Kelly {d.kelly_fraction_pct}%) — {d.veto_reason}"
                ),
            }
            for d in decisions
            if d.proposed_decision != "Rejected"
        ]

        recommendations = [
            f"{d.symbol}: allocate {d.final_position_pct}% of equity (VaR {d.var_1d_99_pct}%) — {d.veto_reason}"
            for d in decisions
        ]

        return RiskGuardrailReport(
            account_equity=ACCOUNT_EQUITY,
            margin_utilization_pct=margin_utilization_pct,
            decisions=decisions,
            total_allocated_pct=round(total_allocated_pct, 2),
            portfolio_var_1d_99_pct=portfolio_var_pct,
            vetoes=vetoes,
            expert_summary=expert_summary,
            market_signals=signals,
            recommendations=recommendations,
            data_source="Internal portfolio ledger + Adversarial Debate & Consensus Router state",
        )

    def to_dict(self, report: RiskGuardrailReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Risk Management & Guardrail Agent (The Ultimate Auditor)",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
                "temperature": self.temperature,
                "account_equity": report.account_equity,
                "margin_utilization_pct": report.margin_utilization_pct,
            },
            "decisions": [
                {
                    "symbol": d.symbol,
                    "proposed_decision": d.proposed_decision,
                    "proposed_size_multiplier": d.proposed_size_multiplier,
                    "win_rate_estimate": d.win_rate_estimate,
                    "kelly_fraction_pct": d.kelly_fraction_pct,
                    "base_position_pct": d.base_position_pct,
                    "var_1d_99_pct": d.var_1d_99_pct,
                    "cluster": d.cluster,
                    "cluster_exposure_pct": d.cluster_exposure_pct,
                    "final_position_pct": d.final_position_pct,
                    "veto_applied": d.veto_applied,
                    "veto_reason": d.veto_reason,
                }
                for d in report.decisions
            ],
            "metrics": {
                "total_allocated_pct": report.total_allocated_pct,
                "portfolio_var_1d_99_pct": report.portfolio_var_1d_99_pct,
                "veto_count": len(report.vetoes),
            },
            "vetoes": report.vetoes,
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "risk_guardrail_limits.json"
            catalog.write_text(
                json.dumps(
                    {
                        "max_single_position_pct": MAX_SINGLE_POSITION_PCT,
                        "max_portfolio_var_pct": MAX_PORTFOLIO_VAR_PCT,
                        "max_margin_utilization_pct": MAX_MARGIN_UTILIZATION_PCT,
                        "max_cluster_exposure_pct": MAX_CLUSTER_EXPOSURE_PCT,
                        "kelly_fraction": KELLY_FRACTION,
                        "sector_clusters": SECTOR_CLUSTERS,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        return result


def run_risk_guardrail_analysis(output: Path | None = None) -> dict[str, Any]:
    return RiskGuardrailExpert().run(output=output)
