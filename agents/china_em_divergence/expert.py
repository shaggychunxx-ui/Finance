"""
China / EM Divergence Expert Agent
===================================
Expert analysis of the 2026 "Great Growth Divergence": China's Q2 GDP
slowdown and historic property/domestic-demand collapse versus the AI-chip
driven boom in Taiwan and South Korea, and the "China + 1" supply-chain
reroute into Malaysia, Vietnam, and India.

Primary data: Yahoo Finance chart API (live equity-index ETF proxies for
each region). China's official GDP/FAI/retail-sales prints are not
reachable from this sandbox (National Bureau of Statistics of China and
Trading Economics premium tiers are unavailable), so those macro figures
use a calibrated proxy snapshot sourced from the public reporting cited in
``CHINA_EM_RESOURCES`` below and are always labeled ``"proxy"``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base import BaseExpert
from agents.market_data import fetch_chart_meta, fetch_closes

# Calibrated China macro proxy snapshot (Q2 2026 prints). Values are
# indicative reference points transcribed from public reporting, not a
# live feed, and are always labeled "proxy" in the report.
CHINA_MACRO_PROXY: dict[str, dict[str, Any]] = {
    "q2_gdp_growth_yoy": {
        "label": "Q2 GDP growth (YoY)",
        "value": 4.3,
        "unit": "%",
        "note": "Weakest quarterly expansion since late 2022",
    },
    "h1_gdp_growth_yoy": {
        "label": "H1 GDP growth (YoY)",
        "value": 4.7,
        "unit": "%",
        "note": "Below Beijing's 4.5%-5.0% full-year target range",
    },
    "h1_fixed_asset_investment": {
        "label": "H1 fixed-asset investment",
        "value": -5.7,
        "unit": "%",
        "note": "Domestic investment freeze",
    },
    "june_retail_sales_growth": {
        "label": "June retail sales growth",
        "value": 1.0,
        "unit": "%",
        "note": "Barely positive; large-ticket items far weaker",
    },
    "auto_purchases_growth": {
        "label": "Large-ticket auto purchases",
        "value": -16.0,
        "unit": "%",
        "note": "Collapse in big-ticket consumer spending",
    },
    "h1_property_investment": {
        "label": "H1 property investment",
        "value": -18.0,
        "unit": "%",
        "note": "Sharpest drop since data tracking began in 1992",
    },
    "car_exports_monthly": {
        "label": "Monthly car exports",
        "value": 1.0,
        "unit": "million units",
        "note": "First time car exports have eclipsed 1 million units in a month",
    },
}

# Region proxies: role classifies each region within the divergence thesis.
#   stress_epicenter        - the source of the domestic weakness (China)
#   tech_beneficiary        - AI/chip export boom beneficiaries
#   supply_chain_reroute    - "China + 1" manufacturing migration nodes
#   trade_negotiation       - contested/negotiating EM member
#   decoupling_benchmark    - EM-ex-China passive benchmark
#   broad_index             - broad EM index still China-weighted
REGION_PROXIES: dict[str, dict[str, str]] = {
    "china": {
        "name": "China",
        "ticker": "FXI",
        "role": "stress_epicenter",
        "narrative": (
            "Property collapse (-18% H1 investment) and precautionary savings "
            "entrench a deflationary domestic loop even as exports stay robust."
        ),
    },
    "taiwan": {
        "name": "Taiwan",
        "ticker": "EWT",
        "role": "tech_beneficiary",
        "narrative": (
            "Epicenter of leading-edge AI chip manufacturing (TSMC); exports "
            "surged >50% YoY, steering GDP growth close to 7%."
        ),
    },
    "south_korea": {
        "name": "South Korea",
        "ticker": "EWY",
        "role": "tech_beneficiary",
        "narrative": (
            "Surging HBM memory demand for AI hardware drives high earnings "
            "momentum for local semiconductor manufacturers."
        ),
    },
    "malaysia": {
        "name": "Malaysia",
        "ticker": "EWM",
        "role": "supply_chain_reroute",
        "narrative": (
            "'China + 1' node absorbing midstream electronics packaging and "
            "assembly relocated to dodge Western tariff barriers."
        ),
    },
    "vietnam": {
        "name": "Vietnam",
        "ticker": "VNM",
        "role": "supply_chain_reroute",
        "narrative": (
            "Manufacturing migration destination stabilizing macro receipts "
            "against the Chinese slowdown."
        ),
    },
    "india": {
        "name": "India",
        "ticker": "INDA",
        "role": "trade_negotiation",
        "narrative": (
            "Navigating complex U.S. trade negotiations to secure its own "
            "market multiple expansion against competitive EM shifts."
        ),
    },
    "em_ex_china": {
        "name": "EM ex-China",
        "ticker": "EMXC",
        "role": "decoupling_benchmark",
        "narrative": (
            "Benchmark for active managers running 'EM ex-China' strategies "
            "to sidestep index drag from China's underperformance."
        ),
    },
    "broad_em": {
        "name": "Broad Emerging Markets",
        "ticker": "EEM",
        "role": "broad_index",
        "narrative": (
            "Passive EM index still China-weighted, absorbing structural "
            "drag from the domestic slowdown."
        ),
    },
}

# Calibrated fallback returns (pct, 60-trading-day) used only when the
# live Yahoo Finance chart fetch is unavailable.
PROXY_MOMENTUM_PCT: dict[str, float] = {
    "FXI": -2.5,
    "EWT": 14.0,
    "EWY": 11.5,
    "EWM": 3.0,
    "VNM": 4.0,
    "INDA": 1.0,
    "EMXC": 4.5,
    "EEM": 1.5,
}

CHINA_EM_RESOURCES: list[dict[str, Any]] = [
    {
        "id": "reuters_gdp",
        "name": "China Q2 GDP growth slows to 4.3% YoY, misses forecast",
        "url": "https://www.reuters.com/world/china/chinas-q2-gdp-growth-slows-43-yy-misses-market-forecast-2026-07-15/",
        "description": "Reuters coverage of the Q2 2026 GDP print and structural imbalance",
    },
    {
        "id": "cnbc_retail_investment",
        "name": "China GDP, retail sales, investment (June)",
        "url": "https://www.cnbc.com/2026/07/15/china-gdp-retail-sales-investment-june-.html",
        "description": "CNBC breakdown of retail sales and fixed-asset investment data",
    },
    {
        "id": "cnn_export_economy",
        "name": "China Q2 GDP export economy",
        "url": "https://www.cnn.com/2026/07/14/business/china-q2-gdp-export-economy-intl-hnk",
        "description": "CNN analysis of the export-vs-domestic-demand divergence",
    },
    {
        "id": "indexbox_gdp",
        "name": "China's Q2 2026 GDP growth misses expectations at 4.3%",
        "url": "https://www.indexbox.io/blog/chinas-q2-2026-gdp-growth-misses-expectations-at-43/",
        "description": "IndexBox summary of the GDP miss and sector detail",
    },
    {
        "id": "trading_economics_gdp",
        "name": "China GDP Growth Rate",
        "url": "https://tradingeconomics.com/china/gdp-growth",
        "description": "Trading Economics historical GDP growth series for China",
    },
    {
        "id": "reuters_breaks_step",
        "name": "China breaks step with global markets as investors buy",
        "url": "https://www.reuters.com/world/china/china-breaks-step-with-global-markets-investors-buy-2026-07-07/",
        "description": "Reuters on Chinese bonds/Yuan decoupling from global market trends",
    },
    {
        "id": "lazard_em_outlook",
        "name": "Emerging Markets Outlook 2026",
        "url": "https://www.lazardassetmanagement.com/uk/en_gb/research-insights/investment-insights/investment-research/emerging-markets-outlook-2026",
        "description": "Lazard Asset Management's EM outlook, incl. Taiwan/South Korea tech dispersion",
    },
    {
        "id": "fundfinity_em_2026",
        "name": "Emerging Markets 2026",
        "url": "https://fundfinity.net/blog/emerging-markets-2026/",
        "description": "FundFinity overview of 'EM ex-China' fund strategies",
    },
]


@dataclass
class RegionMomentum:
    region_id: str
    name: str
    ticker: str
    role: str
    narrative: str
    price: float | None
    momentum_60d_pct: float | None
    is_proxy: bool


@dataclass
class ChinaEMDivergenceReport:
    regions: list[RegionMomentum]
    china_macro: dict[str, dict[str, Any]]
    decoupling_score: float
    decoupling_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ChinaEMDivergenceExpert(BaseExpert):
    """Analyst covering China's structural slowdown and the EM spillover it drives."""

    def __init__(self, *, pipeline_context: dict | None = None) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="china-em-divergence")

    @staticmethod
    def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
        return max(low, min(high, value))

    def _momentum_60d(self, ticker: str) -> tuple[float | None, float | None, bool]:
        """Returns (price, 60-trading-day pct change, is_proxy)."""
        try:
            closes = fetch_closes(ticker, range_="6mo", client_tag="china-em-divergence")
        except Exception:
            closes = []
        if len(closes) >= 61 and closes[-61]:
            price = closes[-1]
            pct = round((closes[-1] - closes[-61]) / closes[-61] * 100.0, 3)
            return price, pct, False
        meta = None
        try:
            meta = fetch_chart_meta(ticker, range_="1mo", client_tag="china-em-divergence")
        except Exception:
            meta = None
        price = meta.get("price") if meta else None
        proxy_pct = PROXY_MOMENTUM_PCT.get(ticker)
        return price, proxy_pct, True

    def _fetch_regions(self) -> tuple[list[RegionMomentum], list[str]]:
        regions: list[RegionMomentum] = []
        live_hits = 0
        for region_id, meta in REGION_PROXIES.items():
            ticker = meta["ticker"]
            price, momentum, is_proxy = self._momentum_60d(ticker)
            if not is_proxy:
                live_hits += 1
            regions.append(
                RegionMomentum(
                    region_id=region_id,
                    name=meta["name"],
                    ticker=ticker,
                    role=meta["role"],
                    narrative=meta["narrative"],
                    price=price,
                    momentum_60d_pct=momentum,
                    is_proxy=is_proxy,
                )
            )
        sources = []
        if live_hits:
            sources.append(f"Yahoo Finance Chart API ({live_hits}/{len(REGION_PROXIES)} region proxies live)")
        if live_hits < len(REGION_PROXIES):
            sources.append("Calibrated 60d momentum proxy (chart API unavailable for remaining regions)")
        sources.append("Calibrated China macro proxy snapshot (Q2 2026 public reporting)")
        return regions, sources

    def _decoupling_score(self, regions: list[RegionMomentum]) -> tuple[float, str]:
        china = next((r for r in regions if r.region_id == "china"), None)
        beneficiaries = [
            r for r in regions
            if r.role in ("tech_beneficiary", "supply_chain_reroute") and r.momentum_60d_pct is not None
        ]
        if not china or china.momentum_60d_pct is None or not beneficiaries:
            return 0.0, "Insufficient data"

        avg_beneficiary = sum(r.momentum_60d_pct for r in beneficiaries) / len(beneficiaries)
        spread = avg_beneficiary - china.momentum_60d_pct
        score = round(self._clamp(spread / 20.0), 4)

        if score >= 0.35:
            label = "Sharp EM ex-China outperformance / decoupling confirmed"
        elif score <= -0.15:
            label = "China outperforming spillover beneficiaries"
        else:
            label = "Moderate decoupling / broad EM correlation partly intact"
        return score, label

    def _market_signal(self, region: RegionMomentum, decoupling_score: float) -> dict[str, Any]:
        from agent_signal_logic import build_market_signal

        momentum = region.momentum_60d_pct or 0.0
        if region.role == "stress_epicenter":
            bias = "BEARISH" if decoupling_score >= 0.15 else "NEUTRAL"
            reason = (
                f"China property investment collapsed 18% H1; domestic freeze offsets export "
                f"strength ({region.ticker} 60d momentum {momentum:+.2f}%)"
            )
        elif region.role in ("tech_beneficiary", "supply_chain_reroute"):
            bias = "BULLISH" if momentum > 0 else "NEUTRAL"
            reason = f"{region.narrative} ({region.ticker} 60d momentum {momentum:+.2f}%)"
        elif region.role == "decoupling_benchmark":
            bias = "BULLISH" if decoupling_score >= 0.2 else "NEUTRAL"
            reason = (
                f"Active managers rotating into 'EM ex-China' strategies as China lags "
                f"tech-driven EM peers (decoupling score {decoupling_score:+.2f})"
            )
        else:
            bias = "NEUTRAL"
            reason = f"{region.narrative} ({region.ticker} 60d momentum {momentum:+.2f}%)"

        confidence = min(0.85, 0.4 + abs(decoupling_score) * 0.5 + (0.1 if not region.is_proxy else 0.0))
        confidence = self.adjust_signal_confidence(region.ticker, bias, confidence)

        return build_market_signal(
            sector=f"{region.name} / China-EM Divergence",
            tickers=[region.ticker],
            bias=bias,
            reason=reason,
            confidence=confidence,
            evidence={
                "role": region.role,
                "momentum_60d_pct": region.momentum_60d_pct,
                "decoupling_score": decoupling_score,
                "is_proxy": region.is_proxy,
            },
        )

    def analyze(self) -> ChinaEMDivergenceReport:
        regions, sources = self._fetch_regions()
        decoupling_score, decoupling_label = self._decoupling_score(regions)
        signals = [self._market_signal(r, decoupling_score) for r in regions]

        china_gdp = CHINA_MACRO_PROXY["q2_gdp_growth_yoy"]["value"]
        property_drop = CHINA_MACRO_PROXY["h1_property_investment"]["value"]
        expert_summary = (
            f"China Q2 GDP growth slowed to {china_gdp}% YoY, the weakest since late 2022, "
            f"as a {abs(property_drop)}% H1 property-investment collapse and precautionary "
            f"savings offset export-led industrial strength. Decoupling assessment: "
            f"{decoupling_label} (score {decoupling_score:+.2f}), with Taiwan/South Korea AI-chip "
            f"exports and 'China + 1' reroutes into Malaysia/Vietnam diverging sharply from "
            f"China's domestic freeze."
        )

        recs = [
            f"Decoupling stance: {decoupling_label} (score {decoupling_score:+.2f})",
            (
                f"China domestic freeze: H1 fixed-asset investment {CHINA_MACRO_PROXY['h1_fixed_asset_investment']['value']}%, "
                f"June retail sales +{CHINA_MACRO_PROXY['june_retail_sales_growth']['value']}%, "
                f"auto purchases {CHINA_MACRO_PROXY['auto_purchases_growth']['value']}%"
            ),
        ]
        for region in sorted(regions, key=lambda r: -(r.momentum_60d_pct or 0.0)):
            recs.append(
                f"{region.name} ({region.ticker}): {region.role.replace('_', ' ')} — "
                f"60d momentum {region.momentum_60d_pct:+.2f}%"
                if region.momentum_60d_pct is not None
                else f"{region.name} ({region.ticker}): {region.role.replace('_', ' ')} — momentum unavailable"
            )
        recs.append(
            "Watch the late-July Politburo meeting for fiscal-stimulus signals and "
            "U.S.-China-India trade-deal developments that could re-rate EM equities."
        )

        return ChinaEMDivergenceReport(
            regions=regions,
            china_macro=CHINA_MACRO_PROXY,
            decoupling_score=decoupling_score,
            decoupling_label=decoupling_label,
            expert_summary=expert_summary,
            market_signals=signals,
            recommendations=self.append_memory_recommendations(recs),
            data_sources=sources,
        )

    def to_dict(self, report: ChinaEMDivergenceReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "China / EM Divergence Expert",
                "analyzed_at": report.analyzed_at,
                "expert_summary": report.expert_summary,
                "regions_analyzed": len(report.regions),
                "data_sources": report.data_sources,
            },
            "china_macro": report.china_macro,
            "regions": [
                {
                    "region_id": r.region_id,
                    "name": r.name,
                    "ticker": r.ticker,
                    "role": r.role,
                    "narrative": r.narrative,
                    "price": r.price,
                    "momentum_60d_pct": r.momentum_60d_pct,
                    "is_proxy": r.is_proxy,
                }
                for r in report.regions
            ],
            "metrics": {
                "decoupling_score": report.decoupling_score,
                "decoupling_label": report.decoupling_label,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            resources_path = output.parent / "china_em_divergence_resources.json"
            resources_path.write_text(
                json.dumps(CHINA_EM_RESOURCES, indent=2),
                encoding="utf-8",
            )
        return result


def run_china_em_divergence_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return ChinaEMDivergenceExpert(pipeline_context=pipeline_context).run(output=output)
