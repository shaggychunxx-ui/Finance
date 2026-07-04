"""
Theoretical Probability Expert Agent
====================================
Expert in theoretical probability applied to financial markets:
Markov chains, Bayesian inference, conditional probability, binomial
streak models, GBM barrier probabilities, expected value, and Kelly criterion.

Data: Yahoo Finance chart API (6-month daily history).
"""

from __future__ import annotations

import json
import math
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agents.base import BaseExpert

CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Finance-Theoretical-Probability/1.0 (shaggychunxx@gmail.com)"}

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

MARKOV_STATES = ("bull", "bear", "neutral")
BULL_THRESHOLD = 0.0025
BEAR_THRESHOLD = -0.0025

PROBABILITY_MODELS: list[dict[str, Any]] = [
    {
        "id": "markov_chain",
        "name": "Markov Chain Regime Model",
        "description": "3-state daily transition matrix (bull/bear/neutral) with stationary distribution",
        "formula": "P(X_{t+1}=j | X_t=i) estimated from empirical state transitions",
    },
    {
        "id": "bayesian_update",
        "name": "Bayesian Regime Posterior",
        "description": "Posterior P(regime | evidence) via Bayes theorem with breadth and return likelihoods",
        "formula": "P(H|E) = P(E|H)P(H) / P(E)",
    },
    {
        "id": "conditional_probability",
        "name": "Conditional Market Probabilities",
        "description": "P(asset up | benchmark up/down) from joint daily return events",
        "formula": "P(A|B) = P(A∩B) / P(B)",
    },
    {
        "id": "binomial_streak",
        "name": "Binomial Streak Model",
        "description": "Theoretical consecutive-up probability under i.i.d. daily win-rate assumption",
        "formula": "P(k consecutive ups) ≈ p^k",
    },
    {
        "id": "gbm_barrier",
        "name": "GBM First-Passage Barrier",
        "description": "Probability of touching a drawdown barrier within n days under lognormal diffusion",
        "formula": "P(min S_t ≤ K) ≈ 2Φ((ln(K/S₀) - (μ-σ²/2)T) / (σ√T))",
    },
    {
        "id": "expected_value",
        "name": "Expected Value of Bets",
        "description": "EV = p·gain - (1-p)·loss for momentum and mean-reversion setups",
        "formula": "EV = p·W - (1-p)·L",
    },
    {
        "id": "kelly_criterion",
        "name": "Kelly Criterion",
        "description": "Optimal bet fraction maximizing long-run geometric growth",
        "formula": "f* = (p·b - q) / b  where b = win/loss odds, q = 1-p",
    },
    {
        "id": "law_of_large_numbers",
        "name": "Law of Large Numbers",
        "description": "Sample size for win-rate estimate precision (±ε at 95% confidence)",
        "formula": "n ≥ (z²·p(1-p)) / ε²",
    },
]


@dataclass
class MarkovModel:
    transition_matrix: dict[str, dict[str, float]]
    stationary_distribution: dict[str, float]
    current_state: str
    one_step_forecast: dict[str, float]


@dataclass
class BayesianPosterior:
    prior: dict[str, float]
    likelihood: dict[str, float]
    posterior: dict[str, float]
    evidence: str
    dominant_regime: str


@dataclass
class ConditionalProb:
    event: str
    condition: str
    probability: float
    sample_size: int
    label: str


@dataclass
class StreakAnalysis:
    symbol: str
    empirical_up_rate: float
    longest_up_streak: int
    longest_down_streak: int
    theoretical_streak_prob: float
    streak_vs_theory: str


@dataclass
class BarrierProb:
    symbol: str
    barrier_pct: float
    horizon_days: int
    theoretical_prob: float
    drift_daily: float
    vol_daily: float
    interpretation: str


@dataclass
class BetExpectedValue:
    strategy: str
    symbol: str
    win_prob: float
    avg_win_pct: float
    avg_loss_pct: float
    expected_value_pct: float
    kelly_fraction: float
    recommendation: str


@dataclass
class ProbabilityAssessment:
    regime_forecast: str
    bayesian_signal: str
    conditional_structure: str
    streak_signal: str
    barrier_risk: str
    ev_signal: str
    theoretical_edge: str


@dataclass
class TheoreticalProbabilityReport:
    markov: MarkovModel
    bayesian: BayesianPosterior
    conditionals: list[ConditionalProb]
    streaks: list[StreakAnalysis]
    barriers: list[BarrierProb]
    expected_values: list[BetExpectedValue]
    sample_size_guidance: dict[str, Any]
    assessment: ProbabilityAssessment
    conviction_score: float
    uncertainty_score: float
    regime_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TheoreticalProbabilityExpert(BaseExpert):
    """Expert in theoretical probability — models and inference on market data."""

    def __init__(self, delay_seconds: float = 0.3) -> None:
        self.delay_seconds = delay_seconds
        super().__init__()

    @staticmethod
    def _norm_cdf(x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

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

    def _markov_chain(self, returns: list[float]) -> MarkovModel:
        counts: dict[str, dict[str, int]] = {
            s: {t: 0 for t in MARKOV_STATES} for s in MARKOV_STATES
        }
        states = [self._classify_state(r) for r in returns]
        for i in range(len(states) - 1):
            counts[states[i]][states[i + 1]] += 1

        matrix: dict[str, dict[str, float]] = {}
        for s in MARKOV_STATES:
            total = sum(counts[s].values()) or 1
            matrix[s] = {t: round(counts[s][t] / total, 4) for t in MARKOV_STATES}

        # Power iteration for stationary distribution
        dist = {s: 1 / 3 for s in MARKOV_STATES}
        for _ in range(50):
            new_dist: dict[str, float] = {t: 0.0 for t in MARKOV_STATES}
            for s in MARKOV_STATES:
                for t in MARKOV_STATES:
                    new_dist[t] += dist[s] * matrix[s][t]
            dist = new_dist
        stationary = {s: round(dist[s], 4) for s in MARKOV_STATES}

        current = states[-1] if states else "neutral"
        forecast = {
            t: round(matrix[current][t], 4) for t in MARKOV_STATES
        }

        return MarkovModel(
            transition_matrix=matrix,
            stationary_distribution=stationary,
            current_state=current,
            one_step_forecast=forecast,
        )

    def _bayesian_update(
        self,
        markov: MarkovModel,
        spy_return_today: float,
        breadth_up_pct: float,
    ) -> BayesianPosterior:
        prior = dict(markov.stationary_distribution)
        if sum(prior.values()) == 0:
            prior = {s: 1 / 3 for s in MARKOV_STATES}

        def likelihood_bull() -> float:
            ret_lik = math.exp(-((spy_return_today - 0.008) ** 2) / (2 * 0.004 ** 2))
            breadth_lik = breadth_up_pct / 100
            return max(0.01, ret_lik * breadth_lik)

        def likelihood_bear() -> float:
            ret_lik = math.exp(-((spy_return_today + 0.008) ** 2) / (2 * 0.004 ** 2))
            breadth_lik = (100 - breadth_up_pct) / 100
            return max(0.01, ret_lik * breadth_lik)

        def likelihood_neutral() -> float:
            ret_lik = math.exp(-(spy_return_today ** 2) / (2 * 0.002 ** 2))
            breadth_lik = 1 - abs(breadth_up_pct - 50) / 50
            return max(0.01, ret_lik * breadth_lik)

        likelihood = {
            "bull": round(likelihood_bull(), 4),
            "bear": round(likelihood_bear(), 4),
            "neutral": round(likelihood_neutral(), 4),
        }

        evidence_total = sum(prior[s] * likelihood[s] for s in MARKOV_STATES)
        if evidence_total == 0:
            evidence_total = 1.0

        posterior = {
            s: round(prior[s] * likelihood[s] / evidence_total, 4) for s in MARKOV_STATES
        }
        dominant = max(posterior, key=posterior.get)

        evidence_txt = (
            f"SPY today {spy_return_today * 100:+.2f}%, "
            f"breadth {breadth_up_pct:.0f}% assets positive"
        )

        return BayesianPosterior(
            prior=prior,
            likelihood=likelihood,
            posterior=posterior,
            evidence=evidence_txt,
            dominant_regime=dominant,
        )

    def _conditional_probs(
        self, return_map: dict[str, list[float]]
    ) -> list[ConditionalProb]:
        pairs: list[tuple[str, str, str, str]] = [
            ("XLK", "SPY", "Technology up", "SPY up"),
            ("XLU", "SPY", "Utilities up", "SPY down"),
            ("XLE", "SPY", "Energy up", "SPY up"),
            ("GLD", "SPY", "Gold up", "SPY down"),
            ("^VIX", "SPY", "VIX up", "SPY down"),
            ("QQQ", "SPY", "Nasdaq up", "SPY up"),
            ("IWM", "SPY", "Small-cap up", "SPY up"),
        ]
        results: list[ConditionalProb] = []
        bench = return_map.get(BENCHMARK, [])
        if not bench:
            return results

        for sym, cond_sym, event, condition in pairs:
            if sym not in return_map or cond_sym not in return_map:
                continue
            a = return_map[sym]
            b = return_map[cond_sym]
            n = min(len(a), len(b))
            if n < 20:
                continue
            a_tail, b_tail = a[-n:], b[-n:]

            if "down" in condition:
                cond_idx = [i for i in range(n) if b_tail[i] < 0]
            else:
                cond_idx = [i for i in range(n) if b_tail[i] > 0]

            if len(cond_idx) < 5:
                continue

            joint = sum(1 for i in cond_idx if a_tail[i] > 0)
            prob = round(joint / len(cond_idx), 4)

            if prob >= 0.65:
                label = "strong positive dependence"
            elif prob <= 0.35:
                label = "inverse or weak dependence"
            else:
                label = "moderate conditional probability"

            results.append(ConditionalProb(
                event=event,
                condition=condition,
                probability=prob,
                sample_size=len(cond_idx),
                label=label,
            ))

        results.sort(key=lambda c: -abs(c.probability - 0.5))
        return results

    def _streak_analysis(self, symbol: str, returns: list[float]) -> StreakAnalysis:
        ups = [r > 0 for r in returns]
        p_up = sum(ups) / len(ups) if ups else 0.5

        longest_up = longest_down = cur_up = cur_down = 0
        for u in ups:
            if u:
                cur_up += 1
                cur_down = 0
                longest_up = max(longest_up, cur_up)
            else:
                cur_down += 1
                cur_up = 0
                longest_down = max(longest_down, cur_down)

        theory = round(p_up ** longest_up, 6) if longest_up > 0 else 1.0
        if longest_up >= 4 and theory < 0.05:
            vs = f"up streak {longest_up} is rare under i.i.d. model (p<{theory:.3f}) — momentum persistence"
        elif longest_down >= 4 and (1 - p_up) ** longest_down < 0.05:
            vs = f"down streak {longest_down} exceeds binomial expectation — capitulation risk"
        else:
            vs = "streaks within theoretical binomial expectations"

        return StreakAnalysis(
            symbol=symbol,
            empirical_up_rate=round(p_up, 4),
            longest_up_streak=longest_up,
            longest_down_streak=longest_down,
            theoretical_streak_prob=theory,
            streak_vs_theory=vs,
        )

    def _barrier_probability(
        self,
        symbol: str,
        closes: list[float],
        barrier_pct: float = -5.0,
        horizon_days: int = 5,
    ) -> BarrierProb | None:
        if len(closes) < 30:
            return None
        returns = self._daily_returns(closes)
        mu = statistics.mean(returns[-60:])
        sigma = statistics.stdev(returns[-60:]) if len(returns) >= 2 else 0.01
        s0 = closes[-1]
        k = s0 * (1 + barrier_pct / 100)
        t = horizon_days / 252

        if sigma <= 0 or k <= 0:
            return None

        d = (math.log(k / s0) - (mu - 0.5 * sigma ** 2) * t) / (sigma * math.sqrt(t))
        prob = round(min(1.0, max(0.0, 2 * self._norm_cdf(d))), 4)

        if prob >= 0.35:
            interp = f"elevated {barrier_pct:.0f}% touch risk within {horizon_days}d"
        elif prob <= 0.10:
            interp = f"low probability of {barrier_pct:.0f}% drawdown in {horizon_days}d"
        else:
            interp = f"moderate {barrier_pct:.0f}% barrier risk over {horizon_days}d"

        return BarrierProb(
            symbol=symbol,
            barrier_pct=barrier_pct,
            horizon_days=horizon_days,
            theoretical_prob=prob,
            drift_daily=round(mu, 6),
            vol_daily=round(sigma, 6),
            interpretation=interp,
        )

    def _expected_values(
        self,
        return_map: dict[str, list[float]],
        posterior: BayesianPosterior,
    ) -> list[BetExpectedValue]:
        bets: list[BetExpectedValue] = []
        p_bull = posterior.posterior.get("bull", 0.33)

        for sym in ("SPY", "QQQ", "XLK"):
            rets = return_map.get(sym, [])
            if len(rets) < 30:
                continue
            wins = [r for r in rets if r > 0]
            losses = [r for r in rets if r <= 0]
            if not wins or not losses:
                continue
            avg_win = statistics.mean(wins)
            avg_loss = abs(statistics.mean(losses))
            win_rate = len(wins) / len(rets)

            # Momentum: bet with trend when bull posterior high
            mom_p = round(0.5 * win_rate + 0.5 * p_bull, 4)
            mom_ev = round((mom_p * avg_win - (1 - mom_p) * avg_loss) * 100, 4)
            b = avg_win / avg_loss if avg_loss else 1
            kelly = round(max(0.0, (mom_p * b - (1 - mom_p)) / b), 4)
            bets.append(BetExpectedValue(
                strategy="momentum",
                symbol=sym,
                win_prob=mom_p,
                avg_win_pct=round(avg_win * 100, 3),
                avg_loss_pct=round(avg_loss * 100, 3),
                expected_value_pct=mom_ev,
                kelly_fraction=kelly,
                recommendation=(
                    "positive EV — size per Kelly" if mom_ev > 0 and kelly > 0.02 else
                    "negative EV — avoid momentum bet"
                ),
            ))

            # Mean reversion after 2 down days
            down_streak_rets: list[float] = []
            for i in range(2, len(rets)):
                if rets[i - 1] < 0 and rets[i - 2] < 0:
                    down_streak_rets.append(rets[i])
            if len(down_streak_rets) >= 8:
                rev_wins = sum(1 for r in down_streak_rets if r > 0)
                rev_p = rev_wins / len(down_streak_rets)
                rev_avg_win = statistics.mean([r for r in down_streak_rets if r > 0]) if rev_wins else avg_win
                rev_avg_loss = abs(statistics.mean([r for r in down_streak_rets if r <= 0])) if rev_wins < len(down_streak_rets) else avg_loss
                rev_ev = round((rev_p * rev_avg_win - (1 - rev_p) * rev_avg_loss) * 100, 4)
                rb = rev_avg_win / rev_avg_loss if rev_avg_loss else 1
                rev_kelly = round(max(0.0, (rev_p * rb - (1 - rev_p)) / rb), 4)
                bets.append(BetExpectedValue(
                    strategy="mean_reversion_2d",
                    symbol=sym,
                    win_prob=round(rev_p, 4),
                    avg_win_pct=round(rev_avg_win * 100, 3),
                    avg_loss_pct=round(rev_avg_loss * 100, 3),
                    expected_value_pct=rev_ev,
                    kelly_fraction=rev_kelly,
                    recommendation=(
                        "mean-reversion edge after 2 down days" if rev_ev > 0 else
                        "no mean-reversion edge"
                    ),
                ))

        bets.sort(key=lambda b: -b.expected_value_pct)
        return bets[:6]

    @staticmethod
    def _sample_size_guidance(p: float, epsilon: float = 0.05) -> dict[str, Any]:
        z = 1.96
        n = math.ceil((z ** 2 * p * (1 - p)) / (epsilon ** 2))
        return {
            "target_precision": epsilon,
            "confidence": 0.95,
            "assumed_win_rate": round(p, 4),
            "min_sample_size": n,
            "interpretation": (
                f"Law of large numbers: need ≥{n} independent trials to estimate "
                f"win-rate within ±{epsilon*100:.0f}% at 95% confidence"
            ),
        }

    def _assessment(
        self,
        markov: MarkovModel,
        bayesian: BayesianPosterior,
        conditionals: list[ConditionalProb],
        streaks: list[StreakAnalysis],
        barriers: list[BarrierProb],
        expected_values: list[BetExpectedValue],
    ) -> ProbabilityAssessment:
        forecast = markov.one_step_forecast
        top_state = max(forecast, key=forecast.get)
        regime_forecast = (
            f"Markov 1-step forecast: {top_state} {forecast[top_state]:.0%} "
            f"(current state: {markov.current_state})"
        )

        dom = bayesian.dominant_regime
        post_p = bayesian.posterior[dom]
        bayesian_signal = (
            f"Bayesian posterior favors {dom} ({post_p:.0%}) given {bayesian.evidence}"
        )

        if conditionals:
            top_c = conditionals[0]
            cond_struct = (
                f"P({top_c.event}|{top_c.condition})={top_c.probability:.0%} "
                f"({top_c.label}, n={top_c.sample_size})"
            )
        else:
            cond_struct = "conditional probability data limited"

        spy_streak = next((s for s in streaks if s.symbol == BENCHMARK), None)
        streak_signal = spy_streak.streak_vs_theory if spy_streak else "streak analysis unavailable"

        spy_barrier = next((b for b in barriers if b.symbol == BENCHMARK), None)
        barrier_risk = spy_barrier.interpretation if spy_barrier else "barrier model unavailable"

        positive_ev = [e for e in expected_values if e.expected_value_pct > 0]
        if positive_ev:
            best = positive_ev[0]
            ev_signal = (
                f"positive EV on {best.symbol} {best.strategy}: "
                f"{best.expected_value_pct:+.3f}% per bet, Kelly f*={best.kelly_fraction:.2%}"
            )
        else:
            ev_signal = "no positive-EV setups under current probability estimates"

        if post_p >= 0.55 and forecast.get("bull", 0) >= 0.4:
            edge = "theoretical models align bullish — momentum bets favored"
        elif post_p >= 0.55 and dom == "bear":
            edge = "bearish posterior — reduce risk, favor hedges (GLD, TLT, XLU)"
        elif positive_ev:
            edge = f"selective edge via {positive_ev[0].strategy} on {positive_ev[0].symbol}"
        else:
            edge = "probability models show no clear edge — stay flat or diversify"

        return ProbabilityAssessment(
            regime_forecast=regime_forecast,
            bayesian_signal=bayesian_signal,
            conditional_structure=cond_struct,
            streak_signal=streak_signal,
            barrier_risk=barrier_risk,
            ev_signal=ev_signal,
            theoretical_edge=edge,
        )

    def _expert_summary(
        self,
        assessment: ProbabilityAssessment,
        bayesian: BayesianPosterior,
        markov: MarkovModel,
        conviction: float,
        label: str,
    ) -> str:
        return (
            f"Theoretical probability scan: {label} (conviction {conviction:.2f}). "
            f"{assessment.regime_forecast}. "
            f"{assessment.bayesian_signal}. "
            f"{assessment.conditional_structure}. "
            f"{assessment.streak_signal}. "
            f"{assessment.barrier_risk}. "
            f"{assessment.ev_signal}. "
            f"Edge: {assessment.theoretical_edge}."
        )

    def analyze(self) -> TheoreticalProbabilityReport:
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
            raise RuntimeError("Unable to fetch SPY data for probability analysis")

        markov = self._markov_chain(spy_returns)

        sector_syms = ["XLK", "XLE", "XLU", "XLF", "QQQ", "IWM", "GLD"]
        breadth_count = 0
        breadth_total = 0
        for sym in sector_syms:
            rets = return_map.get(sym, [])
            if rets:
                breadth_total += 1
                if rets[-1] > 0:
                    breadth_count += 1
        breadth_pct = (breadth_count / breadth_total * 100) if breadth_total else 50.0

        bayesian = self._bayesian_update(markov, spy_returns[-1], breadth_pct)
        conditionals = self._conditional_probs(return_map)
        streaks = [
            self._streak_analysis(sym, return_map[sym])
            for sym in (BENCHMARK, "QQQ", "XLK")
            if sym in return_map
        ]
        barriers = []
        for sym in (BENCHMARK, "QQQ"):
            if sym in price_data:
                b = self._barrier_probability(sym, price_data[sym])
                if b:
                    barriers.append(b)

        expected_values = self._expected_values(return_map, bayesian)
        p_up = sum(1 for r in spy_returns if r > 0) / len(spy_returns)
        sample_guidance = self._sample_size_guidance(p_up)

        assessment = self._assessment(
            markov, bayesian, conditionals, streaks, barriers, expected_values
        )

        conviction = round(
            0.4 * max(bayesian.posterior.values())
            + 0.3 * max(markov.one_step_forecast.values())
            + 0.3 * (1.0 if expected_values and expected_values[0].expected_value_pct > 0 else 0.3),
            4,
        )
        uncertainty = round(1.0 - conviction, 4)

        dom = bayesian.dominant_regime
        if dom == "bull" and conviction >= 0.55:
            regime_label = "Theoretically Bullish"
        elif dom == "bear" and conviction >= 0.55:
            regime_label = "Theoretically Bearish"
        else:
            regime_label = "Theoretically Uncertain"

        summary = self._expert_summary(assessment, bayesian, markov, conviction, regime_label)
        signals = self._market_signals(bayesian, markov, conditionals, expected_values, barriers)
        recs = self._recommendations(
            assessment, markov, bayesian, conditionals, streaks, barriers,
            expected_values, sample_guidance,
        )

        return TheoreticalProbabilityReport(
            markov=markov,
            bayesian=bayesian,
            conditionals=conditionals,
            streaks=streaks,
            barriers=barriers,
            expected_values=expected_values,
            sample_size_guidance=sample_guidance,
            assessment=assessment,
            conviction_score=conviction,
            uncertainty_score=uncertainty,
            regime_label=regime_label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source="Yahoo Finance API",
        )

    @staticmethod
    def _market_signals(
        bayesian: BayesianPosterior,
        markov: MarkovModel,
        conditionals: list[ConditionalProb],
        expected_values: list[BetExpectedValue],
        barriers: list[BarrierProb],
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        dom = bayesian.dominant_regime
        post_p = bayesian.posterior[dom]

        bias = (
            "BULLISH" if dom == "bull" and post_p >= 0.5 else
            "BEARISH" if dom == "bear" and post_p >= 0.5 else
            "NEUTRAL"
        )
        signals.append({
            "sector": "Bayesian Regime",
            "tickers": ["SPY", "QQQ", "IWM"],
            "bias": bias,
            "reason": f"Posterior P({dom})={post_p:.0%} — {bayesian.evidence}",
        })

        bull_f = markov.one_step_forecast.get("bull", 0)
        if bull_f >= 0.45:
            signals.append({
                "sector": "Markov Transition",
                "tickers": ["SPY", "DIA"],
                "bias": "BULLISH",
                "reason": f"P(bull tomorrow | {markov.current_state})={bull_f:.0%}",
            })
        elif markov.one_step_forecast.get("bear", 0) >= 0.45:
            signals.append({
                "sector": "Markov Transition",
                "tickers": ["SH", "TLT", "GLD"],
                "bias": "BEARISH",
                "reason": f"P(bear tomorrow | {markov.current_state})={markov.one_step_forecast['bear']:.0%}",
            })

        for c in conditionals[:2]:
            if c.probability >= 0.65:
                tickers = ["XLK"] if "Technology" in c.event else ["XLU", "GLD"]
                signals.append({
                    "sector": f"Conditional — {c.event}",
                    "tickers": tickers,
                    "bias": "BULLISH",
                    "reason": f"P({c.event}|{c.condition})={c.probability:.0%}",
                })

        for ev in expected_values[:2]:
            if ev.expected_value_pct > 0 and ev.kelly_fraction > 0.02:
                signals.append({
                    "sector": f"Positive EV — {ev.strategy}",
                    "tickers": [ev.symbol],
                    "bias": "BULLISH",
                    "reason": f"EV {ev.expected_value_pct:+.3f}%, Kelly {ev.kelly_fraction:.1%}",
                })

        for b in barriers:
            if b.theoretical_prob >= 0.30:
                signals.append({
                    "sector": "Barrier Risk",
                    "tickers": ["VIXY", "TLT", "GLD"],
                    "bias": "BEARISH",
                    "reason": f"P({b.barrier_pct:.0f}% {b.symbol} in {b.horizon_days}d)={b.theoretical_prob:.0%}",
                })
                break

        if not signals:
            signals.append({
                "sector": "Probability Neutral",
                "tickers": ["SPY"],
                "bias": "NEUTRAL",
                "reason": "Theoretical models show no dominant edge",
            })
        return signals

    @staticmethod
    def _recommendations(
        assessment: ProbabilityAssessment,
        markov: MarkovModel,
        bayesian: BayesianPosterior,
        conditionals: list[ConditionalProb],
        streaks: list[StreakAnalysis],
        barriers: list[BarrierProb],
        expected_values: list[BetExpectedValue],
        sample_guidance: dict[str, Any],
    ) -> list[str]:
        recs = [
            assessment.regime_forecast,
            assessment.bayesian_signal,
            assessment.conditional_structure,
            assessment.streak_signal,
            assessment.barrier_risk,
            assessment.ev_signal,
            assessment.theoretical_edge,
            (
                f"Stationary distribution: bull {markov.stationary_distribution['bull']:.0%}, "
                f"bear {markov.stationary_distribution['bear']:.0%}, "
                f"neutral {markov.stationary_distribution['neutral']:.0%}"
            ),
            sample_guidance["interpretation"],
        ]
        for c in conditionals[:4]:
            recs.append(
                f"P({c.event} | {c.condition}) = {c.probability:.0%} "
                f"({c.label}, n={c.sample_size})"
            )
        for s in streaks:
            recs.append(
                f"{s.symbol} streaks: up {s.longest_up_streak} / down {s.longest_down_streak}, "
                f"p(up)={s.empirical_up_rate:.0%}, theory P(streak)={s.theoretical_streak_prob:.4f}"
            )
        for b in barriers:
            recs.append(
                f"{b.symbol} GBM barrier: P({b.barrier_pct:.0f}% in {b.horizon_days}d)="
                f"{b.theoretical_prob:.0%} — {b.interpretation}"
            )
        for ev in expected_values[:3]:
            recs.append(
                f"{ev.symbol} {ev.strategy}: EV {ev.expected_value_pct:+.3f}%, "
                f"win p={ev.win_prob:.0%}, Kelly f*={ev.kelly_fraction:.1%} — {ev.recommendation}"
            )
        return recs

    def to_dict(self, report: TheoreticalProbabilityReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Theoretical Probability Expert",
                "temperature": self.temperature,
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
                "models_applied": [m["id"] for m in PROBABILITY_MODELS],
            },
            "probability_models": PROBABILITY_MODELS,
            "markov_chain": {
                "states": list(MARKOV_STATES),
                "transition_matrix": report.markov.transition_matrix,
                "stationary_distribution": report.markov.stationary_distribution,
                "current_state": report.markov.current_state,
                "one_step_forecast": report.markov.one_step_forecast,
            },
            "bayesian_inference": {
                "prior": report.bayesian.prior,
                "likelihood": report.bayesian.likelihood,
                "posterior": report.bayesian.posterior,
                "evidence": report.bayesian.evidence,
                "dominant_regime": report.bayesian.dominant_regime,
            },
            "conditional_probabilities": [
                {
                    "event": c.event,
                    "condition": c.condition,
                    "probability": c.probability,
                    "sample_size": c.sample_size,
                    "label": c.label,
                }
                for c in report.conditionals
            ],
            "streak_analysis": [
                {
                    "symbol": s.symbol,
                    "empirical_up_rate": s.empirical_up_rate,
                    "longest_up_streak": s.longest_up_streak,
                    "longest_down_streak": s.longest_down_streak,
                    "theoretical_streak_prob": s.theoretical_streak_prob,
                    "streak_vs_theory": s.streak_vs_theory,
                }
                for s in report.streaks
            ],
            "barrier_probabilities": [
                {
                    "symbol": b.symbol,
                    "barrier_pct": b.barrier_pct,
                    "horizon_days": b.horizon_days,
                    "theoretical_prob": b.theoretical_prob,
                    "drift_daily": b.drift_daily,
                    "vol_daily": b.vol_daily,
                    "interpretation": b.interpretation,
                }
                for b in report.barriers
            ],
            "expected_values": [
                {
                    "strategy": e.strategy,
                    "symbol": e.symbol,
                    "win_prob": e.win_prob,
                    "avg_win_pct": e.avg_win_pct,
                    "avg_loss_pct": e.avg_loss_pct,
                    "expected_value_pct": e.expected_value_pct,
                    "kelly_fraction": e.kelly_fraction,
                    "recommendation": e.recommendation,
                }
                for e in report.expected_values
            ],
            "sample_size_guidance": report.sample_size_guidance,
            "probability_assessment": {
                "regime_forecast": a.regime_forecast,
                "bayesian_signal": a.bayesian_signal,
                "conditional_structure": a.conditional_structure,
                "streak_signal": a.streak_signal,
                "barrier_risk": a.barrier_risk,
                "ev_signal": a.ev_signal,
                "theoretical_edge": a.theoretical_edge,
            },
            "metrics": {
                "conviction_score": report.conviction_score,
                "uncertainty_score": report.uncertainty_score,
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
            models_path = output.parent / "probability_models.json"
            models_path.write_text(
                json.dumps(PROBABILITY_MODELS, indent=2),
                encoding="utf-8",
            )
        return result


def run_theoretical_probability_analysis(output: Path | None = None) -> dict[str, Any]:
    return TheoreticalProbabilityExpert().run(output=output)