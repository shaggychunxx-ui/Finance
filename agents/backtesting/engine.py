"""
Shared Backtesting Engine
=========================
Reusable walk-forward backtesting primitives shared across Finance agents.

Rather than trusting a raw in-sample win rate, agents that generate trading
signals (momentum, mean reversion, breakouts, etc.) can run those signals
through this engine to get a chronological, out-of-sample validated read on
whether the signal actually has an edge: win rate, Sharpe ratio, max
drawdown, profit factor, and edge versus a simple buy-and-hold benchmark.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Callable, Sequence

EntryFn = Callable[[Sequence[float], int], bool]

TRADING_DAYS_PER_YEAR = 252


@dataclass
class BacktestMetrics:
    """Performance metrics computed from a sequence of realized trade returns."""

    trades: int
    win_rate: float
    avg_return_pct: float
    total_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    profit_factor: float
    best_trade_pct: float
    worst_trade_pct: float


EMPTY_METRICS = BacktestMetrics(
    trades=0,
    win_rate=0.0,
    avg_return_pct=0.0,
    total_return_pct=0.0,
    sharpe_ratio=0.0,
    max_drawdown_pct=0.0,
    profit_factor=0.0,
    best_trade_pct=0.0,
    worst_trade_pct=0.0,
)


@dataclass
class WalkForwardResult:
    """In-sample vs. out-of-sample comparison for a single signal rule."""

    rule_id: str
    symbol: str
    in_sample: BacktestMetrics
    out_of_sample: BacktestMetrics
    benchmark_return_pct: float
    edge_vs_benchmark_pct: float
    stable: bool
    verdict: str


def _compound(returns: Sequence[float]) -> float:
    total = 1.0
    for r in returns:
        total *= (1 + r)
    return total


def compute_metrics(trade_returns: list[float]) -> BacktestMetrics:
    """Compute standard backtest metrics from realized trade returns (fractional)."""
    if not trade_returns:
        return EMPTY_METRICS

    trades = len(trade_returns)
    wins = [r for r in trade_returns if r > 0]
    losses = [r for r in trade_returns if r <= 0]
    win_rate = round(len(wins) / trades, 4)
    avg_return = statistics.mean(trade_returns)

    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in trade_returns:
        equity *= (1 + r)
        peak = max(peak, equity)
        drawdown = (equity - peak) / peak if peak > 0 else 0.0
        max_dd = min(max_dd, drawdown)

    std = statistics.stdev(trade_returns) if trades > 1 else 0.0
    sharpe = round((avg_return / std) * math.sqrt(TRADING_DAYS_PER_YEAR), 4) if std > 0 else 0.0

    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    if gross_loss > 0:
        profit_factor = round(gross_win / gross_loss, 4)
    else:
        profit_factor = round(gross_win, 4) if gross_win > 0 else 0.0

    return BacktestMetrics(
        trades=trades,
        win_rate=win_rate,
        avg_return_pct=round(avg_return * 100, 4),
        total_return_pct=round((equity - 1.0) * 100, 2),
        sharpe_ratio=sharpe,
        max_drawdown_pct=round(max_dd * 100, 2),
        profit_factor=profit_factor,
        best_trade_pct=round(max(trade_returns) * 100, 2),
        worst_trade_pct=round(min(trade_returns) * 100, 2),
    )


def walk_forward_backtest(
    rule_id: str,
    symbol: str,
    returns: list[float],
    entry_fn: EntryFn,
    train_ratio: float = 0.7,
    min_in_sample_trades: int = 10,
    min_out_of_sample_trades: int = 5,
) -> WalkForwardResult | None:
    """Walk forward through `returns`, applying `entry_fn(returns, i)` at each index.

    When the signal fires at index ``i`` the trade's realized return is
    ``returns[i]``. Results are split chronologically into an in-sample
    training segment and an out-of-sample holdout segment (``train_ratio``)
    so a strategy is only treated as validated when it holds up on data it
    was not tuned against — the essence of backtesting discipline.

    Args:
        rule_id: Identifier for the signal rule being tested.
        symbol: Ticker symbol the returns series belongs to.
        returns: Chronological daily return series (fractional, e.g. 0.01 = 1%).
        entry_fn: Callable ``(returns, i) -> bool`` returning True when the
            signal fires at index ``i``.
        train_ratio: Fraction (0-1) of the series used for the in-sample
            training segment; the remainder is the out-of-sample holdout.
        min_in_sample_trades: Minimum number of in-sample trades required
            before a strategy can be considered for validation.
        min_out_of_sample_trades: Minimum number of out-of-sample trades
            required before a strategy can be considered for validation.
    """
    if len(returns) < 40:
        return None

    split = int(len(returns) * train_ratio)
    train, test = returns[:split], returns[split:]

    def collect_trades(rets: list[float]) -> list[float]:
        return [rets[i] for i in range(len(rets)) if entry_fn(rets, i)]

    in_metrics = compute_metrics(collect_trades(train))
    out_metrics = compute_metrics(collect_trades(test))

    benchmark_return_pct = round((_compound(test) - 1.0) * 100, 2) if test else 0.0
    edge = round(out_metrics.total_return_pct - benchmark_return_pct, 2)

    stable = (
        in_metrics.trades >= min_in_sample_trades
        and out_metrics.trades >= min_out_of_sample_trades
        and abs(in_metrics.win_rate - out_metrics.win_rate) <= 0.15
        and out_metrics.profit_factor >= 1.0
    )

    if stable and out_metrics.sharpe_ratio > 0:
        verdict = (
            f"validated — {out_metrics.win_rate:.0%} OOS win rate, "
            f"Sharpe {out_metrics.sharpe_ratio:+.2f}, edge {edge:+.2f}% vs buy-and-hold"
        )
    elif in_metrics.win_rate >= 0.55:
        verdict = (
            f"in-sample edge {in_metrics.win_rate:.0%} did not survive out-of-sample testing "
            f"(OOS win rate {out_metrics.win_rate:.0%}, Sharpe {out_metrics.sharpe_ratio:+.2f})"
        )
    else:
        verdict = f"no reliable edge — in-sample win rate {in_metrics.win_rate:.0%}"

    return WalkForwardResult(
        rule_id=rule_id,
        symbol=symbol,
        in_sample=in_metrics,
        out_of_sample=out_metrics,
        benchmark_return_pct=benchmark_return_pct,
        edge_vs_benchmark_pct=edge,
        stable=stable,
        verdict=verdict,
    )


# --- Reusable signal library -------------------------------------------------

def momentum_signal(returns: Sequence[float], i: int, lookback: int = 5) -> bool:
    """True when the trailing `lookback`-day cumulative return is positive.

    Args:
        returns: Chronological daily return series.
        i: Index at which to evaluate the signal.
        lookback: Number of trailing days used to compute the cumulative return.
    """
    if i < lookback:
        return False
    window = returns[i - lookback:i]
    return _compound(window) - 1 > 0


def mean_reversion_signal(returns: Sequence[float], i: int, down_days: int = 2) -> bool:
    """True after `down_days` consecutive negative-return days.

    Args:
        returns: Chronological daily return series.
        i: Index at which to evaluate the signal.
        down_days: Number of consecutive prior negative-return days required.
    """
    if i < down_days:
        return False
    return all(returns[i - k] < 0 for k in range(1, down_days + 1))


def breakout_signal(returns: Sequence[float], i: int, lookback: int = 20, z_threshold: float = 1.0) -> bool:
    """True when the prior day's return is a volatility breakout vs. its trailing window.

    Args:
        returns: Chronological daily return series.
        i: Index at which to evaluate the signal.
        lookback: Number of days in the trailing window used to compute the
            mean and standard deviation used for the z-score.
        z_threshold: Minimum z-score (standard deviations from the trailing
            mean) the prior day's return must exceed to fire the signal.
    """
    if i < lookback + 1:
        return False
    window = returns[i - lookback - 1:i - 1]
    if len(window) < 2:
        return False
    mean = statistics.mean(window)
    std = statistics.stdev(window)
    if std <= 0:
        return False
    z = (returns[i - 1] - mean) / std
    return z > z_threshold


SIGNAL_LIBRARY: dict[str, dict[str, Any]] = {
    "momentum_5d": {
        "name": "5-Day Momentum",
        "description": "Enter when trailing 5-day cumulative return is positive; expect continuation.",
        "fn": momentum_signal,
    },
    "mean_reversion_2d": {
        "name": "2-Day Mean Reversion",
        "description": "Enter after 2 consecutive down days; expect a bounce.",
        "fn": mean_reversion_signal,
    },
    "volatility_breakout": {
        "name": "Volatility Breakout",
        "description": (
            "Enter after a >1 std-dev single-day move relative to the trailing "
            "20-day window; expect follow-through."
        ),
        "fn": breakout_signal,
    },
}
