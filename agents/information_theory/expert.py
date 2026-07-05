"""
Information Theory Expert Agent
===============================
Applies core information-theory tools to market return data: Shannon
entropy (how "random"/efficient a market's return distribution is),
mutual information (shared information / co-movement between an asset and
the benchmark), approximate entropy (signal complexity/regularity), and the
Hurst exponent (long-memory persistence vs mean-reversion via R/S analysis).

This is the concrete, data-driven counterpart to the informational view of
markets: instead of treating price action as an abstract metaphor, every
metric below is computed directly from real daily return series.

Data: Yahoo Finance chart API (1-year daily history).
"""

from __future__ import annotations

import itertools
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
HEADERS = {"User-Agent": "Finance-Information-Theory/1.0 (shaggychunxx@gmail.com)"}

BENCHMARK = "SPY"
ENTROPY_BINS = 10
MI_BINS = 6
APEN_M = 2
HURST_WINDOWS = (10, 20, 40, 80, 120)

WATCHLIST = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "IWM": "Russell 2000",
    "XLK": "Technology",
    "XLE": "Energy",
    "XLU": "Utilities",
    "XLF": "Financials",
    "GLD": "Gold",
    "TLT": "Treasuries",
}

INFORMATION_METHODS: list[dict[str, Any]] = [
    {
        "id": "shannon_entropy",
        "name": "Shannon Entropy of Returns",
        "description": "Measures the unpredictability of the daily-return distribution",
        "formula": "H(X) = -Σ p(xᵢ) log₂ p(xᵢ)",
    },
    {
        "id": "normalized_entropy",
        "name": "Normalized Entropy",
        "description": "Entropy scaled to [0,1] against the maximum entropy for the bin count",
        "formula": "H_norm = H(X) / log₂(K)",
    },
    {
        "id": "mutual_information",
        "name": "Mutual Information vs Benchmark",
        "description": "Shared information between an asset's and SPY's daily returns",
        "formula": "I(X;Y) = Σ p(x,y) log₂ [p(x,y) / (p(x)p(y))]",
    },
    {
        "id": "approximate_entropy",
        "name": "Approximate Entropy (ApEn)",
        "description": "Regularity/complexity of the return series — lower ApEn means more repeatable structure",
        "formula": "ApEn(m,r) = Φᵐ(r) - Φᵐ⁺¹(r)",
    },
    {
        "id": "hurst_exponent",
        "name": "Hurst Exponent (R/S Analysis)",
        "description": "Long-memory persistence (H>0.5), mean-reversion (H<0.5), or random walk (H≈0.5)",
        "formula": "R/S ~ n^H  ⇒  H = slope of log(R/S) vs log(n)",
    },
]


@dataclass
class EntropyResult:
    symbol: str
    shannon_entropy_bits: float
    max_entropy_bits: float
    normalized_entropy: float
    efficiency_label: str
    sample_size: int


@dataclass
class MutualInformationResult:
    symbol: str
    benchmark: str
    mutual_info_bits: float
    normalized_mi: float
    interpretation: str


@dataclass
class ComplexityResult:
    symbol: str
    approx_entropy: float
    complexity_label: str


@dataclass
class HurstResult:
    symbol: str
    hurst_exponent: float
    regime: str
    interpretation: str


@dataclass
class InformationFinding:
    title: str
    method: str
    symbols: list[str]
    value: float
    practical_implication: str


@dataclass
class InformationAssessment:
    entropy_signal: str
    mutual_information_signal: str
    complexity_signal: str
    memory_signal: str
    information_conclusion: str


@dataclass
class InformationTheoryReport:
    entropy_results: list[EntropyResult]
    mutual_information: list[MutualInformationResult]
    complexity_results: list[ComplexityResult]
    hurst_results: list[HurstResult]
    findings: list[InformationFinding]
    assessment: InformationAssessment
    average_normalized_entropy: float
    average_hurst: float
    regime_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class InformationTheoryExpert(BaseExpert):
    """Information theorist — entropy, mutual information, complexity and memory in markets."""

    def __init__(self, delay_seconds: float = 0.3) -> None:
        super().__init__()
        self.delay_seconds = delay_seconds

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
    def _histogram_bins(values: list[float], bins: int) -> list[int]:
        """Assign each value to an equal-width bin index in [0, bins-1]."""
        lo, hi = min(values), max(values)
        width = (hi - lo) or 1e-12
        indices = []
        for v in values:
            idx = int((v - lo) / width * bins)
            idx = min(idx, bins - 1)
            indices.append(idx)
        return indices

    def _shannon_entropy(self, symbol: str, returns: list[float]) -> EntropyResult:
        n = len(returns)
        bin_idx = self._histogram_bins(returns, ENTROPY_BINS)
        counts: dict[int, int] = {}
        for idx in bin_idx:
            counts[idx] = counts.get(idx, 0) + 1
        entropy = 0.0
        for c in counts.values():
            p = c / n
            entropy -= p * math.log2(p)
        max_entropy = math.log2(ENTROPY_BINS)
        normalized = round(entropy / max_entropy, 4) if max_entropy else 0.0
        if normalized >= 0.9:
            label = "High-Entropy / Efficient"
        elif normalized >= 0.75:
            label = "Moderate-Entropy"
        else:
            label = "Low-Entropy / Structured"
        return EntropyResult(
            symbol=symbol,
            shannon_entropy_bits=round(entropy, 4),
            max_entropy_bits=round(max_entropy, 4),
            normalized_entropy=normalized,
            efficiency_label=label,
            sample_size=n,
        )

    def _mutual_information(
        self, symbol: str, returns: list[float], bench_returns: list[float]
    ) -> MutualInformationResult | None:
        n = min(len(returns), len(bench_returns))
        if n < 20:
            return None
        x = returns[-n:]
        y = bench_returns[-n:]
        x_bins = self._histogram_bins(x, MI_BINS)
        y_bins = self._histogram_bins(y, MI_BINS)

        joint_counts: dict[tuple[int, int], int] = {}
        x_counts: dict[int, int] = {}
        y_counts: dict[int, int] = {}
        for xi, yi in zip(x_bins, y_bins):
            joint_counts[(xi, yi)] = joint_counts.get((xi, yi), 0) + 1
            x_counts[xi] = x_counts.get(xi, 0) + 1
            y_counts[yi] = y_counts.get(yi, 0) + 1

        mi = 0.0
        for (xi, yi), joint_c in joint_counts.items():
            p_xy = joint_c / n
            p_x = x_counts[xi] / n
            p_y = y_counts[yi] / n
            if p_xy > 0 and p_x > 0 and p_y > 0:
                mi += p_xy * math.log2(p_xy / (p_x * p_y))
        mi = max(mi, 0.0)
        max_mi = math.log2(MI_BINS)
        normalized_mi = round(mi / max_mi, 4) if max_mi else 0.0

        if symbol == BENCHMARK:
            interpretation = "identity — benchmark shares all information with itself"
        elif normalized_mi >= 0.4:
            interpretation = f"{symbol} shares substantial information with {BENCHMARK} (tightly coupled)"
        elif normalized_mi >= 0.15:
            interpretation = f"{symbol} shares moderate information with {BENCHMARK} (partial co-movement)"
        else:
            interpretation = f"{symbol} shares little information with {BENCHMARK} (largely independent)"

        return MutualInformationResult(
            symbol=symbol,
            benchmark=BENCHMARK,
            mutual_info_bits=round(mi, 4),
            normalized_mi=normalized_mi,
            interpretation=interpretation,
        )

    @staticmethod
    def _approx_entropy(returns: list[float], m: int = APEN_M) -> float:
        n = len(returns)
        if n < m + 10:
            return 0.0
        stdev = statistics.stdev(returns) if n > 1 else 1e-9
        r = 0.2 * stdev if stdev else 1e-9

        def _phi(dim: int) -> float:
            templates = [returns[i:i + dim] for i in range(n - dim + 1)]
            counts = []
            for i, t_i in enumerate(templates):
                matches = 0
                for t_j in templates:
                    if max(abs(a - b) for a, b in zip(t_i, t_j)) <= r:
                        matches += 1
                counts.append(matches / len(templates))
            return sum(math.log(c) for c in counts if c > 0) / len(counts)

        try:
            return round(_phi(m) - _phi(m + 1), 4)
        except (ValueError, ZeroDivisionError):
            return 0.0

    def _complexity(self, symbol: str, returns: list[float]) -> ComplexityResult:
        # Limit sample for ApEn's O(n^2) template comparison to keep runtime bounded.
        sample = returns[-120:] if len(returns) > 120 else returns
        apen = self._approx_entropy(sample)
        if apen >= 0.6:
            label = "High-Complexity / Irregular"
        elif apen >= 0.3:
            label = "Moderate-Complexity"
        else:
            label = "Low-Complexity / Repetitive Structure"
        return ComplexityResult(symbol=symbol, approx_entropy=apen, complexity_label=label)

    @staticmethod
    def _rescaled_range(window: list[float]) -> float:
        mean = statistics.mean(window)
        adjusted = [x - mean for x in window]
        cumulative = list(itertools.accumulate(adjusted))
        r_stat = max(cumulative) - min(cumulative)
        s_stat = statistics.stdev(window) if len(window) > 1 else 0.0
        return r_stat / s_stat if s_stat else 0.0

    def _hurst_exponent(self, symbol: str, returns: list[float]) -> HurstResult:
        n = len(returns)
        window_sizes = [w for w in HURST_WINDOWS if w * 2 <= n]
        log_n: list[float] = []
        log_rs: list[float] = []
        for w in window_sizes:
            rs_values = []
            for start in range(0, n - w + 1, w):
                window = returns[start:start + w]
                if len(window) == w:
                    rs = self._rescaled_range(window)
                    if rs > 0:
                        rs_values.append(rs)
            if rs_values:
                avg_rs = statistics.mean(rs_values)
                if avg_rs > 0:
                    log_n.append(math.log(w))
                    log_rs.append(math.log(avg_rs))

        if len(log_n) < 2:
            hurst = 0.5
        else:
            mean_x = statistics.mean(log_n)
            mean_y = statistics.mean(log_rs)
            num = sum((x - mean_x) * (y - mean_y) for x, y in zip(log_n, log_rs))
            den = sum((x - mean_x) ** 2 for x in log_n)
            hurst = round(num / den, 4) if den else 0.5

        if hurst >= 0.55:
            regime = "Trend-Persistent"
            interpretation = f"H={hurst:.2f} > 0.5 — {symbol} shows long-memory trend persistence"
        elif hurst <= 0.45:
            regime = "Mean-Reverting"
            interpretation = f"H={hurst:.2f} < 0.5 — {symbol} shows anti-persistent, mean-reverting behavior"
        else:
            regime = "Random Walk"
            interpretation = f"H={hurst:.2f} ≈ 0.5 — {symbol} is statistically consistent with a random walk"

        return HurstResult(symbol=symbol, hurst_exponent=hurst, regime=regime, interpretation=interpretation)

    @staticmethod
    def _findings(
        entropy_results: list[EntropyResult],
        mi_results: list[MutualInformationResult],
        complexity_results: list[ComplexityResult],
        hurst_results: list[HurstResult],
    ) -> list[InformationFinding]:
        findings: list[InformationFinding] = []

        for e in sorted(entropy_results, key=lambda x: x.normalized_entropy)[:3]:
            findings.append(InformationFinding(
                title=f"{e.symbol} entropy structure",
                method="shannon_entropy",
                symbols=[e.symbol],
                value=e.normalized_entropy,
                practical_implication=f"{e.efficiency_label}: normalized H={e.normalized_entropy:.3f}",
            ))

        for m in sorted(mi_results, key=lambda x: -x.normalized_mi):
            if m.symbol == BENCHMARK:
                continue
            findings.append(InformationFinding(
                title=f"{m.symbol} vs {BENCHMARK} shared information",
                method="mutual_information",
                symbols=[m.symbol, BENCHMARK],
                value=m.normalized_mi,
                practical_implication=m.interpretation,
            ))
            break

        for c in sorted(complexity_results, key=lambda x: -x.approx_entropy)[:2]:
            findings.append(InformationFinding(
                title=f"{c.symbol} regularity",
                method="approximate_entropy",
                symbols=[c.symbol],
                value=c.approx_entropy,
                practical_implication=f"{c.complexity_label}: ApEn={c.approx_entropy:.3f}",
            ))

        for h in hurst_results:
            if h.regime != "Random Walk":
                findings.append(InformationFinding(
                    title=f"{h.symbol} memory structure",
                    method="hurst_exponent",
                    symbols=[h.symbol],
                    value=h.hurst_exponent,
                    practical_implication=h.interpretation,
                ))

        return findings

    @staticmethod
    def _assessment(
        entropy_results: list[EntropyResult],
        mi_results: list[MutualInformationResult],
        complexity_results: list[ComplexityResult],
        hurst_results: list[HurstResult],
        avg_norm_entropy: float,
        avg_hurst: float,
    ) -> InformationAssessment:
        entropy_signal = (
            f"Average normalized entropy {avg_norm_entropy:.3f} across watchlist — "
            + ("markets are close to maximum-entropy (near-efficient)" if avg_norm_entropy >= 0.85
               else "markets show detectable structure below maximum entropy")
        )

        coupled = [m for m in mi_results if m.symbol != BENCHMARK and m.normalized_mi >= 0.4]
        mutual_information_signal = (
            f"{len(coupled)} of {len([m for m in mi_results if m.symbol != BENCHMARK])} assets "
            f"tightly share information with {BENCHMARK}"
            if mi_results else "insufficient overlapping data for mutual information"
        )

        avg_apen = statistics.mean([c.approx_entropy for c in complexity_results]) if complexity_results else 0.0
        complexity_signal = f"Average approximate entropy {avg_apen:.3f} — " + (
            "irregular, complex return dynamics" if avg_apen >= 0.5 else "relatively regular return dynamics"
        )

        memory_signal = f"Average Hurst exponent {avg_hurst:.3f} — " + (
            "persistent trending memory dominant" if avg_hurst >= 0.55 else
            "mean-reverting memory dominant" if avg_hurst <= 0.45 else
            "consistent with efficient random-walk pricing"
        )

        if avg_norm_entropy >= 0.85 and 0.45 < avg_hurst < 0.55:
            information_conclusion = "Information content is close to maximum entropy — little exploitable structure detected."
        elif avg_hurst >= 0.55:
            information_conclusion = "Detectable trend-persistence — momentum-based information edge may exist."
        elif avg_hurst <= 0.45:
            information_conclusion = "Detectable mean-reversion — contrarian information edge may exist."
        else:
            information_conclusion = "Mixed information signature — no single dominant structural edge."

        return InformationAssessment(
            entropy_signal=entropy_signal,
            mutual_information_signal=mutual_information_signal,
            complexity_signal=complexity_signal,
            memory_signal=memory_signal,
            information_conclusion=information_conclusion,
        )

    @staticmethod
    def _expert_summary(assessment: InformationAssessment, regime_label: str) -> str:
        return (
            f"Information-theoretic regime: {regime_label}. {assessment.information_conclusion} "
            f"{assessment.memory_signal}"
        )

    @staticmethod
    def _market_signals(
        hurst_results: list[HurstResult],
        mi_results: list[MutualInformationResult],
        findings: list[InformationFinding],
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        for h in hurst_results:
            if h.symbol == BENCHMARK and h.regime != "Random Walk":
                bias = "BULLISH" if h.regime == "Trend-Persistent" else "NEUTRAL"
                signals.append({
                    "sector": "Market Memory — SPY",
                    "tickers": ["SPY", "VOO"],
                    "bias": bias,
                    "reason": h.interpretation,
                })

        for h in hurst_results:
            if h.symbol != BENCHMARK and h.regime == "Trend-Persistent":
                signals.append({
                    "sector": f"Trend Persistence — {h.symbol}",
                    "tickers": [h.symbol],
                    "bias": "BULLISH",
                    "reason": h.interpretation,
                })
            elif h.symbol != BENCHMARK and h.regime == "Mean-Reverting":
                signals.append({
                    "sector": f"Mean Reversion — {h.symbol}",
                    "tickers": [h.symbol],
                    "bias": "NEUTRAL",
                    "reason": h.interpretation,
                })

        low_mi = [m for m in mi_results if m.symbol != BENCHMARK and m.normalized_mi < 0.15]
        for m in low_mi[:2]:
            signals.append({
                "sector": f"Diversification — {m.symbol}",
                "tickers": [m.symbol],
                "bias": "NEUTRAL",
                "reason": m.interpretation,
            })

        if not signals:
            signals.append({
                "sector": "Information Neutral",
                "tickers": ["SPY"],
                "bias": "NEUTRAL",
                "reason": "No dominant entropy/memory structure detected across watchlist",
            })
        return signals

    @staticmethod
    def _recommendations(
        assessment: InformationAssessment,
        entropy_results: list[EntropyResult],
        mi_results: list[MutualInformationResult],
        complexity_results: list[ComplexityResult],
        hurst_results: list[HurstResult],
        findings: list[InformationFinding],
    ) -> list[str]:
        recs = [
            assessment.entropy_signal,
            assessment.mutual_information_signal,
            assessment.complexity_signal,
            assessment.memory_signal,
            assessment.information_conclusion,
        ]
        for e in sorted(entropy_results, key=lambda x: x.normalized_entropy)[:4]:
            recs.append(
                f"{e.symbol}: H={e.shannon_entropy_bits:.3f} bits "
                f"(normalized {e.normalized_entropy:.3f}) — {e.efficiency_label}"
            )
        for m in mi_results:
            if m.symbol != BENCHMARK:
                recs.append(f"{m.symbol} I(X;{BENCHMARK})={m.mutual_info_bits:.3f} bits — {m.interpretation}")
        for c in sorted(complexity_results, key=lambda x: -x.approx_entropy)[:4]:
            recs.append(f"{c.symbol} ApEn={c.approx_entropy:.3f} — {c.complexity_label}")
        for h in hurst_results:
            recs.append(f"{h.symbol} Hurst={h.hurst_exponent:.3f} ({h.regime}) — {h.interpretation}")
        for f in findings[:5]:
            recs.append(f"Finding: {f.title} — {f.practical_implication}")
        return recs

    def analyze(self) -> InformationTheoryReport:
        return_map: dict[str, list[float]] = {}

        for symbol in WATCHLIST:
            closes = self._fetch_closes(symbol)
            if closes:
                return_map[symbol] = self._daily_returns(closes)
            time.sleep(self.delay_seconds)

        if BENCHMARK not in return_map:
            raise RuntimeError("Unable to fetch SPY data for information theory analysis")

        bench = return_map[BENCHMARK]

        entropy_results = [self._shannon_entropy(sym, rets) for sym, rets in return_map.items()]
        mi_results = [
            mi for sym, rets in return_map.items()
            if (mi := self._mutual_information(sym, rets, bench)) is not None
        ]
        complexity_results = [self._complexity(sym, rets) for sym, rets in return_map.items()]
        hurst_results = [self._hurst_exponent(sym, rets) for sym, rets in return_map.items()]

        findings = self._findings(entropy_results, mi_results, complexity_results, hurst_results)

        avg_norm_entropy = round(statistics.mean([e.normalized_entropy for e in entropy_results]), 4)
        avg_hurst = round(statistics.mean([h.hurst_exponent for h in hurst_results]), 4)

        assessment = self._assessment(
            entropy_results, mi_results, complexity_results, hurst_results,
            avg_norm_entropy, avg_hurst,
        )

        if avg_norm_entropy >= 0.85 and 0.45 < avg_hurst < 0.55:
            regime_label = "Maximum-Entropy / Efficient"
        elif avg_hurst >= 0.55:
            regime_label = "Persistent-Memory / Trending"
        elif avg_hurst <= 0.45:
            regime_label = "Anti-Persistent / Mean-Reverting"
        else:
            regime_label = "Mixed-Information Regime"

        summary = self._expert_summary(assessment, regime_label)
        signals = self._market_signals(hurst_results, mi_results, findings)
        recs = self._recommendations(
            assessment, entropy_results, mi_results, complexity_results, hurst_results, findings,
        )

        return InformationTheoryReport(
            entropy_results=entropy_results,
            mutual_information=mi_results,
            complexity_results=complexity_results,
            hurst_results=hurst_results,
            findings=findings,
            assessment=assessment,
            average_normalized_entropy=avg_norm_entropy,
            average_hurst=avg_hurst,
            regime_label=regime_label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source="Yahoo Finance API",
        )

    def to_dict(self, report: InformationTheoryReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Information Theory Expert",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "temperature": self.temperature,
                "expert_summary": report.expert_summary,
                "methods_applied": [m["id"] for m in INFORMATION_METHODS],
            },
            "information_methods": INFORMATION_METHODS,
            "entropy_results": [
                {
                    "symbol": e.symbol,
                    "shannon_entropy_bits": e.shannon_entropy_bits,
                    "max_entropy_bits": e.max_entropy_bits,
                    "normalized_entropy": e.normalized_entropy,
                    "efficiency_label": e.efficiency_label,
                    "sample_size": e.sample_size,
                }
                for e in report.entropy_results
            ],
            "mutual_information": [
                {
                    "symbol": m.symbol,
                    "benchmark": m.benchmark,
                    "mutual_info_bits": m.mutual_info_bits,
                    "normalized_mi": m.normalized_mi,
                    "interpretation": m.interpretation,
                }
                for m in report.mutual_information
            ],
            "complexity_results": [
                {
                    "symbol": c.symbol,
                    "approx_entropy": c.approx_entropy,
                    "complexity_label": c.complexity_label,
                }
                for c in report.complexity_results
            ],
            "hurst_results": [
                {
                    "symbol": h.symbol,
                    "hurst_exponent": h.hurst_exponent,
                    "regime": h.regime,
                    "interpretation": h.interpretation,
                }
                for h in report.hurst_results
            ],
            "findings": [
                {
                    "title": f.title,
                    "method": f.method,
                    "symbols": f.symbols,
                    "value": f.value,
                    "practical_implication": f.practical_implication,
                }
                for f in report.findings
            ],
            "assessment": {
                "entropy_signal": a.entropy_signal,
                "mutual_information_signal": a.mutual_information_signal,
                "complexity_signal": a.complexity_signal,
                "memory_signal": a.memory_signal,
                "information_conclusion": a.information_conclusion,
            },
            "metrics": {
                "average_normalized_entropy": report.average_normalized_entropy,
                "average_hurst": report.average_hurst,
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
            catalog = output.parent / "information_theory_methods.json"
            catalog.write_text(
                json.dumps(INFORMATION_METHODS, indent=2),
                encoding="utf-8",
            )
        return result


def run_information_theory_analysis(output: Path | None = None) -> dict[str, Any]:
    return InformationTheoryExpert().run(output=output)
