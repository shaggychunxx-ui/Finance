"""
Dual-Force Momentum / Mean-Reversion Expert Agent
==================================================
Expert in blending trend-persistence (momentum) and overextension-correction
(mean reversion) anomalies via three structural architectures:

1. Multi-Timeframe Trend-Pullback — macro momentum filter (120d return +
   100-day EMA) gating a micro mean-reversion trigger (fast RSI(3) < 15),
   exited on SMA(10) normalization, a -5% hard stop, or a 5-day time stop.
2. Statistical Arbitrage with Momentum Overlay — cointegrated-pair spread
   z-score reversion trades, only permitted when spread momentum (a
   close-only ADX proxy) has exhausted below 20.
3. Regime-Switching Matrix — Efficiency Ratio + rolling volatility trend
   route capital between momentum and mean-reversion systems.

Data: Yahoo Finance chart API (2-year daily history).
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

from agents.base import BaseExpert

BENCHMARK = "SPY"
WATCHLIST = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "IWM": "Russell 2000",
    "XLK": "Technology",
    "XLE": "Energy",
    "XLF": "Financials",
    "GLD": "Gold",
    "TLT": "Treasuries",
}

# Cointegration-style candidate pairs referenced by Architecture 2.
STAT_ARB_PAIRS: list[tuple[str, str]] = [
    ("KO", "PEP"),
    ("XOM", "CVX"),
]

# System configuration mirrors the quantitative testing blueprint.
LOOKBACK_MOMENTUM = 120
LOOKBACK_REVERSION = 3
EMA_TREND_FILTER = 100
RSI_OVERSOLD_LIMIT = 15.0
EXIT_MA_WINDOW = 10
HARD_STOP_PCT = -0.05
TIME_STOP_BARS = 5
REGIME_ER_WINDOW = 20
REGIME_VOL_WINDOW = 20
PAIR_LOOKBACK = 60
ADX_WINDOW = 14
DRAWDOWN_CIRCUIT_BREAKER_PCT = 0.07
VOL_RISING_THRESHOLD = 1.02
VOL_DECLINING_THRESHOLD = 0.98

# Regime-Switching Matrix thresholds (Efficiency Ratio + capital allocation split).
ER_MOMENTUM_THRESHOLD = 0.6
ER_REVERSION_THRESHOLD = 0.3
FULL_ALLOCATION_PCT = 100.0
NO_ALLOCATION_PCT = 0.0
SPLIT_ALLOCATION_PCT = 50.0

# Statistical Arbitrage with Momentum Overlay thresholds.
ADX_BLOCKED_THRESHOLD = 30
ADX_ALLOWED_THRESHOLD = 20
ZSCORE_TRADE_THRESHOLD = 2.0

# Backtest signal-confidence z-score parameter (fixed input to quant_signal_confidence).
DEFAULT_ZSCORE_SIGNAL = -1.5

# Evidence score weights (base term keeps the score away from zero when data is thin).
EVIDENCE_ENTRY_WEIGHT = 0.35
EVIDENCE_WIN_RATE_WEIGHT = 0.30
EVIDENCE_STAT_ARB_WEIGHT = 0.20
EVIDENCE_BASE_TERM = 0.15
EVIDENCE_CIRCUIT_BREAKER_PENALTY = 0.25

DUAL_FORCE_PLAYBOOK: list[dict[str, Any]] = [
    {
        "id": "trend_pullback",
        "name": "Multi-Timeframe Trend-Pullback Setup",
        "description": (
            "Momentum as macro filter (price > 120d ago and > 100-day EMA), "
            "mean reversion as micro entry trigger (RSI(3) < 15), exit on SMA(10) "
            "normalization, -5% hard stop, or 5-day time stop."
        ),
    },
    {
        "id": "stat_arb_momentum_overlay",
        "name": "Statistical Arbitrage with Momentum Overlay",
        "description": (
            "Spread = Price(A) - beta*Price(B). Trade the z-score reversion only "
            "when spread ADX < 20 (momentum exhausted); block entries when ADX > 30 "
            "(spread trending, mean-reversion failure mode risk)."
        ),
    },
    {
        "id": "regime_switching_matrix",
        "name": "Regime-Switching Matrix",
        "description": (
            "Efficiency Ratio (ER) + rolling volatility trend gate capital allocation: "
            "ER > 0.6 and rising volatility routes 100% to momentum; ER < 0.3 and "
            "declining volatility routes 100% to mean reversion."
        ),
    },
    {
        "id": "drawdown_circuit_breaker",
        "name": "Maximum Drawdown Circuit Breaker",
        "description": (
            "If the momentum sub-portfolio equity curve draws down 7% peak-to-trough, "
            "allocation is cut in half and frozen in cash rather than handed to the "
            "mean-reversion system."
        ),
    },
    {
        "id": "time_based_stop",
        "name": "Time-Based Stop (Liquidity Exit)",
        "description": (
            "Mean-reversion positions stuck for more than 5 trading days without "
            "hitting a price stop are forcefully liquidated to avoid tying up capital "
            "in an asset undergoing a structural shift."
        ),
    },
]

RISK_PROFILE_TABLE: list[dict[str, str]] = [
    {
        "risk_dimension": "Market Regime Failure",
        "momentum_system": "Whipsawed heavily during sideways consolidation.",
        "mean_reversion_system": "Decimated during runaway, uncorrected vertical trends.",
        "combined_portfolio_impact": "Balanced. One system offsets the organic losses of the other.",
    },
    {
        "risk_dimension": "Win Rate Character",
        "momentum_system": "Low win rate (35%-40%), but massive average gains per win.",
        "mean_reversion_system": "High win rate (65%-75%), but small average gains per win.",
        "combined_portfolio_impact": "Smoothed equity curve with higher overall Sharpe and Sortino ratios.",
    },
    {
        "risk_dimension": "Fat-Tail Event Vulnerability",
        "momentum_system": "Suffers during flash crashes or sudden macro pivot points.",
        "mean_reversion_system": "Suffers when an asset gaps down overnight and never recovers.",
        "combined_portfolio_impact": "Requires strict, independent stop-loss structures to protect capital.",
    },
]


@dataclass
class TrendPullbackTrade:
    entry_index: int
    exit_index: int
    entry_price: float
    exit_price: float
    return_pct: float
    exit_reason: str


@dataclass
class TrendPullbackBacktest:
    symbol: str
    trades: int
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    max_drawdown_pct: float
    time_stop_exits: int
    circuit_breaker_triggered: bool
    macro_filter_intact: bool
    rsi_fast: float | None
    current_status: str


@dataclass
class RegimeMetric:
    symbol: str
    efficiency_ratio: float
    volatility_20d: float
    volatility_trend: str
    regime_label: str
    momentum_allocation_pct: float
    mean_reversion_allocation_pct: float


@dataclass
class StatArbSignal:
    pair: tuple[str, str]
    beta: float
    spread_zscore: float
    adx_proxy: float | None
    momentum_overlay: str
    trade_signal: str


@dataclass
class DualForceAssessment:
    trend_pullback_signal: str
    regime_signal: str
    stat_arb_signal: str
    defense_signal: str
    combined_edge: str


@dataclass
class DualForceReport:
    backtests: list[TrendPullbackBacktest]
    regimes: list[RegimeMetric]
    pairs: list[StatArbSignal]
    assessment: DualForceAssessment
    evidence_score: float
    regime_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def calculate_ema(closes: list[float], window: int) -> list[float | None]:
    n = len(closes)
    result: list[float | None] = [None] * n
    if n < window:
        return result
    multiplier = 2.0 / (window + 1)
    seed = sum(closes[:window]) / window
    result[window - 1] = seed
    for i in range(window, n):
        prev = result[i - 1]
        result[i] = (closes[i] - prev) * multiplier + prev
    return result


def calculate_sma(closes: list[float], window: int) -> list[float | None]:
    n = len(closes)
    result: list[float | None] = [None] * n
    for i in range(window - 1, n):
        result[i] = sum(closes[i - window + 1: i + 1]) / window
    return result


def calculate_rsi(closes: list[float], window: int) -> list[float | None]:
    n = len(closes)
    result: list[float | None] = [None] * n
    if n <= window:
        return result
    gains = []
    losses = []
    for i in range(1, n):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    def _rsi_from(avg_gain: float, avg_loss: float) -> float:
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    avg_gain = sum(gains[:window]) / window
    avg_loss = sum(losses[:window]) / window
    result[window] = _rsi_from(avg_gain, avg_loss)
    for i in range(window, len(gains)):
        avg_gain = (avg_gain * (window - 1) + gains[i]) / window
        avg_loss = (avg_loss * (window - 1) + losses[i]) / window
        result[i + 1] = _rsi_from(avg_gain, avg_loss)
    return result


def calculate_adx_proxy(values: list[float], window: int = ADX_WINDOW) -> float | None:
    """Close-only ADX approximation (no intraday high/low available)."""
    n = len(values)
    if n < window * 2:
        return None
    diffs = [values[i] - values[i - 1] for i in range(1, n)]
    plus_dm = [max(d, 0.0) for d in diffs]
    minus_dm = [max(-d, 0.0) for d in diffs]
    tr = [abs(d) for d in diffs]

    def _dx(sp: float, sm: float, str_: float) -> float:
        if str_ == 0:
            return 0.0
        di_plus = 100.0 * sp / str_
        di_minus = 100.0 * sm / str_
        denom = di_plus + di_minus
        return 100.0 * abs(di_plus - di_minus) / denom if denom > 0 else 0.0

    smoothed_plus = sum(plus_dm[:window])
    smoothed_minus = sum(minus_dm[:window])
    smoothed_tr = sum(tr[:window])
    dx_values = [_dx(smoothed_plus, smoothed_minus, smoothed_tr)]
    for i in range(window, len(diffs)):
        smoothed_plus = smoothed_plus - smoothed_plus / window + plus_dm[i]
        smoothed_minus = smoothed_minus - smoothed_minus / window + minus_dm[i]
        smoothed_tr = smoothed_tr - smoothed_tr / window + tr[i]
        dx_values.append(_dx(smoothed_plus, smoothed_minus, smoothed_tr))
    if len(dx_values) < window:
        return round(dx_values[-1], 2) if dx_values else None
    adx = sum(dx_values[:window]) / window
    for i in range(window, len(dx_values)):
        adx = (adx * (window - 1) + dx_values[i]) / window
    return round(adx, 2)


class MomentumReversionExpert(BaseExpert):
    """Expert in blended momentum + mean-reversion structural architectures."""

    def __init__(
        self,
        delay_seconds: float = 0.3,
        *,
        pipeline_context: dict | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="momentum-reversion")
        self.delay_seconds = delay_seconds

    def _trend_pullback_backtest(self, symbol: str, closes: list[float]) -> TrendPullbackBacktest | None:
        n = len(closes)
        if n <= LOOKBACK_MOMENTUM + EMA_TREND_FILTER:
            return None

        ema_trend = calculate_ema(closes, EMA_TREND_FILTER)
        sma_exit = calculate_sma(closes, EXIT_MA_WINDOW)
        rsi_fast = calculate_rsi(closes, LOOKBACK_REVERSION)

        trades: list[TrendPullbackTrade] = []
        position: dict[str, Any] | None = None
        equity = 1.0
        peak = 1.0
        max_dd = 0.0
        time_stop_exits = 0

        for i in range(LOOKBACK_MOMENTUM, n):
            price = closes[i]
            if ema_trend[i] is None or sma_exit[i] is None or rsi_fast[i] is None:
                continue
            historical_momentum = closes[i] - closes[i - LOOKBACK_MOMENTUM]

            if position is None:
                if price > ema_trend[i] and historical_momentum > 0 and rsi_fast[i] < RSI_OVERSOLD_LIMIT:
                    position = {"entry_index": i, "entry_price": price}
                continue

            bars_held = i - position["entry_index"]
            exit_reason = None
            if price >= sma_exit[i]:
                exit_reason = "reversion_normalized"
            elif price <= position["entry_price"] * (1 + HARD_STOP_PCT):
                exit_reason = "hard_stop"
            elif bars_held > TIME_STOP_BARS:
                exit_reason = "time_stop"

            if exit_reason:
                ret = (price - position["entry_price"]) / position["entry_price"]
                trades.append(TrendPullbackTrade(
                    entry_index=position["entry_index"],
                    exit_index=i,
                    entry_price=position["entry_price"],
                    exit_price=price,
                    return_pct=round(ret * 100, 3),
                    exit_reason=exit_reason,
                ))
                if exit_reason == "time_stop":
                    time_stop_exits += 1
                equity *= (1 + ret)
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak if peak > 0 else 0.0)
                position = None

        wins = [t for t in trades if t.return_pct > 0]
        losses = [t for t in trades if t.return_pct <= 0]
        win_rate = round(len(wins) / len(trades), 4) if trades else 0.0
        avg_win = round(statistics.fmean([t.return_pct for t in wins]), 3) if wins else 0.0
        avg_loss = round(statistics.fmean([t.return_pct for t in losses]), 3) if losses else 0.0

        macro_intact = bool(
            ema_trend[-1] is not None
            and len(closes) > LOOKBACK_MOMENTUM
            and closes[-1] > ema_trend[-1]
            and (closes[-1] - closes[-LOOKBACK_MOMENTUM]) > 0
        )
        latest_rsi = rsi_fast[-1]

        if position is not None:
            current_status = "OPEN_LONG_POSITION"
        elif macro_intact and latest_rsi is not None and latest_rsi < RSI_OVERSOLD_LIMIT:
            current_status = "ENTRY_SIGNAL"
        elif macro_intact:
            current_status = "MACRO_INTACT_AWAITING_TRIGGER"
        else:
            current_status = "MACRO_FILTER_FAILED"

        return TrendPullbackBacktest(
            symbol=symbol,
            trades=len(trades),
            win_rate=win_rate,
            avg_win_pct=avg_win,
            avg_loss_pct=avg_loss,
            max_drawdown_pct=round(max_dd * 100, 3),
            time_stop_exits=time_stop_exits,
            circuit_breaker_triggered=max_dd >= DRAWDOWN_CIRCUIT_BREAKER_PCT,
            macro_filter_intact=macro_intact,
            rsi_fast=round(latest_rsi, 2) if latest_rsi is not None else None,
            current_status=current_status,
        )

    @staticmethod
    def _daily_returns(closes: list[float]) -> list[float]:
        return [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]

    def _regime_metric(self, symbol: str, closes: list[float]) -> RegimeMetric | None:
        if len(closes) <= REGIME_ER_WINDOW * 2 + 1:
            return None
        tail = closes[-(REGIME_ER_WINDOW + 1):]
        net = abs(tail[-1] - tail[0])
        total = sum(abs(tail[k] - tail[k - 1]) for k in range(1, len(tail)))
        efficiency_ratio = round(net / total, 4) if total > 0 else 0.0

        returns = self._daily_returns(closes)
        vol_window = returns[-REGIME_VOL_WINDOW:]
        vol_prior = returns[-2 * REGIME_VOL_WINDOW:-REGIME_VOL_WINDOW]
        vol_now = statistics.pstdev(vol_window) * math.sqrt(252) if len(vol_window) >= 2 else 0.0
        vol_before = statistics.pstdev(vol_prior) * math.sqrt(252) if len(vol_prior) >= 2 else vol_now

        if vol_now > vol_before * VOL_RISING_THRESHOLD:
            vol_trend = "rising"
        elif vol_now < vol_before * VOL_DECLINING_THRESHOLD:
            vol_trend = "declining"
        else:
            vol_trend = "flat"

        if efficiency_ratio > ER_MOMENTUM_THRESHOLD and vol_trend == "rising":
            label = "Breakout Momentum Regime"
            momentum_pct, reversion_pct = FULL_ALLOCATION_PCT, NO_ALLOCATION_PCT
        elif efficiency_ratio < ER_REVERSION_THRESHOLD and vol_trend == "declining":
            label = "Mean-Reverting Chop Regime"
            momentum_pct, reversion_pct = NO_ALLOCATION_PCT, FULL_ALLOCATION_PCT
        else:
            label = "Transitional / Mixed Regime"
            momentum_pct, reversion_pct = SPLIT_ALLOCATION_PCT, SPLIT_ALLOCATION_PCT

        return RegimeMetric(
            symbol=symbol,
            efficiency_ratio=efficiency_ratio,
            volatility_20d=round(vol_now * 100, 3),
            volatility_trend=vol_trend,
            regime_label=label,
            momentum_allocation_pct=momentum_pct,
            mean_reversion_allocation_pct=reversion_pct,
        )

    @staticmethod
    def _ols_beta(a_vals: list[float], b_vals: list[float]) -> float:
        n = len(a_vals)
        mean_a = sum(a_vals) / n
        mean_b = sum(b_vals) / n
        cov = sum((a_vals[i] - mean_a) * (b_vals[i] - mean_b) for i in range(n))
        var_b = sum((b_vals[i] - mean_b) ** 2 for i in range(n))
        return cov / var_b if var_b > 0 else 1.0

    def _stat_arb_signal(self, symbol_a: str, symbol_b: str, closes_a: list[float], closes_b: list[float]) -> StatArbSignal | None:
        n = min(len(closes_a), len(closes_b))
        if n <= PAIR_LOOKBACK * 2:
            return None
        a_vals = closes_a[-n:]
        b_vals = closes_b[-n:]

        beta = self._ols_beta(a_vals[-PAIR_LOOKBACK:], b_vals[-PAIR_LOOKBACK:])
        spread = [a_vals[i] - beta * b_vals[i] for i in range(n)]

        recent_spread = spread[-PAIR_LOOKBACK:]
        mean_spread = statistics.fmean(recent_spread)
        std_spread = statistics.pstdev(recent_spread)
        z_score = round((spread[-1] - mean_spread) / std_spread, 3) if std_spread > 0 else 0.0

        adx_proxy = calculate_adx_proxy(spread)
        if adx_proxy is not None and adx_proxy > ADX_BLOCKED_THRESHOLD:
            momentum_overlay = "BLOCKED"
        elif adx_proxy is not None and adx_proxy < ADX_ALLOWED_THRESHOLD:
            momentum_overlay = "ALLOWED"
        else:
            momentum_overlay = "CAUTION"

        if momentum_overlay == "ALLOWED" and z_score >= ZSCORE_TRADE_THRESHOLD:
            trade_signal = f"SHORT_{symbol_a}_LONG_{symbol_b}"
        elif momentum_overlay == "ALLOWED" and z_score <= -ZSCORE_TRADE_THRESHOLD:
            trade_signal = f"LONG_{symbol_a}_SHORT_{symbol_b}"
        else:
            trade_signal = "NO_TRADE"

        return StatArbSignal(
            pair=(symbol_a, symbol_b),
            beta=round(beta, 4),
            spread_zscore=z_score,
            adx_proxy=adx_proxy,
            momentum_overlay=momentum_overlay,
            trade_signal=trade_signal,
        )

    def _assessment(
        self,
        backtests: list[TrendPullbackBacktest],
        regimes: list[RegimeMetric],
        pairs: list[StatArbSignal],
    ) -> DualForceAssessment:
        entries = [b for b in backtests if b.current_status in ("ENTRY_SIGNAL", "OPEN_LONG_POSITION")]
        breakers = [b for b in backtests if b.circuit_breaker_triggered]
        trend_signal = (
            f"{len(entries)}/{len(backtests)} symbols show an active trend-pullback setup"
            if backtests else "No trend-pullback backtests available"
        )

        momentum_regimes = [r for r in regimes if r.momentum_allocation_pct > 50]
        reversion_regimes = [r for r in regimes if r.mean_reversion_allocation_pct > 50]
        regime_signal = (
            f"{len(momentum_regimes)} symbols favor momentum, {len(reversion_regimes)} favor mean reversion, "
            f"{len(regimes) - len(momentum_regimes) - len(reversion_regimes)} transitional"
        )

        active_pairs = [p for p in pairs if p.trade_signal != "NO_TRADE"]
        stat_arb_signal = (
            f"{len(active_pairs)}/{len(pairs)} pairs cleared the momentum overlay for a reversion trade"
            if pairs else "No statistical arbitrage pairs available"
        )

        defense_signal = (
            f"{len(breakers)} symbol(s) breached the {DRAWDOWN_CIRCUIT_BREAKER_PCT:.0%} drawdown circuit breaker"
            if breakers else "No drawdown circuit breaker triggers detected"
        )

        if entries and momentum_regimes and not breakers:
            combined_edge = "Momentum and mean-reversion engines are aligned with risk controls intact"
        elif breakers:
            combined_edge = "Risk controls engaged — capital defensively routed to cash"
        else:
            combined_edge = "Mixed signal — no strong dual-force alignment currently present"

        return DualForceAssessment(
            trend_pullback_signal=trend_signal,
            regime_signal=regime_signal,
            stat_arb_signal=stat_arb_signal,
            defense_signal=defense_signal,
            combined_edge=combined_edge,
        )

    def _expert_summary(self, assessment: DualForceAssessment, regime_label: str, evidence_score: float) -> str:
        return (
            f"Dual-force regime: {regime_label} (evidence {evidence_score}). "
            f"{assessment.trend_pullback_signal}. {assessment.regime_signal}. "
            f"{assessment.stat_arb_signal}. {assessment.defense_signal}. "
            f"Edge: {assessment.combined_edge}."
        )

    def _market_signals(
        self,
        backtests: list[TrendPullbackBacktest],
        regimes: list[RegimeMetric],
        pairs: list[StatArbSignal],
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal, quant_signal_confidence

        signals: list[dict[str, Any]] = []
        for b in backtests:
            if b.current_status not in ("ENTRY_SIGNAL", "OPEN_LONG_POSITION"):
                continue
            conf = quant_signal_confidence(
                momentum=1.0 if b.macro_filter_intact else 0.4,
                mc_prob_up=b.win_rate,
                z_score=DEFAULT_ZSCORE_SIGNAL,
            )
            signals.append(build_market_signal(
                sector=f"{b.symbol} Trend-Pullback",
                tickers=[b.symbol],
                bias="BULLISH",
                reason=(
                    f"{b.symbol}: macro uptrend intact, RSI(3)={b.rsi_fast} triggered a mean-reversion entry "
                    f"(historical win rate {b.win_rate:.0%} over {b.trades} trades)."
                ),
                confidence=conf,
                evidence={
                    "trades": b.trades,
                    "win_rate": b.win_rate,
                    "max_drawdown_pct": b.max_drawdown_pct,
                    "current_status": b.current_status,
                },
            ))

        for r in regimes:
            if r.regime_label == "Transitional / Mixed Regime":
                continue
            bias = "BULLISH" if r.momentum_allocation_pct > 50 else "NEUTRAL"
            signals.append(build_market_signal(
                sector=f"{r.symbol} Regime",
                tickers=[r.symbol],
                bias=bias,
                reason=(
                    f"{r.symbol}: ER={r.efficiency_ratio}, volatility {r.volatility_trend} — "
                    f"{r.regime_label}, allocate {r.momentum_allocation_pct:.0f}% momentum / "
                    f"{r.mean_reversion_allocation_pct:.0f}% mean reversion."
                ),
                confidence=0.55 + min(0.3, abs(r.efficiency_ratio - 0.45)),
            ))

        for p in pairs:
            if p.trade_signal == "NO_TRADE":
                continue
            symbol_a, symbol_b = p.pair
            signals.append(build_market_signal(
                sector=f"{symbol_a}/{symbol_b} Stat Arb",
                tickers=[symbol_a, symbol_b],
                bias="NEUTRAL",
                reason=(
                    f"{symbol_a}/{symbol_b} spread z-score {p.spread_zscore} with ADX proxy {p.adx_proxy} "
                    f"(momentum overlay {p.momentum_overlay}) — {p.trade_signal}."
                ),
                confidence=0.55,
            ))

        return signals

    def _recommendations(
        self,
        backtests: list[TrendPullbackBacktest],
        regimes: list[RegimeMetric],
        pairs: list[StatArbSignal],
    ) -> list[str]:
        recs: list[str] = []
        for b in backtests:
            if b.current_status == "ENTRY_SIGNAL":
                recs.append(
                    f"{b.symbol}: RSI(3) oversold within an intact 100-day EMA uptrend — "
                    f"trend-pullback entry candidate (historical win rate {b.win_rate:.0%})."
                )
            elif b.current_status == "OPEN_LONG_POSITION":
                recs.append(f"{b.symbol}: hold open trend-pullback position until SMA(10) or a risk stop triggers.")
            if b.circuit_breaker_triggered:
                recs.append(
                    f"{b.symbol}: backtested drawdown breached {DRAWDOWN_CIRCUIT_BREAKER_PCT:.0%} — "
                    "halve allocation and freeze in cash per the drawdown circuit breaker."
                )
            if b.time_stop_exits:
                recs.append(
                    f"{b.symbol}: {b.time_stop_exits} historical trade(s) hit the 5-day time stop — "
                    "monitor for structural shifts rather than pure liquidity dislocations."
                )

        for r in regimes:
            if r.regime_label == "Breakout Momentum Regime":
                recs.append(f"{r.symbol}: {r.regime_label} — deactivate mean-reversion systems, favor breakout momentum.")
            elif r.regime_label == "Mean-Reverting Chop Regime":
                recs.append(f"{r.symbol}: {r.regime_label} — lock down momentum models, favor short-term support/resistance reversion.")

        for p in pairs:
            symbol_a, symbol_b = p.pair
            if p.momentum_overlay == "BLOCKED":
                recs.append(f"{symbol_a}/{symbol_b}: spread ADX proxy > 30 — momentum overlay blocks the mean-reversion trade (failure-mode risk).")
            elif p.trade_signal != "NO_TRADE":
                recs.append(f"{symbol_a}/{symbol_b}: {p.trade_signal} — spread z-score {p.spread_zscore} with momentum exhausted (ADX proxy {p.adx_proxy}).")

        if not recs:
            recs.append("No dual-force setups currently active — continue monitoring the watchlist for regime shifts.")
        return recs

    def analyze(self) -> DualForceReport:
        from agents.probability_market_data import ProbabilityMarketData

        pmd = ProbabilityMarketData(self)
        self._pmd = pmd
        watchlist = pmd.prepare_watchlist(WATCHLIST)
        pmd.request_enhancement(watchlist)

        close_map: dict[str, list[float]] = {}
        for symbol in watchlist:
            closes = self.fetch_yahoo_closes(symbol, range_="2y", interval="1d")
            if closes:
                close_map[symbol] = closes
            time.sleep(self.delay_seconds)

        if BENCHMARK not in close_map:
            raise RuntimeError("Unable to fetch SPY data for momentum-reversion analysis")

        backtests: list[TrendPullbackBacktest] = []
        regimes: list[RegimeMetric] = []
        for symbol, closes in close_map.items():
            bt = self._trend_pullback_backtest(symbol, closes)
            if bt:
                backtests.append(bt)
            regime = self._regime_metric(symbol, closes)
            if regime:
                regimes.append(regime)

        pairs: list[StatArbSignal] = []
        for symbol_a, symbol_b in STAT_ARB_PAIRS:
            closes_a = self.fetch_yahoo_closes(symbol_a, range_="2y", interval="1d")
            time.sleep(self.delay_seconds)
            closes_b = self.fetch_yahoo_closes(symbol_b, range_="2y", interval="1d")
            time.sleep(self.delay_seconds)
            if not closes_a or not closes_b:
                continue
            sig = self._stat_arb_signal(symbol_a, symbol_b, closes_a, closes_b)
            if sig:
                pairs.append(sig)

        assessment = self._assessment(backtests, regimes, pairs)

        entry_ratio = (
            sum(1 for b in backtests if b.current_status in ("ENTRY_SIGNAL", "OPEN_LONG_POSITION")) / len(backtests)
            if backtests else 0.0
        )
        avg_win_rate = statistics.fmean([b.win_rate for b in backtests]) if backtests else 0.5
        breaker_penalty = EVIDENCE_CIRCUIT_BREAKER_PENALTY if any(b.circuit_breaker_triggered for b in backtests) else 0.0
        stat_arb_ratio = (
            sum(1 for p in pairs if p.trade_signal != "NO_TRADE") / len(pairs) if pairs else 0.0
        )
        evidence_score = round(max(0.0, min(1.0,
            EVIDENCE_ENTRY_WEIGHT * entry_ratio
            + EVIDENCE_WIN_RATE_WEIGHT * avg_win_rate
            + EVIDENCE_STAT_ARB_WEIGHT * stat_arb_ratio
            + EVIDENCE_BASE_TERM
            - breaker_penalty
        )), 4)

        momentum_regimes = sum(1 for r in regimes if r.momentum_allocation_pct > 50)
        reversion_regimes = sum(1 for r in regimes if r.mean_reversion_allocation_pct > 50)
        if momentum_regimes > reversion_regimes:
            regime_label = "Momentum-Favored"
        elif reversion_regimes > momentum_regimes:
            regime_label = "Mean-Reversion-Favored"
        else:
            regime_label = "Balanced Dual-Force"

        summary = self._expert_summary(assessment, regime_label, evidence_score)
        signals = self._market_signals(backtests, regimes, pairs)
        signals.extend(pmd.live_market_signals())
        recs = self._recommendations(backtests, regimes, pairs)

        return DualForceReport(
            backtests=backtests,
            regimes=regimes,
            pairs=pairs,
            assessment=assessment,
            evidence_score=evidence_score,
            regime_label=regime_label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source="Yahoo Finance API",
        )

    def to_dict(self, report: DualForceReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Dual-Force Momentum / Mean-Reversion Expert",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
                "architectures": [p["id"] for p in DUAL_FORCE_PLAYBOOK],
            },
            "dual_force_playbook": DUAL_FORCE_PLAYBOOK,
            "risk_profile_table": RISK_PROFILE_TABLE,
            "trend_pullback_backtests": [
                {
                    "symbol": b.symbol,
                    "trades": b.trades,
                    "win_rate": b.win_rate,
                    "avg_win_pct": b.avg_win_pct,
                    "avg_loss_pct": b.avg_loss_pct,
                    "max_drawdown_pct": b.max_drawdown_pct,
                    "time_stop_exits": b.time_stop_exits,
                    "circuit_breaker_triggered": b.circuit_breaker_triggered,
                    "macro_filter_intact": b.macro_filter_intact,
                    "rsi_fast": b.rsi_fast,
                    "current_status": b.current_status,
                }
                for b in report.backtests
            ],
            "regime_metrics": [
                {
                    "symbol": r.symbol,
                    "efficiency_ratio": r.efficiency_ratio,
                    "volatility_20d_pct": r.volatility_20d,
                    "volatility_trend": r.volatility_trend,
                    "regime_label": r.regime_label,
                    "momentum_allocation_pct": r.momentum_allocation_pct,
                    "mean_reversion_allocation_pct": r.mean_reversion_allocation_pct,
                }
                for r in report.regimes
            ],
            "stat_arb_signals": [
                {
                    "pair": list(p.pair),
                    "beta": p.beta,
                    "spread_zscore": p.spread_zscore,
                    "adx_proxy": p.adx_proxy,
                    "momentum_overlay": p.momentum_overlay,
                    "trade_signal": p.trade_signal,
                }
                for p in report.pairs
            ],
            "dual_force_assessment": {
                "trend_pullback_signal": a.trend_pullback_signal,
                "regime_signal": a.regime_signal,
                "stat_arb_signal": a.stat_arb_signal,
                "defense_signal": a.defense_signal,
                "combined_edge": a.combined_edge,
            },
            "metrics": {
                "evidence_score": report.evidence_score,
                "regime_label": report.regime_label,
            },
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if getattr(self, "_pmd", None):
            self._pmd.attach_to_result(result)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "dual_force_playbook.json"
            catalog.write_text(
                json.dumps({"architectures": DUAL_FORCE_PLAYBOOK, "risk_profile_table": RISK_PROFILE_TABLE}, indent=2),
                encoding="utf-8",
            )
        return result


def run_momentum_reversion_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return MomentumReversionExpert(pipeline_context=pipeline_context).run(output=output)
