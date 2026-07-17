"""
Failure-to-Deliver (FTD) & Regulation SHO Protocol Expert Agent
================================================================
Models the clearinghouse settlement mechanics that govern Failure-to-Deliver
positions at the National Securities Clearing Corporation (NSCC): the
Threshold Security List criteria (Rule 203(c)(6)) and the Rule 204
mandatory close-out windows.

Data: Yahoo Finance chart API (3-month daily OHLCV). Real FTD data is
published by FINRA/NSCC on a ~2-week lag and is not reachable from this
sandbox, so per-symbol "FTD risk proxy" figures are transparent, disclosed
proxies built from settlement-relevant volatility/volume anomalies — not
live clearinghouse fail data.
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
    "AAPL": "Mega-cap tech (low FTD risk)",
    "MSFT": "Mega-cap tech (low FTD risk)",
    "QQQ": "Nasdaq 100 (low FTD risk)",
    "IWM": "Russell 2000 (moderate FTD risk)",
    "GME": "Retail-driven small/mid cap (historically threshold-listed)",
    "COIN": "Crypto-adjacent equity (settlement friction prone)",
    "PLTR": "High-beta growth name (moderate settlement friction)",
}

CLEARINGHOUSE_REFERENCE: dict[str, str] = {
    "clearinghouse": "National Securities Clearing Corporation (NSCC)",
    "reference_url": "https://www.dtcc.com/about/businesses-and-subsidiaries/nscc",
    "standard_settlement_cycle": "T+1",
    "summary": (
        "An FTD occurs when a broker-dealer fails to deliver securities to the NSCC "
        "by the standard settlement cycle."
    ),
}

THRESHOLD_SECURITY_CRITERIA: dict[str, str] = {
    "rule": "Regulation SHO Rule 203(c)(6)",
    "consecutive_days": "5 consecutive settlement days",
    "share_floor": "10,000 shares or more",
    "float_pct_floor": "At least 0.5% of the issuer's total shares outstanding",
    "note": (
        "FTDs can be a byproduct of illegal naked short selling (no locate secured), "
        "or legitimate operational friction such as certificate-processing delays or "
        "rapid intra-day liquidity evaporation."
    ),
}

RULE_204_CLOSEOUT: list[dict[str, str]] = [
    {
        "category": "Long Sales / Standard FTDs",
        "closeout_deadline": "Beginning of regular trading hours on T+3",
    },
    {
        "category": "Short Sale FTDs",
        "closeout_deadline": "Beginning of regular trading hours on T+2 (morning after T+1 settlement failure)",
    },
    {
        "category": "Failure to Close Out",
        "closeout_deadline": (
            "Broker-dealer is prohibited from further short sales in the security without "
            "pre-borrowing or a firm locate arrangement until the FTD is resolved."
        ),
    },
]


@dataclass
class SymbolFTDProfile:
    symbol: str
    name: str
    last_close: float
    volume_spike_days: int
    gap_frequency_pct: float
    ftd_risk_proxy_score: float
    threshold_security_proxy_flag: bool
    rationale: str


@dataclass
class FTDAssessment:
    threshold_flagged_count: int
    average_ftd_risk_score: float
    highest_risk_symbol: str
    settlement_friction_signal: str
    closeout_signal: str
    conclusion: str


@dataclass
class FTDRegShoReport:
    symbols: list[SymbolFTDProfile]
    assessment: FTDAssessment
    ftd_pressure_score: float
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FTDRegShoExpert(BaseExpert):
    """Expert market analyst — Failure-to-Deliver / Regulation SHO settlement mechanics."""

    def __init__(
        self,
        delay_seconds: float = 0.35,
        *,
        pipeline_context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="ftd-regsho")
        self.delay_seconds = delay_seconds

    def _analyze_symbol(self, symbol: str, name: str) -> SymbolFTDProfile | None:
        data = self.fetch_yahoo_ohlcv(symbol, range_="3mo", interval="1d")
        closes = data.get("close", [])
        opens = data.get("open", [])
        volumes = data.get("volume", [])
        if len(closes) < 15:
            return None

        last_close = closes[-1]
        window = min(len(closes), 20)
        recent_closes = closes[-window:]
        recent_opens = opens[-window:]
        recent_volumes = volumes[-window:]

        avg_volume = statistics.mean(recent_volumes) if recent_volumes else 0.0
        volume_spike_days = sum(1 for v in recent_volumes if avg_volume and v >= avg_volume * 1.75)

        gaps = [
            abs(recent_opens[i] - recent_closes[i - 1]) / recent_closes[i - 1] * 100
            for i in range(1, len(recent_closes))
            if recent_closes[i - 1]
        ]
        gap_frequency_pct = round(
            (sum(1 for g in gaps if g >= 2.0) / len(gaps) * 100) if gaps else 0.0, 1
        )

        # Settlement-friction proxy: repeated large-volume days plus frequent overnight
        # gaps are the observable footprint of the intraday liquidity evaporation that
        # legitimately drives FTDs (in addition to naked-short scenarios we cannot see).
        volume_component = min(volume_spike_days / window * 100 * 0.6, 60)
        gap_component = min(gap_frequency_pct * 0.4, 40)
        ftd_risk_proxy_score = round(min(volume_component + gap_component, 100), 1)

        # Threshold Security List proxy: requires a sustained (5+ settlement day) pattern,
        # mirrored here as a proxy score consistently in the elevated band.
        threshold_flag = ftd_risk_proxy_score >= 55 and volume_spike_days >= 5

        rationale = (
            f"{volume_spike_days}/{window} high-volume days, {gap_frequency_pct:.1f}% gap frequency "
            f"→ FTD risk proxy {ftd_risk_proxy_score:.0f}/100."
        )

        return SymbolFTDProfile(
            symbol=symbol,
            name=name,
            last_close=round(last_close, 2),
            volume_spike_days=volume_spike_days,
            gap_frequency_pct=gap_frequency_pct,
            ftd_risk_proxy_score=ftd_risk_proxy_score,
            threshold_security_proxy_flag=threshold_flag,
            rationale=rationale,
        )

    def _assessment(self, symbols: list[SymbolFTDProfile]) -> FTDAssessment:
        flagged = [s for s in symbols if s.threshold_security_proxy_flag]
        highest = max(symbols, key=lambda s: s.ftd_risk_proxy_score) if symbols else None
        avg_score = round(statistics.mean([s.ftd_risk_proxy_score for s in symbols]), 1) if symbols else 0.0

        settlement_friction_signal = (
            f"{len(flagged)}/{len(symbols)} symbols show a settlement-friction footprint consistent "
            "with Rule 203(c)(6)'s 5-consecutive-day / 10,000-share / 0.5%-of-float threshold."
        )
        closeout_signal = (
            "Short-sale FTDs must close out by the open on T+2; failure to close out bars further "
            "short sales in that name without a pre-borrow or firm locate."
        )
        if highest and highest.threshold_security_proxy_flag:
            conclusion = (
                f"{highest.symbol} proxies as a Threshold Security candidate — treat as pre-borrow-only "
                "for new short exposure until the friction footprint clears."
            )
        elif flagged:
            conclusion = "Isolated settlement friction detected — monitor for a sustained 5-day pattern."
        else:
            conclusion = "No name currently proxies as Threshold-Security-risk; standard locate rules apply."

        return FTDAssessment(
            threshold_flagged_count=len(flagged),
            average_ftd_risk_score=avg_score,
            highest_risk_symbol=highest.symbol if highest else "",
            settlement_friction_signal=settlement_friction_signal,
            closeout_signal=closeout_signal,
            conclusion=conclusion,
        )

    def _expert_summary(self, assessment: FTDAssessment) -> str:
        return (
            f"FTD/Reg SHO scan: avg risk proxy {assessment.average_ftd_risk_score:.1f}/100. "
            f"{assessment.settlement_friction_signal} {assessment.closeout_signal} {assessment.conclusion}"
        )

    def _market_signals(self, symbols: list[SymbolFTDProfile]) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        def _keep(symbol: str) -> bool:
            return not self.pipeline_should_skip_symbol(symbol)

        flagged = [s.symbol for s in symbols if s.threshold_security_proxy_flag and _keep(s.symbol)]
        if flagged:
            signals.append(
                {
                    "sector": "FTD / Reg SHO",
                    "bias": "threshold-security-risk",
                    "tickers": flagged,
                    "reason": "Sustained settlement-friction footprint proxies a Rule 203(c)(6) threshold candidate.",
                }
            )
        elevated = [
            s.symbol
            for s in symbols
            if 30 <= s.ftd_risk_proxy_score < 55 and _keep(s.symbol)
        ]
        if elevated:
            signals.append(
                {
                    "sector": "FTD / Reg SHO",
                    "bias": "settlement-friction",
                    "tickers": elevated,
                    "reason": "Elevated volume/gap footprint — early-stage FTD risk to monitor.",
                }
            )
        clean = [s.symbol for s in symbols if s.ftd_risk_proxy_score < 15 and _keep(s.symbol)]
        if clean:
            signals.append(
                {
                    "sector": "FTD / Reg SHO",
                    "bias": "clean-settlement",
                    "tickers": clean,
                    "reason": "No settlement-friction footprint — standard locate/settlement applies.",
                }
            )
        return signals

    def _recommendations(
        self, symbols: list[SymbolFTDProfile], assessment: FTDAssessment
    ) -> list[str]:
        recs = [assessment.conclusion]
        for s in sorted(symbols, key=lambda x: -x.ftd_risk_proxy_score)[:6]:
            flag = "Threshold-candidate" if s.threshold_security_proxy_flag else "Not flagged"
            recs.append(f"{s.symbol} [{flag}]: {s.rationale}")
        return recs

    def analyze(self) -> FTDRegShoReport:
        symbols: list[SymbolFTDProfile] = []
        for symbol, name in WATCHLIST.items():
            row = self._analyze_symbol(symbol, name)
            if row:
                symbols.append(row)
            time.sleep(self.delay_seconds)

        if not any(s.symbol == BENCHMARK for s in symbols):
            raise RuntimeError("Unable to fetch SPY data for ftd-regsho analysis")

        assessment = self._assessment(symbols)
        expert_summary = self._expert_summary(assessment)
        ftd_pressure_score = round(
            statistics.mean([s.ftd_risk_proxy_score for s in symbols]) / 10, 1
        )

        return FTDRegShoReport(
            symbols=symbols,
            assessment=assessment,
            ftd_pressure_score=ftd_pressure_score,
            expert_summary=expert_summary,
            market_signals=self._market_signals(symbols),
            recommendations=self._recommendations(symbols, assessment),
            data_source=(
                "Yahoo Finance Chart API (3mo daily OHLCV) — FTD risk is a volume/gap proxy, "
                "not live NSCC/FINRA fail data"
            ),
        )

    def to_dict(self, report: FTDRegShoReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Failure-to-Deliver (FTD) & Regulation SHO Protocol Expert",
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
            "clearinghouse_reference": CLEARINGHOUSE_REFERENCE,
            "threshold_security_criteria": THRESHOLD_SECURITY_CRITERIA,
            "rule_204_closeout": RULE_204_CLOSEOUT,
            "symbol_ftd_profiles": [
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "last_close": s.last_close,
                    "volume_spike_days": s.volume_spike_days,
                    "gap_frequency_pct": s.gap_frequency_pct,
                    "ftd_risk_proxy_score": s.ftd_risk_proxy_score,
                    "threshold_security_proxy_flag": s.threshold_security_proxy_flag,
                    "rationale": s.rationale,
                }
                for s in report.symbols
            ],
            "ftd_assessment": {
                "threshold_flagged_count": a.threshold_flagged_count,
                "average_ftd_risk_score": a.average_ftd_risk_score,
                "highest_risk_symbol": a.highest_risk_symbol,
                "settlement_friction_signal": a.settlement_friction_signal,
                "closeout_signal": a.closeout_signal,
                "conclusion": a.conclusion,
            },
            "metrics": {"ftd_pressure_score": report.ftd_pressure_score},
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "regsho_threshold_criteria.json"
            catalog.write_text(
                json.dumps(
                    {
                        "threshold_security_criteria": THRESHOLD_SECURITY_CRITERIA,
                        "rule_204_closeout": RULE_204_CLOSEOUT,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        return result


def run_ftd_regsho_analysis(
    output: Path | None = None,
    pipeline_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return FTDRegShoExpert(pipeline_context=pipeline_context).run(output=output)
