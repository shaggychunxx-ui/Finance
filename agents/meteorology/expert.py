"""
Meteorology Expert Agent
========================
Expert analysis of US weather hazards and forecasts via the National Weather Service.

Data: https://www.weather.gov/  (API: https://api.weather.gov)
No API key required; a descriptive User-Agent is required per NWS policy.
"""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

DASHBOARD_URL = "https://www.weather.gov/"
API_BASE = "https://api.weather.gov"
HEADERS = {
    "User-Agent": "Finance-Meteorology-Expert/1.0 (shaggychunxx@gmail.com)",
    "Accept": "application/geo+json",
}

DEFAULT_HUBS = [
    (40.7128, -74.0060, "New York"),
    (41.8781, -87.6298, "Chicago"),
    (29.7604, -95.3698, "Houston"),
    (32.7767, -96.7970, "Dallas"),
    (34.0522, -118.2437, "Los Angeles"),
    (33.7490, -84.3880, "Atlanta"),
    (33.4484, -112.0740, "Phoenix"),
    (39.7392, -104.9903, "Denver"),
    (47.6062, -122.3321, "Seattle"),
]

HEAT_EVENTS = {
    "extreme heat warning", "excessive heat warning", "heat advisory", "heat warning",
}
COLD_EVENTS = {
    "extreme cold warning", "wind chill warning", "wind chill advisory",
    "freeze warning", "freeze watch", "winter storm warning", "blizzard warning",
}
SEVERE_EVENTS = {
    "tornado warning", "tornado watch", "severe thunderstorm warning",
    "severe thunderstorm watch", "hurricane warning", "hurricane watch",
    "tropical storm warning", "tropical storm watch",
}
FLOOD_EVENTS = {
    "flood warning", "flash flood warning", "flood watch",
    "flash flood watch", "flood advisory",
}
FIRE_EVENTS = {"red flag warning", "fire weather watch", "fire warning"}
WIND_EVENTS = {"high wind warning", "high wind watch", "wind advisory"}


@dataclass
class AlertSummary:
    total_active: int
    land_alerts: int
    marine_alerts: int
    by_event: dict[str, int] = field(default_factory=dict)
    by_state: dict[str, int] = field(default_factory=dict)
    heat_alerts: int = 0
    cold_alerts: int = 0
    severe_alerts: int = 0
    flood_alerts: int = 0
    fire_alerts: int = 0
    wind_alerts: int = 0
    sample_alerts: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class HubForecast:
    name: str
    lat: float
    lon: float
    office: str
    periods: list[dict[str, Any]] = field(default_factory=list)
    max_temp_f: float | None = None
    min_temp_f: float | None = None
    heat_index_f: float | None = None
    dominant_pattern: str = ""


@dataclass
class SynopticAssessment:
    """Expert-level synoptic read derived from national alert + forecast context."""
    season_context: str
    dominant_hazards: list[str]
    ridge_trough_signal: str
    tropical_activity: str
    agricultural_risk: str
    aviation_disruption: str


@dataclass
class MeteorologyReport:
    region: str
    region_name: str
    alerts: AlertSummary
    hub_forecasts: list[HubForecast]
    synoptic: SynopticAssessment
    heat_stress_score: float
    cold_stress_score: float
    severe_weather_score: float
    flood_risk_score: float
    energy_demand_score: float
    disruption_score: float
    disruption_label: str
    national_headline: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MeteorologyExpert:
    """Expert meteorologist agent — NWS hazards, hub forecasts, and market implications."""

    def __init__(self, hubs: list[tuple[float, float, str]] | None = None) -> None:
        self.hubs = hubs or self._load_config_hubs() or DEFAULT_HUBS
        # Randomized creativity/variance level for this run's analysis (1=conservative, 8=exploratory)
        self.temperature = random.randint(1, 8)

    @staticmethod
    def _load_config_hubs() -> list[tuple[float, float, str]]:
        for cfg in (Path("config.json"), Path(__file__).resolve().parents[2] / "config.json"):
            if not cfg.exists():
                continue
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
                raw = data.get("weather_hubs", [])
                return [
                    (float(h["lat"]), float(h["lon"]), str(h["name"]))
                    for h in raw
                    if "lat" in h and "lon" in h and "name" in h
                ]
            except Exception:
                continue
        return []

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = path if path.startswith("http") else f"{API_BASE}{path}"
        resp = requests.get(url, params=params, headers=HEADERS, timeout=45)
        resp.raise_for_status()
        return resp.json()

    def _fetch_alert_count(self) -> dict[str, Any]:
        return self._get("/alerts/active/count")

    def _fetch_active_alerts(self) -> list[dict[str, Any]]:
        data = self._get("/alerts/active", {"status": "actual"})
        return data.get("features", [])

    @staticmethod
    def _match_category(event: str, keywords: set[str]) -> bool:
        ev = event.lower()
        return any(k in ev for k in keywords)

    def _summarize_alerts(self, features: list[dict[str, Any]]) -> AlertSummary:
        by_event: dict[str, int] = {}
        by_state: dict[str, int] = {}
        heat = cold = severe = flood = fire = wind = 0
        samples: list[dict[str, Any]] = []

        for feat in features:
            props = feat.get("properties", {})
            event = props.get("event", "Unknown")
            by_event[event] = by_event.get(event, 0) + 1

            for area in props.get("areaDesc", "").split(";"):
                st_match = re.search(r",\s*([A-Z]{2})\b", area)
                if st_match:
                    st = st_match.group(1)
                    by_state[st] = by_state.get(st, 0) + 1

            ev_lower = event.strip().lower()
            if self._match_category(ev_lower, HEAT_EVENTS):
                heat += 1
            if self._match_category(ev_lower, COLD_EVENTS):
                cold += 1
            if self._match_category(ev_lower, SEVERE_EVENTS):
                severe += 1
            if self._match_category(ev_lower, FLOOD_EVENTS):
                flood += 1
            if self._match_category(ev_lower, FIRE_EVENTS):
                fire += 1
            if self._match_category(ev_lower, WIND_EVENTS):
                wind += 1

            if len(samples) < 12 and props.get("severity") in ("Extreme", "Severe"):
                samples.append({
                    "event": event,
                    "area": props.get("areaDesc", "")[:120],
                    "severity": props.get("severity"),
                    "headline": (props.get("headline") or "")[:160],
                })

        count_data = self._fetch_alert_count()
        return AlertSummary(
            total_active=int(count_data.get("total", len(features))),
            land_alerts=int(count_data.get("land", 0)),
            marine_alerts=int(count_data.get("marine", 0)),
            by_event=dict(sorted(by_event.items(), key=lambda x: -x[1])),
            by_state=dict(sorted(by_state.items(), key=lambda x: -x[1])[:15]),
            heat_alerts=heat,
            cold_alerts=cold,
            severe_alerts=severe,
            flood_alerts=flood,
            fire_alerts=fire,
            wind_alerts=wind,
            sample_alerts=samples,
        )

    @staticmethod
    def _infer_pattern(periods: list[dict[str, Any]]) -> str:
        text = " ".join(
            str(p.get("forecast", "")) + " " + str(p.get("shortForecast", ""))
            for p in periods
        ).lower()
        if any(w in text for w in ("thunder", "storm", "tornado", "hurricane")):
            return "convective / severe"
        if any(w in text for w in ("snow", "blizzard", "ice", "freezing")):
            return "winter storm"
        if any(w in text for w in ("heat", "hot", "record")):
            return "heat ridge"
        if any(w in text for w in ("rain", "flood", "shower")):
            return "wet pattern"
        if any(w in text for w in ("wind", "gust")):
            return "windy / frontal"
        if any(w in text for w in ("sunny", "clear", "fair")):
            return "fair / stable"
        return "mixed"

    def _fetch_hub_forecast(self, lat: float, lon: float, name: str) -> HubForecast:
        hub = HubForecast(name=name, lat=lat, lon=lon, office="")
        try:
            points = self._get(f"/points/{lat:.4f},{lon:.4f}")
            props = points.get("properties", {})
            hub.office = str(props.get("cwa", ""))
            forecast_url = props.get("forecast")
            if not forecast_url:
                return hub
            fc = self._get(forecast_url)
            periods = fc.get("properties", {}).get("periods", [])[:8]
            hub.periods = [
                {
                    "name": p.get("name"),
                    "temperature": p.get("temperature"),
                    "unit": p.get("temperatureUnit"),
                    "forecast": p.get("shortForecast"),
                    "wind": p.get("windSpeed"),
                }
                for p in periods
            ]
            hub.dominant_pattern = self._infer_pattern(periods)
            temps = [float(p["temperature"]) for p in periods if p.get("temperature") is not None]
            if temps:
                hub.max_temp_f = max(temps)
                hub.min_temp_f = min(temps)
            day_highs = [
                float(p["temperature"])
                for p in periods
                if p.get("temperature") is not None
                and p.get("temperatureUnit") == "F"
                and "night" not in str(p.get("name", "")).lower()
            ]
            if day_highs:
                hub.heat_index_f = max(day_highs)
        except Exception:
            pass
        return hub

    def fetch_hub_forecasts(self) -> list[HubForecast]:
        forecasts: list[HubForecast] = []
        for lat, lon, name in self.hubs:
            forecasts.append(self._fetch_hub_forecast(lat, lon, name))
            time.sleep(0.12)
        return forecasts

    @staticmethod
    def _score_from_count(count: int, scale: float = 50.0) -> float:
        return round(max(0.0, min(1.0, count / scale)), 4)

    def _heat_stress(self, alerts: AlertSummary, hubs: list[HubForecast]) -> float:
        alert_score = self._score_from_count(alerts.heat_alerts, 80)
        temp_score = 0.0
        highs = [h.heat_index_f for h in hubs if h.heat_index_f is not None]
        if highs:
            peak = max(highs)
            if peak >= 105:
                temp_score = 1.0
            elif peak >= 95:
                temp_score = 0.75
            elif peak >= 85:
                temp_score = 0.45
            else:
                temp_score = 0.20
        return round(min(1.0, alert_score * 0.55 + temp_score * 0.45), 4)

    def _cold_stress(self, alerts: AlertSummary, hubs: list[HubForecast]) -> float:
        alert_score = self._score_from_count(alerts.cold_alerts, 40)
        lows = [h.min_temp_f for h in hubs if h.min_temp_f is not None]
        temp_score = 0.0
        if lows:
            trough = min(lows)
            if trough <= 10:
                temp_score = 1.0
            elif trough <= 25:
                temp_score = 0.70
            elif trough <= 32:
                temp_score = 0.40
        return round(min(1.0, alert_score * 0.5 + temp_score * 0.5), 4)

    def _disruption_score(
        self,
        alerts: AlertSummary,
        heat: float,
        cold: float,
        severe: float,
        flood: float,
    ) -> float:
        base = (
            heat * 0.30
            + cold * 0.15
            + severe * 0.25
            + flood * 0.15
            + self._score_from_count(alerts.fire_alerts, 20) * 0.08
            + self._score_from_count(alerts.wind_alerts, 30) * 0.07
        )
        if alerts.total_active > 300:
            base = min(1.0, base + 0.10)
        return round(max(0.0, min(1.0, base)), 4)

    @staticmethod
    def _season_context(now: datetime | None = None) -> str:
        now = now or datetime.now(timezone.utc)
        month = now.month
        if month in (6, 7, 8, 9):
            return "Atlantic hurricane season active; summer convective peak; cooling demand elevated"
        if month in (12, 1, 2):
            return "Winter season — heating demand, polar outbreaks, and storm tracks dominate"
        if month in (3, 4, 5):
            return "Spring transition — severe weather season ramps; planting weather critical"
        return "Fall transition — tropical tail risk and early heating demand build"

    def _synoptic_assessment(
        self, alerts: AlertSummary, hubs: list[HubForecast]
    ) -> SynopticAssessment:
        top_events = list(alerts.by_event.keys())[:4]
        patterns = [h.dominant_pattern for h in hubs if h.dominant_pattern]
        pattern_counts: dict[str, int] = {}
        for p in patterns:
            pattern_counts[p] = pattern_counts.get(p, 0) + 1
        dominant_pattern = (
            max(pattern_counts, key=pattern_counts.get) if pattern_counts else "mixed"
        )

        tropical = "quiet"
        if alerts.severe_alerts > 0 and any(
            "hurricane" in e.lower() or "tropical" in e.lower()
            for e in alerts.by_event
        ):
            tropical = "active tropical cyclone alerts — Gulf / Atlantic exposure"
        elif datetime.now(timezone.utc).month in (6, 7, 8, 9, 10, 11):
            tropical = "hurricane season — monitor Gulf Coast and Florida load centers"

        ag_risk = "normal"
        if alerts.flood_alerts >= 15:
            ag_risk = "elevated flood stress — row-crop and logistics corridors impacted"
        elif alerts.heat_alerts >= 20:
            ag_risk = "heat/drought stress — yield risk for corn/soy belt"
        elif alerts.cold_alerts >= 10:
            ag_risk = "freeze risk — citrus and early planting vulnerable"

        aviation = "normal"
        if alerts.wind_alerts >= 10 or alerts.severe_alerts >= 8:
            aviation = "hub delay risk — convective or wind-related ground stops likely"

        ridge_trough = dominant_pattern
        if alerts.heat_alerts > alerts.cold_alerts * 2:
            ridge_trough = "persistent ridge / heat dome signal nationally"
        elif alerts.cold_alerts > alerts.heat_alerts * 2:
            ridge_trough = "trough / Arctic intrusion signal"

        return SynopticAssessment(
            season_context=self._season_context(),
            dominant_hazards=top_events,
            ridge_trough_signal=ridge_trough,
            tropical_activity=tropical,
            agricultural_risk=ag_risk,
            aviation_disruption=aviation,
        )

    def _expert_summary(
        self,
        alerts: AlertSummary,
        synoptic: SynopticAssessment,
        heat: float,
        cold: float,
        severe: float,
        disruption: float,
        label: str,
    ) -> str:
        parts = [
            f"National weather disruption is {label.lower()} (score {disruption:.2f}).",
            synoptic.season_context + ".",
            f"Synoptic read: {synoptic.ridge_trough_signal}.",
            (
                f"Active hazards led by {synoptic.dominant_hazards[0]}"
                if synoptic.dominant_hazards
                else "No dominant hazard type"
            )
            + f" across {alerts.total_active} NWS alerts.",
            f"Heat stress {heat:.2f}, cold stress {cold:.2f}, severe weather {severe:.2f}.",
            f"Tropical: {synoptic.tropical_activity}.",
            f"Agriculture: {synoptic.agricultural_risk}.",
            f"Aviation: {synoptic.aviation_disruption}.",
        ]
        return " ".join(parts)

    def analyze(self) -> MeteorologyReport:
        features = self._fetch_active_alerts()
        alerts = self._summarize_alerts(features)
        hubs = self.fetch_hub_forecasts()

        heat = self._heat_stress(alerts, hubs)
        cold = self._cold_stress(alerts, hubs)
        severe = self._score_from_count(alerts.severe_alerts, 35)
        flood = self._score_from_count(alerts.flood_alerts, 40)
        energy = round(min(1.0, heat * 0.65 + cold * 0.35), 4)
        disruption = self._disruption_score(alerts, heat, cold, severe, flood)
        synoptic = self._synoptic_assessment(alerts, hubs)

        label = (
            "Critical" if disruption >= 0.75 else
            "Elevated" if disruption >= 0.55 else
            "Moderate" if disruption >= 0.35 else
            "Normal"
        )

        headline = self._national_headline(alerts)
        summary = self._expert_summary(alerts, synoptic, heat, cold, severe, disruption, label)
        signals = self._market_signals(heat, cold, severe, flood, energy, alerts, hubs, synoptic)
        recs = self._recommendations(alerts, hubs, heat, cold, severe, flood, energy, synoptic)

        return MeteorologyReport(
            region="US",
            region_name="United States (NWS)",
            alerts=alerts,
            hub_forecasts=hubs,
            synoptic=synoptic,
            heat_stress_score=heat,
            cold_stress_score=cold,
            severe_weather_score=severe,
            flood_risk_score=flood,
            energy_demand_score=energy,
            disruption_score=disruption,
            disruption_label=label,
            national_headline=headline,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source="NWS API (api.weather.gov)",
        )

    @staticmethod
    def _national_headline(alerts: AlertSummary) -> str:
        if not alerts.by_event:
            return "No active NWS alerts"
        top = next(iter(alerts.by_event.items()))
        return f"{alerts.total_active} active alerts — leading hazard: {top[0]} ({top[1]})"

    @staticmethod
    def _market_signals(
        heat: float,
        cold: float,
        severe: float,
        flood: float,
        energy: float,
        alerts: AlertSummary,
        hubs: list[HubForecast],
        synoptic: SynopticAssessment,
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        if heat >= 0.45:
            signals.append({
                "sector": "Power / Cooling Demand",
                "tickers": ["CEG", "VST", "XLU", "NRG"],
                "bias": "BULLISH" if heat >= 0.65 else "NEUTRAL",
                "reason": f"Heat stress {heat:.2f} — {alerts.heat_alerts} heat alerts",
            })

        if energy >= 0.50:
            signals.append({
                "sector": "Natural Gas / Energy",
                "tickers": ["XLE", "UNG", "AR", "EQT"],
                "bias": "BULLISH" if energy >= 0.70 else "NEUTRAL",
                "reason": f"Weather-driven energy demand score {energy:.2f}",
            })

        if cold >= 0.45:
            signals.append({
                "sector": "Heating Demand",
                "tickers": ["UNG", "XLE", "XLU"],
                "bias": "BULLISH" if cold >= 0.65 else "NEUTRAL",
                "reason": f"Cold stress {cold:.2f} — {alerts.cold_alerts} winter alerts",
            })

        if "hurricane" in synoptic.tropical_activity.lower() or "active tropical" in synoptic.tropical_activity.lower():
            signals.append({
                "sector": "Gulf Energy / Refining",
                "tickers": ["USO", "XLE", "VLO", "MPC", "HAL"],
                "bias": "NEUTRAL",
                "reason": synoptic.tropical_activity,
            })

        if "flood" in synoptic.agricultural_risk.lower() or "heat/drought" in synoptic.agricultural_risk.lower():
            signals.append({
                "sector": "Agriculture / Soft Commodities",
                "tickers": ["DBA", "CORN", "SOYB", "WEAT"],
                "bias": "BULLISH" if "drought" in synoptic.agricultural_risk.lower() else "NEUTRAL",
                "reason": synoptic.agricultural_risk,
            })

        if severe >= 0.35:
            signals.append({
                "sector": "Insurance / Utilities",
                "tickers": ["ALL", "TRV", "PGR", "XLU"],
                "bias": "NEUTRAL",
                "reason": f"{alerts.severe_alerts} severe/tropical alerts — outage & claims risk",
            })

        houston = next((h for h in hubs if h.name == "Houston"), None)
        if houston and houston.max_temp_f and houston.max_temp_f >= 95:
            signals.append({
                "sector": "Gulf / Refining",
                "tickers": ["USO", "XLE", "VLO"],
                "bias": "NEUTRAL",
                "reason": f"Houston peak forecast {houston.max_temp_f:.0f}°F",
            })

        if not signals:
            signals.append({
                "sector": "Weather / Utilities",
                "tickers": ["XLU", "CEG"],
                "bias": "NEUTRAL",
                "reason": "No significant national weather stress detected",
            })

        return signals

    @staticmethod
    def _recommendations(
        alerts: AlertSummary,
        hubs: list[HubForecast],
        heat: float,
        cold: float,
        severe: float,
        flood: float,
        energy: float,
        synoptic: SynopticAssessment,
    ) -> list[str]:
        recs = [
            synoptic.season_context,
            (
                f"{alerts.total_active} active NWS alerts "
                f"({alerts.land_alerts} land, {alerts.marine_alerts} marine)"
            ),
            (
                f"Hazards: {alerts.heat_alerts} heat, {alerts.severe_alerts} severe, "
                f"{alerts.flood_alerts} flood, {alerts.cold_alerts} cold"
            ),
            f"Synoptic: {synoptic.ridge_trough_signal}",
            f"Tropical outlook: {synoptic.tropical_activity}",
            f"Agriculture: {synoptic.agricultural_risk}",
        ]
        top_states = list(alerts.by_state.items())[:5]
        if top_states:
            recs.append(
                "Most affected states: " + ", ".join(f"{st} ({n})" for st, n in top_states)
            )
        hot_hubs = sorted(
            [h for h in hubs if h.max_temp_f is not None],
            key=lambda h: h.max_temp_f or 0,
            reverse=True,
        )[:3]
        if hot_hubs:
            recs.append(
                "Peak hub temps: "
                + ", ".join(f"{h.name} {h.max_temp_f:.0f}°F ({h.dominant_pattern})" for h in hot_hubs)
            )
        if heat >= 0.65:
            recs.append("Extreme heat — favor merchant power (CEG, VST) over pure transmission")
        if cold >= 0.65:
            recs.append("Cold snap — watch nat gas (UNG) and heating-driven load")
        if severe >= 0.50:
            recs.append("Elevated severe weather — monitor utility outages and insurance exposure")
        if energy >= 0.70:
            recs.append(f"Weather-driven energy demand elevated ({energy:.2f})")
        return recs

    def to_dict(self, report: MeteorologyReport) -> dict[str, Any]:
        a = report.alerts
        s = report.synoptic
        return {
            "meta": {
                "dashboard": DASHBOARD_URL,
                "agent": "Meteorology Expert",
                "temperature": self.temperature,
                "region": report.region,
                "region_name": report.region_name,
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "national_headline": report.national_headline,
                "expert_summary": report.expert_summary,
            },
            "synoptic": {
                "season_context": s.season_context,
                "dominant_hazards": s.dominant_hazards,
                "ridge_trough_signal": s.ridge_trough_signal,
                "tropical_activity": s.tropical_activity,
                "agricultural_risk": s.agricultural_risk,
                "aviation_disruption": s.aviation_disruption,
            },
            "alerts": {
                "total_active": a.total_active,
                "land_alerts": a.land_alerts,
                "marine_alerts": a.marine_alerts,
                "heat_alerts": a.heat_alerts,
                "cold_alerts": a.cold_alerts,
                "severe_alerts": a.severe_alerts,
                "flood_alerts": a.flood_alerts,
                "fire_alerts": a.fire_alerts,
                "wind_alerts": a.wind_alerts,
                "by_event": dict(list(a.by_event.items())[:15]),
                "by_state": a.by_state,
                "sample_alerts": a.sample_alerts,
            },
            "hub_forecasts": [
                {
                    "name": h.name,
                    "lat": h.lat,
                    "lon": h.lon,
                    "office": h.office,
                    "dominant_pattern": h.dominant_pattern,
                    "max_temp_f": h.max_temp_f,
                    "min_temp_f": h.min_temp_f,
                    "periods": h.periods,
                }
                for h in report.hub_forecasts
            ],
            "metrics": {
                "heat_stress_score": report.heat_stress_score,
                "cold_stress_score": report.cold_stress_score,
                "severe_weather_score": report.severe_weather_score,
                "flood_risk_score": report.flood_risk_score,
                "energy_demand_score": report.energy_demand_score,
                "disruption_score": report.disruption_score,
                "disruption_label": report.disruption_label,
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


def run_meteorology_analysis(output: Path | None = None) -> dict[str, Any]:
    return MeteorologyExpert().run(output=output)