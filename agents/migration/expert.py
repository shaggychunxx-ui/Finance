"""
Migration Data Analyst Agent
============================
Demographic/economic analysis of international migration corridors, using the
Migration Policy Institute's Migration Data Hub (migrationpolicy.org/programs/
migration-data-hub) as the reference portal and methodology guide, with live
figures pulled from the World Bank Open Data API (the same underlying source
MPI cites for net migration, remittance, and migrant-stock indicators).

Data: World Bank Open Data API — net migration, personal remittances received,
and international migrant stock, across the largest US-linked migration and
remittance corridors.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agents.base import BaseExpert

HEADERS = {"User-Agent": "Finance-Migration-Analyst/1.0 (shaggychunxx@gmail.com)"}
WORLD_BANK_API = "https://api.worldbank.org/v2/country"
MPI_PORTAL = "https://www.migrationpolicy.org/programs/migration-data-hub"

MIGRATION_RESOURCES: list[dict[str, Any]] = [
    {
        "id": "net_migration",
        "name": "Net Migration by Country",
        "category": "International Migration",
        "url": f"{MPI_PORTAL}",
        "indicator": "SM.POP.NETM",
        "access": "api",
        "notes": "Five-year net migration estimates (World Bank / UN DESA)",
    },
    {
        "id": "remittances",
        "name": "Personal Remittances Received",
        "category": "Remittances",
        "url": f"{MPI_PORTAL}",
        "indicator": "BX.TRF.PWKR.CD.DT",
        "access": "api",
        "notes": "Annual remittance inflows in current US$",
    },
    {
        "id": "remittances_pct_gdp",
        "name": "Remittances (% of GDP)",
        "category": "Remittances",
        "url": f"{MPI_PORTAL}",
        "indicator": "BX.TRF.PWKR.DT.GD.ZS",
        "access": "api",
        "notes": "Remittance dependency relative to national output",
    },
    {
        "id": "migrant_stock",
        "name": "International Migrant Stock (% of population)",
        "category": "International Migration",
        "url": f"{MPI_PORTAL}",
        "indicator": "SM.POP.TOTL.ZS",
        "access": "api",
        "notes": "Foreign-born share of resident population",
    },
    {
        "id": "refugee_pop",
        "name": "Refugee Population by Origin",
        "category": "Forced Displacement",
        "url": f"{MPI_PORTAL}",
        "indicator": "SM.POP.REFG.OR",
        "access": "api",
        "notes": "UNHCR-derived refugee population by country of origin",
    },
    {
        "id": "mpi_data_hub",
        "name": "MPI Migration Data Hub",
        "category": "Reference Portal",
        "url": MPI_PORTAL,
        "indicator": "",
        "access": "portal",
        "notes": "Curated charts, country profiles, and explainers on global migration trends",
    },
]

# ISO3 code -> (display name, sector tickers most linked to that corridor's
# remittance flows, diaspora consumer demand, or US labor supply).
CORRIDOR_TICKERS: dict[str, list[str]] = {
    "MEX": ["EWW", "WU", "MELI"],
    "IND": ["INDA", "WU", "PYPL"],
    "PHL": ["EPHE", "WU", "PYPL"],
    "CHN": ["MCHI", "BABA", "WU"],
    "NGA": ["WU", "PYPL"],
    "GTM": ["EWW", "WU"],
    "SLV": ["EWW", "WU"],
    "VNM": ["VNM", "WU"],
    "PAK": ["WU", "PYPL"],
    "BGD": ["WU", "PYPL"],
}

DEFAULT_COUNTRIES: list[dict[str, Any]] = [
    {"iso3": "MEX", "name": "Mexico", "net_migration": -400000, "remittances_usd": 63_300_000_000, "remittances_pct_gdp": 3.7, "migrant_stock_pct_pop": 1.0},
    {"iso3": "IND", "name": "India", "net_migration": -2_500_000, "remittances_usd": 125_000_000_000, "remittances_pct_gdp": 3.3, "migrant_stock_pct_pop": 0.4},
    {"iso3": "PHL", "name": "Philippines", "net_migration": -850_000, "remittances_usd": 40_000_000_000, "remittances_pct_gdp": 8.9, "migrant_stock_pct_pop": 0.2},
    {"iso3": "CHN", "name": "China", "net_migration": -450_000, "remittances_usd": 20_000_000_000, "remittances_pct_gdp": 0.1, "migrant_stock_pct_pop": 0.1},
    {"iso3": "NGA", "name": "Nigeria", "net_migration": -300_000, "remittances_usd": 20_100_000_000, "remittances_pct_gdp": 4.7, "migrant_stock_pct_pop": 0.7},
    {"iso3": "GTM", "name": "Guatemala", "net_migration": -175_000, "remittances_usd": 19_800_000_000, "remittances_pct_gdp": 19.0, "migrant_stock_pct_pop": 0.5},
    {"iso3": "SLV", "name": "El Salvador", "net_migration": -90_000, "remittances_usd": 8_200_000_000, "remittances_pct_gdp": 23.5, "migrant_stock_pct_pop": 0.3},
    {"iso3": "VNM", "name": "Vietnam", "net_migration": -170_000, "remittances_usd": 18_100_000_000, "remittances_pct_gdp": 4.4, "migrant_stock_pct_pop": 0.1},
    {"iso3": "PAK", "name": "Pakistan", "net_migration": -1_000_000, "remittances_usd": 27_000_000_000, "remittances_pct_gdp": 8.0, "migrant_stock_pct_pop": 0.4},
    {"iso3": "BGD", "name": "Bangladesh", "net_migration": -1_500_000, "remittances_usd": 21_500_000_000, "remittances_pct_gdp": 5.4, "migrant_stock_pct_pop": 0.9},
]


@dataclass
class CountryMigrationProfile:
    iso3: str
    name: str
    net_migration: float
    remittances_usd: float
    remittances_pct_gdp: float
    migrant_stock_pct_pop: float
    rank: int = 0


@dataclass
class MigrationReport:
    resources: list[dict[str, Any]]
    countries: list[CountryMigrationProfile]
    top_remittance_recipients: list[CountryMigrationProfile]
    top_net_emigration: list[CountryMigrationProfile]
    total_remittances_usd: float
    avg_remittance_pct_gdp: float
    migration_pressure_score: float
    remittance_dependency_score: float
    pressure_label: str
    expert_summary: str
    demographic_assessment: dict[str, str]
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    live_api_fields: int = 0
    seed_fallback_fields: int = 0
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MigrationDataAnalyst(BaseExpert):
    """Demographic/economic analyst for MPI Migration Data Hub corridors."""

    def __init__(self, *, pipeline_context: dict | None = None) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="migration")

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

    def _worldbank_get(self, iso3: str, indicator: str) -> float | None:
        url = f"{WORLD_BANK_API}/{iso3}/indicator/{indicator}"
        try:
            resp = requests.get(
                url,
                headers=HEADERS,
                params={"format": "json", "per_page": 10, "mrnev": 1},
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, list) or len(payload) < 2:
                return None
            for row in payload[1] or []:
                value = row.get("value")
                if value is not None:
                    return float(value)
            return None
        except Exception:
            return None

    def _fetch_countries(self) -> tuple[list[CountryMigrationProfile], int, int]:
        profiles: list[CountryMigrationProfile] = []
        live_fields = 0
        seed_fields = 0
        for seed in DEFAULT_COUNTRIES:
            net_mig = self._worldbank_get(seed["iso3"], "SM.POP.NETM")
            remit = self._worldbank_get(seed["iso3"], "BX.TRF.PWKR.CD.DT")
            remit_pct = self._worldbank_get(seed["iso3"], "BX.TRF.PWKR.DT.GD.ZS")
            stock_pct = self._worldbank_get(seed["iso3"], "SM.POP.TOTL.ZS")

            for live_val, seed_val in (
                (net_mig, seed["net_migration"]),
                (remit, seed["remittances_usd"]),
                (remit_pct, seed["remittances_pct_gdp"]),
                (stock_pct, seed["migrant_stock_pct_pop"]),
            ):
                if live_val is not None:
                    live_fields += 1
                else:
                    seed_fields += 1

            profiles.append(CountryMigrationProfile(
                iso3=seed["iso3"],
                name=seed["name"],
                net_migration=net_mig if net_mig is not None else float(seed["net_migration"]),
                remittances_usd=remit if remit is not None else float(seed["remittances_usd"]),
                remittances_pct_gdp=remit_pct if remit_pct is not None else float(seed["remittances_pct_gdp"]),
                migrant_stock_pct_pop=stock_pct if stock_pct is not None else float(seed["migrant_stock_pct_pop"]),
            ))

        profiles.sort(key=lambda p: p.remittances_usd, reverse=True)
        for i, p in enumerate(profiles, start=1):
            p.rank = i
        return profiles, live_fields, seed_fields

    def _demographic_assessment(
        self,
        countries: list[CountryMigrationProfile],
        top_remit: list[CountryMigrationProfile],
        top_emigration: list[CountryMigrationProfile],
        avg_remit_pct: float,
    ) -> dict[str, str]:
        leader = top_remit[0] if top_remit else None
        most_dependent = max(countries, key=lambda p: p.remittances_pct_gdp) if countries else None
        most_outflow = top_emigration[0] if top_emigration else None

        remittance_signal = (
            f"{leader.name} is the largest remittance recipient tracked "
            f"(${leader.remittances_usd / 1e9:.1f}B/yr)"
            if leader else "No remittance data available"
        )
        dependency_signal = (
            f"{most_dependent.name} is most remittance-dependent "
            f"({most_dependent.remittances_pct_gdp:.1f}% of GDP) — currency and "
            "consumption sensitive to US/Gulf labor market swings"
            if most_dependent else "No dependency data available"
        )
        outflow_signal = (
            f"{most_outflow.name} shows the largest net emigration in this corridor "
            f"set ({most_outflow.net_migration:,.0f} over the latest 5-year window)"
            if most_outflow else "No net migration data available"
        )

        if avg_remit_pct >= 10:
            macro_signal = "High average remittance dependency — corridor currencies vulnerable to US labor slowdowns"
        elif avg_remit_pct >= 4:
            macro_signal = "Moderate remittance dependency across tracked corridors"
        else:
            macro_signal = "Low aggregate remittance dependency — diversified corridor economies"

        return {
            "remittance_leader": remittance_signal,
            "remittance_dependency": dependency_signal,
            "net_migration": outflow_signal,
            "macro_sensitivity": macro_signal,
            "labor_supply_note": (
                "Persistent net emigration from South/Southeast Asia and Central America "
                "corresponds to elastic US labor supply in agriculture, construction, and staffing"
            ),
        }

    def _scores(
        self,
        countries: list[CountryMigrationProfile],
        avg_remit_pct: float,
    ) -> tuple[float, float, str]:
        if not countries:
            return 0.0, 0.0, "Insufficient data"

        emigration_intensity = statistics.mean(
            max(0.0, -p.net_migration) / 1_000_000 for p in countries
        )
        pressure = min(100.0, emigration_intensity * 8 + avg_remit_pct * 2)
        dependency = min(100.0, avg_remit_pct * 6)

        if pressure >= 65:
            label = "High migration pressure"
        elif pressure >= 35:
            label = "Moderate migration pressure"
        else:
            label = "Stable migration patterns"

        return round(pressure, 1), round(dependency, 1), label

    def _market_signals(
        self,
        top_remit: list[CountryMigrationProfile],
        most_dependent: CountryMigrationProfile | None,
        avg_remit_pct: float,
        *,
        pressure_score: float,
        pressure_label: str,
        dependency_score: float,
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import migration_market_impact_signals

        corridor_tickers: list[str] = []
        for c in top_remit[:3]:
            corridor_tickers.extend(CORRIDOR_TICKERS.get(c.iso3, []))
        deduped = list(dict.fromkeys(corridor_tickers))[:6]

        top_payload = [
            {
                "name": c.name,
                "iso3": c.iso3,
                "remittances_usd": c.remittances_usd,
                "remittances_pct_gdp": c.remittances_pct_gdp,
            }
            for c in top_remit
        ]
        dependent_payload = None
        if most_dependent is not None:
            dependent_payload = {
                "name": most_dependent.name,
                "iso3": most_dependent.iso3,
                "remittances_pct_gdp": most_dependent.remittances_pct_gdp,
                "tickers": CORRIDOR_TICKERS.get(most_dependent.iso3, ["WU"]),
            }

        signals = migration_market_impact_signals(
            pressure_score=pressure_score,
            pressure_label=pressure_label,
            avg_remit_pct=avg_remit_pct,
            dependency_score=dependency_score,
            top_remit=top_payload,
            most_dependent=dependent_payload,
            corridor_tickers=deduped,
        )
        return self._adjust_market_signals(signals)

    def analyze(self) -> MigrationReport:
        countries, live_fields, seed_fields = self._fetch_countries()
        if not countries:
            raise RuntimeError("Unable to fetch migration data for migration-data-hub analysis")

        top_remit = sorted(countries, key=lambda p: p.remittances_usd, reverse=True)[:5]
        top_emigration = sorted(countries, key=lambda p: p.net_migration)[:5]
        total_remit = sum(p.remittances_usd for p in countries)
        avg_remit_pct = round(statistics.mean(p.remittances_pct_gdp for p in countries), 1)
        most_dependent = max(countries, key=lambda p: p.remittances_pct_gdp)

        pressure_score, dependency_score, pressure_label = self._scores(countries, avg_remit_pct)
        assessment = self._demographic_assessment(countries, top_remit, top_emigration, avg_remit_pct)

        sources = [
            "World Bank Net Migration (SM.POP.NETM)",
            "World Bank Personal Remittances Received (BX.TRF.PWKR.CD.DT)",
            "World Bank Remittances % GDP (BX.TRF.PWKR.DT.GD.ZS)",
            "MPI Migration Data Hub (reference portal)",
        ]
        if seed_fields > live_fields:
            sources.append("Calibrated corridor seed (World Bank partial/unavailable)")

        summary = (
            f"Migration Data Hub scan across {len(countries)} major corridors "
            f"(MPI-referenced, World Bank-sourced). "
            f"Total tracked remittances: ${total_remit / 1e9:.1f}B/yr. "
            f"Top recipient: {top_remit[0].name} (${top_remit[0].remittances_usd / 1e9:.1f}B). "
            f"Average remittance dependency: {avg_remit_pct:.1f}% of GDP. "
            f"Migration pressure: {pressure_label} ({pressure_score})."
        )

        recs = [
            summary,
            f"Migration pressure score: {pressure_score} | Remittance dependency score: {dependency_score}",
            f"Reference portal: {MPI_PORTAL}",
            assessment["remittance_leader"],
            assessment["remittance_dependency"],
            assessment["net_migration"],
            assessment["macro_sensitivity"],
            assessment["labor_supply_note"],
        ]
        for c in top_remit:
            recs.append(
                f"Remittances #{c.rank} {c.name}: ${c.remittances_usd / 1e9:.1f}B/yr "
                f"({c.remittances_pct_gdp:.1f}% of GDP)"
            )

        return MigrationReport(
            resources=MIGRATION_RESOURCES,
            countries=countries,
            top_remittance_recipients=top_remit,
            top_net_emigration=top_emigration,
            total_remittances_usd=total_remit,
            avg_remittance_pct_gdp=avg_remit_pct,
            migration_pressure_score=pressure_score,
            remittance_dependency_score=dependency_score,
            pressure_label=pressure_label,
            expert_summary=summary,
            demographic_assessment=assessment,
            market_signals=self._market_signals(
                top_remit,
                most_dependent,
                avg_remit_pct,
                pressure_score=pressure_score,
                pressure_label=pressure_label,
                dependency_score=dependency_score,
            ),
            recommendations=recs,
            data_sources=sources,
            live_api_fields=live_fields,
            seed_fallback_fields=seed_fields,
        )

    def to_dict(self, report: MigrationReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Migration Data Analyst",
                "portal": MPI_PORTAL,
                "analyzed_at": report.analyzed_at,
                "data_sources": report.data_sources,
                "expert_summary": report.expert_summary,
                "resources_cataloged": len(report.resources),
                "data_degraded": report.seed_fallback_fields > report.live_api_fields,
            },
            "metrics": {
                "migration_pressure_score": report.migration_pressure_score,
                "remittance_dependency_score": report.remittance_dependency_score,
                "pressure_label": report.pressure_label,
                "total_remittances_usd": report.total_remittances_usd,
                "avg_remittance_pct_gdp": report.avg_remittance_pct_gdp,
                "live_api_fields": report.live_api_fields,
                "seed_fallback_fields": report.seed_fallback_fields,
            },
            "resources": report.resources,
            "countries": [
                {
                    "iso3": c.iso3,
                    "name": c.name,
                    "net_migration": c.net_migration,
                    "remittances_usd": c.remittances_usd,
                    "remittances_pct_gdp": c.remittances_pct_gdp,
                    "migrant_stock_pct_pop": c.migrant_stock_pct_pop,
                    "rank": c.rank,
                }
                for c in report.countries
            ],
            "top_remittance_recipients": [c.name for c in report.top_remittance_recipients],
            "top_net_emigration": [c.name for c in report.top_net_emigration],
            "demographic_assessment": report.demographic_assessment,
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        report = self.analyze()
        result = self.to_dict(report)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog_path = output.parent / "migration_data_hub_resources.json"
            catalog_path.write_text(
                json.dumps(report.resources, indent=2),
                encoding="utf-8",
            )
        return result


def run_migration_analysis(
    output: Path | None = None,
    *,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return MigrationDataAnalyst(pipeline_context=pipeline_context).run(output=output)
