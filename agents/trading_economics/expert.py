"""
Trading Economics Macro Expert Agent
=====================================
Expert macroeconomic analysis from the Trading Economics public API:
GDP growth, inflation, policy interest rates, unemployment, and trade
balance across the countries covered by the free `guest:guest` API key.

API: https://api.tradingeconomics.com/
Docs: https://docs.tradingeconomics.com/
GitHub: https://github.com/tradingeconomics/tradingeconomics
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agents.base import BaseExpert

HEADERS = {"User-Agent": "Finance-Trading-Economics-Expert/1.0 (shaggychunxx@gmail.com)"}
BASE_URL = "https://api.tradingeconomics.com"
GUEST_CREDENTIALS = "guest:guest"

# The free "guest:guest" Trading Economics API key is restricted to these
# five countries; any other country slug returns an empty/unauthorized
# response.
GUEST_COUNTRIES: dict[str, str] = {
    "mexico": "Mexico",
    "sweden": "Sweden",
    "new-zealand": "New Zealand",
    "thailand": "Thailand",
    "switzerland": "Switzerland",
}

# Cross-market proxies used to translate a country's macro regime into a
# tradeable sector/FX signal.
COUNTRY_MARKETS: dict[str, dict[str, str]] = {
    "Mexico": {"equity_etf": "EWW", "fx_pair": "USD/MXN"},
    "Sweden": {"equity_etf": "EWD", "fx_pair": "USD/SEK"},
    "New Zealand": {"equity_etf": "ENZL", "fx_pair": "NZD/USD"},
    "Thailand": {"equity_etf": "THD", "fx_pair": "USD/THB"},
    "Switzerland": {"equity_etf": "EWL", "fx_pair": "USD/CHF"},
}

TRACKED_CATEGORIES = [
    "GDP Growth Rate",
    "Inflation Rate",
    "Interest Rate",
    "Unemployment Rate",
    "Balance of Trade",
]

TRADING_ECONOMICS_RESOURCES: list[dict[str, Any]] = [
    {
        "id": "guest_country",
        "name": "Guest Country Snapshot",
        "url": f"{BASE_URL}/country/{{country}}?c={GUEST_CREDENTIALS}",
        "description": "Latest indicator values for a guest-tier country",
    },
    {
        "id": "indicators",
        "name": "Indicators Catalog",
        "url": f"{BASE_URL}/indicators?c={GUEST_CREDENTIALS}",
        "description": "Full list of indicator categories tracked by Trading Economics",
    },
    {
        "id": "countries",
        "name": "Countries Catalog",
        "url": f"{BASE_URL}/country?c={GUEST_CREDENTIALS}",
        "description": "Metadata for all countries covered by the API",
    },
    {
        "id": "calendar",
        "name": "Economic Calendar",
        "url": f"{BASE_URL}/calendar?c={GUEST_CREDENTIALS}",
        "description": "Upcoming/recent economic releases (paid tiers only)",
    },
]

# Calibrated proxy snapshot used when the live API is unreachable (blocked
# network, rate limit, or credential issue). Values are indicative reference
# points, not live data, and are always labeled as such in the report.
PROXY_SNAPSHOT: dict[str, dict[str, tuple[float, float, str]]] = {
    "Mexico": {
        "GDP Growth Rate": (0.2, 0.6, "%"),
        "Inflation Rate": (4.6, 4.7, "%"),
        "Interest Rate": (10.75, 11.0, "%"),
        "Unemployment Rate": (2.7, 2.6, "%"),
        "Balance of Trade": (-1.2, -0.4, "USD Billion"),
    },
    "Sweden": {
        "GDP Growth Rate": (0.3, 0.1, "%"),
        "Inflation Rate": (1.9, 2.3, "%"),
        "Interest Rate": (2.25, 2.5, "%"),
        "Unemployment Rate": (8.4, 8.3, "%"),
        "Balance of Trade": (7.0, 6.2, "SEK Billion"),
    },
    "New Zealand": {
        "GDP Growth Rate": (0.8, -0.1, "%"),
        "Inflation Rate": (2.2, 2.5, "%"),
        "Interest Rate": (3.25, 3.5, "%"),
        "Unemployment Rate": (5.1, 5.2, "%"),
        "Balance of Trade": (-0.2, -0.9, "NZD Billion"),
    },
    "Thailand": {
        "GDP Growth Rate": (2.1, 1.6, "%"),
        "Inflation Rate": (0.4, 0.9, "%"),
        "Interest Rate": (1.5, 1.75, "%"),
        "Unemployment Rate": (0.9, 0.9, "%"),
        "Balance of Trade": (1.1, 0.5, "USD Billion"),
    },
    "Switzerland": {
        "GDP Growth Rate": (0.5, 0.3, "%"),
        "Inflation Rate": (0.3, 0.6, "%"),
        "Interest Rate": (0.0, 0.25, "%"),
        "Unemployment Rate": (2.7, 2.7, "%"),
        "Balance of Trade": (4.5, 3.9, "CHF Billion"),
    },
}


@dataclass
class IndicatorReading:
    category: str
    latest_value: float | None
    previous_value: float | None
    unit: str
    date: str = ""


@dataclass
class CountryMacro:
    country: str
    indicators: dict[str, IndicatorReading]
    regime: str
    regime_score: float
    summary: str


@dataclass
class TradingEconomicsReport:
    countries: list[CountryMacro]
    composite_score: float
    composite_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TradingEconomicsExpert(BaseExpert):
    """Macro analyst covering the Trading Economics free guest-tier countries."""

    def __init__(self, *, pipeline_context: dict | None = None) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="trading-economics")

    def _fetch_country(self, slug: str) -> list[dict[str, Any]] | None:
        try:
            resp = requests.get(
                f"{BASE_URL}/country/{slug}",
                params={"c": GUEST_CREDENTIALS, "f": "json"},
                headers=HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else None
        except Exception:
            return None

    @staticmethod
    def _to_float(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _parse_indicators(self, rows: list[dict[str, Any]]) -> dict[str, IndicatorReading]:
        indicators: dict[str, IndicatorReading] = {}
        for row in rows:
            category = str(row.get("Category", "")).strip()
            if category not in TRACKED_CATEGORIES or category in indicators:
                continue
            indicators[category] = IndicatorReading(
                category=category,
                latest_value=self._to_float(row.get("LatestValue")),
                previous_value=self._to_float(row.get("PreviousValue")),
                unit=str(row.get("Unit", "")),
                date=str(row.get("DateTime", row.get("LatestValueDate", ""))),
            )
        return indicators

    @staticmethod
    def _proxy_indicators(country: str) -> dict[str, IndicatorReading]:
        rows = PROXY_SNAPSHOT.get(country, {})
        return {
            category: IndicatorReading(
                category=category,
                latest_value=latest,
                previous_value=previous,
                unit=unit,
                date="proxy",
            )
            for category, (latest, previous, unit) in rows.items()
        }

    def _fetch_all_countries(self) -> tuple[dict[str, dict[str, IndicatorReading]], list[str]]:
        by_country: dict[str, dict[str, IndicatorReading]] = {}
        sources: list[str] = []
        live_hits = 0
        for slug, country in GUEST_COUNTRIES.items():
            rows = self._fetch_country(slug)
            if rows:
                indicators = self._parse_indicators(rows)
                if indicators:
                    by_country[country] = indicators
                    live_hits += 1
                    continue
            by_country[country] = self._proxy_indicators(country)

        if live_hits:
            sources.append(f"Trading Economics guest API ({live_hits}/{len(GUEST_COUNTRIES)} countries)")
        if live_hits < len(GUEST_COUNTRIES):
            sources.append("Calibrated macro proxy (API unavailable for remaining countries)")
        return by_country, sources

    @staticmethod
    def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
        return max(low, min(high, value))

    def _score_regime(self, indicators: dict[str, IndicatorReading]) -> tuple[str, float]:
        score = 0.0

        rate = indicators.get("Interest Rate")
        if rate and rate.latest_value is not None and rate.previous_value is not None:
            delta = rate.latest_value - rate.previous_value
            score += self._clamp(delta * 1.5)

        inflation = indicators.get("Inflation Rate")
        if inflation and inflation.latest_value is not None:
            if inflation.latest_value >= 3.5:
                score += 0.35
            elif inflation.latest_value <= 1.0:
                score -= 0.25

        gdp = indicators.get("GDP Growth Rate")
        if gdp and gdp.latest_value is not None:
            if gdp.latest_value < 0:
                score -= 0.35
            elif gdp.latest_value >= 2.5:
                score += 0.1

        score = round(self._clamp(score), 4)
        label = (
            "Tightening" if score >= 0.35 else
            "Easing" if score <= -0.25 else
            "Neutral"
        )
        return label, score

    @staticmethod
    def _country_summary(country: str, indicators: dict[str, IndicatorReading], regime: str, score: float) -> str:
        parts = []
        for cat in TRACKED_CATEGORIES:
            reading = indicators.get(cat)
            if reading and reading.latest_value is not None:
                parts.append(f"{cat} {reading.latest_value:.2f}{reading.unit or ''}".strip())
        detail = ", ".join(parts) if parts else "no indicators available"
        return f"{country}: {regime} (score {score:+.2f}) — {detail}"

    def _market_signal(self, country: str, regime: str, score: float) -> dict[str, Any]:
        from agent_signal_logic import build_market_signal

        market = COUNTRY_MARKETS.get(country, {})
        etf = market.get("equity_etf")
        fx = market.get("fx_pair")
        tickers = [t for t in (etf,) if t]

        if regime == "Tightening":
            bias = "BEARISH"
            reason = (
                f"{country} macro regime tightening (score {score:+.2f}) — rising rates "
                f"pressure local equities ({etf}); firmer local currency vs. USD ({fx})"
            )
        elif regime == "Easing":
            bias = "BULLISH"
            reason = (
                f"{country} macro regime easing (score {score:+.2f}) — falling rates "
                f"support local equities ({etf}); softer local currency vs. USD ({fx})"
            )
        else:
            bias = "NEUTRAL"
            reason = f"{country} macro regime neutral (score {score:+.2f}) — no strong policy tilt"

        return build_market_signal(
            sector=f"{country} Macro",
            tickers=tickers,
            bias=bias,
            reason=reason,
            confidence=min(0.8, 0.45 + abs(score) * 0.5),
            evidence={"regime_score": score, "fx_pair": fx},
        )

    def _composite(self, countries: list[CountryMacro]) -> tuple[float, str]:
        if not countries:
            return 0.0, "Neutral"
        avg = round(sum(c.regime_score for c in countries) / len(countries), 4)
        label = (
            "Global tightening bias" if avg >= 0.30 else
            "Global easing bias" if avg <= -0.20 else
            "Mixed / neutral policy stance"
        )
        return avg, label

    def analyze(self) -> TradingEconomicsReport:
        by_country, sources = self._fetch_all_countries()

        countries: list[CountryMacro] = []
        signals: list[dict[str, Any]] = []
        for country in GUEST_COUNTRIES.values():
            indicators = by_country.get(country, {})
            regime, score = self._score_regime(indicators)
            summary = self._country_summary(country, indicators, regime, score)
            countries.append(
                CountryMacro(
                    country=country,
                    indicators=indicators,
                    regime=regime,
                    regime_score=score,
                    summary=summary,
                )
            )
            signals.append(self._market_signal(country, regime, score))

        signals = self._adjust_market_signals(signals)
        composite_score, composite_label = self._composite(countries)

        expert_summary = (
            f"Guest-tier macro snapshot across {len(countries)} Trading Economics countries: "
            f"{composite_label} (composite score {composite_score:+.2f}). "
            + " ".join(c.summary for c in countries)
        )

        recs = [
            f"Composite policy stance: {composite_label} (score {composite_score:+.2f})",
        ]
        for c in sorted(countries, key=lambda x: abs(x.regime_score), reverse=True):
            recs.append(c.summary)
        recs.append(
            "Trading Economics free guest API is limited to Mexico, Sweden, New Zealand, "
            "Thailand, and Switzerland — a paid key unlocks the full 190+ country dataset."
        )

        return TradingEconomicsReport(
            countries=countries,
            composite_score=composite_score,
            composite_label=composite_label,
            expert_summary=expert_summary,
            market_signals=signals,
            recommendations=self.append_memory_recommendations(recs),
            data_sources=sources,
        )

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

    def to_dict(self, report: TradingEconomicsReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Trading Economics Macro Expert",
                "analyzed_at": report.analyzed_at,
                "expert_summary": report.expert_summary,
                "countries_analyzed": len(report.countries),
                "data_sources": report.data_sources,
            },
            "countries": [
                {
                    "country": c.country,
                    "regime": c.regime,
                    "regime_score": c.regime_score,
                    "summary": c.summary,
                    "indicators": {
                        cat: {
                            "latest_value": r.latest_value,
                            "previous_value": r.previous_value,
                            "unit": r.unit,
                            "date": r.date,
                        }
                        for cat, r in c.indicators.items()
                    },
                }
                for c in report.countries
            ],
            "metrics": {
                "composite_score": report.composite_score,
                "composite_label": report.composite_label,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            resources_path = output.parent / "trading_economics_resources.json"
            resources_path.write_text(
                json.dumps(TRADING_ECONOMICS_RESOURCES, indent=2),
                encoding="utf-8",
            )
        return result


def run_trading_economics_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return TradingEconomicsExpert(pipeline_context=pipeline_context).run(output=output)
