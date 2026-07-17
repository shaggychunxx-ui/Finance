"""
Estimate Revisions Expert Agent
================================
EPS & revenue analyst estimate revision momentum — the diffusion index
(breadth), revision magnitude, and FY2-vs-FY1 acceleration that act as a
leading indicator of institutional capital reallocation.

Dashboard: https://finance.yahoo.com/
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

DASHBOARD_URL = "https://finance.yahoo.com/"
QUOTE_SUMMARY_API = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
QUOTE_SUMMARY_MODULES = "earningsTrend,financialData,price,summaryDetail"
HEADERS = {"User-Agent": "Finance-Estimate-Revisions/1.0 (shaggychunxx@gmail.com)"}

# Liquid, widely covered large caps — satisfies the Phase 1 liquidity floor
# ($20M+ ADV) for the vast majority of trading days.
WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "AVGO", "LLY",
    "JPM", "V", "UNH", "XOM", "JNJ", "WMT", "HD", "COST",
    "ORCL", "ABBV", "CRM", "NFLX",
]

# Screening thresholds (Phase 1-3 quantitative framework).
MIN_ADV_USD = 20_000_000.0
MIN_ROE_PCT = 15.0
MIN_MAGNITUDE_30D_PCT = 5.0
MIN_DIFFUSION_30D = 0.25
DIFFUSION_STRONG_UP = 0.20
DIFFUSION_STRONG_DOWN = -0.20

BEHAVIORAL_DISTORTIONS = [
    {
        "name": "Analyst Herding",
        "note": (
            "Analysts cluster around consensus to limit career risk, raising estimates "
            "in small conservative increments after a guidance beat rather than jumping "
            "to fair value immediately — creating an exploitable revision lag."
        ),
    },
    {
        "name": "Late-Cycle Downward Drift",
        "note": (
            "Forecasts start each fiscal year optimistic and get shaved down as the year "
            "progresses, so a flat or slightly positive 90-day revision profile is "
            "actually outperforming peers on a relative basis."
        ),
    },
    {
        "name": "Post-Guidance Cliff",
        "note": (
            "Distinguish estimate cuts driven by structural business decay from cuts that "
            "simply match conservative corporate guidance designed to manufacture an "
            "artificial earnings surprise next quarter."
        ),
    },
]

MACRO_TRANSMISSION_LAYERS = [
    {
        "layer": "Macro Regime",
        "catalyst": "Central bank pivot or sharp yield-curve moves",
        "effect": "Blanket revision of discount rates across long-duration assets (e.g. Technology)",
    },
    {
        "layer": "Sector Rotation",
        "catalyst": "Commodity supply shocks or localized regulatory updates",
        "effect": "Simultaneous upward revision across entire baskets (e.g. Energy or Defense)",
    },
    {
        "layer": "Micro Execution",
        "catalyst": "Proprietary product adoption, margin expansion, supply chain optimization",
        "effect": "Isolated, idiosyncratic revision momentum independent of sector peers",
    },
]


@dataclass
class RevisionMetrics:
    symbol: str
    fy1_eps_current: float | None = None
    magnitude_7d_pct: float | None = None
    magnitude_30d_pct: float | None = None
    magnitude_60d_pct: float | None = None
    magnitude_90d_pct: float | None = None
    fy2_magnitude_60d_pct: float | None = None
    acceleration_pct: float | None = None
    up_last_30d: int | None = None
    down_last_30d: int | None = None
    analysts_count: int | None = None
    diffusion_index_30d: float | None = None
    price: float | None = None
    ema50: float | None = None
    ema200: float | None = None
    price_above_ema50: bool | None = None
    price_above_ema200: bool | None = None
    adv_usd: float | None = None
    roe_pct: float | None = None
    fcf_positive: bool | None = None
    phase1_pass: bool = False
    phase2_pass: bool = False
    phase3_pass: bool = False
    quant_screen_pass: bool = False
    diffusion_label: str = "insufficient data"


@dataclass
class EstimateRevisionsReport:
    metrics: list[RevisionMetrics]
    screen_passes: list[str]
    acceleration_leaders: list[dict[str, Any]]
    diffusion_leaders: list[dict[str, Any]]
    behavioral_distortions: list[dict[str, str]]
    macro_transmission: list[dict[str, str]]
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EstimateRevisionsExpert(BaseExpert):
    """Expert on analyst EPS/revenue estimate revision momentum."""

    def __init__(
        self,
        delay_seconds: float = 0.35,
        *,
        pipeline_context: dict | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="estimate-revisions")
        self.delay_seconds = delay_seconds
        self.symbols = list(WATCHLIST)

    def _fetch_quote_summary(self, symbol: str) -> dict[str, Any] | None:
        headers = {**HEADERS}
        try:
            time.sleep(self.delay_seconds)
            resp = requests.get(
                QUOTE_SUMMARY_API.format(symbol=symbol),
                params={"modules": QUOTE_SUMMARY_MODULES},
                headers=headers,
                timeout=20,
            )
            resp.raise_for_status()
            result = resp.json()["quoteSummary"]["result"]
            if not result:
                return None
            return result[0]
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError):
            return None

    @staticmethod
    def _raw(value: Any) -> float | None:
        if isinstance(value, dict):
            value = value.get("raw")
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _ema(closes: list[float], period: int) -> float | None:
        if len(closes) < period:
            return None
        k = 2.0 / (period + 1)
        ema = sum(closes[:period]) / period
        for price in closes[period:]:
            ema = price * k + ema * (1 - k)
        return round(ema, 2)

    @staticmethod
    def _pct_change(current: float | None, prior: float | None) -> float | None:
        if current is None or prior is None or prior == 0:
            return None
        return round((current - prior) / abs(prior) * 100.0, 2)

    def _parse_earnings_trend(self, payload: dict[str, Any]) -> dict[str, Any]:
        trend_entries = payload.get("earningsTrend", {}).get("trend", []) or []
        by_period = {entry.get("period"): entry for entry in trend_entries}
        fy1 = by_period.get("0y", {})
        fy2 = by_period.get("+1y", {})

        fy1_trend = fy1.get("epsTrend", {}) or {}
        fy1_revisions = fy1.get("epsRevisions", {}) or {}
        fy1_estimate = fy1.get("earningsEstimate", {}) or {}
        fy2_trend = fy2.get("epsTrend", {}) or {}

        current = self._raw(fy1_trend.get("current"))
        ago_7 = self._raw(fy1_trend.get("7daysAgo"))
        ago_30 = self._raw(fy1_trend.get("30daysAgo"))
        ago_60 = self._raw(fy1_trend.get("60daysAgo"))
        ago_90 = self._raw(fy1_trend.get("90daysAgo"))

        fy2_current = self._raw(fy2_trend.get("current"))
        fy2_ago_60 = self._raw(fy2_trend.get("60daysAgo"))

        magnitude_30d = self._pct_change(current, ago_30)
        magnitude_60d = self._pct_change(current, ago_60)
        fy2_magnitude_60d = self._pct_change(fy2_current, fy2_ago_60)

        up_30 = fy1_revisions.get("upLast30days")
        down_30 = fy1_revisions.get("downLast30days")
        analysts = fy1_estimate.get("numberOfAnalysts")
        analysts = int(self._raw(analysts)) if self._raw(analysts) is not None else None
        total_revisers = (up_30 or 0) + (down_30 or 0)
        diffusion = None
        if analysts and analysts > 0 and (up_30 is not None or down_30 is not None):
            diffusion = round(((up_30 or 0) - (down_30 or 0)) / analysts, 4)

        acceleration = None
        if fy2_magnitude_60d is not None and magnitude_60d is not None:
            acceleration = round(fy2_magnitude_60d - magnitude_60d, 2)

        return {
            "fy1_eps_current": current,
            "magnitude_7d_pct": self._pct_change(current, ago_7),
            "magnitude_30d_pct": magnitude_30d,
            "magnitude_60d_pct": magnitude_60d,
            "magnitude_90d_pct": self._pct_change(current, ago_90),
            "fy2_magnitude_60d_pct": fy2_magnitude_60d,
            "acceleration_pct": acceleration,
            "up_last_30d": int(up_30) if up_30 is not None else None,
            "down_last_30d": int(down_30) if down_30 is not None else None,
            "analysts_count": analysts,
            "diffusion_index_30d": diffusion,
            "_total_revisers_30d": total_revisers,
        }

    def _parse_quality(self, payload: dict[str, Any]) -> dict[str, Any]:
        financial = payload.get("financialData", {}) or {}
        price_mod = payload.get("price", {}) or {}
        summary = payload.get("summaryDetail", {}) or {}

        price = self._raw(financial.get("currentPrice")) or self._raw(price_mod.get("regularMarketPrice"))
        roe = self._raw(financial.get("returnOnEquity"))
        roe_pct = round(roe * 100.0, 2) if roe is not None else None
        fcf = self._raw(financial.get("freeCashflow"))
        adv = self._raw(price_mod.get("averageDailyVolume10Day")) or self._raw(
            summary.get("averageVolume10days")
        )
        adv_usd = round(adv * price, 2) if adv is not None and price is not None else None

        return {
            "price": price,
            "roe_pct": roe_pct,
            "fcf_positive": (fcf is not None and fcf > 0) if fcf is not None else None,
            "adv_usd": adv_usd,
        }

    def _diffusion_label(self, diffusion: float | None) -> str:
        if diffusion is None:
            return "insufficient data"
        if diffusion >= DIFFUSION_STRONG_UP:
            return "structural upward consensus shift"
        if diffusion <= DIFFUSION_STRONG_DOWN:
            return "severe fundamental deterioration"
        return "mixed / no clear consensus"

    def _build_metrics(self, symbol: str) -> RevisionMetrics:
        m = RevisionMetrics(symbol=symbol)
        payload = self._fetch_quote_summary(symbol)
        if payload:
            trend = self._parse_earnings_trend(payload)
            quality = self._parse_quality(payload)
            m.fy1_eps_current = trend["fy1_eps_current"]
            m.magnitude_7d_pct = trend["magnitude_7d_pct"]
            m.magnitude_30d_pct = trend["magnitude_30d_pct"]
            m.magnitude_60d_pct = trend["magnitude_60d_pct"]
            m.magnitude_90d_pct = trend["magnitude_90d_pct"]
            m.fy2_magnitude_60d_pct = trend["fy2_magnitude_60d_pct"]
            m.acceleration_pct = trend["acceleration_pct"]
            m.up_last_30d = trend["up_last_30d"]
            m.down_last_30d = trend["down_last_30d"]
            m.analysts_count = trend["analysts_count"]
            m.diffusion_index_30d = trend["diffusion_index_30d"]
            m.price = quality["price"]
            m.roe_pct = quality["roe_pct"]
            m.fcf_positive = quality["fcf_positive"]
            m.adv_usd = quality["adv_usd"]

        closes = self.fetch_yahoo_closes(symbol, range_="1y", interval="1d")
        if closes:
            m.ema50 = self._ema(closes, 50)
            m.ema200 = self._ema(closes, 200)
            latest_price = m.price or closes[-1]
            m.price = latest_price
            if m.ema50 is not None:
                m.price_above_ema50 = latest_price > m.ema50
            if m.ema200 is not None:
                m.price_above_ema200 = latest_price > m.ema200

        m.diffusion_label = self._diffusion_label(m.diffusion_index_30d)

        m.phase1_pass = bool(
            m.adv_usd is not None and m.adv_usd >= MIN_ADV_USD
            and m.roe_pct is not None and m.roe_pct > MIN_ROE_PCT
            and m.fcf_positive is True
        )
        m.phase2_pass = bool(
            m.magnitude_30d_pct is not None and m.magnitude_30d_pct > MIN_MAGNITUDE_30D_PCT
            and m.diffusion_index_30d is not None and m.diffusion_index_30d > MIN_DIFFUSION_30D
            and m.fy2_magnitude_60d_pct is not None and m.magnitude_60d_pct is not None
            and m.fy2_magnitude_60d_pct >= m.magnitude_60d_pct
        )
        m.phase3_pass = bool(m.price_above_ema50 is True and m.price_above_ema200 is True)
        m.quant_screen_pass = m.phase1_pass and m.phase2_pass and m.phase3_pass
        return m

    def _market_signals(self, metrics: list[RevisionMetrics]) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal, quant_signal_confidence

        signals: list[dict[str, Any]] = []
        for m in metrics:
            if m.quant_screen_pass:
                momentum = 0.5 + min((m.magnitude_30d_pct or 0) / 40.0, 0.45)
                signals.append(
                    build_market_signal(
                        sector=f"Estimate Momentum — {m.symbol}",
                        tickers=[m.symbol],
                        bias="BULLISH",
                        reason=(
                            f"30d EPS magnitude {m.magnitude_30d_pct:+.2f}%, diffusion "
                            f"{m.diffusion_index_30d:+.2f}, FY2 accel {m.acceleration_pct:+.2f}pp"
                        ),
                        confidence=self.adjust_signal_confidence(
                            m.symbol,
                            "BULLISH",
                            quant_signal_confidence(momentum=momentum, z_score=m.diffusion_index_30d),
                        ),
                        evidence={
                            "magnitude_30d_pct": m.magnitude_30d_pct,
                            "diffusion_index_30d": m.diffusion_index_30d,
                            "acceleration_pct": m.acceleration_pct,
                        },
                    )
                )
            elif m.diffusion_index_30d is not None and m.diffusion_index_30d <= DIFFUSION_STRONG_DOWN:
                signals.append(
                    build_market_signal(
                        sector=f"Estimate Deterioration — {m.symbol}",
                        tickers=[m.symbol],
                        bias="BEARISH",
                        reason=f"30d diffusion index {m.diffusion_index_30d:+.2f} — severe downward revisions",
                        confidence=self.adjust_signal_confidence(
                            m.symbol,
                            "BEARISH",
                            quant_signal_confidence(momentum=0.35, z_score=m.diffusion_index_30d),
                        ),
                        evidence={"diffusion_index_30d": m.diffusion_index_30d},
                    )
                )
        if not signals:
            signals.append(
                build_market_signal(
                    sector="Estimate Revisions",
                    tickers=[m.symbol for m in metrics[:5]],
                    bias="NEUTRAL",
                    reason="No symbol cleared the full revision-momentum screen",
                    confidence=self.adjust_signal_confidence("SPY", "NEUTRAL", 0.4),
                )
            )
        return signals

    @staticmethod
    def _recommendations(
        metrics: list[RevisionMetrics],
        screen_passes: list[str],
        accel_leaders: list[dict[str, Any]],
        diffusion_leaders: list[dict[str, Any]],
    ) -> list[str]:
        recs: list[str] = []
        if screen_passes:
            recs.append(
                "Full Phase 1-3 screen passes: " + ", ".join(screen_passes)
            )
        else:
            recs.append("No symbol cleared all three screening phases this run")
        if diffusion_leaders:
            top = diffusion_leaders[0]
            recs.append(
                f"Strongest diffusion index: {top['symbol']} ({top['diffusion_index_30d']:+.2f})"
            )
        if accel_leaders:
            top = accel_leaders[0]
            recs.append(
                f"Best FY2-vs-FY1 acceleration: {top['symbol']} ({top['acceleration_pct']:+.2f}pp)"
            )
        for m in metrics:
            if m.diffusion_index_30d is not None and m.diffusion_index_30d <= DIFFUSION_STRONG_DOWN:
                recs.append(f"{m.symbol}: severe downward revision consensus — flag for bear thesis review")
        recs.append(
            "Behavioral check: confirm any downward revisions reflect structural decay, not "
            "deliberate conservative guidance ahead of an engineered earnings beat"
        )
        return recs

    def analyze(self) -> EstimateRevisionsReport:
        metrics = [self._build_metrics(symbol) for symbol in self.symbols]

        screen_passes = [m.symbol for m in metrics if m.quant_screen_pass]
        accel_leaders = sorted(
            (
                {"symbol": m.symbol, "acceleration_pct": m.acceleration_pct}
                for m in metrics
                if m.acceleration_pct is not None
            ),
            key=lambda r: r["acceleration_pct"],
            reverse=True,
        )[:5]
        diffusion_leaders = sorted(
            (
                {"symbol": m.symbol, "diffusion_index_30d": m.diffusion_index_30d}
                for m in metrics
                if m.diffusion_index_30d is not None
            ),
            key=lambda r: r["diffusion_index_30d"],
            reverse=True,
        )[:5]

        signals = self._market_signals(metrics)
        recs = self.append_memory_recommendations(
            self._recommendations(metrics, screen_passes, accel_leaders, diffusion_leaders)
        )

        if screen_passes:
            summary = (
                f"{len(screen_passes)} of {len(metrics)} tracked symbols cleared the full "
                f"estimate-revision momentum screen: {', '.join(screen_passes)}."
            )
        else:
            summary = (
                f"No symbol among {len(metrics)} tracked cleared the full liquidity/quality/"
                f"momentum/price-confirmation screen this run."
            )
        if diffusion_leaders:
            top = diffusion_leaders[0]
            summary += f" Strongest breadth: {top['symbol']} diffusion {top['diffusion_index_30d']:+.2f}."

        return EstimateRevisionsReport(
            metrics=metrics,
            screen_passes=screen_passes,
            acceleration_leaders=accel_leaders,
            diffusion_leaders=diffusion_leaders,
            behavioral_distortions=BEHAVIORAL_DISTORTIONS,
            macro_transmission=MACRO_TRANSMISSION_LAYERS,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source="Yahoo Finance quoteSummary (earningsTrend, financialData) + chart API",
        )

    def to_dict(self, report: EstimateRevisionsReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Estimate Revisions Expert",
                "dashboard": DASHBOARD_URL,
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
            },
            "screening_framework": {
                "phase1_liquidity_quality": {
                    "min_adv_usd": MIN_ADV_USD,
                    "min_roe_pct": MIN_ROE_PCT,
                    "requires_positive_fcf_ttm": True,
                },
                "phase2_estimate_momentum": {
                    "min_30d_eps_magnitude_pct": MIN_MAGNITUDE_30D_PCT,
                    "min_diffusion_index_30d": MIN_DIFFUSION_30D,
                    "fy2_delta_must_meet_or_exceed_fy1": True,
                },
                "phase3_price_confirmation": "Price above 50-day and 200-day EMA",
            },
            "metrics": [
                {
                    "symbol": m.symbol,
                    "fy1_eps_current": m.fy1_eps_current,
                    "magnitude_7d_pct": m.magnitude_7d_pct,
                    "magnitude_30d_pct": m.magnitude_30d_pct,
                    "magnitude_60d_pct": m.magnitude_60d_pct,
                    "magnitude_90d_pct": m.magnitude_90d_pct,
                    "fy2_magnitude_60d_pct": m.fy2_magnitude_60d_pct,
                    "acceleration_pct": m.acceleration_pct,
                    "up_last_30d": m.up_last_30d,
                    "down_last_30d": m.down_last_30d,
                    "analysts_count": m.analysts_count,
                    "diffusion_index_30d": m.diffusion_index_30d,
                    "diffusion_label": m.diffusion_label,
                    "price": m.price,
                    "ema50": m.ema50,
                    "ema200": m.ema200,
                    "price_above_ema50": m.price_above_ema50,
                    "price_above_ema200": m.price_above_ema200,
                    "adv_usd": m.adv_usd,
                    "roe_pct": m.roe_pct,
                    "fcf_positive": m.fcf_positive,
                    "phase1_pass": m.phase1_pass,
                    "phase2_pass": m.phase2_pass,
                    "phase3_pass": m.phase3_pass,
                    "quant_screen_pass": m.quant_screen_pass,
                }
                for m in report.metrics
            ],
            "screen_passes": report.screen_passes,
            "acceleration_leaders": report.acceleration_leaders,
            "diffusion_leaders": report.diffusion_leaders,
            "behavioral_distortions": report.behavioral_distortions,
            "macro_transmission": report.macro_transmission,
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog_path = output.parent / "estimate_revision_framework.json"
            catalog_path.write_text(
                json.dumps(
                    {
                        "behavioral_distortions": BEHAVIORAL_DISTORTIONS,
                        "macro_transmission": MACRO_TRANSMISSION_LAYERS,
                        "screening_thresholds": result["screening_framework"],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        return result


def run_estimate_revisions_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return EstimateRevisionsExpert(pipeline_context=pipeline_context).run(output=output)
