"""
Correlation Breakdown / Tail-Risk Expert Agent
===============================================
Quantitative risk analyst covering "correlation breakdown" — the tendency
of historically uncorrelated assets to converge toward r ≈ 1.0 during
systemic liquidity shocks, eliminating diversification benefits exactly
when they are needed most.

Covers:
  * Calm-vs-stress pairwise correlation convergence (proxy for copula
    lower-tail dependence — Student-t / Clayton copula frameworks)
  * Historical CVaR / Expected Shortfall (tail loss beyond VaR)
  * A two-state (calm / panicked) regime-switching proxy driven by VIX,
    with an empirical regime-persistence and switch probability
  * Structural portfolio-protection playbook (long volatility, trend
    following / CTA, tail-risk budgeting)

Data: Yahoo Finance chart API (1-year daily history).
Reference: https://www.investopedia.com/ray-dalio-on-surviving-market-crashes-11699830
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

from agent_signal_logic import build_market_signal, quant_signal_confidence
from agents.base import BaseExpert

BENCHMARK = "SPY"
VIX_SYMBOL = "^VIX"
VIX_PANIC_THRESHOLD = 20.0
STRESS_TAIL_FRACTION = 0.15  # worst 15% of SPY return days = "stress" regime
REFERENCE_URL = "https://www.investopedia.com/ray-dalio-on-surviving-market-crashes-11699830"

WATCHLIST = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "AAPL": "Apple",
    "GLD": "Gold",
    "TLT": "Long Treasuries",
    "BTC-USD": "Bitcoin",
    "HYG": "High Yield Credit",
}

TAIL_RISK_FRAMEWORKS: list[dict[str, Any]] = [
    {
        "id": "copulas",
        "name": "Copulas (Student-t / Clayton)",
        "description": (
            "Join separate marginal return distributions into a single multivariate "
            "distribution, isolating lower-tail dependence — the probability an asset "
            "crashes given another asset has already crashed — instead of assuming a "
            "single static correlation."
        ),
    },
    {
        "id": "cvar",
        "name": "Conditional Value at Risk (Expected Shortfall)",
        "description": (
            "While VaR answers 'what is my max loss at X% confidence', CVaR answers "
            "'what is the expected average loss inside that worst-case tail', dynamically "
            "capturing losses generated when correlations spike during a collapse."
        ),
    },
    {
        "id": "regime_switching",
        "name": "Regime-Switching (Markov) Models",
        "description": (
            "Treats markets as two latent states — Regime 0 (low volatility / normal "
            "correlation) and Regime 1 (high volatility / panicked correlation) — with a "
            "Markov chain governing the probability of switching from calm to crash."
        ),
    },
]

PROTECTION_STRATEGIES: list[dict[str, Any]] = [
    {
        "id": "long_volatility",
        "name": "Long Volatility Options",
        "description": "Out-of-the-money puts on major indices capture explicit gains when volatility spikes.",
    },
    {
        "id": "trend_following",
        "name": "Trend Following / CTA",
        "description": "Systematic CTA frameworks rapidly short equities and go long safe-haven bonds as macro trends break down.",
    },
    {
        "id": "tail_risk_budgeting",
        "name": "Tail-Risk Budgeting",
        "description": "Allocate a fixed 1%-3% annual premium budget to insurance assets that appreciate during systemic liquidations.",
    },
]


@dataclass
class CorrelationRegimePair:
    symbol: str
    name: str
    calm_correlation: float | None
    stress_correlation: float | None
    delta: float | None
    convergence_flag: bool
    label: str


@dataclass
class TailRiskMetric:
    symbol: str
    name: str
    var_95_pct: float
    cvar_95_pct: float
    cvar_99_pct: float
    excess_kurtosis: float
    fat_tail_flag: bool


@dataclass
class RegimeState:
    current_regime: int
    regime_label: str
    vix_level: float | None
    days_in_current_regime: int
    calm_persistence_prob: float
    panic_persistence_prob: float
    calm_to_panic_switch_prob: float


@dataclass
class TailRiskAssessment:
    diversification_signal: str
    correlation_breakdown_signal: str
    tail_risk_regime: str
    protection_posture: str
    expert_conclusion: str


@dataclass
class CorrelationBreakdownReport:
    correlation_pairs: list[CorrelationRegimePair]
    tail_metrics: list[TailRiskMetric]
    regime: RegimeState
    assessment: TailRiskAssessment
    correlation_convergence_score: float
    tail_risk_score: float
    diversification_score: float
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CorrelationBreakdownExpert(BaseExpert):
    """Quantitative risk analyst — correlation breakdown, CVaR, and regime switching."""

    def __init__(
        self,
        delay_seconds: float = 0.35,
        *,
        pipeline_context: dict | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="correlation-breakdown")
        self.delay_seconds = delay_seconds
        self.watchlist = dict(WATCHLIST)

    def _fetch_closes(self, symbol: str, *, range_: str = "1y") -> list[float]:
        return self.fetch_yahoo_closes(symbol, range_=range_, interval="1d")

    @staticmethod
    def _log_returns(prices: list[float]) -> list[float]:
        return [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]

    @staticmethod
    def _pearson(a: list[float], b: list[float]) -> float | None:
        n = min(len(a), len(b))
        if n < 10:
            return None
        a_tail, b_tail = a[-n:], b[-n:]
        ma, mb = statistics.mean(a_tail), statistics.mean(b_tail)
        num = sum((a_tail[i] - ma) * (b_tail[i] - mb) for i in range(n))
        da = math.sqrt(sum((x - ma) ** 2 for x in a_tail))
        db = math.sqrt(sum((x - mb) ** 2 for x in b_tail))
        if da == 0 or db == 0:
            return None
        return round(num / (da * db), 3)

    @staticmethod
    def _excess_kurtosis(vals: list[float]) -> float:
        n = len(vals)
        if n < 4:
            return 0.0
        m = statistics.mean(vals)
        s = statistics.stdev(vals)
        if s == 0:
            return 0.0
        return round(sum(((x - m) / s) ** 4 for x in vals) / n - 3.0, 3)

    @staticmethod
    def _stress_indices(bench_returns: list[float]) -> tuple[set[int], set[int]]:
        """Split return-day indices into calm vs stress (worst-tail SPY days)."""
        n = len(bench_returns)
        if n < 20:
            return set(range(n)), set()
        k = max(5, int(round(n * STRESS_TAIL_FRACTION)))
        order = sorted(range(n), key=lambda i: bench_returns[i])
        stress = set(order[:k])
        calm = set(range(n)) - stress
        return calm, stress

    def _correlation_pair(
        self,
        symbol: str,
        name: str,
        returns: list[float],
        bench_returns: list[float],
        calm_idx: set[int],
        stress_idx: set[int],
    ) -> CorrelationRegimePair:
        n = min(len(returns), len(bench_returns))
        r, b = returns[-n:], bench_returns[-n:]
        calm = sorted(i for i in calm_idx if i < n)
        stress = sorted(i for i in stress_idx if i < n)
        calm_corr = self._pearson([r[i] for i in calm], [b[i] for i in calm]) if len(calm) >= 10 else None
        stress_corr = self._pearson([r[i] for i in stress], [b[i] for i in stress]) if len(stress) >= 8 else None
        delta = None
        convergence = False
        label = "insufficient data"
        if calm_corr is not None and stress_corr is not None:
            delta = round(stress_corr - calm_corr, 3)
            convergence = stress_corr >= 0.75 and delta >= 0.20
            if convergence:
                label = "correlation breakdown — diversification failing"
            elif stress_corr >= 0.6:
                label = "elevated stress correlation"
            else:
                label = "diversification holding"
        return CorrelationRegimePair(
            symbol=symbol,
            name=name,
            calm_correlation=calm_corr,
            stress_correlation=stress_corr,
            delta=delta,
            convergence_flag=convergence,
            label=label,
        )

    @staticmethod
    def _var_cvar(returns: list[float], confidence: float) -> tuple[float, float]:
        """Historical-simulation VaR and CVaR (Expected Shortfall) as % loss."""
        if len(returns) < 20:
            return 0.0, 0.0
        ordered = sorted(returns)
        cutoff = max(1, int(round(len(ordered) * (1 - confidence))))
        tail = ordered[:cutoff]
        var_pct = round(-tail[-1] * 100, 2)
        cvar_pct = round(-statistics.mean(tail) * 100, 2)
        return var_pct, cvar_pct

    def _tail_metric(self, symbol: str, name: str, returns: list[float]) -> TailRiskMetric:
        var95, cvar95 = self._var_cvar(returns, 0.95)
        _, cvar99 = self._var_cvar(returns, 0.99)
        kurt = self._excess_kurtosis(returns[-120:]) if len(returns) >= 30 else 0.0
        return TailRiskMetric(
            symbol=symbol,
            name=name,
            var_95_pct=var95,
            cvar_95_pct=cvar95,
            cvar_99_pct=cvar99,
            excess_kurtosis=kurt,
            fat_tail_flag=kurt > 1.0,
        )

    @staticmethod
    def _regime_state(vix_closes: list[float]) -> RegimeState:
        if len(vix_closes) < 20:
            return RegimeState(
                current_regime=0,
                regime_label="unknown (insufficient VIX data)",
                vix_level=vix_closes[-1] if vix_closes else None,
                days_in_current_regime=0,
                calm_persistence_prob=0.0,
                panic_persistence_prob=0.0,
                calm_to_panic_switch_prob=0.0,
            )
        states = [1 if v >= VIX_PANIC_THRESHOLD else 0 for v in vix_closes]
        calm_to_calm = calm_to_panic = panic_to_panic = panic_to_calm = 0
        for i in range(1, len(states)):
            prev, cur = states[i - 1], states[i]
            if prev == 0 and cur == 0:
                calm_to_calm += 1
            elif prev == 0 and cur == 1:
                calm_to_panic += 1
            elif prev == 1 and cur == 1:
                panic_to_panic += 1
            else:
                panic_to_calm += 1
        calm_total = calm_to_calm + calm_to_panic
        panic_total = panic_to_panic + panic_to_calm
        calm_persist = round(calm_to_calm / calm_total, 3) if calm_total else 0.0
        panic_persist = round(panic_to_panic / panic_total, 3) if panic_total else 0.0
        switch_prob = round(calm_to_panic / calm_total, 3) if calm_total else 0.0
        current = states[-1]
        days_in_regime = 1
        for i in range(len(states) - 2, -1, -1):
            if states[i] == current:
                days_in_regime += 1
            else:
                break
        return RegimeState(
            current_regime=current,
            regime_label="Regime 1 — panicked / high correlation" if current == 1 else "Regime 0 — calm / normal correlation",
            vix_level=round(vix_closes[-1], 2),
            days_in_current_regime=days_in_regime,
            calm_persistence_prob=calm_persist,
            panic_persistence_prob=panic_persist,
            calm_to_panic_switch_prob=switch_prob,
        )

    @staticmethod
    def _assessment(
        pairs: list[CorrelationRegimePair],
        regime: RegimeState,
        tail_metrics: list[TailRiskMetric],
    ) -> TailRiskAssessment:
        convergent = [p for p in pairs if p.convergence_flag]
        if len(convergent) >= max(1, len(pairs) // 2):
            div_signal = "diversification impaired — majority of assets converging toward SPY in stress windows"
        elif convergent:
            div_signal = "partial correlation breakdown — some assets losing independence under stress"
        else:
            div_signal = "diversification structurally intact across the watchlist"

        if regime.current_regime == 1:
            corr_signal = f"currently in {regime.regime_label} ({regime.days_in_current_regime}d)"
        else:
            corr_signal = (
                f"currently in {regime.regime_label}; "
                f"{regime.calm_to_panic_switch_prob:.0%} historical odds of switching to panic on any given day"
            )

        fat_tails = [m for m in tail_metrics if m.fat_tail_flag]
        tail_regime = (
            f"fat-tailed (leptokurtic) return distributions detected in {len(fat_tails)}/{len(tail_metrics)} assets — "
            "Gaussian VaR likely understates crash risk"
            if fat_tails
            else "return distributions broadly consistent with near-normal tails"
        )

        posture = (
            "raise tail-risk budget (1-3% premium to long-volatility/put hedges) and trend-following overlays"
            if regime.current_regime == 1 or convergent
            else "maintain modest tail-risk budget; monitor for stress-correlation convergence"
        )

        conclusion = (
            f"{div_signal}. {tail_regime}. Regime: {corr_signal}."
        )
        return TailRiskAssessment(
            diversification_signal=div_signal,
            correlation_breakdown_signal=(
                "breakdown detected" if convergent else "no breakdown detected"
            ),
            tail_risk_regime=tail_regime,
            protection_posture=posture,
            expert_conclusion=conclusion,
        )

    def _market_signals(
        self,
        pairs: list[CorrelationRegimePair],
        regime: RegimeState,
        tail_metrics: list[TailRiskMetric],
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        convergent = [p for p in pairs if p.convergence_flag]
        if convergent:
            symbols = [p.symbol for p in convergent]
            signals.append(
                build_market_signal(
                    sector="Correlation Breakdown",
                    tickers=symbols,
                    bias="BEARISH",
                    reason=(
                        f"{len(convergent)} asset(s) converging toward SPY under stress "
                        f"(stress ρ up to {max(p.stress_correlation or 0 for p in convergent):+.2f})"
                    ),
                    confidence=self.adjust_signal_confidence(
                        symbols[0],
                        "BEARISH",
                        quant_signal_confidence(momentum=0.5, stress=abs(regime.calm_to_panic_switch_prob) + 0.2),
                    ),
                )
            )
        if regime.current_regime == 1:
            signals.append(
                build_market_signal(
                    sector="Volatility Regime",
                    tickers=["VIX", "SPY", "TLT"],
                    bias="BEARISH",
                    reason=f"VIX {regime.vix_level} — panicked regime, {regime.panic_persistence_prob:.0%} persistence",
                    confidence=self.adjust_signal_confidence(
                        "SPY", "BEARISH", quant_signal_confidence(momentum=0.4, stress=0.7)
                    ),
                )
            )
        fat_tails = [m for m in tail_metrics if m.fat_tail_flag]
        if fat_tails:
            signals.append(
                build_market_signal(
                    sector="Tail Risk",
                    tickers=[m.symbol for m in fat_tails],
                    bias="NEUTRAL",
                    reason=f"Fat-tailed distributions — CVaR95 up to {max(m.cvar_95_pct for m in fat_tails):.2f}%",
                    confidence=self.adjust_signal_confidence(
                        fat_tails[0].symbol, "NEUTRAL", quant_signal_confidence(momentum=0.5, stress=0.5)
                    ),
                )
            )
        if not signals:
            signals.append(
                build_market_signal(
                    sector="Correlation Breakdown",
                    tickers=["SPY"],
                    bias="NEUTRAL",
                    reason="No material correlation convergence or regime-panic signal detected",
                    confidence=self.adjust_signal_confidence("SPY", "NEUTRAL", 0.4),
                )
            )
        return signals

    @staticmethod
    def _recommendations(
        pairs: list[CorrelationRegimePair],
        regime: RegimeState,
        tail_metrics: list[TailRiskMetric],
        assessment: TailRiskAssessment,
    ) -> list[str]:
        recs = [assessment.diversification_signal, assessment.tail_risk_regime, assessment.protection_posture]
        for p in pairs:
            if p.convergence_flag:
                recs.append(
                    f"{p.symbol} ({p.name}): calm ρ={p.calm_correlation:+.2f} → stress ρ={p.stress_correlation:+.2f} "
                    f"(Δ{p.delta:+.2f}) — diversification benefit erodes in a crash"
                )
        worst = sorted(tail_metrics, key=lambda m: m.cvar_95_pct, reverse=True)[:3]
        for m in worst:
            recs.append(f"{m.symbol}: CVaR95 {m.cvar_95_pct:.2f}%, CVaR99 {m.cvar_99_pct:.2f}% — expected shortfall in the tail")
        recs.append(
            f"Regime: {regime.regime_label} (VIX {regime.vix_level}); "
            f"calm→panic switch prob {regime.calm_to_panic_switch_prob:.0%}, panic persistence {regime.panic_persistence_prob:.0%}"
        )
        for strat in PROTECTION_STRATEGIES:
            recs.append(f"{strat['name']}: {strat['description']}")
        return recs

    def analyze(self) -> CorrelationBreakdownReport:
        return_map: dict[str, list[float]] = {}
        for symbol in self.watchlist:
            prices = self._fetch_closes(symbol)
            if len(prices) >= 30:
                return_map[symbol] = self._log_returns(prices)
            time.sleep(self.delay_seconds)

        bench_returns = return_map.get(BENCHMARK)
        if not bench_returns:
            raise RuntimeError("Unable to fetch SPY data for correlation-breakdown analysis")

        calm_idx, stress_idx = self._stress_indices(bench_returns)

        pairs: list[CorrelationRegimePair] = []
        for symbol, name in self.watchlist.items():
            if symbol == BENCHMARK or symbol not in return_map:
                continue
            pairs.append(
                self._correlation_pair(symbol, name, return_map[symbol], bench_returns, calm_idx, stress_idx)
            )

        tail_metrics: list[TailRiskMetric] = [
            self._tail_metric(symbol, self.watchlist[symbol], returns)
            for symbol, returns in return_map.items()
        ]

        vix_closes = self._fetch_closes(VIX_SYMBOL)
        regime = self._regime_state(vix_closes)

        assessment = self._assessment(pairs, regime, tail_metrics)
        signals = self._market_signals(pairs, regime, tail_metrics)
        recs = self.append_memory_recommendations(
            self._recommendations(pairs, regime, tail_metrics, assessment)
        )

        convergent_count = sum(1 for p in pairs if p.convergence_flag)
        convergence_score = round(convergent_count / len(pairs), 3) if pairs else 0.0
        fat_tail_count = sum(1 for m in tail_metrics if m.fat_tail_flag)
        tail_score = round(fat_tail_count / len(tail_metrics), 3) if tail_metrics else 0.0
        diversification_score = round(max(0.0, 1.0 - convergence_score), 3)

        summary = f"Correlation Breakdown Expert: {assessment.expert_conclusion}"

        return CorrelationBreakdownReport(
            correlation_pairs=pairs,
            tail_metrics=tail_metrics,
            regime=regime,
            assessment=assessment,
            correlation_convergence_score=convergence_score,
            tail_risk_score=tail_score,
            diversification_score=diversification_score,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source="Yahoo Finance chart API (1y daily) + VIX regime proxy",
        )

    def to_dict(self, report: CorrelationBreakdownReport) -> dict[str, Any]:
        a = report.assessment
        r = report.regime
        return {
            "meta": {
                "agent": "Correlation Breakdown / Tail-Risk Expert",
                "reference": REFERENCE_URL,
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
            },
            "frameworks": TAIL_RISK_FRAMEWORKS,
            "protection_strategies": PROTECTION_STRATEGIES,
            "assessment": {
                "diversification_signal": a.diversification_signal,
                "correlation_breakdown_signal": a.correlation_breakdown_signal,
                "tail_risk_regime": a.tail_risk_regime,
                "protection_posture": a.protection_posture,
                "expert_conclusion": a.expert_conclusion,
            },
            "regime": {
                "current_regime": r.current_regime,
                "regime_label": r.regime_label,
                "vix_level": r.vix_level,
                "days_in_current_regime": r.days_in_current_regime,
                "calm_persistence_prob": r.calm_persistence_prob,
                "panic_persistence_prob": r.panic_persistence_prob,
                "calm_to_panic_switch_prob": r.calm_to_panic_switch_prob,
            },
            "correlation_pairs": [
                {
                    "symbol": p.symbol,
                    "name": p.name,
                    "calm_correlation": p.calm_correlation,
                    "stress_correlation": p.stress_correlation,
                    "delta": p.delta,
                    "convergence_flag": p.convergence_flag,
                    "label": p.label,
                }
                for p in report.correlation_pairs
            ],
            "tail_metrics": [
                {
                    "symbol": m.symbol,
                    "name": m.name,
                    "var_95_pct": m.var_95_pct,
                    "cvar_95_pct": m.cvar_95_pct,
                    "cvar_99_pct": m.cvar_99_pct,
                    "excess_kurtosis": m.excess_kurtosis,
                    "fat_tail_flag": m.fat_tail_flag,
                }
                for m in report.tail_metrics
            ],
            "metrics": {
                "correlation_convergence_score": report.correlation_convergence_score,
                "tail_risk_score": report.tail_risk_score,
                "diversification_score": report.diversification_score,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "tail_risk_frameworks.json"
            catalog.write_text(
                json.dumps(TAIL_RISK_FRAMEWORKS + PROTECTION_STRATEGIES, indent=2),
                encoding="utf-8",
            )
        return result


def run_correlation_breakdown_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return CorrelationBreakdownExpert(pipeline_context=pipeline_context).run(output=output)
