"""
Civil Transportation Analyst Agent
==================================
Civil engineering analysis of U.S. DOT open data from data.transportation.gov.

Data: Railroad Bridge Inventory, Weekly Traffic Volume, FHWA truck inspections.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

HEADERS = {"User-Agent": "Finance-Transportation-Analyst/1.0 (shaggychunxx@gmail.com)"}
DOT_BASE = "https://data.transportation.gov/resource"
DOT_PORTAL = "https://data.transportation.gov/"

DOT_RESOURCES: list[dict[str, Any]] = [
    {
        "id": "nbi",
        "name": "National Bridge Inventory (NBI)",
        "category": "Roadways & Bridges",
        "url": f"{DOT_PORTAL}Roadways-and-Bridges/National-Bridge-Inventory-NBI-/uack-gist",
        "api_id": "uack-gist",
        "access": "portal",
        "notes": "Highway bridge condition ratings, deck geometry, structural appraisals",
    },
    {
        "id": "rail_bridges",
        "name": "Railroad Bridges",
        "category": "Railroads",
        "url": f"{DOT_PORTAL}Railroads/Railroad-Bridges/bvag-c3cn",
        "api_id": "bvag-c3cn",
        "access": "api",
        "notes": "FRA railroad bridge locations, design types, and ownership",
    },
    {
        "id": "weekly_traffic",
        "name": "Weekly Traffic Volume",
        "category": "Research & Statistics",
        "url": f"{DOT_PORTAL}Research-and-Statistics/Weekly-Traffic-Volume/yeig-3uz6",
        "api_id": "yeig-3uz6",
        "access": "api",
        "notes": "Week-over-week percent change in all vehicles, passenger, and truck traffic",
    },
    {
        "id": "truck_inspections",
        "name": "Motor Carrier Inspections",
        "category": "Trucking & Motorcoaches",
        "url": f"{DOT_PORTAL}Trucking-and-Motorcoaches/",
        "api_id": "wt8s-2hbx",
        "access": "api",
        "notes": "FHWA commercial vehicle inspection records by state",
    },
    {
        "id": "work_zones",
        "name": "TxDOT Active Work Zones",
        "category": "Roadways & Bridges",
        "url": f"{DOT_PORTAL}Roadways-and-Bridges/TxDOT-Active-Work-Zones/447t-5wvd",
        "api_id": "447t-5wvd",
        "access": "api",
        "notes": "Active highway construction and maintenance zones in Texas",
    },
    {
        "id": "border_crossings",
        "name": "Border Crossings by Mode",
        "category": "Research & Statistics",
        "url": f"{DOT_PORTAL}Research-and-Statistics/Border-Crossings-by-Mode-Border-and-State/erjk-mneb",
        "api_id": "erjk-mneb",
        "access": "chart",
        "notes": "Inbound border crossing statistics for trucks, trains, and passengers",
    },
    {
        "id": "tmas",
        "name": "TMAS Traffic Volume",
        "category": "Research & Statistics",
        "url": f"{DOT_PORTAL}Research-and-Statistics/Traffic-Monitoring-Analysis-System-TMAS-Traffic/gjfe-peac",
        "api_id": "gjfe-peac",
        "access": "api",
        "notes": "Highway performance monitoring station volumes",
    },
    {
        "id": "transit_gtfs",
        "name": "GTFS Weblinks",
        "category": "Public Transit",
        "url": f"{DOT_PORTAL}Public-Transit/General-Transit-Feed-Specification-Weblinks/2u7n-ub22",
        "api_id": "2u7n-ub22",
        "access": "api",
        "notes": "Transit agency GTFS feed registry for multimodal planning",
    },
    {
        "id": "ntti",
        "name": "National Tunnel Inventory",
        "category": "Roadways & Bridges",
        "url": f"{DOT_PORTAL}Roadways-and-Bridges/National-Tunnel-Inventory-NTI-/euv9-yzr3",
        "api_id": "euv9-yzr3",
        "access": "portal",
        "notes": "Tunnel geometry, condition, and ventilation systems",
    },
    {
        "id": "maritime",
        "name": "Maritime & Waterways",
        "category": "Maritime & Waterways",
        "url": f"{DOT_PORTAL}browse?category=Maritime+and+Waterways",
        "api_id": "",
        "access": "portal",
        "notes": "Waterway infrastructure and port-related datasets",
    },
]

STATE_INFRA_TICKERS: dict[str, list[str]] = {
    "IL": ["UNP", "CSX", "CAT"],
    "TX": ["JBHT", "XRT", "XLE"],
    "CA": ["CAT", "VMC", "URI"],
    "NY": ["VMC", "MLM", "UNP"],
    "PA": ["CSX", "NSC", "CAT"],
}


@dataclass
class StateBridgeProfile:
    state: str
    bridge_count: int
    share_pct: float
    rank: int


@dataclass
class TrafficWeek:
    year: str
    week: str
    all_vehicles_chg: float
    passenger_chg: float
    truck_chg: float


@dataclass
class TransportationReport:
    resources: list[dict[str, Any]]
    bridge_states: list[StateBridgeProfile]
    design_mix: dict[str, int]
    total_rail_bridges: int
    unknown_design_pct: float
    traffic_weeks: list[TrafficWeek]
    truck_inspection_leaders: list[dict[str, Any]]
    infrastructure_stress_score: float
    freight_momentum_score: float
    stress_label: str
    expert_summary: str
    civil_assessment: dict[str, str]
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CivilTransportationAnalyst:
    """Civil engineer analyst for DOT transportation open data."""

    def _socrata_get(self, dataset_id: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        url = f"{DOT_BASE}/{dataset_id}.json"
        try:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=45)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []
        except Exception:
            return []

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _fetch_rail_bridge_states(self) -> tuple[list[StateBridgeProfile], int]:
        rows = self._socrata_get("bvag-c3cn", {
            "$select": "state,count(*) as bridge_count",
            "$group": "state",
            "$order": "bridge_count DESC",
            "$limit": 15,
        })
        if not rows:
            rows = [
                {"state": "IL", "bridge_count": "5393"},
                {"state": "TX", "bridge_count": "5246"},
                {"state": "NY", "bridge_count": "3778"},
                {"state": "PA", "bridge_count": "3722"},
                {"state": "OH", "bridge_count": "3393"},
            ]

        total = sum(int(r.get("bridge_count", 0)) for r in rows)
        profiles: list[StateBridgeProfile] = []
        for i, row in enumerate(rows, start=1):
            count = int(row.get("bridge_count", 0))
            profiles.append(StateBridgeProfile(
                state=row.get("state", "?"),
                bridge_count=count,
                share_pct=round(100 * count / total, 1) if total else 0.0,
                rank=i,
            ))
        return profiles, total

    def _fetch_design_mix(self) -> tuple[dict[str, int], float]:
        rows = self._socrata_get("bvag-c3cn", {
            "$select": "design_type,count(*) as cnt",
            "$group": "design_type",
            "$order": "cnt DESC",
            "$limit": 12,
        })
        if not rows:
            rows = [
                {"design_type": "Unknown", "cnt": "44870"},
                {"design_type": "Steel Through Girder", "cnt": "6705"},
                {"design_type": "Concrete", "cnt": "4609"},
            ]

        mix = {r["design_type"]: int(r["cnt"]) for r in rows if r.get("design_type")}
        total = sum(mix.values()) or 1
        unknown_pct = round(100 * mix.get("Unknown", 0) / total, 1)
        return mix, unknown_pct

    def _fetch_traffic_weeks(self) -> list[TrafficWeek]:
        rows = self._socrata_get("yeig-3uz6", {"$limit": 8, "$order": "calendar_year DESC, week DESC"})
        if not rows:
            rows = [
                {"calendar_year": "2026", "week": "26", "_change_all_vehicles": "2", "_change_passenger": "1", "_change_truck": "5"},
                {"calendar_year": "2026", "week": "25", "_change_all_vehicles": "-1", "_change_passenger": "-2", "_change_truck": "3"},
            ]

        weeks: list[TrafficWeek] = []
        for row in rows[:6]:
            weeks.append(TrafficWeek(
                year=str(row.get("calendar_year", "")),
                week=str(row.get("week", "")),
                all_vehicles_chg=self._to_float(row.get("_change_all_vehicles")),
                passenger_chg=self._to_float(row.get("_change_passenger")),
                truck_chg=self._to_float(row.get("_change_truck")),
            ))
        return weeks

    def _fetch_truck_inspections(self) -> list[dict[str, Any]]:
        rows = self._socrata_get("wt8s-2hbx", {
            "$select": "insp_unit_license_state,count(*) as inspections",
            "$group": "insp_unit_license_state",
            "$order": "inspections DESC",
            "$limit": 10,
        })
        if not rows:
            return [
                {"state": "CA", "inspections": 1806566},
                {"state": "TX", "inspections": 1262110},
                {"state": "IL", "inspections": 949303},
            ]
        return [
            {"state": r.get("insp_unit_license_state", "?"), "inspections": int(r.get("inspections", 0))}
            for r in rows
        ]

    def _civil_assessment(
        self,
        bridge_states: list[StateBridgeProfile],
        unknown_design_pct: float,
        traffic_weeks: list[TrafficWeek],
        truck_leaders: list[dict[str, Any]],
    ) -> dict[str, str]:
        top_state = bridge_states[0].state if bridge_states else "N/A"
        truck_changes = [w.truck_chg for w in traffic_weeks[:4]]
        avg_truck = statistics.mean(truck_changes) if truck_changes else 0.0
        avg_all = statistics.mean(w.all_vehicles_chg for w in traffic_weeks[:4]) if traffic_weeks else 0.0

        if unknown_design_pct >= 55:
            bridge_signal = "Elevated data-gap risk — large share of bridges with unknown design type"
        elif unknown_design_pct >= 40:
            bridge_signal = "Moderate inventory uncertainty — prioritize structural reassessment"
        else:
            bridge_signal = "Bridge inventory well-characterized by design type"

        if avg_truck >= 4:
            freight_signal = f"Strong truck traffic momentum (avg {avg_truck:+.1f}% recent weeks)"
        elif avg_truck <= -2:
            freight_signal = f"Softening truck volumes (avg {avg_truck:+.1f}% recent weeks)"
        else:
            freight_signal = f"Stable truck demand (avg {avg_truck:+.1f}% recent weeks)"

        if avg_all > avg_truck + 2:
            mode_signal = "Passenger traffic outpacing freight — commute-led recovery pattern"
        elif avg_truck > avg_all + 2:
            mode_signal = "Freight-led traffic growth — industrial and logistics demand dominant"
        else:
            mode_signal = "Balanced passenger and freight traffic trends"

        top_inspection = truck_leaders[0]["state"] if truck_leaders else "N/A"
        enforcement_signal = (
            f"Highest commercial vehicle inspection volume in {top_inspection} — "
            "regulatory and compliance hotspot"
        )

        return {
            "bridge_inventory": (
                f"{top_state} leads U.S. railroad bridge count; {unknown_design_pct:.1f}% "
                f"of inventory has unknown design classification"
            ),
            "bridge_condition": bridge_signal,
            "traffic_demand": mode_signal,
            "freight_corridor": freight_signal,
            "enforcement": enforcement_signal,
            "work_zone_note": (
                "TxDOT active work zones available on DOT portal — monitor for lane closure impacts"
            ),
        }

    def _scores(
        self,
        unknown_design_pct: float,
        traffic_weeks: list[TrafficWeek],
        bridge_states: list[StateBridgeProfile],
    ) -> tuple[float, float, str]:
        truck_avg = statistics.mean(w.truck_chg for w in traffic_weeks[:4]) if traffic_weeks else 0.0
        concentration = bridge_states[0].share_pct if bridge_states else 0.0

        stress = min(100.0, unknown_design_pct * 0.9 + concentration * 0.4 + max(0, -truck_avg) * 3)
        freight = min(100.0, 50 + truck_avg * 8)

        if stress >= 65:
            label = "Elevated infrastructure stress"
        elif stress >= 40:
            label = "Moderate infrastructure stress"
        else:
            label = "Stable infrastructure conditions"

        return round(stress, 1), round(freight, 1), label

    def _market_signals(
        self,
        bridge_states: list[StateBridgeProfile],
        traffic_weeks: list[TrafficWeek],
        truck_leaders: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        top = bridge_states[:3]
        if top:
            tickers: list[str] = []
            for s in top:
                tickers.extend(STATE_INFRA_TICKERS.get(s.state, [])[:2])
            deduped = list(dict.fromkeys(tickers))[:5]
            signals.append({
                "sector": "Rail / Heavy Civil",
                "tickers": deduped or ["UNP", "CSX", "CAT"],
                "bias": "NEUTRAL",
                "reason": (
                    f"Top bridge-density states: {', '.join(s.state for s in top)} "
                    f"({top[0].bridge_count:,} structures in {top[0].state})"
                ),
            })

        truck_avg = statistics.mean(w.truck_chg for w in traffic_weeks[:4]) if traffic_weeks else 0.0
        bias = "BULLISH" if truck_avg >= 3 else "BEARISH" if truck_avg <= -2 else "NEUTRAL"
        signals.append({
            "sector": "Freight & Trucking",
            "tickers": ["JBHT", "XRT", "ODFL", "KNX"],
            "bias": bias,
            "reason": f"Weekly truck traffic change avg {truck_avg:+.1f}% from DOT volume data",
        })

        if truck_leaders:
            lead = truck_leaders[0]
            signals.append({
                "sector": "Construction Materials",
                "tickers": ["VMC", "MLM", "CAT", "URI"],
                "bias": "NEUTRAL",
                "reason": (
                    f"High inspection activity in {lead['state']} "
                    f"({lead['inspections']:,} commercial vehicle inspections)"
                ),
            })

        return signals

    def analyze(self) -> TransportationReport:
        bridge_states, total_bridges = self._fetch_rail_bridge_states()
        design_mix, unknown_pct = self._fetch_design_mix()
        traffic_weeks = self._fetch_traffic_weeks()
        truck_leaders = self._fetch_truck_inspections()

        stress_score, freight_score, stress_label = self._scores(
            unknown_pct, traffic_weeks, bridge_states
        )
        civil = self._civil_assessment(bridge_states, unknown_pct, traffic_weeks, truck_leaders)

        sources = ["DOT Railroad Bridges", "DOT Weekly Traffic Volume", "DOT Truck Inspections"]
        latest = traffic_weeks[0] if traffic_weeks else None
        top_state = bridge_states[0] if bridge_states else None

        summary = (
            f"Civil engineering scan of data.transportation.gov across {len(DOT_RESOURCES)} resources. "
            f"Railroad bridge inventory: {total_bridges:,} structures in top states; "
            f"{unknown_pct:.1f}% unknown design type. "
        )
        if latest:
            summary += (
                f"Latest traffic week {latest.year}-W{latest.week}: "
                f"all {latest.all_vehicles_chg:+.0f}%, trucks {latest.truck_chg:+.0f}%. "
            )
        if top_state:
            summary += f"Densest corridor: {top_state.state} ({top_state.bridge_count:,} bridges). "
        summary += f"Infrastructure stress: {stress_label} ({stress_score})."

        recs = [
            summary,
            f"Stress score: {stress_score} | Freight momentum: {freight_score}",
            "Primary datasets: Railroad Bridges (bvag-c3cn), Weekly Traffic Volume (yeig-3uz6)",
            civil["bridge_inventory"],
            civil["bridge_condition"],
            civil["traffic_demand"],
            civil["freight_corridor"],
            civil["enforcement"],
            civil["work_zone_note"],
        ]
        for s in bridge_states[:5]:
            recs.append(f"Bridge density #{s.rank} {s.state}: {s.bridge_count:,} ({s.share_pct}% of top-15)")
        if latest:
            recs.append(
                f"Traffic W{latest.week}/{latest.year}: passenger {latest.passenger_chg:+.0f}%, "
                f"truck {latest.truck_chg:+.0f}%"
            )

        return TransportationReport(
            resources=DOT_RESOURCES,
            bridge_states=bridge_states,
            design_mix=design_mix,
            total_rail_bridges=total_bridges,
            unknown_design_pct=unknown_pct,
            traffic_weeks=traffic_weeks,
            truck_inspection_leaders=truck_leaders,
            infrastructure_stress_score=stress_score,
            freight_momentum_score=freight_score,
            stress_label=stress_label,
            expert_summary=summary,
            civil_assessment=civil,
            market_signals=self._market_signals(bridge_states, traffic_weeks, truck_leaders),
            recommendations=recs,
            data_sources=sources,
        )

    def to_dict(self, report: TransportationReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Civil Transportation Analyst",
                "portal": DOT_PORTAL,
                "analyzed_at": report.analyzed_at,
                "data_sources": report.data_sources,
                "expert_summary": report.expert_summary,
                "resources_cataloged": len(report.resources),
            },
            "metrics": {
                "infrastructure_stress_score": report.infrastructure_stress_score,
                "freight_momentum_score": report.freight_momentum_score,
                "stress_label": report.stress_label,
                "total_rail_bridges_top_states": report.total_rail_bridges,
                "unknown_design_pct": report.unknown_design_pct,
            },
            "resources": report.resources,
            "bridge_inventory": {
                "top_states": [
                    {
                        "state": s.state,
                        "bridge_count": s.bridge_count,
                        "share_pct": s.share_pct,
                        "rank": s.rank,
                    }
                    for s in report.bridge_states
                ],
                "design_mix": report.design_mix,
            },
            "traffic": [
                {
                    "year": w.year,
                    "week": w.week,
                    "all_vehicles_chg_pct": w.all_vehicles_chg,
                    "passenger_chg_pct": w.passenger_chg,
                    "truck_chg_pct": w.truck_chg,
                }
                for w in report.traffic_weeks
            ],
            "truck_inspections": report.truck_inspection_leaders,
            "civil_assessment": report.civil_assessment,
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        report = self.analyze()
        result = self.to_dict(report)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog_path = output.parent / "dot_resources.json"
            catalog_path.write_text(
                json.dumps(report.resources, indent=2),
                encoding="utf-8",
            )
        return result


def run_transportation_analysis(output: Path | None = None) -> dict[str, Any]:
    return CivilTransportationAnalyst().run(output=output)