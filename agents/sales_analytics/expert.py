"""
Sales Analytics BI Expert Agent
=================================
Business Intelligence developer analysis of US retail and consumer sales proxies
via Yahoo Finance sector ETFs and major retail tickers.

Dashboard: sales_dashboard.html
"""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Finance-Sales-Analytics-BI/1.0 (shaggychunxx@gmail.com)"}

RETAIL_UNIVERSE: dict[str, dict[str, str]] = {
    "WMT": {"name": "Walmart", "category": "big_box"},
    "COST": {"name": "Costco", "category": "big_box"},
    "TGT": {"name": "Target", "category": "big_box"},
    "HD": {"name": "Home Depot", "category": "home_improvement"},
    "LOW": {"name": "Lowe's", "category": "home_improvement"},
    "AMZN": {"name": "Amazon", "category": "e_commerce"},
    "SHOP": {"name": "Shopify", "category": "e_commerce"},
    "MCD": {"name": "McDonald's", "category": "restaurants"},
    "SBUX": {"name": "Starbucks", "category": "restaurants"},
    "DPZ": {"name": "Domino's", "category": "restaurants"},
    "NKE": {"name": "Nike", "category": "apparel"},
    "TJX": {"name": "TJX Companies", "category": "apparel"},
    "LULU": {"name": "Lululemon", "category": "apparel"},
    "XLY": {"name": "Consumer Discretionary ETF", "category": "sector_etf"},
    "XLP": {"name": "Consumer Staples ETF", "category": "sector_etf"},
}

CATEGORY_LABELS = {
    "big_box": "Big Box Retail",
    "home_improvement": "Home Improvement",
    "e_commerce": "E-Commerce",
    "restaurants": "Restaurants",
    "apparel": "Apparel",
    "sector_etf": "Sector ETFs",
}

SALES_DASHBOARD_PANELS: list[dict[str, Any]] = [
    {"id": "kpi_row", "name": "KPI Summary", "type": "kpi_cards"},
    {"id": "category_breakdown", "name": "Category Performance", "type": "bar_chart"},
    {"id": "retail_table", "name": "Retail Ticker Table", "type": "data_table"},
    {"id": "trend_sparklines", "name": "20-Day Trend Sparklines", "type": "sparkline"},
    {"id": "discretionary_vs_staples", "name": "Discretionary vs Staples", "type": "comparison"},
    {"id": "top_movers", "name": "Top Sales Proxies", "type": "leaderboard"},
    {"id": "market_signals", "name": "BI Market Signals", "type": "signals"},
]


@dataclass
class RetailMetric:
    symbol: str
    name: str
    category: str
    price: float | None
    return_1d_pct: float | None
    return_5d_pct: float | None
    return_20d_pct: float | None
    volume: int | None
    momentum_score: float
    trend_20d: list[float]


@dataclass
class CategoryAggregate:
    category: str
    label: str
    ticker_count: int
    avg_return_20d_pct: float
    avg_momentum: float
    positive_count: int
    breadth_pct: float


@dataclass
class BIAssessment:
    consumer_demand: str
    category_leader: str
    category_laggard: str
    discretionary_signal: str
    e_commerce_signal: str
    bi_insight: str


@dataclass
class SalesAnalyticsReport:
    retailers: list[RetailMetric]
    categories: list[CategoryAggregate]
    assessment: BIAssessment
    sales_momentum_index: float
    discretionary_premium_pct: float
    retail_breadth_pct: float
    consumer_strength_score: float
    strength_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SalesAnalyticsBIExpert:
    """BI developer — retail sales proxy analytics and dashboard data feeds."""

    def __init__(self, delay_seconds: float = 0.3) -> None:
        self.delay_seconds = delay_seconds

    def _fetch_chart(self, symbol: str) -> dict[str, Any] | None:
        try:
            resp = requests.get(
                CHART_API.format(symbol=symbol),
                params={"interval": "1d", "range": "3mo"},
                headers=HEADERS,
                timeout=25,
            )
            if resp.status_code == 429:
                time.sleep(3)
                resp = requests.get(
                    CHART_API.format(symbol=symbol),
                    params={"interval": "1d", "range": "3mo"},
                    headers=HEADERS,
                    timeout=25,
                )
            resp.raise_for_status()
            return resp.json()["chart"]["result"][0]
        except Exception:
            return None

    @staticmethod
    def _period_return(closes: list[float], days: int) -> float | None:
        if len(closes) <= days:
            return None
        return round(((closes[-1] - closes[-days - 1]) / closes[-days - 1]) * 100, 2)

    @staticmethod
    def _momentum_score(return_20d: float | None, return_5d: float | None) -> float:
        if return_20d is None:
            return 0.5
        score = 0.5 + (return_20d / 20) * 0.25
        if return_5d is not None:
            score += (return_5d / 10) * 0.1
        return round(max(0.0, min(1.0, score)), 4)

    def _retail_metric(self, symbol: str, meta: dict[str, str]) -> RetailMetric | None:
        result = self._fetch_chart(symbol)
        if not result:
            return None
        chart_meta = result["meta"]
        closes = [
            float(c) for c in result["indicators"]["quote"][0]["close"] if c is not None
        ]
        if len(closes) < 2:
            return None

        day_chg: float | None = None
        if len(closes) >= 2:
            day_chg = round(((closes[-1] - closes[-2]) / closes[-2]) * 100, 2)
        elif chart_meta.get("regularMarketChangePercent") is not None:
            day_chg = round(float(chart_meta["regularMarketChangePercent"]), 2)

        trend = closes[-20:] if len(closes) >= 20 else closes
        trend_norm = []
        if trend:
            lo, hi = min(trend), max(trend)
            span = hi - lo or 1
            trend_norm = [round((p - lo) / span, 4) for p in trend]

        r20 = self._period_return(closes, 20)
        r5 = self._period_return(closes, 5)

        return RetailMetric(
            symbol=symbol,
            name=meta["name"],
            category=meta["category"],
            price=round(float(chart_meta.get("regularMarketPrice") or closes[-1]), 2),
            return_1d_pct=day_chg,
            return_5d_pct=r5,
            return_20d_pct=r20,
            volume=chart_meta.get("regularMarketVolume"),
            momentum_score=self._momentum_score(r20, r5),
            trend_20d=trend_norm,
        )

    def _category_aggregates(self, retailers: list[RetailMetric]) -> list[CategoryAggregate]:
        by_cat: dict[str, list[RetailMetric]] = {}
        for r in retailers:
            if r.category == "sector_etf":
                continue
            by_cat.setdefault(r.category, []).append(r)

        aggregates: list[CategoryAggregate] = []
        for cat, rows in by_cat.items():
            r20_vals = [r.return_20d_pct for r in rows if r.return_20d_pct is not None]
            if not r20_vals:
                continue
            pos = sum(1 for v in r20_vals if v > 0)
            aggregates.append(CategoryAggregate(
                category=cat,
                label=CATEGORY_LABELS.get(cat, cat),
                ticker_count=len(rows),
                avg_return_20d_pct=round(statistics.mean(r20_vals), 2),
                avg_momentum=round(statistics.mean(r.momentum_score for r in rows), 4),
                positive_count=pos,
                breadth_pct=round(pos / len(r20_vals) * 100, 1),
            ))
        aggregates.sort(key=lambda c: -c.avg_return_20d_pct)
        return aggregates

    def _assessment(
        self,
        retailers: list[RetailMetric],
        categories: list[CategoryAggregate],
        xly: RetailMetric | None,
        xlp: RetailMetric | None,
        breadth: float,
        momentum_index: float,
    ) -> BIAssessment:
        if momentum_index >= 0.6:
            demand = "strong consumer demand — retail proxies trending higher"
        elif momentum_index <= 0.4:
            demand = "soft consumer demand — retail momentum weakening"
        else:
            demand = "mixed consumer demand — selective category strength"

        if categories:
            leader = categories[0]
            laggard = categories[-1]
            cat_leader = f"{leader.label} leading ({leader.avg_return_20d_pct:+.2f}% avg 20d)"
            cat_laggard = f"{laggard.label} lagging ({laggard.avg_return_20d_pct:+.2f}% avg 20d)"
        else:
            cat_leader = cat_laggard = "category data limited"

        if xly and xlp and xly.return_20d_pct is not None and xlp.return_20d_pct is not None:
            spread = xly.return_20d_pct - xlp.return_20d_pct
            if spread > 2:
                disc = f"discretionary outperforming staples by {spread:+.2f}% — risk-on consumer spending"
            elif spread < -2:
                disc = f"staples outperforming discretionary by {-spread:+.2f}% — defensive consumer tilt"
            else:
                disc = f"discretionary/staples balanced (spread {spread:+.2f}%)"
        else:
            disc = "discretionary vs staples comparison unavailable"

        ecom = [r for r in retailers if r.category == "e_commerce"]
        if ecom:
            avg = statistics.mean(r.return_20d_pct for r in ecom if r.return_20d_pct is not None)
            ecom_sig = f"e-commerce avg 20d {avg:+.2f}% ({', '.join(r.symbol for r in ecom)})"
        else:
            ecom_sig = "e-commerce data unavailable"

        top = max(retailers, key=lambda r: r.momentum_score) if retailers else None
        if top and breadth >= 60:
            insight = f"BI signal: broad retail strength ({breadth:.0f}% positive) led by {top.name}"
        elif top and breadth <= 40:
            insight = f"BI signal: retail weakness — only {breadth:.0f}% positive, watch {top.name} for reversal"
        elif top:
            insight = f"BI signal: selective strength — monitor {top.name} (momentum {top.momentum_score:.2f})"
        else:
            insight = "BI signal: insufficient retail data"

        return BIAssessment(
            consumer_demand=demand,
            category_leader=cat_leader,
            category_laggard=cat_laggard,
            discretionary_signal=disc,
            e_commerce_signal=ecom_sig,
            bi_insight=insight,
        )

    def analyze(self) -> SalesAnalyticsReport:
        retailers: list[RetailMetric] = []
        for symbol, meta in RETAIL_UNIVERSE.items():
            row = self._retail_metric(symbol, meta)
            if row:
                retailers.append(row)
            time.sleep(self.delay_seconds)

        if not retailers:
            raise RuntimeError("Unable to fetch retail sales proxy data")

        categories = self._category_aggregates(retailers)
        xly = next((r for r in retailers if r.symbol == "XLY"), None)
        xlp = next((r for r in retailers if r.symbol == "XLP"), None)

        non_etf = [r for r in retailers if r.category != "sector_etf"]
        r20_vals = [r.return_20d_pct for r in non_etf if r.return_20d_pct is not None]
        momentum_index = (
            round(statistics.mean(r.momentum_score for r in non_etf), 4) if non_etf else 0.5
        )
        breadth = (
            round(sum(1 for v in r20_vals if v > 0) / len(r20_vals) * 100, 1) if r20_vals else 50.0
        )
        disc_premium = 0.0
        if xly and xlp and xly.return_20d_pct is not None and xlp.return_20d_pct is not None:
            disc_premium = round(xly.return_20d_pct - xlp.return_20d_pct, 2)

        consumer_strength = round(
            0.4 * momentum_index
            + 0.3 * (breadth / 100)
            + 0.3 * (0.5 + disc_premium / 20),
            4,
        )
        strength_label = (
            "Strong" if consumer_strength >= 0.62 else
            "Weak" if consumer_strength <= 0.38 else
            "Moderate"
        )

        assessment = self._assessment(
            retailers, categories, xly, xlp, breadth, momentum_index
        )
        summary = (
            f"Sales analytics BI scan: {strength_label} consumer strength "
            f"(score {consumer_strength:.2f}). "
            f"{assessment.consumer_demand}. "
            f"{assessment.category_leader}; {assessment.category_laggard}. "
            f"{assessment.discretionary_signal}. "
            f"{assessment.e_commerce_signal}. "
            f"Momentum index {momentum_index:.2f}, breadth {breadth:.0f}%. "
            f"{assessment.bi_insight}."
        )

        signals = self._market_signals(retailers, categories, assessment, consumer_strength)
        recs = self._recommendations(
            assessment, retailers, categories, momentum_index, breadth, disc_premium
        )

        return SalesAnalyticsReport(
            retailers=retailers,
            categories=categories,
            assessment=assessment,
            sales_momentum_index=momentum_index,
            discretionary_premium_pct=disc_premium,
            retail_breadth_pct=breadth,
            consumer_strength_score=consumer_strength,
            strength_label=strength_label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source="Yahoo Finance API",
        )

    @staticmethod
    def _market_signals(
        retailers: list[RetailMetric],
        categories: list[CategoryAggregate],
        assessment: BIAssessment,
        strength: float,
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal, retail_signal_confidence

        non_etf = [r for r in retailers if r.category != "sector_etf"]
        breadth = (
            round(sum(1 for r in non_etf if (r.return_20d_pct or 0) > 0) / len(non_etf) * 100, 1)
            if non_etf
            else 50.0
        )
        signals: list[dict[str, Any]] = []

        sector_bias = (
            "BULLISH"
            if strength >= 0.62 and breadth >= 55
            else "BEARISH"
            if strength <= 0.38 and breadth <= 45
            else "NEUTRAL"
        )
        sector_conf = retail_signal_confidence(
            momentum=strength,
            return_20d_pct=None,
            breadth_pct=breadth,
            consumer_strength=strength,
        )
        if sector_bias != "NEUTRAL" or strength >= 0.5:
            signals.append(
                build_market_signal(
                    sector="Consumer / Retail",
                    tickers=["XLY", "XLP", "WMT"],
                    bias=sector_bias,
                    reason=f"Consumer strength {strength:.2f}, breadth {breadth:.0f}% — {assessment.consumer_demand}",
                    confidence=sector_conf,
                    evidence={"consumer_strength": round(strength, 3), "breadth_pct": breadth},
                )
            )

        if categories:
            leader = categories[0]
            leader_tickers = [
                r.symbol
                for r in retailers
                if r.category == leader.category and r.symbol in RETAIL_UNIVERSE
            ][:3]
            if leader_tickers and leader.avg_return_20d_pct > 1.5 and leader.breadth_pct >= 50:
                signals.append(
                    build_market_signal(
                        sector=f"Category Leader — {leader.label}",
                        tickers=leader_tickers,
                        bias="BULLISH",
                        reason=f"Avg 20d {leader.avg_return_20d_pct:+.2f}%, breadth {leader.breadth_pct:.0f}%",
                        confidence=retail_signal_confidence(
                            momentum=leader.avg_momentum,
                            return_20d_pct=leader.avg_return_20d_pct,
                            breadth_pct=leader.breadth_pct,
                            consumer_strength=strength,
                        ),
                    )
                )

        top = sorted(
            [r for r in non_etf if r.symbol in RETAIL_UNIVERSE],
            key=lambda r: -r.momentum_score,
        )[:1]
        if top:
            pick = top[0]
            if pick.momentum_score >= 0.58 and (pick.return_20d_pct or 0) >= 1.5:
                signals.append(
                    build_market_signal(
                        sector=f"Top Retail Proxy — {pick.name}",
                        tickers=[pick.symbol],
                        bias="BULLISH",
                        reason=f"Momentum {pick.momentum_score:.2f}, 20d {pick.return_20d_pct:+.2f}%",
                        confidence=retail_signal_confidence(
                            momentum=pick.momentum_score,
                            return_20d_pct=pick.return_20d_pct,
                            breadth_pct=breadth,
                            consumer_strength=strength,
                        ),
                    )
                )

        ecom = [
            r
            for r in retailers
            if r.category == "e_commerce"
            and (r.return_20d_pct or 0) < -5
            and r.momentum_score < 0.45
        ]
        if ecom:
            signals.append(
                build_market_signal(
                    sector="E-Commerce Weakness",
                    tickers=[r.symbol for r in ecom[:2]],
                    bias="BEARISH",
                    reason=f"{ecom[0].symbol} 20d {ecom[0].return_20d_pct:+.2f}%",
                    confidence=0.58,
                )
            )

        if not signals:
            signals.append(
                build_market_signal(
                    sector="Retail Neutral",
                    tickers=["XLY"],
                    bias="NEUTRAL",
                    reason="No statistically strong retail sales signal",
                    confidence=0.42,
                )
            )
        return signals

    @staticmethod
    def _recommendations(
        assessment: BIAssessment,
        retailers: list[RetailMetric],
        categories: list[CategoryAggregate],
        momentum_index: float,
        breadth: float,
        disc_premium: float,
    ) -> list[str]:
        recs = [
            assessment.consumer_demand,
            assessment.category_leader,
            assessment.category_laggard,
            assessment.discretionary_signal,
            assessment.e_commerce_signal,
            assessment.bi_insight,
            f"Sales momentum index: {momentum_index:.2f}",
            f"Retail breadth: {breadth:.0f}% tickers positive (20d)",
            f"Discretionary premium vs staples: {disc_premium:+.2f}%",
        ]
        for c in categories:
            recs.append(
                f"{c.label}: avg 20d {c.avg_return_20d_pct:+.2f}%, "
                f"momentum {c.avg_momentum:.2f}, breadth {c.breadth_pct:.0f}%"
            )
        for r in sorted(retailers, key=lambda x: -x.momentum_score)[:5]:
            recs.append(
                f"{r.symbol} ({r.name}): 1d {r.return_1d_pct:+.2f}%, "
                f"20d {r.return_20d_pct:+.2f}%, momentum {r.momentum_score:.2f}"
            )
        return recs

    def to_dict(self, report: SalesAnalyticsReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Sales Analytics BI Expert",
                "dashboard": "sales_dashboard.html",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
                "retail_tickers": len(report.retailers),
            },
            "dashboard_panels": SALES_DASHBOARD_PANELS,
            "kpis": {
                "sales_momentum_index": report.sales_momentum_index,
                "discretionary_premium_pct": report.discretionary_premium_pct,
                "retail_breadth_pct": report.retail_breadth_pct,
                "consumer_strength_score": report.consumer_strength_score,
                "strength_label": report.strength_label,
            },
            "bi_assessment": {
                "consumer_demand": a.consumer_demand,
                "category_leader": a.category_leader,
                "category_laggard": a.category_laggard,
                "discretionary_signal": a.discretionary_signal,
                "e_commerce_signal": a.e_commerce_signal,
                "bi_insight": a.bi_insight,
            },
            "categories": [
                {
                    "category": c.category,
                    "label": c.label,
                    "ticker_count": c.ticker_count,
                    "avg_return_20d_pct": c.avg_return_20d_pct,
                    "avg_momentum": c.avg_momentum,
                    "breadth_pct": c.breadth_pct,
                }
                for c in report.categories
            ],
            "retailers": [
                {
                    "symbol": r.symbol,
                    "name": r.name,
                    "category": r.category,
                    "category_label": CATEGORY_LABELS.get(r.category, r.category),
                    "price": r.price,
                    "return_1d_pct": r.return_1d_pct,
                    "return_5d_pct": r.return_5d_pct,
                    "return_20d_pct": r.return_20d_pct,
                    "volume": r.volume,
                    "momentum_score": r.momentum_score,
                    "trend_20d": r.trend_20d,
                }
                for r in report.retailers
            ],
            "metrics": {
                "sales_momentum_index": report.sales_momentum_index,
                "retail_breadth_pct": report.retail_breadth_pct,
                "consumer_strength_score": report.consumer_strength_score,
                "strength_label": report.strength_label,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def _dashboard_feed(self, report: SalesAnalyticsReport) -> dict[str, Any]:
        """Compact JSON feed optimized for sales_dashboard.html."""
        return {
            "updated_at": report.analyzed_at,
            "kpis": {
                "sales_momentum_index": report.sales_momentum_index,
                "discretionary_premium_pct": report.discretionary_premium_pct,
                "retail_breadth_pct": report.retail_breadth_pct,
                "consumer_strength_score": report.consumer_strength_score,
                "strength_label": report.strength_label,
            },
            "summary": report.expert_summary,
            "categories": [
                {
                    "label": c.label,
                    "avg_return_20d_pct": c.avg_return_20d_pct,
                    "breadth_pct": c.breadth_pct,
                }
                for c in report.categories
            ],
            "retailers": [
                {
                    "symbol": r.symbol,
                    "name": r.name,
                    "category_label": CATEGORY_LABELS.get(r.category, r.category),
                    "return_1d_pct": r.return_1d_pct,
                    "return_20d_pct": r.return_20d_pct,
                    "momentum_score": r.momentum_score,
                    "trend_20d": r.trend_20d,
                }
                for r in sorted(report.retailers, key=lambda x: -x.momentum_score)
            ],
            "signals": report.market_signals,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        report = self.analyze()
        result = self.to_dict(report)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            feed_path = output.parent / "sales_dashboard_data.json"
            feed_path.write_text(
                json.dumps(self._dashboard_feed(report), indent=2),
                encoding="utf-8",
            )
            panels_path = output.parent / "sales_dashboard_panels.json"
            panels_path.write_text(
                json.dumps(SALES_DASHBOARD_PANELS, indent=2),
                encoding="utf-8",
            )
        return result


def run_sales_analytics_analysis(output: Path | None = None) -> dict[str, Any]:
    return SalesAnalyticsBIExpert().run(output=output)