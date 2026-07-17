"""
Sector Rotation & Relative Strength Expert Agent
=================================================
Tracks relative strength (RS) of the 11 major S&P sector ETFs against the
S&P 500 benchmark (SPY), applies a moving-average trend filter, and derives
a simplified Relative Rotation Graph (RRG) style JdK RS-Ratio / RS-Momentum
reading for each sector to classify it into one of four quadrants:
Leading, Weakening, Lagging, or Improving.

The agent also maps the current sector leadership mix onto the four-stage
business cycle (Early / Mid / Late / Recession) using the classic sector
rotation playbook.

Data source: Yahoo Finance chart API (via ``agents.market_data.yahoo``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base import BaseExpert

DASHBOARD_URL = "https://finance.yahoo.com/"
BENCHMARK = "SPY"

# RS-line trend/momentum tuning constants.
LONG_SMA_WINDOW = 200
MIN_POINTS_FOR_LONG_SMA = 210
SHORT_SMA_MIN = 5
SHORT_SMA_MAX = 20
FALLBACK_SMA_BUFFER = 10
FALLBACK_SMA_CAP = 50  # trend-filter window cap when fewer than MIN_POINTS_FOR_LONG_SMA closes exist
MOMENTUM_LOOKBACK_PERIODS = 5
MOMENTUM_SCALE_FACTOR = 3.0  # amplifies the 5-period RS-Ratio change into an RS-Momentum reading

# Cycle-confidence scoring.
CYCLE_CONFIDENCE_BASE = 0.35
CYCLE_CONFIDENCE_SCALE = 0.65
CYCLE_CONFIDENCE_MAX = 0.95

# Rotation-strength normalization (RS-Ratio spread between top and bottom sector).
ROTATION_SPREAD_NORMALIZER = 20.0

# Signal-confidence weighting (deviation of RS-Ratio/RS-Momentum from the 100 baseline).
CONFIDENCE_DEVIATION_SCALE = 8.0
CONFIDENCE_BASE = 0.4
CONFIDENCE_RATIO_WEIGHT = 0.35
CONFIDENCE_MOMENTUM_WEIGHT = 0.25
IMPROVING_SECTOR_BASE_CONFIDENCE = 0.42
FALLBACK_NEUTRAL_CONFIDENCE = 0.4

SECTOR_ETFS: dict[str, str] = {
    "XLK": "Technology",
    "XLC": "Communication Services",
    "XLY": "Consumer Discretionary",
    "XLF": "Financials",
    "XLI": "Industrials",
    "XLE": "Energy",
    "XLB": "Materials",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLV": "Health Care",
    "XLRE": "Real Estate",
}

# Classic sector rotation playbook mapped across the four-stage business cycle.
CYCLE_PLAYBOOK: dict[str, dict[str, Any]] = {
    "Early Cycle": {
        "conditions": "GDP rebounds; rates low; credit loosens",
        "sectors": ["XLY", "XLF", "XLI"],
        "rationale": "Cyclicals lead as lower rates boost consumer confidence, "
        "housing demand, and bank lending margins.",
    },
    "Mid-Cycle": {
        "conditions": "Growth stabilizes; profits peak; policy turns neutral",
        "sectors": ["XLK", "XLC"],
        "rationale": "Growth leads as businesses raise capex on technology, "
        "software, automation, and digital infrastructure.",
    },
    "Late Cycle": {
        "conditions": "Inflation climbs; labor tightens; central banks hike",
        "sectors": ["XLE", "XLB"],
        "rationale": "Hard assets lead — high commodity prices lift resource "
        "extractor and energy producer margins as an inflation hedge.",
    },
    "Recession": {
        "conditions": "Growth contracts; earnings fall; credit dries up",
        "sectors": ["XLP", "XLU", "XLV"],
        "rationale": "Defensives lead as spending shifts to non-discretionary "
        "necessities: groceries, prescriptions, electricity, water.",
    },
}

QUADRANTS = ("Leading", "Weakening", "Lagging", "Improving")


def _sma(series: list[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(series)
    if window <= 0 or len(series) < window:
        return out
    running = sum(series[:window])
    out[window - 1] = running / window
    for i in range(window, len(series)):
        running += series[i] - series[i - window]
        out[i] = running / window
    return out


@dataclass
class SectorLine:
    etf: str
    sector: str
    rs_value: float
    rs_ratio: float
    rs_momentum: float
    quadrant: str
    trend_filter: str
    sma_window: int
    day_chg_pct: float | None
    week_chg_pct: float | None


@dataclass
class RotationAssessment:
    cycle_phase: str
    cycle_confidence: float
    conditions: str
    rationale: str
    playbook_sectors: list[str]
    aligned_sectors: list[str]
    leading: list[str]
    weakening: list[str]
    lagging: list[str]
    improving: list[str]


@dataclass
class RotationReport:
    benchmark: str
    sectors: list[SectorLine]
    assessment: RotationAssessment
    breadth_score: float
    rotation_strength_score: float
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SectorRotationExpert(BaseExpert):
    """Expert relative-strength / sector-rotation analyst with an RRG-style quadrant read."""

    def __init__(
        self,
        *,
        range_: str = "1y",
        pipeline_context: dict | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="sector-rotation")
        self.range_ = range_
        self.delay_seconds = 0.35

    def _closes(self, symbol: str) -> list[float]:
        return self.fetch_yahoo_closes(symbol, range_=self.range_, interval="1d")

    @staticmethod
    def _pct_change(series: list[float], periods: int) -> float | None:
        if len(series) <= periods:
            return None
        prev = series[-1 - periods]
        if not prev:
            return None
        return round((series[-1] / prev - 1.0) * 100.0, 2)

    def _sector_line(self, etf: str, name: str, bench_closes: list[float]) -> SectorLine | None:
        sector_closes = self._closes(etf)
        n = min(len(sector_closes), len(bench_closes))
        if n < 30:
            return None
        sector_closes = sector_closes[-n:]
        bench_closes = bench_closes[-n:]
        rs_line = [s / b for s, b in zip(sector_closes, bench_closes) if b]
        if len(rs_line) < 30:
            return None

        window = (
            LONG_SMA_WINDOW
            if len(rs_line) >= MIN_POINTS_FOR_LONG_SMA
            else max(SHORT_SMA_MIN, min(FALLBACK_SMA_CAP, len(rs_line) - FALLBACK_SMA_BUFFER))
        )
        window = min(int(window), len(rs_line))
        rs_sma = _sma(rs_line, window)
        current_rs = rs_line[-1]
        current_sma = rs_sma[-1]
        trend_filter = "unavailable"
        if current_sma:
            trend_filter = "bullish" if current_rs > current_sma else "bearish"

        # JdK-style RS-Ratio / RS-Momentum proxy: smooth the RS line with a short
        # SMA, express current RS as a percent of that smoothing baseline
        # (centered on 100), then measure the 5-period rate of change of that
        # ratio as the momentum reading (also centered on 100).
        short_window = min(SHORT_SMA_MAX, max(SHORT_SMA_MIN, len(rs_line) // 4))
        short_sma = _sma(rs_line, short_window)
        rs_ratio_series: list[float] = []
        for i, sma_val in enumerate(short_sma):
            if sma_val:
                rs_ratio_series.append(100.0 * rs_line[i] / sma_val)
        if not rs_ratio_series:
            return None
        rs_ratio = round(rs_ratio_series[-1], 2)

        lookback = MOMENTUM_LOOKBACK_PERIODS
        if len(rs_ratio_series) > lookback:
            momentum_raw = rs_ratio_series[-1] - rs_ratio_series[-1 - lookback]
        else:
            momentum_raw = 0.0
        rs_momentum = round(100.0 + momentum_raw * MOMENTUM_SCALE_FACTOR, 2)

        if rs_ratio >= 100 and rs_momentum >= 100:
            quadrant = "Leading"
        elif rs_ratio >= 100 and rs_momentum < 100:
            quadrant = "Weakening"
        elif rs_ratio < 100 and rs_momentum < 100:
            quadrant = "Lagging"
        else:
            quadrant = "Improving"

        return SectorLine(
            etf=etf,
            sector=name,
            rs_value=round(current_rs, 6),
            rs_ratio=rs_ratio,
            rs_momentum=rs_momentum,
            quadrant=quadrant,
            trend_filter=trend_filter,
            sma_window=window,
            day_chg_pct=self._pct_change(sector_closes, 1),
            week_chg_pct=self._pct_change(sector_closes, 5),
        )

    def _cycle_assessment(self, sectors: list[SectorLine]) -> RotationAssessment:
        leading = [s.etf for s in sectors if s.quadrant == "Leading"]
        weakening = [s.etf for s in sectors if s.quadrant == "Weakening"]
        lagging = [s.etf for s in sectors if s.quadrant == "Lagging"]
        improving = [s.etf for s in sectors if s.quadrant == "Improving"]

        best_phase = "Mid-Cycle"
        best_overlap = -1
        best_aligned: list[str] = []
        for phase, info in CYCLE_PLAYBOOK.items():
            aligned = [etf for etf in info["sectors"] if etf in leading]
            if len(aligned) > best_overlap:
                best_overlap = len(aligned)
                best_phase = phase
                best_aligned = aligned

        phase_size = len(CYCLE_PLAYBOOK[best_phase]["sectors"])
        confidence = (
            round(
                min(
                    CYCLE_CONFIDENCE_MAX,
                    CYCLE_CONFIDENCE_BASE + CYCLE_CONFIDENCE_SCALE * (best_overlap / phase_size),
                ),
                3,
            )
            if phase_size
            else CYCLE_CONFIDENCE_BASE
        )

        return RotationAssessment(
            cycle_phase=best_phase,
            cycle_confidence=confidence,
            conditions=CYCLE_PLAYBOOK[best_phase]["conditions"],
            rationale=CYCLE_PLAYBOOK[best_phase]["rationale"],
            playbook_sectors=list(CYCLE_PLAYBOOK[best_phase]["sectors"]),
            aligned_sectors=best_aligned,
            leading=leading,
            weakening=weakening,
            lagging=lagging,
            improving=improving,
        )

    def _expert_summary(self, assessment: RotationAssessment, sectors: list[SectorLine]) -> str:
        leaders = ", ".join(
            f"{s.sector} ({s.etf})" for s in sectors if s.quadrant == "Leading"
        ) or "none"
        laggards = ", ".join(
            f"{s.sector} ({s.etf})" for s in sectors if s.quadrant == "Lagging"
        ) or "none"
        return (
            f"Sector leadership best matches the {assessment.cycle_phase} playbook "
            f"(confidence {assessment.cycle_confidence:.2f}): {assessment.rationale} "
            f"Leading quadrant: {leaders}. Lagging quadrant: {laggards}."
        )

    def analyze(self) -> RotationReport:
        bench_closes = self._closes(BENCHMARK)
        if not bench_closes:
            raise RuntimeError("Unable to fetch SPY data for sector-rotation analysis")

        sectors: list[SectorLine] = []
        for etf, name in SECTOR_ETFS.items():
            line = self._sector_line(etf, name, bench_closes)
            if line:
                sectors.append(line)
        sectors.sort(key=lambda s: s.rs_ratio, reverse=True)

        assessment = self._cycle_assessment(sectors)

        breadth_score = round(
            len(assessment.leading) / len(sectors), 3
        ) if sectors else 0.0
        if sectors:
            spread = sectors[0].rs_ratio - sectors[-1].rs_ratio
            rotation_strength = round(max(0.0, min(1.0, spread / ROTATION_SPREAD_NORMALIZER)), 3)
        else:
            rotation_strength = 0.0

        summary = self._expert_summary(assessment, sectors)
        signals = self._market_signals(sectors, assessment)
        recs = self.append_memory_recommendations(self._recommendations(sectors, assessment))

        return RotationReport(
            benchmark=BENCHMARK,
            sectors=sectors,
            assessment=assessment,
            breadth_score=breadth_score,
            rotation_strength_score=rotation_strength,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source="Yahoo Finance API (RS line vs SPY, JdK RS-Ratio/Momentum proxy)",
        )

    @staticmethod
    def _deviation_confidence_base(
        sector: SectorLine,
        *,
        include_momentum: bool = True,
    ) -> float:
        """Baseline confidence from how far RS-Ratio/RS-Momentum sit from the 100 baseline."""
        ratio_dev = min(abs(sector.rs_ratio - 100.0) / CONFIDENCE_DEVIATION_SCALE, 1.0)
        base = CONFIDENCE_BASE + CONFIDENCE_RATIO_WEIGHT * ratio_dev
        if include_momentum:
            momentum_dev = min(abs(sector.rs_momentum - 100.0) / CONFIDENCE_DEVIATION_SCALE, 1.0)
            base += CONFIDENCE_MOMENTUM_WEIGHT * momentum_dev
        return base

    def _market_signals(
        self,
        sectors: list[SectorLine],
        assessment: RotationAssessment,
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal

        signals: list[dict[str, Any]] = []

        for sector in [s for s in sectors if s.quadrant == "Leading"][:3]:
            signals.append(
                build_market_signal(
                    sector=f"Leading — {sector.sector}",
                    tickers=[sector.etf],
                    bias="BULLISH",
                    reason=(
                        f"RS-Ratio {sector.rs_ratio:.1f} / RS-Momentum {sector.rs_momentum:.1f}, "
                        f"trend filter {sector.trend_filter}"
                    ),
                    confidence=self.adjust_signal_confidence(
                        sector.etf,
                        "BULLISH",
                        self._deviation_confidence_base(sector),
                    ),
                    evidence={
                        "rs_ratio": sector.rs_ratio,
                        "rs_momentum": sector.rs_momentum,
                        "quadrant": sector.quadrant,
                        "trend_filter": sector.trend_filter,
                    },
                )
            )

        for sector in [s for s in sectors if s.quadrant == "Lagging"][-3:]:
            signals.append(
                build_market_signal(
                    sector=f"Lagging — {sector.sector}",
                    tickers=[sector.etf],
                    bias="BEARISH",
                    reason=(
                        f"RS-Ratio {sector.rs_ratio:.1f} / RS-Momentum {sector.rs_momentum:.1f}, "
                        f"trend filter {sector.trend_filter}"
                    ),
                    confidence=self.adjust_signal_confidence(
                        sector.etf,
                        "BEARISH",
                        self._deviation_confidence_base(sector, include_momentum=False),
                    ),
                    evidence={
                        "rs_ratio": sector.rs_ratio,
                        "rs_momentum": sector.rs_momentum,
                        "quadrant": sector.quadrant,
                        "trend_filter": sector.trend_filter,
                    },
                )
            )

        for sector in [s for s in sectors if s.quadrant == "Improving"][:2]:
            signals.append(
                build_market_signal(
                    sector=f"Improving — {sector.sector}",
                    tickers=[sector.etf],
                    bias="NEUTRAL",
                    reason="RS-Momentum turning up while RS-Ratio still lags — early entry watchlist",
                    confidence=self.adjust_signal_confidence(sector.etf, "NEUTRAL", IMPROVING_SECTOR_BASE_CONFIDENCE),
                    evidence={"rs_ratio": sector.rs_ratio, "rs_momentum": sector.rs_momentum},
                )
            )

        if not signals:
            signals.append(
                build_market_signal(
                    sector="Sector Rotation",
                    tickers=[BENCHMARK],
                    bias="NEUTRAL",
                    reason="Insufficient relative-strength data for a directional read",
                    confidence=self.adjust_signal_confidence(BENCHMARK, "NEUTRAL", FALLBACK_NEUTRAL_CONFIDENCE),
                )
            )
        return signals

    @staticmethod
    def _recommendations(
        sectors: list[SectorLine],
        assessment: RotationAssessment,
    ) -> list[str]:
        recs = [
            f"Cycle read: {assessment.cycle_phase} ({assessment.cycle_confidence:.2f} confidence) — "
            f"{assessment.conditions}",
            assessment.rationale,
        ]
        leaders = [s for s in sectors if s.quadrant == "Leading"]
        if leaders:
            recs.append(
                "Leading quadrant (overweight): "
                + ", ".join(f"{s.sector} ({s.etf})" for s in leaders)
            )
        laggards = [s for s in sectors if s.quadrant == "Lagging"]
        if laggards:
            recs.append(
                "Lagging quadrant (underweight): "
                + ", ".join(f"{s.sector} ({s.etf})" for s in laggards)
            )
        improving = [s for s in sectors if s.quadrant == "Improving"]
        if improving:
            recs.append(
                "Improving quadrant (watchlist for early entries): "
                + ", ".join(f"{s.sector} ({s.etf})" for s in improving)
            )
        weakening = [s for s in sectors if s.quadrant == "Weakening"]
        if weakening:
            recs.append(
                "Weakening quadrant (hold, pause new buys): "
                + ", ".join(f"{s.sector} ({s.etf})" for s in weakening)
            )
        bearish_trend = [s for s in sectors if s.trend_filter == "bearish" and s.quadrant == "Leading"]
        if bearish_trend:
            recs.append(
                "Caution: still leading but below long-term RS moving average — "
                + ", ".join(s.etf for s in bearish_trend)
            )
        recs.append(
            "Verify via ratio chart: sector ETF / SPY should sit above its rising SMA "
            "before adding size; rebalance when the RS line breaks its long-term trendline."
        )
        return recs

    def to_dict(self, report: RotationReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Sector Rotation & Relative Strength Expert",
                "dashboard": DASHBOARD_URL,
                "benchmark": report.benchmark,
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
            },
            "assessment": {
                "cycle_phase": a.cycle_phase,
                "cycle_confidence": a.cycle_confidence,
                "conditions": a.conditions,
                "rationale": a.rationale,
                "playbook_sectors": a.playbook_sectors,
                "aligned_sectors": a.aligned_sectors,
                "leading": a.leading,
                "weakening": a.weakening,
                "lagging": a.lagging,
                "improving": a.improving,
            },
            "sectors": [
                {
                    "etf": s.etf,
                    "sector": s.sector,
                    "rs_value": s.rs_value,
                    "rs_ratio": s.rs_ratio,
                    "rs_momentum": s.rs_momentum,
                    "quadrant": s.quadrant,
                    "trend_filter": s.trend_filter,
                    "sma_window": s.sma_window,
                    "day_chg_pct": s.day_chg_pct,
                    "week_chg_pct": s.week_chg_pct,
                }
                for s in report.sectors
            ],
            "cycle_playbook": CYCLE_PLAYBOOK,
            "metrics": {
                "breadth_score": report.breadth_score,
                "rotation_strength_score": report.rotation_strength_score,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result


def run_sector_rotation_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return SectorRotationExpert(pipeline_context=pipeline_context).run(output=output)
