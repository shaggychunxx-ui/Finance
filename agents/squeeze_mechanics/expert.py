"""
Squeeze Evolution & Liquidation Cascade Expert Agent
=====================================================
A short squeeze is a forced mechanical unwinding driven by risk-management
algorithms and clearinghouse collateral demands, not just a psychological
shift:

  Price Spikes -> Margin Threshold Violated -> Automated Buy-to-Cover
  Market Orders -> Float Illiquidity Absorbs Orders -> Price Accelerates Upward

This agent screens the watchlist for where a name sits on that cascade using
momentum/volatility proxies, and models the gamma-exposure ("GEX") feedback
loop from options market-maker hedging.

Data: Yahoo Finance chart API (3-month daily OHLCV). Real-time margin-call
telemetry and options gamma exposure feeds are not reachable from this
sandbox, so per-symbol cascade staging is a transparent, disclosed proxy
built from realized momentum/volatility — not a live risk-desk feed.
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
    "AAPL": "Mega-cap tech (low squeeze risk)",
    "MSFT": "Mega-cap tech (low squeeze risk)",
    "QQQ": "Nasdaq 100 (low squeeze risk)",
    "IWM": "Russell 2000 (moderate squeeze risk)",
    "GME": "Retail-driven small/mid cap (historically squeeze-prone)",
    "COIN": "Crypto-adjacent equity (high beta)",
    "PLTR": "High-beta growth name (options-heavy)",
}

CASCADE_STAGES: list[dict[str, str]] = [
    {
        "stage": "1. Price Spikes",
        "description": "Catalyst-driven rally reduces the value of short sellers' equity cushion.",
    },
    {
        "stage": "2. Margin Threshold Violated",
        "description": "Broker's Maintenance Margin Requirement (MMR) breach triggers a margin call.",
    },
    {
        "stage": "3. Automated Buy-to-Cover Market Orders",
        "description": "Uncured margin calls trigger the broker risk desk's forced buy-to-cover orders.",
    },
    {
        "stage": "4. Float Illiquidity Absorbs Orders",
        "description": "Thin float cannot absorb forced buying without material price impact.",
    },
    {
        "stage": "5. Price Accelerates Upward",
        "description": "Forced buying pushes price higher, triggering further margin calls — the loop compounds.",
    },
]

MARGIN_THRESHOLDS: dict[str, str] = {
    "standard_equity_mmr": "30% – 40% maintenance margin requirement",
    "volatile_htb_mmr": "Up to 100% or higher for volatile Hard-to-Borrow stocks",
    "note": (
        "If equity falls below the threshold, a margin call is issued; failure to post "
        "additional collateral promptly triggers automated Buy-to-Cover market orders."
    ),
}

GEX_FACTOR: dict[str, str] = {
    "name": "Gamma Exposure (Gamma Squeeze)",
    "mechanism": (
        "Retail investors buy out-of-the-money (OTM) call options. Market makers who "
        "sold those options must hedge by buying the underlying stock. As price rises, "
        "market makers must buy exponentially more shares (delta increases toward 1), "
        "creating a compounding feedback loop that crushes short sellers."
    ),
}


@dataclass
class SymbolSqueezeProfile:
    symbol: str
    name: str
    last_close: float
    return_5d_pct: float
    return_10d_pct: float
    realized_vol_pct: float
    volume_spike_ratio: float
    squeeze_risk_score: float
    cascade_stage: str
    margin_call_proxy_pct: float
    rationale: str


@dataclass
class SqueezeAssessment:
    elevated_risk_count: int
    average_squeeze_risk_score: float
    hottest_symbol: str
    cascade_signal: str
    gamma_signal: str
    conclusion: str


@dataclass
class SqueezeMechanicsReport:
    symbols: list[SymbolSqueezeProfile]
    assessment: SqueezeAssessment
    squeeze_pressure_score: float
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SqueezeMechanicsExpert(BaseExpert):
    """Expert market analyst — short-squeeze cascade mechanics and gamma exposure."""

    def __init__(
        self,
        delay_seconds: float = 0.35,
        *,
        pipeline_context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="squeeze-mechanics")
        self.delay_seconds = delay_seconds

    @staticmethod
    def _cascade_stage_for_score(score: float) -> str:
        if score < 20:
            return "No cascade risk — stable float/equity cushion"
        if score < 40:
            return CASCADE_STAGES[0]["stage"]
        if score < 60:
            return CASCADE_STAGES[1]["stage"]
        if score < 80:
            return CASCADE_STAGES[2]["stage"] + " / " + CASCADE_STAGES[3]["stage"]
        return CASCADE_STAGES[4]["stage"]

    def _analyze_symbol(self, symbol: str, name: str) -> SymbolSqueezeProfile | None:
        data = self.fetch_yahoo_ohlcv(symbol, range_="3mo", interval="1d")
        closes = data.get("close", [])
        volumes = data.get("volume", [])
        if len(closes) < 15:
            return None

        last_close = closes[-1]
        return_5d_pct = round((closes[-1] / closes[-6] - 1) * 100, 2) if len(closes) >= 6 else 0.0
        return_10d_pct = round((closes[-1] / closes[-11] - 1) * 100, 2) if len(closes) >= 11 else 0.0

        window = min(len(closes), 20)
        recent_closes = closes[-window:]
        recent_volumes = volumes[-window:]
        daily_returns = [
            abs(recent_closes[i] / recent_closes[i - 1] - 1) * 100
            for i in range(1, len(recent_closes))
            if recent_closes[i - 1]
        ]
        realized_vol_pct = round(statistics.mean(daily_returns) if daily_returns else 0.0, 2)

        avg_volume = statistics.mean(recent_volumes) if recent_volumes else 0.0
        latest_volume = volumes[-1] if volumes else 0.0
        volume_spike_ratio = round(latest_volume / avg_volume, 2) if avg_volume else 1.0

        # Squeeze risk proxy: upside momentum + realized volatility + volume spike —
        # the observable footprint of a forced buy-to-cover cascade in progress.
        momentum_component = max(0.0, min(return_5d_pct, 40)) * 1.2
        vol_component = min(realized_vol_pct / 8.0 * 30, 30)
        volume_component = max(0.0, min((volume_spike_ratio - 1) * 20, 30))
        squeeze_risk_score = round(min(momentum_component + vol_component + volume_component, 100), 1)

        cascade_stage = self._cascade_stage_for_score(squeeze_risk_score)
        margin_call_proxy_pct = round(min(squeeze_risk_score * 0.9, 100), 1)

        rationale = (
            f"5d return {return_5d_pct:+.2f}%, realized vol {realized_vol_pct:.2f}%/day, "
            f"volume {volume_spike_ratio:.2f}x average → squeeze risk score {squeeze_risk_score:.0f}/100."
        )

        return SymbolSqueezeProfile(
            symbol=symbol,
            name=name,
            last_close=round(last_close, 2),
            return_5d_pct=return_5d_pct,
            return_10d_pct=return_10d_pct,
            realized_vol_pct=realized_vol_pct,
            volume_spike_ratio=volume_spike_ratio,
            squeeze_risk_score=squeeze_risk_score,
            cascade_stage=cascade_stage,
            margin_call_proxy_pct=margin_call_proxy_pct,
            rationale=rationale,
        )

    def _assessment(self, symbols: list[SymbolSqueezeProfile]) -> SqueezeAssessment:
        elevated = [s for s in symbols if s.squeeze_risk_score >= 60]
        hottest = max(symbols, key=lambda s: s.squeeze_risk_score) if symbols else None
        avg_score = round(statistics.mean([s.squeeze_risk_score for s in symbols]), 1) if symbols else 0.0

        cascade_signal = (
            f"{len(elevated)}/{len(symbols)} symbols screen at Stage 3+ (forced buy-to-cover risk) — "
            "float illiquidity there can absorb margin-driven orders poorly."
        )
        gamma_signal = (
            f"Gamma-exposure feedback ({GEX_FACTOR['name']}) is most relevant on the "
            f"highest-momentum, options-heavy names in the set."
        )
        if hottest and hottest.squeeze_risk_score >= 80:
            conclusion = (
                f"{hottest.symbol} is at/near the top of the cascade ({hottest.cascade_stage}) — "
                "short exposure there carries acute forced-liquidation risk."
            )
        elif elevated:
            conclusion = "Squeeze pressure is building on select names — tighten short risk limits there."
        else:
            conclusion = "No name in the watchlist currently screens as cascade-risk elevated."

        return SqueezeAssessment(
            elevated_risk_count=len(elevated),
            average_squeeze_risk_score=avg_score,
            hottest_symbol=hottest.symbol if hottest else "",
            cascade_signal=cascade_signal,
            gamma_signal=gamma_signal,
            conclusion=conclusion,
        )

    def _expert_summary(self, assessment: SqueezeAssessment) -> str:
        return (
            f"Squeeze-cascade scan: avg risk score {assessment.average_squeeze_risk_score:.1f}/100. "
            f"{assessment.cascade_signal} {assessment.gamma_signal} {assessment.conclusion}"
        )

    def _market_signals(self, symbols: list[SymbolSqueezeProfile]) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        def _keep(symbol: str) -> bool:
            return not self.pipeline_should_skip_symbol(symbol)

        elevated = [s.symbol for s in symbols if s.squeeze_risk_score >= 60 and _keep(s.symbol)]
        if elevated:
            signals.append(
                {
                    "sector": "Squeeze Mechanics",
                    "bias": "cascade-risk",
                    "tickers": elevated,
                    "reason": "Momentum/volume footprint consistent with a forced buy-to-cover cascade.",
                }
            )
        volume_spikes = [s.symbol for s in symbols if s.volume_spike_ratio >= 2.0 and _keep(s.symbol)]
        if volume_spikes:
            signals.append(
                {
                    "sector": "Squeeze Mechanics",
                    "bias": "gamma-amplified",
                    "tickers": volume_spikes,
                    "reason": "Volume spike consistent with market-maker delta hedging (gamma squeeze).",
                }
            )
        stable = [s.symbol for s in symbols if s.squeeze_risk_score < 20 and _keep(s.symbol)]
        if stable:
            signals.append(
                {
                    "sector": "Squeeze Mechanics",
                    "bias": "stable",
                    "tickers": stable,
                    "reason": "No cascade footprint — short exposure carries normal risk here.",
                }
            )
        return signals

    def _recommendations(
        self, symbols: list[SymbolSqueezeProfile], assessment: SqueezeAssessment
    ) -> list[str]:
        recs = [assessment.conclusion]
        for s in sorted(symbols, key=lambda x: -x.squeeze_risk_score)[:6]:
            recs.append(
                f"{s.symbol} [{s.cascade_stage}]: margin-call proxy {s.margin_call_proxy_pct:.0f}% — "
                f"{s.rationale}"
            )
        return recs

    def analyze(self) -> SqueezeMechanicsReport:
        symbols: list[SymbolSqueezeProfile] = []
        for symbol, name in WATCHLIST.items():
            row = self._analyze_symbol(symbol, name)
            if row:
                symbols.append(row)
            time.sleep(self.delay_seconds)

        if not any(s.symbol == BENCHMARK for s in symbols):
            raise RuntimeError("Unable to fetch SPY data for squeeze-mechanics analysis")

        assessment = self._assessment(symbols)
        expert_summary = self._expert_summary(assessment)
        squeeze_pressure_score = round(
            statistics.mean([s.squeeze_risk_score for s in symbols]) / 10, 1
        )

        return SqueezeMechanicsReport(
            symbols=symbols,
            assessment=assessment,
            squeeze_pressure_score=squeeze_pressure_score,
            expert_summary=expert_summary,
            market_signals=self._market_signals(symbols),
            recommendations=self._recommendations(symbols, assessment),
            data_source="Yahoo Finance Chart API (3mo daily OHLCV) — cascade staging is a momentum/volume proxy",
        )

    def to_dict(self, report: SqueezeMechanicsReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Squeeze Evolution & Liquidation Cascade Expert",
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
            "cascade_stages": CASCADE_STAGES,
            "margin_thresholds": MARGIN_THRESHOLDS,
            "gex_factor": GEX_FACTOR,
            "symbol_squeeze_profiles": [
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "last_close": s.last_close,
                    "return_5d_pct": s.return_5d_pct,
                    "return_10d_pct": s.return_10d_pct,
                    "realized_vol_pct": s.realized_vol_pct,
                    "volume_spike_ratio": s.volume_spike_ratio,
                    "squeeze_risk_score": s.squeeze_risk_score,
                    "cascade_stage": s.cascade_stage,
                    "margin_call_proxy_pct": s.margin_call_proxy_pct,
                    "rationale": s.rationale,
                }
                for s in report.symbols
            ],
            "squeeze_assessment": {
                "elevated_risk_count": a.elevated_risk_count,
                "average_squeeze_risk_score": a.average_squeeze_risk_score,
                "hottest_symbol": a.hottest_symbol,
                "cascade_signal": a.cascade_signal,
                "gamma_signal": a.gamma_signal,
                "conclusion": a.conclusion,
            },
            "metrics": {"squeeze_pressure_score": report.squeeze_pressure_score},
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "squeeze_cascade_stages.json"
            catalog.write_text(json.dumps(CASCADE_STAGES, indent=2), encoding="utf-8")
        return result


def run_squeeze_mechanics_analysis(
    output: Path | None = None,
    pipeline_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return SqueezeMechanicsExpert(pipeline_context=pipeline_context).run(output=output)
