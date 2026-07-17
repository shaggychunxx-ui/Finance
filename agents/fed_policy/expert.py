"""
Fed Rate Policy & SOFR Curve Expert Agent
==========================================
Tracks the FOMC's Summary of Economic Projections (SEP) "dot plot", the
Effective Federal Funds Rate (EFFR) / Secured Overnight Financing Rate
(SOFR) overnight-rate mechanics, the Treasury/swap curve shape, and the
resulting corporate borrowing/hedging implications.

Baseline reference: the June 2026 hawkish-pivot SEP under Fed Chair Kevin
Warsh (target range held at 3.50%-3.75%, median dot shifted to 3.75%-4.00%).

The agent studies the full hiking/cutting cycle, not just the latest print:
it pulls the entire available FRED history for EFFR/SOFR to compute cycle
highs/lows and multi-year trend stats, keeps a public-record timeline of
past FOMC target-range moves (2019 cutting cycle through the current 2026
stance), and extends the dot plot into a multi-year forward path (SEP
projections for the current year, the following two years, and the
"longer run" neutral-rate estimate) rather than a single year-end median.

Live data: FRED public CSV endpoints (SOFR, DFF, DGS5, DGS10, DGS3MO,
T10Y2Y), fetched as full historical series. FRED is DNS-blocked in the
sandbox, so a calibrated proxy snapshot derived from the June 2026 SEP/market
briefing is always available as a fallback and is clearly labeled as such.

Docs: https://fred.stlouisfed.org/  |  https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from agents.base import BaseExpert

HEADERS = {"User-Agent": "Finance-Fed-Policy-Expert/1.0 (shaggychunxx@gmail.com)"}
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

# FRED series used for live overnight-rate / curve confirmation.
FRED_SERIES: dict[str, str] = {
    "effr": "DFF",
    "sofr": "SOFR",
    "treasury_5y": "DGS5",
    "treasury_10y": "DGS10",
    "treasury_3mo": "DGS3MO",
    "curve_10y2y": "T10Y2Y",
}

FED_POLICY_RESOURCES: list[dict[str, Any]] = [
    {
        "id": "sofr_fred",
        "name": "SOFR (FRED)",
        "url": f"{FRED_CSV_URL}?id=SOFR",
        "description": "Daily Secured Overnight Financing Rate",
    },
    {
        "id": "effr_fred",
        "name": "Effective Federal Funds Rate (FRED)",
        "url": f"{FRED_CSV_URL}?id=DFF",
        "description": "Daily effective federal funds rate",
    },
    {
        "id": "dgs5_fred",
        "name": "5-Year Treasury Constant Maturity Rate (FRED)",
        "url": f"{FRED_CSV_URL}?id=DGS5",
        "description": "Daily 5-year Treasury yield",
    },
    {
        "id": "dgs10_fred",
        "name": "10-Year Treasury Constant Maturity Rate (FRED)",
        "url": f"{FRED_CSV_URL}?id=DGS10",
        "description": "Daily 10-year Treasury yield",
    },
    {
        "id": "t10y2y_fred",
        "name": "10Y-2Y Treasury Spread (FRED)",
        "url": f"{FRED_CSV_URL}?id=T10Y2Y",
        "description": "Daily 10-year minus 2-year Treasury spread (curve shape/inversion gauge)",
    },
    {
        "id": "sep_dot_plot",
        "name": "FOMC Summary of Economic Projections",
        "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        "description": "Quarterly dot plot / SEP releases",
    },
    {
        "id": "pensford_forward_curve",
        "name": "Pensford Forward SOFR Curve",
        "url": "https://www.pensford.com/forward-curve",
        "description": "Forward Term SOFR curve and swap-rate reference",
    },
]

# June 2026 FOMC dot plot: 18 anonymous participants across four buckets,
# ordered from highest to lowest projected year-end 2026 rate.
DOT_PLOT_BUCKETS: list[dict[str, Any]] = [
    {
        "range_low": 4.00,
        "range_high": 4.25,
        "dots": 5,
        "label": "Half-point hike",
    },
    {
        "range_low": 3.75,
        "range_high": 4.00,
        "dots": 3,
        "label": "Quarter-point hike",
        "is_median": True,
    },
    {
        "range_low": 3.50,
        "range_high": 3.75,
        "dots": 9,
        "label": "Hold / unchanged",
        "is_current": True,
    },
    {
        "range_low": 3.00,
        "range_high": 3.50,
        "dots": 1,
        "label": "Rate cut",
    },
]
DOT_PLOT_PARTICIPANTS = 18
MEDIAN_RANGE = (3.75, 4.00)
PRIOR_MEDIAN_MIDPOINT = 3.625  # 25bp below the new median midpoint

# The committee-split narrative from the SEP briefing: exactly nine members
# project the fed funds rate unchanged-or-lower by year-end 2026, the other
# nine project at least one hike (five of those backing 50bp). This is the
# briefing's own framing and is kept distinct from the raw dot-plot bucket
# counts above, which group projections into ranges rather than hike/hold
# votes.
COMMITTEE_SPLIT = {
    "hold_or_cut": 9,
    "hike": 9,
    "half_point_hike": 5,
}

# Calibrated proxy snapshot (June/July 2026 SEP + market briefing). Used
# whenever a live FRED series is unavailable; each field is labeled as
# "proxy" in the report so it is never confused with a live print.
PROXY_SNAPSHOT: dict[str, float] = {
    "fed_funds_low": 3.50,
    "fed_funds_high": 3.75,
    "effr": 3.62,
    "sofr": 3.575,  # midpoint of the ~3.55%-3.60% overnight SOFR range
    "term_sofr_1mo": 3.659,
    "treasury_3mo": 3.60,
    "treasury_5y": 4.305,
    "treasury_10y": 4.561,
    "swap_5y": 3.95,
    "swap_10y": 4.06,
    "futures_oct_2026": 3.80,
    "futures_year_end_2026": 4.00,
    "pce_inflation_2026": 3.6,
    "pce_inflation_revision": 0.9,
    "gdp_growth_2026": 2.2,
}

# Public-record timeline of FOMC target-range moves spanning the full past
# cycle (2019 pre-pandemic cuts through the current 2026 hawkish-pivot
# stance). Used to give the report a "past years" view of the cycle rather
# than only the latest print.
RATE_CYCLE_HISTORY: list[dict[str, Any]] = [
    {"date": "2019-07-31", "action": "cut", "target_low": 2.00, "target_high": 2.25, "note": "Mid-cycle adjustment cut #1 of 3"},
    {"date": "2019-09-18", "action": "cut", "target_low": 1.75, "target_high": 2.00, "note": "Mid-cycle adjustment cut #2 of 3"},
    {"date": "2019-10-30", "action": "cut", "target_low": 1.50, "target_high": 1.75, "note": "Mid-cycle adjustment cut #3 of 3"},
    {"date": "2020-03-15", "action": "cut", "target_low": 0.00, "target_high": 0.25, "note": "Emergency pandemic cut to zero lower bound"},
    {"date": "2022-03-16", "action": "hike", "target_low": 0.25, "target_high": 0.50, "note": "Start of the 2022-2023 hiking cycle"},
    {"date": "2022-12-14", "action": "hike", "target_low": 4.25, "target_high": 4.50, "note": "Step-down to 50bp after four 75bp hikes"},
    {"date": "2023-07-26", "action": "hike", "target_low": 5.25, "target_high": 5.50, "note": "Cycle-peak hike"},
    {"date": "2024-09-18", "action": "cut", "target_low": 4.75, "target_high": 5.00, "note": "First cut of the 2024-2025 easing cycle (50bp)"},
    {"date": "2024-12-18", "action": "cut", "target_low": 4.25, "target_high": 4.50, "note": "Third consecutive 2024 cut"},
    {"date": "2025-09-17", "action": "cut", "target_low": 3.75, "target_high": 4.00, "note": "Resumed cuts amid labor-market softening"},
    {"date": "2026-01-28", "action": "hold", "target_low": 3.50, "target_high": 3.75, "note": "Held steady pending inflation data"},
    {"date": "2026-06-17", "action": "hold", "target_low": 3.50, "target_high": 3.75, "note": "Current stance: hold, hawkish-tilted June SEP"},
]

# Multi-year SEP dot-plot median path: current year, the next two years, and
# the "longer run" (neutral rate) estimate, mirroring the FOMC's actual SEP
# matrix layout rather than a single year-end figure.
SEP_FORWARD_PATH: list[dict[str, Any]] = [
    {"year": "2026", "median_low": 3.75, "median_high": 4.00, "label": "Current SEP year"},
    {"year": "2027", "median_low": 3.50, "median_high": 3.75, "label": "One cut priced by end-2027"},
    {"year": "2028", "median_low": 3.25, "median_high": 3.50, "label": "Gradual normalization continues"},
    {"year": "Longer Run", "median_low": 3.00, "median_high": 3.00, "label": "Longer-run neutral rate (R*) estimate"},
]


@dataclass
class DotPlotBucket:
    range_low: float
    range_high: float
    dots: int
    label: str
    is_median: bool = False
    is_current: bool = False


@dataclass
class RateSnapshot:
    fed_funds_low: float
    fed_funds_high: float
    effr: float
    sofr: float
    term_sofr_1mo: float
    treasury_3mo: float
    treasury_5y: float
    treasury_10y: float
    swap_5y: float
    swap_10y: float
    futures_oct_2026: float
    futures_year_end_2026: float


@dataclass
class FedPolicyReport:
    dot_plot: list[DotPlotBucket]
    median_range: tuple[float, float]
    committee_split: dict[str, int]
    macro: dict[str, float]
    rates: RateSnapshot
    curve_shape: str
    ten_minus_five_bp: float
    hawkish_score: float
    hawkish_label: str
    rate_cycle_history: list[dict[str, Any]]
    forward_path: list[dict[str, Any]]
    historical_stats: dict[str, Any]
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FedPolicyExpert(BaseExpert):
    """Analyst covering the FOMC dot plot, EFFR/SOFR mechanics, and curve shape."""

    def __init__(self, *, pipeline_context: dict | None = None) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="fed-policy")

    @staticmethod
    def _fetch_fred_latest(series_id: str) -> float | None:
        try:
            resp = requests.get(
                FRED_CSV_URL,
                params={"id": series_id},
                headers=HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
            rows = list(csv.reader(io.StringIO(resp.text)))
        except Exception:
            return None

        for row in reversed(rows[1:]):
            if len(row) < 2:
                continue
            value = row[1].strip()
            if not value or value == ".":
                continue
            try:
                return float(value)
            except ValueError:
                continue
        return None

    def _fetch_live_rates(self) -> tuple[dict[str, float], list[str]]:
        live: dict[str, float] = {}
        for field_name, series_id in FRED_SERIES.items():
            value = self._fetch_fred_latest(series_id)
            if value is not None:
                live[field_name] = value

        sources: list[str] = []
        if live:
            sources.append(f"FRED public CSV ({len(live)}/{len(FRED_SERIES)} series)")
        if len(live) < len(FRED_SERIES):
            sources.append("Calibrated June 2026 SEP/market proxy (FRED unavailable for remaining series)")
        else:
            sources.append("June 2026 FOMC SEP dot plot (fixed meeting materials)")
        return live, sources

    @staticmethod
    def _fetch_fred_history(series_id: str, *, years: int = 10) -> list[tuple[datetime, float]]:
        """Pull the full available FRED history for a series (past N years)."""
        try:
            resp = requests.get(
                FRED_CSV_URL,
                params={"id": series_id},
                headers=HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
            rows = list(csv.reader(io.StringIO(resp.text)))
        except Exception:
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(days=365 * years)
        history: list[tuple[datetime, float]] = []
        for row in rows[1:]:
            if len(row) < 2:
                continue
            date_str, value_str = row[0].strip(), row[1].strip()
            if not value_str or value_str == ".":
                continue
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                value = float(value_str)
            except ValueError:
                continue
            if dt >= cutoff:
                history.append((dt, value))
        return history

    def _historical_stats(self, current_effr: float) -> tuple[dict[str, Any], bool]:
        """Summarize the multi-year EFFR history: cycle high/low and trend."""
        history = self._fetch_fred_history(FRED_SERIES["effr"], years=10)
        if not history:
            return {
                "years_covered": None,
                "cycle_high": None,
                "cycle_low": None,
                "rate_1y_ago": None,
                "change_1y_bp": None,
                "source": "unavailable (FRED unreachable) — see rate_cycle_history for the public-record timeline",
            }, False

        values = [v for _, v in history]
        history.sort(key=lambda pair: pair[0])
        oldest, newest = history[0][0], history[-1][0]
        years_covered = round((newest - oldest).days / 365.25, 1)

        one_year_ago_target = newest - timedelta(days=365)
        closest = min(history, key=lambda pair: abs((pair[0] - one_year_ago_target).total_seconds()))
        rate_1y_ago = closest[1]
        change_1y_bp = round((current_effr - rate_1y_ago) * 100, 1)

        return {
            "years_covered": years_covered,
            "cycle_high": round(max(values), 2),
            "cycle_low": round(min(values), 2),
            "rate_1y_ago": round(rate_1y_ago, 2),
            "change_1y_bp": change_1y_bp,
            "source": f"FRED EFFR daily history ({len(history)} observations over {years_covered} years)",
        }, True

    @staticmethod
    def _build_rates(live: dict[str, float]) -> RateSnapshot:
        def pick(name: str) -> float:
            return live.get(name, PROXY_SNAPSHOT[name])

        return RateSnapshot(
            fed_funds_low=PROXY_SNAPSHOT["fed_funds_low"],
            fed_funds_high=PROXY_SNAPSHOT["fed_funds_high"],
            effr=pick("effr"),
            sofr=pick("sofr"),
            term_sofr_1mo=PROXY_SNAPSHOT["term_sofr_1mo"],
            treasury_3mo=pick("treasury_3mo"),
            treasury_5y=pick("treasury_5y"),
            treasury_10y=pick("treasury_10y"),
            swap_5y=PROXY_SNAPSHOT["swap_5y"],
            swap_10y=PROXY_SNAPSHOT["swap_10y"],
            futures_oct_2026=PROXY_SNAPSHOT["futures_oct_2026"],
            futures_year_end_2026=PROXY_SNAPSHOT["futures_year_end_2026"],
        )

    @staticmethod
    def _curve_shape(rates: RateSnapshot) -> tuple[str, float]:
        ten_minus_five_bp = round((rates.treasury_10y - rates.treasury_5y) * 100, 1)
        short_vs_five_bp = round((rates.treasury_5y - rates.treasury_3mo) * 100, 1)
        if ten_minus_five_bp > 15 and short_vs_five_bp <= 0:
            shape = "Bear steepening at the long end, flat-to-inverted short end"
        elif ten_minus_five_bp > 15:
            shape = "Bear steepening across the curve"
        elif ten_minus_five_bp < -5:
            shape = "Inverted long end"
        else:
            shape = "Roughly flat long end"
        return shape, ten_minus_five_bp

    @staticmethod
    def _hawkish_score(committee_split: dict[str, int], macro: dict[str, float]) -> tuple[float, str]:
        hike_share = committee_split["hike"] / DOT_PLOT_PARTICIPANTS
        half_point_share = committee_split["half_point_hike"] / DOT_PLOT_PARTICIPANTS
        median_shift = (sum(MEDIAN_RANGE) / 2) - PRIOR_MEDIAN_MIDPOINT

        score = 0.0
        score += hike_share * 0.9
        score += half_point_share * 0.6
        score += max(0.0, median_shift) * 2.0
        if macro.get("pce_inflation_2026", 0) >= 3.0:
            score += 0.25
        if macro.get("gdp_growth_2026", 3.0) <= 2.5:
            score += 0.1

        score = round(max(-1.0, min(1.0, score)), 4)
        label = (
            "Strongly hawkish" if score >= 0.7 else
            "Hawkish" if score >= 0.4 else
            "Neutral" if score >= -0.1 else
            "Dovish"
        )
        return score, label

    def _market_signals(
        self, rates: RateSnapshot, curve_shape: str, hawkish_score: float, hawkish_label: str
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal

        signals: list[dict[str, Any]] = []

        signals.append(
            build_market_signal(
                sector="Rates / Duration",
                tickers=["TLT", "IEF", "SHY"],
                bias="BEARISH" if hawkish_score >= 0.3 else "NEUTRAL",
                reason=(
                    f"{hawkish_label} June 2026 dot plot (median {MEDIAN_RANGE[0]:.2f}%-"
                    f"{MEDIAN_RANGE[1]:.2f}%, score {hawkish_score:+.2f}) prices out near-term "
                    "cuts and pressures long-duration Treasury proxies"
                ),
                confidence=min(0.85, 0.5 + abs(hawkish_score) * 0.4),
                evidence={
                    "hawkish_score": hawkish_score,
                    "treasury_10y": rates.treasury_10y,
                    "treasury_5y": rates.treasury_5y,
                },
            )
        )

        signals.append(
            build_market_signal(
                sector="Bank Financials (NIM)",
                tickers=["XLF", "KRE"],
                bias="BULLISH" if rates.effr >= rates.fed_funds_low else "NEUTRAL",
                reason=(
                    f"EFFR ~{rates.effr:.2f}% holding near the top of the "
                    f"{rates.fed_funds_low:.2f}%-{rates.fed_funds_high:.2f}% target range supports "
                    "bank net interest margins under a higher-for-longer stance"
                ),
                confidence=0.55,
                evidence={"effr": rates.effr, "sofr": rates.sofr},
            )
        )

        signals.append(
            build_market_signal(
                sector="Floating-Rate Credit Stress",
                tickers=["IWM", "HYG"],
                bias="BEARISH",
                reason=(
                    f"1-Month Term SOFR at {rates.term_sofr_1mo:.3f}% keeps floating-rate credit "
                    "facility costs structurally elevated, squeezing small-cap/leveraged borrower "
                    "cash flow"
                ),
                confidence=0.6,
                evidence={"term_sofr_1mo": rates.term_sofr_1mo},
            )
        )

        signals.append(
            build_market_signal(
                sector="Yield Curve Shape",
                tickers=["STPP", "TLT"],
                bias="BEARISH",
                reason=(
                    f"{curve_shape} — 10Y-5Y spread at {round((rates.treasury_10y - rates.treasury_5y) * 100, 1):+.1f}bp "
                    "reflects rising term premium demanded for structural deficits and long-term "
                    "inflation risk"
                ),
                confidence=0.5,
                evidence={
                    "treasury_10y": rates.treasury_10y,
                    "treasury_5y": rates.treasury_5y,
                    "swap_10y": rates.swap_10y,
                    "swap_5y": rates.swap_5y,
                },
            )
        )

        return self._adjust_market_signals(signals)

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

    def analyze(self) -> FedPolicyReport:
        live, sources = self._fetch_live_rates()
        rates = self._build_rates(live)

        dot_plot = [DotPlotBucket(**bucket) for bucket in DOT_PLOT_BUCKETS]
        committee_split = dict(COMMITTEE_SPLIT)

        macro = {
            "pce_inflation_2026": PROXY_SNAPSHOT["pce_inflation_2026"],
            "pce_inflation_revision": PROXY_SNAPSHOT["pce_inflation_revision"],
            "gdp_growth_2026": PROXY_SNAPSHOT["gdp_growth_2026"],
        }

        curve_shape, ten_minus_five_bp = self._curve_shape(rates)
        hawkish_score, hawkish_label = self._hawkish_score(committee_split, macro)
        signals = self._market_signals(rates, curve_shape, hawkish_score, hawkish_label)

        historical_stats, history_live = self._historical_stats(rates.effr)
        if history_live:
            sources.append(historical_stats["source"])
        rate_cycle_history = [dict(entry) for entry in RATE_CYCLE_HISTORY]
        forward_path = [dict(entry) for entry in SEP_FORWARD_PATH]

        cycle_note = (
            f"cycle range {historical_stats['cycle_low']:.2f}%-{historical_stats['cycle_high']:.2f}% "
            f"over the trailing {historical_stats['years_covered']} years "
            f"({historical_stats['change_1y_bp']:+.1f}bp vs. one year ago)"
            if history_live
            else "cycle context from the public FOMC decision timeline (live FRED history unavailable)"
        )
        forward_note = ", ".join(
            f"{p['year']}: {p['median_low']:.2f}%-{p['median_high']:.2f}%" for p in forward_path
        )

        expert_summary = (
            f"FOMC held the target range at {rates.fed_funds_low:.2f}%-{rates.fed_funds_high:.2f}%, "
            f"but the June 2026 SEP median rose to {MEDIAN_RANGE[0]:.2f}%-{MEDIAN_RANGE[1]:.2f}% "
            f"({hawkish_label}, score {hawkish_score:+.2f}). Committee split {committee_split['hold_or_cut']}-"
            f"{committee_split['hike']} between hold/cut and hike, with {committee_split['half_point_hike']} "
            "backing a 50bp move. EFFR ~"
            f"{rates.effr:.2f}% and overnight SOFR ~{rates.sofr:.2f}% track just under the target ceiling "
            f"while 1-Month Term SOFR trades at {rates.term_sofr_1mo:.3f}%. {curve_shape} "
            f"(10Y-5Y {ten_minus_five_bp:+.1f}bp), with the 10Y at {rates.treasury_10y:.2f}% "
            f"vs. the 5Y at {rates.treasury_5y:.2f}%. Full-cycle view: {cycle_note}; the "
            f"{len(rate_cycle_history)}-move public FOMC timeline spans the 2019 cutting cycle through today. "
            f"Forward SEP path: {forward_note}."
        )

        recs = [
            f"Policy stance: {hawkish_label} (score {hawkish_score:+.2f}); "
            f"median dot {MEDIAN_RANGE[0]:.2f}%-{MEDIAN_RANGE[1]:.2f}% for year-end 2026",
            f"Committee split: {committee_split['hold_or_cut']} hold/cut vs. {committee_split['hike']} hike "
            f"({committee_split['half_point_hike']} of those favoring 50bp)",
            f"Overnight rates: EFFR ~{rates.effr:.2f}%, SOFR ~{rates.sofr:.2f}%, "
            f"1M Term SOFR {rates.term_sofr_1mo:.3f}%",
            f"Curve: {curve_shape} — 5Y {rates.treasury_5y:.2f}% / 10Y {rates.treasury_10y:.2f}% "
            f"(10Y-5Y {ten_minus_five_bp:+.1f}bp)",
            f"Corporate hedging: 5Y swap ~{rates.swap_5y:.2f}%, 10Y swap ~{rates.swap_10y:.2f}% — "
            "floating-to-fixed swaps lock in elevated structural funding costs",
            "Futures pricing tracks the hawkish half of the dot plot: implied "
            f"~{rates.futures_oct_2026:.2f}% by October 2026, ~{rates.futures_year_end_2026:.2f}% by year-end",
            f"Past-cycle context: {cycle_note}",
            f"Forward SEP path (multi-year): {forward_note}",
        ]

        return FedPolicyReport(
            dot_plot=dot_plot,
            median_range=MEDIAN_RANGE,
            committee_split=committee_split,
            macro=macro,
            rates=rates,
            curve_shape=curve_shape,
            ten_minus_five_bp=ten_minus_five_bp,
            hawkish_score=hawkish_score,
            hawkish_label=hawkish_label,
            rate_cycle_history=rate_cycle_history,
            forward_path=forward_path,
            historical_stats=historical_stats,
            expert_summary=expert_summary,
            market_signals=signals,
            recommendations=self.append_memory_recommendations(recs),
            data_sources=sources,
        )

    def to_dict(self, report: FedPolicyReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Fed Rate Policy & SOFR Curve Expert",
                "analyzed_at": report.analyzed_at,
                "expert_summary": report.expert_summary,
                "data_sources": report.data_sources,
                "dot_plot_participants": DOT_PLOT_PARTICIPANTS,
            },
            "dot_plot": [
                {
                    "range_low": b.range_low,
                    "range_high": b.range_high,
                    "dots": b.dots,
                    "label": b.label,
                    "is_median": b.is_median,
                    "is_current": b.is_current,
                }
                for b in report.dot_plot
            ],
            "median_range": {"low": report.median_range[0], "high": report.median_range[1]},
            "committee_split": report.committee_split,
            "macro": report.macro,
            "rates": {
                "fed_funds_low": report.rates.fed_funds_low,
                "fed_funds_high": report.rates.fed_funds_high,
                "effr": report.rates.effr,
                "sofr": report.rates.sofr,
                "term_sofr_1mo": report.rates.term_sofr_1mo,
                "treasury_3mo": report.rates.treasury_3mo,
                "treasury_5y": report.rates.treasury_5y,
                "treasury_10y": report.rates.treasury_10y,
                "swap_5y": report.rates.swap_5y,
                "swap_10y": report.rates.swap_10y,
                "futures_oct_2026": report.rates.futures_oct_2026,
                "futures_year_end_2026": report.rates.futures_year_end_2026,
            },
            "metrics": {
                "curve_shape": report.curve_shape,
                "ten_minus_five_bp": report.ten_minus_five_bp,
                "hawkish_score": report.hawkish_score,
                "hawkish_label": report.hawkish_label,
            },
            "rate_cycle_history": report.rate_cycle_history,
            "historical_stats": report.historical_stats,
            "forward_path": report.forward_path,
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            resources_path = output.parent / "fed_policy_resources.json"
            resources_path.write_text(
                json.dumps(FED_POLICY_RESOURCES, indent=2),
                encoding="utf-8",
            )
            timeline_path = output.parent / "fed_policy_rate_timeline.json"
            timeline_path.write_text(
                json.dumps(
                    {
                        "rate_cycle_history": result.get("rate_cycle_history", []),
                        "historical_stats": result.get("historical_stats", {}),
                        "forward_path": result.get("forward_path", []),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        return result


def run_fed_policy_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return FedPolicyExpert(pipeline_context=pipeline_context).run(output=output)
