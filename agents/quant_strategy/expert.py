"""
Quant Strategy Architect Expert Agent
=====================================
Quantitative risk architecture across financial mathematics, asset-class
microstructure, and micro-level/algorithmic execution mechanics:

* Risk-of-Ruin (symmetric gambler's-ruin and asymmetric characteristic-root form)
* Dynamic ATR-based position sizing
* Statistical-arbitrage pairs trading (OLS cointegration + spread Z-score)
* Volume Weighted Average Price (VWAP) deviation
* A static playbook catalog of asset-class microstructure and execution
  strategies (Spot FX, index futures, equities, scalping, momentum,
  mean reversion, adverse selection, stop hunting, spoofing)

Data: Yahoo Finance chart API (6-month daily OHLCV history).
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
HEADERS = {"User-Agent": "Finance-Quant-Strategy/1.0 (shaggychunxx@gmail.com)"}

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

# Candidate cointegrated pairs for statistical arbitrage (Y regressed on X).
PAIRS: list[tuple[str, str, str]] = [
    ("XLE", "XOP", "Energy Sector vs Exploration & Production"),
    ("GLD", "SLV", "Gold vs Silver"),
    ("XLF", "KRE", "Broad Financials vs Regional Banks"),
]

# Fixed risk parameters used for the position-sizing / risk-of-ruin scenarios.
ACCOUNT_BALANCE = 100_000.0
RISK_PCT = 0.01          # 1.0% risk per trade
ATR_MULTIPLIER = 2.0     # k
ATR_LOOKBACK = 14
ZSCORE_LOOKBACK = 20
ZSCORE_ENTRY = 2.0

STRATEGY_FORMULAS: list[dict[str, Any]] = [
    {
        "id": "risk_of_ruin_symmetric",
        "name": "Risk-of-Ruin (Symmetric, R=1)",
        "description": "Terminal drawdown-to-zero probability for a fixed risk-per-trade, R=1 payoff",
        "formula": "RoR = ((1-(W-L)) / (1+(W-L)))^U = (L/W)^U",
    },
    {
        "id": "risk_of_ruin_asymmetric",
        "name": "Risk-of-Ruin (Asymmetric, R≠1)",
        "description": "Characteristic-root random-walk solution for non-symmetric win/loss payoffs",
        "formula": "W·x^(R+1) - x + L = 0, root x0 ∈ (0,1); RoR = x0^U",
    },
    {
        "id": "dynamic_position_size",
        "name": "Dynamic Position Sizing (ATR)",
        "description": "Position size scaled to account risk budget and volatility (ATR) stop distance",
        "formula": "Size = (C · R%) / (k · ATR_N)",
    },
    {
        "id": "pairs_zscore",
        "name": "Statistical Arbitrage Spread Z-Score",
        "description": "OLS cointegration spread standardized against its rolling mean/stdev",
        "formula": "Z_t = (ε_t - μ_ε) / σ_ε, where ln(Y_t) = β·ln(X_t) + α + ε_t",
    },
    {
        "id": "vwap",
        "name": "Volume Weighted Average Price",
        "description": "Institutional valuation anchor weighting price by traded volume",
        "formula": "VWAP = Σ(P_i · V_i) / Σ(V_i)",
    },
]

MICROSTRUCTURE_PLAYBOOK: list[dict[str, Any]] = [
    {
        "id": "spot_fx",
        "asset_class": "Spot FX",
        "structure": "Decentralized OTC network (banks, prime brokers, ECNs)",
        "matching": "ECN match engine — no central tape",
        "notes": "No unified public tape; Tom-Next rollover applies to positions held past 17:00 EST",
    },
    {
        "id": "index_futures",
        "asset_class": "Index Futures (CME)",
        "structure": "Central limit order book, single central counterparty",
        "matching": "FIFO time-price priority, Level 3 transparency",
        "notes": "Intraday performance-bond margining levers a small cash outlay against full notional exposure",
    },
    {
        "id": "equities",
        "asset_class": "Equities (NYSE/NASDAQ)",
        "structure": "Fragmented lit exchanges, dark pools, and wholesale internalizers",
        "matching": "Reg NMS Rule 611 order-protection router to the NBBO",
        "notes": "SIP consolidates Tape A (NYSE), Tape B (regional/NYSE American), Tape C (NASDAQ); PFOF routes retail flow to wholesalers",
    },
]

EXECUTION_STRATEGIES: list[dict[str, Any]] = [
    {
        "id": "order_book_scalping",
        "name": "High-Frequency Order Book Scalping",
        "mechanism": "Trade immediately ahead of large passive block orders acting as short-term price barriers",
        "risk": "Loss triggered instantly if the protective block is cancelled or aggressively consumed",
    },
    {
        "id": "momentum_catalyst",
        "name": "Momentum Catalyst Trading",
        "mechanism": "Opening Range Breakout on high RVOL (>300%) names driven by a news catalyst",
        "risk": "Stop at VWAP or the opening-range midpoint",
    },
    {
        "id": "mean_reversion_overextension",
        "name": "Mean Reversion via Statistical Overextension",
        "mechanism": "Fade price outside the 3σ Bollinger Band with RSI >85 or <15 on order-flow exhaustion",
        "risk": "Stop above/below the exhaustion candle extreme; target rolling VWAP",
    },
    {
        "id": "adverse_selection",
        "name": "Adverse Selection (Winner's Curse)",
        "mechanism": "Passive limit orders fill precisely when informed institutional flow moves the market against the resting order",
        "risk": "Immediate open loss upon fill",
    },
    {
        "id": "stop_hunting",
        "name": "Algorithmic Stop Hunting",
        "mechanism": "Sweep price through a cluster of resting retail stop-losses just beyond visual support/resistance",
        "risk": "Forced liquidity absorbed by institutions before a rapid reversal",
    },
    {
        "id": "spoofing",
        "name": "Wash Trading & Order Book Spoofing",
        "mechanism": "Phantom large orders create a false wall of supply/demand, then are cancelled once opposite hidden orders fill",
        "risk": "Illegal manipulation — violates the Dodd-Frank Wall Street Reform Act",
    },
]


@dataclass
class RiskOfRuinScenario:
    symbol: str
    win_rate: float
    reward_ratio: float
    units_available: float
    root_x0: float
    ror: float
    stressed_units: float
    stressed_ror: float
    interpretation: str


@dataclass
class PositionSizing:
    symbol: str
    price: float
    atr: float
    stop_distance: float
    position_size: float
    notional_exposure: float
    risk_dollars: float
    interpretation: str


@dataclass
class PairsSignal:
    pair_label: str
    symbol_y: str
    symbol_x: str
    beta: float
    alpha: float
    zscore: float
    signal: str
    interpretation: str


@dataclass
class VwapDeviation:
    symbol: str
    price: float
    vwap: float
    deviation_pct: float
    signal: str


@dataclass
class QuantAssessment:
    ruin_signal: str
    sizing_signal: str
    pairs_signal: str
    vwap_signal: str
    conclusion: str


@dataclass
class QuantStrategyReport:
    ruin_scenarios: list[RiskOfRuinScenario]
    position_sizing: list[PositionSizing]
    pairs_signals: list[PairsSignal]
    vwap_deviations: list[VwapDeviation]
    assessment: QuantAssessment
    risk_architecture_score: float
    regime_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class QuantStrategyExpert:
    """Quant strategist — risk-of-ruin, volatility sizing, stat-arb, and execution architecture."""

    def __init__(self, delay_seconds: float = 0.3) -> None:
        self.delay_seconds = delay_seconds

    def _fetch_ohlcv(self, symbol: str) -> dict[str, list[float]]:
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
            quote = resp.json()["chart"]["result"][0]["indicators"]["quote"][0]
            highs = quote.get("high") or []
            lows = quote.get("low") or []
            closes = quote.get("close") or []
            volumes = quote.get("volume") or []
            n = min(len(highs), len(lows), len(closes), len(volumes))
            rows = [
                (highs[i], lows[i], closes[i], volumes[i])
                for i in range(n)
                if None not in (highs[i], lows[i], closes[i], volumes[i])
            ]
            if not rows:
                return {}
            return {
                "high": [float(r[0]) for r in rows],
                "low": [float(r[1]) for r in rows],
                "close": [float(r[2]) for r in rows],
                "volume": [float(r[3]) for r in rows],
            }
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Core math
    # ------------------------------------------------------------------

    @staticmethod
    def _daily_returns(closes: list[float]) -> list[float]:
        return [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]

    @staticmethod
    def _win_rate_and_reward_ratio(returns: list[float]) -> tuple[float, float]:
        wins = [r for r in returns if r > 0]
        losses = [-r for r in returns if r < 0]
        w = len(wins) / len(returns) if returns else 0.5
        w = min(max(w, 0.01), 0.99)
        avg_win = statistics.mean(wins) if wins else 1e-6
        avg_loss = statistics.mean(losses) if losses else 1e-6
        r = avg_win / avg_loss if avg_loss > 0 else 1.0
        return round(w, 4), round(max(r, 0.01), 4)

    @staticmethod
    def _ruin_root(w: float, r: float, tol: float = 1e-9, max_iter: int = 200) -> float:
        """Bisection root-find of W·x^(R+1) - x + L = 0 for x0 ∈ (0,1)."""
        l = 1.0 - w
        if abs(r - 1.0) < 1e-9:
            return l / w if w > 0 else 1.0

        def f(x: float) -> float:
            return w * (x ** (r + 1.0)) - x + l

        lo, hi = 1e-9, 1.0 - 1e-9
        f_lo, f_hi = f(lo), f(hi)
        if f_lo * f_hi > 0:
            # Fall back to the symmetric approximation if no sign change is found.
            return min(max(l / w, 1e-9), 1.0 - 1e-9)
        for _ in range(max_iter):
            mid = (lo + hi) / 2.0
            f_mid = f(mid)
            if abs(f_mid) < tol:
                return mid
            if f_lo * f_mid < 0:
                hi, f_hi = mid, f_mid
            else:
                lo, f_lo = mid, f_mid
        return (lo + hi) / 2.0

    def _risk_of_ruin(self, symbol: str, returns: list[float]) -> RiskOfRuinScenario:
        w, r = self._win_rate_and_reward_ratio(returns)
        units = round(1.0 / RISK_PCT, 2)
        x0 = self._ruin_root(w, r)
        ror = round(min(x0 ** units, 1.0), 6)
        stressed_units = round(units / 4.0, 2)
        stressed_ror = round(min(x0 ** stressed_units, 1.0), 6)
        if ror < 0.02:
            note = "capital depth provides a statistically negligible chance of terminal ruin"
        elif ror < 0.15:
            note = "ruin probability is moderate — maintain strict risk-per-trade discipline"
        else:
            note = "ruin probability is elevated — reduce risk-per-trade or reward ratio is unfavorable"
        return RiskOfRuinScenario(
            symbol=symbol,
            win_rate=w,
            reward_ratio=r,
            units_available=units,
            root_x0=round(x0, 6),
            ror=ror,
            stressed_units=stressed_units,
            stressed_ror=stressed_ror,
            interpretation=note,
        )

    @staticmethod
    def _atr(highs: list[float], lows: list[float], closes: list[float], n: int = ATR_LOOKBACK) -> float:
        trs: list[float] = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            trs.append(tr)
        if not trs:
            return 0.0
        window = trs[-n:] if len(trs) >= n else trs
        return statistics.mean(window)

    def _position_sizing(self, symbol: str, ohlcv: dict[str, list[float]]) -> PositionSizing | None:
        closes = ohlcv.get("close", [])
        highs = ohlcv.get("high", [])
        lows = ohlcv.get("low", [])
        if len(closes) < 2:
            return None
        price = closes[-1]
        atr = self._atr(highs, lows, closes)
        if atr <= 0:
            return None
        stop_distance = round(ATR_MULTIPLIER * atr, 4)
        risk_dollars = ACCOUNT_BALANCE * RISK_PCT
        position_size = round(risk_dollars / stop_distance, 2)
        notional = round(position_size * price, 2)
        note = (
            f"stop distance ${stop_distance:.2f} ({ATR_MULTIPLIER}× ATR{ATR_LOOKBACK}) sizes "
            f"{position_size:.0f} units for ${risk_dollars:,.0f} at-risk (${notional:,.0f} notional)"
        )
        return PositionSizing(
            symbol=symbol,
            price=round(price, 2),
            atr=round(atr, 4),
            stop_distance=stop_distance,
            position_size=position_size,
            notional_exposure=notional,
            risk_dollars=round(risk_dollars, 2),
            interpretation=note,
        )

    @staticmethod
    def _ols(y: list[float], x: list[float]) -> tuple[float, float]:
        n = len(y)
        mean_x, mean_y = statistics.mean(x), statistics.mean(y)
        cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
        var_x = sum((xi - mean_x) ** 2 for xi in x)
        beta = cov / var_x if var_x > 0 else 0.0
        alpha = mean_y - beta * mean_x
        return round(beta, 6), round(alpha, 6)

    def _pairs_signal(
        self, label: str, symbol_y: str, symbol_x: str,
        closes_y: list[float], closes_x: list[float],
    ) -> PairsSignal | None:
        n = min(len(closes_y), len(closes_x))
        if n < ZSCORE_LOOKBACK + 5:
            return None
        ln_y = [math.log(c) for c in closes_y[-n:]]
        ln_x = [math.log(c) for c in closes_x[-n:]]
        beta, alpha = self._ols(ln_y, ln_x)
        spread = [ln_y[i] - (beta * ln_x[i] + alpha) for i in range(n)]
        window = spread[-ZSCORE_LOOKBACK:]
        mu = statistics.mean(window)
        sigma = statistics.stdev(window) if len(window) > 1 else 1e-9
        z = (spread[-1] - mu) / sigma if sigma > 0 else 0.0
        z = round(z, 4)
        if z > ZSCORE_ENTRY:
            signal = "SHORT_SPREAD"
            note = f"Z={z:+.2f} > +{ZSCORE_ENTRY} — sell {symbol_y}, buy {symbol_x} (overextended upward)"
        elif z < -ZSCORE_ENTRY:
            signal = "LONG_SPREAD"
            note = f"Z={z:+.2f} < -{ZSCORE_ENTRY} — buy {symbol_y}, sell {symbol_x} (overextended downward)"
        elif abs(z) < 0.2:
            signal = "CONVERGED"
            note = f"Z={z:+.2f} ≈ 0 — spread has mean-reverted, unwind positions"
        else:
            signal = "NEUTRAL"
            note = f"Z={z:+.2f} within normal band — no entry signal"
        return PairsSignal(
            pair_label=label,
            symbol_y=symbol_y,
            symbol_x=symbol_x,
            beta=beta,
            alpha=alpha,
            zscore=z,
            signal=signal,
            interpretation=note,
        )

    def _vwap_deviation(self, symbol: str, ohlcv: dict[str, list[float]]) -> VwapDeviation | None:
        highs, lows, closes, volumes = (
            ohlcv.get("high", []), ohlcv.get("low", []), ohlcv.get("close", []), ohlcv.get("volume", []),
        )
        n = min(len(highs), len(lows), len(closes), len(volumes))
        if n < ZSCORE_LOOKBACK:
            return None
        window = range(n - ZSCORE_LOOKBACK, n)
        typical = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in window]
        vols = [volumes[i] for i in window]
        total_vol = sum(vols)
        if total_vol <= 0:
            return None
        vwap = sum(t * v for t, v in zip(typical, vols)) / total_vol
        price = closes[-1]
        deviation_pct = round(((price - vwap) / vwap) * 100.0, 3) if vwap else 0.0
        if deviation_pct > 3.0:
            signal = "ABOVE_VWAP_EXTENDED"
        elif deviation_pct < -3.0:
            signal = "BELOW_VWAP_EXTENDED"
        else:
            signal = "NEAR_VWAP"
        return VwapDeviation(
            symbol=symbol,
            price=round(price, 2),
            vwap=round(vwap, 4),
            deviation_pct=deviation_pct,
            signal=signal,
        )

    def _assessment(
        self,
        ruin: list[RiskOfRuinScenario],
        sizing: list[PositionSizing],
        pairs: list[PairsSignal],
        vwaps: list[VwapDeviation],
    ) -> QuantAssessment:
        elevated = [r for r in ruin if r.ror >= 0.15]
        ruin_sig = (
            f"{len(elevated)}/{len(ruin)} watchlist assets show elevated risk-of-ruin at 1% risk-per-trade"
            if elevated else
            f"all {len(ruin)} watchlist assets keep risk-of-ruin below 15% at 1% risk-per-trade"
        )
        sizing_sig = (
            f"ATR-scaled sizing spans {min(s.position_size for s in sizing):.0f}-"
            f"{max(s.position_size for s in sizing):.0f} units across the watchlist"
            if sizing else "insufficient OHLCV history for ATR sizing"
        )
        active_pairs = [p for p in pairs if p.signal in ("SHORT_SPREAD", "LONG_SPREAD")]
        pairs_sig = (
            "; ".join(f"{p.pair_label}: {p.signal}" for p in active_pairs)
            if active_pairs else "no pairs currently outside the ±2.0 Z-score entry band"
        )
        extended = [v for v in vwaps if v.signal != "NEAR_VWAP"]
        vwap_sig = (
            "; ".join(f"{v.symbol} {v.deviation_pct:+.2f}% vs VWAP" for v in extended)
            if extended else "watchlist trading close to volume-weighted fair value"
        )
        if active_pairs or extended:
            conclusion = "active statistical-arbitrage and mean-reversion opportunities detected"
        elif elevated:
            conclusion = "risk architecture requires tightening — reduce size on elevated ruin-risk names"
        else:
            conclusion = "risk architecture within tolerance — no immediate rebalancing required"
        return QuantAssessment(
            ruin_signal=ruin_sig,
            sizing_signal=sizing_sig,
            pairs_signal=pairs_sig,
            vwap_signal=vwap_sig,
            conclusion=conclusion,
        )

    def _expert_summary(self, assessment: QuantAssessment, label: str, score: float) -> str:
        return (
            f"Quant strategy architecture scan: {label} (risk architecture score {score:.2f}). "
            f"{assessment.ruin_signal}. {assessment.sizing_signal}. "
            f"{assessment.pairs_signal}. {assessment.vwap_signal}. {assessment.conclusion}."
        )

    def analyze(self) -> QuantStrategyReport:
        ohlcv_map: dict[str, dict[str, list[float]]] = {}
        for symbol in WATCHLIST:
            data = self._fetch_ohlcv(symbol)
            if data:
                ohlcv_map[symbol] = data
            time.sleep(self.delay_seconds)

        pair_symbols = {s for pair in PAIRS for s in (pair[0], pair[1])}
        for symbol in pair_symbols:
            if symbol not in ohlcv_map:
                data = self._fetch_ohlcv(symbol)
                if data:
                    ohlcv_map[symbol] = data
                time.sleep(self.delay_seconds)

        if BENCHMARK not in ohlcv_map:
            raise RuntimeError("Unable to fetch SPY data for quant strategy analysis")

        ruin_scenarios: list[RiskOfRuinScenario] = []
        sizing: list[PositionSizing] = []
        vwaps: list[VwapDeviation] = []
        for symbol in WATCHLIST:
            data = ohlcv_map.get(symbol)
            if not data:
                continue
            returns = self._daily_returns(data["close"])
            if returns:
                ruin_scenarios.append(self._risk_of_ruin(symbol, returns))
            ps = self._position_sizing(symbol, data)
            if ps:
                sizing.append(ps)
            vw = self._vwap_deviation(symbol, data)
            if vw:
                vwaps.append(vw)

        pairs_signals: list[PairsSignal] = []
        for symbol_y, symbol_x, label in PAIRS:
            data_y, data_x = ohlcv_map.get(symbol_y), ohlcv_map.get(symbol_x)
            if not data_y or not data_x:
                continue
            sig = self._pairs_signal(label, symbol_y, symbol_x, data_y["close"], data_x["close"])
            if sig:
                pairs_signals.append(sig)

        assessment = self._assessment(ruin_scenarios, sizing, pairs_signals, vwaps)

        low_ruin = sum(1 for r in ruin_scenarios if r.ror < 0.15)
        active_pairs = sum(1 for p in pairs_signals if p.signal in ("SHORT_SPREAD", "LONG_SPREAD"))
        near_vwap = sum(1 for v in vwaps if v.signal == "NEAR_VWAP")
        risk_architecture_score = round(
            0.5 * (low_ruin / max(len(ruin_scenarios), 1))
            + 0.25 * (near_vwap / max(len(vwaps), 1))
            + 0.25 * min(1.0, active_pairs / max(len(pairs_signals), 1) + 0.5),
            4,
        )
        if risk_architecture_score >= 0.75:
            regime_label = "Risk Architecture Sound"
        elif risk_architecture_score >= 0.5:
            regime_label = "Mixed Risk Architecture"
        else:
            regime_label = "Risk Architecture Stressed"

        summary = self._expert_summary(assessment, regime_label, risk_architecture_score)
        signals = self._market_signals(ruin_scenarios, pairs_signals, vwaps)
        recs = self._recommendations(assessment, ruin_scenarios, sizing, pairs_signals, vwaps)

        return QuantStrategyReport(
            ruin_scenarios=ruin_scenarios,
            position_sizing=sizing,
            pairs_signals=pairs_signals,
            vwap_deviations=vwaps,
            assessment=assessment,
            risk_architecture_score=risk_architecture_score,
            regime_label=regime_label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source="Yahoo Finance API",
        )

    @staticmethod
    def _market_signals(
        ruin: list[RiskOfRuinScenario],
        pairs: list[PairsSignal],
        vwaps: list[VwapDeviation],
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        for p in pairs:
            if p.signal in ("SHORT_SPREAD", "LONG_SPREAD"):
                bias = "BEARISH" if p.signal == "SHORT_SPREAD" else "BULLISH"
                signals.append({
                    "sector": f"Pairs Trade — {p.pair_label}",
                    "tickers": [p.symbol_y, p.symbol_x],
                    "bias": bias,
                    "reason": p.interpretation,
                })
        for v in vwaps:
            if v.signal != "NEAR_VWAP":
                bias = "BEARISH" if v.signal == "ABOVE_VWAP_EXTENDED" else "BULLISH"
                signals.append({
                    "sector": f"VWAP Mean Reversion — {v.symbol}",
                    "tickers": [v.symbol],
                    "bias": bias,
                    "reason": f"price {v.deviation_pct:+.2f}% from 20d VWAP (${v.vwap:.2f})",
                })
        elevated = [r for r in ruin if r.ror >= 0.15]
        for r in elevated[:3]:
            signals.append({
                "sector": f"Elevated Risk-of-Ruin — {r.symbol}",
                "tickers": [r.symbol],
                "bias": "NEUTRAL",
                "reason": f"RoR≈{r.ror * 100:.1f}% at U={r.units_available:.0f} units (W={r.win_rate}, R={r.reward_ratio})",
            })
        if not signals:
            signals.append({
                "sector": "Quant Risk Architecture Neutral",
                "tickers": [BENCHMARK],
                "bias": "NEUTRAL",
                "reason": "no pairs, VWAP extremes, or elevated ruin risk detected",
            })
        return signals

    @staticmethod
    def _recommendations(
        assessment: QuantAssessment,
        ruin: list[RiskOfRuinScenario],
        sizing: list[PositionSizing],
        pairs: list[PairsSignal],
        vwaps: list[VwapDeviation],
    ) -> list[str]:
        recs = [
            assessment.ruin_signal,
            assessment.sizing_signal,
            assessment.pairs_signal,
            assessment.vwap_signal,
            assessment.conclusion,
        ]
        for r in sorted(ruin, key=lambda x: -x.ror)[:4]:
            recs.append(
                f"{r.symbol} RoR: x0={r.root_x0}, RoR(U={r.units_available:.0f})={r.ror * 100:.2f}%, "
                f"stressed RoR(U={r.stressed_units:.0f})={r.stressed_ror * 100:.2f}% — {r.interpretation}"
            )
        for s in sizing[:4]:
            recs.append(f"{s.symbol} sizing: {s.interpretation}")
        for p in pairs:
            recs.append(f"{p.pair_label}: β={p.beta}, Z={p.zscore:+.2f} — {p.interpretation}")
        for v in vwaps:
            if v.signal != "NEAR_VWAP":
                recs.append(f"{v.symbol}: {v.deviation_pct:+.2f}% vs 20d VWAP ${v.vwap:.2f} — {v.signal}")
        return recs

    def to_dict(self, report: QuantStrategyReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Quant Strategy Architect Expert",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
                "account_balance": ACCOUNT_BALANCE,
                "risk_pct": RISK_PCT,
                "atr_multiplier": ATR_MULTIPLIER,
                "formulas_applied": [f["id"] for f in STRATEGY_FORMULAS],
            },
            "strategy_formulas": STRATEGY_FORMULAS,
            "microstructure_playbook": MICROSTRUCTURE_PLAYBOOK,
            "execution_strategies": EXECUTION_STRATEGIES,
            "risk_of_ruin": [
                {
                    "symbol": r.symbol,
                    "win_rate": r.win_rate,
                    "reward_ratio": r.reward_ratio,
                    "units_available": r.units_available,
                    "root_x0": r.root_x0,
                    "ror": r.ror,
                    "stressed_units": r.stressed_units,
                    "stressed_ror": r.stressed_ror,
                    "interpretation": r.interpretation,
                }
                for r in report.ruin_scenarios
            ],
            "position_sizing": [
                {
                    "symbol": s.symbol,
                    "price": s.price,
                    "atr": s.atr,
                    "stop_distance": s.stop_distance,
                    "position_size": s.position_size,
                    "notional_exposure": s.notional_exposure,
                    "risk_dollars": s.risk_dollars,
                    "interpretation": s.interpretation,
                }
                for s in report.position_sizing
            ],
            "pairs_signals": [
                {
                    "pair_label": p.pair_label,
                    "symbol_y": p.symbol_y,
                    "symbol_x": p.symbol_x,
                    "beta": p.beta,
                    "alpha": p.alpha,
                    "zscore": p.zscore,
                    "signal": p.signal,
                    "interpretation": p.interpretation,
                }
                for p in report.pairs_signals
            ],
            "vwap_deviations": [
                {
                    "symbol": v.symbol,
                    "price": v.price,
                    "vwap": v.vwap,
                    "deviation_pct": v.deviation_pct,
                    "signal": v.signal,
                }
                for v in report.vwap_deviations
            ],
            "quant_assessment": {
                "ruin_signal": a.ruin_signal,
                "sizing_signal": a.sizing_signal,
                "pairs_signal": a.pairs_signal,
                "vwap_signal": a.vwap_signal,
                "conclusion": a.conclusion,
            },
            "metrics": {
                "risk_architecture_score": report.risk_architecture_score,
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
            catalog = output.parent / "quant_strategy_playbook.json"
            catalog.write_text(
                json.dumps(
                    {
                        "strategy_formulas": STRATEGY_FORMULAS,
                        "microstructure_playbook": MICROSTRUCTURE_PLAYBOOK,
                        "execution_strategies": EXECUTION_STRATEGIES,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        return result


def run_quant_strategy_analysis(output: Path | None = None) -> dict[str, Any]:
    return QuantStrategyExpert().run(output=output)
