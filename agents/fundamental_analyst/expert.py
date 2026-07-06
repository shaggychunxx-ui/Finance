"""
Fundamental Analyst Agent — "The Grounding Force"
==================================================
Mission: prevent the system from buying "junk" companies or trading against
long-term macroeconomic gravity by anchoring every symbol to real corporate
filings rather than price action or hype.

API interfacing:
  * SEC EDGAR ``companyfacts`` XBRL API (``data.sec.gov``) — free, keyless,
    standardized US-GAAP corporate financial statement data straight from
    10-K/10-Q filings.
  * Yahoo Finance chart API — last traded price, used together with EDGAR
    shares-outstanding to derive an approximate market capitalization for
    free-cash-flow yield.

Mathematical processing: Return on Invested Capital (ROIC), Debt-to-Equity
(D/E), and free-cash-flow (FCF) yield are computed from the two most recent
annual filings (to show a trend), then compared against static historical
sector averages. When a symbol's valuation/leverage materially diverges from
its sector norm (e.g. a hype-driven microcap trading far above sane
multiples, or leverage/ROIC that fails the sector bar), the agent injects an
"Overvalued Risk" / "Junk Risk" state that downstream agents (Consensus
Router, Risk Guardrail) can use to veto or downsize a trade.
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

SEC_COMPANYFACTS_API = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:0>10}.json"
CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Finance-Fundamental-Analyst/1.0 (shaggychunxx@gmail.com)"}

# Ticker -> (SEC EDGAR CIK, sector) for a diversified, liquid watchlist.
WATCHLIST: dict[str, tuple[int, str]] = {
    "AAPL": (320193, "Technology"),
    "MSFT": (789019, "Technology"),
    "NVDA": (1045810, "Technology"),
    "AMZN": (1018724, "Consumer Discretionary"),
    "TSLA": (1318605, "Consumer Discretionary"),
    "JPM": (19617, "Financials"),
    "XOM": (34088, "Energy"),
    "JNJ": (200406, "Healthcare"),
}

# Static historical sectoral averages used as the "grounding" comparison
# baseline (approximate, illustrative long-run figures).
SECTOR_AVERAGES: dict[str, dict[str, float]] = {
    "Technology": {"roic_pct": 18.0, "debt_to_equity": 0.8, "fcf_yield_pct": 3.0},
    "Consumer Discretionary": {"roic_pct": 12.0, "debt_to_equity": 1.2, "fcf_yield_pct": 2.0},
    "Financials": {"roic_pct": 9.0, "debt_to_equity": 2.5, "fcf_yield_pct": 4.0},
    "Energy": {"roic_pct": 10.0, "debt_to_equity": 0.6, "fcf_yield_pct": 6.0},
    "Healthcare": {"roic_pct": 13.0, "debt_to_equity": 0.9, "fcf_yield_pct": 3.5},
    "Industrials": {"roic_pct": 11.0, "debt_to_equity": 1.1, "fcf_yield_pct": 3.0},
    "default": {"roic_pct": 11.0, "debt_to_equity": 1.0, "fcf_yield_pct": 3.0},
}

# US-GAAP XBRL tags read from the SEC companyfacts payload.
TAGS = {
    "assets": "Assets",
    "liabilities": "Liabilities",
    "equity": "StockholdersEquity",
    "net_income": "NetIncomeLoss",
    "operating_income": "OperatingIncomeLoss",
    "pretax_income": "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "tax_expense": "IncomeTaxExpenseBenefit",
    "operating_cash_flow": "NetCashProvidedByUsedInOperatingActivities",
    "capex": "PaymentsToAcquirePropertyPlantAndEquipment",
    "long_term_debt": "LongTermDebtNoncurrent",
    "short_term_debt": "ShortTermBorrowings",
    "shares_outstanding": "CommonStockSharesOutstanding",
}

OVERVALUED_ROIC_GAP_PCT = -5.0  # ROIC this far below sector avg is a red flag
OVERVALUED_DE_MULTIPLE = 1.75  # D/E this many times the sector avg is a red flag
JUNK_FCF_YIELD_PCT = 0.0  # negative/zero FCF yield contributes to "junk" risk


@dataclass
class FundamentalSnapshot:
    symbol: str
    sector: str
    fiscal_year: int | None
    roic_pct: float | None
    roic_prior_pct: float | None
    debt_to_equity: float | None
    fcf_yield_pct: float | None
    market_cap: float | None
    sector_roic_avg_pct: float
    sector_de_avg: float
    sector_fcf_yield_avg_pct: float
    risk_state: str
    rationale: str


@dataclass
class FundamentalAnalystReport:
    snapshots: list[FundamentalSnapshot]
    grounding_verdict: str
    overvalued_risk_count: int
    junk_risk_count: int
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FundamentalAnalystExpert(BaseExpert):
    """The 'grounding force' — anchors trades to real filings, not hype."""

    def __init__(self, delay_seconds: float = 0.25) -> None:
        super().__init__()
        self.delay_seconds = delay_seconds

    # -- data fetching -------------------------------------------------
    def _fetch_companyfacts(self, cik: int) -> dict[str, Any]:
        try:
            resp = requests.get(
                SEC_COMPANYFACTS_API.format(cik=cik),
                headers=HEADERS,
                timeout=25,
            )
            if resp.status_code == 429:
                time.sleep(2)
                resp = requests.get(
                    SEC_COMPANYFACTS_API.format(cik=cik),
                    headers=HEADERS,
                    timeout=25,
                )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return {}

    def _fetch_last_price(self, symbol: str) -> float | None:
        try:
            resp = requests.get(
                CHART_API.format(symbol=symbol),
                params={"interval": "1d", "range": "5d"},
                headers=HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
            meta = resp.json()["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice")
            return float(price) if price is not None else None
        except Exception:
            return None

    @staticmethod
    def _annual_series(facts: dict[str, Any], tag: str) -> list[dict[str, Any]]:
        """Return 10-K annual USD (or shares) data points for a tag, newest first."""
        us_gaap = facts.get("facts", {}).get("us-gaap", {})
        node = us_gaap.get(tag)
        if not node:
            return []
        units = node.get("units", {})
        rows = units.get("USD") or units.get("shares") or []
        annual = [r for r in rows if r.get("form") == "10-K" and r.get("fp") == "FY"]
        annual.sort(key=lambda r: r.get("end", ""), reverse=True)
        return annual

    def _value_for_year(self, facts: dict[str, Any], tag: str, index: int) -> float | None:
        series = self._annual_series(facts, tag)
        if index >= len(series):
            return None
        val = series[index].get("val")
        return float(val) if val is not None else None

    # -- math ------------------------------------------------------------
    def _compute_roic(self, facts: dict[str, Any], index: int) -> tuple[float | None, int | None]:
        net_income = self._value_for_year(facts, TAGS["net_income"], index)
        pretax = self._value_for_year(facts, TAGS["pretax_income"], index)
        tax = self._value_for_year(facts, TAGS["tax_expense"], index)
        operating_income = self._value_for_year(facts, TAGS["operating_income"], index)
        equity = self._value_for_year(facts, TAGS["equity"], index)
        lt_debt = self._value_for_year(facts, TAGS["long_term_debt"], index) or 0.0
        st_debt = self._value_for_year(facts, TAGS["short_term_debt"], index) or 0.0

        if equity is None:
            return None, None

        tax_rate = 0.21  # default US statutory corporate tax rate fallback
        if pretax and tax is not None and pretax != 0:
            tax_rate = max(0.0, min(0.5, tax / pretax))

        nopat = (operating_income if operating_income is not None else net_income)
        if nopat is None:
            return None, None
        nopat_after_tax = nopat * (1 - tax_rate)

        invested_capital = equity + lt_debt + st_debt
        if not invested_capital:
            return None, None

        roic_pct = (nopat_after_tax / invested_capital) * 100
        series = self._annual_series(facts, TAGS["equity"])
        fiscal_year = None
        if index < len(series):
            end = series[index].get("end", "")
            fiscal_year = int(end[:4]) if end[:4].isdigit() else None
        return round(roic_pct, 2), fiscal_year

    def _compute_debt_to_equity(self, facts: dict[str, Any], index: int) -> float | None:
        liabilities = self._value_for_year(facts, TAGS["liabilities"], index)
        equity = self._value_for_year(facts, TAGS["equity"], index)
        if liabilities is None or not equity:
            return None
        return round(liabilities / equity, 2)

    def _compute_fcf_yield(
        self, facts: dict[str, Any], index: int, market_cap: float | None
    ) -> float | None:
        ocf = self._value_for_year(facts, TAGS["operating_cash_flow"], index)
        capex = self._value_for_year(facts, TAGS["capex"], index) or 0.0
        if ocf is None or not market_cap:
            return None
        fcf = ocf - abs(capex)
        return round((fcf / market_cap) * 100, 2)

    def _market_cap(self, facts: dict[str, Any], price: float | None) -> float | None:
        shares = self._value_for_year(facts, TAGS["shares_outstanding"], 0)
        if not shares or price is None:
            return None
        return round(shares * price, 2)

    def _risk_state(
        self,
        roic_pct: float | None,
        de: float | None,
        fcf_yield_pct: float | None,
        sector_avg: dict[str, float],
    ) -> tuple[str, str]:
        reasons: list[str] = []
        risk = "Grounded"

        if roic_pct is not None and roic_pct - sector_avg["roic_pct"] <= OVERVALUED_ROIC_GAP_PCT:
            reasons.append(
                f"ROIC {roic_pct}% trails sector average {sector_avg['roic_pct']}% by "
                f"{round(sector_avg['roic_pct'] - roic_pct, 1)}pts"
            )
            risk = "Junk Risk"

        if de is not None and sector_avg["debt_to_equity"] and de >= sector_avg["debt_to_equity"] * OVERVALUED_DE_MULTIPLE:
            reasons.append(
                f"D/E {de} is {round(de / sector_avg['debt_to_equity'], 1)}x the sector norm "
                f"({sector_avg['debt_to_equity']})"
            )
            risk = "Overvalued Risk" if risk == "Grounded" else "Junk & Overvalued Risk"

        if fcf_yield_pct is not None and fcf_yield_pct <= JUNK_FCF_YIELD_PCT:
            reasons.append(f"FCF yield {fcf_yield_pct}% is non-positive")
            risk = "Junk Risk" if risk == "Grounded" else risk

        if not reasons:
            reasons.append("Valuation and leverage sit within historical sector norms")

        return risk, "; ".join(reasons)

    def _analyze_symbol(self, symbol: str, cik: int, sector: str) -> FundamentalSnapshot | None:
        facts = self._fetch_companyfacts(cik)
        if not facts:
            return None
        time.sleep(self.delay_seconds)
        price = self._fetch_last_price(symbol)

        roic_pct, fiscal_year = self._compute_roic(facts, 0)
        roic_prior_pct, _ = self._compute_roic(facts, 1)
        de = self._compute_debt_to_equity(facts, 0)
        market_cap = self._market_cap(facts, price)
        fcf_yield_pct = self._compute_fcf_yield(facts, 0, market_cap)

        sector_avg = SECTOR_AVERAGES.get(sector, SECTOR_AVERAGES["default"])
        risk_state, rationale = self._risk_state(roic_pct, de, fcf_yield_pct, sector_avg)

        return FundamentalSnapshot(
            symbol=symbol,
            sector=sector,
            fiscal_year=fiscal_year,
            roic_pct=roic_pct,
            roic_prior_pct=roic_prior_pct,
            debt_to_equity=de,
            fcf_yield_pct=fcf_yield_pct,
            market_cap=market_cap,
            sector_roic_avg_pct=sector_avg["roic_pct"],
            sector_de_avg=sector_avg["debt_to_equity"],
            sector_fcf_yield_avg_pct=sector_avg["fcf_yield_pct"],
            risk_state=risk_state,
            rationale=rationale,
        )

    def _market_signals(self, snapshots: list[FundamentalSnapshot]) -> list[dict[str, Any]]:
        signals = []
        for s in snapshots:
            if s.risk_state == "Grounded":
                continue
            signals.append(
                {
                    "sector": s.sector,
                    "bias": "avoid" if "Junk" in s.risk_state else "caution",
                    "tickers": [s.symbol],
                    "reason": f"{s.risk_state}: {s.rationale}",
                }
            )
        return signals

    def _recommendations(self, snapshots: list[FundamentalSnapshot]) -> list[str]:
        recs = []
        for s in snapshots:
            if s.risk_state != "Grounded":
                recs.append(
                    f"{s.symbol}: flag '{s.risk_state}' in system memory — block/downsize "
                    "momentum-driven allocation until fundamentals re-anchor."
                )
            else:
                recs.append(f"{s.symbol}: fundamentals grounded; no valuation veto required.")
        return recs

    def analyze(self) -> FundamentalAnalystReport:
        snapshots: list[FundamentalSnapshot] = []
        for symbol, (cik, sector) in WATCHLIST.items():
            snap = self._analyze_symbol(symbol, cik, sector)
            if snap:
                snapshots.append(snap)

        overvalued = sum(1 for s in snapshots if "Overvalued" in s.risk_state)
        junk = sum(1 for s in snapshots if "Junk" in s.risk_state)

        if not snapshots:
            grounding_verdict = "No filings retrieved — grounding check unavailable this run"
        elif overvalued or junk:
            grounding_verdict = (
                f"{overvalued + junk} of {len(snapshots)} symbols fail the fundamental "
                "grounding check — momentum allocation should be capped for those names"
            )
        else:
            grounding_verdict = f"All {len(snapshots)} tracked symbols are fundamentally grounded"

        expert_summary = (
            "Fundamental Analyst cross-checked SEC EDGAR 10-K filings against sector ROIC, "
            f"D/E, and FCF-yield norms. {grounding_verdict}."
        )

        return FundamentalAnalystReport(
            snapshots=snapshots,
            grounding_verdict=grounding_verdict,
            overvalued_risk_count=overvalued,
            junk_risk_count=junk,
            expert_summary=expert_summary,
            market_signals=self._market_signals(snapshots),
            recommendations=self._recommendations(snapshots),
            data_source="SEC EDGAR companyfacts XBRL API + Yahoo Finance Chart API",
        )

    def to_dict(self, report: FundamentalAnalystReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Fundamental Analyst Agent (The Grounding Force)",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
                "temperature": self.temperature,
            },
            "snapshots": [
                {
                    "symbol": s.symbol,
                    "sector": s.sector,
                    "fiscal_year": s.fiscal_year,
                    "roic_pct": s.roic_pct,
                    "roic_prior_pct": s.roic_prior_pct,
                    "debt_to_equity": s.debt_to_equity,
                    "fcf_yield_pct": s.fcf_yield_pct,
                    "market_cap": s.market_cap,
                    "sector_roic_avg_pct": s.sector_roic_avg_pct,
                    "sector_de_avg": s.sector_de_avg,
                    "sector_fcf_yield_avg_pct": s.sector_fcf_yield_avg_pct,
                    "risk_state": s.risk_state,
                    "rationale": s.rationale,
                }
                for s in report.snapshots
            ],
            "metrics": {
                "grounding_verdict": report.grounding_verdict,
                "overvalued_risk_count": report.overvalued_risk_count,
                "junk_risk_count": report.junk_risk_count,
                "symbols_analyzed": len(report.snapshots),
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "sector_valuation_baselines.json"
            catalog.write_text(json.dumps(SECTOR_AVERAGES, indent=2), encoding="utf-8")
        return result


def run_fundamental_analyst_analysis(output: Path | None = None) -> dict[str, Any]:
    return FundamentalAnalystExpert().run(output=output)
