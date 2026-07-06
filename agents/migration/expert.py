"""
Migration & Demographics Expert Agent
======================================
Expert cross-border migration analysis derived from the World Bank's net
migration indicator, translated into labor-supply, housing-demand, and
remittance-driven market implications.

Primary data: World Bank Open Data API — indicator SM.POP.NETM ("Net
migration", https://data.worldbank.org/indicator/SM.POP.NETM), a 5-year
period estimate of immigrants minus emigrants for each country. Population
totals (SP.POP.TOTL) are pulled from the same API to normalize migration
into a per-1,000-population rate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agents.base import BaseExpert

HEADERS = {"User-Agent": "Finance-Migration-Expert/1.0 (shaggychunxx@gmail.com)"}
WORLD_BANK_API = "https://api.worldbank.org/v2/country/{codes}/indicator/{indicator}"
NET_MIGRATION_INDICATOR = "SM.POP.NETM"
POPULATION_INDICATOR = "SP.POP.TOTL"
INDICATOR_URL = "https://data.worldbank.org/indicator/SM.POP.NETM"

# ISO3 code -> (country name, region, market grouping)
COUNTRIES: dict[str, dict[str, str]] = {
    "USA": {"name": "United States", "region": "North America", "group": "advanced_receiver"},
    "DEU": {"name": "Germany", "region": "Europe", "group": "advanced_receiver"},
    "GBR": {"name": "United Kingdom", "region": "Europe", "group": "advanced_receiver"},
    "CAN": {"name": "Canada", "region": "North America", "group": "advanced_receiver"},
    "AUS": {"name": "Australia", "region": "Oceania", "group": "advanced_receiver"},
    "ESP": {"name": "Spain", "region": "Europe", "group": "advanced_receiver"},
    "ITA": {"name": "Italy", "region": "Europe", "group": "advanced_receiver"},
    "FRA": {"name": "France", "region": "Europe", "group": "advanced_receiver"},
    "SAU": {"name": "Saudi Arabia", "region": "Middle East", "group": "gulf_labor"},
    "ARE": {"name": "United Arab Emirates", "region": "Middle East", "group": "gulf_labor"},
    "TUR": {"name": "Turkiye", "region": "Middle East", "group": "advanced_receiver"},
    "JPN": {"name": "Japan", "region": "East Asia", "group": "aging_low_migration"},
    "KOR": {"name": "Korea, Rep.", "region": "East Asia", "group": "aging_low_migration"},
    "CHN": {"name": "China", "region": "East Asia", "group": "aging_low_migration"},
    "IND": {"name": "India", "region": "South Asia", "group": "remittance_sender"},
    "MEX": {"name": "Mexico", "region": "Latin America", "group": "remittance_sender"},
    "PHL": {"name": "Philippines", "region": "Southeast Asia", "group": "remittance_sender"},
    "BGD": {"name": "Bangladesh", "region": "South Asia", "group": "remittance_sender"},
    "PAK": {"name": "Pakistan", "region": "South Asia", "group": "remittance_sender"},
    "VNM": {"name": "Vietnam", "region": "Southeast Asia", "group": "remittance_sender"},
    "NGA": {"name": "Nigeria", "region": "Sub-Saharan Africa", "group": "remittance_sender"},
    "EGY": {"name": "Egypt, Arab Rep.", "region": "MENA", "group": "remittance_sender"},
    "UKR": {"name": "Ukraine", "region": "Europe", "group": "conflict_sender"},
    "VEN": {"name": "Venezuela, RB", "region": "Latin America", "group": "conflict_sender"},
    "COL": {"name": "Colombia", "region": "Latin America", "group": "remittance_sender"},
    "BRA": {"name": "Brazil", "region": "Latin America", "group": "balanced"},
    "ZAF": {"name": "South Africa", "region": "Sub-Saharan Africa", "group": "balanced"},
    "POL": {"name": "Poland", "region": "Europe", "group": "balanced"},
}

# Approximate net-migration (persons, latest available 5-yr World Bank
# period) and total population, used only when the live API is
# unreachable so the agent still returns a usable, labeled estimate.
PROXY_NET_MIGRATION: dict[str, dict[str, Any]] = {
    "USA": {"net_migration": 4_620_000, "year": 2022, "population": 333_000_000},
    "DEU": {"net_migration": 2_400_000, "year": 2022, "population": 83_800_000},
    "GBR": {"net_migration": 1_500_000, "year": 2022, "population": 67_700_000},
    "CAN": {"net_migration": 1_450_000, "year": 2022, "population": 38_900_000},
    "AUS": {"net_migration": 900_000, "year": 2022, "population": 26_000_000},
    "ESP": {"net_migration": 750_000, "year": 2022, "population": 47_600_000},
    "ITA": {"net_migration": 400_000, "year": 2022, "population": 59_000_000},
    "FRA": {"net_migration": 350_000, "year": 2022, "population": 67_900_000},
    "SAU": {"net_migration": 1_900_000, "year": 2022, "population": 36_400_000},
    "ARE": {"net_migration": 900_000, "year": 2022, "population": 9_400_000},
    "TUR": {"net_migration": 1_800_000, "year": 2022, "population": 85_300_000},
    "JPN": {"net_migration": 150_000, "year": 2022, "population": 124_500_000},
    "KOR": {"net_migration": 200_000, "year": 2022, "population": 51_700_000},
    "CHN": {"net_migration": -650_000, "year": 2022, "population": 1_412_000_000},
    "IND": {"net_migration": -2_400_000, "year": 2022, "population": 1_417_000_000},
    "MEX": {"net_migration": -450_000, "year": 2022, "population": 127_500_000},
    "PHL": {"net_migration": -800_000, "year": 2022, "population": 115_600_000},
    "BGD": {"net_migration": -1_600_000, "year": 2022, "population": 171_000_000},
    "PAK": {"net_migration": -1_200_000, "year": 2022, "population": 235_800_000},
    "VNM": {"net_migration": -300_000, "year": 2022, "population": 98_900_000},
    "NGA": {"net_migration": -450_000, "year": 2022, "population": 218_500_000},
    "EGY": {"net_migration": -450_000, "year": 2022, "population": 111_200_000},
    "UKR": {"net_migration": -3_500_000, "year": 2022, "population": 36_700_000},
    "VEN": {"net_migration": -900_000, "year": 2022, "population": 28_300_000},
    "COL": {"net_migration": -250_000, "year": 2022, "population": 52_200_000},
    "BRA": {"net_migration": -50_000, "year": 2022, "population": 216_400_000},
    "ZAF": {"net_migration": 100_000, "year": 2022, "population": 60_400_000},
    "POL": {"net_migration": 250_000, "year": 2022, "population": 37_700_000},
}

RECEIVER_ABS_THRESHOLD = 300_000
SENDER_ABS_THRESHOLD = -300_000


@dataclass
class CountryMigration:
    iso3: str
    name: str
    region: str
    group: str
    net_migration: float
    year: int | None
    population: float | None
    net_migration_per_1000: float | None
    classification: str


@dataclass
class MigrationAssessment:
    dominant_pattern: str
    top_receivers: list[str]
    top_senders: list[str]
    labor_supply_signal: str
    housing_demand_signal: str
    remittance_signal: str
    gulf_labor_signal: str
    aging_workforce_signal: str
    aging_labor_scarcity: bool = False


@dataclass
class MigrationReport:
    countries: list[CountryMigration]
    assessment: MigrationAssessment
    global_receivers_total: float
    global_senders_total: float
    migration_intensity_score: float
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MigrationExpert(BaseExpert):
    """Expert migration analyst — World Bank net migration to market implications."""

    def __init__(self, use_live: bool = True) -> None:
        super().__init__()
        self.use_live = use_live

    @staticmethod
    def _fetch_indicator(codes: list[str], indicator: str) -> dict[str, tuple[float, int]]:
        url = WORLD_BANK_API.format(codes=";".join(codes), indicator=indicator)
        resp = requests.get(
            url,
            params={"format": "json", "per_page": 2000, "mrnev": 1},
            headers=HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
            return {}
        values: dict[str, tuple[float, int]] = {}
        for row in payload[1]:
            iso3 = row.get("countryiso3code")
            value = row.get("value")
            date = row.get("date")
            if not iso3 or value is None:
                continue
            try:
                values[iso3] = (float(value), int(date))
            except (TypeError, ValueError):
                continue
        return values

    def _fetch_live(self) -> tuple[list[CountryMigration], list[str]] | None:
        codes = list(COUNTRIES.keys())
        try:
            migration = self._fetch_indicator(codes, NET_MIGRATION_INDICATOR)
            if not migration:
                return None
            population = self._fetch_indicator(codes, POPULATION_INDICATOR)
        except Exception:
            return None

        countries: list[CountryMigration] = []
        for iso3, meta in COUNTRIES.items():
            if iso3 not in migration:
                continue
            net_value, year = migration[iso3]
            pop_value = population.get(iso3, (None, None))[0]
            countries.append(self._build_country(iso3, meta, net_value, year, pop_value))

        if not countries:
            return None
        return countries, ["World Bank Open Data API (SM.POP.NETM, SP.POP.TOTL)"]

    @staticmethod
    def _classify(net_migration: float) -> str:
        if net_migration >= RECEIVER_ABS_THRESHOLD:
            return "Major receiver"
        if net_migration <= SENDER_ABS_THRESHOLD:
            return "Major sender"
        return "Balanced / marginal"

    @classmethod
    def _build_country(
        cls,
        iso3: str,
        meta: dict[str, str],
        net_migration: float,
        year: int | None,
        population: float | None,
    ) -> CountryMigration:
        per_1000 = (
            round(net_migration / population * 1000, 3)
            if population is not None and population > 0 else None
        )
        return CountryMigration(
            iso3=iso3,
            name=meta["name"],
            region=meta["region"],
            group=meta["group"],
            net_migration=net_migration,
            year=year,
            population=population,
            net_migration_per_1000=per_1000,
            classification=cls._classify(net_migration),
        )

    def _proxy_data(self) -> tuple[list[CountryMigration], list[str]]:
        countries = [
            self._build_country(
                iso3,
                COUNTRIES[iso3],
                float(row["net_migration"]),
                int(row["year"]),
                float(row["population"]),
            )
            for iso3, row in PROXY_NET_MIGRATION.items()
        ]
        return countries, ["Calibrated net-migration proxy dataset (World Bank API unavailable)"]

    def _fetch_countries(self) -> tuple[list[CountryMigration], list[str]]:
        if self.use_live:
            live = self._fetch_live()
            if live:
                return live
        return self._proxy_data()

    @staticmethod
    def _assess(countries: list[CountryMigration]) -> MigrationAssessment:
        receivers = sorted(
            (c for c in countries if c.classification == "Major receiver"),
            key=lambda c: c.net_migration,
            reverse=True,
        )
        senders = sorted(
            (c for c in countries if c.classification == "Major sender"),
            key=lambda c: c.net_migration,
        )

        dominant = (
            f"{receivers[0].name} leads net inflows ({receivers[0].net_migration:,.0f})"
            if receivers else "No dominant receiving economy in current sample"
        )

        advanced_receivers = [c for c in receivers if c.group == "advanced_receiver"]
        housing_signal = (
            f"Sustained net inflows to {', '.join(c.name for c in advanced_receivers[:3])} "
            "support household formation, rental demand and labor supply"
            if advanced_receivers else "No strong advanced-economy inflow signal"
        )

        labor_signal = (
            f"{len(receivers)} economies show net labor-supply expansion via migration"
            if receivers else "Limited net labor-supply expansion detected"
        )

        remittance_senders = [c for c in senders if c.group == "remittance_sender"]
        remittance_signal = (
            f"Large diaspora outflows from {', '.join(c.name for c in remittance_senders[:3])} "
            "sustain remittance inflows supporting home-country consumption and currencies"
            if remittance_senders else "No significant remittance-corridor signal"
        )

        gulf = [c for c in receivers if c.group == "gulf_labor"]
        gulf_signal = (
            f"{', '.join(c.name for c in gulf)} net inflows reflect labor migration into "
            "construction/energy/logistics buildout"
            if gulf else "No elevated Gulf labor-migration signal"
        )

        aging = [c for c in countries if c.group == "aging_low_migration"]
        weak_aging_inflow = [c for c in aging if c.classification != "Major receiver"]
        aging_signal = (
            f"{', '.join(c.name for c in weak_aging_inflow)} combine population aging with "
            "muted migrant inflows — structural labor-scarcity/automation tailwind"
            if weak_aging_inflow else "Aging economies currently offsetting demographics via migration"
        )

        return MigrationAssessment(
            dominant_pattern=dominant,
            top_receivers=[c.name for c in receivers[:5]],
            top_senders=[c.name for c in senders[:5]],
            labor_supply_signal=labor_signal,
            housing_demand_signal=housing_signal,
            remittance_signal=remittance_signal,
            gulf_labor_signal=gulf_signal,
            aging_workforce_signal=aging_signal,
            aging_labor_scarcity=bool(weak_aging_inflow),
        )

    @staticmethod
    def _migration_intensity(countries: list[CountryMigration]) -> float:
        if not countries:
            return 0.0
        rates = [abs(c.net_migration_per_1000) for c in countries if c.net_migration_per_1000 is not None]
        if not rates:
            return 0.0
        return round(min(1.0, (sum(rates) / len(rates)) / 15.0), 4)

    def _expert_summary(
        self,
        assessment: MigrationAssessment,
        countries: list[CountryMigration],
        intensity: float,
    ) -> str:
        return (
            f"{assessment.dominant_pattern}. "
            f"Top receivers: {', '.join(assessment.top_receivers) or 'none'}. "
            f"Top senders: {', '.join(assessment.top_senders) or 'none'}. "
            f"Migration intensity index {intensity:.2f} across {len(countries)} economies. "
            f"Housing/labor: {assessment.housing_demand_signal}. "
            f"Remittances: {assessment.remittance_signal}. "
            f"Gulf labor migration: {assessment.gulf_labor_signal}. "
            f"Aging workforce: {assessment.aging_workforce_signal}."
        )

    @staticmethod
    def _market_signals(assessment: MigrationAssessment, countries: list[CountryMigration]) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        by_name = {c.name: c for c in countries}

        def group_of(name: str) -> str:
            country = by_name.get(name)
            return country.group if country else ""

        advanced = [n for n in assessment.top_receivers if group_of(n) == "advanced_receiver"]
        if advanced:
            signals.append({
                "sector": "Housing & Domestic Consumption",
                "tickers": ["ITB", "XHB", "HD", "LOW"],
                "bias": "BULLISH",
                "reason": assessment.housing_demand_signal,
            })

        if assessment.top_senders:
            signals.append({
                "sector": "Global Remittances & Cross-Border Payments",
                "tickers": ["WU", "EEFT", "MA", "V"],
                "bias": "BULLISH",
                "reason": assessment.remittance_signal,
            })
            signals.append({
                "sector": "EM Consumer (Remittance-Supported)",
                "tickers": ["EWW", "INDA", "EPOL"],
                "bias": "NEUTRAL",
                "reason": "Remittance inflows cushion household spending in sending economies",
            })

        gulf_names = [n for n in assessment.top_receivers if group_of(n) == "gulf_labor"]
        if gulf_names:
            signals.append({
                "sector": "Gulf Infrastructure & Construction",
                "tickers": ["KSA", "UAE"],
                "bias": "BULLISH",
                "reason": assessment.gulf_labor_signal,
            })

        if assessment.aging_labor_scarcity:
            signals.append({
                "sector": "Automation & Labor Productivity",
                "tickers": ["ROBO", "ISRG", "ROK"],
                "bias": "NEUTRAL",
                "reason": assessment.aging_workforce_signal,
            })

        conflict_senders = [c for c in countries if c.group == "conflict_sender" and c.classification == "Major sender"]
        if conflict_senders:
            signals.append({
                "sector": "Frontier/Conflict-Exposed Currencies",
                "tickers": [],
                "bias": "BEARISH",
                "reason": (
                    "Large forced-migration outflows from "
                    f"{', '.join(c.name for c in conflict_senders)} signal acute economic disruption"
                ),
            })

        if not signals:
            signals.append({
                "sector": "Global Migration",
                "tickers": ["SPY"],
                "bias": "NEUTRAL",
                "reason": "No pronounced migration-driven market signal in current sample",
            })
        return signals

    @staticmethod
    def _recommendations(assessment: MigrationAssessment, countries: list[CountryMigration], intensity: float) -> list[str]:
        recs = [
            f"Migration intensity index {intensity:.2f} — {assessment.dominant_pattern}",
            f"Housing/labor supply: {assessment.housing_demand_signal}",
            f"Remittance corridors: {assessment.remittance_signal}",
            f"Gulf labor migration: {assessment.gulf_labor_signal}",
            f"Aging workforce: {assessment.aging_workforce_signal}",
        ]
        for c in sorted(countries, key=lambda c: abs(c.net_migration), reverse=True)[:6]:
            rate = f", {c.net_migration_per_1000:+.2f}/1,000 pop" if c.net_migration_per_1000 is not None else ""
            recs.append(
                f"{c.name} ({c.region}): net migration {c.net_migration:+,.0f}{rate} — {c.classification}"
            )
        return recs

    def analyze(self) -> MigrationReport:
        countries, sources = self._fetch_countries()
        assessment = self._assess(countries)
        intensity = self._migration_intensity(countries)
        receivers_total = sum(c.net_migration for c in countries if c.net_migration > 0)
        senders_total = sum(c.net_migration for c in countries if c.net_migration < 0)
        summary = self._expert_summary(assessment, countries, intensity)
        signals = self._market_signals(assessment, countries)
        recs = self._recommendations(assessment, countries, intensity)

        return MigrationReport(
            countries=countries,
            assessment=assessment,
            global_receivers_total=receivers_total,
            global_senders_total=senders_total,
            migration_intensity_score=intensity,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_sources=sources,
        )

    def to_dict(self, report: MigrationReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Migration & Demographics Expert",
                "analyzed_at": report.analyzed_at,
                "expert_summary": report.expert_summary,
                "countries_analyzed": len(report.countries),
                "data_sources": report.data_sources,
                "temperature": self.temperature,
                "indicator": {
                    "id": NET_MIGRATION_INDICATOR,
                    "name": "Net migration",
                    "url": INDICATOR_URL,
                },
            },
            "assessment": {
                "dominant_pattern": a.dominant_pattern,
                "top_receivers": a.top_receivers,
                "top_senders": a.top_senders,
                "labor_supply_signal": a.labor_supply_signal,
                "housing_demand_signal": a.housing_demand_signal,
                "remittance_signal": a.remittance_signal,
                "gulf_labor_signal": a.gulf_labor_signal,
                "aging_workforce_signal": a.aging_workforce_signal,
                "aging_labor_scarcity": a.aging_labor_scarcity,
            },
            "countries": [
                {
                    "iso3": c.iso3,
                    "name": c.name,
                    "region": c.region,
                    "group": c.group,
                    "net_migration": c.net_migration,
                    "year": c.year,
                    "population": c.population,
                    "net_migration_per_1000": c.net_migration_per_1000,
                    "classification": c.classification,
                }
                for c in sorted(report.countries, key=lambda c: c.net_migration, reverse=True)
            ],
            "metrics": {
                "migration_intensity_score": report.migration_intensity_score,
                "global_receivers_total": report.global_receivers_total,
                "global_senders_total": report.global_senders_total,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        report = self.analyze()
        result = self.to_dict(report)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog_path = output.parent / "migration_corridors.json"
            catalog = {
                "indicator": {
                    "id": NET_MIGRATION_INDICATOR,
                    "name": "Net migration",
                    "url": INDICATOR_URL,
                },
                "top_receivers": report.assessment.top_receivers,
                "top_senders": report.assessment.top_senders,
                "countries": [
                    {"iso3": c.iso3, "name": c.name, "classification": c.classification}
                    for c in report.countries
                ],
            }
            catalog_path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
        return result


def run_migration_analysis(output: Path | None = None) -> dict[str, Any]:
    return MigrationExpert().run(output=output)
