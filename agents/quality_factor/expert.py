"""
Quality Factor Expert Agent
===========================
Economic-moat / cash-compounding analysis built on the two pillars of the
Quality factor: Return on Invested Capital (ROIC) versus the Weighted
Average Cost of Capital (WACC), and Free Cash Flow (FCF) conversion versus
reported accounting earnings.

The agent classifies each name in a curated quality universe into one of
four ROIC × FCF quadrants (Compounder Machine, Paper Tiger Profits, Mature
Cash Cow, Structural Value Trap), derives the sustainable organic growth
rate implied by ROIC and the reinvestment rate, computes an accrual ratio
to flag earnings-quality risk, and surfaces the macro vulnerabilities that
typically erode the Quality premium (valuation-premium risk, CapEx/inflation
sensitivity, and competitive reversion-to-the-mean risk).

Data: Yahoo Finance quoteSummary/chart APIs with a calibrated fundamentals
proxy fallback (fundamentals are reporting-lag data; live requests are
attempted first and the proxy figures are always labeled as such).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agents.base import BaseExpert

HEADERS = {"User-Agent": "Finance-Quality-Factor-Expert/1.0 (shaggychunxx@gmail.com)"}
QUOTE_SUMMARY_API = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
QUOTE_SUMMARY_MODULES = "financialData,incomeStatementHistory,balanceSheetHistory,cashflowStatementHistory,defaultKeyStatistics"

# High-quality-vs-low-quality benchmark universe spanning all four ROIC × FCF
# quadrants: asset-light compounders, a capex-heavy energy name, cyclical
# capital-intensive industrials, and a working-capital-heavy homebuilder.
QUALITY_UNIVERSE: dict[str, dict[str, Any]] = {
    "MSFT": {"name": "Microsoft", "sector": "Software / Cloud"},
    "AAPL": {"name": "Apple", "sector": "Consumer Technology"},
    "V": {"name": "Visa", "sector": "Payments"},
    "MA": {"name": "Mastercard", "sector": "Payments"},
    "COST": {"name": "Costco", "sector": "Retail"},
    "NVDA": {"name": "Nvidia", "sector": "Semiconductors"},
    "XOM": {"name": "ExxonMobil", "sector": "Energy"},
    "F": {"name": "Ford Motor", "sector": "Automotive"},
    "BA": {"name": "Boeing", "sector": "Aerospace / Defense"},
    "DHI": {"name": "D.R. Horton", "sector": "Homebuilding"},
}

# Calibrated proxy fundamentals ($ millions unless noted) used when the live
# quoteSummary endpoint is unreachable. Figures are indicative, reporting-lag
# reference points chosen to illustrate the full ROIC × FCF quadrant matrix —
# not a live feed. tax_rate/wacc are decimals; shares_out is in millions;
# price is $ per share.
PROXY_FUNDAMENTALS: dict[str, dict[str, float]] = {
    "MSFT": {
        "ebit": 125_000, "tax_rate": 0.18, "invested_capital": 210_000, "wacc": 0.088,
        "da": 16_000, "delta_nwc": 1_500, "capex": 55_000, "ocf": 110_000,
        "net_income": 88_000, "total_assets": 520_000, "shares_out": 7_430, "price": 420.0,
    },
    "AAPL": {
        "ebit": 123_000, "tax_rate": 0.16, "invested_capital": 75_000, "wacc": 0.085,
        "da": 11_500, "delta_nwc": -3_000, "capex": 11_000, "ocf": 110_000,
        "net_income": 97_000, "total_assets": 365_000, "shares_out": 15_200, "price": 225.0,
    },
    "V": {
        "ebit": 15_500, "tax_rate": 0.19, "invested_capital": 20_000, "wacc": 0.083,
        "da": 700, "delta_nwc": 300, "capex": 700, "ocf": 14_500,
        "net_income": 13_000, "total_assets": 90_000, "shares_out": 2_030, "price": 310.0,
    },
    "MA": {
        "ebit": 11_800, "tax_rate": 0.18, "invested_capital": 15_000, "wacc": 0.083,
        "da": 550, "delta_nwc": 250, "capex": 650, "ocf": 10_800,
        "net_income": 10_100, "total_assets": 45_000, "shares_out": 920, "price": 520.0,
    },
    "COST": {
        "ebit": 9_300, "tax_rate": 0.25, "invested_capital": 30_000, "wacc": 0.08,
        "da": 2_100, "delta_nwc": -800, "capex": 4_400, "ocf": 10_500,
        "net_income": 7_400, "total_assets": 70_000, "shares_out": 443, "price": 970.0,
    },
    "NVDA": {
        "ebit": 80_000, "tax_rate": 0.13, "invested_capital": 55_000, "wacc": 0.11,
        "da": 2_000, "delta_nwc": 9_000, "capex": 3_500, "ocf": 64_000,
        "net_income": 72_000, "total_assets": 110_000, "shares_out": 24_500, "price": 185.0,
    },
    "XOM": {
        "ebit": 40_000, "tax_rate": 0.24, "invested_capital": 200_000, "wacc": 0.075,
        "da": 12_000, "delta_nwc": 1_000, "capex": 27_000, "ocf": 55_000,
        "net_income": 33_000, "total_assets": 380_000, "shares_out": 4_250, "price": 118.0,
    },
    "F": {
        "ebit": 6_000, "tax_rate": 0.21, "invested_capital": 95_000, "wacc": 0.09,
        "da": 8_500, "delta_nwc": 2_000, "capex": 8_800, "ocf": 14_000,
        "net_income": 5_000, "total_assets": 270_000, "shares_out": 4_000, "price": 12.5,
    },
    "BA": {
        "ebit": -2_000, "tax_rate": 0.21, "invested_capital": 60_000, "wacc": 0.09,
        "da": 1_900, "delta_nwc": 3_000, "capex": 2_100, "ocf": -1_500,
        "net_income": -3_500, "total_assets": 140_000, "shares_out": 620, "price": 175.0,
    },
    "DHI": {
        "ebit": 4_200, "tax_rate": 0.24, "invested_capital": 18_000, "wacc": 0.10,
        "da": 60, "delta_nwc": 2_800, "capex": 90, "ocf": 1_200,
        "net_income": 3_100, "total_assets": 24_000, "shares_out": 300, "price": 175.0,
    },
}

QUALITY_FACTOR_METHODOLOGY: list[dict[str, Any]] = [
    {
        "id": "roic_vs_wacc",
        "name": "ROIC vs. WACC Economic Spread",
        "formula": "ROIC = NOPAT / Invested Capital; NOPAT = EBIT x (1 - Tax Rate)",
        "description": "Positive spread (ROIC > WACC) generates Economic Value Added (EVA); negative spread destroys capital.",
    },
    {
        "id": "fcf_conversion",
        "name": "Free Cash Flow Conversion",
        "formula": "FCF Conversion = FCFE / Net Income; FCFE = OCF - CapEx",
        "description": "High-quality firms convert accounting earnings to cash at or above ~100%.",
    },
    {
        "id": "fcf_yield",
        "name": "Free Cash Flow Yield",
        "formula": "FCF Yield = FCF per Share / Price per Share",
        "description": "Gauges valuation richness of a quality name's cash-generating power.",
    },
    {
        "id": "accrual_ratio",
        "name": "Accrual Ratio (Earnings Quality)",
        "formula": "Accrual Ratio = (Net Income - FCF) / Total Assets",
        "description": "A rising accrual ratio flags reported profits outpacing cash generation.",
    },
    {
        "id": "sustainable_growth",
        "name": "Sustainable Growth Rate",
        "formula": "Sustainable Growth Rate = ROIC x Reinvestment Rate",
        "description": "Caps organic, self-funded growth without dilutive equity or toxic debt.",
    },
]

QUADRANT_LABELS: dict[tuple[bool, bool], str] = {
    (True, True): "Compounder Machine",
    (True, False): "Paper Tiger Profits",
    (False, True): "Mature Cash Cow",
    (False, False): "Structural Value Trap",
}

FCF_CONVERSION_HIGH_THRESHOLD = 0.85
HIGH_VALUATION_FCF_YIELD_THRESHOLD = 0.025
HIGH_CAPEX_TO_DA_RATIO = 2.0
COMPETITIVE_REVERSION_SPREAD_THRESHOLD = 0.30


@dataclass
class QualityCompany:
    symbol: str
    name: str
    sector: str
    price: float
    nopat: float
    invested_capital: float
    roic: float
    wacc: float
    eva_spread: float
    fcff: float
    fcfe: float
    fcf_conversion: float | None
    fcf_per_share: float
    fcf_yield: float
    accrual_ratio: float
    reinvestment_rate: float | None
    sustainable_growth_rate: float | None
    quadrant: str
    macro_flags: list[str]
    summary: str
    data_source: str


@dataclass
class QualityFactorReport:
    companies: list[QualityCompany]
    quadrant_counts: dict[str, int]
    avg_eva_spread: float
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class QualityFactorExpert(BaseExpert):
    """Analyst covering ROIC/WACC economic spread and FCF cash-conversion quality."""

    def __init__(self, *, pipeline_context: dict | None = None) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="quality-factor")

    def _fetch_live_fundamentals(self, symbol: str) -> dict[str, float] | None:
        try:
            resp = requests.get(
                QUOTE_SUMMARY_API.format(symbol=symbol),
                params={"modules": QUOTE_SUMMARY_MODULES},
                headers=HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
            result = resp.json()["quoteSummary"]["result"][0]
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError):
            return None

        try:
            fin = result.get("financialData", {}) or {}
            income = (result.get("incomeStatementHistory", {}) or {}).get("incomeStatementHistory", [{}])[0]
            balance = (result.get("balanceSheetHistory", {}) or {}).get("balanceSheetStatements", [{}])[0]
            cashflow = (result.get("cashflowStatementHistory", {}) or {}).get("cashflowStatements", [{}])[0]
            stats = result.get("defaultKeyStatistics", {}) or {}

            def _raw(node: dict[str, Any], key: str) -> float | None:
                value = node.get(key)
                if isinstance(value, dict):
                    value = value.get("raw")
                return float(value) if value is not None else None

            ebit = _raw(income, "ebit")
            tax_rate = _raw(fin, "effectiveTaxRate") or 0.21
            total_assets = _raw(balance, "totalAssets")
            net_income = _raw(income, "netIncome")
            ocf = _raw(cashflow, "totalCashFromOperatingActivities")
            capex = abs(_raw(cashflow, "capitalExpenditures") or 0.0)
            da = _raw(cashflow, "depreciation")
            shares_out = _raw(stats, "sharesOutstanding")
            price = _raw(fin, "currentPrice")

            required = [ebit, total_assets, net_income, ocf, da, shares_out, price]
            if any(v is None for v in required) or not total_assets:
                return None

            invested_capital = total_assets * 0.55  # operating-approach approximation
            return {
                "ebit": ebit / 1e6,
                "tax_rate": tax_rate,
                "invested_capital": invested_capital / 1e6,
                "wacc": 0.09,
                "da": da / 1e6,
                "delta_nwc": 0.0,
                "capex": capex / 1e6,
                "ocf": ocf / 1e6,
                "net_income": net_income / 1e6,
                "total_assets": total_assets / 1e6,
                "shares_out": shares_out / 1e6,
                "price": price,
            }
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    def _fetch_universe(self) -> tuple[dict[str, dict[str, float]], list[str]]:
        by_symbol: dict[str, dict[str, float]] = {}
        live_hits = 0
        for symbol in QUALITY_UNIVERSE:
            live = self._fetch_live_fundamentals(symbol)
            if live:
                by_symbol[symbol] = {**live, "_source": "live"}
                live_hits += 1
            else:
                by_symbol[symbol] = {**PROXY_FUNDAMENTALS[symbol], "_source": "proxy"}

        sources: list[str] = []
        if live_hits:
            sources.append(f"Yahoo Finance quoteSummary ({live_hits}/{len(QUALITY_UNIVERSE)} live)")
        if live_hits < len(QUALITY_UNIVERSE):
            sources.append("Calibrated fundamentals proxy (quoteSummary unavailable for remaining names)")
        return by_symbol, sources

    @staticmethod
    def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
        return max(low, min(high, value))

    def _analyze_company(self, symbol: str, fundamentals: dict[str, float]) -> QualityCompany:
        meta = QUALITY_UNIVERSE[symbol]
        ebit = fundamentals["ebit"]
        tax_rate = fundamentals["tax_rate"]
        invested_capital = fundamentals["invested_capital"]
        wacc = fundamentals["wacc"]
        da = fundamentals["da"]
        delta_nwc = fundamentals["delta_nwc"]
        capex = fundamentals["capex"]
        ocf = fundamentals["ocf"]
        net_income = fundamentals["net_income"]
        total_assets = fundamentals["total_assets"]
        shares_out = fundamentals["shares_out"]
        price = fundamentals["price"]
        source = fundamentals.get("_source", "proxy")

        nopat = ebit * (1 - tax_rate)
        roic = nopat / invested_capital if invested_capital else 0.0
        eva_spread = roic - wacc

        fcff = nopat + da - delta_nwc - capex
        fcfe = ocf - capex
        fcf_conversion = (fcfe / net_income) if net_income else None
        fcf_per_share = fcfe / shares_out if shares_out else 0.0
        fcf_yield = fcf_per_share / price if price else 0.0
        accrual_ratio = (net_income - fcfe) / total_assets if total_assets else 0.0

        reinvestment_rate = None
        sustainable_growth_rate = None
        if nopat > 0:
            reinvestment_rate = round(self._clamp((capex + delta_nwc - da) / nopat), 4)
            sustainable_growth_rate = round(roic * reinvestment_rate, 4)

        high_roic = eva_spread > 0
        high_fcf = (
            net_income > 0
            and fcf_conversion is not None
            and fcf_conversion >= FCF_CONVERSION_HIGH_THRESHOLD
        )
        quadrant = QUADRANT_LABELS[(high_roic, high_fcf)]

        flags: list[str] = []
        if fcf_yield and 0 < fcf_yield < HIGH_VALUATION_FCF_YIELD_THRESHOLD:
            flags.append("Growth-at-any-price premium: thin FCF yield leaves little valuation margin of safety")
        if da and capex / da >= HIGH_CAPEX_TO_DA_RATIO:
            flags.append("CapEx/inflation shock: heavy capital intensity vs. depreciation base compresses FCF if input costs spike")
        if eva_spread >= COMPETITIVE_REVERSION_SPREAD_THRESHOLD:
            flags.append("Competitive reversion risk: outsized ROIC-WACC spread is a beacon for capital and disruptive entrants")
        elif eva_spread < 0:
            flags.append("Capital destruction: ROIC below WACC — every incremental project erodes shareholder value")

        conv_label = f"{fcf_conversion * 100:.0f}%" if fcf_conversion is not None else "n/m (net loss)"
        summary = (
            f"{meta['name']} ({symbol}): ROIC {roic * 100:.1f}% vs. WACC {wacc * 100:.1f}% "
            f"(spread {eva_spread * 100:+.1f}pp), FCF conversion {conv_label} — {quadrant}"
        )

        return QualityCompany(
            symbol=symbol,
            name=meta["name"],
            sector=meta["sector"],
            price=round(price, 2),
            nopat=round(nopat, 1),
            invested_capital=round(invested_capital, 1),
            roic=round(roic, 4),
            wacc=round(wacc, 4),
            eva_spread=round(eva_spread, 4),
            fcff=round(fcff, 1),
            fcfe=round(fcfe, 1),
            fcf_conversion=round(fcf_conversion, 4) if fcf_conversion is not None else None,
            fcf_per_share=round(fcf_per_share, 2),
            fcf_yield=round(fcf_yield, 4),
            accrual_ratio=round(accrual_ratio, 4),
            reinvestment_rate=reinvestment_rate,
            sustainable_growth_rate=sustainable_growth_rate,
            quadrant=quadrant,
            macro_flags=flags,
            summary=summary,
            data_source=source,
        )

    def _market_signal(self, company: QualityCompany) -> dict[str, Any]:
        from agent_signal_logic import build_market_signal

        if company.quadrant == "Compounder Machine":
            bias = "BULLISH"
        elif company.quadrant == "Structural Value Trap":
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"

        confidence = self._clamp(0.5 + abs(company.eva_spread) * 1.2, 0.15, 0.95)
        return build_market_signal(
            sector=f"Quality Factor — {company.sector}",
            tickers=[company.symbol],
            bias=bias,
            reason=company.summary,
            confidence=confidence,
            evidence={
                "roic": company.roic,
                "wacc": company.wacc,
                "eva_spread": company.eva_spread,
                "fcf_conversion": company.fcf_conversion,
                "quadrant": company.quadrant,
            },
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

    def analyze(self) -> QualityFactorReport:
        raw_fundamentals, sources = self._fetch_universe()

        companies = [self._analyze_company(symbol, raw_fundamentals[symbol]) for symbol in QUALITY_UNIVERSE]
        signals = self._adjust_market_signals([self._market_signal(c) for c in companies])

        quadrant_counts: dict[str, int] = {}
        for c in companies:
            quadrant_counts[c.quadrant] = quadrant_counts.get(c.quadrant, 0) + 1
        avg_eva_spread = round(sum(c.eva_spread for c in companies) / len(companies), 4) if companies else 0.0

        compounders = [c.symbol for c in companies if c.quadrant == "Compounder Machine"]
        traps = [c.symbol for c in companies if c.quadrant == "Structural Value Trap"]
        expert_summary = (
            f"Quality factor scan of {len(companies)} names: {quadrant_counts.get('Compounder Machine', 0)} "
            f"Compounder Machines ({', '.join(compounders) or 'none'}), "
            f"{quadrant_counts.get('Structural Value Trap', 0)} Structural Value Traps ({', '.join(traps) or 'none'}); "
            f"average EVA spread {avg_eva_spread * 100:+.1f}pp."
        )

        recs = [f"Universe EVA spread average: {avg_eva_spread * 100:+.1f}pp across {len(companies)} names"]
        for c in sorted(companies, key=lambda x: x.eva_spread, reverse=True):
            recs.append(c.summary)
            for flag in c.macro_flags:
                recs.append(f"  ⚠ {c.symbol}: {flag}")

        return QualityFactorReport(
            companies=companies,
            quadrant_counts=quadrant_counts,
            avg_eva_spread=avg_eva_spread,
            expert_summary=expert_summary,
            market_signals=signals,
            recommendations=self.append_memory_recommendations(recs),
            data_sources=sources,
        )

    def to_dict(self, report: QualityFactorReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Quality Factor Expert",
                "analyzed_at": report.analyzed_at,
                "expert_summary": report.expert_summary,
                "companies_analyzed": len(report.companies),
                "data_sources": report.data_sources,
            },
            "companies": [
                {
                    "symbol": c.symbol,
                    "name": c.name,
                    "sector": c.sector,
                    "price": c.price,
                    "roic": c.roic,
                    "wacc": c.wacc,
                    "eva_spread": c.eva_spread,
                    "nopat": c.nopat,
                    "invested_capital": c.invested_capital,
                    "fcff": c.fcff,
                    "fcfe": c.fcfe,
                    "fcf_conversion": c.fcf_conversion,
                    "fcf_per_share": c.fcf_per_share,
                    "fcf_yield": c.fcf_yield,
                    "accrual_ratio": c.accrual_ratio,
                    "reinvestment_rate": c.reinvestment_rate,
                    "sustainable_growth_rate": c.sustainable_growth_rate,
                    "quadrant": c.quadrant,
                    "macro_flags": c.macro_flags,
                    "summary": c.summary,
                    "data_source": c.data_source,
                }
                for c in report.companies
            ],
            "metrics": {
                "quadrant_counts": report.quadrant_counts,
                "avg_eva_spread": report.avg_eva_spread,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            methodology_path = output.parent / "quality_factor_methodology.json"
            methodology_path.write_text(
                json.dumps(QUALITY_FACTOR_METHODOLOGY, indent=2),
                encoding="utf-8",
            )
        return result


def run_quality_factor_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return QualityFactorExpert(pipeline_context=pipeline_context).run(output=output)
