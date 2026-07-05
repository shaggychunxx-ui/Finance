"""
Oceanography Expert Agent
=========================
Expert analysis of US coastal tides, water levels, and sea-surface conditions
via NOAA Tides & Currents (CO-OPS), cross-referenced against public tide
forecasts.

Primary data: https://tidesandcurrents.noaa.gov/  (API: https://api.tidesandcurrents.noaa.gov)
No API key required.
Secondary dashboard (surf/tide outlook reference): https://www.tide-forecast.com/
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

DASHBOARD_URL = "https://tidesandcurrents.noaa.gov/"
SECONDARY_DASHBOARD_URL = "https://www.tide-forecast.com/"
API_BASE = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
HEADERS = {
    "User-Agent": "Finance-Oceanography-Expert/1.0 (shaggychunxx@gmail.com)",
}

# NOAA CO-OPS station IDs spanning major US coastal/port markets.
DEFAULT_STATIONS = [
    (8518750, 40.7006, -74.0142, "New York (The Battery)"),
    (8443970, 42.3548, -71.0510, "Boston"),
    (8638610, 36.9467, -76.3300, "Norfolk / Sewells Point"),
    (8665530, 32.7817, -79.9250, "Charleston"),
    (8724580, 24.5557, -81.8079, "Key West"),
    (8771450, 29.3100, -94.7933, "Galveston (Houston Ship Channel)"),
    (8761724, 29.2633, -89.9567, "Grand Isle (Gulf of Mexico)"),
    (9414290, 37.8063, -122.4659, "San Francisco"),
    (9410660, 33.7200, -118.2717, "Los Angeles"),
    (9447130, 47.6023, -122.3393, "Seattle"),
    (1612340, 21.3067, -157.8670, "Honolulu"),
    (9455920, 61.2378, -149.8900, "Anchorage"),
]

# Approximate mean tidal ranges (ft) used to flag anomalous/extreme spring tides.
NORMAL_TIDAL_RANGE_FT = {
    "New York (The Battery)": 4.7,
    "Boston": 9.5,
    "Norfolk / Sewells Point": 2.9,
    "Charleston": 5.9,
    "Key West": 1.4,
    "Galveston (Houston Ship Channel)": 1.4,
    "Grand Isle (Gulf of Mexico)": 1.3,
    "San Francisco": 4.3,
    "Los Angeles": 5.4,
    "Seattle": 9.6,
    "Honolulu": 1.9,
    "Anchorage": 26.0,
}

# Rough seasonal-normal coastal water temps (F) used to flag marine-heatwave risk.
NORMAL_WATER_TEMP_F = {
    1: 45, 2: 44, 3: 46, 4: 51, 5: 58, 6: 66,
    7: 72, 8: 74, 9: 71, 10: 63, 11: 55, 12: 48,
}


@dataclass
class StationReading:
    station_id: int
    name: str
    lat: float
    lon: float
    next_high_ft: float | None = None
    next_high_time: str | None = None
    next_low_ft: float | None = None
    next_low_time: str | None = None
    tidal_range_ft: float | None = None
    normal_range_ft: float | None = None
    observed_level_ft: float | None = None
    predicted_level_ft: float | None = None
    surge_anomaly_ft: float | None = None
    water_temp_f: float | None = None
    data_ok: bool = False


@dataclass
class OceanAssessment:
    """Expert oceanographic read derived from tide, surge, and SST context."""
    season_context: str
    dominant_hazard: str
    storm_surge_status: str
    tidal_extreme_status: str
    marine_heatwave_status: str
    shipping_draft_risk: str


@dataclass
class OceanographyReport:
    region: str
    region_name: str
    stations: list[StationReading]
    assessment: OceanAssessment
    storm_surge_score: float
    tidal_extreme_score: float
    marine_heatwave_score: float
    port_disruption_score: float
    disruption_label: str
    national_headline: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class OceanographyExpert:
    """Expert oceanographer agent — NOAA CO-OPS tides/currents and market implications."""

    def __init__(self, stations: list[tuple[int, float, float, str]] | None = None) -> None:
        self.stations = stations or self._load_config_stations() or DEFAULT_STATIONS

    @staticmethod
    def _load_config_stations() -> list[tuple[int, float, float, str]]:
        for cfg in (Path("config.json"), Path(__file__).resolve().parents[2] / "config.json"):
            if not cfg.exists():
                continue
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
                raw = data.get("tide_stations", [])
                return [
                    (int(s["id"]), float(s["lat"]), float(s["lon"]), str(s["name"]))
                    for s in raw
                    if "id" in s and "lat" in s and "lon" in s and "name" in s
                ]
            except Exception:
                continue
        return []

    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        resp = requests.get(API_BASE, params=params, headers=HEADERS, timeout=45)
        resp.raise_for_status()
        return resp.json()

    def _fetch_tide_predictions(self, station_id: int) -> list[dict[str, Any]]:
        data = self._get({
            "station": station_id,
            "product": "predictions",
            "datum": "MLLW",
            "units": "english",
            "time_zone": "lst_ld",
            "format": "json",
            "interval": "hilo",
            "begin_date": "today",
            "range": 48,
        })
        return data.get("predictions", [])

    def _fetch_hourly_predictions(self, station_id: int) -> list[dict[str, Any]]:
        data = self._get({
            "station": station_id,
            "product": "predictions",
            "datum": "MLLW",
            "units": "english",
            "time_zone": "lst_ld",
            "format": "json",
            "interval": "h",
            "begin_date": "today",
            "range": 6,
        })
        return data.get("predictions", [])

    def _fetch_water_level(self, station_id: int) -> dict[str, Any] | None:
        data = self._get({
            "station": station_id,
            "product": "water_level",
            "datum": "MLLW",
            "units": "english",
            "time_zone": "lst_ld",
            "format": "json",
            "date": "latest",
        })
        rows = data.get("data", [])
        return rows[-1] if rows else None

    def _fetch_water_temperature(self, station_id: int) -> float | None:
        try:
            data = self._get({
                "station": station_id,
                "product": "water_temperature",
                "units": "english",
                "time_zone": "lst_ld",
                "format": "json",
                "date": "latest",
            })
            rows = data.get("data", [])
            if rows:
                return float(rows[-1]["v"])
        except Exception:
            pass
        return None

    def _build_station_reading(
        self, station_id: int, lat: float, lon: float, name: str
    ) -> StationReading:
        reading = StationReading(station_id=station_id, name=name, lat=lat, lon=lon)
        try:
            hilo = self._fetch_tide_predictions(station_id)
            highs = [p for p in hilo if p.get("type") == "H"]
            lows = [p for p in hilo if p.get("type") == "L"]
            if highs:
                reading.next_high_ft = float(highs[0]["v"])
                reading.next_high_time = highs[0]["t"]
            if lows:
                reading.next_low_ft = float(lows[0]["v"])
                reading.next_low_time = lows[0]["t"]
            heights = [float(p["v"]) for p in hilo if p.get("v") is not None]
            if heights:
                reading.tidal_range_ft = round(max(heights) - min(heights), 2)
            reading.normal_range_ft = NORMAL_TIDAL_RANGE_FT.get(name)

            wl = self._fetch_water_level(station_id)
            if wl:
                reading.observed_level_ft = float(wl["v"])

            preds = self._fetch_hourly_predictions(station_id)
            if preds and reading.observed_level_ft is not None:
                reading.predicted_level_ft = float(preds[-1]["v"])
                reading.surge_anomaly_ft = round(
                    reading.observed_level_ft - reading.predicted_level_ft, 2
                )

            reading.water_temp_f = self._fetch_water_temperature(station_id)
            reading.data_ok = True
        except Exception:
            reading.data_ok = False
        return reading

    def fetch_station_readings(self) -> list[StationReading]:
        readings: list[StationReading] = []
        for station_id, lat, lon, name in self.stations:
            readings.append(self._build_station_reading(station_id, lat, lon, name))
            time.sleep(0.12)
        return readings

    @staticmethod
    def _score_from_count(count: int, scale: float) -> float:
        return round(max(0.0, min(1.0, count / scale)), 4)

    def _storm_surge_score(self, stations: list[StationReading]) -> float:
        anomalies = [s.surge_anomaly_ft for s in stations if s.surge_anomaly_ft is not None]
        if not anomalies:
            return 0.0
        peak = max(anomalies)
        if peak >= 3.0:
            return 1.0
        if peak >= 2.0:
            return 0.75
        if peak >= 1.0:
            return 0.45
        if peak >= 0.5:
            return 0.20
        return 0.05

    def _tidal_extreme_score(self, stations: list[StationReading]) -> float:
        ratios = []
        for s in stations:
            if s.tidal_range_ft is not None and s.normal_range_ft:
                ratios.append(s.tidal_range_ft / s.normal_range_ft)
        if not ratios:
            return 0.0
        peak_ratio = max(ratios)
        if peak_ratio >= 1.35:
            return 1.0
        if peak_ratio >= 1.20:
            return 0.65
        if peak_ratio >= 1.10:
            return 0.35
        return 0.10

    def _marine_heatwave_score(self, stations: list[StationReading], now: datetime) -> float:
        normal = NORMAL_WATER_TEMP_F.get(now.month, 60)
        anomalies = [
            s.water_temp_f - normal for s in stations if s.water_temp_f is not None
        ]
        if not anomalies:
            return 0.0
        peak = max(anomalies)
        if peak >= 6.0:
            return 1.0
        if peak >= 4.0:
            return 0.65
        if peak >= 2.0:
            return 0.35
        return 0.10

    def _port_disruption_score(
        self, surge: float, tidal: float, heatwave: float, stations: list[StationReading]
    ) -> float:
        ok_ratio = (
            sum(1 for s in stations if s.data_ok) / len(stations) if stations else 0.0
        )
        base = surge * 0.5 + tidal * 0.30 + heatwave * 0.20
        if ok_ratio < 0.5:
            base = min(1.0, base + 0.10)
        return round(max(0.0, min(1.0, base)), 4)

    @staticmethod
    def _season_context(now: datetime | None = None) -> str:
        now = now or datetime.now(timezone.utc)
        month = now.month
        if month in (6, 7, 8, 9):
            return "Atlantic/Gulf hurricane season — storm surge and coastal flooding risk elevated"
        if month in (12, 1, 2):
            return "Winter storm season — king tides and nor'easter surge risk on Atlantic/Pacific coasts"
        if month in (3, 4, 5):
            return "Spring transition — snowmelt runoff and spring tide ranges peak"
        return "Fall transition — late-season tropical tail risk and seasonal SST decline"

    def _assessment(
        self,
        stations: list[StationReading],
        surge: float,
        tidal: float,
        heatwave: float,
    ) -> OceanAssessment:
        surge_status = (
            "elevated storm surge / anomalous water levels detected"
            if surge >= 0.45
            else "water levels tracking near astronomical predictions"
        )
        tidal_status = (
            "spring tide extremes exceeding normal ranges — draft/berthing constraints likely"
            if tidal >= 0.35
            else "tidal ranges within normal seasonal bounds"
        )
        heat_status = (
            "marine heatwave signal — SST anomalies above seasonal norms"
            if heatwave >= 0.35
            else "sea-surface temperatures near seasonal norms"
        )
        draft_risk = "normal"
        low_stations = [
            s for s in stations
            if s.tidal_range_ft is not None and s.normal_range_ft
            and s.tidal_range_ft > s.normal_range_ft * 1.2
        ]
        if low_stations:
            draft_risk = (
                "elevated — "
                + ", ".join(s.name for s in low_stations[:3])
                + " showing amplified tidal swing"
            )

        dominant = "tidal/coastal conditions nominal"
        if surge >= tidal and surge >= heatwave and surge >= 0.35:
            dominant = "storm surge / anomalous water levels"
        elif tidal >= heatwave and tidal >= 0.35:
            dominant = "spring tide extremes"
        elif heatwave >= 0.35:
            dominant = "marine heatwave / SST anomaly"

        return OceanAssessment(
            season_context=self._season_context(),
            dominant_hazard=dominant,
            storm_surge_status=surge_status,
            tidal_extreme_status=tidal_status,
            marine_heatwave_status=heat_status,
            shipping_draft_risk=draft_risk,
        )

    def _expert_summary(
        self,
        assessment: OceanAssessment,
        surge: float,
        tidal: float,
        heatwave: float,
        disruption: float,
        label: str,
    ) -> str:
        parts = [
            f"Coastal/port disruption is {label.lower()} (score {disruption:.2f}).",
            assessment.season_context + ".",
            f"Dominant hazard: {assessment.dominant_hazard}.",
            f"Storm surge {surge:.2f}: {assessment.storm_surge_status}.",
            f"Tidal extremes {tidal:.2f}: {assessment.tidal_extreme_status}.",
            f"Marine heatwave {heatwave:.2f}: {assessment.marine_heatwave_status}.",
            f"Shipping draft risk: {assessment.shipping_draft_risk}.",
        ]
        return " ".join(parts)

    def analyze(self) -> OceanographyReport:
        stations = self.fetch_station_readings()
        now = datetime.now(timezone.utc)

        surge = self._storm_surge_score(stations)
        tidal = self._tidal_extreme_score(stations)
        heatwave = self._marine_heatwave_score(stations, now)
        disruption = self._port_disruption_score(surge, tidal, heatwave, stations)
        assessment = self._assessment(stations, surge, tidal, heatwave)

        label = (
            "Critical" if disruption >= 0.75 else
            "Elevated" if disruption >= 0.55 else
            "Moderate" if disruption >= 0.35 else
            "Normal"
        )

        headline = self._national_headline(stations, assessment)
        summary = self._expert_summary(assessment, surge, tidal, heatwave, disruption, label)
        signals = self._market_signals(surge, tidal, heatwave, disruption, stations, assessment)
        recs = self._recommendations(stations, surge, tidal, heatwave, disruption, assessment)

        return OceanographyReport(
            region="US",
            region_name="United States Coastal Waters (NOAA CO-OPS)",
            stations=stations,
            assessment=assessment,
            storm_surge_score=surge,
            tidal_extreme_score=tidal,
            marine_heatwave_score=heatwave,
            port_disruption_score=disruption,
            disruption_label=label,
            national_headline=headline,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source="NOAA CO-OPS API (api.tidesandcurrents.noaa.gov)",
        )

    @staticmethod
    def _national_headline(
        stations: list[StationReading], assessment: OceanAssessment
    ) -> str:
        ok = sum(1 for s in stations if s.data_ok)
        return (
            f"{ok}/{len(stations)} NOAA tide stations reporting — "
            f"dominant hazard: {assessment.dominant_hazard}"
        )

    @staticmethod
    def _market_signals(
        surge: float,
        tidal: float,
        heatwave: float,
        disruption: float,
        stations: list[StationReading],
        assessment: OceanAssessment,
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        if surge >= 0.45:
            signals.append({
                "sector": "Insurance / Coastal Property",
                "tickers": ["ALL", "TRV", "PGR", "CB"],
                "bias": "BEARISH" if surge >= 0.70 else "NEUTRAL",
                "reason": f"Storm surge anomaly score {surge:.2f} — {assessment.storm_surge_status}",
            })
            signals.append({
                "sector": "Gulf Energy / LNG Terminals",
                "tickers": ["LNG", "XLE", "VLO", "MPC"],
                "bias": "NEUTRAL",
                "reason": "Elevated water levels at Gulf Coast stations — terminal/refinery flood risk",
            })

        if tidal >= 0.35:
            signals.append({
                "sector": "Shipping / Port Logistics",
                "tickers": ["ZIM", "MATX", "GOGL", "XPO"],
                "bias": "NEUTRAL",
                "reason": f"Tidal extreme score {tidal:.2f} — {assessment.shipping_draft_risk}",
            })

        if heatwave >= 0.35:
            signals.append({
                "sector": "Fisheries / Seafood",
                "tickers": ["BUKS.OL", "MHG.OL"],
                "bias": "BEARISH" if heatwave >= 0.65 else "NEUTRAL",
                "reason": f"Marine heatwave score {heatwave:.2f} — {assessment.marine_heatwave_status}",
            })

        if disruption >= 0.50:
            signals.append({
                "sector": "Coastal Tourism / Cruise",
                "tickers": ["CCL", "RCL", "NCLH"],
                "bias": "BEARISH" if disruption >= 0.70 else "NEUTRAL",
                "reason": f"Coastal disruption score {disruption:.2f} — port/beach conditions degraded",
            })

        if not signals:
            signals.append({
                "sector": "Coastal / Marine",
                "tickers": ["ZIM", "XLE"],
                "bias": "NEUTRAL",
                "reason": "No significant tidal, surge, or SST anomalies detected",
            })

        return signals

    @staticmethod
    def _recommendations(
        stations: list[StationReading],
        surge: float,
        tidal: float,
        heatwave: float,
        disruption: float,
        assessment: OceanAssessment,
    ) -> list[str]:
        recs = [
            assessment.season_context,
            f"Dominant hazard: {assessment.dominant_hazard}",
            f"Storm surge: {assessment.storm_surge_status}",
            f"Tidal extremes: {assessment.tidal_extreme_status}",
            f"Marine heatwave: {assessment.marine_heatwave_status}",
            f"Shipping draft risk: {assessment.shipping_draft_risk}",
        ]
        surging = sorted(
            [s for s in stations if s.surge_anomaly_ft is not None],
            key=lambda s: s.surge_anomaly_ft or 0,
            reverse=True,
        )[:3]
        if surging:
            recs.append(
                "Largest surge anomalies: "
                + ", ".join(f"{s.name} {s.surge_anomaly_ft:+.2f} ft" for s in surging)
            )
        ranged = sorted(
            [s for s in stations if s.tidal_range_ft is not None],
            key=lambda s: s.tidal_range_ft or 0,
            reverse=True,
        )[:3]
        if ranged:
            recs.append(
                "Largest tidal ranges: "
                + ", ".join(f"{s.name} {s.tidal_range_ft:.1f} ft" for s in ranged)
            )
        if surge >= 0.65:
            recs.append("Storm surge critical — monitor Gulf/Atlantic coastal insurance and energy exposure")
        if tidal >= 0.65:
            recs.append("Extreme spring tides — expect port draft restrictions and berthing schedule shifts")
        if heatwave >= 0.65:
            recs.append("Marine heatwave signal — fishery yield and coastal ecosystem stress risk")
        return recs

    def to_dict(self, report: OceanographyReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "dashboard": DASHBOARD_URL,
                "secondary_dashboard": SECONDARY_DASHBOARD_URL,
                "agent": "Oceanography Expert",
                "region": report.region,
                "region_name": report.region_name,
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "national_headline": report.national_headline,
                "expert_summary": report.expert_summary,
            },
            "assessment": {
                "season_context": a.season_context,
                "dominant_hazard": a.dominant_hazard,
                "storm_surge_status": a.storm_surge_status,
                "tidal_extreme_status": a.tidal_extreme_status,
                "marine_heatwave_status": a.marine_heatwave_status,
                "shipping_draft_risk": a.shipping_draft_risk,
            },
            "stations": [
                {
                    "station_id": s.station_id,
                    "name": s.name,
                    "lat": s.lat,
                    "lon": s.lon,
                    "next_high_ft": s.next_high_ft,
                    "next_high_time": s.next_high_time,
                    "next_low_ft": s.next_low_ft,
                    "next_low_time": s.next_low_time,
                    "tidal_range_ft": s.tidal_range_ft,
                    "normal_range_ft": s.normal_range_ft,
                    "observed_level_ft": s.observed_level_ft,
                    "predicted_level_ft": s.predicted_level_ft,
                    "surge_anomaly_ft": s.surge_anomaly_ft,
                    "water_temp_f": s.water_temp_f,
                    "data_ok": s.data_ok,
                }
                for s in report.stations
            ],
            "metrics": {
                "storm_surge_score": report.storm_surge_score,
                "tidal_extreme_score": report.tidal_extreme_score,
                "marine_heatwave_score": report.marine_heatwave_score,
                "port_disruption_score": report.port_disruption_score,
                "disruption_label": report.disruption_label,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def station_catalog(self) -> dict[str, Any]:
        """Reference catalog of NOAA CO-OPS stations and public tide dashboards."""
        return {
            "dashboard": DASHBOARD_URL,
            "secondary_dashboard": SECONDARY_DASHBOARD_URL,
            "api_base": API_BASE,
            "stations": [
                {
                    "station_id": station_id,
                    "name": name,
                    "lat": lat,
                    "lon": lon,
                    "noaa_station_page": f"https://tidesandcurrents.noaa.gov/stationhome.html?id={station_id}",
                    "normal_tidal_range_ft": NORMAL_TIDAL_RANGE_FT.get(name),
                }
                for station_id, lat, lon, name in self.stations
            ],
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog_path = output.parent / "noaa_tide_stations.json"
            catalog_path.write_text(
                json.dumps(self.station_catalog(), indent=2),
                encoding="utf-8",
            )
        return result


def run_oceanography_analysis(output: Path | None = None) -> dict[str, Any]:
    return OceanographyExpert().run(output=output)
