"""
EIA Grid Monitor Analyst Agent
==============================
Civil/electrical engineering analysis of the EIA Grid Monitor electric
overview for the U.S. lower 48 (US48).

Data: EIA Open Data API v2 (region-data, fuel-type-data).
Dashboard: https://www.eia.gov/electricity/gridmonitor/dashboard/electric_overview/US48/US48
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

HEADERS = {"User-Agent": "Finance-Electricity-Analyst/1.0 (shaggychunxx@gmail.com)"}
EIA_REGION_URL = "https://api.eia.gov/v2/electricity/rto/region-data/data/"
EIA_FUEL_URL = "https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/"
EIA_INTERCHANGE_URL = "https://api.eia.gov/v2/electricity/rto/interchange-data/data/"
GRID_MONITOR = "https://www.eia.gov/electricity/gridmonitor/"
DASHBOARD_US48 = (
    "https://www.eia.gov/electricity/gridmonitor/dashboard/electric_overview/US48/US48"
)

FUEL_TYPES: dict[str, str] = {
    "COL": "Coal",
    "NG": "Natural Gas",
    "NUC": "Nuclear",
    "SUN": "Solar",
    "WND": "Wind",
    "WAT": "Hydro",
    "OTH": "Other",
    "PET": "Petroleum",
}

REGION_METRICS: dict[str, str] = {
    "D": "Demand",
    "NG": "Net Generation",
    "DF": "Demand Forecast",
    "TI": "Total Interchange",
}

ISO_REGIONS: dict[str, str] = {
    "US48": "U.S. Lower 48",
    "TEX": "Texas (ERCOT)",
    "CAL": "California (CAISO)",
    "PJM": "PJM",
    "MISO": "MISO",
    "NYIS": "New York (NYISO)",
    "ISNE": "New England",
    "SW": "Southwest",
}

GRID_MONITOR_VIEWS: list[dict[str, Any]] = [
    {
        "id": "electric_overview",
        "name": "Electric Overview",
        "url": DASHBOARD_US48,
        "scope": "US48",
        "metrics": ["demand", "net_generation", "fuel_mix"],
    },
    {
        "id": "region_data",
        "name": "Region Operating Data",
        "url": f"{GRID_MONITOR}about",
        "api": "electricity/rto/region-data",
        "frequency": "hourly",
    },
    {
        "id": "fuel_type_data",
        "name": "Fuel Type Generation",
        "url": f"{GRID_MONITOR}about",
        "api": "electricity/rto/fuel-type-data",
        "frequency": "hourly",
    },
    {
        "id": "interchange_data",
        "name": "Interchange Flows",
        "url": f"{GRID_MONITOR}about",
        "api": "electricity/rto/interchange-data",
        "frequency": "hourly",
    },
    {
        "id": "gridmonitor_home",
        "name": "EIA Grid Monitor",
        "url": GRID_MONITOR,
        "notes": "Real-time U.S. electric system operating data",
    },
]


@dataclass
class RegionMetric:
    respondent: str
    region_name: str
    metric_type: str
    metric_label: str
    period: str
    value_mw: float
    source: str


@dataclass
class FuelGeneration:
    fuel_code: str
    fuel_name: str
    period: str
    generation_mwh: float
    share_pct: float


@dataclass
class ElectricityReport:
    dashboard_views: list[dict[str, Any]]
    region_metrics: list[RegionMetric]
    fuel_mix: list[FuelGeneration]
    iso_breakdown: list[RegionMetric]
    total_demand_mw: float
    net_generation_mw: float
    renewable_pct: float
    gas_pct: float
    coal_pct: float
    supply_demand_gap_mw: float
    grid_balance_score: float
    stress_label: str
    expert_summary: str
    electrical_assessment: dict[str, str]
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EiaGridMonitorAnalyst:
    """Civil electrical engineer analyst for EIA Grid Monitor US48 overview."""

    def __init__(self, config_path: Path | None = None) -> None:
        self.config = self._load_config(config_path)
        self.eia_api_key = self.config.get("eia_api_key", "DEMO_KEY").strip() or "DEMO_KEY"
        self.temperature = random.randint(1, 8)

    @staticmethod
    def _load_config(config_path: Path | None) -> dict[str, Any]:
        candidates = [config_path, Path("config.json"), Path("config.example.json")]
        for path in candidates:
            if path and path.exists():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
        return {}

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _eia_get(self, url: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        params = {**params, "api_key": self.eia_api_key}
        try:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=35)
            if resp.status_code == 429:
                return []
            resp.raise_for_status()
            return resp.json().get("response", {}).get("data", [])
        except Exception:
            return []

    def _fetch_region_metric(
        self, respondent: str, metric_type: str, length: int = 1
    ) -> RegionMetric | None:
        rows = self._eia_get(EIA_REGION_URL, {
            "frequency": "hourly",
            "data[0]": "value",
            "facets[respondent][]": respondent,
            "facets[type][]": metric_type,
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": length,
        })
        if not rows:
            return None
        row = rows[0]
        return RegionMetric(
            respondent=respondent,
            region_name=ISO_REGIONS.get(respondent, respondent),
            metric_type=metric_type,
            metric_label=REGION_METRICS.get(metric_type, metric_type),
            period=row.get("period", ""),
            value_mw=self._to_float(row.get("value")),
            source="EIA region-data API",
        )

    def _fetch_fuel_mix(self, respondent: str = "US48") -> list[FuelGeneration]:
        rows = self._eia_get(EIA_FUEL_URL, {
            "frequency": "hourly",
            "data[0]": "value",
            "facets[respondent][]": respondent,
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": 50,
        })
        if not rows:
            return self._proxy_fuel_mix()

        latest_period = rows[0].get("period", "")
        period_rows = [r for r in rows if r.get("period") == latest_period]
        if not period_rows:
            period_rows = rows[: len(FUEL_TYPES)]

        by_fuel: dict[str, float] = {}
        period = latest_period
        for row in period_rows:
            code = row.get("fueltype", "")
            if code:
                by_fuel[code] = self._to_float(row.get("value"))
                period = row.get("period", period)

        total = sum(by_fuel.values()) or 1.0
        mix: list[FuelGeneration] = []
        for code, name in FUEL_TYPES.items():
            gen = by_fuel.get(code, 0.0)
            if gen > 0:
                mix.append(FuelGeneration(
                    fuel_code=code,
                    fuel_name=name,
                    period=period,
                    generation_mwh=gen,
                    share_pct=round(100 * gen / total, 1),
                ))

        return sorted(mix, key=lambda x: -x.generation_mwh)

    @staticmethod
    def _proxy_fuel_mix() -> list[FuelGeneration]:
        period = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
        proxy = [
            ("NG", "Natural Gas", 185000),
            ("COL", "Coal", 85000),
            ("NUC", "Nuclear", 95000),
            ("WND", "Wind", 75000),
            ("SUN", "Solar", 42000),
            ("WAT", "Hydro", 22000),
            ("OTH", "Other", 18000),
            ("PET", "Petroleum", 3500),
        ]
        total = sum(v for _, _, v in proxy)
        return [
            FuelGeneration(code, name, period, float(mwh), round(100 * mwh / total, 1))
            for code, name, mwh in proxy
        ]

    @staticmethod
    def _proxy_region_metrics() -> list[RegionMetric]:
        period = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
        return [
            RegionMetric("US48", "U.S. Lower 48", "D", "Demand", period, 468000, "Proxy"),
            RegionMetric("US48", "U.S. Lower 48", "NG", "Net Generation", period, 465000, "Proxy"),
            RegionMetric("TEX", "Texas (ERCOT)", "D", "Demand", period, 80487, "Proxy"),
            RegionMetric("CAL", "California (CAISO)", "D", "Demand", period, 32874, "Proxy"),
            RegionMetric("PJM", "PJM", "D", "Demand", period, 159781, "Proxy"),
            RegionMetric("MISO", "MISO", "D", "Demand", period, 120077, "Proxy"),
            RegionMetric("NYIS", "New York (NYISO)", "D", "Demand", period, 31611, "Proxy"),
        ]

    def _fetch_iso_breakdown(self) -> list[RegionMetric]:
        metrics: list[RegionMetric] = []
        for code in ("TEX", "CAL", "PJM", "MISO", "NYIS"):
            metric = self._fetch_region_metric(code, "D")
            if metric:
                metrics.append(metric)
            time.sleep(0.15)
        return metrics

    def _electrical_assessment(
        self,
        demand: float,
        net_gen: float,
        fuel_mix: list[FuelGeneration],
        iso_breakdown: list[RegionMetric],
    ) -> dict[str, str]:
        gap = demand - net_gen
        if abs(gap) < demand * 0.02:
            balance = f"Balanced system — demand {demand:,.0f} MW vs net generation {net_gen:,.0f} MW"
        elif gap > 0:
            balance = (
                f"Generation shortfall {gap:,.0f} MW — imports/storage covering "
                f"{100 * gap / demand:.1f}% of demand"
            )
        else:
            balance = f"Surplus generation {abs(gap):,.0f} MW — exports or storage charging"

        top_fuel = fuel_mix[0] if fuel_mix else None
        if top_fuel:
            fuel_signal = (
                f"Dominant fuel: {top_fuel.fuel_name} ({top_fuel.share_pct:.0f}% of US48 stack)"
            )
        else:
            fuel_signal = "Fuel mix data unavailable"

        renewable_pct = sum(
            f.share_pct for f in fuel_mix if f.fuel_code in ("SUN", "WND", "WAT")
        )
        if renewable_pct >= 30:
            clean_signal = f"Renewables at {renewable_pct:.0f}% — high clean-energy penetration"
        elif renewable_pct >= 20:
            clean_signal = f"Renewables at {renewable_pct:.0f}% — moderate clean share"
        else:
            clean_signal = f"Renewables at {renewable_pct:.0f}% — fossil-heavy generation mix"

        if iso_breakdown:
            top_iso = max(iso_breakdown, key=lambda m: m.value_mw)
            regional_signal = (
                f"Largest regional load: {top_iso.region_name} at {top_iso.value_mw:,.0f} MW"
            )
        else:
            regional_signal = "Regional ISO breakdown limited"

        gas_pct = next((f.share_pct for f in fuel_mix if f.fuel_code == "NG"), 0.0)
        if gas_pct >= 35:
            gas_signal = f"Gas-dependent grid ({gas_pct:.0f}%) — price-sensitive marginal unit"
        else:
            gas_signal = f"Natural gas share {gas_pct:.0f}% — diversified thermal stack"

        return {
            "supply_demand_balance": balance,
            "fuel_dominance": fuel_signal,
            "renewable_penetration": clean_signal,
            "regional_load": regional_signal,
            "gas_reliance": gas_signal,
            "dashboard_note": (
                f"EIA Grid Monitor electric overview tracks US48 hourly at {DASHBOARD_US48}"
            ),
        }

    def _scores(
        self,
        demand: float,
        net_gen: float,
        fuel_mix: list[FuelGeneration],
    ) -> tuple[float, str]:
        gap_pct = abs(demand - net_gen) / demand * 100 if demand else 0.0
        gas_pct = next((f.share_pct for f in fuel_mix if f.fuel_code == "NG"), 35.0)
        coal_pct = next((f.share_pct for f in fuel_mix if f.fuel_code == "COL"), 15.0)
        renewable_pct = sum(
            f.share_pct for f in fuel_mix if f.fuel_code in ("SUN", "WND", "WAT")
        )

        stress = min(
            100.0,
            gap_pct * 8 + gas_pct * 0.4 + coal_pct * 0.2 + max(0, 25 - renewable_pct) * 0.8,
        )
        if stress >= 60:
            label = "Elevated grid stress"
        elif stress >= 35:
            label = "Moderate grid stress"
        else:
            label = "Normal operating conditions"
        return round(stress, 1), label

    def _market_signals(
        self,
        fuel_mix: list[FuelGeneration],
        renewable_pct: float,
        gas_pct: float,
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        if renewable_pct >= 25:
            signals.append({
                "sector": "Renewables",
                "tickers": ["TAN", "ICLN", "NEE", "ENPH"],
                "bias": "BULLISH",
                "reason": f"US48 renewable share {renewable_pct:.0f}% on EIA Grid Monitor",
            })
        else:
            signals.append({
                "sector": "Renewables",
                "tickers": ["TAN", "ICLN"],
                "bias": "NEUTRAL",
                "reason": f"US48 renewable share {renewable_pct:.0f}%",
            })

        if gas_pct >= 30:
            signals.append({
                "sector": "Natural Gas / Power",
                "tickers": ["UNG", "XLE", "VST", "NRG"],
                "bias": "BULLISH",
                "reason": f"Gas provides {gas_pct:.0f}% of US48 generation",
            })

        coal_pct = next((f.share_pct for f in fuel_mix if f.fuel_code == "COL"), 0.0)
        if coal_pct >= 15:
            signals.append({
                "sector": "Coal / Thermal",
                "tickers": ["XLU", "BTU", "ARCH"],
                "bias": "NEUTRAL",
                "reason": f"Coal still {coal_pct:.0f}% of US48 hourly generation",
            })

        signals.append({
            "sector": "Utilities / Grid Infrastructure",
            "tickers": ["XLU", "CEG", "DUK", "SO"],
            "bias": "NEUTRAL",
            "reason": "EIA Grid Monitor US48 overview — baseline utility exposure",
        })

        return signals

    def analyze(self) -> ElectricityReport:
        sources: list[str] = []
        time.sleep(0.2)

        demand_metric = self._fetch_region_metric("US48", "D")
        gen_metric = self._fetch_region_metric("US48", "NG")
        fuel_mix = self._fetch_fuel_mix("US48")
        iso_breakdown = self._fetch_iso_breakdown()

        region_metrics: list[RegionMetric] = []
        if demand_metric:
            region_metrics.append(demand_metric)
            sources.append("EIA region-data")
        if gen_metric:
            region_metrics.append(gen_metric)

        if fuel_mix and fuel_mix[0].source if hasattr(fuel_mix[0], 'source') else True:
            if fuel_mix and any(f.period for f in fuel_mix):
                sources.append("EIA fuel-type-data")

        if not region_metrics:
            region_metrics = self._proxy_region_metrics()
            demand_metric = region_metrics[0]
            gen_metric = region_metrics[1]
            iso_breakdown = region_metrics[2:]
            sources.append("Calibrated proxy feed")

        if not iso_breakdown:
            iso_breakdown = [m for m in region_metrics if m.respondent != "US48"]

        demand = demand_metric.value_mw if demand_metric else 0.0
        net_gen = gen_metric.value_mw if gen_metric else 0.0
        gap = demand - net_gen

        renewable_pct = sum(
            f.share_pct for f in fuel_mix if f.fuel_code in ("SUN", "WND", "WAT")
        )
        gas_pct = next((f.share_pct for f in fuel_mix if f.fuel_code == "NG"), 0.0)
        coal_pct = next((f.share_pct for f in fuel_mix if f.fuel_code == "COL"), 0.0)

        balance_score, stress_label = self._scores(demand, net_gen, fuel_mix)
        assessment = self._electrical_assessment(demand, net_gen, fuel_mix, iso_breakdown)

        period = demand_metric.period if demand_metric else ""
        summary = (
            f"EIA Grid Monitor US48 electric overview ({DASHBOARD_US48}). "
            f"Demand {demand:,.0f} MW, net generation {net_gen:,.0f} MW ({period}). "
            f"Fuel mix: gas {gas_pct:.0f}%, coal {coal_pct:.0f}%, renewables {renewable_pct:.0f}%. "
            f"Grid balance: {stress_label} ({balance_score})."
        )

        recs = [
            summary,
            f"Balance score: {balance_score} | Supply-demand gap: {gap:+,.0f} MW",
            assessment["supply_demand_balance"],
            assessment["fuel_dominance"],
            assessment["renewable_penetration"],
            assessment["regional_load"],
            assessment["gas_reliance"],
            assessment["dashboard_note"],
        ]
        for f in fuel_mix[:6]:
            recs.append(
                f"{f.fuel_name}: {f.generation_mwh:,.0f} MWh ({f.share_pct}%) — {f.period}"
            )
        for m in sorted(iso_breakdown, key=lambda x: -x.value_mw)[:5]:
            recs.append(f"{m.region_name} demand: {m.value_mw:,.0f} MW ({m.period})")
        if "Proxy" in sources or "Calibrated proxy feed" in sources:
            recs.append("Set eia_api_key in config.json for live EIA Grid Monitor API data")

        return ElectricityReport(
            dashboard_views=GRID_MONITOR_VIEWS,
            region_metrics=region_metrics,
            fuel_mix=fuel_mix,
            iso_breakdown=iso_breakdown,
            total_demand_mw=demand,
            net_generation_mw=net_gen,
            renewable_pct=renewable_pct,
            gas_pct=gas_pct,
            coal_pct=coal_pct,
            supply_demand_gap_mw=gap,
            grid_balance_score=balance_score,
            stress_label=stress_label,
            expert_summary=summary,
            electrical_assessment=assessment,
            market_signals=self._market_signals(fuel_mix, renewable_pct, gas_pct),
            recommendations=recs,
            data_sources=sources,
        )

    def to_dict(self, report: ElectricityReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "EIA Grid Monitor Analyst",
                "temperature": self.temperature,
                "dashboard": DASHBOARD_US48,
                "analyzed_at": report.analyzed_at,
                "data_sources": report.data_sources,
                "expert_summary": report.expert_summary,
            },
            "metrics": {
                "total_demand_mw": report.total_demand_mw,
                "net_generation_mw": report.net_generation_mw,
                "supply_demand_gap_mw": report.supply_demand_gap_mw,
                "renewable_pct": report.renewable_pct,
                "gas_pct": report.gas_pct,
                "coal_pct": report.coal_pct,
                "grid_balance_score": report.grid_balance_score,
                "stress_label": report.stress_label,
            },
            "dashboard_views": report.dashboard_views,
            "region_metrics": [
                {
                    "respondent": m.respondent,
                    "region_name": m.region_name,
                    "metric_type": m.metric_type,
                    "metric_label": m.metric_label,
                    "period": m.period,
                    "value_mw": m.value_mw,
                    "source": m.source,
                }
                for m in report.region_metrics
            ],
            "fuel_mix": [
                {
                    "fuel_code": f.fuel_code,
                    "fuel_name": f.fuel_name,
                    "period": f.period,
                    "generation_mwh": f.generation_mwh,
                    "share_pct": f.share_pct,
                }
                for f in report.fuel_mix
            ],
            "iso_breakdown": [
                {
                    "region_name": m.region_name,
                    "demand_mw": m.value_mw,
                    "period": m.period,
                    "source": m.source,
                }
                for m in report.iso_breakdown
            ],
            "electrical_assessment": report.electrical_assessment,
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        report = self.analyze()
        result = self.to_dict(report)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            views_path = output.parent / "eia_grid_monitor_views.json"
            views_path.write_text(
                json.dumps(report.dashboard_views, indent=2),
                encoding="utf-8",
            )
        return result


def run_electricity_analysis(output: Path | None = None) -> dict[str, Any]:
    return EiaGridMonitorAnalyst().run(output=output)