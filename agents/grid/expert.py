"""
Electrical Grid Analyst Agent
=============================
Civil/electrical engineering analysis of live wholesale power markets,
mirroring Grid Status Live (gridstatus.io/live) using ISO public feeds.

Data: ERCOT & CAISO live dashboards, EIA RTO demand (+ optional Grid Status API).
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agents.base import BaseExpert

HEADERS = {"User-Agent": "Finance-Grid-Analyst/1.0 (shaggychunxx@gmail.com)"}
GRID_LIVE = "https://www.gridstatus.io/live"
GRID_API = "https://api.gridstatus.io/v1"

ERCOT_FUEL_URL = "https://www.ercot.com/api/1/services/read/dashboards/fuel-mix.json"
CAISO_FUEL_URL = "https://www.caiso.com/outlook/current/fuelsource.csv"
CAISO_DEMAND_URL = "https://www.caiso.com/outlook/current/demand.csv"
CAISO_NET_DEMAND_URL = "https://www.caiso.com/outlook/current/netdemand.csv"
EIA_RTO_URL = "https://api.eia.gov/v2/electricity/rto/region-data/data/"

GRID_MARKETS: list[dict[str, Any]] = [
    {"id": "ercot", "name": "ERCOT", "region": "Texas", "live_url": f"{GRID_LIVE}/ercot"},
    {"id": "caiso", "name": "CAISO", "region": "California", "live_url": f"{GRID_LIVE}/caiso"},
    {"id": "pjm", "name": "PJM", "region": "Mid-Atlantic / Midwest", "live_url": f"{GRID_LIVE}/pjm"},
    {"id": "miso", "name": "MISO", "region": "Central US", "live_url": f"{GRID_LIVE}/miso"},
    {"id": "spp", "name": "SPP", "region": "Great Plains", "live_url": f"{GRID_LIVE}/spp"},
    {"id": "nyiso", "name": "NYISO", "region": "New York", "live_url": f"{GRID_LIVE}/nyiso"},
    {"id": "isone", "name": "ISO-NE", "region": "New England", "live_url": f"{GRID_LIVE}/isone"},
    {"id": "ieso", "name": "IESO", "region": "Ontario", "live_url": f"{GRID_LIVE}/ieso"},
    {"id": "aeso", "name": "AESO", "region": "Alberta", "live_url": f"{GRID_LIVE}/aeso"},
]

EIA_ISO_MAP = {
    "TEX": "ERCOT",
    "CAL": "CAISO",
    "PJM": "PJM",
    "MISO": "MISO",
    "NYIS": "NYISO",
    "ISNE": "ISO-NE",
    "SW": "Southwest",
}


@dataclass
class FuelSnapshot:
    market: str
    timestamp: str
    total_mw: float
    solar_mw: float
    wind_mw: float
    gas_mw: float
    coal_mw: float
    nuclear_mw: float
    storage_mw: float
    renewable_pct: float
    gas_pct: float
    source: str


@dataclass
class IsoDemand:
    iso: str
    name: str
    period: str
    demand_mw: float
    source: str


@dataclass
class HubPrice:
    hub: str
    lmp: float
    market: str


@dataclass
class GridReport:
    markets: list[dict[str, Any]]
    fuel_snapshots: list[FuelSnapshot]
    iso_demands: list[IsoDemand]
    hub_prices: list[HubPrice]
    caiso_net_demand_mw: float | None
    grid_stress_score: float
    renewable_index: float
    stress_label: str
    expert_summary: str
    electrical_assessment: dict[str, str]
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ElectricalGridAnalyst(BaseExpert):
    """Electrical engineer analyst for live wholesale grid conditions."""

    def __init__(
        self,
        config_path: Path | None = None,
        *,
        pipeline_context: dict | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="grid")
        self.config = self._load_config(config_path)
        self.gridstatus_api_key = self.config.get("gridstatus_api_key", "").strip()
        self.eia_api_key = self.config.get("eia_api_key", "DEMO_KEY").strip() or "DEMO_KEY"

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

    def _gridstatus_query(self, dataset_id: str, **params: Any) -> list[dict[str, Any]]:
        if not self.gridstatus_api_key:
            return []
        headers = {**HEADERS, "x-api-key": self.gridstatus_api_key}
        query = {"limit": 5, **params}
        try:
            resp = requests.get(
                f"{GRID_API}/datasets/{dataset_id}/query",
                headers=headers,
                params=query,
                timeout=35,
            )
            resp.raise_for_status()
            payload = resp.json()
            return payload.get("data", [])
        except Exception:
            return []

    def _fetch_ercot_fuel(self) -> FuelSnapshot | None:
        try:
            resp = requests.get(ERCOT_FUEL_URL, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            return None

        data = payload.get("data", {})
        if not data:
            return None

        last_day = sorted(data.keys())[-1]
        last_time = sorted(data[last_day].keys())[-1]
        fuels = data[last_day][last_time]

        solar = self._to_float(fuels.get("Solar", {}).get("gen"))
        wind = self._to_float(fuels.get("Wind", {}).get("gen"))
        gas = self._to_float(fuels.get("Natural Gas", {}).get("gen"))
        coal = self._to_float(fuels.get("Coal and Lignite", {}).get("gen"))
        nuclear = self._to_float(fuels.get("Nuclear", {}).get("gen"))
        storage = self._to_float(fuels.get("Power Storage", {}).get("gen"))
        hydro = self._to_float(fuels.get("Hydro", {}).get("gen"))
        other = self._to_float(fuels.get("Other", {}).get("gen"))

        total = solar + wind + gas + coal + nuclear + storage + hydro + other
        if total <= 0:
            return None

        renewable = solar + wind + hydro
        return FuelSnapshot(
            market="ERCOT",
            timestamp=payload.get("lastUpdated", last_time),
            total_mw=round(total, 1),
            solar_mw=round(solar, 1),
            wind_mw=round(wind, 1),
            gas_mw=round(gas, 1),
            coal_mw=round(coal, 1),
            nuclear_mw=round(nuclear, 1),
            storage_mw=round(storage, 1),
            renewable_pct=round(100 * renewable / total, 1),
            gas_pct=round(100 * gas / total, 1),
            source="ERCOT Public API",
        )

    @staticmethod
    def _parse_caiso_csv(url: str) -> list[dict[str, str]]:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=25)
            resp.raise_for_status()
            reader = csv.DictReader(io.StringIO(resp.text))
            return list(reader)
        except Exception:
            return []

    def _fetch_caiso_fuel(self) -> FuelSnapshot | None:
        rows = self._parse_caiso_csv(CAISO_FUEL_URL)
        if not rows:
            return None

        row = rows[-1]
        solar = max(0.0, self._to_float(row.get("Solar")))
        wind = self._to_float(row.get("Wind"))
        gas = self._to_float(row.get("Natural Gas"))
        coal = self._to_float(row.get("Coal"))
        nuclear = self._to_float(row.get("Nuclear"))
        storage = self._to_float(row.get("Batteries"))
        hydro = max(0.0, self._to_float(row.get("Large Hydro"))) + max(
            0.0, self._to_float(row.get("Small hydro"))
        )
        imports = max(0.0, self._to_float(row.get("Imports")))
        other = max(0.0, self._to_float(row.get("Other"))) + max(
            0.0, self._to_float(row.get("Geothermal"))
        )
        other += max(0.0, self._to_float(row.get("Biomass"))) + max(
            0.0, self._to_float(row.get("Biogas"))
        )

        total = solar + wind + max(0.0, gas) + max(0.0, coal) + max(0.0, nuclear)
        total += abs(storage) + hydro + imports + other
        if total <= 0:
            return None

        renewable = solar + wind + hydro
        return FuelSnapshot(
            market="CAISO",
            timestamp=row.get("Time", ""),
            total_mw=round(total, 1),
            solar_mw=round(solar, 1),
            wind_mw=round(wind, 1),
            gas_mw=round(gas, 1),
            coal_mw=round(coal, 1),
            nuclear_mw=round(nuclear, 1),
            storage_mw=round(storage, 1),
            renewable_pct=round(100 * renewable / total, 1),
            gas_pct=round(100 * gas / total, 1),
            source="CAISO Today's Outlook",
        )

    def _fetch_caiso_net_demand(self) -> float | None:
        rows = self._parse_caiso_csv(CAISO_NET_DEMAND_URL)
        for row in reversed(rows):
            value = self._to_float(row.get("Net demand"))
            if value > 0:
                return value
        return None

    def _fetch_eia_demands(self) -> list[IsoDemand]:
        demands: list[IsoDemand] = []
        for code, name in EIA_ISO_MAP.items():
            params = {
                "api_key": self.eia_api_key,
                "frequency": "hourly",
                "data[0]": "value",
                "facets[type][]": "D",
                "facets[respondent][]": code,
                "sort[0][column]": "period",
                "sort[0][direction]": "desc",
                "length": 1,
            }
            try:
                resp = requests.get(EIA_RTO_URL, headers=HEADERS, params=params, timeout=20)
                resp.raise_for_status()
                rows = resp.json().get("response", {}).get("data", [])
                if rows:
                    row = rows[0]
                    demands.append(IsoDemand(
                        iso=code,
                        name=name,
                        period=row.get("period", ""),
                        demand_mw=self._to_float(row.get("value")),
                        source="EIA RTO API",
                    ))
            except Exception:
                continue

        if not demands:
            demands = [
                IsoDemand("TEX", "ERCOT", "proxy", 80487, "Proxy"),
                IsoDemand("CAL", "CAISO", "proxy", 32874, "Proxy"),
                IsoDemand("PJM", "PJM", "proxy", 159781, "Proxy"),
            ]
        return demands

    def _fetch_hub_prices(self) -> list[HubPrice]:
        rows = self._gridstatus_query(
            "ercot_lmp_by_settlement_point",
            time="latest",
            filter_column="location",
            filter_value="HB_HOUSTON,HB_NORTH,HB_WEST,HB_SOUTH",
            filter_operator="in",
            columns="location,lmp,interval_start_utc",
        )
        prices: list[HubPrice] = []
        for row in rows:
            hub = row.get("location", "")
            lmp = self._to_float(row.get("lmp"))
            if hub and lmp:
                prices.append(HubPrice(hub=hub, lmp=lmp, market="ERCOT"))
        return prices

    def _electrical_assessment(
        self,
        fuels: list[FuelSnapshot],
        demands: list[IsoDemand],
        hub_prices: list[HubPrice],
        net_demand: float | None,
    ) -> dict[str, str]:
        ercot = next((f for f in fuels if f.market == "ERCOT"), None)
        caiso = next((f for f in fuels if f.market == "CAISO"), None)

        if ercot and ercot.wind_mw > ercot.solar_mw * 2:
            ercot_mix = (
                f"ERCOT wind-dominant renewables ({ercot.wind_mw:,.0f} MW wind vs "
                f"{ercot.solar_mw:,.0f} MW solar); gas {ercot.gas_pct:.0f}% of stack"
            )
        elif ercot:
            ercot_mix = (
                f"ERCOT balanced renewables ({ercot.renewable_pct:.0f}% clean); "
                f"gas {ercot.gas_pct:.0f}% of generation"
            )
        else:
            ercot_mix = "ERCOT fuel mix unavailable — check ERCOT dashboard"

        if caiso:
            caiso_mix = (
                f"CAISO {caiso.renewable_pct:.0f}% renewable penetration; "
                f"batteries dispatching {caiso.storage_mw:,.0f} MW"
            )
        else:
            caiso_mix = "CAISO fuel mix unavailable"

        top_demand = max(demands, key=lambda d: d.demand_mw) if demands else None
        if top_demand:
            load_signal = (
                f"Highest monitored load: {top_demand.name} at "
                f"{top_demand.demand_mw:,.0f} MW ({top_demand.period})"
            )
        else:
            load_signal = "Regional load data limited"

        if hub_prices:
            avg_lmp = sum(p.lmp for p in hub_prices) / len(hub_prices)
            max_hub = max(hub_prices, key=lambda p: p.lmp)
            price_signal = (
                f"ERCOT hub LMP avg ${avg_lmp:.2f}/MWh; peak {max_hub.hub} ${max_hub.lmp:.2f}/MWh"
            )
        else:
            price_signal = (
                "Hub LMP data requires gridstatus_api_key — add key from gridstatus.io for pricing"
            )

        if net_demand is not None:
            net_signal = f"CAISO net demand {net_demand:,.0f} MW — load minus renewables/storage"
        else:
            net_signal = "CAISO net demand feed unavailable"

        if ercot and ercot.storage_mw > 3000:
            storage_signal = (
                f"Active battery participation: ERCOT {ercot.storage_mw:,.0f} MW, "
                f"CAISO {caiso.storage_mw if caiso else 0:,.0f} MW"
            )
        else:
            storage_signal = "Battery storage dispatch within normal operating range"

        return {
            "generation_mix": ercot_mix,
            "caiso_renewables": caiso_mix,
            "regional_load": load_signal,
            "wholesale_pricing": price_signal,
            "net_demand": net_signal,
            "storage_dispatch": storage_signal,
        }

    def _scores(self, fuels: list[FuelSnapshot], hub_prices: list[HubPrice]) -> tuple[float, float, str]:
        if fuels:
            renewable_index = sum(f.renewable_pct for f in fuels) / len(fuels)
            gas_avg = sum(f.gas_pct for f in fuels) / len(fuels)
        else:
            renewable_index = 30.0
            gas_avg = 40.0

        price_stress = 0.0
        if hub_prices:
            avg_lmp = sum(p.lmp for p in hub_prices) / len(hub_prices)
            price_stress = min(40.0, max(0.0, (avg_lmp - 30) * 2))

        stress = min(100.0, gas_avg * 0.6 + price_stress + max(0, 50 - renewable_index) * 0.5)
        if stress >= 65:
            label = "Elevated grid stress"
        elif stress >= 40:
            label = "Moderate grid stress"
        else:
            label = "Normal grid operations"

        return round(stress, 1), round(renewable_index, 1), label

    def _market_signals(
        self,
        fuels: list[FuelSnapshot],
        hub_prices: list[HubPrice],
        demands: list[IsoDemand],
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import meteorology_energy_score, power_grid_market_impact_signals

        avg_renewable = sum(f.renewable_pct for f in fuels) / len(fuels) if fuels else 0.0
        ercot = next((f for f in fuels if f.market == "ERCOT"), None)
        avg_lmp = sum(p.lmp for p in hub_prices) / len(hub_prices) if hub_prices else None
        peak_load = max((d.demand_mw for d in demands), default=0.0) or None
        stress_score, _, stress_label = self._scores(fuels, hub_prices)

        signals = power_grid_market_impact_signals(
            grid_stress=stress_score,
            stress_label=stress_label,
            renewable_pct=avg_renewable,
            gas_pct=ercot.gas_pct if ercot else None,
            avg_lmp=avg_lmp,
            weather_energy=meteorology_energy_score(),
            peak_load_mw=peak_load,
            source="grid",
        )
        return self._adjust_market_signals(signals)

    def analyze(self) -> GridReport:
        fuels: list[FuelSnapshot] = []
        sources: list[str] = []

        ercot = self._fetch_ercot_fuel()
        if ercot:
            fuels.append(ercot)
            sources.append("ERCOT Public API")

        caiso = self._fetch_caiso_fuel()
        if caiso:
            fuels.append(caiso)
            sources.append("CAISO Today's Outlook")

        demands = self._fetch_eia_demands()
        if demands and demands[0].source == "EIA RTO API":
            sources.append("EIA RTO API")

        net_demand = self._fetch_caiso_net_demand()
        hub_prices = self._fetch_hub_prices()
        if hub_prices:
            sources.append("Grid Status API")

        stress_score, renewable_index, stress_label = self._scores(fuels, hub_prices)
        assessment = self._electrical_assessment(fuels, demands, hub_prices, net_demand)

        summary = (
            f"Electrical engineering scan of Grid Status Live ({GRID_LIVE}) across "
            f"{len(GRID_MARKETS)} wholesale markets. "
        )
        if ercot:
            summary += (
                f"ERCOT: {ercot.total_mw:,.0f} MW generation, "
                f"{ercot.renewable_pct:.0f}% renewable, gas {ercot.gas_pct:.0f}%. "
            )
        if caiso:
            summary += f"CAISO: {caiso.renewable_pct:.0f}% renewable, storage {caiso.storage_mw:,.0f} MW. "
        summary += f"Grid stress: {stress_label} ({stress_score})."

        recs = [
            summary,
            f"Stress score: {stress_score} | Renewable index: {renewable_index}",
            f"Live portal: {GRID_LIVE}",
            assessment["generation_mix"],
            assessment["caiso_renewables"],
            assessment["regional_load"],
            assessment["wholesale_pricing"],
            assessment["net_demand"],
            assessment["storage_dispatch"],
        ]
        for f in fuels:
            recs.append(
                f"{f.market}: {f.total_mw:,.0f} MW total | solar {f.solar_mw:,.0f} | "
                f"wind {f.wind_mw:,.0f} | gas {f.gas_pct:.0f}%"
            )
        for d in sorted(demands, key=lambda x: -x.demand_mw)[:5]:
            recs.append(f"{d.name} load: {d.demand_mw:,.0f} MW ({d.period})")
        for p in hub_prices:
            recs.append(f"{p.market} {p.hub}: ${p.lmp:.2f}/MWh")

        return GridReport(
            markets=GRID_MARKETS,
            fuel_snapshots=fuels,
            iso_demands=demands,
            hub_prices=hub_prices,
            caiso_net_demand_mw=net_demand,
            grid_stress_score=stress_score,
            renewable_index=renewable_index,
            stress_label=stress_label,
            expert_summary=summary,
            electrical_assessment=assessment,
            market_signals=self._market_signals(fuels, hub_prices, demands),
            recommendations=recs,
            data_sources=sources,
        )

    def to_dict(self, report: GridReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Electrical Grid Analyst",
                "portal": GRID_LIVE,
                "analyzed_at": report.analyzed_at,
                "data_sources": report.data_sources,
                "expert_summary": report.expert_summary,
                "markets_monitored": len(report.markets),
            },
            "metrics": {
                "grid_stress_score": report.grid_stress_score,
                "renewable_index": report.renewable_index,
                "stress_label": report.stress_label,
                "caiso_net_demand_mw": report.caiso_net_demand_mw,
            },
            "markets": report.markets,
            "fuel_mix": [
                {
                    "market": f.market,
                    "timestamp": f.timestamp,
                    "total_mw": f.total_mw,
                    "solar_mw": f.solar_mw,
                    "wind_mw": f.wind_mw,
                    "gas_mw": f.gas_mw,
                    "coal_mw": f.coal_mw,
                    "nuclear_mw": f.nuclear_mw,
                    "storage_mw": f.storage_mw,
                    "renewable_pct": f.renewable_pct,
                    "gas_pct": f.gas_pct,
                    "source": f.source,
                }
                for f in report.fuel_snapshots
            ],
            "iso_demand": [
                {
                    "iso": d.iso,
                    "name": d.name,
                    "period": d.period,
                    "demand_mw": d.demand_mw,
                    "source": d.source,
                }
                for d in report.iso_demands
            ],
            "hub_prices": [
                {"hub": p.hub, "lmp": p.lmp, "market": p.market}
                for p in report.hub_prices
            ],
            "electrical_assessment": report.electrical_assessment,
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        report = self.analyze()
        result = self.to_dict(report)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            markets_path = output.parent / "grid_markets.json"
            markets_path.write_text(
                json.dumps(report.markets, indent=2),
                encoding="utf-8",
            )
        return result


def run_grid_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return ElectricalGridAnalyst(pipeline_context=pipeline_context).run(output=output)