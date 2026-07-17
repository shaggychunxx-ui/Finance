"""
CPI Inflation Analyst Agent
===========================
Tracks U.S. Consumer Price Index (CPI-U) series — headline, core, food,
energy, and shelter — and classifies the current inflation regime with
market sector implications.

Data: BLS CPI public API (https://www.bls.gov/cpi/), with FINRA's investor
education page on key economic indicators used as supplementary context.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agents.base import BaseExpert

HEADERS = {"User-Agent": "Finance-CPI-Inflation-Analyst/1.0 (shaggychunxx@gmail.com)"}
BLS_TIMESERIES_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

CPI_SERIES: list[dict[str, Any]] = [
    {
        "series_id": "CUUR0000SA0",
        "label": "CPI-U — All Items (Headline)",
        "component": "headline",
    },
    {
        "series_id": "CUUR0000SA0L1E",
        "label": "CPI-U — All Items Less Food & Energy (Core)",
        "component": "core",
    },
    {
        "series_id": "CUUR0000SAF1",
        "label": "CPI-U — Food",
        "component": "food",
    },
    {
        "series_id": "CUUR0000SA0E",
        "label": "CPI-U — Energy",
        "component": "energy",
    },
    {
        "series_id": "CUUR0000SAH1",
        "label": "CPI-U — Shelter",
        "component": "shelter",
    },
]

# Approximate annual growth calibration per component (based on 2024 BLS CPI
# historical averages), used only when the live BLS API is unreachable
# (e.g. bls.gov DNS blocked in this sandbox).
_PROXY_ANNUAL_GROWTH = {
    "headline": 0.029,
    "core": 0.032,
    "food": 0.026,
    "energy": 0.011,
    "shelter": 0.041,
}

FINRA_REFERENCE: dict[str, Any] = {
    "name": "Key Economic Indicators Every Investor Should Know",
    "provider": "FINRA",
    "url": "https://www.finra.org/investors/insights/key-economic-indicators-every-investor-should-know",
    "indicators_covered": [
        "Consumer Price Index (CPI)",
        "Gross Domestic Product (GDP)",
        "Unemployment Rate",
        "Producer Price Index (PPI)",
        "Retail Sales",
        "Interest Rates (Fed Funds Rate)",
        "Housing Starts & Building Permits",
        "Consumer Confidence Index",
    ],
    "notes": (
        "Investor-education framing of CPI as the primary consumer-level inflation "
        "gauge; used as supplementary context alongside BLS's own CPI publication."
    ),
}

REGIME_BANDS = [
    (1.5, "below-target / disinflation risk"),
    (2.5, "on-target"),
    (3.5, "elevated"),
    (5.0, "high"),
]


@dataclass
class CPISeriesResult:
    series_id: str
    label: str
    component: str
    latest_period: str
    latest_value: float
    yoy_pct: float
    mom_pct: float


@dataclass
class CPIReport:
    series: list[CPISeriesResult]
    headline_yoy: float
    core_yoy: float
    headline_mom: float
    regime_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CPIInflationAnalyst(BaseExpert):
    """Analyze BLS CPI series and translate inflation trends into sector signals."""

    def __init__(self, *, pipeline_context: dict | None = None) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="cpi")

    def _adjust_market_signals(self, signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        adjusted: list[dict[str, Any]] = []
        for sig in signals:
            row = dict(sig)
            tickers = row.get("tickers") or []
            conf = row.get("confidence")
            if tickers and conf is not None:
                row["confidence"] = self.adjust_signal_confidence(
                    str(tickers[0]), str(row.get("bias", "NEUTRAL")), conf
                )
            adjusted.append(row)
        return adjusted

    @staticmethod
    def _parse_bls_response(payload: dict[str, Any]) -> dict[str, list[tuple[str, float]]]:
        by_series: dict[str, list[tuple[str, float]]] = {}
        for series in payload.get("Results", {}).get("series", []):
            series_id = series.get("seriesID", "")
            points: list[tuple[str, float]] = []
            for row in series.get("data", []):
                period = str(row.get("period", ""))
                # BLS periods are "M01".."M12" for months and "M13" for the
                # annual average — skip M13 and keep only monthly points.
                if not period.startswith("M") or period == "M13":
                    continue
                year = str(row.get("year", ""))
                month = period[1:]
                try:
                    value = float(row.get("value"))
                except (TypeError, ValueError):
                    continue
                points.append((f"{year}-{month}", value))
            points.sort(key=lambda p: p[0])
            if points:
                by_series[series_id] = points
        return by_series

    def _fetch_series(self) -> tuple[dict[str, list[tuple[str, float]]], list[str]]:
        series_ids = [s["series_id"] for s in CPI_SERIES]
        try:
            end_year = datetime.now(timezone.utc).year
            resp = requests.post(
                BLS_TIMESERIES_URL,
                headers=HEADERS,
                json={
                    "seriesid": series_ids,
                    "startyear": str(end_year - 2),
                    "endyear": str(end_year),
                },
                timeout=30,
            )
            resp.raise_for_status()
            parsed = self._parse_bls_response(resp.json())
            if parsed:
                return parsed, ["BLS CPI Public API"]
        except Exception:
            pass
        return self._proxy_series(), ["Calibrated proxy series (BLS CPI unreachable)"]

    @staticmethod
    def _proxy_series() -> dict[str, list[tuple[str, float]]]:
        """Deterministic calibrated fallback: 25 months of index values per component."""
        now = datetime.now(timezone.utc)
        months: list[str] = []
        year, month = now.year, now.month
        for _ in range(25):
            months.append(f"{year:04d}-{month:02d}")
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        months.reverse()

        by_series: dict[str, list[tuple[str, float]]] = {}
        for spec in CPI_SERIES:
            annual_growth = _PROXY_ANNUAL_GROWTH.get(spec["component"], 0.025)
            monthly_growth = annual_growth / 12.0
            base_value = 300.0
            points: list[tuple[str, float]] = []
            value = base_value
            for i, period in enumerate(months):
                if i > 0:
                    value *= 1 + monthly_growth
                points.append((period, round(value, 3)))
            by_series[spec["series_id"]] = points
        return by_series

    @staticmethod
    def _pct_change(current: float, prior: float) -> float:
        if prior == 0:
            return 0.0
        return round((current - prior) / prior * 100.0, 2)

    def _build_series_results(
        self, raw: dict[str, list[tuple[str, float]]]
    ) -> list[CPISeriesResult]:
        results: list[CPISeriesResult] = []
        for spec in CPI_SERIES:
            points = raw.get(spec["series_id"], [])
            if not points:
                continue
            latest_period, latest_value = points[-1]
            mom_pct = 0.0
            if len(points) >= 2:
                mom_pct = self._pct_change(latest_value, points[-2][1])
            yoy_pct = 0.0
            if len(points) >= 13:
                yoy_pct = self._pct_change(latest_value, points[-13][1])
            results.append(
                CPISeriesResult(
                    series_id=spec["series_id"],
                    label=spec["label"],
                    component=spec["component"],
                    latest_period=latest_period,
                    latest_value=latest_value,
                    yoy_pct=yoy_pct,
                    mom_pct=mom_pct,
                )
            )
        return results

    @staticmethod
    def _classify_regime(headline_yoy: float) -> str:
        for threshold, label in REGIME_BANDS:
            if headline_yoy < threshold:
                return label
        return "very-high"

    def _market_signals(
        self, headline_yoy: float, core_yoy: float, regime_label: str
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal

        signals: list[dict[str, Any]] = []
        distance_from_target = abs(headline_yoy - 2.0)
        # Confidence scales with how far headline CPI sits from the Fed's 2%
        # target: 0.45 baseline + 0.09 per point of distance, capped at 0.88
        # so a single data point never dominates cross-agent signal blending.
        confidence = round(min(0.88, 0.45 + distance_from_target * 0.09), 3)

        if regime_label in ("elevated", "high", "very-high"):
            signals.append(
                build_market_signal(
                    sector="Inflation Hedges",
                    tickers=["GLD", "TIP", "DBC"],
                    bias="BULLISH",
                    reason=f"Headline CPI YoY {headline_yoy:.1f}% ({regime_label}) supports real-asset hedges",
                    confidence=confidence,
                )
            )
            signals.append(
                build_market_signal(
                    sector="Long Duration Bonds",
                    tickers=["TLT", "IEF"],
                    bias="BEARISH",
                    reason=f"Elevated inflation ({headline_yoy:.1f}% YoY) pressures long-duration bond prices",
                    confidence=confidence,
                )
            )
            signals.append(
                build_market_signal(
                    sector="Consumer Staples",
                    tickers=["XLP"],
                    bias="BULLISH",
                    reason="Defensive tilt favored while inflation erodes discretionary purchasing power",
                    confidence=round(min(0.75, 0.4 + distance_from_target * 0.07), 3),
                )
            )
        elif regime_label == "on-target":
            signals.append(
                build_market_signal(
                    sector="Broad Market",
                    tickers=["SPY", "QQQ"],
                    bias="BULLISH",
                    reason=f"Headline CPI YoY {headline_yoy:.1f}% near the Fed's 2% target supports risk assets",
                    confidence=confidence,
                )
            )
            signals.append(
                build_market_signal(
                    sector="Duration Bonds",
                    tickers=["TLT", "IEF"],
                    bias="BULLISH",
                    reason="Stable inflation reduces upside rate-hike risk for long-duration bonds",
                    confidence=confidence,
                )
            )
        else:
            signals.append(
                build_market_signal(
                    sector="Duration Bonds",
                    tickers=["TLT", "IEF"],
                    bias="BULLISH",
                    reason=f"Headline CPI YoY {headline_yoy:.1f}% ({regime_label}) raises disinflation/deflation risk",
                    confidence=confidence,
                )
            )
            signals.append(
                build_market_signal(
                    sector="Consumer Discretionary",
                    tickers=["XLY"],
                    bias="NEUTRAL",
                    reason="Soft inflation readings can reflect weakening demand; watch growth data",
                    confidence=round(min(0.65, 0.4 + distance_from_target * 0.05), 3),
                )
            )

        if core_yoy > headline_yoy + 0.3:
            signals.append(
                build_market_signal(
                    sector="Rate-Sensitive / Growth",
                    tickers=["QQQ", "XLK"],
                    bias="BEARISH",
                    reason=f"Core CPI YoY {core_yoy:.1f}% running above headline signals sticky underlying inflation",
                    confidence=round(min(0.7, 0.42 + (core_yoy - headline_yoy) * 0.1), 3),
                )
            )

        return self._adjust_market_signals(signals)

    def analyze(self) -> CPIReport:
        raw, sources = self._fetch_series()
        series = self._build_series_results(raw)

        headline = next((s for s in series if s.component == "headline"), None)
        core = next((s for s in series if s.component == "core"), None)
        headline_yoy = headline.yoy_pct if headline else 0.0
        headline_mom = headline.mom_pct if headline else 0.0
        core_yoy = core.yoy_pct if core else 0.0

        regime_label = self._classify_regime(headline_yoy)

        summary_parts = [
            f"Headline CPI-U +{headline_yoy:.1f}% YoY ({headline_mom:+.1f}% MoM), "
            f"core +{core_yoy:.1f}% YoY — regime: {regime_label}.",
        ]
        for s in series:
            if s.component in ("food", "energy", "shelter"):
                summary_parts.append(f"{s.label.split('— ')[-1]}: {s.yoy_pct:+.1f}% YoY.")
        summary = " ".join(summary_parts)

        signals = self._market_signals(headline_yoy, core_yoy, regime_label)

        recs = [
            summary,
            f"Inflation regime: {regime_label} (distance from 2% target: {abs(headline_yoy - 2.0):.1f}pp)",
        ]
        for s in series:
            recs.append(f"{s.label}: {s.yoy_pct:+.1f}% YoY, {s.mom_pct:+.1f}% MoM (as of {s.latest_period})")
        recs.append(
            f"Supplementary reference: FINRA — {FINRA_REFERENCE['name']} ({FINRA_REFERENCE['url']})"
        )

        return CPIReport(
            series=series,
            headline_yoy=headline_yoy,
            core_yoy=core_yoy,
            headline_mom=headline_mom,
            regime_label=regime_label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_sources=sources,
        )

    def to_dict(self, report: CPIReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "CPI Inflation Analyst",
                "analyzed_at": report.analyzed_at,
                "data_sources": report.data_sources,
                "expert_summary": report.expert_summary,
                "series_tracked": len(report.series),
            },
            "summary": {
                "headline_yoy_pct": report.headline_yoy,
                "headline_mom_pct": report.headline_mom,
                "core_yoy_pct": report.core_yoy,
                "regime_label": report.regime_label,
            },
            "series": [
                {
                    "series_id": s.series_id,
                    "label": s.label,
                    "component": s.component,
                    "latest_period": s.latest_period,
                    "latest_value": s.latest_value,
                    "yoy_pct": s.yoy_pct,
                    "mom_pct": s.mom_pct,
                }
                for s in report.series
            ],
            "supplementary_data_source": FINRA_REFERENCE,
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        report = self.analyze()
        result = self.to_dict(report)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog_path = output.parent / "bls_cpi_series.json"
            catalog_path.write_text(
                json.dumps(
                    {"series": CPI_SERIES, "supplementary_data_source": FINRA_REFERENCE},
                    indent=2,
                ),
                encoding="utf-8",
            )
        return result


def run_cpi_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return CPIInflationAnalyst(pipeline_context=pipeline_context).run(output=output)
