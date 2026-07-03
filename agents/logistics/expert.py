"""
Logistics Expert Agent
======================
Expert analysis of global shipping lanes, port activity, and supply-chain stress.

Primary data: MarineTraffic AIS API (optional key) with calibrated corridor proxies.
Dashboard: https://www.marinetraffic.com/
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

AIS_EXPORT_URL = "https://services.marinetraffic.com/api/exportvessels"
HEADERS = {"User-Agent": "Finance-Logistics-Expert/1.0 (shaggychunxx@gmail.com)"}
PRIMARY_DASHBOARD = (
    "https://www.marinetraffic.com/en/ais/home/centerx:2.7/centery:51.2/zoom:6"
)
PRIMARY_CORRIDOR_ID = "north_sea"

CORRIDORS = {
    "north_sea": {
        "name": "North Sea / English Channel",
        "center": {"lon": 2.7, "lat": 51.2, "zoom": 6},
        "dashboard": "https://www.marinetraffic.com/en/ais/home/centerx:2.7/centery:51.2/zoom:6",
        "expected_vessels": 180,
        "ports": [
            (4.48, 51.92, "Rotterdam"),
            (4.40, 51.23, "Antwerp"),
            (0.45, 51.48, "Thames"),
            (9.97, 53.55, "Hamburg"),
            (1.40, 51.00, "Dover Strait"),
        ],
        "proxy": {
            "total": 195, "tanker": 42, "cargo": 78, "bulk": 28, "container": 65,
            "anchored": 38, "underway": 157, "avg_speed": 11.2,
            "port_proximity": {"Rotterdam": 48, "Antwerp": 31, "Thames": 22, "Hamburg": 14, "Dover Strait": 56},
        },
    },
    "us_west_coast": {
        "name": "US West Coast — LA/Long Beach",
        "center": {"lon": -118.3, "lat": 33.7, "zoom": 8},
        "dashboard": "https://www.marinetraffic.com/en/ais/home/centerx:-118.3/centery:33.7/zoom:8",
        "expected_vessels": 85,
        "ports": [
            (-118.27, 33.75, "Los Angeles"),
            (-118.19, 33.76, "Long Beach"),
            (-122.41, 37.80, "Oakland"),
            (-117.16, 32.71, "San Diego"),
        ],
        "proxy": {
            "total": 92, "tanker": 8, "cargo": 54, "bulk": 6, "container": 48,
            "anchored": 28, "underway": 64, "avg_speed": 8.4,
            "port_proximity": {"Los Angeles": 34, "Long Beach": 41, "Oakland": 12, "San Diego": 5},
        },
    },
    "singapore": {
        "name": "Singapore Strait",
        "center": {"lon": 103.8, "lat": 1.2, "zoom": 8},
        "dashboard": "https://www.marinetraffic.com/en/ais/home/centerx:103.8/centery:1.2/zoom:8",
        "expected_vessels": 120,
        "ports": [
            (103.85, 1.29, "Singapore"),
            (103.40, 3.00, "Port Klang"),
            (104.00, 1.45, "Tanjung Pelepas"),
        ],
        "proxy": {
            "total": 128, "tanker": 36, "cargo": 52, "bulk": 22, "container": 38,
            "anchored": 22, "underway": 106, "avg_speed": 10.8,
            "port_proximity": {"Singapore": 62, "Port Klang": 18, "Tanjung Pelepas": 24},
        },
    },
}


@dataclass
class BoundingBox:
    min_lon: float
    max_lon: float
    min_lat: float
    max_lat: float


@dataclass
class CorridorSnapshot:
    corridor_id: str
    corridor_name: str
    dashboard_url: str
    total_vessels: int
    tanker_count: int
    cargo_count: int
    bulk_count: int
    container_count: int
    anchored_count: int
    underway_count: int
    avg_speed_knots: float
    port_proximity: dict[str, int] = field(default_factory=dict)
    type_breakdown: dict[str, int] = field(default_factory=dict)
    lane_density_score: float = 0.0
    freight_score: float = 0.0
    congestion_score: float = 0.0
    data_source: str = ""


@dataclass
class LogisticsAssessment:
    """Expert logistics read across monitored corridors."""
    chokepoint_risk: str
    container_backlog_signal: str
    bulk_freight_signal: str
    tanker_flow_signal: str
    retail_lead_time_signal: str
    manufacturing_input_signal: str


@dataclass
class LogisticsReport:
    corridors: list[CorridorSnapshot]
    assessment: LogisticsAssessment
    supply_chain_stress_score: float
    freight_momentum_score: float
    congestion_score: float
    stress_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    primary_corridor: CorridorSnapshot | None = None
    marine_traffic_strategies: dict[str, str] = field(default_factory=dict)
    data_sources: list[str] = field(default_factory=list)
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class LogisticsExpert:
    """Expert logistics agent — multi-corridor AIS analysis and supply-chain signals."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("MARINETRAFFIC_API_KEY", "") or self._load_config_key()

    @staticmethod
    def _load_config_key() -> str:
        for cfg in (Path("config.json"), Path(__file__).resolve().parents[2] / "config.json"):
            if not cfg.exists():
                continue
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
                return str(data.get("marinetraffic_api_key", "") or "")
            except Exception:
                continue
        return ""

    @staticmethod
    def center_zoom_to_bbox(lon: float, lat: float, zoom: int) -> BoundingBox:
        view_px = 512
        lon_span = (view_px / 256) * (360 / (2**zoom))
        lat_span = lon_span * 0.65
        cos_lat = max(0.25, math.cos(math.radians(lat)))
        lon_span /= cos_lat
        return BoundingBox(
            min_lon=round(lon - lon_span / 2, 4),
            max_lon=round(lon + lon_span / 2, 4),
            min_lat=round(lat - lat_span / 2, 4),
            max_lat=round(lat + lat_span / 2, 4),
        )

    def _fetch_vessels_api(self, bbox: BoundingBox) -> list[dict[str, Any]]:
        params = {
            "v": 8,
            "timespan": 30,
            "MINLAT": bbox.min_lat,
            "MAXLAT": bbox.max_lat,
            "MINLON": bbox.min_lon,
            "MAXLON": bbox.max_lon,
            "protocol": "jsono",
            "msgtype": "extended",
        }
        url = f"{AIS_EXPORT_URL}/{self.api_key}"
        resp = requests.get(url, params=params, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            return data.get("DATA", data.get("data", [])) or []
        return data if isinstance(data, list) else []

    @staticmethod
    def _haversine_nm(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
        r = 3440.065
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return r * 2 * math.asin(min(1.0, math.sqrt(a)))

    @staticmethod
    def _classify_vessel(row: dict[str, Any]) -> str:
        summary = str(row.get("AIS_TYPE_SUMMARY") or row.get("TYPE_NAME") or "").lower()
        shiptype = str(row.get("SHIPTYPE", ""))
        if "tanker" in summary or shiptype == "8":
            return "tanker"
        if "bulk" in summary:
            return "bulk"
        if "container" in summary or "cargo" in summary or shiptype == "7":
            return "cargo"
        return "other"

    def _build_from_vessels(
        self,
        vessels: list[dict[str, Any]],
        corridor_id: str,
        cfg: dict[str, Any],
        source: str,
    ) -> CorridorSnapshot:
        ports = cfg["ports"]
        type_breakdown: dict[str, int] = {}
        port_proximity: dict[str, int] = {name: 0 for _, _, name in ports}
        speeds: list[float] = []
        tanker = cargo = bulk = container = anchored = underway = 0

        for v in vessels:
            vtype = self._classify_vessel(v)
            type_breakdown[vtype] = type_breakdown.get(vtype, 0) + 1
            if vtype == "tanker":
                tanker += 1
            elif vtype == "bulk":
                bulk += 1
            elif vtype == "cargo":
                cargo += 1
                if "container" in str(v.get("TYPE_NAME", "")).lower():
                    container += 1
            status = str(v.get("STATUS", "0"))
            if status in ("1", "5"):
                anchored += 1
            else:
                underway += 1
            try:
                speed_raw = float(v.get("SPEED", 0) or 0)
                speed_kn = speed_raw / 10.0 if speed_raw > 50 else speed_raw
                if speed_kn > 0:
                    speeds.append(speed_kn)
            except (TypeError, ValueError):
                pass
            try:
                vlon, vlat = float(v["LON"]), float(v["LAT"])
                for plon, plat, pname in ports:
                    if self._haversine_nm(vlon, vlat, plon, plat) <= 25:
                        port_proximity[pname] += 1
            except (KeyError, TypeError, ValueError):
                pass

        total = len(vessels)
        avg_speed = round(sum(speeds) / len(speeds), 1) if speeds else 0.0
        snap = CorridorSnapshot(
            corridor_id=corridor_id,
            corridor_name=cfg["name"],
            dashboard_url=cfg["dashboard"],
            total_vessels=total,
            tanker_count=tanker,
            cargo_count=cargo,
            bulk_count=bulk,
            container_count=container or cargo,
            anchored_count=anchored,
            underway_count=underway,
            avg_speed_knots=avg_speed,
            port_proximity=port_proximity,
            type_breakdown=type_breakdown,
            data_source=source,
        )
        self._score_corridor(snap, cfg["expected_vessels"])
        return snap

    def _build_from_proxy(self, corridor_id: str, cfg: dict[str, Any], source: str) -> CorridorSnapshot:
        p = cfg["proxy"]
        snap = CorridorSnapshot(
            corridor_id=corridor_id,
            corridor_name=cfg["name"],
            dashboard_url=cfg["dashboard"],
            total_vessels=p["total"],
            tanker_count=p["tanker"],
            cargo_count=p["cargo"],
            bulk_count=p["bulk"],
            container_count=p["container"],
            anchored_count=p["anchored"],
            underway_count=p["underway"],
            avg_speed_knots=p["avg_speed"],
            port_proximity=dict(p["port_proximity"]),
            type_breakdown={
                "cargo": p["cargo"], "tanker": p["tanker"], "bulk": p["bulk"],
            },
            data_source=source,
        )
        self._score_corridor(snap, cfg["expected_vessels"])
        return snap

    @staticmethod
    def _score_corridor(snap: CorridorSnapshot, expected: int) -> None:
        total = max(snap.total_vessels, 1)
        density_ratio = snap.total_vessels / expected
        snap.lane_density_score = round(max(0.15, min(1.0, 0.35 + density_ratio * 0.45)), 4)
        bulk_w = snap.bulk_count / total
        cargo_w = snap.cargo_count / total
        underway = snap.underway_count / total
        snap.freight_score = round(max(0.2, min(1.0, 0.40 + bulk_w * 0.35 + cargo_w * 0.15 + underway * 0.10)), 4)
        anchored = snap.anchored_count / total
        slow = 1.0 if snap.avg_speed_knots < 8 else 0.0
        snap.congestion_score = round(max(0.15, min(1.0, 0.25 + anchored * 0.45 + slow * 0.30)), 4)

    def _analyze_corridor(self, corridor_id: str, cfg: dict[str, Any]) -> CorridorSnapshot:
        center = cfg["center"]
        bbox = self.center_zoom_to_bbox(center["lon"], center["lat"], center["zoom"])

        if self.api_key:
            try:
                vessels = self._fetch_vessels_api(bbox)
                if vessels:
                    return self._build_from_vessels(
                        vessels, corridor_id, cfg, "MarineTraffic AIS API"
                    )
            except Exception:
                pass

        return self._build_from_proxy(
            corridor_id, cfg,
            "Corridor proxy (set marinetraffic_api_key in config.json for live AIS)",
        )

    def _logistics_assessment(self, corridors: list[CorridorSnapshot]) -> LogisticsAssessment:
        us_wc = next((c for c in corridors if c.corridor_id == "us_west_coast"), None)
        north_sea = next((c for c in corridors if c.corridor_id == "north_sea"), None)
        singapore = next((c for c in corridors if c.corridor_id == "singapore"), None)

        chokepoint = "normal global routing"
        if north_sea and north_sea.congestion_score >= 0.60:
            chokepoint = "English Channel / Dover congestion — EU-UK trade delay risk"
        if singapore and singapore.lane_density_score >= 0.75:
            chokepoint = "Singapore Strait high density — Asia-Europe chokepoint active"

        container_backlog = "normal"
        if us_wc and us_wc.congestion_score >= 0.55:
            container_backlog = (
                f"LA/LB anchorage elevated ({us_wc.anchored_count} anchored) — "
                "import backlog / retail inventory build risk"
            )

        bulk_freight = "neutral"
        bulk_scores = [c.freight_score for c in corridors if c.bulk_count > 10]
        if bulk_scores and max(bulk_scores) >= 0.65:
            bulk_freight = "bulk cargo momentum supports dry freight rates (BDRY proxy)"

        tanker_flow = "normal"
        tanker_total = sum(c.tanker_count for c in corridors)
        if tanker_total >= 80:
            tanker_flow = f"elevated tanker transit ({tanker_total} across corridors) — crude/product flow active"

        retail = "stable lead times"
        if us_wc and us_wc.congestion_score >= 0.60:
            retail = "West Coast port congestion — watch retail restocking delays (XRT, AMZN)"
        elif us_wc and us_wc.congestion_score <= 0.35:
            retail = "West Coast fluid — favorable import lead times"

        mfg = "normal input flow"
        if singapore and singapore.lane_density_score >= 0.70:
            mfg = "Asia export lane active — semiconductor/consumer goods flow normal-to-strong"

        return LogisticsAssessment(
            chokepoint_risk=chokepoint,
            container_backlog_signal=container_backlog,
            bulk_freight_signal=bulk_freight,
            tanker_flow_signal=tanker_flow,
            retail_lead_time_signal=retail,
            manufacturing_input_signal=mfg,
        )

    def _supply_chain_stress(self, corridors: list[CorridorSnapshot]) -> float:
        congestion = max(c.congestion_score for c in corridors)
        density = sum(c.lane_density_score for c in corridors) / len(corridors)
        anchored_ratio = sum(
            c.anchored_count / max(c.total_vessels, 1) for c in corridors
        ) / len(corridors)
        return round(min(1.0, congestion * 0.45 + density * 0.30 + anchored_ratio * 0.25), 4)

    def _freight_momentum(self, corridors: list[CorridorSnapshot]) -> float:
        return round(sum(c.freight_score for c in corridors) / len(corridors), 4)

    def _congestion_aggregate(self, corridors: list[CorridorSnapshot]) -> float:
        return round(max(c.congestion_score for c in corridors), 4)

    @staticmethod
    def _marine_traffic_strategies(primary: CorridorSnapshot | None) -> dict[str, str]:
        if not primary:
            return {
                "routing": "Primary corridor unavailable — use multi-corridor proxy",
                "anchorage": "n/a",
                "freight_mix": "n/a",
                "port_priority": "n/a",
            }

        total = max(primary.total_vessels, 1)
        anchored_pct = primary.anchored_count / total * 100
        underway_pct = primary.underway_count / total * 100
        top_ports = sorted(primary.port_proximity.items(), key=lambda x: -x[1])[:3]
        port_line = ", ".join(f"{n} ({v})" for n, v in top_ports) if top_ports else "n/a"

        routing = (
            f"High lane density ({primary.lane_density_score:.2f}) — "
            "favor scheduled feeder services and Dover/Channel weather windows"
            if primary.lane_density_score >= 0.65
            else "Moderate North Sea traffic — standard EU-UK routing viable"
        )

        anchorage = (
            f"{anchored_pct:.0f}% anchored ({primary.anchored_count} vessels) — "
            "expect Rotterdam/Antwerp queue delays; consider just-in-time berth booking"
            if anchored_pct >= 25
            else f"{underway_pct:.0f}% underway — fluid anchorage, normal port turnaround"
        )

        bulk_share = primary.bulk_count / total * 100
        cargo_share = primary.cargo_count / total * 100
        freight_mix = (
            f"Bulk-heavy mix ({bulk_share:.0f}% bulk, {cargo_share:.0f}% cargo) — "
            "dry freight rate sensitivity (BDRY); prioritize bulk berth slots"
            if bulk_share >= 20
            else f"Container/cargo dominant ({cargo_share:.0f}%) — "
            "monitor TEU flow through Rotterdam and Antwerp"
        )

        return {
            "routing": routing,
            "anchorage": anchorage,
            "freight_mix": freight_mix,
            "port_priority": f"Top port proximity: {port_line}",
            "dashboard_note": (
                f"MarineTraffic North Sea view at {PRIMARY_DASHBOARD} "
                f"({primary.total_vessels} vessels tracked)"
            ),
        }

    def _expert_summary(
        self,
        corridors: list[CorridorSnapshot],
        assessment: LogisticsAssessment,
        stress: float,
        freight: float,
        label: str,
        primary: CorridorSnapshot | None,
    ) -> str:
        total_vessels = sum(c.total_vessels for c in corridors)
        busiest = max(corridors, key=lambda c: c.total_vessels)
        primary_line = ""
        if primary:
            primary_line = (
                f" Primary view ({PRIMARY_DASHBOARD}): "
                f"{primary.total_vessels} vessels, density {primary.lane_density_score:.2f}, "
                f"congestion {primary.congestion_score:.2f}."
            )
        return (
            f"MarineTraffic logistics analysis — global stress {label.lower()} "
            f"(score {stress:.2f}) across {len(corridors)} corridors "
            f"({total_vessels} vessels total).{primary_line} "
            f"Busiest lane: {busiest.corridor_name} ({busiest.total_vessels} vessels). "
            f"Freight momentum {freight:.2f}. "
            f"Chokepoint: {assessment.chokepoint_risk}. "
            f"Containers: {assessment.container_backlog_signal}. "
            f"Bulk: {assessment.bulk_freight_signal}. "
            f"Tankers: {assessment.tanker_flow_signal}. "
            f"Retail: {assessment.retail_lead_time_signal}."
        )

    def analyze(self) -> LogisticsReport:
        corridors: list[CorridorSnapshot] = []
        for cid, cfg in CORRIDORS.items():
            corridors.append(self._analyze_corridor(cid, cfg))
            time.sleep(0.15)

        assessment = self._logistics_assessment(corridors)
        stress = self._supply_chain_stress(corridors)
        freight = self._freight_momentum(corridors)
        congestion = self._congestion_aggregate(corridors)

        label = (
            "Critical" if stress >= 0.75 else
            "Elevated" if stress >= 0.55 else
            "Moderate" if stress >= 0.35 else
            "Normal"
        )

        primary = next((c for c in corridors if c.corridor_id == PRIMARY_CORRIDOR_ID), None)
        strategies = self._marine_traffic_strategies(primary)
        sources = sorted({c.data_source for c in corridors if c.data_source})

        summary = self._expert_summary(
            corridors, assessment, stress, freight, label, primary
        )
        signals = self._market_signals(corridors, assessment, stress, freight, congestion)
        recs = self._recommendations(corridors, assessment, stress, freight, congestion)
        for key, value in strategies.items():
            recs.append(f"{key.replace('_', ' ').title()}: {value}")

        return LogisticsReport(
            corridors=corridors,
            assessment=assessment,
            supply_chain_stress_score=stress,
            freight_momentum_score=freight,
            congestion_score=congestion,
            stress_label=label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            primary_corridor=primary,
            marine_traffic_strategies=strategies,
            data_sources=sources,
        )

    @staticmethod
    def _market_signals(
        corridors: list[CorridorSnapshot],
        assessment: LogisticsAssessment,
        stress: float,
        freight: float,
        congestion: float,
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        if freight >= 0.55:
            signals.append({
                "sector": "Dry Bulk Shipping",
                "tickers": ["BDRY", "GOGL", "SBLK"],
                "bias": "BULLISH" if freight >= 0.70 else "NEUTRAL",
                "reason": f"Freight momentum {freight:.2f} — {assessment.bulk_freight_signal}",
            })

        north_sea = next((c for c in corridors if c.corridor_id == "north_sea"), None)
        if north_sea and north_sea.lane_density_score >= 0.65:
            signals.append({
                "sector": "Container Shipping — Europe",
                "tickers": ["ZIM", "DAC", "CMRE"],
                "bias": "BULLISH" if north_sea.freight_score >= 0.70 else "NEUTRAL",
                "reason": f"North Sea density {north_sea.lane_density_score:.2f} — Rotterdam/Antwerp active",
            })

        us_wc = next((c for c in corridors if c.corridor_id == "us_west_coast"), None)
        if us_wc:
            if us_wc.congestion_score >= 0.55:
                signals.append({
                    "sector": "Retail / Import Congestion",
                    "tickers": ["XRT", "AMZN", "WMT", "TGT"],
                    "bias": "BEARISH" if us_wc.congestion_score >= 0.70 else "NEUTRAL",
                    "reason": assessment.retail_lead_time_signal,
                })
            else:
                signals.append({
                    "sector": "Retail / Import Flow",
                    "tickers": ["XRT", "FDX", "UPS"],
                    "bias": "NEUTRAL",
                    "reason": "West Coast ports fluid — normal import lead times",
                })

        if "tanker" in assessment.tanker_flow_signal.lower():
            signals.append({
                "sector": "Tanker / Product Shipping",
                "tickers": ["FRO", "STNG", "TNK", "DHT"],
                "bias": "BULLISH",
                "reason": assessment.tanker_flow_signal,
            })

        if stress >= 0.60:
            signals.append({
                "sector": "Supply Chain Stress",
                "tickers": ["CHRW", "XPO", "JBHT"],
                "bias": "NEUTRAL",
                "reason": f"Elevated logistics stress {stress:.2f} — rate volatility likely",
            })

        if not signals:
            signals.append({
                "sector": "Global Trade / Shipping",
                "tickers": ["BDRY", "ZIM"],
                "bias": "NEUTRAL",
                "reason": "No significant logistics stress detected",
            })

        return signals

    @staticmethod
    def _recommendations(
        corridors: list[CorridorSnapshot],
        assessment: LogisticsAssessment,
        stress: float,
        freight: float,
        congestion: float,
    ) -> list[str]:
        recs = [
            f"Supply chain stress: {stress:.2f} | Freight momentum: {freight:.2f} | Peak congestion: {congestion:.2f}",
            f"Chokepoint: {assessment.chokepoint_risk}",
            f"Containers: {assessment.container_backlog_signal}",
            f"Retail lead times: {assessment.retail_lead_time_signal}",
            f"Manufacturing inputs: {assessment.manufacturing_input_signal}",
        ]
        for c in corridors:
            top_ports = sorted(c.port_proximity.items(), key=lambda x: x[1], reverse=True)[:2]
            ports_str = ", ".join(f"{n} ({v})" for n, v in top_ports) if top_ports else "n/a"
            recs.append(
                f"{c.corridor_name}: {c.total_vessels} vessels, "
                f"density {c.lane_density_score:.2f}, congestion {c.congestion_score:.2f} — {ports_str}"
            )
        if freight >= 0.65:
            recs.append("Elevated freight momentum — dry bulk (BDRY) and container (ZIM) rate sensitivity")
        if congestion >= 0.65:
            recs.append("Port congestion elevated — monitor retail inventory and margin pressure")
        return recs

    @staticmethod
    def corridor_catalog() -> list[dict[str, Any]]:
        return [
            {
                "id": cid,
                "name": cfg["name"],
                "dashboard": cfg["dashboard"],
                "center": cfg["center"],
                "ports": [name for _, _, name in cfg["ports"]],
                "primary": cid == PRIMARY_CORRIDOR_ID,
            }
            for cid, cfg in CORRIDORS.items()
        ]

    def to_dict(self, report: LogisticsReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Logistics Expert",
                "primary_dashboard": PRIMARY_DASHBOARD,
                "analyzed_at": report.analyzed_at,
                "expert_summary": report.expert_summary,
                "corridors_monitored": len(report.corridors),
                "data_sources": report.data_sources,
            },
            "marine_traffic_strategies": report.marine_traffic_strategies,
            "primary_corridor": (
                {
                    "id": report.primary_corridor.corridor_id,
                    "name": report.primary_corridor.corridor_name,
                    "dashboard": report.primary_corridor.dashboard_url,
                    "total_vessels": report.primary_corridor.total_vessels,
                    "lane_density_score": report.primary_corridor.lane_density_score,
                    "congestion_score": report.primary_corridor.congestion_score,
                    "freight_score": report.primary_corridor.freight_score,
                    "port_proximity": report.primary_corridor.port_proximity,
                    "data_source": report.primary_corridor.data_source,
                }
                if report.primary_corridor
                else None
            ),
            "assessment": {
                "chokepoint_risk": a.chokepoint_risk,
                "container_backlog_signal": a.container_backlog_signal,
                "bulk_freight_signal": a.bulk_freight_signal,
                "tanker_flow_signal": a.tanker_flow_signal,
                "retail_lead_time_signal": a.retail_lead_time_signal,
                "manufacturing_input_signal": a.manufacturing_input_signal,
            },
            "corridors": [
                {
                    "id": c.corridor_id,
                    "name": c.corridor_name,
                    "dashboard": c.dashboard_url,
                    "data_source": c.data_source,
                    "total_vessels": c.total_vessels,
                    "tanker_count": c.tanker_count,
                    "bulk_count": c.bulk_count,
                    "cargo_count": c.cargo_count,
                    "container_count": c.container_count,
                    "anchored_count": c.anchored_count,
                    "underway_count": c.underway_count,
                    "avg_speed_knots": c.avg_speed_knots,
                    "port_proximity": c.port_proximity,
                    "metrics": {
                        "lane_density_score": c.lane_density_score,
                        "freight_score": c.freight_score,
                        "congestion_score": c.congestion_score,
                    },
                }
                for c in report.corridors
            ],
            "metrics": {
                "supply_chain_stress_score": report.supply_chain_stress_score,
                "freight_momentum_score": report.freight_momentum_score,
                "congestion_score": report.congestion_score,
                "stress_label": report.stress_label,
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
            catalog_path = output.parent / "marine_traffic_corridors.json"
            catalog_path.write_text(
                json.dumps(self.corridor_catalog(), indent=2),
                encoding="utf-8",
            )
        return result


def run_logistics_analysis(output: Path | None = None) -> dict[str, Any]:
    return LogisticsExpert().run(output=output)