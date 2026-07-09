"""
Data Science Expert Agent
=========================
Quantitative market analysis: returns, volatility, z-scores, correlations,
empirical probabilities, and Monte Carlo forward simulations.

Data: Yahoo Finance chart API (daily closes, 6-month history).
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

from agents.base import BaseExpert

WATCHLIST = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "IWM": "Russell 2000",
    "XLK": "Technology",
    "XLE": "Energy",
    "XLF": "Financials",
    "XLU": "Utilities",
    "GLD": "Gold",
    "TLT": "Long Treasuries",
    "HYG": "High Yield Credit",
}

BENCHMARK = "SPY"
MC_SIMULATIONS = 5000
MC_HORIZON_DAYS = 5


@dataclass
class TickerStats:
    symbol: str
    name: str
    last_price: float
    return_1d_pct: float
    return_5d_pct: float
    return_20d_pct: float
    vol_20d_ann_pct: float
    z_score_20d: float
    prob_up_empirical: float
    mc_prob_up_5d: float
    mc_median_return_5d_pct: float
    momentum_score: float
    mean_reversion_score: float


@dataclass
class CorrelationPair:
    symbol_a: str
    symbol_b: str
    correlation: float
    label: str


@dataclass
class QuantAssessment:
    market_regime: str
    dispersion_signal: str
    correlation_structure: str
    tail_risk_signal: str
    factor_leader: str
    factor_laggard: str


@dataclass
class DataScienceReport:
    tickers: list[TickerStats]
    correlations: list[CorrelationPair]
    assessment: QuantAssessment
    quant_stress_score: float
    opportunity_score: float
    stress_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DataScienceExpert(BaseExpert):
    """Expert data scientist — statistical factor analysis on US market ETFs."""

    def __init__(
        self,
        delay_seconds: float = 0.3,
        *,
        pipeline_context: dict | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="datascience")
        self.delay_seconds = delay_seconds
        self.watchlist = dict(WATCHLIST)

    def _fetch_closes(self, symbol: str) -> list[float]:
        return self.fetch_yahoo_closes(symbol, range_="6mo", interval="1d")

    @staticmethod
    def _log_returns(prices: list[float]) -> list[float]:
        return [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]

    @staticmethod
    def _pct_return(prices: list[float], days: int) -> float:
        if len(prices) <= days:
            return 0.0
        return round(((prices[-1] - prices[-1 - days]) / prices[-1 - days]) * 100, 2)

    @staticmethod
    def _volatility_ann(returns: list[float], window: int = 20) -> float:
        if len(returns) < window:
            return 0.0
        recent = returns[-window:]
        daily_std = statistics.stdev(recent) if len(recent) > 1 else 0.0
        return round(daily_std * math.sqrt(252) * 100, 2)

    @staticmethod
    def _z_score(prices: list[float], window: int = 20) -> float:
        if len(prices) < window:
            return 0.0
        recent = prices[-window:]
        mean = statistics.mean(recent)
        std = statistics.stdev(recent) if len(recent) > 1 else 1e-9
        return round((prices[-1] - mean) / std, 2)

    @staticmethod
    def _empirical_prob_up(returns: list[float]) -> float:
        if not returns:
            return 0.5
        ups = sum(1 for r in returns if r > 0)
        return round(ups / len(returns), 4)

    @staticmethod
    def _monte_carlo_5d(returns: list[float], last_price: float) -> tuple[float, float]:
        if len(returns) < 20:
            return 0.5, 0.0
        recent = returns[-60:]
        mu = statistics.mean(recent)
        sigma = statistics.stdev(recent) if len(recent) > 1 else 0.01
        ups = 0
        finals: list[float] = []
        for _ in range(MC_SIMULATIONS):
            price = last_price
            for _ in range(MC_HORIZON_DAYS):
                price *= math.exp(mu + sigma * random.gauss(0, 1))
            ret = (price - last_price) / last_price
            finals.append(ret)
            if ret > 0:
                ups += 1
        prob_up = round(ups / MC_SIMULATIONS, 4)
        finals.sort()
        median_ret = round(finals[len(finals) // 2] * 100, 2)
        return prob_up, median_ret

    @staticmethod
    def _momentum_score(return_20d: float, vol: float) -> float:
        if vol <= 0:
            return 0.5
        sharpe_like = return_20d / vol
        return round(max(0.0, min(1.0, 0.5 + sharpe_like * 0.15)), 4)

    @staticmethod
    def _mean_reversion_score(z: float) -> float:
        """High score = stretched, likely to revert."""
        return round(max(0.0, min(1.0, abs(z) / 3.0)), 4)

    @staticmethod
    def _pearson(a: list[float], b: list[float]) -> float:
        n = min(len(a), len(b))
        if n < 10:
            return 0.0
        a, b = a[-n:], b[-n:]
        ma, mb = statistics.mean(a), statistics.mean(b)
        num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
        da = math.sqrt(sum((x - ma) ** 2 for x in a))
        db = math.sqrt(sum((x - mb) ** 2 for x in b))
        if da == 0 or db == 0:
            return 0.0
        return round(num / (da * db), 4)

    def _analyze_ticker(self, symbol: str, name: str) -> TickerStats | None:
        prices = self._fetch_closes(symbol)
        if len(prices) < 25:
            return None
        returns = self._log_returns(prices)
        vol = self._volatility_ann(returns)
        z = self._z_score(prices)
        r20 = self._pct_return(prices, 20)
        mc_up, mc_med = self._monte_carlo_5d(returns, prices[-1])
        return TickerStats(
            symbol=symbol,
            name=name,
            last_price=round(prices[-1], 2),
            return_1d_pct=self._pct_return(prices, 1),
            return_5d_pct=self._pct_return(prices, 5),
            return_20d_pct=r20,
            vol_20d_ann_pct=vol,
            z_score_20d=z,
            prob_up_empirical=self._empirical_prob_up(returns[-60:]),
            mc_prob_up_5d=mc_up,
            mc_median_return_5d_pct=mc_med,
            momentum_score=self._momentum_score(r20, vol),
            mean_reversion_score=self._mean_reversion_score(z),
        )

    def _correlations(self, return_map: dict[str, list[float]]) -> list[CorrelationPair]:
        pairs: list[CorrelationPair] = []
        bench = return_map.get(BENCHMARK, [])
        for sym in self.watchlist:
            if sym == BENCHMARK or sym not in return_map:
                continue
            corr = self._pearson(bench, return_map[sym])
            label = (
                "highly correlated" if corr >= 0.85 else
                "moderately correlated" if corr >= 0.6 else
                "low correlation" if corr >= 0.3 else
                "decoupled"
            )
            pairs.append(CorrelationPair(BENCHMARK, sym, corr, label))
        pairs.sort(key=lambda p: abs(p.correlation), reverse=True)
        return pairs

    def _assessment(
        self,
        tickers: list[TickerStats],
        correlations: list[CorrelationPair],
    ) -> QuantAssessment:
        spy = next((t for t in tickers if t.symbol == BENCHMARK), tickers[0])
        vols = [t.vol_20d_ann_pct for t in tickers]
        avg_vol = statistics.mean(vols) if vols else 15.0

        if spy.return_20d_pct > 2 and spy.momentum_score >= 0.6:
            regime = "trending bullish — positive 20d momentum with factor confirmation"
        elif spy.return_20d_pct < -2 and spy.momentum_score <= 0.4:
            regime = "trending bearish — negative momentum across benchmark"
        else:
            regime = "range-bound — no strong directional trend in SPY"

        vol_spread = (max(vols) - min(vols)) if vols else 0
        dispersion = (
            f"high cross-asset dispersion ({vol_spread:.1f} vol spread)"
            if vol_spread > 12 else
            f"moderate dispersion ({vol_spread:.1f} vol spread)"
        )

        high_corr = [p for p in correlations if p.correlation >= 0.85]
        if len(high_corr) >= 4:
            corr_struct = "risk-on clustering — equities moving together (beta regime)"
        elif any(p.symbol_b in ("GLD", "TLT") and p.correlation < 0.3 for p in correlations):
            corr_struct = "diversification available — gold/bonds decoupled from SPY"
        else:
            corr_struct = "mixed correlation structure"

        neg_z = [t for t in tickers if t.z_score_20d <= -1.5]
        pos_z = [t for t in tickers if t.z_score_20d >= 1.5]
        if neg_z:
            tail = f"oversold candidates: {', '.join(t.symbol for t in neg_z[:3])}"
        elif pos_z:
            tail = f"overbought stretch: {', '.join(t.symbol for t in pos_z[:3])}"
        else:
            tail = "no extreme z-score tails — prices near 20d mean"

        ranked = sorted(tickers, key=lambda t: t.momentum_score, reverse=True)
        leader = f"{ranked[0].symbol} (momentum {ranked[0].momentum_score:.2f})"
        laggard = f"{ranked[-1].symbol} (momentum {ranked[-1].momentum_score:.2f})"

        return QuantAssessment(
            market_regime=regime,
            dispersion_signal=dispersion,
            correlation_structure=corr_struct,
            tail_risk_signal=tail,
            factor_leader=leader,
            factor_laggard=laggard,
        )

    def _quant_stress(self, tickers: list[TickerStats]) -> float:
        spy = next((t for t in tickers if t.symbol == BENCHMARK), None)
        hyg = next((t for t in tickers if t.symbol == "HYG"), None)
        vix_proxy = statistics.mean(t.vol_20d_ann_pct for t in tickers)
        stress = 0.0
        if spy and spy.return_20d_pct < 0:
            stress += min(0.4, abs(spy.return_20d_pct) / 20)
        if hyg and hyg.return_20d_pct < -2:
            stress += 0.25
        if vix_proxy > 20:
            stress += min(0.35, (vix_proxy - 15) / 30)
        return round(min(1.0, stress), 4)

    def _opportunity_score(self, tickers: list[TickerStats]) -> float:
        oversold = [t for t in tickers if t.z_score_20d <= -1.2 and t.mc_prob_up_5d >= 0.52]
        momentum = [t for t in tickers if t.momentum_score >= 0.65]
        score = len(oversold) * 0.15 + len(momentum) * 0.12
        return round(min(1.0, score), 4)

    def _expert_summary(
        self,
        assessment: QuantAssessment,
        stress: float,
        opportunity: float,
        label: str,
        tickers: list[TickerStats],
    ) -> str:
        spy = next((t for t in tickers if t.symbol == BENCHMARK), tickers[0])
        return (
            f"Quantitative regime: {label} (stress {stress:.2f}, opportunity {opportunity:.2f}). "
            f"{assessment.market_regime}. "
            f"SPY 20d return {spy.return_20d_pct:+.2f}%, vol {spy.vol_20d_ann_pct:.1f}%, "
            f"z-score {spy.z_score_20d:+.2f}. "
            f"5d MC P(up)={spy.mc_prob_up_5d:.0%}, median {spy.mc_median_return_5d_pct:+.2f}%. "
            f"Dispersion: {assessment.dispersion_signal}. "
            f"Correlations: {assessment.correlation_structure}. "
            f"Tails: {assessment.tail_risk_signal}. "
            f"Factor leader {assessment.factor_leader}, laggard {assessment.factor_laggard}."
        )

    def analyze(self) -> DataScienceReport:
        tickers: list[TickerStats] = []
        return_map: dict[str, list[float]] = {}

        for symbol, name in self.watchlist.items():
            prices = self._fetch_closes(symbol)
            if len(prices) >= 25:
                return_map[symbol] = self._log_returns(prices)
            stats = self._analyze_ticker(symbol, name)
            if stats:
                tickers.append(stats)
            time.sleep(self.delay_seconds)

        correlations = self._correlations(return_map)
        assessment = self._assessment(tickers, correlations)
        stress = self._quant_stress(tickers)
        opportunity = self._opportunity_score(tickers)

        label = (
            "Stressed" if stress >= 0.65 else
            "Cautious" if stress >= 0.40 else
            "Constructive" if opportunity >= 0.35 else
            "Neutral"
        )

        summary = self._expert_summary(assessment, stress, opportunity, label, tickers)
        signals = self._market_signals(tickers, assessment, stress, opportunity)
        recs = self.append_memory_recommendations(
            self._recommendations(tickers, assessment, correlations)
        )

        return DataScienceReport(
            tickers=tickers,
            correlations=correlations,
            assessment=assessment,
            quant_stress_score=stress,
            opportunity_score=opportunity,
            stress_label=label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source="Yahoo Finance (6mo daily, Monte Carlo GBM)",
        )

    def _market_signals(
        self,
        tickers: list[TickerStats],
        assessment: QuantAssessment,
        stress: float,
        opportunity: float,
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal, quant_signal_confidence

        signals: list[dict[str, Any]] = []
        by_sym = {t.symbol: t for t in tickers}
        spy = by_sym.get("SPY")

        if spy:
            if spy.momentum_score >= 0.65 and spy.mc_prob_up_5d >= 0.55:
                signals.append(
                    build_market_signal(
                        sector="Momentum — Broad Market",
                        tickers=["SPY", "QQQ"],
                        bias="BULLISH",
                        reason=(
                            f"SPY momentum {spy.momentum_score:.2f}, "
                            f"MC P(up) {spy.mc_prob_up_5d:.0%}"
                        ),
                        confidence=self.adjust_signal_confidence(
                            "SPY",
                            "BULLISH",
                            quant_signal_confidence(
                                momentum=spy.momentum_score,
                                mc_prob_up=spy.mc_prob_up_5d,
                                stress=stress,
                            ),
                        ),
                        evidence={"mc_prob_up_5d": spy.mc_prob_up_5d, "stress": round(stress, 3)},
                    )
                )
            elif spy.momentum_score <= 0.4 and stress >= 0.45:
                signals.append(
                    build_market_signal(
                        sector="Defensive Hedge",
                        tickers=["TLT", "GLD", "XLU"],
                        bias="BULLISH",
                        reason=f"Quant stress {stress:.2f} — defensive factors favored",
                        confidence=self.adjust_signal_confidence(
                            "TLT",
                            "BULLISH",
                            quant_signal_confidence(
                                momentum=spy.momentum_score,
                                stress=stress,
                            ),
                        ),
                    )
                )

        oversold = sorted(
            [t for t in tickers if t.z_score_20d <= -1.4 and t.mc_prob_up_5d >= 0.52],
            key=lambda t: t.z_score_20d,
        )
        if oversold:
            t = oversold[0]
            signals.append(
                build_market_signal(
                    sector="Mean Reversion",
                    tickers=[t.symbol],
                    bias="BULLISH",
                    reason=(
                        f"{t.symbol} z-score {t.z_score_20d:+.2f}, "
                        f"MC P(up) {t.mc_prob_up_5d:.0%}"
                    ),
                    confidence=self.adjust_signal_confidence(
                        t.symbol,
                        "BULLISH",
                        quant_signal_confidence(
                            momentum=t.momentum_score,
                            mc_prob_up=t.mc_prob_up_5d,
                            z_score=t.z_score_20d,
                        ),
                    ),
                )
            )

        overbought = [t for t in tickers if t.z_score_20d >= 1.8]
        if overbought:
            t = overbought[0]
            signals.append(
                build_market_signal(
                    sector="Overbought Caution",
                    tickers=[t.symbol],
                    bias="BEARISH",
                    reason=f"{t.symbol} z-score {t.z_score_20d:+.2f} — stretched vs 20d mean",
                    confidence=self.adjust_signal_confidence(
                        t.symbol,
                        "BEARISH",
                        quant_signal_confidence(
                            momentum=t.momentum_score,
                            z_score=t.z_score_20d,
                        ),
                    ),
                )
            )

        leader = max(tickers, key=lambda t: t.momentum_score)
        if leader.momentum_score >= 0.62 and leader.symbol not in ("SPY",) and leader.return_20d_pct >= 2.0:
            signals.append(
                build_market_signal(
                    sector=f"Factor Leader — {leader.name}",
                    tickers=[leader.symbol],
                    bias="BULLISH",
                    reason=f"Top momentum score {leader.momentum_score:.2f}, 20d {leader.return_20d_pct:+.2f}%",
                    confidence=self.adjust_signal_confidence(
                        leader.symbol,
                        "BULLISH",
                        quant_signal_confidence(
                            momentum=leader.momentum_score,
                            mc_prob_up=leader.mc_prob_up_5d,
                        ),
                    ),
                )
            )

        hyg = by_sym.get("HYG")
        if hyg and hyg.return_20d_pct < -2.0:
            signals.append(
                build_market_signal(
                    sector="Credit Stress",
                    tickers=["HYG", "LQD", "JNK"],
                    bias="BEARISH",
                    reason=f"HYG 20d return {hyg.return_20d_pct:+.2f}% — credit risk rising",
                    confidence=self.adjust_signal_confidence(
                        "HYG",
                        "BEARISH",
                        quant_signal_confidence(
                            momentum=hyg.momentum_score,
                            z_score=hyg.z_score_20d,
                            stress=stress,
                        ),
                    ),
                )
            )

        if not signals:
            signals.append(
                build_market_signal(
                    sector="Quant Neutral",
                    tickers=["SPY"],
                    bias="NEUTRAL",
                    reason="No strong statistical edge detected",
                    confidence=self.adjust_signal_confidence("SPY", "NEUTRAL", 0.42),
                )
            )
        return signals

    @staticmethod
    def _recommendations(
        tickers: list[TickerStats],
        assessment: QuantAssessment,
        correlations: list[CorrelationPair],
    ) -> list[str]:
        recs = [
            assessment.market_regime,
            assessment.dispersion_signal,
            assessment.correlation_structure,
            assessment.tail_risk_signal,
            f"Factor leader: {assessment.factor_leader}",
            f"Factor laggard: {assessment.factor_laggard}",
        ]
        spy = next((t for t in tickers if t.symbol == "SPY"), None)
        if spy:
            recs.append(
                f"SPY: 20d {spy.return_20d_pct:+.2f}%, vol {spy.vol_20d_ann_pct:.1f}%, "
                f"z {spy.z_score_20d:+.2f}, empirical P(up) {spy.prob_up_empirical:.0%}, "
                f"MC 5d P(up) {spy.mc_prob_up_5d:.0%}"
            )
        for t in sorted(tickers, key=lambda x: abs(x.z_score_20d), reverse=True)[:3]:
            recs.append(
                f"{t.symbol}: z={t.z_score_20d:+.2f}, momentum={t.momentum_score:.2f}, "
                f"20d={t.return_20d_pct:+.2f}%"
            )
        if correlations:
            top = correlations[0]
            recs.append(
                f"Highest SPY correlation: {top.symbol_b} ({top.correlation:+.2f}, {top.label})"
            )
        return recs

    def to_dict(self, report: DataScienceReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Data Science Expert",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
                "tickers_analyzed": len(report.tickers),
                "monte_carlo": {
                    "simulations": MC_SIMULATIONS,
                    "horizon_days": MC_HORIZON_DAYS,
                },
            },
            "assessment": {
                "market_regime": a.market_regime,
                "dispersion_signal": a.dispersion_signal,
                "correlation_structure": a.correlation_structure,
                "tail_risk_signal": a.tail_risk_signal,
                "factor_leader": a.factor_leader,
                "factor_laggard": a.factor_laggard,
            },
            "tickers": [
                {
                    "symbol": t.symbol,
                    "name": t.name,
                    "last_price": t.last_price,
                    "return_1d_pct": t.return_1d_pct,
                    "return_5d_pct": t.return_5d_pct,
                    "return_20d_pct": t.return_20d_pct,
                    "vol_20d_ann_pct": t.vol_20d_ann_pct,
                    "z_score_20d": t.z_score_20d,
                    "prob_up_empirical": t.prob_up_empirical,
                    "mc_prob_up_5d": t.mc_prob_up_5d,
                    "mc_median_return_5d_pct": t.mc_median_return_5d_pct,
                    "momentum_score": t.momentum_score,
                    "mean_reversion_score": t.mean_reversion_score,
                }
                for t in report.tickers
            ],
            "correlations": [
                {
                    "symbol_a": c.symbol_a,
                    "symbol_b": c.symbol_b,
                    "correlation": c.correlation,
                    "label": c.label,
                }
                for c in report.correlations
            ],
            "metrics": {
                "quant_stress_score": report.quant_stress_score,
                "opportunity_score": report.opportunity_score,
                "stress_label": report.stress_label,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result


def run_datascience_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return DataScienceExpert(pipeline_context=pipeline_context).run(output=output)