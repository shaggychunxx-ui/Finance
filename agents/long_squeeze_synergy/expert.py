"""
Structural Synergy Expert Agent: Long Squeezes & Institutional Tailwinds
=========================================================================
Targets scenarios where systemic buying pressure is (or has historically
been) guaranteed by market structure rather than random stock picking:

* Index Inclusion Front-Running — mandatory ETF buying when a stock joins
  a major index.
* The Long Gamma Squeeze — market makers forced to buy shares to hedge
  short call options, approximated here with a volume+momentum spike scan.
* Post-Earnings Announcement Drift (PEAD) — underreaction to exceptional
  earnings, approximated with momentum-acceleration between the trailing
  1-month and 3-month return.

Data: Yahoo Finance chart API (3-month daily OHLCV).
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base import BaseExpert

BENCHMARK = "SPY"
VOLUME_LOOKBACK_DAYS = 20
GAMMA_VOLUME_Z_THRESHOLD = 1.75
GAMMA_MOMENTUM_THRESHOLD_PCT = 8.0
PEAD_ACCELERATION_THRESHOLD_PCT = 3.0

WATCHLIST: dict[str, str] = {
    "SPY": "Broad market benchmark",
    "GME": "Low-float retail favorite (gamma squeeze history)",
    "AMC": "Low-float retail favorite (gamma squeeze history)",
    "NVDA": "High-beta semiconductor (institutional call flow)",
    "PLTR": "High-beta growth (retail + institutional flow)",
    "SMCI": "High-beta AI infrastructure (call-heavy flow)",
    "TSLA": "High-beta mega-cap (frequent index/gamma activity)",
}

STRUCTURAL_CATALYSTS: list[dict[str, Any]] = [
    {
        "id": "index_inclusion_front_running",
        "name": "Index Inclusion Front-Running",
        "structural_catalyst": "Mandatory ETF buying when a stock joins an index (e.g. S&P 500).",
        "execution_strategy": (
            "Buy the stock immediately upon announcement; sell to passive funds "
            "on the exact day of inclusion."
        ),
    },
    {
        "id": "long_gamma_squeeze",
        "name": "The Long Gamma Squeeze",
        "structural_catalyst": "Market makers forced to buy shares to hedge short call options.",
        "execution_strategy": (
            "Buy equity or near-the-money calls on low-float stocks experiencing "
            "sudden, massive call option volume spikes."
        ),
        "proxy_used": (
            f"Volume z-score >= {GAMMA_VOLUME_Z_THRESHOLD} combined with trailing "
            f"1-month price momentum >= {GAMMA_MOMENTUM_THRESHOLD_PCT}% (equity flow "
            "proxy for call-option volume, since options chain data is unavailable)."
        ),
    },
    {
        "id": "post_earnings_announcement_drift",
        "name": "Post-Earnings Announcement Drift (PEAD)",
        "structural_catalyst": "Underreaction to exceptional earnings reports.",
        "execution_strategy": (
            "Buy companies that beat earnings expectations by 10%+ and raise "
            "forward guidance; hold for 30-90 days as funds slowly accumulate."
        ),
        "proxy_used": (
            f"Momentum acceleration: 1-month return exceeding the 3-month return "
            f"by {PEAD_ACCELERATION_THRESHOLD_PCT}+ points (drift-continuation proxy)."
        ),
    },
]


@dataclass
class SqueezeCandidate:
    symbol: str
    label: str
    volume_zscore: float
    one_month_return_pct: float
    three_month_return_pct: float
    gamma_squeeze_flag: bool
    pead_drift_flag: bool


@dataclass
class LongSqueezeReport:
    candidates: list[SqueezeCandidate]
    gamma_squeeze_count: int
    pead_drift_count: int
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class LongSqueezeSynergyExpert(BaseExpert):
    """Structural long squeeze and institutional tailwind catalyst scanner."""

    def __init__(self, *, pipeline_context: dict | None = None) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="long-squeeze-synergy")
        self.delay_seconds = 0.35

    @staticmethod
    def _return_pct(closes: list[float], lookback_days: int) -> float:
        if len(closes) <= lookback_days or not closes[-lookback_days - 1]:
            return 0.0
        return round((closes[-1] / closes[-lookback_days - 1] - 1) * 100, 2)

    def _scan_symbol(self, symbol: str, label: str, ohlcv: dict[str, list[float]]) -> SqueezeCandidate | None:
        closes, volumes = ohlcv["close"], ohlcv["volume"]
        if len(closes) < 25:
            return None
        window = volumes[-VOLUME_LOOKBACK_DAYS - 1:-1] if len(volumes) > VOLUME_LOOKBACK_DAYS else volumes[:-1]
        vol_z = 0.0
        if len(window) >= 2:
            mean = statistics.mean(window)
            stdev = statistics.pstdev(window)
            if stdev > 0:
                vol_z = round((volumes[-1] - mean) / stdev, 3)
        one_month = self._return_pct(closes, min(21, len(closes) - 1))
        three_month = self._return_pct(closes, min(63, len(closes) - 1))
        gamma_flag = vol_z >= GAMMA_VOLUME_Z_THRESHOLD and one_month >= GAMMA_MOMENTUM_THRESHOLD_PCT
        pead_flag = (one_month - three_month) >= PEAD_ACCELERATION_THRESHOLD_PCT
        return SqueezeCandidate(
            symbol=symbol,
            label=label,
            volume_zscore=vol_z,
            one_month_return_pct=one_month,
            three_month_return_pct=three_month,
            gamma_squeeze_flag=gamma_flag,
            pead_drift_flag=pead_flag,
        )

    def _market_signals(self, candidates: list[SqueezeCandidate]) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal

        signals: list[dict[str, Any]] = []
        gamma = [c for c in candidates if c.gamma_squeeze_flag]
        if gamma:
            signals.append(
                build_market_signal(
                    sector="Long Gamma Squeeze",
                    tickers=[c.symbol for c in gamma][:5],
                    bias="BULLISH",
                    reason=(
                        f"{len(gamma)} low-float/high-beta names with volume z-score "
                        f">= {GAMMA_VOLUME_Z_THRESHOLD} and momentum >= {GAMMA_MOMENTUM_THRESHOLD_PCT}%"
                    ),
                    confidence=min(0.78, 0.5 + 0.06 * len(gamma)),
                )
            )
        pead = [c for c in candidates if c.pead_drift_flag]
        if pead:
            signals.append(
                build_market_signal(
                    sector="Post-Earnings Drift",
                    tickers=[c.symbol for c in pead][:5],
                    bias="BULLISH",
                    reason=f"{len(pead)} names showing momentum acceleration consistent with PEAD",
                    confidence=0.55,
                )
            )
        if not signals:
            signals.append(
                build_market_signal(
                    sector="Structural Synergy",
                    tickers=[BENCHMARK],
                    bias="NEUTRAL",
                    reason="No gamma-squeeze or PEAD-consistent candidates detected in the watchlist",
                    confidence=0.4,
                )
            )
        return signals

    def analyze(self) -> LongSqueezeReport:
        candidates: list[SqueezeCandidate] = []
        for symbol, label in WATCHLIST.items():
            ohlcv = self.fetch_yahoo_ohlcv(symbol, range_="3mo", interval="1d")
            if not ohlcv["close"]:
                continue
            candidate = self._scan_symbol(symbol, label, ohlcv)
            if candidate:
                candidates.append(candidate)

        if not any(c.symbol == BENCHMARK for c in candidates):
            raise RuntimeError("Unable to fetch SPY data for long squeeze synergy analysis")

        gamma_count = sum(1 for c in candidates if c.gamma_squeeze_flag)
        pead_count = sum(1 for c in candidates if c.pead_drift_flag)

        summary = (
            f"Scanned {len(candidates)} structural-catalyst candidates: "
            f"{gamma_count} gamma-squeeze setups, {pead_count} PEAD-drift setups."
        )

        recs = [summary]
        for c in sorted(candidates, key=lambda x: x.one_month_return_pct, reverse=True)[:5]:
            flags = []
            if c.gamma_squeeze_flag:
                flags.append("GAMMA")
            if c.pead_drift_flag:
                flags.append("PEAD")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            recs.append(
                f"{c.symbol} ({c.label}): 1mo {c.one_month_return_pct}%, 3mo {c.three_month_return_pct}%, "
                f"vol z={c.volume_zscore}{flag_str}"
            )
        recs.append("Verify index-inclusion candidates against official S&P/Russell reconstitution calendars.")

        return LongSqueezeReport(
            candidates=candidates,
            gamma_squeeze_count=gamma_count,
            pead_drift_count=pead_count,
            expert_summary=summary,
            market_signals=self._market_signals(candidates),
            recommendations=recs,
        )

    def to_dict(self, report: LongSqueezeReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Structural Synergy Expert (Long Squeezes & Institutional Tailwinds)",
                "analyzed_at": report.analyzed_at,
                "data_sources": ["Yahoo Finance Chart API"],
                "expert_summary": report.expert_summary,
                "temperature": self.temperature,
            },
            "metrics": {
                "gamma_squeeze_count": report.gamma_squeeze_count,
                "pead_drift_count": report.pead_drift_count,
            },
            "candidates": [
                {
                    "symbol": c.symbol,
                    "label": c.label,
                    "volume_zscore": c.volume_zscore,
                    "one_month_return_pct": c.one_month_return_pct,
                    "three_month_return_pct": c.three_month_return_pct,
                    "gamma_squeeze_flag": c.gamma_squeeze_flag,
                    "pead_drift_flag": c.pead_drift_flag,
                }
                for c in report.candidates
            ],
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "structural_catalysts.json"
            catalog.write_text(json.dumps(STRUCTURAL_CATALYSTS, indent=2), encoding="utf-8")
        return result


def run_long_squeeze_synergy_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return LongSqueezeSynergyExpert(pipeline_context=pipeline_context).run(output=output)
