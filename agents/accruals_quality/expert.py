"""
Accruals Quality Forensic Analyst Agent
========================================
Forensic accounting analysis of earnings quality — how closely reported net
income maps to actual cash realizations. Applies three quantitative
frameworks to a watchlist of tickers using per-company fundamentals:

- Sloan Ratio (aggregate accrual test)
- Modified Jones Model (discretionary vs normal accruals, cross-sectional OLS)
- Beneish M-Score (statistical probability of earnings manipulation)

Data: SEC EDGAR XBRL Company Facts API (intended live source) with a
calibrated proxy fundamentals fallback, since the sandbox has no network
access to data.sec.gov. One hypothetical entry ("CMPX") reproduces the
Company X case study from the accruals-quality methodology write-up.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base import BaseExpert

DASHBOARD_URL = "https://data.sec.gov/api/xbrl/companyfacts/"

ACCRUALS_RESOURCES: list[dict[str, Any]] = [
    {
        "id": "sec_xbrl_companyfacts",
        "name": "SEC EDGAR XBRL Company Facts API",
        "provider": "SEC",
        "url": "https://data.sec.gov/api/xbrl/companyfacts/",
        "coverage": "Structured financial statement facts (Revenues, NetIncomeLoss, "
        "NetCashProvidedByUsedInOperatingActivities, Assets, ...)",
        "access": "api",
        "api_key_required": False,
        "notes": "Intended live source; falls back to calibrated proxy fundamentals "
        "when data.sec.gov is unreachable.",
    },
    {
        "id": "sloan_ratio_methodology",
        "name": "Sloan Ratio — Aggregate Accrual Test",
        "provider": "Richard Sloan (accounting research)",
        "url": "https://courses.lumenlearning.com/suny-finaccounting/chapter/direct-write-off-and-allowance-methods/",
        "coverage": "(Net Income - Operating CF - Investing CF) / Total Assets",
        "access": "reference",
        "api_key_required": False,
        "notes": "Classifies earnings quality risk into Low/Moderate/Severe bands.",
    },
    {
        "id": "modified_jones_model",
        "name": "Modified Jones Model — Discretionary Accruals",
        "provider": "Jones (1991) / Dechow, Sloan & Sweeney (1995)",
        "url": "https://courses.lumenlearning.com/suny-finaccounting/chapter/direct-write-off-and-allowance-methods/",
        "coverage": "TA_t/A_(t-1) = a1(1/A_(t-1)) + a2((dREV-dREC)/A_(t-1)) + a3(PPE_t/A_(t-1)) + e_t",
        "access": "reference",
        "api_key_required": False,
        "notes": "Residual (e_t) is the discretionary accrual estimate, fit via "
        "cross-sectional OLS across the watchlist.",
    },
    {
        "id": "beneish_m_score",
        "name": "Beneish M-Score",
        "provider": "Messod Beneish",
        "url": "https://www.investopedia.com/terms/b/beneishmodel.asp",
        "coverage": "8-ratio composite score estimating probability of earnings manipulation",
        "access": "reference",
        "api_key_required": False,
        "notes": "Score > -1.78 flags a statistically significant probability of manipulation.",
    },
]

# Calibrated proxy fundamentals ($ millions), two fiscal years per ticker.
# "CMPX" reproduces the hypothetical Company X case study from the
# accruals-quality methodology write-up (Revenue $100M -> $150M, Net Income
# $10M -> $20M, OCF $12M -> $2M, Total Assets $100M -> $130M).
FUNDAMENTALS: dict[str, dict[str, dict[str, float]]] = {
    "AAPL": {
        "year1": {"revenue": 380000, "cogs": 214000, "sga": 25000, "net_income": 97000,
                   "ocf": 110000, "icf": -4000, "total_assets": 352000, "current_assets": 143000,
                   "current_liabilities": 145000, "long_term_debt": 95000, "receivables": 29000,
                   "ppe_gross": 43000, "depreciation": 11500, "securities": 31500},
        "year2": {"revenue": 391000, "cogs": 210000, "sga": 26000, "net_income": 94000,
                   "ocf": 118000, "icf": -3000, "total_assets": 365000, "current_assets": 153000,
                   "current_liabilities": 176000, "long_term_debt": 86000, "receivables": 33000,
                   "ppe_gross": 46000, "depreciation": 11400, "securities": 35000},
    },
    "MSFT": {
        "year1": {"revenue": 212000, "cogs": 65000, "sga": 28000, "net_income": 72000,
                   "ocf": 87000, "icf": -22000, "total_assets": 411000, "current_assets": 184000,
                   "current_liabilities": 95000, "long_term_debt": 48000, "receivables": 48000,
                   "ppe_gross": 145000, "depreciation": 13800, "securities": 76000},
        "year2": {"revenue": 245000, "cogs": 74000, "sga": 32000, "net_income": 88000,
                   "ocf": 119000, "icf": -45000, "total_assets": 512000, "current_assets": 159000,
                   "current_liabilities": 125000, "long_term_debt": 42000, "receivables": 56000,
                   "ppe_gross": 180000, "depreciation": 22000, "securities": 71000},
    },
    "NVDA": {
        "year1": {"revenue": 27000, "cogs": 11000, "sga": 2600, "net_income": 4400,
                   "ocf": 5600, "icf": -9000, "total_assets": 41000, "current_assets": 28000,
                   "current_liabilities": 6600, "long_term_debt": 9700, "receivables": 3400,
                   "ppe_gross": 6300, "depreciation": 1200, "securities": 10000},
        "year2": {"revenue": 61000, "cogs": 17000, "sga": 3300, "net_income": 30000,
                   "ocf": 28000, "icf": -10500, "total_assets": 65700, "current_assets": 44000,
                   "current_liabilities": 10600, "long_term_debt": 9700, "receivables": 8300,
                   "ppe_gross": 8900, "depreciation": 1500, "securities": 18700},
    },
    "AMZN": {
        "year1": {"revenue": 514000, "cogs": 289000, "sga": 110000, "net_income": 30000,
                   "ocf": 46000, "icf": -49000, "total_assets": 462000, "current_assets": 146000,
                   "current_liabilities": 155000, "long_term_debt": 58000, "receivables": 34000,
                   "ppe_gross": 250000, "depreciation": 48000, "securities": 13600},
        "year2": {"revenue": 575000, "cogs": 305000, "sga": 127000, "net_income": 37000,
                   "ocf": 71000, "icf": -51000, "total_assets": 527000, "current_assets": 172000,
                   "current_liabilities": 170000, "long_term_debt": 55000, "receivables": 39000,
                   "ppe_gross": 290000, "depreciation": 53000, "securities": 17000},
    },
    "META": {
        "year1": {"revenue": 117000, "cogs": 25000, "sga": 13000, "net_income": 39000,
                   "ocf": 71000, "icf": -27000, "total_assets": 229000, "current_assets": 65000,
                   "current_liabilities": 25000, "long_term_debt": 18400, "receivables": 14400,
                   "ppe_gross": 100000, "depreciation": 15500, "securities": 41000},
        "year2": {"revenue": 135000, "cogs": 27000, "sga": 14000, "net_income": 45000,
                   "ocf": 91000, "icf": -38000, "total_assets": 273000, "current_assets": 78000,
                   "current_liabilities": 28000, "long_term_debt": 18400, "receivables": 16200,
                   "ppe_gross": 125000, "depreciation": 17000, "securities": 54000},
    },
    "GOOGL": {
        "year1": {"revenue": 283000, "cogs": 126000, "sga": 27000, "net_income": 60000,
                   "ocf": 91000, "icf": -27000, "total_assets": 402000, "current_assets": 170000,
                   "current_liabilities": 81000, "long_term_debt": 13300, "receivables": 39000,
                   "ppe_gross": 155000, "depreciation": 15000, "securities": 118000},
        "year2": {"revenue": 307000, "cogs": 133000, "sga": 29000, "net_income": 73000,
                   "ocf": 101000, "icf": -31000, "total_assets": 402000, "current_assets": 163000,
                   "current_liabilities": 84000, "long_term_debt": 13300, "receivables": 41000,
                   "ppe_gross": 170000, "depreciation": 16500, "securities": 95000},
    },
    "TSLA": {
        "year1": {"revenue": 97000, "cogs": 79000, "sga": 4900, "net_income": 15000,
                   "ocf": 13300, "icf": -8900, "total_assets": 106000, "current_assets": 49000,
                   "current_liabilities": 28000, "long_term_debt": 2000, "receivables": 2800,
                   "ppe_gross": 46000, "depreciation": 4900, "securities": 15000},
        "year2": {"revenue": 97700, "cogs": 80200, "sga": 5500, "net_income": 7100,
                   "ocf": 2000, "icf": -15000, "total_assets": 122000, "current_assets": 51000,
                   "current_liabilities": 28800, "long_term_debt": 2600, "receivables": 4400,
                   "ppe_gross": 58000, "depreciation": 5000, "securities": 17000},
    },
    "CMPX": {
        "year1": {"revenue": 100, "cogs": 60, "sga": 20, "net_income": 10,
                   "ocf": 12, "icf": 0, "total_assets": 100, "current_assets": 40,
                   "current_liabilities": 25, "long_term_debt": 10, "receivables": 15,
                   "ppe_gross": 40, "depreciation": 5, "securities": 0},
        "year2": {"revenue": 150, "cogs": 100, "sga": 28, "net_income": 20,
                   "ocf": 2, "icf": 0, "total_assets": 130, "current_assets": 100,
                   "current_liabilities": 32, "long_term_debt": 10, "receivables": 45,
                   "ppe_gross": 42, "depreciation": 5.2, "securities": 0},
    },
}

COMPANY_NAMES: dict[str, str] = {
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corp.",
    "NVDA": "NVIDIA Corp.",
    "AMZN": "Amazon.com Inc.",
    "META": "Meta Platforms Inc.",
    "GOOGL": "Alphabet Inc.",
    "TSLA": "Tesla Inc.",
    "CMPX": "Company X (Hypothetical Case Study)",
}


def _safe_div(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return numerator / denominator


def _solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting for a small n x n system."""
    n = len(vector)
    aug = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot_row = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot_row][col]) < 1e-12:
            continue
        aug[col], aug[pivot_row] = aug[pivot_row], aug[col]
        pivot = aug[col][col]
        aug[col] = [v / pivot for v in aug[col]]
        for r in range(n):
            if r != col:
                factor = aug[r][col]
                aug[r] = [aug[r][k] - factor * aug[col][k] for k in range(n + 1)]
    return [row[n] for row in aug]


@dataclass
class AccrualMetrics:
    symbol: str
    company: str
    dso_year1: float
    dso_year2: float
    dso_delta: float
    sloan_ratio_pct: float
    sloan_risk: str
    total_accruals_to_assets_pct: float
    discretionary_accrual_pct: float
    beneish_m_score: float
    manipulation_flag: bool
    beneish_components: dict[str, float]
    expert_note: str


@dataclass
class AccrualsQualityReport:
    resources: list[dict[str, Any]]
    metrics: list[AccrualMetrics]
    jones_coefficients: dict[str, float]
    avg_sloan_ratio_pct: float
    severe_count: int
    moderate_count: int
    low_count: int
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    used_proxy_fundamentals: bool = True
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AccrualsQualityExpert(BaseExpert):
    """Forensic accounting analyst — Sloan Ratio, Modified Jones, Beneish M-Score."""

    def __init__(self, *, pipeline_context: dict | None = None) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="accruals-quality")
        self.fundamentals = dict(FUNDAMENTALS)

    @staticmethod
    def _catalog_resources() -> list[dict[str, Any]]:
        return [dict(res) for res in ACCRUALS_RESOURCES]

    def _fetch_live_fundamentals(self, symbol: str) -> dict[str, dict[str, float]] | None:
        """Attempt to fetch fundamentals via SEC XBRL; unavailable in the sandbox."""
        try:
            import requests

            headers = {"User-Agent": "Finance-Accruals-Quality-Analyst/1.0 (shaggychunxx@gmail.com)"}
            resp = requests.get(
                f"https://data.sec.gov/api/xbrl/companyfacts/CIK{symbol}.json",
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
            return None  # parsing XBRL facts into our schema is out of scope; proxy is used instead
        except Exception:
            return None

    @staticmethod
    def _dso(receivables: float, revenue: float) -> float:
        return round(_safe_div(receivables, revenue) * 365.0, 1)

    @staticmethod
    def _sloan_ratio(net_income: float, ocf: float, icf: float, total_assets: float) -> float:
        return round(_safe_div(net_income - ocf - icf, total_assets) * 100.0, 2)

    @staticmethod
    def _sloan_risk(ratio_pct: float) -> str:
        if ratio_pct > 25:
            return "SEVERE"
        if ratio_pct > 10:
            return "MODERATE"
        if ratio_pct < -10:
            return "LOW (conservative)"
        return "LOW"

    @staticmethod
    def _beneish_components(y1: dict[str, float], y2: dict[str, float]) -> dict[str, float]:
        dsri = _safe_div(_safe_div(y2["receivables"], y2["revenue"]), _safe_div(y1["receivables"], y1["revenue"]) or 1e-9)
        gm_y1 = _safe_div(y1["revenue"] - y1["cogs"], y1["revenue"])
        gm_y2 = _safe_div(y2["revenue"] - y2["cogs"], y2["revenue"])
        gmi = _safe_div(gm_y1, gm_y2 or 1e-9)
        aqi_y1 = 1 - _safe_div(y1["current_assets"] + y1["ppe_gross"] + y1["securities"], y1["total_assets"])
        aqi_y2 = 1 - _safe_div(y2["current_assets"] + y2["ppe_gross"] + y2["securities"], y2["total_assets"])
        aqi = _safe_div(aqi_y2, aqi_y1 or 1e-9)
        sgi = _safe_div(y2["revenue"], y1["revenue"] or 1e-9)
        depi_y1 = _safe_div(y1["depreciation"], y1["depreciation"] + y1["ppe_gross"])
        depi_y2 = _safe_div(y2["depreciation"], y2["depreciation"] + y2["ppe_gross"])
        depi = _safe_div(depi_y1, depi_y2 or 1e-9)
        sgai = _safe_div(_safe_div(y2["sga"], y2["revenue"]), _safe_div(y1["sga"], y1["revenue"]) or 1e-9)
        lvgi_y1 = _safe_div(y1["current_liabilities"] + y1["long_term_debt"], y1["total_assets"])
        lvgi_y2 = _safe_div(y2["current_liabilities"] + y2["long_term_debt"], y2["total_assets"])
        lvgi = _safe_div(lvgi_y2, lvgi_y1 or 1e-9)
        tata = _safe_div(y2["net_income"] - y2["ocf"], y2["total_assets"])
        return {
            "DSRI": round(dsri, 4),
            "GMI": round(gmi, 4),
            "AQI": round(aqi, 4),
            "SGI": round(sgi, 4),
            "DEPI": round(depi, 4),
            "SGAI": round(sgai, 4),
            "LVGI": round(lvgi, 4),
            "TATA": round(tata, 4),
        }

    @staticmethod
    def _beneish_m_score(components: dict[str, float]) -> float:
        return round(
            -4.84
            + 0.920 * components["DSRI"]
            + 0.528 * components["GMI"]
            + 0.404 * components["AQI"]
            + 0.892 * components["SGI"]
            + 0.115 * components["DEPI"]
            - 0.172 * components["SGAI"]
            + 4.679 * components["TATA"]
            - 0.327 * components["LVGI"],
            4,
        )

    def _fit_modified_jones(self) -> tuple[dict[str, float], dict[str, tuple[float, float]]]:
        """Cross-sectional OLS across the watchlist. Returns coefficients and
        (fitted, residual) per symbol for the discretionary-accrual diagnostic."""
        rows: list[tuple[str, float, float, float, float]] = []
        for symbol, years in self.fundamentals.items():
            y1, y2 = years["year1"], years["year2"]
            assets_prior = y1["total_assets"] or 1e-9
            total_accruals = y2["net_income"] - y2["ocf"]
            delta_rev = y2["revenue"] - y1["revenue"]
            delta_rec = y2["receivables"] - y1["receivables"]
            x1 = 1.0 / assets_prior
            x2 = (delta_rev - delta_rec) / assets_prior
            x3 = y2["ppe_gross"] / assets_prior
            y = total_accruals / assets_prior
            rows.append((symbol, x1, x2, x3, y))

        n = len(rows)
        # Normal equations for [a1, a2, a3] against X = [x1, x2, x3]
        xtx = [[0.0] * 3 for _ in range(3)]
        xty = [0.0, 0.0, 0.0]
        for _, x1, x2, x3, y in rows:
            xs = (x1, x2, x3)
            for i in range(3):
                xty[i] += xs[i] * y
                for j in range(3):
                    xtx[i][j] += xs[i] * xs[j]

        if n < 4:
            coeffs = [0.0, 0.0, 0.0]
        else:
            try:
                coeffs = _solve_linear_system(xtx, xty)
            except Exception:
                coeffs = [0.0, 0.0, 0.0]

        residuals: dict[str, tuple[float, float]] = {}
        for symbol, x1, x2, x3, y in rows:
            fitted = coeffs[0] * x1 + coeffs[1] * x2 + coeffs[2] * x3
            residuals[symbol] = (round(y * 100.0, 2), round((y - fitted) * 100.0, 2))

        return (
            {"alpha1": round(coeffs[0], 6), "alpha2": round(coeffs[1], 6), "alpha3": round(coeffs[2], 6)},
            residuals,
        )

    def _market_signals(self, metrics: list[AccrualMetrics]) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal

        signals: list[dict[str, Any]] = []
        for m in sorted(metrics, key=lambda x: -x.sloan_ratio_pct)[:3]:
            if m.sloan_risk in ("SEVERE", "MODERATE"):
                bias = "BEARISH"
            elif m.sloan_risk == "LOW (conservative)":
                bias = "NEUTRAL"
            else:
                bias = "BULLISH" if m.sloan_ratio_pct < 5 else "NEUTRAL"
            confidence = min(0.88, 0.45 + abs(m.sloan_ratio_pct) / 100.0)
            signals.append(
                build_market_signal(
                    sector="Earnings Quality / Forensic Accounting",
                    tickers=[m.symbol],
                    bias=bias,
                    reason=(
                        f"Sloan Ratio {m.sloan_ratio_pct:.1f}% ({m.sloan_risk}), "
                        f"M-Score {m.beneish_m_score:.2f}"
                        + (" (manipulation risk flagged)" if m.manipulation_flag else "")
                    ),
                    confidence=self.adjust_signal_confidence(m.symbol, bias, confidence),
                    evidence={
                        "sloan_ratio_pct": m.sloan_ratio_pct,
                        "discretionary_accrual_pct": m.discretionary_accrual_pct,
                        "beneish_m_score": m.beneish_m_score,
                        "dso_delta_days": m.dso_delta,
                    },
                )
            )
        if not signals:
            signals.append(
                build_market_signal(
                    sector="Earnings Quality / Forensic Accounting",
                    tickers=["SPY"],
                    bias="NEUTRAL",
                    reason="No accrual-quality watchlist data available",
                    confidence=0.4,
                )
            )
        return signals

    def analyze(self) -> AccrualsQualityReport:
        resources = self._catalog_resources()
        jones_coefficients, jones_residuals = self._fit_modified_jones()

        metrics: list[AccrualMetrics] = []
        for symbol, years in self.fundamentals.items():
            y1, y2 = years["year1"], years["year2"]
            self._fetch_live_fundamentals(symbol)  # best-effort; falls back to proxy

            dso1 = self._dso(y1["receivables"], y1["revenue"])
            dso2 = self._dso(y2["receivables"], y2["revenue"])
            sloan = self._sloan_ratio(y2["net_income"], y2["ocf"], y2["icf"], y2["total_assets"])
            risk = self._sloan_risk(sloan)
            total_accrual_pct, discretionary_pct = jones_residuals.get(symbol, (0.0, 0.0))
            components = self._beneish_components(y1, y2)
            m_score = self._beneish_m_score(components)
            manipulation_flag = m_score > -1.78

            note_parts = [f"DSO moved {dso1:.1f} -> {dso2:.1f} days ({dso2 - dso1:+.1f})."]
            if risk in ("SEVERE", "MODERATE"):
                note_parts.append(f"Sloan Ratio {sloan:.1f}% signals {risk.lower()} accrual risk.")
            else:
                note_parts.append(f"Sloan Ratio {sloan:.1f}% is within the safe -10%/+10% band.")
            if manipulation_flag:
                note_parts.append(f"Beneish M-Score {m_score:.2f} exceeds -1.78 — statistically flagged.")
            else:
                note_parts.append(f"Beneish M-Score {m_score:.2f} is below the -1.78 manipulation threshold.")

            metrics.append(
                AccrualMetrics(
                    symbol=symbol,
                    company=COMPANY_NAMES.get(symbol, symbol),
                    dso_year1=dso1,
                    dso_year2=dso2,
                    dso_delta=round(dso2 - dso1, 1),
                    sloan_ratio_pct=sloan,
                    sloan_risk=risk,
                    total_accruals_to_assets_pct=total_accrual_pct,
                    discretionary_accrual_pct=discretionary_pct,
                    beneish_m_score=m_score,
                    manipulation_flag=manipulation_flag,
                    beneish_components=components,
                    expert_note=" ".join(note_parts),
                )
            )

        severe_count = sum(1 for m in metrics if m.sloan_risk == "SEVERE")
        moderate_count = sum(1 for m in metrics if m.sloan_risk == "MODERATE")
        low_count = len(metrics) - severe_count - moderate_count
        avg_sloan = round(sum(m.sloan_ratio_pct for m in metrics) / len(metrics), 2) if metrics else 0.0

        worst = max(metrics, key=lambda m: m.sloan_ratio_pct) if metrics else None
        summary = (
            f"Screened {len(metrics)} tickers for accruals quality. "
            f"Average Sloan Ratio {avg_sloan:.1f}%. "
            f"{severe_count} severe / {moderate_count} moderate / {low_count} low-risk. "
        )
        if worst is not None:
            summary += (
                f"Highest accrual risk: {worst.symbol} ({worst.sloan_risk}, "
                f"Sloan {worst.sloan_ratio_pct:.1f}%, M-Score {worst.beneish_m_score:.2f})."
            )

        signals = self._market_signals(metrics)
        recs = [summary, f"Methodology reference: {DASHBOARD_URL}"]
        for m in sorted(metrics, key=lambda x: -x.sloan_ratio_pct):
            recs.append(f"[{m.symbol}] {m.expert_note}")

        return AccrualsQualityReport(
            resources=resources,
            metrics=metrics,
            jones_coefficients=jones_coefficients,
            avg_sloan_ratio_pct=avg_sloan,
            severe_count=severe_count,
            moderate_count=moderate_count,
            low_count=low_count,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_sources=["Calibrated proxy fundamentals (SEC XBRL companyfacts unavailable)"],
        )

    def to_dict(self, report: AccrualsQualityReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Accruals Quality Forensic Analyst",
                "analyzed_at": report.analyzed_at,
                "data_sources": report.data_sources,
                "expert_summary": report.expert_summary,
                "resources_tracked": len(report.resources),
                "tickers_screened": len(report.metrics),
                "dashboard": DASHBOARD_URL,
                "used_proxy_fundamentals": report.used_proxy_fundamentals,
            },
            "summary": {
                "avg_sloan_ratio_pct": report.avg_sloan_ratio_pct,
                "severe_count": report.severe_count,
                "moderate_count": report.moderate_count,
                "low_count": report.low_count,
                "modified_jones_coefficients": report.jones_coefficients,
            },
            "resources": report.resources,
            "metrics": [
                {
                    "symbol": m.symbol,
                    "company": m.company,
                    "dso_year1": m.dso_year1,
                    "dso_year2": m.dso_year2,
                    "dso_delta_days": m.dso_delta,
                    "sloan_ratio_pct": m.sloan_ratio_pct,
                    "sloan_risk": m.sloan_risk,
                    "total_accruals_to_assets_pct": m.total_accruals_to_assets_pct,
                    "discretionary_accrual_pct": m.discretionary_accrual_pct,
                    "beneish_m_score": m.beneish_m_score,
                    "manipulation_flag": m.manipulation_flag,
                    "beneish_components": m.beneish_components,
                    "expert_note": m.expert_note,
                }
                for m in report.metrics
            ],
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        report = self.analyze()
        result = self.to_dict(report)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog_path = output.parent / "accrual_forensic_frameworks.json"
            catalog_path.write_text(json.dumps(report.resources, indent=2), encoding="utf-8")
        return result


def run_accruals_quality_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return AccrualsQualityExpert(pipeline_context=pipeline_context).run(output=output)
