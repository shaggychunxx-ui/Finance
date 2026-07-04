"""
Backtesting Expert Agent
========================
Expert in strategy backtesting: walks common technical signals (momentum,
mean reversion, volatility breakout) forward through historical daily
returns, splits results into in-sample/out-of-sample windows, and reports
whether each signal has a validated edge — win rate, Sharpe ratio, max
drawdown, profit factor, and performance versus a simple buy-and-hold
benchmark.

Data: Yahoo Finance chart API (1-year daily history).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .engine import SIGNAL_LIBRARY, WalkForwardResult, walk_forward_backtest

CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Finance-Backtesting-Expert/1.0 (shaggychunxx@gmail.com)"}

BENCHMARK = "SPY"
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

BACKTEST_STRATEGIES: list[dict[str, Any]] = [
    {"id": rule_id, "name": spec["name"], "description": spec["description"]}
    for rule_id, spec in SIGNAL_LIBRARY.items()
]


@dataclass
class StrategyResult:
    rule_id: str
    strategy_name: str
    symbol: str
    in_sample_trades: int
    in_sample_win_rate: float
    out_of_sample_trades: int
    out_of_sample_win_rate: float
    out_of_sample_sharpe: float
    out_of_sample_max_drawdown_pct: float
    out_of_sample_profit_factor: float
    benchmark_return_pct: float
    edge_vs_benchmark_pct: float
    stable: bool
    verdict: str


@dataclass
class BacktestAssessment:
    best_strategy: str
    robustness_signal: str
    benchmark_comparison: str
    overall_edge_signal: str


@dataclass
class BacktestingReport:
    strategies: list[StrategyResult]
    assessment: BacktestAssessment
    tested_count: int
    validated_count: int
    validation_rate: float
    regime_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class BacktestingExpert:
    """Expert in walk-forward strategy backtesting and signal validation."""

    def __init__(self, delay_seconds: float = 0.3) -> None:
        self.delay_seconds = delay_seconds
        self.watchlist = dict(WATCHLIST)

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
    def _to_strategy_result(result: WalkForwardResult, name: str) -> StrategyResult:
        return StrategyResult(
            rule_id=result.rule_id,
            strategy_name=name,
            symbol=result.symbol,
            in_sample_trades=result.in_sample.trades,
            in_sample_win_rate=result.in_sample.win_rate,
            out_of_sample_trades=result.out_of_sample.trades,
            out_of_sample_win_rate=result.out_of_sample.win_rate,
            out_of_sample_sharpe=result.out_of_sample.sharpe_ratio,
            out_of_sample_max_drawdown_pct=result.out_of_sample.max_drawdown_pct,
            out_of_sample_profit_factor=result.out_of_sample.profit_factor,
            benchmark_return_pct=result.benchmark_return_pct,
            edge_vs_benchmark_pct=result.edge_vs_benchmark_pct,
            stable=result.stable,
            verdict=result.verdict,
        )

    def _assessment(self, strategies: list[StrategyResult]) -> BacktestAssessment:
        validated = [s for s in strategies if s.stable]
        if validated:
            best = max(validated, key=lambda s: s.out_of_sample_sharpe)
            best_strategy = (
                f"{best.strategy_name} on {best.symbol} — Sharpe {best.out_of_sample_sharpe:+.2f}, "
                f"OOS win rate {best.out_of_sample_win_rate:.0%}"
            )
        elif strategies:
            best = max(strategies, key=lambda s: s.out_of_sample_win_rate)
            best_strategy = (
                f"No strategy passed validation; closest was {best.strategy_name} on {best.symbol} "
                f"({best.out_of_sample_win_rate:.0%} OOS win rate)"
            )
        else:
            best_strategy = "No strategies could be backtested (insufficient data)"

        robustness_signal = (
            f"{len(validated)}/{len(strategies)} tested strategies held up out-of-sample"
            if strategies else "no strategies tested"
        )

        beating_benchmark = [s for s in validated if s.edge_vs_benchmark_pct > 0]
        if validated:
            benchmark_comparison = (
                f"{len(beating_benchmark)}/{len(validated)} validated strategies beat buy-and-hold "
                f"over the same out-of-sample window"
            )
        else:
            benchmark_comparison = "no validated strategies to compare against buy-and-hold"

        if len(validated) >= 2 and len(beating_benchmark) >= 1:
            overall_edge_signal = "genuine, backtested edge found in at least one strategy"
        elif validated:
            overall_edge_signal = "marginal backtested edge — validated but not clearly beating buy-and-hold"
        else:
            overall_edge_signal = "no backtested edge — signals did not survive out-of-sample testing"

        return BacktestAssessment(
            best_strategy=best_strategy,
            robustness_signal=robustness_signal,
            benchmark_comparison=benchmark_comparison,
            overall_edge_signal=overall_edge_signal,
        )

    @staticmethod
    def _expert_summary(assessment: BacktestAssessment, regime_label: str, validation_rate: float) -> str:
        return (
            f"Backtest regime: {regime_label} ({validation_rate:.0%} of strategies validated OOS). "
            f"{assessment.best_strategy}. {assessment.overall_edge_signal}."
        )

    @staticmethod
    def _market_signals(strategies: list[StrategyResult]) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        for s in sorted(strategies, key=lambda x: x.out_of_sample_sharpe, reverse=True):
            if not s.stable or s.edge_vs_benchmark_pct <= 0:
                continue
            signals.append({
                "sector": f"{s.strategy_name} — {s.symbol}",
                "tickers": [s.symbol],
                "bias": "BULLISH" if s.out_of_sample_win_rate >= 0.5 else "BEARISH",
                "reason": (
                    f"Backtest validated: Sharpe {s.out_of_sample_sharpe:+.2f}, "
                    f"OOS win rate {s.out_of_sample_win_rate:.0%}, "
                    f"edge {s.edge_vs_benchmark_pct:+.2f}% vs buy-and-hold"
                ),
            })
            if len(signals) >= 5:
                break
        return signals

    @staticmethod
    def _recommendations(strategies: list[StrategyResult], assessment: BacktestAssessment) -> list[str]:
        recs: list[str] = []
        validated = [s for s in strategies if s.stable]
        for s in sorted(validated, key=lambda x: x.out_of_sample_sharpe, reverse=True)[:5]:
            recs.append(
                f"{s.strategy_name} on {s.symbol}: {s.verdict}"
            )
        if not validated and strategies:
            recs.append(
                "No tested strategy survived out-of-sample validation — treat in-sample "
                "signals as noise until backtested edge is confirmed."
            )
        recs.append(assessment.robustness_signal)
        recs.append(assessment.benchmark_comparison)
        return recs

    def analyze(self) -> BacktestingReport:
        return_map: dict[str, list[float]] = {}
        for symbol in self.watchlist:
            closes = self._fetch_closes(symbol)
            if closes:
                return_map[symbol] = self._daily_returns(closes)
            time.sleep(self.delay_seconds)

        if BENCHMARK not in return_map:
            raise RuntimeError("Unable to fetch SPY data for backtesting analysis")

        strategies: list[StrategyResult] = []
        for symbol, returns in return_map.items():
            for rule_id, spec in SIGNAL_LIBRARY.items():
                result = walk_forward_backtest(rule_id, symbol, returns, spec["fn"])
                if result:
                    strategies.append(self._to_strategy_result(result, spec["name"]))

        assessment = self._assessment(strategies)
        validated_count = sum(1 for s in strategies if s.stable)
        tested_count = len(strategies)
        validation_rate = round(validated_count / tested_count, 4) if tested_count else 0.0

        regime_label = (
            "Backtest-Validated" if validation_rate >= 0.35 else
            "Backtest-Mixed" if validation_rate >= 0.15 else
            "Backtest-Unvalidated"
        )

        summary = self._expert_summary(assessment, regime_label, validation_rate)
        signals = self._market_signals(strategies)
        recs = self._recommendations(strategies, assessment)

        return BacktestingReport(
            strategies=strategies,
            assessment=assessment,
            tested_count=tested_count,
            validated_count=validated_count,
            validation_rate=validation_rate,
            regime_label=regime_label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source="Yahoo Finance (1yr daily, walk-forward backtest)",
        )

    def to_dict(self, report: BacktestingReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Backtesting Expert",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
                "strategies_catalog": [s["id"] for s in BACKTEST_STRATEGIES],
            },
            "backtest_strategies": BACKTEST_STRATEGIES,
            "results": [
                {
                    "rule_id": s.rule_id,
                    "strategy_name": s.strategy_name,
                    "symbol": s.symbol,
                    "in_sample_trades": s.in_sample_trades,
                    "in_sample_win_rate": s.in_sample_win_rate,
                    "out_of_sample_trades": s.out_of_sample_trades,
                    "out_of_sample_win_rate": s.out_of_sample_win_rate,
                    "out_of_sample_sharpe": s.out_of_sample_sharpe,
                    "out_of_sample_max_drawdown_pct": s.out_of_sample_max_drawdown_pct,
                    "out_of_sample_profit_factor": s.out_of_sample_profit_factor,
                    "benchmark_return_pct": s.benchmark_return_pct,
                    "edge_vs_benchmark_pct": s.edge_vs_benchmark_pct,
                    "stable": s.stable,
                    "verdict": s.verdict,
                }
                for s in report.strategies
            ],
            "backtest_assessment": {
                "best_strategy": a.best_strategy,
                "robustness_signal": a.robustness_signal,
                "benchmark_comparison": a.benchmark_comparison,
                "overall_edge_signal": a.overall_edge_signal,
            },
            "metrics": {
                "tested_count": report.tested_count,
                "validated_count": report.validated_count,
                "validation_rate": report.validation_rate,
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
            catalog = output.parent / "backtest_strategies.json"
            catalog.write_text(json.dumps(BACKTEST_STRATEGIES, indent=2), encoding="utf-8")
        return result


def run_backtesting_analysis(output: Path | None = None) -> dict[str, Any]:
    return BacktestingExpert().run(output=output)
