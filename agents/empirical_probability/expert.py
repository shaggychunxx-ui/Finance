"""
Empirical (Experimental) Probability Expert Agent
=================================================
Expert in empirical/experimental probability applied to financial markets:
observed frequencies, rolling win rates, Wilson confidence intervals,
bootstrap resampling, return-bin histograms, and out-of-sample rule experiments.

Data: Yahoo Finance chart API (1-year daily history).
"""

from __future__ import annotations

import json
import math
import random
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Finance-Empirical-Probability/1.0 (shaggychunxx@gmail.com)"}

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

BOOTSTRAP_SAMPLES = 2000
TRAIN_RATIO = 0.7

EMPIRICAL_EXPERIMENTS: list[dict[str, Any]] = [
    {
        "id": "daily_frequency",
        "name": "Daily Up/Down Frequency",
        "description": "Empirical P(up) and P(down) from observed daily return counts",
        "method": "frequency = successes / trials",
    },
    {
        "id": "rolling_win_rate",
        "name": "Rolling Window Win Rate",
        "description": "20/60/120-day rolling empirical win probabilities",
        "method": "P_up(window) = count(r>0) / window_size",
    },
    {
        "id": "wilson_ci",
        "name": "Wilson Score Confidence Interval",
        "description": "95% CI for empirical win rate accounting for finite sample size",
        "method": "Wilson score interval for binomial proportion",
    },
    {
        "id": "conditional_frequency",
        "name": "Conditional Empirical Frequency",
        "description": "P(up today | prior day up/down) from joint observation counts",
        "method": "P(A|B) = count(A∩B) / count(B)",
    },
    {
        "id": "return_histogram",
        "name": "Return Bin Histogram",
        "description": "Empirical probability mass across return buckets",
        "method": "P(bin) = count(returns in bin) / total_returns",
    },
    {
        "id": "bootstrap_resample",
        "name": "Bootstrap Resampling",
        "description": "Non-parametric CI for mean return and win rate via resampling",
        "method": "2000 bootstrap draws with replacement",
    },
    {
        "id": "momentum_experiment",
        "name": "Momentum Rule Experiment",
        "description": "Buy after positive 5d return — empirical win rate and avg payoff",
        "method": "experimental trial = enter when 5d return > 0, measure next-day outcome",
    },
    {
        "id": "mean_reversion_experiment",
        "name": "Mean-Reversion Rule Experiment",
        "description": "Buy after 2 consecutive down days — empirical recovery frequency",
        "method": "experimental trial = enter after 2 down days, measure next-day outcome",
    },
    {
        "id": "out_of_sample",
        "name": "Out-of-Sample Validation",
        "description": "Train/test split (70/30) to validate experimental rule stability",
        "method": "compare in-sample vs out-of-sample empirical win rates",
    },
]


@dataclass
class FrequencyEstimate:
    symbol: str
    event: str
    trials: int
    successes: int
    empirical_prob: float
    wilson_ci_low: float
    wilson_ci_high: float
    sample_adequate: bool


@dataclass
class RollingWinRate:
    symbol: str
    window_days: int
    empirical_prob: float
    trials: int


@dataclass
class ReturnBin:
    label: str
    lower_pct: float
    upper_pct: float
    count: int
    empirical_prob: float


@dataclass
class BootstrapResult:
    symbol: str
    metric: str
    point_estimate: float
    ci_low: float
    ci_high: float
    bootstrap_samples: int


@dataclass
class RuleExperiment:
    rule_id: str
    symbol: str
    description: str
    in_sample_trials: int
    in_sample_win_rate: float
    out_of_sample_trials: int
    out_of_sample_win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    empirical_edge: str
    stable: bool


@dataclass
class EmpiricalAssessment:
    frequency_signal: str
    rolling_trend: str
    conditional_signal: str
    histogram_signal: str
    experiment_signal: str
    bootstrap_signal: str
    experimental_edge: str


@dataclass
class EmpiricalProbabilityReport:
    frequencies: list[FrequencyEstimate]
    rolling_rates: list[RollingWinRate]
    return_bins: list[ReturnBin]
    bootstrap_results: list[BootstrapResult]
    experiments: list[RuleExperiment]
    conditionals: list[FrequencyEstimate]
    assessment: EmpiricalAssessment
    evidence_score: float
    stability_score: float
    regime_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EmpiricalProbabilityExpert:
    """Expert in empirical/experimental probability — observed frequencies and rule trials."""

    def __init__(self, delay_seconds: float = 0.3) -> None:
        self.delay_seconds = delay_seconds
        # Randomized creativity/variance level for this run's analysis (1=conservative, 8=exploratory)
        self.temperature = random.randint(1, 8)

    def _fetch_closes(self, symbol: str) -> list[float]:
        try:
            resp = requests.get(
                CHART_API.format(symbol=symbol),
                params={"interval": "1d", "range": "1y"},
                headers=HEADERS,
                timeout=25,
            )
            if resp.status_code == 429:
                time.sleep(3)
                resp = requests.get(
                    CHART_API.format(symbol=symbol),
                    params={"interval": "1d", "range": "1y"},
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
    def _wilson_ci(successes: int, trials: int, z: float = 1.96) -> tuple[float, float]:
        if trials == 0:
            return 0.0, 1.0
        p = successes / trials
        denom = 1 + z ** 2 / trials
        center = (p + z ** 2 / (2 * trials)) / denom
        margin = z * math.sqrt((p * (1 - p) + z ** 2 / (4 * trials)) / trials) / denom
        return round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4)

    def _frequency(
        self,
        symbol: str,
        event: str,
        returns: list[float],
        predicate: Any = None,
    ) -> FrequencyEstimate:
        if predicate is None:
            successes = sum(1 for r in returns if r > 0)
            trials = len(returns)
            event = event or "daily up"
        else:
            trials = 0
            successes = 0
            for i, r in enumerate(returns):
                if predicate(returns, i):
                    trials += 1
                    if r > 0:
                        successes += 1

        prob = round(successes / trials, 4) if trials else 0.5
        lo, hi = self._wilson_ci(successes, trials)
        adequate = trials >= 30 and (hi - lo) <= 0.25

        return FrequencyEstimate(
            symbol=symbol,
            event=event,
            trials=trials,
            successes=successes,
            empirical_prob=prob,
            wilson_ci_low=lo,
            wilson_ci_high=hi,
            sample_adequate=adequate,
        )

    def _rolling_rates(self, symbol: str, returns: list[float]) -> list[RollingWinRate]:
        rates: list[RollingWinRate] = []
        for window in (20, 60, 120):
            if len(returns) < window:
                continue
            recent = returns[-window:]
            ups = sum(1 for r in recent if r > 0)
            rates.append(RollingWinRate(
                symbol=symbol,
                window_days=window,
                empirical_prob=round(ups / window, 4),
                trials=window,
            ))
        return rates

    @staticmethod
    def _return_bins(returns: list[float]) -> list[ReturnBin]:
        bins_def = [
            ("large down (<-2%)", -100, -2.0),
            ("moderate down (-2% to -0.5%)", -2.0, -0.5),
            ("flat (-0.5% to +0.5%)", -0.5, 0.5),
            ("moderate up (+0.5% to +2%)", 0.5, 2.0),
            ("large up (>+2%)", 2.0, 100),
        ]
        total = len(returns) or 1
        bins: list[ReturnBin] = []
        for label, lo, hi in bins_def:
            count = sum(1 for r in returns if lo <= r * 100 < hi)
            bins.append(ReturnBin(
                label=label,
                lower_pct=lo,
                upper_pct=hi,
                count=count,
                empirical_prob=round(count / total, 4),
            ))
        return bins

    def _bootstrap(self, symbol: str, returns: list[float]) -> list[BootstrapResult]:
        if len(returns) < 30:
            return []
        results: list[BootstrapResult] = []
        n = len(returns)

        for metric, extractor in (
            ("win_rate", lambda sample: sum(1 for r in sample if r > 0) / len(sample)),
            ("mean_return_pct", lambda sample: statistics.mean(sample) * 100),
        ):
            estimates: list[float] = []
            for _ in range(BOOTSTRAP_SAMPLES):
                sample = [returns[random.randrange(n)] for _ in range(n)]
                estimates.append(extractor(sample))
            estimates.sort()
            lo = estimates[int(0.025 * len(estimates))]
            hi = estimates[int(0.975 * len(estimates))]
            point = extractor(returns)
            results.append(BootstrapResult(
                symbol=symbol,
                metric=metric,
                point_estimate=round(point, 4),
                ci_low=round(lo, 4),
                ci_high=round(hi, 4),
                bootstrap_samples=BOOTSTRAP_SAMPLES,
            ))
        return results

    def _conditional_frequencies(
        self, symbol: str, returns: list[float]
    ) -> list[FrequencyEstimate]:
        results: list[FrequencyEstimate] = []

        def after_up(rets: list[float], i: int) -> bool:
            return i > 0 and rets[i - 1] > 0

        def after_down(rets: list[float], i: int) -> bool:
            return i > 0 and rets[i - 1] < 0

        def after_two_down(rets: list[float], i: int) -> bool:
            return i > 1 and rets[i - 1] < 0 and rets[i - 2] < 0

        for event, pred in (
            ("up after prior up", after_up),
            ("up after prior down", after_down),
            ("up after 2 down days", after_two_down),
        ):
            results.append(self._frequency(symbol, event, returns, pred))

        return results

    def _rule_experiment(
        self,
        rule_id: str,
        symbol: str,
        description: str,
        returns: list[float],
        entry_fn: Any,
    ) -> RuleExperiment | None:
        if len(returns) < 40:
            return None

        split = int(len(returns) * TRAIN_RATIO)
        train, test = returns[:split], returns[split:]

        def run_trials(rets: list[float]) -> tuple[int, int, list[float], list[float]]:
            trials = wins = 0
            win_rets: list[float] = []
            loss_rets: list[float] = []
            for i in range(len(rets)):
                if not entry_fn(rets, i):
                    continue
                trials += 1
                if rets[i] > 0:
                    wins += 1
                    win_rets.append(rets[i])
                else:
                    loss_rets.append(rets[i])
            return trials, wins, win_rets, loss_rets

        in_trials, in_wins, in_win_rets, in_loss_rets = run_trials(train)
        out_trials, out_wins, _, _ = run_trials(test)

        in_rate = round(in_wins / in_trials, 4) if in_trials else 0.0
        out_rate = round(out_wins / out_trials, 4) if out_trials else 0.0
        avg_win = round(statistics.mean(in_win_rets) * 100, 3) if in_win_rets else 0.0
        avg_loss = round(abs(statistics.mean(in_loss_rets)) * 100, 3) if in_loss_rets else 0.0

        stable = in_trials >= 10 and out_trials >= 5 and abs(in_rate - out_rate) <= 0.15
        if in_rate >= 0.55 and stable:
            edge = f"empirical edge confirmed — {in_rate:.0%} in-sample, {out_rate:.0%} out-of-sample"
        elif in_rate >= 0.55:
            edge = f"in-sample edge {in_rate:.0%} but unstable out-of-sample ({out_rate:.0%})"
        else:
            edge = f"no reliable edge — in-sample win rate {in_rate:.0%}"

        return RuleExperiment(
            rule_id=rule_id,
            symbol=symbol,
            description=description,
            in_sample_trials=in_trials,
            in_sample_win_rate=in_rate,
            out_of_sample_trials=out_trials,
            out_of_sample_win_rate=out_rate,
            avg_win_pct=avg_win,
            avg_loss_pct=avg_loss,
            empirical_edge=edge,
            stable=stable,
        )

    def _assessment(
        self,
        frequencies: list[FrequencyEstimate],
        rolling: list[RollingWinRate],
        bins: list[ReturnBin],
        experiments: list[RuleExperiment],
        bootstrap_results: list[BootstrapResult],
        conditionals: list[FrequencyEstimate],
    ) -> EmpiricalAssessment:
        spy_freq = next((f for f in frequencies if f.symbol == BENCHMARK), None)
        if spy_freq:
            freq_sig = (
                f"SPY empirical P(up)={spy_freq.empirical_prob:.0%} "
                f"(n={spy_freq.trials}, 95% CI [{spy_freq.wilson_ci_low:.0%}, {spy_freq.wilson_ci_high:.0%}])"
            )
        else:
            freq_sig = "frequency data unavailable"

        spy_rolling = [r for r in rolling if r.symbol == BENCHMARK]
        if len(spy_rolling) >= 2:
            short = spy_rolling[0].empirical_prob
            long = spy_rolling[-1].empirical_prob
            if short > long + 0.08:
                roll_trend = f"rising short-term win rate ({short:.0%} 20d vs {long:.0%} 120d)"
            elif short < long - 0.08:
                roll_trend = f"falling short-term win rate ({short:.0%} 20d vs {long:.0%} 120d)"
            else:
                roll_trend = f"stable rolling win rates ({short:.0%} to {long:.0%})"
        else:
            roll_trend = "rolling win rate data limited"

        after_down = next((c for c in conditionals if "prior down" in c.event), None)
        after_up = next((c for c in conditionals if "prior up" in c.event), None)
        if after_down and after_up:
            if after_down.empirical_prob > after_up.empirical_prob + 0.05:
                cond_sig = (
                    f"mean-reversion tendency: P(up|down)={after_down.empirical_prob:.0%} > "
                    f"P(up|up)={after_up.empirical_prob:.0%}"
                )
            elif after_up.empirical_prob > after_down.empirical_prob + 0.05:
                cond_sig = (
                    f"momentum tendency: P(up|up)={after_up.empirical_prob:.0%} > "
                    f"P(up|down)={after_down.empirical_prob:.0%}"
                )
            else:
                cond_sig = "conditional frequencies near symmetric — weak serial dependence"
        else:
            cond_sig = "conditional frequency data limited"

        large_moves = sum(b.empirical_prob for b in bins if "large" in b.label)
        if large_moves >= 0.25:
            hist_sig = f"fat empirical tails — {large_moves:.0%} of days are large moves (|r|>2%)"
        else:
            hist_sig = f"moderate tail frequency — {large_moves:.0%} large-move days"

        stable_exps = [e for e in experiments if e.stable and e.in_sample_win_rate >= 0.55]
        if stable_exps:
            best = max(stable_exps, key=lambda e: e.out_of_sample_win_rate)
            exp_sig = (
                f"validated experiment '{best.rule_id}' on {best.symbol}: "
                f"OOS win rate {best.out_of_sample_win_rate:.0%}"
            )
        elif experiments:
            exp_sig = "experimental rules lack out-of-sample stability"
        else:
            exp_sig = "no rule experiments completed"

        boot = next((b for b in bootstrap_results if b.metric == "win_rate"), None)
        if boot:
            boot_sig = (
                f"bootstrap win-rate CI [{boot.ci_low:.0%}, {boot.ci_high:.0%}] "
                f"(point {boot.point_estimate:.0%})"
            )
        else:
            boot_sig = "bootstrap results unavailable"

        if stable_exps:
            best = stable_exps[0]
            edge = f"experimental edge via {best.rule_id} on {best.symbol} — empirically validated"
        elif after_down and after_down.empirical_prob >= 0.58:
            edge = "conditional mean-reversion frequency supports dip-buying experiments"
        elif spy_freq and spy_freq.empirical_prob >= 0.55:
            edge = "positive empirical drift — frequency favors long bias"
        else:
            edge = "empirical evidence does not support a directional edge"

        return EmpiricalAssessment(
            frequency_signal=freq_sig,
            rolling_trend=roll_trend,
            conditional_signal=cond_sig,
            histogram_signal=hist_sig,
            experiment_signal=exp_sig,
            bootstrap_signal=boot_sig,
            experimental_edge=edge,
        )

    def _expert_summary(
        self,
        assessment: EmpiricalAssessment,
        label: str,
        evidence: float,
    ) -> str:
        return (
            f"Empirical probability scan: {label} (evidence {evidence:.2f}). "
            f"{assessment.frequency_signal}. "
            f"{assessment.rolling_trend}. "
            f"{assessment.conditional_signal}. "
            f"{assessment.histogram_signal}. "
            f"{assessment.experiment_signal}. "
            f"{assessment.bootstrap_signal}. "
            f"Edge: {assessment.experimental_edge}."
        )

    def analyze(self) -> EmpiricalProbabilityReport:
        return_map: dict[str, list[float]] = {}

        for symbol in WATCHLIST:
            closes = self._fetch_closes(symbol)
            if closes:
                return_map[symbol] = self._daily_returns(closes)
            time.sleep(self.delay_seconds)

        if BENCHMARK not in return_map:
            raise RuntimeError("Unable to fetch SPY data for empirical probability analysis")

        frequencies: list[FrequencyEstimate] = []
        rolling_rates: list[RollingWinRate] = []
        all_conditionals: list[FrequencyEstimate] = []
        experiments: list[RuleExperiment] = []
        bootstrap_results: list[BootstrapResult] = []

        for symbol, returns in return_map.items():
            frequencies.append(self._frequency(symbol, "daily up", returns))
            rolling_rates.extend(self._rolling_rates(symbol, returns))
            if symbol in (BENCHMARK, "QQQ", "XLK"):
                all_conditionals.extend(self._conditional_frequencies(symbol, returns))
            if symbol == BENCHMARK:
                bootstrap_results = self._bootstrap(symbol, returns)

        return_bins = self._return_bins(return_map[BENCHMARK])

        def momentum_entry(rets: list[float], i: int) -> bool:
            if i < 5:
                return False
            ret_5d = (1 + rets[i - 1]) * (1 + rets[i - 2]) * (1 + rets[i - 3]) * (1 + rets[i - 4]) * (1 + rets[i - 5]) - 1
            return ret_5d > 0

        def reversion_entry(rets: list[float], i: int) -> bool:
            return i > 1 and rets[i - 1] < 0 and rets[i - 2] < 0

        for symbol in (BENCHMARK, "QQQ", "XLK"):
            rets = return_map.get(symbol, [])
            mom = self._rule_experiment(
                "momentum_5d",
                symbol,
                "Enter when 5-day cumulative return > 0, measure next-day up frequency",
                rets,
                momentum_entry,
            )
            if mom:
                experiments.append(mom)
            rev = self._rule_experiment(
                "mean_reversion_2d",
                symbol,
                "Enter after 2 consecutive down days, measure next-day recovery frequency",
                rets,
                reversion_entry,
            )
            if rev:
                experiments.append(rev)

        assessment = self._assessment(
            frequencies, rolling_rates, return_bins,
            experiments, bootstrap_results, all_conditionals,
        )

        spy_freq = next(f for f in frequencies if f.symbol == BENCHMARK)
        stable_count = sum(1 for e in experiments if e.stable)
        evidence_score = round(
            0.35 * spy_freq.empirical_prob
            + 0.25 * (stable_count / max(len(experiments), 1))
            + 0.20 * (1.0 if spy_freq.sample_adequate else 0.4)
            + 0.20 * min(1.0, spy_freq.trials / 200),
            4,
        )
        stability_score = round(stable_count / max(len(experiments), 1), 4)

        if evidence_score >= 0.58 and spy_freq.empirical_prob >= 0.52:
            regime_label = "Empirically Bullish"
        elif evidence_score <= 0.42 or spy_freq.empirical_prob <= 0.45:
            regime_label = "Empirically Bearish"
        else:
            regime_label = "Empirically Mixed"

        summary = self._expert_summary(assessment, regime_label, evidence_score)
        signals = self._market_signals(frequencies, experiments, all_conditionals, rolling_rates)
        recs = self._recommendations(
            assessment, frequencies, rolling_rates, return_bins,
            experiments, bootstrap_results, all_conditionals,
        )

        return EmpiricalProbabilityReport(
            frequencies=frequencies,
            rolling_rates=rolling_rates,
            return_bins=return_bins,
            bootstrap_results=bootstrap_results,
            experiments=experiments,
            conditionals=all_conditionals,
            assessment=assessment,
            evidence_score=evidence_score,
            stability_score=stability_score,
            regime_label=regime_label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source="Yahoo Finance API",
        )

    @staticmethod
    def _market_signals(
        frequencies: list[FrequencyEstimate],
        experiments: list[RuleExperiment],
        conditionals: list[FrequencyEstimate],
        rolling: list[RollingWinRate],
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        spy = next((f for f in frequencies if f.symbol == BENCHMARK), None)

        if spy:
            bias = (
                "BULLISH" if spy.empirical_prob >= 0.55 else
                "BEARISH" if spy.empirical_prob <= 0.45 else
                "NEUTRAL"
            )
            signals.append({
                "sector": "Empirical Daily Frequency",
                "tickers": ["SPY", "VOO", "IVV"],
                "bias": bias,
                "reason": (
                    f"P(up)={spy.empirical_prob:.0%} over {spy.trials} days "
                    f"[{spy.wilson_ci_low:.0%}, {spy.wilson_ci_high:.0%}]"
                ),
            })

        for exp in experiments:
            if exp.stable and exp.out_of_sample_win_rate >= 0.55:
                signals.append({
                    "sector": f"Validated Experiment — {exp.rule_id}",
                    "tickers": [exp.symbol],
                    "bias": "BULLISH",
                    "reason": (
                        f"OOS win rate {exp.out_of_sample_win_rate:.0%} "
                        f"({exp.out_of_sample_trials} trials)"
                    ),
                })

        rev = next(
            (c for c in conditionals if c.symbol == BENCHMARK and "2 down" in c.event),
            None,
        )
        if rev and rev.empirical_prob >= 0.58 and rev.sample_adequate:
            signals.append({
                "sector": "Conditional Mean Reversion",
                "tickers": ["SPY", "SSO"],
                "bias": "BULLISH",
                "reason": f"P(up after 2 down days)={rev.empirical_prob:.0%} (n={rev.trials})",
            })

        r20 = next(
            (r for r in rolling if r.symbol == BENCHMARK and r.window_days == 20),
            None,
        )
        r120 = next(
            (r for r in rolling if r.symbol == BENCHMARK and r.window_days == 120),
            None,
        )
        if r20 and r120 and r20.empirical_prob < r120.empirical_prob - 0.1:
            signals.append({
                "sector": "Rolling Win-Rate Decline",
                "tickers": ["SH", "TLT", "GLD"],
                "bias": "BEARISH",
                "reason": f"20d win rate {r20.empirical_prob:.0%} vs 120d {r120.empirical_prob:.0%}",
            })

        if not signals:
            signals.append({
                "sector": "Empirical Neutral",
                "tickers": ["SPY"],
                "bias": "NEUTRAL",
                "reason": "Observed frequencies show no dominant edge",
            })
        return signals

    @staticmethod
    def _recommendations(
        assessment: EmpiricalAssessment,
        frequencies: list[FrequencyEstimate],
        rolling: list[RollingWinRate],
        bins: list[ReturnBin],
        experiments: list[RuleExperiment],
        bootstrap_results: list[BootstrapResult],
        conditionals: list[FrequencyEstimate],
    ) -> list[str]:
        recs = [
            assessment.frequency_signal,
            assessment.rolling_trend,
            assessment.conditional_signal,
            assessment.histogram_signal,
            assessment.experiment_signal,
            assessment.bootstrap_signal,
            assessment.experimental_edge,
        ]
        for f in sorted(frequencies, key=lambda x: -x.empirical_prob)[:4]:
            recs.append(
                f"{f.symbol} P({f.event})={f.empirical_prob:.0%} "
                f"(n={f.trials}, CI [{f.wilson_ci_low:.0%}, {f.wilson_ci_high:.0%}])"
            )
        for r in [x for x in rolling if x.symbol == BENCHMARK]:
            recs.append(f"SPY {r.window_days}d rolling win rate: {r.empirical_prob:.0%}")
        for b in bins:
            if b.empirical_prob >= 0.15:
                recs.append(f"Return bin '{b.label}': {b.empirical_prob:.0%} ({b.count} days)")
        for c in conditionals[:4]:
            recs.append(
                f"{c.symbol} P({c.event})={c.empirical_prob:.0%} "
                f"(n={c.trials}, adequate={c.sample_adequate})"
            )
        for e in experiments:
            recs.append(
                f"{e.symbol} {e.rule_id}: in-sample {e.in_sample_win_rate:.0%} "
                f"(n={e.in_sample_trials}), OOS {e.out_of_sample_win_rate:.0%} "
                f"(n={e.out_of_sample_trials}) — {e.empirical_edge}"
            )
        for b in bootstrap_results:
            recs.append(
                f"{b.symbol} bootstrap {b.metric}: {b.point_estimate} "
                f"[{b.ci_low}, {b.ci_high}] ({b.bootstrap_samples} resamples)"
            )
        return recs

    def to_dict(self, report: EmpiricalProbabilityReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Empirical Probability Expert",
                "temperature": self.temperature,
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
                "experiments_run": [e["id"] for e in EMPIRICAL_EXPERIMENTS],
            },
            "empirical_experiments": EMPIRICAL_EXPERIMENTS,
            "frequency_estimates": [
                {
                    "symbol": f.symbol,
                    "event": f.event,
                    "trials": f.trials,
                    "successes": f.successes,
                    "empirical_prob": f.empirical_prob,
                    "wilson_ci_low": f.wilson_ci_low,
                    "wilson_ci_high": f.wilson_ci_high,
                    "sample_adequate": f.sample_adequate,
                }
                for f in report.frequencies
            ],
            "rolling_win_rates": [
                {
                    "symbol": r.symbol,
                    "window_days": r.window_days,
                    "empirical_prob": r.empirical_prob,
                    "trials": r.trials,
                }
                for r in report.rolling_rates
            ],
            "return_bins": [
                {
                    "label": b.label,
                    "lower_pct": b.lower_pct,
                    "upper_pct": b.upper_pct,
                    "count": b.count,
                    "empirical_prob": b.empirical_prob,
                }
                for b in report.return_bins
            ],
            "bootstrap_results": [
                {
                    "symbol": b.symbol,
                    "metric": b.metric,
                    "point_estimate": b.point_estimate,
                    "ci_low": b.ci_low,
                    "ci_high": b.ci_high,
                    "bootstrap_samples": b.bootstrap_samples,
                }
                for b in report.bootstrap_results
            ],
            "rule_experiments": [
                {
                    "rule_id": e.rule_id,
                    "symbol": e.symbol,
                    "description": e.description,
                    "in_sample_trials": e.in_sample_trials,
                    "in_sample_win_rate": e.in_sample_win_rate,
                    "out_of_sample_trials": e.out_of_sample_trials,
                    "out_of_sample_win_rate": e.out_of_sample_win_rate,
                    "avg_win_pct": e.avg_win_pct,
                    "avg_loss_pct": e.avg_loss_pct,
                    "empirical_edge": e.empirical_edge,
                    "stable": e.stable,
                }
                for e in report.experiments
            ],
            "conditional_frequencies": [
                {
                    "symbol": c.symbol,
                    "event": c.event,
                    "trials": c.trials,
                    "successes": c.successes,
                    "empirical_prob": c.empirical_prob,
                    "wilson_ci_low": c.wilson_ci_low,
                    "wilson_ci_high": c.wilson_ci_high,
                    "sample_adequate": c.sample_adequate,
                }
                for c in report.conditionals
            ],
            "empirical_assessment": {
                "frequency_signal": a.frequency_signal,
                "rolling_trend": a.rolling_trend,
                "conditional_signal": a.conditional_signal,
                "histogram_signal": a.histogram_signal,
                "experiment_signal": a.experiment_signal,
                "bootstrap_signal": a.bootstrap_signal,
                "experimental_edge": a.experimental_edge,
            },
            "metrics": {
                "evidence_score": report.evidence_score,
                "stability_score": report.stability_score,
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
            catalog = output.parent / "empirical_experiments.json"
            catalog.write_text(
                json.dumps(EMPIRICAL_EXPERIMENTS, indent=2),
                encoding="utf-8",
            )
        return result


def run_empirical_probability_analysis(output: Path | None = None) -> dict[str, Any]:
    return EmpiricalProbabilityExpert().run(output=output)