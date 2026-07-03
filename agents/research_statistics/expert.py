"""
Research Statistics Expert Agent
================================
Research scientist / statistician analysis of financial market data:
hypothesis tests, confidence intervals, linear regression, autocorrelation,
normality diagnostics, variance tests, and research-grade findings.

Data: Yahoo Finance chart API (1-year daily history).
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

CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Finance-Research-Statistics/1.0 (shaggychunxx@gmail.com)"}

BENCHMARK = "SPY"
ALPHA = 0.05
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

STATISTICAL_METHODS: list[dict[str, Any]] = [
    {
        "id": "one_sample_ttest",
        "name": "One-Sample t-Test",
        "description": "Test H₀: mean daily return = 0 against two-sided alternative",
        "formula": "t = (x̄ - μ₀) / (s / √n)",
    },
    {
        "id": "two_sample_ttest",
        "name": "Two-Sample t-Test",
        "description": "Compare mean returns of asset vs benchmark",
        "formula": "t = (x̄₁ - x̄₂) / √(s₁²/n₁ + s₂²/n₂)",
    },
    {
        "id": "confidence_interval",
        "name": "Confidence Interval for Mean Return",
        "description": "95% CI for expected daily return using t critical value",
        "formula": "CI = x̄ ± t_{α/2, n-1} · (s / √n)",
    },
    {
        "id": "ols_regression",
        "name": "OLS Linear Regression",
        "description": "Regress asset returns on benchmark — estimate α, β, R²",
        "formula": "β = Cov(rᵢ, rₘ) / Var(rₘ), α = r̄ᵢ - β·r̄ₘ",
    },
    {
        "id": "autocorrelation",
        "name": "Lag-1 Autocorrelation",
        "description": "Serial correlation in daily returns — momentum vs mean-reversion signal",
        "formula": "ρ₁ = Corr(rₜ, rₜ₋₁)",
    },
    {
        "id": "jarque_bera",
        "name": "Jarque-Bera Normality Test",
        "description": "Test whether returns follow a normal distribution",
        "formula": "JB = (n/6)(S² + (K-3)²/4)",
    },
    {
        "id": "f_test_variance",
        "name": "F-Test for Equal Variances",
        "description": "Compare return volatility between asset and benchmark",
        "formula": "F = s₁² / s₂²",
    },
    {
        "id": "effect_size",
        "name": "Cohen's d Effect Size",
        "description": "Standardized difference in mean returns vs benchmark",
        "formula": "d = (x̄₁ - x̄₂) / s_pooled",
    },
]


@dataclass
class HypothesisTest:
    test_id: str
    symbol: str
    hypothesis: str
    statistic: float
    p_value: float
    significant: bool
    conclusion: str
    sample_size: int


@dataclass
class ConfidenceInterval:
    symbol: str
    metric: str
    point_estimate: float
    ci_low: float
    ci_high: float
    confidence_level: float


@dataclass
class RegressionResult:
    symbol: str
    benchmark: str
    alpha_daily: float
    beta: float
    r_squared: float
    slope_se: float
    slope_t_stat: float
    slope_p_value: float
    significant_beta: bool
    interpretation: str


@dataclass
class AutocorrelationResult:
    symbol: str
    lag: int
    autocorr: float
    t_stat: float
    p_value: float
    significant: bool
    interpretation: str


@dataclass
class NormalityResult:
    symbol: str
    skewness: float
    excess_kurtosis: float
    jarque_bera: float
    jb_p_value: float
    normal: bool
    interpretation: str


@dataclass
class VarianceTest:
    symbol_a: str
    symbol_b: str
    f_statistic: float
    p_value: float
    significant: bool
    interpretation: str


@dataclass
class ResearchFinding:
    title: str
    method: str
    symbols: list[str]
    statistic: float
    p_value: float
    significant: bool
    practical_implication: str


@dataclass
class ResearchAssessment:
    drift_signal: str
    regression_signal: str
    serial_correlation_signal: str
    normality_signal: str
    volatility_signal: str
    research_conclusion: str
    statistical_edge: str


@dataclass
class ResearchStatisticsReport:
    hypothesis_tests: list[HypothesisTest]
    confidence_intervals: list[ConfidenceInterval]
    regressions: list[RegressionResult]
    autocorrelations: list[AutocorrelationResult]
    normality_tests: list[NormalityResult]
    variance_tests: list[VarianceTest]
    findings: list[ResearchFinding]
    assessment: ResearchAssessment
    significance_score: float
    research_quality_score: float
    regime_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ResearchStatisticsExpert:
    """Research scientist / statistician — formal inference on market return data."""

    def __init__(self, delay_seconds: float = 0.3) -> None:
        self.delay_seconds = delay_seconds

    @staticmethod
    def _norm_cdf(x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    @staticmethod
    def _p_value_normal(z: float) -> float:
        return round(2 * (1 - ResearchStatisticsExpert._norm_cdf(abs(z))), 4)

    @staticmethod
    def _t_critical(df: int, alpha: float = 0.05) -> float:
        """Approximate two-tailed t critical value."""
        table = {
            5: 2.571, 10: 2.228, 20: 2.086, 30: 2.042,
            50: 2.009, 100: 1.984, 200: 1.972, 250: 1.969,
        }
        if df >= 200:
            return 1.96
        keys = sorted(table)
        for k in keys:
            if df <= k:
                return table[k]
        return 1.96

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

    def _one_sample_ttest(self, symbol: str, returns: list[float]) -> HypothesisTest:
        n = len(returns)
        mean = statistics.mean(returns)
        stdev = statistics.stdev(returns) if n > 1 else 1e-9
        t_stat = (mean - 0) / (stdev / math.sqrt(n))
        p_val = self._p_value_normal(t_stat) if n >= 30 else self._p_value_normal(t_stat) * 1.05
        sig = p_val < ALPHA
        ann_mean = mean * 252 * 100
        conclusion = (
            f"reject H₀ — mean daily return significantly ≠ 0 (annualized ≈ {ann_mean:+.1f}%)"
            if sig and mean > 0 else
            f"reject H₀ — significant negative drift (annualized ≈ {ann_mean:+.1f}%)"
            if sig else
            "fail to reject H₀ — no statistically significant drift from zero"
        )
        return HypothesisTest(
            test_id="one_sample_ttest",
            symbol=symbol,
            hypothesis="H₀: μ_daily = 0",
            statistic=round(t_stat, 4),
            p_value=round(min(p_val, 1.0), 4),
            significant=sig,
            conclusion=conclusion,
            sample_size=n,
        )

    def _two_sample_ttest(
        self, symbol: str, returns: list[float], bench_returns: list[float]
    ) -> HypothesisTest:
        n1, n2 = min(len(returns), len(bench_returns)), min(len(returns), len(bench_returns))
        r1, r2 = returns[-n1:], bench_returns[-n2:]
        m1, m2 = statistics.mean(r1), statistics.mean(r2)
        s1 = statistics.stdev(r1) if n1 > 1 else 1e-9
        s2 = statistics.stdev(r2) if n2 > 1 else 1e-9
        se = math.sqrt(s1 ** 2 / n1 + s2 ** 2 / n2)
        t_stat = (m1 - m2) / se if se else 0
        p_val = self._p_value_normal(t_stat)
        sig = p_val < ALPHA
        diff_ann = (m1 - m2) * 252 * 100
        conclusion = (
            f"{symbol} significantly outperforms {BENCHMARK} by {diff_ann:+.1f}% annualized"
            if sig and m1 > m2 else
            f"{symbol} significantly underperforms {BENCHMARK} by {diff_ann:+.1f}% annualized"
            if sig else
            f"no significant mean return difference vs {BENCHMARK}"
        )
        return HypothesisTest(
            test_id="two_sample_ttest",
            symbol=symbol,
            hypothesis=f"H₀: μ_{symbol} = μ_{BENCHMARK}",
            statistic=round(t_stat, 4),
            p_value=round(p_val, 4),
            significant=sig,
            conclusion=conclusion,
            sample_size=n1,
        )

    def _confidence_interval(self, symbol: str, returns: list[float]) -> ConfidenceInterval:
        n = len(returns)
        mean = statistics.mean(returns)
        stdev = statistics.stdev(returns) if n > 1 else 0
        tcrit = self._t_critical(n - 1)
        margin = tcrit * stdev / math.sqrt(n)
        return ConfidenceInterval(
            symbol=symbol,
            metric="daily_mean_return",
            point_estimate=round(mean * 100, 4),
            ci_low=round((mean - margin) * 100, 4),
            ci_high=round((mean + margin) * 100, 4),
            confidence_level=0.95,
        )

    def _ols_regression(
        self, symbol: str, returns: list[float], bench_returns: list[float]
    ) -> RegressionResult | None:
        n = min(len(returns), len(bench_returns))
        if n < 30:
            return None
        y = returns[-n:]
        x = bench_returns[-n:]
        mx, my = statistics.mean(x), statistics.mean(y)
        var_x = statistics.variance(x)
        if var_x == 0:
            return None
        cov_xy = sum((x[i] - mx) * (y[i] - my) for i in range(n)) / (n - 1)
        beta = cov_xy / var_x
        alpha = my - beta * mx

        residuals = [y[i] - (alpha + beta * x[i]) for i in range(n)]
        ss_res = sum(r ** 2 for r in residuals)
        ss_tot = sum((y[i] - my) ** 2 for i in range(n))
        r2 = 1 - ss_res / ss_tot if ss_tot else 0

        mse = ss_res / (n - 2) if n > 2 else 1e-9
        sum_x_dev = sum((xi - mx) ** 2 for xi in x)
        se_beta = math.sqrt(mse / sum_x_dev) if sum_x_dev else 1e-9
        t_beta = beta / se_beta if se_beta else 0
        p_beta = self._p_value_normal(t_beta)
        sig = p_beta < ALPHA

        if beta > 1.2 and sig:
            interp = f"high-beta exposure ({beta:.2f}) — amplifies market moves"
        elif beta < 0.8 and sig:
            interp = f"low-beta defensive ({beta:.2f}) — decoupled from benchmark"
        elif sig:
            interp = f"market-like beta ({beta:.2f}) with significant systematic exposure"
        else:
            interp = f"beta {beta:.2f} not statistically distinguishable from zero slope noise"

        return RegressionResult(
            symbol=symbol,
            benchmark=BENCHMARK,
            alpha_daily=round(alpha * 100, 4),
            beta=round(beta, 4),
            r_squared=round(r2, 4),
            slope_se=round(se_beta, 6),
            slope_t_stat=round(t_beta, 4),
            slope_p_value=round(p_beta, 4),
            significant_beta=sig,
            interpretation=interp,
        )

    def _autocorrelation(self, symbol: str, returns: list[float], lag: int = 1) -> AutocorrelationResult:
        n = len(returns)
        if n < lag + 20:
            return AutocorrelationResult(
                symbol=symbol, lag=lag, autocorr=0, t_stat=0, p_value=1,
                significant=False, interpretation="insufficient data",
            )
        r1 = returns[lag:]
        r0 = returns[:-lag]
        m0, m1 = statistics.mean(r0), statistics.mean(r1)
        num = sum((r0[i] - m0) * (r1[i] - m1) for i in range(len(r0)))
        den0 = math.sqrt(sum((x - m0) ** 2 for x in r0))
        den1 = math.sqrt(sum((x - m1) ** 2 for x in r1))
        rho = num / (den0 * den1) if den0 and den1 else 0
        se_rho = 1 / math.sqrt(n)
        t_stat = rho / se_rho
        p_val = self._p_value_normal(t_stat)
        sig = p_val < ALPHA

        if sig and rho > 0:
            interp = f"significant positive autocorrelation (ρ₁={rho:.3f}) — momentum persistence"
        elif sig and rho < 0:
            interp = f"significant negative autocorrelation (ρ₁={rho:.3f}) — mean-reversion tendency"
        else:
            interp = f"no significant serial correlation (ρ₁={rho:.3f}) — weak form efficiency"

        return AutocorrelationResult(
            symbol=symbol,
            lag=lag,
            autocorr=round(rho, 4),
            t_stat=round(t_stat, 4),
            p_value=round(p_val, 4),
            significant=sig,
            interpretation=interp,
        )

    @staticmethod
    def _skewness(vals: list[float]) -> float:
        n = len(vals)
        if n < 3:
            return 0.0
        m = statistics.mean(vals)
        s = statistics.stdev(vals)
        if s == 0:
            return 0.0
        return sum(((x - m) / s) ** 3 for x in vals) / n

    @staticmethod
    def _excess_kurtosis(vals: list[float]) -> float:
        n = len(vals)
        if n < 4:
            return 0.0
        m = statistics.mean(vals)
        s = statistics.stdev(vals)
        if s == 0:
            return 0.0
        return sum(((x - m) / s) ** 4 for x in vals) / n - 3.0

    def _jarque_bera(self, symbol: str, returns: list[float]) -> NormalityResult:
        n = len(returns)
        s = self._skewness(returns)
        k = self._excess_kurtosis(returns)
        jb = (n / 6) * (s ** 2 + k ** 2 / 4)
        # JB ~ chi-squared(2) under H0; approximate p-value
        p_val = math.exp(-jb / 2) if jb < 20 else 0.0001
        normal = p_val >= ALPHA

        if not normal and k > 1:
            interp = f"non-normal with fat tails (excess kurtosis {k:+.2f}) — tail risk elevated"
        elif not normal and abs(s) > 0.8:
            interp = f"non-normal with skew ({s:+.2f}) — asymmetric return distribution"
        elif normal:
            interp = "returns consistent with normal distribution (JB test)"
        else:
            interp = "mild departure from normality"

        return NormalityResult(
            symbol=symbol,
            skewness=round(s, 3),
            excess_kurtosis=round(k, 3),
            jarque_bera=round(jb, 3),
            jb_p_value=round(p_val, 4),
            normal=normal,
            interpretation=interp,
        )

    def _f_test_variance(
        self, sym_a: str, returns_a: list[float], sym_b: str, returns_b: list[float]
    ) -> VarianceTest | None:
        n = min(len(returns_a), len(returns_b))
        if n < 30:
            return None
        a, b = returns_a[-n:], returns_b[-n:]
        var_a = statistics.variance(a)
        var_b = statistics.variance(b)
        if var_b == 0:
            return None
        f_stat = var_a / var_b if var_a >= var_b else var_b / var_a
        # Approximate two-tailed p using F ~ 1 for equal variances
        log_f = math.log(f_stat)
        p_val = 2 * (1 - self._norm_cdf(abs(log_f) / 0.5))
        sig = p_val < ALPHA and f_stat > 1.3
        higher = sym_a if var_a >= var_b else sym_b
        interp = (
            f"{higher} has significantly higher variance (F={f_stat:.2f})"
            if sig else
            f"variances not significantly different (F={f_stat:.2f})"
        )
        return VarianceTest(
            symbol_a=sym_a,
            symbol_b=sym_b,
            f_statistic=round(f_stat, 4),
            p_value=round(min(p_val, 1.0), 4),
            significant=sig,
            interpretation=interp,
        )

    def _findings(
        self,
        tests: list[HypothesisTest],
        regressions: list[RegressionResult],
        autocorrs: list[AutocorrelationResult],
        normality: list[NormalityResult],
    ) -> list[ResearchFinding]:
        findings: list[ResearchFinding] = []

        for t in tests:
            if t.significant and t.test_id == "one_sample_ttest":
                findings.append(ResearchFinding(
                    title=f"Significant drift in {t.symbol}",
                    method="one_sample_ttest",
                    symbols=[t.symbol],
                    statistic=t.statistic,
                    p_value=t.p_value,
                    significant=True,
                    practical_implication=t.conclusion,
                ))

        for r in regressions:
            if r.significant_beta and r.beta > 1.1:
                findings.append(ResearchFinding(
                    title=f"High-beta systematic risk — {r.symbol}",
                    method="ols_regression",
                    symbols=[r.symbol, r.benchmark],
                    statistic=r.beta,
                    p_value=r.slope_p_value,
                    significant=True,
                    practical_implication=r.interpretation,
                ))
            elif r.significant_beta and r.alpha_daily > 0.02:
                findings.append(ResearchFinding(
                    title=f"Positive alpha estimate — {r.symbol}",
                    method="ols_regression",
                    symbols=[r.symbol],
                    statistic=r.alpha_daily,
                    p_value=r.slope_p_value,
                    significant=True,
                    practical_implication=f"Daily alpha {r.alpha_daily:+.3f}% after beta adjustment",
                ))

        for a in autocorrs:
            if a.significant:
                findings.append(ResearchFinding(
                    title=f"Serial correlation in {a.symbol}",
                    method="autocorrelation",
                    symbols=[a.symbol],
                    statistic=a.autocorr,
                    p_value=a.p_value,
                    significant=True,
                    practical_implication=a.interpretation,
                ))

        for n in normality:
            if not n.normal and n.excess_kurtosis > 1.5:
                findings.append(ResearchFinding(
                    title=f"Fat tails in {n.symbol} returns",
                    method="jarque_bera",
                    symbols=[n.symbol],
                    statistic=n.jarque_bera,
                    p_value=n.jb_p_value,
                    significant=True,
                    practical_implication=n.interpretation,
                ))

        findings.sort(key=lambda f: f.p_value)
        return findings[:10]

    def _assessment(
        self,
        tests: list[HypothesisTest],
        regressions: list[RegressionResult],
        autocorrs: list[AutocorrelationResult],
        normality: list[NormalityResult],
        variance_tests: list[VarianceTest],
        findings: list[ResearchFinding],
    ) -> ResearchAssessment:
        spy_drift = next(
            (t for t in tests if t.symbol == BENCHMARK and t.test_id == "one_sample_ttest"),
            None,
        )
        if spy_drift and spy_drift.significant:
            drift_sig = spy_drift.conclusion
        elif spy_drift:
            drift_sig = "SPY: no statistically significant drift from zero (fail to reject H₀)"
        else:
            drift_sig = "drift test unavailable"

        sig_reg = [r for r in regressions if r.significant_beta]
        if sig_reg:
            top = max(sig_reg, key=lambda r: abs(r.beta - 1))
            reg_sig = f"{top.symbol} β={top.beta:.2f} (R²={top.r_squared:.2f}, p={top.slope_p_value:.3f}) — {top.interpretation}"
        else:
            reg_sig = "no significant regression slopes detected"

        sig_ac = [a for a in autocorrs if a.significant]
        if sig_ac:
            serial_sig = "; ".join(a.interpretation for a in sig_ac[:2])
        else:
            serial_sig = "returns show no significant serial correlation — consistent with weak-form efficiency"

        non_normal = [n for n in normality if not n.normal]
        if non_normal:
            norm_sig = f"{len(non_normal)}/{len(normality)} assets reject normality — " + non_normal[0].interpretation
        else:
            norm_sig = "return distributions consistent with normality (JB tests)"

        sig_var = [v for v in variance_tests if v.significant]
        if sig_var:
            vol_sig = sig_var[0].interpretation
        else:
            vol_sig = "no significant variance differences vs benchmark"

        sig_count = sum(1 for f in findings if f.significant)
        if sig_count >= 4:
            research_conc = f"{sig_count} statistically significant findings at α={ALPHA} — robust evidence for active research"
        elif sig_count >= 2:
            research_conc = f"{sig_count} significant findings — selective statistical evidence"
        else:
            research_conc = "limited significant findings — markets largely consistent with null hypotheses"

        if findings:
            edge = findings[0].practical_implication
        else:
            edge = "no statistically significant edge detected at α=0.05"

        return ResearchAssessment(
            drift_signal=drift_sig,
            regression_signal=reg_sig,
            serial_correlation_signal=serial_sig,
            normality_signal=norm_sig,
            volatility_signal=vol_sig,
            research_conclusion=research_conc,
            statistical_edge=edge,
        )

    def _expert_summary(
        self,
        assessment: ResearchAssessment,
        label: str,
        sig_score: float,
        finding_count: int,
    ) -> str:
        return (
            f"Research statistics scan: {label} (significance score {sig_score:.2f}, "
            f"{finding_count} findings). "
            f"{assessment.drift_signal}. "
            f"{assessment.regression_signal}. "
            f"{assessment.serial_correlation_signal}. "
            f"{assessment.normality_signal}. "
            f"{assessment.volatility_signal}. "
            f"{assessment.research_conclusion}. "
            f"Edge: {assessment.statistical_edge}."
        )

    def analyze(self) -> ResearchStatisticsReport:
        return_map: dict[str, list[float]] = {}

        for symbol in WATCHLIST:
            closes = self._fetch_closes(symbol)
            if closes:
                return_map[symbol] = self._daily_returns(closes)
            time.sleep(self.delay_seconds)

        if BENCHMARK not in return_map:
            raise RuntimeError("Unable to fetch SPY data for research statistics analysis")

        bench = return_map[BENCHMARK]
        hypothesis_tests: list[HypothesisTest] = []
        confidence_intervals: list[ConfidenceInterval] = []
        regressions: list[RegressionResult] = []
        autocorrelations: list[AutocorrelationResult] = []
        normality_tests: list[NormalityResult] = []
        variance_tests: list[VarianceTest] = []

        for symbol, returns in return_map.items():
            hypothesis_tests.append(self._one_sample_ttest(symbol, returns))
            confidence_intervals.append(self._confidence_interval(symbol, returns))
            autocorrelations.append(self._autocorrelation(symbol, returns))
            normality_tests.append(self._jarque_bera(symbol, returns))
            if symbol != BENCHMARK:
                hypothesis_tests.append(self._two_sample_ttest(symbol, returns, bench))
                reg = self._ols_regression(symbol, returns, bench)
                if reg:
                    regressions.append(reg)
                vt = self._f_test_variance(symbol, returns, BENCHMARK, bench)
                if vt:
                    variance_tests.append(vt)

        findings = self._findings(hypothesis_tests, regressions, autocorrelations, normality_tests)
        assessment = self._assessment(
            hypothesis_tests, regressions, autocorrelations,
            normality_tests, variance_tests, findings,
        )

        sig_count = sum(1 for f in findings if f.significant)
        total_tests = len(hypothesis_tests) + len(regressions) + len(autocorrelations)
        sig_tests = sum(1 for t in hypothesis_tests if t.significant)
        significance_score = round(
            0.4 * (sig_count / max(len(findings), 1))
            + 0.3 * (sig_tests / max(len(hypothesis_tests), 1))
            + 0.3 * min(1.0, len(return_map[BENCHMARK]) / 200),
            4,
        )
        research_quality = round(
            0.5 * min(1.0, len(bench) / 200)
            + 0.5 * (1.0 if sig_count >= 2 else 0.4),
            4,
        )

        if significance_score >= 0.55 and sig_count >= 3:
            regime_label = "Statistically Significant"
        elif significance_score >= 0.45:
            regime_label = "Mixed Statistical Evidence"
        else:
            regime_label = "Null Hypothesis Dominant"

        summary = self._expert_summary(assessment, regime_label, significance_score, sig_count)
        signals = self._market_signals(findings, regressions, hypothesis_tests, autocorrelations)
        recs = self._recommendations(
            assessment, hypothesis_tests, confidence_intervals,
            regressions, autocorrelations, normality_tests,
            variance_tests, findings,
        )

        return ResearchStatisticsReport(
            hypothesis_tests=hypothesis_tests,
            confidence_intervals=confidence_intervals,
            regressions=regressions,
            autocorrelations=autocorrelations,
            normality_tests=normality_tests,
            variance_tests=variance_tests,
            findings=findings,
            assessment=assessment,
            significance_score=significance_score,
            research_quality_score=research_quality,
            regime_label=regime_label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source="Yahoo Finance API",
        )

    @staticmethod
    def _market_signals(
        findings: list[ResearchFinding],
        regressions: list[RegressionResult],
        tests: list[HypothesisTest],
        autocorrs: list[AutocorrelationResult],
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        spy_test = next(
            (t for t in tests if t.symbol == BENCHMARK and t.test_id == "one_sample_ttest"),
            None,
        )
        if spy_test:
            bias = (
                "BULLISH" if spy_test.significant and spy_test.statistic > 0 else
                "BEARISH" if spy_test.significant and spy_test.statistic < 0 else
                "NEUTRAL"
            )
            signals.append({
                "sector": "Drift Hypothesis Test",
                "tickers": ["SPY", "VOO"],
                "bias": bias,
                "reason": f"H₀: μ=0, t={spy_test.statistic:.2f}, p={spy_test.p_value:.3f}",
            })

        for f in findings[:3]:
            bias = "BULLISH" if "outperform" in f.practical_implication or "positive" in f.practical_implication.lower() or "momentum" in f.practical_implication.lower() else (
                "BEARISH" if "underperform" in f.practical_implication or "negative" in f.practical_implication.lower() or "fat tail" in f.practical_implication.lower() else
                "NEUTRAL"
            )
            signals.append({
                "sector": f"Research Finding — {f.title}",
                "tickers": f.symbols,
                "bias": bias,
                "reason": f"{f.method}: stat={f.statistic:.3f}, p={f.p_value:.3f}",
            })

        for r in regressions:
            if r.significant_beta and r.beta > 1.15:
                signals.append({
                    "sector": f"High Beta — {r.symbol}",
                    "tickers": [r.symbol],
                    "bias": "BULLISH",
                    "reason": f"β={r.beta:.2f}, R²={r.r_squared:.2f}, p={r.slope_p_value:.3f}",
                })

        for a in autocorrs:
            if a.significant and a.autocorr < -0.05:
                signals.append({
                    "sector": f"Mean Reversion — {a.symbol}",
                    "tickers": [a.symbol],
                    "bias": "BULLISH",
                    "reason": f"ρ₁={a.autocorr:.3f}, p={a.p_value:.3f}",
                })

        if not signals:
            signals.append({
                "sector": "Research Neutral",
                "tickers": ["SPY"],
                "bias": "NEUTRAL",
                "reason": "No significant findings at α=0.05",
            })
        return signals

    @staticmethod
    def _recommendations(
        assessment: ResearchAssessment,
        tests: list[HypothesisTest],
        cis: list[ConfidenceInterval],
        regressions: list[RegressionResult],
        autocorrs: list[AutocorrelationResult],
        normality: list[NormalityResult],
        variance_tests: list[VarianceTest],
        findings: list[ResearchFinding],
    ) -> list[str]:
        recs = [
            assessment.drift_signal,
            assessment.regression_signal,
            assessment.serial_correlation_signal,
            assessment.normality_signal,
            assessment.volatility_signal,
            assessment.research_conclusion,
            assessment.statistical_edge,
        ]
        for t in [x for x in tests if x.significant][:4]:
            recs.append(
                f"{t.symbol} {t.test_id}: t={t.statistic:.3f}, p={t.p_value:.4f} — {t.conclusion}"
            )
        spy_ci = next((c for c in cis if c.symbol == BENCHMARK), None)
        if spy_ci:
            recs.append(
                f"SPY 95% CI for daily mean: [{spy_ci.ci_low:.3f}%, {spy_ci.ci_high:.3f}%]"
            )
        for r in sorted(regressions, key=lambda x: -x.r_squared)[:4]:
            recs.append(
                f"{r.symbol} vs {r.benchmark}: α={r.alpha_daily:+.4f}%/day, β={r.beta:.2f}, "
                f"R²={r.r_squared:.2f}, p(β)={r.slope_p_value:.3f}"
            )
        for a in autocorrs:
            if a.significant:
                recs.append(f"{a.symbol} lag-{a.lag} autocorr: ρ={a.autocorr:.3f}, p={a.p_value:.3f}")
        for n in normality:
            if not n.normal:
                recs.append(
                    f"{n.symbol} normality rejected: JB={n.jarque_bera:.2f}, "
                    f"skew={n.skewness:+.2f}, kurtosis={n.excess_kurtosis:+.2f}"
                )
        for v in variance_tests:
            if v.significant:
                recs.append(f"{v.symbol_a} vs {v.symbol_b} variance: F={v.f_statistic:.2f}, p={v.p_value:.3f}")
        for f in findings[:5]:
            recs.append(f"Finding: {f.title} — {f.practical_implication} (p={f.p_value:.3f})")
        return recs

    def to_dict(self, report: ResearchStatisticsReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Research Statistics Expert",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "alpha_level": ALPHA,
                "expert_summary": report.expert_summary,
                "methods_applied": [m["id"] for m in STATISTICAL_METHODS],
            },
            "statistical_methods": STATISTICAL_METHODS,
            "hypothesis_tests": [
                {
                    "test_id": t.test_id,
                    "symbol": t.symbol,
                    "hypothesis": t.hypothesis,
                    "statistic": t.statistic,
                    "p_value": t.p_value,
                    "significant": t.significant,
                    "conclusion": t.conclusion,
                    "sample_size": t.sample_size,
                }
                for t in report.hypothesis_tests
            ],
            "confidence_intervals": [
                {
                    "symbol": c.symbol,
                    "metric": c.metric,
                    "point_estimate": c.point_estimate,
                    "ci_low": c.ci_low,
                    "ci_high": c.ci_high,
                    "confidence_level": c.confidence_level,
                }
                for c in report.confidence_intervals
            ],
            "regressions": [
                {
                    "symbol": r.symbol,
                    "benchmark": r.benchmark,
                    "alpha_daily": r.alpha_daily,
                    "beta": r.beta,
                    "r_squared": r.r_squared,
                    "slope_t_stat": r.slope_t_stat,
                    "slope_p_value": r.slope_p_value,
                    "significant_beta": r.significant_beta,
                    "interpretation": r.interpretation,
                }
                for r in report.regressions
            ],
            "autocorrelations": [
                {
                    "symbol": a.symbol,
                    "lag": a.lag,
                    "autocorr": a.autocorr,
                    "t_stat": a.t_stat,
                    "p_value": a.p_value,
                    "significant": a.significant,
                    "interpretation": a.interpretation,
                }
                for a in report.autocorrelations
            ],
            "normality_tests": [
                {
                    "symbol": n.symbol,
                    "skewness": n.skewness,
                    "excess_kurtosis": n.excess_kurtosis,
                    "jarque_bera": n.jarque_bera,
                    "jb_p_value": n.jb_p_value,
                    "normal": n.normal,
                    "interpretation": n.interpretation,
                }
                for n in report.normality_tests
            ],
            "variance_tests": [
                {
                    "symbol_a": v.symbol_a,
                    "symbol_b": v.symbol_b,
                    "f_statistic": v.f_statistic,
                    "p_value": v.p_value,
                    "significant": v.significant,
                    "interpretation": v.interpretation,
                }
                for v in report.variance_tests
            ],
            "research_findings": [
                {
                    "title": f.title,
                    "method": f.method,
                    "symbols": f.symbols,
                    "statistic": f.statistic,
                    "p_value": f.p_value,
                    "significant": f.significant,
                    "practical_implication": f.practical_implication,
                }
                for f in report.findings
            ],
            "research_assessment": {
                "drift_signal": a.drift_signal,
                "regression_signal": a.regression_signal,
                "serial_correlation_signal": a.serial_correlation_signal,
                "normality_signal": a.normality_signal,
                "volatility_signal": a.volatility_signal,
                "research_conclusion": a.research_conclusion,
                "statistical_edge": a.statistical_edge,
            },
            "metrics": {
                "significance_score": report.significance_score,
                "research_quality_score": report.research_quality_score,
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
            catalog = output.parent / "statistical_methods.json"
            catalog.write_text(
                json.dumps(STATISTICAL_METHODS, indent=2),
                encoding="utf-8",
            )
        return result


def run_research_statistics_analysis(output: Path | None = None) -> dict[str, Any]:
    return ResearchStatisticsExpert().run(output=output)