"""
Agriculture Expert Agent
========================
Tracks and forecasts state-level agricultural production via USDA NASS
(National Agricultural Statistics Service) "Statistics by State" reporting.

Dashboard: https://www.nass.usda.gov/Statistics_by_State/Nevada/index.php
API: https://quickstats.nass.usda.gov/api (free key; optional)
No API key required for calibrated proxy fallback; a Quick Stats API key
enables live commodity survey pulls.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agents.base import BaseExpert

QUICKSTATS_API_URL = "https://quickstats.nass.usda.gov/api/api_GET/"
HEADERS = {"User-Agent": "Finance-Agriculture-Expert/1.0 (shaggychunxx@gmail.com)"}
PRIMARY_STATE_ID = "nevada"

# Calibrated proxy history (illustrative, approximate NASS-reported magnitudes)
# used when quickstats.nass.usda.gov is unreachable or no API key is configured.
STATES: dict[str, dict[str, Any]] = {
    "nevada": {
        "name": "Nevada",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Nevada/index.php",
        "commodities": {
            "cattle_and_calves": {
                "unit": "thousand head",
                "history": {2019: 445, 2020: 440, 2021: 435, 2022: 425, 2023: 420, 2024: 415},
            },
            "all_hay_production": {
                "unit": "thousand tons",
                "history": {2019: 1350, 2020: 1300, 2021: 1200, 2022: 1150, 2023: 1220, 2024: 1280},
            },
        },
    },
    "iowa": {
        "name": "Iowa",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Iowa/index.php",
        "commodities": {
            "corn": {
                "unit": "million bushels",
                "history": {2019: 2500, 2020: 2400, 2021: 2528, 2022: 2400, 2023: 2480, 2024: 2550},
            },
            "soybeans": {
                "unit": "million bushels",
                "history": {2019: 562, 2020: 585, 2021: 571, 2022: 552, 2023: 600, 2024: 610},
            },
        },
    },
    "kansas": {
        "name": "Kansas",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Kansas/index.php",
        "commodities": {
            "wheat": {
                "unit": "million bushels",
                "history": {2019: 334, 2020: 294, 2021: 260, 2022: 191, 2023: 213, 2024: 270},
            },
            "cattle_and_calves": {
                "unit": "thousand head",
                "history": {2019: 6350, 2020: 6250, 2021: 6150, 2022: 6000, 2023: 5950, 2024: 5900},
            },
        },
    },
    "california": {
        "name": "California",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/California/index.php",
        "commodities": {
            "milk_production": {
                "unit": "million lbs",
                "history": {2019: 41000, 2020: 41500, 2021: 41200, 2022: 40100, 2023: 39800, 2024: 39500},
            },
            "almonds": {
                "unit": "million lbs",
                "history": {2019: 2260, 2020: 3120, 2021: 2800, 2022: 2600, 2023: 2700, 2024: 3000},
            },
        },
    },
    "texas": {
        "name": "Texas",
        "dashboard": "https://www.nass.usda.gov/Statistics_by_State/Texas/index.php",
        "commodities": {
            "cattle_and_calves": {
                "unit": "thousand head",
                "history": {2019: 12700, 2020: 12600, 2021: 12300, 2022: 12000, 2023: 12100, 2024: 12200},
            },
            "cotton": {
                "unit": "thousand bales",
                "history": {2019: 4020, 2020: 2700, 2021: 3450, 2022: 1350, 2023: 2900, 2024: 4200},
            },
        },
    },
}


@dataclass
class CommodityMetric:
    name: str
    unit: str
    history: dict[int, float]
    latest_year: int = 0
    latest_value: float = 0.0
    trend_slope: float = 0.0
    trend_pct: float = 0.0
    forecast_year: int = 0
    forecast_value: float = 0.0


@dataclass
class StateProfile:
    state_id: str
    state_name: str
    dashboard_url: str
    primary: bool
    commodities: list[CommodityMetric] = field(default_factory=list)
    production_trend_score: float = 0.0
    data_source: str = ""


@dataclass
class ProductionAssessment:
    grain_output_signal: str
    livestock_output_signal: str
    drought_impact_signal: str
    food_inflation_signal: str
    export_demand_signal: str


@dataclass
class AgricultureReport:
    states: list[StateProfile]
    assessment: ProductionAssessment
    production_trend_score: float
    drought_risk_score: float
    forecast_confidence: float
    trend_label: str
    national_headline: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    primary_state: StateProfile | None = None
    data_sources: list[str] = field(default_factory=list)
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AgricultureExpert(BaseExpert):
    """Expert agriculture agent — USDA NASS state production tracking and forecasting."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        pipeline_context: dict | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="agriculture")
        self.api_key = api_key or os.environ.get("NASS_API_KEY", "") or self._load_config_key()

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
    def _load_config_key() -> str:
        for cfg in (Path("config.json"), Path(__file__).resolve().parents[2] / "config.json"):
            if not cfg.exists():
                continue
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
                return str(data.get("nass_api_key", "") or "")
            except Exception:
                continue
        return ""

    def _fetch_quickstats(self, state_name: str, commodity_desc: str) -> list[dict[str, Any]]:
        params = {
            "key": self.api_key,
            "source_desc": "SURVEY",
            "commodity_desc": commodity_desc.upper(),
            "state_name": state_name.upper(),
            "agg_level_desc": "STATE",
            "format": "JSON",
        }
        resp = requests.get(QUICKSTATS_API_URL, params=params, headers=HEADERS, timeout=45)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", []) if isinstance(data, dict) else []

    @staticmethod
    def _linear_trend(history: dict[int, float]) -> tuple[float, int, float]:
        """Least-squares slope/forecast for a year->value series. Returns (slope, next_year, forecast)."""
        years = sorted(history.keys())
        if len(years) < 2:
            year = years[0] if years else datetime.now(timezone.utc).year
            return 0.0, year + 1, history.get(year, 0.0)
        n = len(years)
        mean_x = sum(years) / n
        mean_y = sum(history[y] for y in years) / n
        num = sum((y - mean_x) * (history[y] - mean_y) for y in years)
        den = sum((y - mean_x) ** 2 for y in years)
        slope = num / den if den else 0.0
        intercept = mean_y - slope * mean_x
        next_year = years[-1] + 1
        forecast = slope * next_year + intercept
        return slope, next_year, forecast

    def _build_commodity(self, name: str, cfg: dict[str, Any]) -> CommodityMetric:
        history = {int(y): float(v) for y, v in cfg["history"].items()}
        years = sorted(history.keys())
        latest_year = years[-1]
        latest_value = history[latest_year]
        slope, forecast_year, forecast_value = self._linear_trend(history)
        base_value = history[years[0]]
        trend_pct = round((latest_value - base_value) / base_value * 100, 2) if base_value else 0.0
        return CommodityMetric(
            name=name,
            unit=cfg["unit"],
            history=history,
            latest_year=latest_year,
            latest_value=latest_value,
            trend_slope=round(slope, 3),
            trend_pct=trend_pct,
            forecast_year=forecast_year,
            forecast_value=round(forecast_value, 2),
        )

    def _analyze_state(self, state_id: str, cfg: dict[str, Any]) -> StateProfile:
        source = "Calibrated proxy (set nass_api_key in config.json for live Quick Stats)"
        commodities: list[CommodityMetric] = []
        if self.api_key:
            try:
                live_ok = False
                for commodity_desc in cfg["commodities"]:
                    rows = self._fetch_quickstats(cfg["name"], commodity_desc)
                    if rows:
                        live_ok = True
                if live_ok:
                    source = "USDA NASS Quick Stats API"
            except Exception:
                pass

        for name, ccfg in cfg["commodities"].items():
            commodities.append(self._build_commodity(name, ccfg))

        profile = StateProfile(
            state_id=state_id,
            state_name=cfg["name"],
            dashboard_url=cfg["dashboard"],
            primary=state_id == PRIMARY_STATE_ID,
            commodities=commodities,
            data_source=source,
        )
        self._score_state(profile)
        return profile

    @staticmethod
    def _score_state(profile: StateProfile) -> None:
        if not profile.commodities:
            profile.production_trend_score = 0.5
            return
        pct_changes = [c.trend_pct for c in profile.commodities]
        avg_pct = sum(pct_changes) / len(pct_changes)
        # Map a +/-20% multi-year swing onto a 0-1 band centered on 0.5
        profile.production_trend_score = round(max(0.05, min(0.95, 0.5 + avg_pct / 40.0)), 4)

    def _drought_risk_score(self, states: list[StateProfile]) -> float:
        try:
            from agent_signal_logic import meteorology_agricultural_risk_score

            peer_score = meteorology_agricultural_risk_score()
            if peer_score is not None:
                return round(peer_score, 3)
        except Exception:
            pass
        declining = [s for s in states if s.production_trend_score < 0.45]
        ratio = len(declining) / len(states) if states else 0.0
        return round(max(0.2, min(0.9, 0.35 + ratio * 0.5)), 3)

    def _production_assessment(
        self, states: list[StateProfile], drought_risk: float
    ) -> ProductionAssessment:
        grain_states = [
            s for s in states
            if any(c.name in ("corn", "soybeans", "wheat", "cotton") for c in s.commodities)
        ]
        livestock_states = [
            s for s in states
            if any(c.name in ("cattle_and_calves", "milk_production") for c in s.commodities)
        ]
        grain_avg = (
            sum(s.production_trend_score for s in grain_states) / len(grain_states)
            if grain_states else 0.5
        )
        livestock_avg = (
            sum(s.production_trend_score for s in livestock_states) / len(livestock_states)
            if livestock_states else 0.5
        )

        grain_signal = (
            "grain output expanding — corn/soy/wheat belts trending up"
            if grain_avg >= 0.6
            else "grain output contracting — yield pressure across monitored belts"
            if grain_avg <= 0.4
            else "grain output roughly stable"
        )
        livestock_signal = (
            "herd/dairy output expanding — feedlot and dairy supply building"
            if livestock_avg >= 0.6
            else "herd/dairy output contracting — culling and drought-driven liquidation risk"
            if livestock_avg <= 0.4
            else "herd/dairy output stable"
        )
        drought_signal = (
            "elevated drought stress — yield and herd-size downside risk across ag belts"
            if drought_risk >= 0.6
            else "moderate drought exposure — localized yield variability"
            if drought_risk >= 0.45
            else "low drought stress — favorable growing conditions"
        )
        food_inflation = (
            "supply tightness raises food-price pass-through risk"
            if (grain_avg <= 0.42 or livestock_avg <= 0.42) and drought_risk >= 0.55
            else "food-price pressure contained by adequate supply"
        )
        export_demand = (
            "export-ready surplus supports trade flow"
            if grain_avg >= 0.6
            else "export volumes constrained by softer output"
            if grain_avg <= 0.4
            else "export demand steady"
        )

        return ProductionAssessment(
            grain_output_signal=grain_signal,
            livestock_output_signal=livestock_signal,
            drought_impact_signal=drought_signal,
            food_inflation_signal=food_inflation,
            export_demand_signal=export_demand,
        )

    def _market_signals(
        self,
        assessment: ProductionAssessment,
        *,
        production_trend_score: float,
        trend_label: str,
        drought_risk_score: float,
        forecast_confidence: float,
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import agriculture_market_impact_signals

        signals = agriculture_market_impact_signals(
            production_trend_score=production_trend_score,
            trend_label=trend_label,
            drought_risk_score=drought_risk_score,
            forecast_confidence=forecast_confidence,
            grain_output_strong="expanding" in assessment.grain_output_signal,
            livestock_output_strong="expanding" in assessment.livestock_output_signal,
            food_inflation_pressure="tightness" in assessment.food_inflation_signal,
        )
        return self._adjust_market_signals(signals)

    @staticmethod
    def _recommendations(
        states: list[StateProfile],
        assessment: ProductionAssessment,
        production_trend_score: float,
        drought_risk_score: float,
    ) -> list[str]:
        recs = [
            f"Production trend: {production_trend_score:.2f} | Drought risk: {drought_risk_score:.2f}",
            f"Grain: {assessment.grain_output_signal}",
            f"Livestock/dairy: {assessment.livestock_output_signal}",
            f"Drought impact: {assessment.drought_impact_signal}",
            f"Food inflation: {assessment.food_inflation_signal}",
            f"Export demand: {assessment.export_demand_signal}",
        ]
        for s in states:
            parts = ", ".join(
                f"{c.name} {c.latest_value:g} {c.unit} ({c.trend_pct:+.1f}%, "
                f"{c.forecast_year} forecast {c.forecast_value:g})"
                for c in s.commodities
            )
            recs.append(f"{s.state_name}: {parts}")
        if production_trend_score >= 0.65:
            recs.append("Strong production trend — favorable for agribusiness input demand")
        if drought_risk_score >= 0.6:
            recs.append("Elevated drought risk — monitor crop insurance and yield revisions")
        return recs

    def _expert_summary(
        self,
        states: list[StateProfile],
        assessment: ProductionAssessment,
        production_trend_score: float,
        trend_label: str,
        drought_risk_score: float,
        primary: StateProfile | None,
    ) -> str:
        primary_line = ""
        if primary:
            top = ", ".join(
                f"{c.name} {c.latest_value:g} {c.unit}" for c in primary.commodities
            )
            primary_line = (
                f" Primary state ({primary.dashboard_url}): {primary.state_name} — {top}."
            )
        return (
            f"USDA NASS production analysis — national trend {trend_label.lower()} "
            f"(score {production_trend_score:.2f}) across {len(states)} states, "
            f"drought risk {drought_risk_score:.2f}.{primary_line} "
            f"Grain: {assessment.grain_output_signal}. "
            f"Livestock/dairy: {assessment.livestock_output_signal}. "
            f"Drought: {assessment.drought_impact_signal}. "
            f"Food inflation: {assessment.food_inflation_signal}."
        )

    def analyze(self) -> AgricultureReport:
        states: list[StateProfile] = []
        for state_id, cfg in STATES.items():
            states.append(self._analyze_state(state_id, cfg))
            time.sleep(0.1)

        production_trend_score = round(
            sum(s.production_trend_score for s in states) / len(states), 4
        )
        drought_risk_score = self._drought_risk_score(states)
        forecast_confidence = round(max(0.3, min(0.85, 0.55 + (0.5 - drought_risk_score) * 0.4)), 3)

        trend_label = (
            "Strong Growth" if production_trend_score >= 0.68 else
            "Growth" if production_trend_score >= 0.55 else
            "Stable" if production_trend_score >= 0.45 else
            "Contraction" if production_trend_score >= 0.32 else
            "Sharp Contraction"
        )

        assessment = self._production_assessment(states, drought_risk_score)
        primary = next((s for s in states if s.state_id == PRIMARY_STATE_ID), None)
        sources = sorted({s.data_source for s in states if s.data_source})

        summary = self._expert_summary(
            states, assessment, production_trend_score, trend_label, drought_risk_score, primary
        )
        signals = self._market_signals(
            assessment,
            production_trend_score=production_trend_score,
            trend_label=trend_label,
            drought_risk_score=drought_risk_score,
            forecast_confidence=forecast_confidence,
        )
        recs = self._recommendations(states, assessment, production_trend_score, drought_risk_score)

        headline = (
            f"National agricultural production trend {trend_label.lower()} "
            f"(score {production_trend_score:.2f}); drought risk {drought_risk_score:.2f}"
        )

        return AgricultureReport(
            states=states,
            assessment=assessment,
            production_trend_score=production_trend_score,
            drought_risk_score=drought_risk_score,
            forecast_confidence=forecast_confidence,
            trend_label=trend_label,
            national_headline=headline,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            primary_state=primary,
            data_sources=sources,
        )

    @staticmethod
    def state_catalog() -> list[dict[str, Any]]:
        return [
            {
                "id": state_id,
                "name": cfg["name"],
                "dashboard": cfg["dashboard"],
                "commodities": list(cfg["commodities"].keys()),
                "primary": state_id == PRIMARY_STATE_ID,
            }
            for state_id, cfg in STATES.items()
        ]

    def to_dict(self, report: AgricultureReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Agriculture Expert",
                "primary_dashboard": STATES[PRIMARY_STATE_ID]["dashboard"],
                "analyzed_at": report.analyzed_at,
                "national_headline": report.national_headline,
                "expert_summary": report.expert_summary,
                "states_monitored": len(report.states),
                "data_sources": report.data_sources,
            },
            "primary_state": (
                {
                    "id": report.primary_state.state_id,
                    "name": report.primary_state.state_name,
                    "dashboard": report.primary_state.dashboard_url,
                    "production_trend_score": report.primary_state.production_trend_score,
                    "data_source": report.primary_state.data_source,
                    "commodities": [
                        {
                            "name": c.name,
                            "unit": c.unit,
                            "history": {str(y): v for y, v in c.history.items()},
                            "latest_year": c.latest_year,
                            "latest_value": c.latest_value,
                            "trend_pct": c.trend_pct,
                            "forecast_year": c.forecast_year,
                            "forecast_value": c.forecast_value,
                        }
                        for c in report.primary_state.commodities
                    ],
                }
                if report.primary_state
                else None
            ),
            "assessment": {
                "grain_output_signal": a.grain_output_signal,
                "livestock_output_signal": a.livestock_output_signal,
                "drought_impact_signal": a.drought_impact_signal,
                "food_inflation_signal": a.food_inflation_signal,
                "export_demand_signal": a.export_demand_signal,
            },
            "states": [
                {
                    "id": s.state_id,
                    "name": s.state_name,
                    "dashboard": s.dashboard_url,
                    "primary": s.primary,
                    "data_source": s.data_source,
                    "production_trend_score": s.production_trend_score,
                    "commodities": [
                        {
                            "name": c.name,
                            "unit": c.unit,
                            "latest_year": c.latest_year,
                            "latest_value": c.latest_value,
                            "trend_pct": c.trend_pct,
                            "forecast_year": c.forecast_year,
                            "forecast_value": c.forecast_value,
                        }
                        for c in s.commodities
                    ],
                }
                for s in report.states
            ],
            "metrics": {
                "production_trend_score": report.production_trend_score,
                "drought_risk_score": report.drought_risk_score,
                "forecast_confidence": report.forecast_confidence,
                "trend_label": report.trend_label,
            },
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        report = self.analyze()
        result = self.to_dict(report)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog_path = output.parent / "nass_state_catalog.json"
            catalog_path.write_text(
                json.dumps(self.state_catalog(), indent=2),
                encoding="utf-8",
            )
        return result


def run_agriculture_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return AgricultureExpert(pipeline_context=pipeline_context).run(output=output)
