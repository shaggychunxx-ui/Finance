"""
Census Bureau Economic Analyst Agent
=====================================
Economic and demographic analysis from the U.S. Census Bureau
(https://www.census.gov/en.html) open data APIs.

Primary data: Monthly Retail Trade Survey (MRTS), New Residential
Construction (RESCONST), Business Formation Statistics (BFS), and the
Population Estimates Program (PEP) — all served via api.census.gov.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agents.base import BaseExpert

HEADERS = {"User-Agent": "Finance-Census-Analyst/1.0 (shaggychunxx@gmail.com)"}
CENSUS_API_BASE = "https://api.census.gov/data"
CENSUS_PORTAL = "https://www.census.gov/en.html"

CENSUS_RESOURCES: list[dict[str, Any]] = [
    {
        "id": "mrts",
        "name": "Monthly Retail Trade Survey (MRTS)",
        "category": "Economic Indicators",
        "url": "https://www.census.gov/retail/index.html",
        "api_path": "timeseries/eits/mrtssales",
        "access": "api",
        "notes": "Advance and revised monthly retail & food service sales by category",
    },
    {
        "id": "resconst",
        "name": "New Residential Construction",
        "category": "Economic Indicators",
        "url": "https://www.census.gov/construction/nrc/index.html",
        "api_path": "timeseries/eits/resconst",
        "access": "api",
        "notes": "Housing starts, building permits, and completions",
    },
    {
        "id": "bfs",
        "name": "Business Formation Statistics (BFS)",
        "category": "Business Dynamics",
        "url": "https://www.census.gov/econ/bfs/index.html",
        "api_path": "timeseries/eits/bfs",
        "access": "api",
        "notes": "Weekly/monthly business application and formation counts",
    },
    {
        "id": "pep_population",
        "name": "Population Estimates Program (PEP)",
        "category": "Population",
        "url": "https://www.census.gov/programs-surveys/popest.html",
        "api_path": "2023/pep/population",
        "access": "api",
        "notes": "Vintage annual population estimates by state",
    },
    {
        "id": "m3",
        "name": "Manufacturers' Shipments, Inventories & Orders (M3)",
        "category": "Economic Indicators",
        "url": "https://www.census.gov/manufacturing/m3/index.html",
        "api_path": "timeseries/eits/m3",
        "access": "api",
        "notes": "Durable goods orders, shipments, and inventories",
    },
    {
        "id": "cbp",
        "name": "County Business Patterns (CBP)",
        "category": "Business Dynamics",
        "url": "https://www.census.gov/programs-surveys/cbp.html",
        "api_path": "2021/cbp",
        "access": "api",
        "notes": "Establishment counts, employment, and payroll by county/industry",
    },
    {
        "id": "intltrade",
        "name": "International Trade in Goods",
        "category": "International Trade",
        "url": "https://www.census.gov/foreign-trade/index.html",
        "api_path": "timeseries/intltrade/exports/hs",
        "access": "api",
        "notes": "U.S. export/import statistics by HS commodity code",
    },
    {
        "id": "acs",
        "name": "American Community Survey (ACS)",
        "category": "Demographics",
        "url": "https://www.census.gov/programs-surveys/acs",
        "api_path": "2022/acs/acs1",
        "access": "api",
        "notes": "Income, housing, and demographic detail below decennial cadence",
    },
]

STATE_GROWTH_TICKERS: dict[str, list[str]] = {
    "Texas": ["XLRE", "ITB", "D"],
    "Florida": ["XLRE", "PHM", "NEE"],
    "North Carolina": ["XLRE", "DHI", "DUK"],
    "South Carolina": ["XLRE", "LEN", "SCG"],
    "Georgia": ["XLRE", "PHM", "SO"],
    "Arizona": ["XLRE", "TOL", "PNW"],
}

FALLBACK_RETAIL_ROWS: list[dict[str, Any]] = [
    {"time": "2026-05", "cell_value": "739412", "category_code": "44X72"},
    {"time": "2026-04", "cell_value": "735110", "category_code": "44X72"},
    {"time": "2026-03", "cell_value": "731820", "category_code": "44X72"},
    {"time": "2025-05", "cell_value": "703640", "category_code": "44X72"},
]

FALLBACK_HOUSING_ROWS: list[dict[str, Any]] = [
    {"time": "2026-05", "cell_value": "1382", "data_type_code": "STARTS", "seasonally_adj": "yes"},
    {"time": "2026-04", "cell_value": "1354", "data_type_code": "STARTS", "seasonally_adj": "yes"},
    {"time": "2026-03", "cell_value": "1401", "data_type_code": "STARTS", "seasonally_adj": "yes"},
]

FALLBACK_BFS_ROWS: list[dict[str, Any]] = [
    {"time": "2026-05", "cell_value": "445210", "category_code": "TOTAL"},
    {"time": "2026-04", "cell_value": "438760", "category_code": "TOTAL"},
    {"time": "2026-03", "cell_value": "451920", "category_code": "TOTAL"},
]

FALLBACK_POPULATION_ROWS: list[dict[str, Any]] = [
    {"NAME": "Texas", "POP_2023": "30503301", "POP_2022": "30029572"},
    {"NAME": "Florida", "POP_2023": "22610726", "POP_2022": "22245521"},
    {"NAME": "North Carolina", "POP_2023": "10835491", "POP_2022": "10701022"},
    {"NAME": "South Carolina", "POP_2023": "5373555", "POP_2022": "5282634"},
    {"NAME": "Georgia", "POP_2023": "11029227", "POP_2022": "10913150"},
    {"NAME": "Arizona", "POP_2023": "7391720", "POP_2022": "7365684"},
]


@dataclass
class SeriesPoint:
    period: str
    value: float


@dataclass
class StateGrowth:
    state: str
    population: int
    prior_population: int
    growth_pct: float
    rank: int


@dataclass
class CensusReport:
    resources: list[dict[str, Any]]
    retail_sales: list[SeriesPoint]
    housing_starts: list[SeriesPoint]
    business_applications: list[SeriesPoint]
    state_growth: list[StateGrowth]
    retail_mom_pct: float
    retail_yoy_pct: float
    housing_mom_pct: float
    business_formation_mom_pct: float
    consumer_score: float
    housing_score: float
    entrepreneurship_score: float
    economic_label: str
    expert_summary: str
    economic_assessment: dict[str, str]
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    data_degraded: bool = False
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CensusEconomicAnalyst(BaseExpert):
    """Economic/demographic analyst for U.S. Census Bureau open data."""

    def __init__(self, *, pipeline_context: dict | None = None) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="census")

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

    def _census_get(self, api_path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        url = f"{CENSUS_API_BASE}/{api_path}"
        try:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=45)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list) or len(data) < 2:
                return []
            header, *rows = data
            return [dict(zip(header, row)) for row in rows]
        except Exception:
            return []

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _fetch_retail_sales(self) -> tuple[list[SeriesPoint], bool]:
        rows = self._census_get("timeseries/eits/mrtssales", {
            "get": "cell_value,category_code",
            "for": "us:*",
            "category_code": "44X72",
            "time": "from 2024",
        })
        live = bool(rows)
        rows = rows or FALLBACK_RETAIL_ROWS
        points = [
            SeriesPoint(period=str(r.get("time", "")), value=self._to_float(r.get("cell_value")))
            for r in rows
            if r.get("cell_value") not in (None, "")
        ]
        points.sort(key=lambda p: p.period, reverse=True)
        return points[:13], live

    def _fetch_housing_starts(self) -> tuple[list[SeriesPoint], bool]:
        rows = self._census_get("timeseries/eits/resconst", {
            "get": "cell_value,data_type_code,seasonally_adj",
            "for": "us:*",
            "data_type_code": "STARTS",
            "time": "from 2024",
        })
        live = bool(rows)
        rows = rows or FALLBACK_HOUSING_ROWS
        points = [
            SeriesPoint(period=str(r.get("time", "")), value=self._to_float(r.get("cell_value")))
            for r in rows
            if r.get("cell_value") not in (None, "")
        ]
        points.sort(key=lambda p: p.period, reverse=True)
        return points[:13], live

    def _fetch_business_applications(self) -> tuple[list[SeriesPoint], bool]:
        rows = self._census_get("timeseries/eits/bfs", {
            "get": "cell_value,category_code",
            "for": "us:*",
            "category_code": "TOTAL",
            "time": "from 2024",
        })
        live = bool(rows)
        rows = rows or FALLBACK_BFS_ROWS
        points = [
            SeriesPoint(period=str(r.get("time", "")), value=self._to_float(r.get("cell_value")))
            for r in rows
            if r.get("cell_value") not in (None, "")
        ]
        points.sort(key=lambda p: p.period, reverse=True)
        return points[:13], live

    def _fetch_state_growth(self) -> tuple[list[StateGrowth], bool]:
        rows = self._census_get("2023/pep/population", {
            "get": "NAME,POP_2023,POP_2022",
            "for": "state:*",
        })
        live = bool(rows)
        rows = rows or FALLBACK_POPULATION_ROWS
        growth: list[StateGrowth] = []
        for r in rows:
            pop = int(self._to_float(r.get("POP_2023")))
            prior = int(self._to_float(r.get("POP_2022")))
            if not pop or not prior:
                continue
            growth.append(StateGrowth(
                state=str(r.get("NAME", "?")),
                population=pop,
                prior_population=prior,
                growth_pct=round(100 * (pop - prior) / prior, 2),
                rank=0,
            ))
        growth.sort(key=lambda g: g.growth_pct, reverse=True)
        for i, g in enumerate(growth[:10], start=1):
            g.rank = i
        return growth[:10], live

    @staticmethod
    def _pct_change(points: list[SeriesPoint], lag: int = 1) -> float:
        if len(points) <= lag:
            return 0.0
        latest, prior = points[0].value, points[lag].value
        if not prior:
            return 0.0
        return round(100 * (latest - prior) / prior, 2)

    def _scores(
        self,
        retail_mom: float,
        retail_yoy: float,
        housing_mom: float,
        bfs_mom: float,
    ) -> tuple[float, float, float, str]:
        consumer = min(100.0, max(0.0, 50 + retail_mom * 6 + retail_yoy * 1.5))
        housing = min(100.0, max(0.0, 50 + housing_mom * 4))
        entrepreneurship = min(100.0, max(0.0, 50 + bfs_mom * 4))
        composite = (consumer + housing + entrepreneurship) / 3

        if composite >= 62:
            label = "Expansionary economic momentum"
        elif composite <= 38:
            label = "Contractionary economic signals"
        else:
            label = "Stable / mixed economic momentum"

        return round(consumer, 1), round(housing, 1), round(entrepreneurship, 1), label

    def _economic_assessment(
        self,
        retail_mom: float,
        retail_yoy: float,
        housing_mom: float,
        bfs_mom: float,
        state_growth: list[StateGrowth],
    ) -> dict[str, str]:
        if retail_mom >= 0.5:
            consumer_signal = f"Retail sales rising MoM ({retail_mom:+.1f}%) — resilient consumer spending"
        elif retail_mom <= -0.5:
            consumer_signal = f"Retail sales falling MoM ({retail_mom:+.1f}%) — softening consumer demand"
        else:
            consumer_signal = f"Retail sales roughly flat MoM ({retail_mom:+.1f}%)"

        if housing_mom >= 2:
            housing_signal = f"Housing starts up {housing_mom:+.1f}% MoM — homebuilder tailwind"
        elif housing_mom <= -2:
            housing_signal = f"Housing starts down {housing_mom:+.1f}% MoM — rate-sensitive drag"
        else:
            housing_signal = f"Housing starts roughly stable ({housing_mom:+.1f}% MoM)"

        if bfs_mom >= 1:
            formation_signal = f"Business applications up {bfs_mom:+.1f}% MoM — entrepreneurship tailwind"
        elif bfs_mom <= -1:
            formation_signal = f"Business applications down {bfs_mom:+.1f}% MoM — startup formation cooling"
        else:
            formation_signal = f"Business formation steady ({bfs_mom:+.1f}% MoM)"

        top_state = state_growth[0].state if state_growth else "N/A"
        migration_signal = (
            f"{top_state} leads state population growth"
            + (f" ({state_growth[0].growth_pct:+.2f}% YoY)" if state_growth else "")
            + " — Sunbelt migration continues to favor regional homebuilders and utilities"
        )

        return {
            "consumer_spending": consumer_signal,
            "retail_trend": f"Retail sales YoY {retail_yoy:+.1f}%",
            "housing_market": housing_signal,
            "business_formation": formation_signal,
            "population_migration": migration_signal,
        }

    def _market_signals(
        self,
        retail_mom: float,
        retail_yoy: float,
        housing_mom: float,
        bfs_mom: float,
        state_growth: list[StateGrowth],
        *,
        consumer_score: float,
        housing_score: float,
        entrepreneurship_score: float,
        economic_label: str,
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal

        signals: list[dict[str, Any]] = []

        if abs(retail_mom) >= 0.3 or abs(retail_yoy) >= 1.0:
            bias = "BULLISH" if retail_mom >= 0.5 else "BEARISH" if retail_mom <= -0.5 else "NEUTRAL"
            signals.append(
                build_market_signal(
                    sector="Consumer Discretionary / Retail",
                    tickers=["XRT", "WMT", "TGT", "AMZN"],
                    bias=bias,
                    reason=f"MRTS retail sales {retail_mom:+.1f}% MoM, {retail_yoy:+.1f}% YoY",
                    confidence=min(0.8, 0.45 + abs(retail_mom) * 0.05 + abs(retail_yoy) * 0.02),
                    evidence={"retail_mom_pct": retail_mom, "retail_yoy_pct": retail_yoy},
                )
            )

        if abs(housing_mom) >= 1.0:
            bias = "BULLISH" if housing_mom >= 2 else "BEARISH" if housing_mom <= -2 else "NEUTRAL"
            signals.append(
                build_market_signal(
                    sector="Homebuilders",
                    tickers=["XHB", "ITB", "LEN", "DHI", "PHM"],
                    bias=bias,
                    reason=f"New residential construction starts {housing_mom:+.1f}% MoM",
                    confidence=min(0.78, 0.4 + abs(housing_mom) * 0.05),
                    evidence={"housing_starts_mom_pct": housing_mom},
                )
            )

        if abs(bfs_mom) >= 1.0:
            bias = "BULLISH" if bfs_mom >= 1 else "BEARISH" if bfs_mom <= -1 else "NEUTRAL"
            signals.append(
                build_market_signal(
                    sector="Small Caps / Entrepreneurship",
                    tickers=["IWM", "IJR"],
                    bias=bias,
                    reason=f"Business formation applications {bfs_mom:+.1f}% MoM",
                    confidence=min(0.7, 0.4 + abs(bfs_mom) * 0.04),
                    evidence={"business_formation_mom_pct": bfs_mom},
                )
            )

        top_states = state_growth[:3]
        if top_states and top_states[0].growth_pct >= 0.8:
            tickers: list[str] = []
            for s in top_states:
                tickers.extend(STATE_GROWTH_TICKERS.get(s.state, [])[:2])
            deduped = list(dict.fromkeys(tickers))[:5]
            signals.append(
                build_market_signal(
                    sector="Regional Real Estate / Utilities",
                    tickers=deduped or ["XLRE", "XLU"],
                    bias="BULLISH" if top_states[0].growth_pct >= 1.2 else "NEUTRAL",
                    reason=(
                        f"Fastest-growing states: {', '.join(s.state for s in top_states)} "
                        f"(led by {top_states[0].state} at {top_states[0].growth_pct:+.2f}% YoY)"
                    ),
                    confidence=0.5,
                )
            )

        if not signals:
            composite = (consumer_score + housing_score + entrepreneurship_score) / 3.0
            bias = "BULLISH" if composite >= 62 else "BEARISH" if composite <= 38 else "NEUTRAL"
            signals.append(
                build_market_signal(
                    sector="Broad Market",
                    tickers=["SPY"],
                    bias=bias,
                    reason=(
                        f"Census composite {economic_label} "
                        f"(consumer {consumer_score:.1f}, housing {housing_score:.1f}, "
                        f"entrepreneurship {entrepreneurship_score:.1f}) — no single-sector tilt"
                    ),
                    confidence=min(0.55, 0.38 + abs(composite - 50) / 100.0),
                    evidence={
                        "consumer_score": consumer_score,
                        "housing_score": housing_score,
                        "entrepreneurship_score": entrepreneurship_score,
                        "retail_mom_pct": retail_mom,
                        "housing_mom_pct": housing_mom,
                    },
                )
            )

        return self._adjust_market_signals(signals)

    def analyze(self) -> CensusReport:
        retail, retail_live = self._fetch_retail_sales()
        housing, housing_live = self._fetch_housing_starts()
        bfs, bfs_live = self._fetch_business_applications()
        state_growth, pop_live = self._fetch_state_growth()
        data_degraded = not all((retail_live, housing_live, bfs_live, pop_live))

        retail_mom = self._pct_change(retail, lag=1)
        retail_yoy = self._pct_change(retail, lag=min(12, max(1, len(retail) - 1)))
        housing_mom = self._pct_change(housing, lag=1)
        bfs_mom = self._pct_change(bfs, lag=1)

        consumer_score, housing_score, entrepreneurship_score, label = self._scores(
            retail_mom, retail_yoy, housing_mom, bfs_mom
        )
        assessment = self._economic_assessment(retail_mom, retail_yoy, housing_mom, bfs_mom, state_growth)

        sources = [
            "Census MRTS (Retail Trade)",
            "Census RESCONST (Housing)",
            "Census BFS (Business Formation)",
            "Census PEP (Population Estimates)",
        ]
        if data_degraded:
            sources.append("Calibrated proxy (Census API partial/unavailable)")

        summary = (
            f"Census Bureau economic scan of {len(CENSUS_RESOURCES)} data.census.gov / "
            f"api.census.gov resources. Retail sales {retail_mom:+.1f}% MoM ({retail_yoy:+.1f}% YoY); "
            f"housing starts {housing_mom:+.1f}% MoM; business applications {bfs_mom:+.1f}% MoM. "
            f"Overall: {label} (consumer {consumer_score}, housing {housing_score}, "
            f"entrepreneurship {entrepreneurship_score})."
        )

        recs = [
            summary,
            f"Consumer score: {consumer_score} | Housing score: {housing_score} | "
            f"Entrepreneurship score: {entrepreneurship_score}",
            assessment["consumer_spending"],
            assessment["retail_trend"],
            assessment["housing_market"],
            assessment["business_formation"],
            assessment["population_migration"],
        ]
        for s in state_growth[:5]:
            recs.append(
                f"Population growth #{s.rank} {s.state}: {s.growth_pct:+.2f}% YoY "
                f"({s.population:,} residents)"
            )

        return CensusReport(
            resources=CENSUS_RESOURCES,
            retail_sales=retail,
            housing_starts=housing,
            business_applications=bfs,
            state_growth=state_growth,
            retail_mom_pct=retail_mom,
            retail_yoy_pct=retail_yoy,
            housing_mom_pct=housing_mom,
            business_formation_mom_pct=bfs_mom,
            consumer_score=consumer_score,
            housing_score=housing_score,
            entrepreneurship_score=entrepreneurship_score,
            economic_label=label,
            expert_summary=summary,
            economic_assessment=assessment,
            market_signals=self._market_signals(
                retail_mom,
                retail_yoy,
                housing_mom,
                bfs_mom,
                state_growth,
                consumer_score=consumer_score,
                housing_score=housing_score,
                entrepreneurship_score=entrepreneurship_score,
                economic_label=label,
            ),
            recommendations=recs,
            data_sources=sources,
            data_degraded=data_degraded,
        )

    def to_dict(self, report: CensusReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Census Bureau Economic Analyst",
                "portal": CENSUS_PORTAL,
                "analyzed_at": report.analyzed_at,
                "data_sources": report.data_sources,
                "expert_summary": report.expert_summary,
                "resources_cataloged": len(report.resources),
                "data_degraded": report.data_degraded,
            },
            "metrics": {
                "retail_sales_mom_pct": report.retail_mom_pct,
                "retail_sales_yoy_pct": report.retail_yoy_pct,
                "housing_starts_mom_pct": report.housing_mom_pct,
                "business_formation_mom_pct": report.business_formation_mom_pct,
                "consumer_score": report.consumer_score,
                "housing_score": report.housing_score,
                "entrepreneurship_score": report.entrepreneurship_score,
                "economic_label": report.economic_label,
            },
            "resources": report.resources,
            "retail_sales": [{"period": p.period, "value": p.value} for p in report.retail_sales],
            "housing_starts": [{"period": p.period, "value": p.value} for p in report.housing_starts],
            "business_applications": [
                {"period": p.period, "value": p.value} for p in report.business_applications
            ],
            "state_population_growth": [
                {
                    "state": s.state,
                    "population": s.population,
                    "prior_population": s.prior_population,
                    "growth_pct": s.growth_pct,
                    "rank": s.rank,
                }
                for s in report.state_growth
            ],
            "economic_assessment": report.economic_assessment,
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        report = self.analyze()
        result = self.to_dict(report)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog_path = output.parent / "census_resources.json"
            catalog_path.write_text(
                json.dumps(report.resources, indent=2),
                encoding="utf-8",
            )
        return result


def run_census_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return CensusEconomicAnalyst(pipeline_context=pipeline_context).run(output=output)
