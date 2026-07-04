"""
Multiverse Scenario Expert Agent
================================
Operationalizes the mathematical formalisms used to describe "alternate
realities" in physics — Many-Worlds decoherence, the Wheeler-DeWitt timeless
wavefunction, the String Theory Landscape, ergodicity/Bekenstein-style
recurrence bounds, and AdS/CFT boundary-bulk duality — as concrete, testable
financial scenario analytics. Each formalism below is a metaphor: the agent
does not claim markets literally obey quantum field theory, it borrows the
mathematical *structure* of each framework to build a decision-relevant
alternate-scenario report.

Data: Yahoo Finance chart API (6-month daily history).
"""

from __future__ import annotations

import json
import math
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any

import requests

CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Finance-Multiverse-Scenarios/1.0 (shaggychunxx@gmail.com)"}

BENCHMARK = "SPY"
WATCHLIST = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "IWM": "Russell 2000",
    "^VIX": "VIX",
    "XLK": "Technology",
    "XLE": "Energy",
    "XLU": "Utilities",
    "XLF": "Financials",
    "GLD": "Gold",
    "TLT": "Treasuries",
}

REGIME_STATES = ("bull", "bear", "neutral")
BULL_THRESHOLD = 0.0025
BEAR_THRESHOLD = -0.0025

BRANCHING_HORIZON_CAP = 12
COHERENCE_COLLAPSE_THRESHOLD = 0.05

SCENARIO_MODELS: list[dict[str, Any]] = [
    {
        "id": "many_worlds_branching",
        "name": "Many-Worlds Branching Tree",
        "description": (
            "Unitary branch-splitting analogue: each trading day splits the market state into "
            "bull/bear/neutral child branches; interference between branches decays exponentially "
            "(decoherence) until they behave as statistically independent parallel scenarios."
        ),
        "formula": "coherence(g) = exp(-Γg), branches(g) = 3^g",
    },
    {
        "id": "wheeler_dewitt_distribution",
        "name": "Wheeler-DeWitt Timeless Distribution",
        "description": (
            "Timeless, static joint distribution over terminal market configurations — the "
            "'frozen' outcome landscape reported instead of a single time-evolved forecast path."
        ),
        "formula": "Ĥ_WDW Ψ = 0  →  stationary P(state) with no explicit time-evolution operator",
    },
    {
        "id": "string_landscape",
        "name": "String Theory Landscape of Vacua",
        "description": (
            "Grid of volatility×trend regime combinations ('alternate vacua'), each implying "
            "different effective constants (mean return, volatility) for the same tickers."
        ),
        "formula": "Landscape = {(vol_regime, trend_regime): (μ, σ, frequency)}",
    },
    {
        "id": "ergodicity_economics",
        "name": "Ergodicity Economics (Time vs Ensemble Average)",
        "description": (
            "Contrasts the time-average (compounding) growth rate against the ensemble-average "
            "return; large divergence flags compounding/variance-drag risk invisible to "
            "ensemble-average statistics."
        ),
        "formula": "g_time = E[ln(1+r)]  vs  g_ensemble = E[r];  gap ≈ σ²/2",
    },
    {
        "id": "bekenstein_recurrence",
        "name": "Bekenstein-Bound Regime Recurrence",
        "description": (
            "Entropy-based bound on the number of distinguishable finite-state regime patterns, "
            "used to estimate how many observation windows are needed before a similar regime "
            "pattern statistically recurs."
        ),
        "formula": "N_configs ≈ k^w (k states, window w); E[windows to repeat] ≈ sqrt(π/2 · N_configs)",
    },
    {
        "id": "ads_cft_holography",
        "name": "AdS/CFT Boundary–Bulk Duality (metaphorical)",
        "description": (
            "Treats a low-dimensional boundary indicator (VIX) as a 'boundary theory' whose "
            "correlation with cross-sectional sector dispersion (the 'bulk') is reported as a "
            "holographic-duality-strength proxy. Purely a structural analogy, not physics."
        ),
        "formula": "duality_strength ≈ corr(ΔVIX, dispersion(sector returns))",
    },
]


@dataclass
class BranchingTree:
    state_probabilities: dict[str, float]
    decoherence_rate: float
    lag1_autocorrelation: float
    decoherence_horizon_days: int
    total_branches_at_horizon: int
    coherence_by_generation: dict[int, float]
    interpretation: str


@dataclass
class ErgodicDivergence:
    symbol: str
    time_average_growth_annual: float
    ensemble_average_return_annual: float
    divergence_annual: float
    variance_drag_ratio: float
    label: str


@dataclass
class LandscapeVacuum:
    volatility_regime: str
    trend_regime: str
    frequency: float
    mean_forward_return: float
    sample_size: int


@dataclass
class RecurrenceEstimate:
    symbol: str
    window_length: int
    shannon_entropy_bits: float
    distinct_configurations: float
    expected_windows_to_repeat: float
    observed_windows: int
    coverage_ratio: float
    interpretation: str


@dataclass
class BoundaryBulkSignal:
    boundary_indicator: str
    bulk_measure: str
    duality_strength: float
    sample_size: int
    interpretation: str


@dataclass
class ScenarioAssessment:
    branching_signal: str
    ergodicity_signal: str
    landscape_signal: str
    recurrence_signal: str
    holography_signal: str
    multiverse_edge: str


@dataclass
class MultiverseScenarioReport:
    branching_tree: BranchingTree
    ergodic_divergences: list[ErgodicDivergence]
    landscape: list[LandscapeVacuum]
    recurrence: list[RecurrenceEstimate]
    boundary_bulk: BoundaryBulkSignal | None
    assessment: ScenarioAssessment
    divergence_score: float
    coherence_score: float
    regime_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MultiverseScenariosExpert:
    """Expert mapping alternate-reality physics formalisms to financial scenario analytics."""

    def __init__(self, delay_seconds: float = 0.3) -> None:
        self.delay_seconds = delay_seconds

    def _fetch_closes(self, symbol: str) -> list[float]:
        try:
            resp = requests.get(
                CHART_API.format(symbol=symbol),
                params={"interval": "1d", "range": "6mo"},
                headers=HEADERS,
                timeout=25,
            )
            if resp.status_code == 429:
                time.sleep(3)
                resp = requests.get(
                    CHART_API.format(symbol=symbol),
                    params={"interval": "1d", "range": "6mo"},
                    headers=HEADERS,
                    timeout=25,
                )
            resp.raise_for_status()
            closes = resp.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            return [float(c) for c in closes if c is not None]
        except Exception:
            return []

    @staticmethod
    def _daily_returns(closes: list[float]) -> list[float]:
        return [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]

    @staticmethod
    def _classify_state(ret: float) -> str:
        if ret > BULL_THRESHOLD:
            return "bull"
        if ret < BEAR_THRESHOLD:
            return "bear"
        return "neutral"

    @staticmethod
    def _lag1_autocorrelation(returns: list[float]) -> float:
        if len(returns) < 3:
            return 0.0
        x, y = returns[:-1], returns[1:]
        mx, my = statistics.fmean(x), statistics.fmean(y)
        num = sum((a - mx) * (b - my) for a, b in zip(x, y))
        denom = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
        return num / denom if denom else 0.0

    def _branching_tree(self, returns: list[float]) -> BranchingTree:
        states = [self._classify_state(r) for r in returns]
        n = len(states) or 1
        state_probs = {
            s: round(states.count(s) / n, 4) for s in REGIME_STATES
        }

        autocorr = self._lag1_autocorrelation(returns)
        overlap = min(0.999999, max(1e-6, abs(autocorr)))
        gamma = round(-math.log(overlap), 6)

        coherence_by_gen: dict[int, float] = {}
        horizon = BRANCHING_HORIZON_CAP
        for g in range(1, BRANCHING_HORIZON_CAP + 1):
            coherence = math.exp(-gamma * g)
            coherence_by_gen[g] = round(coherence, 6)
            if coherence < COHERENCE_COLLAPSE_THRESHOLD and horizon == BRANCHING_HORIZON_CAP:
                horizon = g

        total_branches = 3 ** horizon

        interpretation = (
            f"Branch interference (autocorrelation-derived Γ={gamma:.3f}) decoheres below "
            f"{COHERENCE_COLLAPSE_THRESHOLD:.0%} by day {horizon}, after which {total_branches:,} "
            "branch scenarios behave as statistically independent parallel realities."
        )

        return BranchingTree(
            state_probabilities=state_probs,
            decoherence_rate=gamma,
            lag1_autocorrelation=round(autocorr, 4),
            decoherence_horizon_days=horizon,
            total_branches_at_horizon=total_branches,
            coherence_by_generation=coherence_by_gen,
            interpretation=interpretation,
        )

    @staticmethod
    def _ergodic_divergence(symbol: str, returns: list[float]) -> ErgodicDivergence | None:
        if len(returns) < 20:
            return None
        log_returns = [math.log(1 + r) for r in returns if r > -1]
        if not log_returns:
            return None
        time_avg_daily = statistics.fmean(log_returns)
        ensemble_avg_daily = statistics.fmean(returns)
        time_avg_annual = time_avg_daily * 252
        ensemble_avg_annual = ensemble_avg_daily * 252
        divergence_annual = ensemble_avg_annual - time_avg_annual
        variance = statistics.pvariance(returns) if len(returns) > 1 else 0.0
        variance_drag_ratio = (
            (variance * 252 / 2) / abs(ensemble_avg_annual) if ensemble_avg_annual else 0.0
        )

        if divergence_annual > 0.08:
            label = "High compounding risk — ensemble average materially overstates realized growth"
        elif divergence_annual > 0.03:
            label = "Moderate compounding drag from volatility"
        else:
            label = "Low ergodicity gap — ensemble and time averages broadly agree"

        return ErgodicDivergence(
            symbol=symbol,
            time_average_growth_annual=round(time_avg_annual, 4),
            ensemble_average_return_annual=round(ensemble_avg_annual, 4),
            divergence_annual=round(divergence_annual, 4),
            variance_drag_ratio=round(variance_drag_ratio, 4),
            label=label,
        )

    @staticmethod
    def _volatility_regime(window_returns: list[float]) -> str:
        vol = statistics.pstdev(window_returns) if len(window_returns) > 1 else 0.0
        annualized = vol * math.sqrt(252)
        if annualized < 0.12:
            return "low_vol"
        if annualized < 0.25:
            return "med_vol"
        return "high_vol"

    def _landscape_grid(self, returns: list[float]) -> list[LandscapeVacuum]:
        window = 20
        buckets: dict[tuple[str, str], list[float]] = {
            combo: [] for combo in product(("low_vol", "med_vol", "high_vol"), REGIME_STATES)
        }
        for i in range(window, len(returns) - 1):
            vol_regime = self._volatility_regime(returns[i - window:i])
            trend_regime = self._classify_state(returns[i])
            forward_return = returns[i + 1]
            buckets[(vol_regime, trend_regime)].append(forward_return)

        total = sum(len(v) for v in buckets.values()) or 1
        vacua: list[LandscapeVacuum] = []
        for (vol_regime, trend_regime), forward_returns in buckets.items():
            n = len(forward_returns)
            vacua.append(
                LandscapeVacuum(
                    volatility_regime=vol_regime,
                    trend_regime=trend_regime,
                    frequency=round(n / total, 4),
                    mean_forward_return=round(statistics.fmean(forward_returns), 5) if n else 0.0,
                    sample_size=n,
                )
            )
        vacua.sort(key=lambda v: v.frequency, reverse=True)
        return vacua

    @staticmethod
    def _shannon_entropy(states: list[str]) -> float:
        n = len(states) or 1
        counts = {s: states.count(s) for s in set(states)}
        entropy = 0.0
        for c in counts.values():
            p = c / n
            if p > 0:
                entropy -= p * math.log2(p)
        return entropy

    def _recurrence_estimate(self, symbol: str, returns: list[float], window: int = 8) -> RecurrenceEstimate | None:
        states = [self._classify_state(r) for r in returns]
        if len(states) < window + 5:
            return None
        entropy_bits = self._shannon_entropy(states)
        distinct_configs = 2 ** (entropy_bits * window)
        observed_windows = len(states) - window + 1
        expected_repeat = math.sqrt(math.pi / 2 * distinct_configs) if distinct_configs > 0 else float("inf")
        coverage = observed_windows / expected_repeat if expected_repeat else 0.0

        if coverage >= 1.0:
            interpretation = (
                f"{symbol}: observed sample already spans the expected recurrence horizon — "
                "similar regime patterns are statistically likely to have repeated."
            )
        elif coverage >= 0.3:
            interpretation = (
                f"{symbol}: sample covers a meaningful fraction of the recurrence horizon; "
                "regime repeats plausible but not yet statistically expected."
            )
        else:
            interpretation = (
                f"{symbol}: finite-state entropy implies a recurrence horizon far beyond the "
                "observed sample — regime pattern is effectively unique in this window."
            )

        return RecurrenceEstimate(
            symbol=symbol,
            window_length=window,
            shannon_entropy_bits=round(entropy_bits, 4),
            distinct_configurations=round(distinct_configs, 2),
            expected_windows_to_repeat=round(expected_repeat, 2),
            observed_windows=observed_windows,
            coverage_ratio=round(coverage, 6),
            interpretation=interpretation,
        )

    @staticmethod
    def _pearson_corr(x: list[float], y: list[float]) -> float:
        n = min(len(x), len(y))
        if n < 3:
            return 0.0
        x, y = x[-n:], y[-n:]
        mx, my = statistics.fmean(x), statistics.fmean(y)
        num = sum((a - mx) * (b - my) for a, b in zip(x, y))
        denom = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
        return num / denom if denom else 0.0

    def _boundary_bulk_signal(self, return_map: dict[str, list[float]]) -> BoundaryBulkSignal | None:
        vix_returns = return_map.get("^VIX")
        sector_syms = [s for s in ("XLK", "XLE", "XLU", "XLF") if s in return_map]
        if not vix_returns or len(sector_syms) < 2:
            return None

        n = min(len(vix_returns), *(len(return_map[s]) for s in sector_syms))
        if n < 10:
            return None

        dispersion: list[float] = []
        for i in range(-n, 0):
            day_returns = [return_map[s][i] for s in sector_syms]
            dispersion.append(statistics.pstdev(day_returns) if len(day_returns) > 1 else 0.0)

        strength = self._pearson_corr(vix_returns[-n:], dispersion)
        interpretation = (
            "Boundary indicator (VIX) and bulk sector dispersion move together closely — "
            "consistent with the holographic analogy that boundary correlators fully "
            "determine bulk geometry."
            if abs(strength) >= 0.4
            else "Boundary–bulk coupling is weak — the metaphorical duality holds only loosely here."
        )

        return BoundaryBulkSignal(
            boundary_indicator="^VIX daily return",
            bulk_measure="cross-sector dispersion (XLK/XLE/XLU/XLF)",
            duality_strength=round(strength, 4),
            sample_size=n,
            interpretation=interpretation,
        )

    @staticmethod
    def _assessment(
        branching: BranchingTree,
        ergodic: list[ErgodicDivergence],
        landscape: list[LandscapeVacuum],
        recurrence: list[RecurrenceEstimate],
        boundary_bulk: BoundaryBulkSignal | None,
    ) -> ScenarioAssessment:
        branching_signal = branching.interpretation

        if ergodic:
            worst = max(ergodic, key=lambda e: e.divergence_annual)
            ergodicity_signal = (
                f"{worst.symbol}: time-average growth {worst.time_average_growth_annual:+.2%}/yr vs "
                f"ensemble-average {worst.ensemble_average_return_annual:+.2%}/yr — {worst.label}"
            )
        else:
            ergodicity_signal = "Insufficient data for ergodic divergence analysis"

        if landscape:
            top = landscape[0]
            landscape_signal = (
                f"Dominant vacuum: {top.volatility_regime}/{top.trend_regime} "
                f"({top.frequency:.0%} of history), mean forward return {top.mean_forward_return:+.3%}"
            )
        else:
            landscape_signal = "Insufficient data for landscape grid"

        if recurrence:
            recurrence_signal = recurrence[0].interpretation
        else:
            recurrence_signal = "Insufficient data for recurrence estimate"

        holography_signal = (
            boundary_bulk.interpretation if boundary_bulk else "VIX data unavailable for boundary-bulk analogy"
        )

        edge_parts = []
        if ergodic and max(e.divergence_annual for e in ergodic) > 0.05:
            edge_parts.append("meaningful ergodicity gap (compounding risk)")
        if branching.decoherence_horizon_days <= 4:
            edge_parts.append("fast-decohering branches (short-lived predictability)")
        if not edge_parts:
            edge_parts.append("no strong multiverse-scenario edge detected")
        multiverse_edge = "; ".join(edge_parts)

        return ScenarioAssessment(
            branching_signal=branching_signal,
            ergodicity_signal=ergodicity_signal,
            landscape_signal=landscape_signal,
            recurrence_signal=recurrence_signal,
            holography_signal=holography_signal,
            multiverse_edge=multiverse_edge,
        )

    @staticmethod
    def _market_signals(
        branching: BranchingTree,
        ergodic: list[ErgodicDivergence],
        landscape: list[LandscapeVacuum],
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        bull_p = branching.state_probabilities.get("bull", 0)
        bear_p = branching.state_probabilities.get("bear", 0)
        if bull_p >= 0.45:
            signals.append({
                "sector": "Many-Worlds Branch Weighting",
                "tickers": ["SPY", "QQQ"],
                "bias": "BULLISH",
                "reason": f"Bull-branch weight {bull_p:.0%} dominates decoherent state space",
            })
        elif bear_p >= 0.45:
            signals.append({
                "sector": "Many-Worlds Branch Weighting",
                "tickers": ["TLT", "GLD"],
                "bias": "BEARISH",
                "reason": f"Bear-branch weight {bear_p:.0%} dominates decoherent state space",
            })

        for e in ergodic:
            if e.divergence_annual > 0.06:
                signals.append({
                    "sector": "Ergodicity Gap",
                    "tickers": [e.symbol],
                    "bias": "CAUTION",
                    "reason": (
                        f"{e.symbol} ensemble avg {e.ensemble_average_return_annual:+.1%}/yr vs "
                        f"time avg {e.time_average_growth_annual:+.1%}/yr — {e.label}"
                    ),
                })

        if landscape:
            top = landscape[0]
            bias = "BULLISH" if top.mean_forward_return > 0 else "BEARISH" if top.mean_forward_return < 0 else "NEUTRAL"
            signals.append({
                "sector": "String-Landscape Vacuum",
                "tickers": ["SPY"],
                "bias": bias,
                "reason": (
                    f"Dominant vacuum {top.volatility_regime}/{top.trend_regime} "
                    f"({top.frequency:.0%} freq) implies forward return {top.mean_forward_return:+.3%}"
                ),
            })

        if not signals:
            signals.append({
                "sector": "Multiverse Neutral",
                "tickers": ["SPY"],
                "bias": "NEUTRAL",
                "reason": "No dominant branch, vacuum, or ergodicity edge detected",
            })
        return signals

    @staticmethod
    def _recommendations(
        assessment: ScenarioAssessment,
        branching: BranchingTree,
        ergodic: list[ErgodicDivergence],
        landscape: list[LandscapeVacuum],
        recurrence: list[RecurrenceEstimate],
    ) -> list[str]:
        recs = [
            assessment.branching_signal,
            assessment.ergodicity_signal,
            assessment.landscape_signal,
            assessment.recurrence_signal,
            assessment.holography_signal,
            f"Multiverse edge: {assessment.multiverse_edge}",
        ]
        for e in ergodic[:4]:
            recs.append(
                f"{e.symbol}: time-avg {e.time_average_growth_annual:+.2%}/yr, "
                f"ensemble-avg {e.ensemble_average_return_annual:+.2%}/yr, "
                f"variance-drag ratio {e.variance_drag_ratio:.2f} — {e.label}"
            )
        for v in landscape[:3]:
            recs.append(
                f"Vacuum {v.volatility_regime}/{v.trend_regime}: freq {v.frequency:.0%}, "
                f"n={v.sample_size}, mean forward return {v.mean_forward_return:+.3%}"
            )
        for r in recurrence[:3]:
            recs.append(
                f"{r.symbol} recurrence: entropy {r.shannon_entropy_bits:.2f} bits/day, "
                f"~{r.expected_windows_to_repeat:.0f} windows to expected repeat "
                f"(observed {r.observed_windows}, coverage {r.coverage_ratio:.1%})"
            )
        return recs

    def _expert_summary(
        self,
        assessment: ScenarioAssessment,
        regime_label: str,
        divergence_score: float,
        coherence_score: float,
    ) -> str:
        return (
            f"Multiverse scenario scan: {regime_label} "
            f"(divergence {divergence_score:.2f}, coherence {coherence_score:.2f}). "
            f"{assessment.branching_signal} "
            f"{assessment.ergodicity_signal}. "
            f"{assessment.landscape_signal}. "
            f"{assessment.recurrence_signal}. "
            f"Edge: {assessment.multiverse_edge}."
        )

    def analyze(self) -> MultiverseScenarioReport:
        price_data: dict[str, list[float]] = {}
        return_map: dict[str, list[float]] = {}

        for symbol in WATCHLIST:
            closes = self._fetch_closes(symbol)
            if closes:
                price_data[symbol] = closes
                return_map[symbol] = self._daily_returns(closes)
            time.sleep(self.delay_seconds)

        spy_returns = return_map.get(BENCHMARK, [])
        if not spy_returns:
            raise RuntimeError("Unable to fetch SPY data for multiverse scenario analysis")

        branching = self._branching_tree(spy_returns)

        ergodic_syms = [s for s in ("SPY", "QQQ", "IWM", "XLK", "GLD", "TLT") if s in return_map]
        ergodic = [
            d for d in (self._ergodic_divergence(sym, return_map[sym]) for sym in ergodic_syms)
            if d is not None
        ]

        landscape = self._landscape_grid(spy_returns)

        recurrence_syms = [s for s in ("SPY", "QQQ") if s in return_map]
        recurrence = [
            r for r in (self._recurrence_estimate(sym, return_map[sym]) for sym in recurrence_syms)
            if r is not None
        ]

        boundary_bulk = self._boundary_bulk_signal(return_map)

        assessment = self._assessment(branching, ergodic, landscape, recurrence, boundary_bulk)

        divergence_score = round(
            max((e.divergence_annual for e in ergodic), default=0.0), 4
        )
        coherence_score = round(
            branching.coherence_by_generation.get(1, 0.0), 4
        )

        if divergence_score > 0.06:
            regime_label = "High Ergodicity Divergence"
        elif branching.decoherence_horizon_days <= 3:
            regime_label = "Rapidly Decohering Branches"
        else:
            regime_label = "Stable Scenario Landscape"

        summary = self._expert_summary(assessment, regime_label, divergence_score, coherence_score)
        signals = self._market_signals(branching, ergodic, landscape)
        recs = self._recommendations(assessment, branching, ergodic, landscape, recurrence)

        return MultiverseScenarioReport(
            branching_tree=branching,
            ergodic_divergences=ergodic,
            landscape=landscape,
            recurrence=recurrence,
            boundary_bulk=boundary_bulk,
            assessment=assessment,
            divergence_score=divergence_score,
            coherence_score=coherence_score,
            regime_label=regime_label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source="Yahoo Finance API",
        )

    def to_dict(self, report: MultiverseScenarioReport) -> dict[str, Any]:
        a = report.assessment
        b = report.branching_tree
        return {
            "meta": {
                "agent": "Multiverse Scenario Expert",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
                "models_applied": [m["id"] for m in SCENARIO_MODELS],
            },
            "scenario_models": SCENARIO_MODELS,
            "many_worlds_branching": {
                "state_probabilities": b.state_probabilities,
                "decoherence_rate": b.decoherence_rate,
                "lag1_autocorrelation": b.lag1_autocorrelation,
                "decoherence_horizon_days": b.decoherence_horizon_days,
                "total_branches_at_horizon": b.total_branches_at_horizon,
                "coherence_by_generation": b.coherence_by_generation,
                "interpretation": b.interpretation,
            },
            "ergodic_divergences": [
                {
                    "symbol": e.symbol,
                    "time_average_growth_annual": e.time_average_growth_annual,
                    "ensemble_average_return_annual": e.ensemble_average_return_annual,
                    "divergence_annual": e.divergence_annual,
                    "variance_drag_ratio": e.variance_drag_ratio,
                    "label": e.label,
                }
                for e in report.ergodic_divergences
            ],
            "string_landscape": [
                {
                    "volatility_regime": v.volatility_regime,
                    "trend_regime": v.trend_regime,
                    "frequency": v.frequency,
                    "mean_forward_return": v.mean_forward_return,
                    "sample_size": v.sample_size,
                }
                for v in report.landscape
            ],
            "bekenstein_recurrence": [
                {
                    "symbol": r.symbol,
                    "window_length": r.window_length,
                    "shannon_entropy_bits": r.shannon_entropy_bits,
                    "distinct_configurations": r.distinct_configurations,
                    "expected_windows_to_repeat": r.expected_windows_to_repeat,
                    "observed_windows": r.observed_windows,
                    "coverage_ratio": r.coverage_ratio,
                    "interpretation": r.interpretation,
                }
                for r in report.recurrence
            ],
            "ads_cft_boundary_bulk": (
                {
                    "boundary_indicator": report.boundary_bulk.boundary_indicator,
                    "bulk_measure": report.boundary_bulk.bulk_measure,
                    "duality_strength": report.boundary_bulk.duality_strength,
                    "sample_size": report.boundary_bulk.sample_size,
                    "interpretation": report.boundary_bulk.interpretation,
                }
                if report.boundary_bulk
                else None
            ),
            "scenario_assessment": {
                "branching_signal": a.branching_signal,
                "ergodicity_signal": a.ergodicity_signal,
                "landscape_signal": a.landscape_signal,
                "recurrence_signal": a.recurrence_signal,
                "holography_signal": a.holography_signal,
                "multiverse_edge": a.multiverse_edge,
            },
            "metrics": {
                "divergence_score": report.divergence_score,
                "coherence_score": report.coherence_score,
                "regime_label": report.regime_label,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            models_path = output.parent / "scenario_models.json"
            models_path.write_text(
                json.dumps(SCENARIO_MODELS, indent=2),
                encoding="utf-8",
            )
        return result


def run_multiverse_scenarios_analysis(output: Path | None = None) -> dict[str, Any]:
    return MultiverseScenariosExpert().run(output=output)
