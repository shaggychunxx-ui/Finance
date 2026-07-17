"""
FRED Macroeconomic Analyst Agent
=================================
Economist analysis of the Federal Reserve Bank of St. Louis's FRED
(Federal Reserve Economic Data) dashboard: policy rates, inflation,
labor market, growth, and the yield curve.

Dashboard: https://fred.stlouisfed.org/
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agents.base import BaseExpert

HEADERS = {"User-Agent": "Finance-FRED-Analyst/1.0 (shaggychunxx@gmail.com)"}
FRED_SERIES_URL = "https://api.stlouisfed.org/fred/series/observations"
DASHBOARD_URL = "https://fred.stlouisfed.org/"

SERIES: dict[str, dict[str, str]] = {
    "FEDFUNDS": {"label": "Effective Federal Funds Rate", "unit": "%", "category": "policy"},
    "CPIAUCSL": {"label": "CPI (All Urban Consumers, YoY)", "unit": "%", "category": "inflation"},
    "UNRATE": {"label": "Unemployment Rate", "unit": "%", "category": "labor"},
    "GDP": {"label": "Gross Domestic Product", "unit": "$B", "category": "growth"},
    "T10Y2Y": {"label": "10Y-2Y Treasury Spread", "unit": "pp", "category": "yield_curve"},
    "DGS10": {"label": "10-Year Treasury Yield", "unit": "%", "category": "rates"},
    "MORTGAGE30US": {"label": "30-Year Fixed Mortgage Rate", "unit": "%", "category": "housing"},
    "M2SL": {"label": "M2 Money Supply", "unit": "$B", "category": "liquidity"},
}

FRED_VIEWS: list[dict[str, Any]] = [
    {
        "id": "fed_funds",
        "name": "Federal Funds Rate",
        "url": f"{DASHBOARD_URL}series/FEDFUNDS",
        "series_id": "FEDFUNDS",
    },
    {
        "id": "cpi",
        "name": "Consumer Price Index",
        "url": f"{DASHBOARD_URL}series/CPIAUCSL",
        "series_id": "CPIAUCSL",
    },
    {
        "id": "unemployment",
        "name": "Unemployment Rate",
        "url": f"{DASHBOARD_URL}series/UNRATE",
        "series_id": "UNRATE",
    },
    {
        "id": "gdp",
        "name": "Gross Domestic Product",
        "url": f"{DASHBOARD_URL}series/GDP",
        "series_id": "GDP",
    },
    {
        "id": "yield_curve",
        "name": "10Y-2Y Treasury Spread",
        "url": f"{DASHBOARD_URL}series/T10Y2Y",
        "series_id": "T10Y2Y",
    },
    {
        "id": "ten_year",
        "name": "10-Year Treasury Yield",
        "url": f"{DASHBOARD_URL}series/DGS10",
        "series_id": "DGS10",
    },
    {
        "id": "mortgage",
        "name": "30-Year Fixed Mortgage Rate",
        "url": f"{DASHBOARD_URL}series/MORTGAGE30US",
        "series_id": "MORTGAGE30US",
    },
    {
        "id": "m2",
        "name": "M2 Money Supply",
        "url": f"{DASHBOARD_URL}series/M2SL",
        "series_id": "M2SL",
    },
]

# Calibrated proxy values used when the FRED API is unavailable or rate-limited
# (approximate 2024-2025 readings, refreshed periodically).
PROXY_LATEST: dict[str, tuple[str, float]] = {
    "FEDFUNDS": ("2025-05-01", 4.33),
    "CPIAUCSL": ("2025-05-01", 2.9),
    "UNRATE": ("2025-05-01", 4.2),
    "GDP": ("2025-01-01", 29017.0),
    "T10Y2Y": ("2025-06-01", 0.50),
    "DGS10": ("2025-06-01", 4.40),
    "MORTGAGE30US": ("2025-06-01", 6.85),
    "M2SL": ("2025-04-01", 21800.0),
}


@dataclass
class SeriesObservation:
    series_id: str
    label: str
    unit: str
    category: str
    date: str
    value: float
    prior_value: float | None = None
    change: float | None = None
    source: str = "FRED API"


@dataclass
class FredReport:
    dashboard_views: list[dict[str, Any]]
    observations: list[SeriesObservation]
    fed_funds_rate: float
    cpi_yoy_pct: float
    unemployment_rate: float
    yield_curve_spread: float
    ten_year_yield: float
    mortgage_rate: float
    policy_stance: str
    inflation_regime: str
    recession_risk_score: float
    recession_risk_label: str
    expert_summary: str
    macro_assessment: dict[str, str]
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FredMacroeconomicAnalyst(BaseExpert):
    """Economist analyst for the FRED (Federal Reserve Economic Data) dashboard."""

    def __init__(
        self,
        config_path: Path | None = None,
        *,
        pipeline_context: dict | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="fred")
        self.config = self._load_config(config_path)
        self.fred_api_key = self.config.get("fred_api_key", "").strip()

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
    def _to_float(value: Any, default: float | None = None) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _fetch_series(self, series_id: str, *, limit: int = 2) -> list[dict[str, Any]]:
        if not self.fred_api_key:
            return []
        params = {
            "series_id": series_id,
            "api_key": self.fred_api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": limit,
        }
        try:
            resp = requests.get(FRED_SERIES_URL, headers=HEADERS, params=params, timeout=35)
            if resp.status_code == 429:
                return []
            resp.raise_for_status()
            return resp.json().get("observations", [])
        except Exception:
            return []

    def _fetch_observation(self, series_id: str) -> SeriesObservation | None:
        meta = SERIES[series_id]
        rows = self._fetch_series(series_id, limit=2)
        parsed = []
        for row in rows:
            val = self._to_float(row.get("value"))
            if val is not None:
                parsed.append((row.get("date", ""), val))
        if not parsed:
            return None
        date, value = parsed[0]
        prior = parsed[1][1] if len(parsed) > 1 else None
        change = round(value - prior, 3) if prior is not None else None
        return SeriesObservation(
            series_id=series_id,
            label=meta["label"],
            unit=meta["unit"],
            category=meta["category"],
            date=date,
            value=value,
            prior_value=prior,
            change=change,
        )

    @staticmethod
    def _proxy_observation(series_id: str) -> SeriesObservation:
        meta = SERIES[series_id]
        date, value = PROXY_LATEST[series_id]
        return SeriesObservation(
            series_id=series_id,
            label=meta["label"],
            unit=meta["unit"],
            category=meta["category"],
            date=date,
            value=value,
            source="Calibrated proxy feed",
        )

    def _fetch_all_series(self) -> tuple[list[SeriesObservation], list[str]]:
        observations: list[SeriesObservation] = []
        sources: list[str] = []
        used_proxy = False
        for series_id in SERIES:
            obs = self._fetch_observation(series_id)
            if obs is None:
                obs = self._proxy_observation(series_id)
                used_proxy = True
            else:
                if "FRED API" not in sources:
                    sources.append("FRED API")
            observations.append(obs)
            time.sleep(0.1)
        if used_proxy:
            sources.append("Calibrated proxy feed")
        return observations, sources

    @staticmethod
    def _by_id(observations: list[SeriesObservation], series_id: str) -> SeriesObservation | None:
        return next((o for o in observations if o.series_id == series_id), None)

    def _policy_stance(self, fed_funds: float, change: float | None) -> str:
        if fed_funds >= 5.0:
            base = "Restrictive policy stance"
        elif fed_funds >= 3.0:
            base = "Moderately restrictive policy stance"
        elif fed_funds >= 1.5:
            base = "Neutral-to-accommodative policy stance"
        else:
            base = "Accommodative policy stance"
        if change is not None and change > 0:
            base += " (recently hiking)"
        elif change is not None and change < 0:
            base += " (recently cutting)"
        return base

    def _inflation_regime(self, cpi_yoy: float) -> str:
        if cpi_yoy >= 4.0:
            return f"Elevated inflation ({cpi_yoy:.1f}% YoY) — above Fed's 2% target"
        if cpi_yoy >= 2.5:
            return f"Above-target inflation ({cpi_yoy:.1f}% YoY) — gradual disinflation"
        if cpi_yoy >= 1.5:
            return f"Near-target inflation ({cpi_yoy:.1f}% YoY)"
        return f"Below-target inflation ({cpi_yoy:.1f}% YoY) — disinflationary risk"

    def _recession_risk(
        self, yield_spread: float, unemployment: float, unemployment_change: float | None
    ) -> tuple[float, str]:
        score = 0.0
        if yield_spread < 0:
            score += 45.0
        elif yield_spread < 0.25:
            score += 20.0
        if unemployment_change is not None and unemployment_change > 0.3:
            score += 30.0
        elif unemployment_change is not None and unemployment_change > 0.1:
            score += 15.0
        if unemployment >= 5.0:
            score += 15.0
        score = min(100.0, score)
        if score >= 55:
            label = "Elevated recession risk"
        elif score >= 25:
            label = "Moderate recession risk"
        else:
            label = "Low recession risk"
        return round(score, 1), label

    def _macro_assessment(
        self,
        observations: list[SeriesObservation],
        policy_stance: str,
        inflation_regime: str,
        recession_label: str,
    ) -> dict[str, str]:
        mortgage = self._by_id(observations, "MORTGAGE30US")
        m2 = self._by_id(observations, "M2SL")
        ten_year = self._by_id(observations, "DGS10")
        curve = self._by_id(observations, "T10Y2Y")

        curve_signal = "Yield curve data unavailable"
        if curve is not None:
            if curve.value < 0:
                curve_signal = f"Inverted curve ({curve.value:+.2f}pp) — classic recession warning signal"
            else:
                curve_signal = f"Normal (upward-sloping) curve ({curve.value:+.2f}pp)"

        housing_signal = "Housing data unavailable"
        if mortgage is not None:
            if mortgage.value >= 6.5:
                housing_signal = f"30Y mortgage at {mortgage.value:.2f}% — housing affordability pressure"
            else:
                housing_signal = f"30Y mortgage at {mortgage.value:.2f}% — moderate borrowing costs"

        liquidity_signal = "Money supply data unavailable"
        if m2 is not None:
            liquidity_signal = f"M2 money supply at ${m2.value:,.0f}B"

        rates_signal = "Treasury yield data unavailable"
        if ten_year is not None:
            rates_signal = f"10-year Treasury yield at {ten_year.value:.2f}%"

        return {
            "policy_stance": policy_stance,
            "inflation_regime": inflation_regime,
            "yield_curve": curve_signal,
            "housing_conditions": housing_signal,
            "liquidity_conditions": liquidity_signal,
            "rates_backdrop": rates_signal,
            "recession_outlook": recession_label,
            "dashboard_note": f"FRED (Federal Reserve Economic Data) tracked at {DASHBOARD_URL}",
        }

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

    def _market_signals(
        self,
        *,
        fed_funds: float,
        fed_funds_change: float | None,
        yield_spread: float,
        cpi_yoy: float,
        recession_score: float,
        recession_label: str,
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_impact_signal

        signals: list[dict[str, Any]] = []

        if fed_funds_change is not None and fed_funds_change < 0:
            signals.append(
                build_market_impact_signal(
                    sector="Rates",
                    tickers=["TLT", "XLF", "SPY"],
                    bias="BULLISH",
                    reason=f"Fed cutting rates (fed funds {fed_funds:.2f}%, Δ{fed_funds_change:+.2f}pp)",
                    confidence=0.68,
                    evidence={"fed_funds_pct": fed_funds, "change_pct": fed_funds_change},
                    domain_context="fred",
                )
            )
        elif fed_funds_change is not None and fed_funds_change > 0:
            signals.append(
                build_market_impact_signal(
                    sector="Rates",
                    tickers=["TLT", "XLU", "SPY"],
                    bias="BEARISH",
                    reason=f"Fed hiking rates (fed funds {fed_funds:.2f}%, Δ{fed_funds_change:+.2f}pp)",
                    confidence=0.65,
                    evidence={"fed_funds_pct": fed_funds, "change_pct": fed_funds_change},
                    domain_context="fred",
                )
            )

        if yield_spread < 0:
            signals.append(
                build_market_impact_signal(
                    sector="Yield Curve",
                    tickers=["SPY", "IWM", "TLT"],
                    bias="BEARISH",
                    reason=f"Inverted 10Y-2Y curve ({yield_spread:+.2f}pp) signals rising recession risk",
                    confidence=min(0.9, 0.5 + recession_score / 100),
                    evidence={"yield_spread_pp": yield_spread, "recession_score": recession_score},
                    domain_context="fred",
                )
            )

        if cpi_yoy >= 3.5:
            signals.append(
                build_market_impact_signal(
                    sector="Inflation",
                    tickers=["GLD", "USO", "XLE"],
                    bias="BULLISH",
                    reason=f"CPI running hot at {cpi_yoy:.1f}% YoY — inflation-hedge tailwind",
                    confidence=0.55,
                    evidence={"cpi_yoy_pct": cpi_yoy},
                    domain_context="fred",
                )
            )
        elif cpi_yoy <= 2.0:
            signals.append(
                build_market_impact_signal(
                    sector="Inflation",
                    tickers=["QQQ", "XLK"],
                    bias="BULLISH",
                    reason=f"CPI cooling to {cpi_yoy:.1f}% YoY — supports rate-cut path and growth equities",
                    confidence=0.5,
                    evidence={"cpi_yoy_pct": cpi_yoy},
                    domain_context="fred",
                )
            )

        if recession_score >= 55:
            signals.append(
                build_market_impact_signal(
                    sector="Macro",
                    tickers=["SPY", "HYG", "VIXY"],
                    bias="BEARISH",
                    reason=f"{recession_label} ({recession_score}) — elevated macro downside risk",
                    confidence=min(0.9, 0.45 + recession_score / 150),
                    evidence={"recession_score": recession_score},
                    domain_context="fred",
                )
            )

        return self._adjust_market_signals(signals)

    def analyze(self) -> FredReport:
        time.sleep(0.2)
        observations, sources = self._fetch_all_series()
        if not sources:
            sources.append("Calibrated proxy feed")

        fed_funds_obs = self._by_id(observations, "FEDFUNDS")
        cpi_obs = self._by_id(observations, "CPIAUCSL")
        unrate_obs = self._by_id(observations, "UNRATE")
        curve_obs = self._by_id(observations, "T10Y2Y")
        ten_year_obs = self._by_id(observations, "DGS10")
        mortgage_obs = self._by_id(observations, "MORTGAGE30US")

        fed_funds = fed_funds_obs.value if fed_funds_obs else 0.0
        fed_funds_change = fed_funds_obs.change if fed_funds_obs else None
        cpi_yoy = cpi_obs.value if cpi_obs else 0.0
        unemployment = unrate_obs.value if unrate_obs else 0.0
        unemployment_change = unrate_obs.change if unrate_obs else None
        yield_spread = curve_obs.value if curve_obs else 0.0
        ten_year = ten_year_obs.value if ten_year_obs else 0.0
        mortgage = mortgage_obs.value if mortgage_obs else 0.0

        policy_stance = self._policy_stance(fed_funds, fed_funds_change)
        inflation_regime = self._inflation_regime(cpi_yoy)
        recession_score, recession_label = self._recession_risk(
            yield_spread, unemployment, unemployment_change
        )
        assessment = self._macro_assessment(
            observations, policy_stance, inflation_regime, recession_label
        )

        summary = (
            f"FRED macroeconomic dashboard ({DASHBOARD_URL}). "
            f"Fed funds {fed_funds:.2f}%, CPI {cpi_yoy:.1f}% YoY, unemployment {unemployment:.1f}%, "
            f"10Y-2Y spread {yield_spread:+.2f}pp. {policy_stance}. {recession_label} ({recession_score})."
        )

        recs = [
            summary,
            f"Recession risk score: {recession_score} ({recession_label})",
            assessment["policy_stance"],
            assessment["inflation_regime"],
            assessment["yield_curve"],
            assessment["housing_conditions"],
            assessment["liquidity_conditions"],
            assessment["rates_backdrop"],
            assessment["dashboard_note"],
        ]
        for obs in observations:
            change_txt = f" (Δ{obs.change:+.2f})" if obs.change is not None else ""
            recs.append(f"{obs.label}: {obs.value:,.2f}{obs.unit}{change_txt} — {obs.date}")
        if "Calibrated proxy feed" in sources:
            recs.append("Set fred_api_key in config.json for live FRED API data")

        return FredReport(
            dashboard_views=FRED_VIEWS,
            observations=observations,
            fed_funds_rate=fed_funds,
            cpi_yoy_pct=cpi_yoy,
            unemployment_rate=unemployment,
            yield_curve_spread=yield_spread,
            ten_year_yield=ten_year,
            mortgage_rate=mortgage,
            policy_stance=policy_stance,
            inflation_regime=inflation_regime,
            recession_risk_score=recession_score,
            recession_risk_label=recession_label,
            expert_summary=summary,
            macro_assessment=assessment,
            market_signals=self._market_signals(
                fed_funds=fed_funds,
                fed_funds_change=fed_funds_change,
                yield_spread=yield_spread,
                cpi_yoy=cpi_yoy,
                recession_score=recession_score,
                recession_label=recession_label,
            ),
            recommendations=recs,
            data_sources=sources,
        )

    def to_dict(self, report: FredReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "FRED Macroeconomic Analyst",
                "dashboard": DASHBOARD_URL,
                "analyzed_at": report.analyzed_at,
                "data_sources": report.data_sources,
                "expert_summary": report.expert_summary,
            },
            "metrics": {
                "fed_funds_rate_pct": report.fed_funds_rate,
                "cpi_yoy_pct": report.cpi_yoy_pct,
                "unemployment_rate_pct": report.unemployment_rate,
                "yield_curve_spread_pp": report.yield_curve_spread,
                "ten_year_yield_pct": report.ten_year_yield,
                "mortgage_rate_pct": report.mortgage_rate,
                "recession_risk_score": report.recession_risk_score,
                "recession_risk_label": report.recession_risk_label,
            },
            "dashboard_views": report.dashboard_views,
            "observations": [
                {
                    "series_id": o.series_id,
                    "label": o.label,
                    "unit": o.unit,
                    "category": o.category,
                    "date": o.date,
                    "value": o.value,
                    "prior_value": o.prior_value,
                    "change": o.change,
                    "source": o.source,
                }
                for o in report.observations
            ],
            "macro_assessment": report.macro_assessment,
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        report = self.analyze()
        result = self.to_dict(report)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            views_path = output.parent / "fred_series_views.json"
            views_path.write_text(
                json.dumps(report.dashboard_views, indent=2),
                encoding="utf-8",
            )
        return result


def run_fred_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return FredMacroeconomicAnalyst(pipeline_context=pipeline_context).run(output=output)
