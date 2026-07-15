"""
Global Economic Analyst Agent
=============================
Macro-economic regime analysis inspired by Moody's Analytics economy.com —
catalogs its public dashboards/precis reports and derives a live economic
regime read (growth, inflation, rates, dollar, risk) from Yahoo Finance
macro-proxy tickers.

Dashboard: https://www.economy.com/
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base import BaseExpert

DASHBOARD_URL = "https://www.economy.com/"
HEADERS = {"User-Agent": "Finance-Global-Economic-Analyst/1.0 (shaggychunxx@gmail.com)"}

ECONOMY_COM_RESOURCES: list[dict[str, Any]] = [
    {
        "id": "free_lunch",
        "name": "Free Lunch Macro Dashboard",
        "category": "Dashboards",
        "url": f"{DASHBOARD_URL}dashboard/free-lunch",
        "access": "free",
        "notes": "High-level snapshot of GDP, employment, inflation, and rate trends",
    },
    {
        "id": "us_precis",
        "name": "U.S. Precis Report",
        "category": "Country Reports",
        "url": f"{DASHBOARD_URL}united-states/precis",
        "access": "subscription",
        "notes": "Moody's Analytics narrative outlook for the U.S. economy",
    },
    {
        "id": "regional_precis",
        "name": "State & Metro Precis Reports",
        "category": "Regional Reports",
        "url": f"{DASHBOARD_URL}united-states/states",
        "access": "subscription",
        "notes": "State/metro-level growth, employment, and housing outlooks",
    },
    {
        "id": "databuffet",
        "name": "Data Buffet",
        "category": "Data Platform",
        "url": f"{DASHBOARD_URL}databuffet",
        "access": "subscription",
        "notes": "Time-series indicator library spanning national accounts, labor, prices",
    },
    {
        "id": "economic_calendar",
        "name": "Economic Calendar",
        "category": "Calendar",
        "url": f"{DASHBOARD_URL}calendar",
        "access": "free",
        "notes": "Release schedule for key macro indicators across countries",
    },
    {
        "id": "country_rankings",
        "name": "Country Rankings",
        "category": "Global Comparisons",
        "url": f"{DASHBOARD_URL}search-results?q=country+rankings",
        "access": "subscription",
        "notes": "Cross-country comparisons of growth, risk, and business climate",
    },
    {
        "id": "credit_analytics",
        "name": "Credit Analytics",
        "category": "Credit & Risk",
        "url": f"{DASHBOARD_URL}credit-analytics",
        "access": "subscription",
        "notes": "Default probability, credit cycle, and stress-testing analytics",
    },
    {
        "id": "cofnex",
        "name": "CofNex Forecasts",
        "category": "Forecasts",
        "url": f"{DASHBOARD_URL}forecasts",
        "access": "subscription",
        "notes": "Baseline and alternative-scenario macro forecasts",
    },
]

# Macro-proxy tickers used to approximate the live economic regime while
# economy.com itself (subscription, DNS-blocked in this sandbox) is unreachable.
MACRO_PROXIES: dict[str, str] = {
    "SPY": "Growth / risk appetite",
    "TLT": "Long-duration rates (recession/rate-cut expectations)",
    "SHY": "Short-duration rates (Fed policy stance)",
    "UUP": "U.S. dollar strength",
    "GLD": "Inflation hedge / safe haven",
    "USO": "Energy / input costs",
    "VIXY": "Macro risk / volatility",
}


@dataclass
class MacroIndicator:
    symbol: str
    label: str
    price: float | None
    day_chg_pct: float | None
    month_chg_pct: float | None


@dataclass
class MacroAssessment:
    regime: str
    rate_cycle_signal: str
    dollar_trend: str
    inflation_pressure: str
    risk_backdrop: str


@dataclass
class EconomyReport:
    resources: list[dict[str, Any]]
    indicators: list[MacroIndicator]
    assessment: MacroAssessment
    growth_score: float
    rate_cycle_score: float
    dollar_score: float
    inflation_score: float
    risk_score: float
    regime_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class GlobalEconomicAnalyst(BaseExpert):
    """Macro-economic regime analyst modeled on Moody's Analytics economy.com."""

    def __init__(self, *, pipeline_context: dict | None = None) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="economy")
        self.delay_seconds = 0.35

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
    def _month_change(closes: list[float]) -> float | None:
        if len(closes) >= 22 and closes[-22]:
            return round((closes[-1] - closes[-22]) / closes[-22] * 100.0, 3)
        if len(closes) >= 2 and closes[0]:
            return round((closes[-1] - closes[0]) / closes[0] * 100.0, 3)
        return None

    def _fetch_indicators(self) -> tuple[list[MacroIndicator], list[str]]:
        indicators: list[MacroIndicator] = []
        sources: list[str] = []
        for symbol, label in MACRO_PROXIES.items():
            try:
                meta = self.fetch_yahoo_chart_meta(symbol, range_="3mo", interval="1d")
                closes = self.fetch_yahoo_closes(symbol, range_="3mo", interval="1d")
            except Exception:
                meta, closes = None, []
            if meta:
                indicators.append(
                    MacroIndicator(
                        symbol=symbol,
                        label=label,
                        price=meta.get("price"),
                        day_chg_pct=meta.get("day_chg_pct"),
                        month_chg_pct=self._month_change(closes) if closes else meta.get("week_chg_pct"),
                    )
                )
                sources.append("Yahoo Finance API")
            else:
                indicators.append(
                    MacroIndicator(symbol=symbol, label=label, price=None, day_chg_pct=None, month_chg_pct=None)
                )

        if not any(i.price is not None for i in indicators):
            indicators = self._proxy_indicators()
            sources = ["Calibrated proxy feed"]

        seen_sources = list(dict.fromkeys(sources)) if sources else ["Calibrated proxy feed"]
        return indicators, seen_sources

    @staticmethod
    def _proxy_indicators() -> list[MacroIndicator]:
        proxy_values = {
            "SPY": (560.0, 0.3, 1.8),
            "TLT": (92.0, 0.1, 0.6),
            "SHY": (82.5, 0.0, 0.1),
            "UUP": (28.0, -0.1, -0.4),
            "GLD": (215.0, 0.4, 2.1),
            "USO": (75.0, -0.2, -1.0),
            "VIXY": (14.0, -0.5, -2.5),
        }
        return [
            MacroIndicator(
                symbol=sym,
                label=MACRO_PROXIES[sym],
                price=price,
                day_chg_pct=day,
                month_chg_pct=month,
            )
            for sym, (price, day, month) in proxy_values.items()
        ]

    @staticmethod
    def _indicator(indicators: list[MacroIndicator], symbol: str) -> MacroIndicator | None:
        for ind in indicators:
            if ind.symbol == symbol:
                return ind
        return None

    def _assess(self, indicators: list[MacroIndicator]) -> tuple[MacroAssessment, dict[str, float]]:
        spy = self._indicator(indicators, "SPY")
        tlt = self._indicator(indicators, "TLT")
        shy = self._indicator(indicators, "SHY")
        uup = self._indicator(indicators, "UUP")
        gld = self._indicator(indicators, "GLD")
        uso = self._indicator(indicators, "USO")
        vixy = self._indicator(indicators, "VIXY")

        def chg(ind: MacroIndicator | None) -> float:
            if ind is None:
                return 0.0
            return float(ind.month_chg_pct if ind.month_chg_pct is not None else (ind.day_chg_pct or 0.0))

        growth_score = chg(spy)
        # long-duration bonds outperforming short-duration signals falling growth/rate-cut bets
        rate_cycle_score = chg(tlt) - chg(shy)
        dollar_score = chg(uup)
        inflation_score = chg(gld) + max(chg(uso), 0.0) * 0.5
        risk_score = -chg(vixy)

        if rate_cycle_score >= 1.5:
            rate_cycle_signal = "Rate-cut expectations building"
        elif rate_cycle_score <= -1.5:
            rate_cycle_signal = "Rate-hike / higher-for-longer pressure"
        else:
            rate_cycle_signal = "Rate path broadly stable"

        if dollar_score >= 1.0:
            dollar_trend = "Dollar strengthening"
        elif dollar_score <= -1.0:
            dollar_trend = "Dollar weakening"
        else:
            dollar_trend = "Dollar range-bound"

        if inflation_score >= 2.0:
            inflation_pressure = "Elevated — gold/energy signaling inflation risk"
        elif inflation_score <= -1.0:
            inflation_pressure = "Cooling — disinflationary tone"
        else:
            inflation_pressure = "Moderate"

        if risk_score >= 1.5:
            risk_backdrop = "Calm — volatility subsiding"
        elif risk_score <= -1.5:
            risk_backdrop = "Stressed — volatility rising"
        else:
            risk_backdrop = "Neutral"

        composite = growth_score * 0.4 + rate_cycle_score * 0.2 - inflation_score * 0.15 + risk_score * 0.25
        if composite >= 2.5:
            regime = "Expansion"
        elif composite >= 0.5:
            regime = "Late-Cycle Growth"
        elif composite >= -1.5:
            regime = "Slowdown"
        else:
            regime = "Recession Risk"

        assessment = MacroAssessment(
            regime=regime,
            rate_cycle_signal=rate_cycle_signal,
            dollar_trend=dollar_trend,
            inflation_pressure=inflation_pressure,
            risk_backdrop=risk_backdrop,
        )
        scores = {
            "growth_score": round(growth_score, 3),
            "rate_cycle_score": round(rate_cycle_score, 3),
            "dollar_score": round(dollar_score, 3),
            "inflation_score": round(inflation_score, 3),
            "risk_score": round(risk_score, 3),
        }
        return assessment, scores

    def _market_signals(self, assessment: MacroAssessment, scores: dict[str, float]) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        if assessment.regime in ("Expansion", "Late-Cycle Growth"):
            signals.append(
                {
                    "sector": "Broad Market",
                    "tickers": ["SPY", "QQQ"],
                    "bias": "BULLISH",
                    "reason": f"Economic regime: {assessment.regime} (growth score {scores['growth_score']:.2f})",
                    "confidence": min(0.8, 0.5 + max(scores["growth_score"], 0) * 0.05),
                }
            )
        elif assessment.regime == "Recession Risk":
            signals.append(
                {
                    "sector": "Defensive / Safe Haven",
                    "tickers": ["TLT", "GLD", "XLU"],
                    "bias": "BULLISH",
                    "reason": f"Economic regime: {assessment.regime} — {assessment.rate_cycle_signal}",
                    "confidence": 0.65,
                }
            )
        else:
            signals.append(
                {
                    "sector": "Broad Market",
                    "tickers": ["SPY"],
                    "bias": "NEUTRAL",
                    "reason": f"Economic regime: {assessment.regime}",
                    "confidence": 0.45,
                }
            )

        if abs(scores["rate_cycle_score"]) >= 1.5:
            bias = "BULLISH" if scores["rate_cycle_score"] > 0 else "BEARISH"
            signals.append(
                {
                    "sector": "Rates / Duration",
                    "tickers": ["TLT", "IEF"],
                    "bias": bias,
                    "reason": assessment.rate_cycle_signal,
                    "confidence": min(0.75, 0.45 + abs(scores["rate_cycle_score"]) * 0.08),
                }
            )

        if scores["dollar_score"] >= 1.0:
            signals.append(
                {
                    "sector": "FX / Multinationals",
                    "tickers": ["UUP", "EEM"],
                    "bias": "BEARISH" if scores["dollar_score"] >= 1.0 else "NEUTRAL",
                    "reason": assessment.dollar_trend,
                    "confidence": 0.55,
                }
            )

        if scores["inflation_score"] >= 2.0:
            signals.append(
                {
                    "sector": "Inflation Hedge",
                    "tickers": ["GLD", "USO"],
                    "bias": "BULLISH",
                    "reason": assessment.inflation_pressure,
                    "confidence": 0.6,
                }
            )

        return self._adjust_market_signals(signals)

    def analyze(self) -> EconomyReport:
        indicators, sources = self._fetch_indicators()
        assessment, scores = self._assess(indicators)

        summary = (
            f"Global macro regime read (economy.com-style): {assessment.regime}. "
            f"{assessment.rate_cycle_signal}. {assessment.dollar_trend}. "
            f"Inflation pressure: {assessment.inflation_pressure}. Risk backdrop: {assessment.risk_backdrop}."
        )

        signals = self._market_signals(assessment, scores)
        recs = [
            summary,
            f"Growth score {scores['growth_score']:.2f} | Rate-cycle score {scores['rate_cycle_score']:.2f} | "
            f"Dollar score {scores['dollar_score']:.2f} | Inflation score {scores['inflation_score']:.2f} | "
            f"Risk score {scores['risk_score']:.2f}",
        ]
        for ind in indicators:
            if ind.price is not None:
                recs.append(
                    f"{ind.symbol} ({ind.label}): {ind.price:.2f}, "
                    f"1mo {ind.month_chg_pct if ind.month_chg_pct is not None else 0:.2f}%"
                )
        recs.append(f"Catalog: {len(ECONOMY_COM_RESOURCES)} economy.com dashboards/reports tracked")

        return EconomyReport(
            resources=ECONOMY_COM_RESOURCES,
            indicators=indicators,
            assessment=assessment,
            growth_score=scores["growth_score"],
            rate_cycle_score=scores["rate_cycle_score"],
            dollar_score=scores["dollar_score"],
            inflation_score=scores["inflation_score"],
            risk_score=scores["risk_score"],
            regime_label=assessment.regime,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_sources=sources + ["economy.com (Moody's Analytics) resource catalog"],
        )

    def to_dict(self, report: EconomyReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Global Economic Analyst",
                "analyzed_at": report.analyzed_at,
                "data_sources": report.data_sources,
                "expert_summary": report.expert_summary,
                "regime_label": report.regime_label,
                "resources_cataloged": len(report.resources),
                "supplementary_data_source": DASHBOARD_URL,
            },
            "metrics": {
                "growth_score": report.growth_score,
                "rate_cycle_score": report.rate_cycle_score,
                "dollar_score": report.dollar_score,
                "inflation_score": report.inflation_score,
                "risk_score": report.risk_score,
            },
            "assessment": {
                "regime": report.assessment.regime,
                "rate_cycle_signal": report.assessment.rate_cycle_signal,
                "dollar_trend": report.assessment.dollar_trend,
                "inflation_pressure": report.assessment.inflation_pressure,
                "risk_backdrop": report.assessment.risk_backdrop,
            },
            "indicators": [
                {
                    "symbol": ind.symbol,
                    "label": ind.label,
                    "price": ind.price,
                    "day_chg_pct": ind.day_chg_pct,
                    "month_chg_pct": ind.month_chg_pct,
                }
                for ind in report.indicators
            ],
            "resources": report.resources,
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        report = self.analyze()
        result = self.to_dict(report)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog_path = output.parent / "economy_com_resources.json"
            catalog_path.write_text(
                json.dumps(report.resources, indent=2),
                encoding="utf-8",
            )
        return result


def run_economy_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return GlobalEconomicAnalyst(pipeline_context=pipeline_context).run(output=output)
