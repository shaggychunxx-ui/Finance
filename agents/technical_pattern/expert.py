"""
Technical Analysis & Pattern Recognition Agent — "The Execution Mapper"
=========================================================================
Mission: define precise mathematical coordinate boundaries — exactly where
to buy, where to set structural stop-losses, and where profit targets rest.

API interfacing: streams daily OHLCV bars from the Yahoo Finance chart API
(the same low-latency-friendly bar structure exposed by streaming platforms
such as Polygon.io / Alpaca) for a diversified watchlist.

Mathematical processing — dual-layer analysis:
  1. Traditional Indicator Layer — EMA(9/21/50) cross-timeframe alignment,
     Wilder RSI (with bullish/bearish divergence vs price), and Average
     True Range (ATR) for volatility-scaled risk.
  2. Geometric Layer — swing-high/swing-low pivot detection mapped into
     support/resistance bands (clustered price levels = "liquidity pools").

How it ensures accuracy: even if an asset is fundamentally cheap and
sentiment is hot, this agent only green-lights an entry when price sits at
a high-probability technical coordinate (near support, aligned EMAs, RSI not
extended), and always emits a structural stop-loss and profit target so the
final trade has a defined risk-to-reward ratio.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agents.base import BaseExpert

CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Finance-Technical-Pattern/1.0 (shaggychunxx@gmail.com)"}

WATCHLIST: dict[str, str] = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "AAPL": "Mega-cap tech",
    "NVDA": "AI/semiconductor",
    "TSLA": "High-beta EV",
    "AMD": "Semiconductor",
    "IWM": "Russell 2000",
    "XLE": "Energy sector",
}

RSI_PERIOD = 14
ATR_PERIOD = 14
EMA_FAST, EMA_MID, EMA_SLOW = 9, 21, 50
PIVOT_WINDOW = 3  # bars on each side to confirm a swing high/low
SR_CLUSTER_PCT = 1.5  # pivots within this % of each other cluster into one band
RSI_OVERBOUGHT, RSI_OVERSOLD = 70.0, 30.0
STOP_ATR_MULTIPLE = 1.5
TARGET_RR_MULTIPLE = 2.0  # profit target expressed as risk-to-reward multiple


@dataclass
class SupportResistanceBand:
    level: float
    kind: str  # "support" | "resistance"
    touches: int


@dataclass
class TechnicalSnapshot:
    symbol: str
    name: str
    last_close: float
    ema_fast: float
    ema_mid: float
    ema_slow: float
    ema_alignment: str
    rsi: float
    rsi_divergence: str
    atr: float
    atr_pct: float
    support_bands: list[float]
    resistance_bands: list[float]
    entry_zone: float | None
    stop_loss: float | None
    profit_target: float | None
    risk_reward: float | None
    entry_grade: str
    rationale: str


@dataclass
class TechnicalPatternReport:
    snapshots: list[TechnicalSnapshot]
    high_probability_entries: list[str]
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TechnicalPatternExpert(BaseExpert):
    """The 'execution mapper' — indicator + geometric coordinates for entries/exits."""

    def __init__(self) -> None:
        super().__init__()

    # -- data fetching -------------------------------------------------
    def _fetch_ohlcv(self, symbol: str) -> dict[str, list[float]]:
        try:
            resp = requests.get(
                CHART_API.format(symbol=symbol),
                params={"interval": "1d", "range": "6mo"},
                headers=HEADERS,
                timeout=25,
            )
            resp.raise_for_status()
            quote = resp.json()["chart"]["result"][0]["indicators"]["quote"][0]
            rows = zip(
                quote.get("high", []), quote.get("low", []), quote.get("close", [])
            )
            highs, lows, closes = [], [], []
            for h, l, c in rows:
                if h is None or l is None or c is None:
                    continue
                highs.append(float(h))
                lows.append(float(l))
                closes.append(float(c))
            return {"high": highs, "low": lows, "close": closes}
        except Exception:
            return {"high": [], "low": [], "close": []}

    # -- traditional indicator layer -------------------------------------
    @staticmethod
    def _ema_series(values: list[float], period: int) -> list[float]:
        if not values:
            return []
        k = 2 / (period + 1)
        ema = [values[0]]
        for v in values[1:]:
            ema.append(v * k + ema[-1] * (1 - k))
        return ema

    @staticmethod
    def _rsi_series(closes: list[float], period: int = RSI_PERIOD) -> list[float]:
        if len(closes) < period + 1:
            return []
        gains, losses = [], []
        for i in range(1, len(closes)):
            change = closes[i] - closes[i - 1]
            gains.append(max(change, 0.0))
            losses.append(max(-change, 0.0))

        avg_gain = statistics.mean(gains[:period])
        avg_loss = statistics.mean(losses[:period])
        rsi_values = []
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            rs = avg_gain / avg_loss if avg_loss else float("inf")
            rsi = 100 - (100 / (1 + rs)) if avg_loss else 100.0
            rsi_values.append(rsi)
        return rsi_values

    @staticmethod
    def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = ATR_PERIOD) -> float:
        if len(closes) < 2:
            return 0.0
        true_ranges = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            true_ranges.append(tr)
        window = true_ranges[-period:] if len(true_ranges) >= period else true_ranges
        return statistics.mean(window) if window else 0.0

    def _rsi_divergence(self, closes: list[float], rsi_values: list[float]) -> str:
        lookback = min(20, len(rsi_values), len(closes) - 1)
        if lookback < 5:
            return "None"
        price_window = closes[-lookback:]
        rsi_window = rsi_values[-lookback:]
        price_trend = price_window[-1] - price_window[0]
        rsi_trend = rsi_window[-1] - rsi_window[0]
        if price_trend > 0 and rsi_trend < 0:
            return "Bearish divergence (price up, RSI down)"
        if price_trend < 0 and rsi_trend > 0:
            return "Bullish divergence (price down, RSI up)"
        return "None"

    # -- geometric layer ---------------------------------------------------
    @staticmethod
    def _find_pivots(highs: list[float], lows: list[float], window: int = PIVOT_WINDOW) -> tuple[list[float], list[float]]:
        swing_highs, swing_lows = [], []
        n = len(highs)
        for i in range(window, n - window):
            if highs[i] == max(highs[i - window : i + window + 1]):
                swing_highs.append(highs[i])
            if lows[i] == min(lows[i - window : i + window + 1]):
                swing_lows.append(lows[i])
        return swing_highs, swing_lows

    @staticmethod
    def _cluster_levels(levels: list[float], pct: float = SR_CLUSTER_PCT) -> list[SupportResistanceBand]:
        if not levels:
            return []
        levels = sorted(levels)
        clusters: list[list[float]] = [[levels[0]]]
        for lvl in levels[1:]:
            if abs(lvl - clusters[-1][-1]) / clusters[-1][-1] * 100 <= pct:
                clusters[-1].append(lvl)
            else:
                clusters.append([lvl])
        bands = [
            SupportResistanceBand(level=round(statistics.mean(c), 2), kind="", touches=len(c))
            for c in clusters
        ]
        bands.sort(key=lambda b: -b.touches)
        return bands

    def _analyze_symbol(self, symbol: str, name: str) -> TechnicalSnapshot | None:
        data = self._fetch_ohlcv(symbol)
        closes = data["close"]
        highs, lows = data["high"], data["low"]
        if len(closes) < 60:
            return None

        last_close = closes[-1]
        ema_fast = self._ema_series(closes, EMA_FAST)[-1]
        ema_mid = self._ema_series(closes, EMA_MID)[-1]
        ema_slow = self._ema_series(closes, EMA_SLOW)[-1]

        if ema_fast > ema_mid > ema_slow:
            ema_alignment = "Bullish stack (fast>mid>slow)"
        elif ema_fast < ema_mid < ema_slow:
            ema_alignment = "Bearish stack (fast<mid<slow)"
        else:
            ema_alignment = "Mixed/no clean trend alignment"

        rsi_values = self._rsi_series(closes)
        rsi = round(rsi_values[-1], 2) if rsi_values else 50.0
        rsi_divergence = self._rsi_divergence(closes, rsi_values)

        atr = self._atr(highs, lows, closes)
        atr_pct = round((atr / last_close) * 100, 2) if last_close else 0.0

        swing_highs, swing_lows = self._find_pivots(highs, lows)
        resistance_bands = [
            b.level for b in self._cluster_levels(swing_highs) if b.level > last_close
        ][:3]
        support_bands = [
            b.level for b in self._cluster_levels(swing_lows) if b.level < last_close
        ][:3]

        nearest_support = max(support_bands) if support_bands else None
        nearest_resistance = min(resistance_bands) if resistance_bands else None

        entry_zone = stop_loss = profit_target = risk_reward = None
        entry_grade = "No-Man's-Land"
        reasons = []

        near_support = (
            nearest_support is not None
            and (last_close - nearest_support) / last_close * 100 <= max(atr_pct * 1.5, 2.0)
        )
        trend_aligned = "Bullish stack" in ema_alignment
        rsi_not_extended = rsi < RSI_OVERBOUGHT

        if near_support and trend_aligned and rsi_not_extended:
            entry_zone = round(last_close, 2)
            stop_loss = round(nearest_support - atr * STOP_ATR_MULTIPLE * 0.5, 2)
            risk = entry_zone - stop_loss
            profit_target = round(entry_zone + risk * TARGET_RR_MULTIPLE, 2)
            risk_reward = TARGET_RR_MULTIPLE
            entry_grade = "High-Probability Entry"
            reasons.append("price at support with bullish EMA stack and RSI not overbought")
        elif trend_aligned and rsi_not_extended:
            entry_grade = "Watchlist (trend aligned, awaiting pullback to support)"
            reasons.append("bullish trend intact but price not yet at a support coordinate")
        elif rsi >= RSI_OVERBOUGHT:
            entry_grade = "Avoid (extended)"
            reasons.append(f"RSI {rsi} is overbought — chase risk too high")
        else:
            entry_grade = "No-Man's-Land"
            reasons.append("no clean confluence of trend, support, and RSI")

        if rsi_divergence != "None":
            reasons.append(rsi_divergence)

        return TechnicalSnapshot(
            symbol=symbol,
            name=name,
            last_close=round(last_close, 2),
            ema_fast=round(ema_fast, 2),
            ema_mid=round(ema_mid, 2),
            ema_slow=round(ema_slow, 2),
            ema_alignment=ema_alignment,
            rsi=rsi,
            rsi_divergence=rsi_divergence,
            atr=round(atr, 2),
            atr_pct=atr_pct,
            support_bands=support_bands,
            resistance_bands=resistance_bands,
            entry_zone=entry_zone,
            stop_loss=stop_loss,
            profit_target=profit_target,
            risk_reward=risk_reward,
            entry_grade=entry_grade,
            rationale="; ".join(reasons),
        )

    def _market_signals(self, snapshots: list[TechnicalSnapshot]) -> list[dict[str, Any]]:
        signals = []
        for s in snapshots:
            if s.entry_grade == "High-Probability Entry":
                signals.append(
                    {
                        "sector": s.name,
                        "bias": "bullish",
                        "tickers": [s.symbol],
                        "reason": (
                            f"Entry {s.entry_zone}, stop {s.stop_loss}, target {s.profit_target} "
                            f"(R:R {s.risk_reward}) — {s.rationale}"
                        ),
                    }
                )
        return signals

    def _recommendations(self, snapshots: list[TechnicalSnapshot]) -> list[str]:
        recs = []
        for s in snapshots:
            if s.entry_grade == "High-Probability Entry":
                recs.append(
                    f"{s.symbol}: buy {s.entry_zone}, stop {s.stop_loss}, target {s.profit_target}."
                )
            else:
                recs.append(f"{s.symbol}: {s.entry_grade} — {s.rationale}")
        return recs

    def analyze(self) -> TechnicalPatternReport:
        snapshots: list[TechnicalSnapshot] = []
        for symbol, name in WATCHLIST.items():
            snap = self._analyze_symbol(symbol, name)
            if snap:
                snapshots.append(snap)

        high_prob = [s.symbol for s in snapshots if s.entry_grade == "High-Probability Entry"]
        expert_summary = (
            f"Mapped {len(snapshots)} symbols across EMA/RSI/ATR indicators and "
            f"swing-pivot support/resistance geometry. {len(high_prob)} high-probability "
            "entry coordinate(s) identified."
        )

        return TechnicalPatternReport(
            snapshots=snapshots,
            high_probability_entries=high_prob,
            expert_summary=expert_summary,
            market_signals=self._market_signals(snapshots),
            recommendations=self._recommendations(snapshots),
            data_source="Yahoo Finance Chart API (6mo daily OHLCV)",
        )

    def to_dict(self, report: TechnicalPatternReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Technical Analysis & Pattern Recognition Agent (The Execution Mapper)",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
                "temperature": self.temperature,
            },
            "snapshots": [
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "last_close": s.last_close,
                    "ema_fast": s.ema_fast,
                    "ema_mid": s.ema_mid,
                    "ema_slow": s.ema_slow,
                    "ema_alignment": s.ema_alignment,
                    "rsi": s.rsi,
                    "rsi_divergence": s.rsi_divergence,
                    "atr": s.atr,
                    "atr_pct": s.atr_pct,
                    "support_bands": s.support_bands,
                    "resistance_bands": s.resistance_bands,
                    "entry_zone": s.entry_zone,
                    "stop_loss": s.stop_loss,
                    "profit_target": s.profit_target,
                    "risk_reward": s.risk_reward,
                    "entry_grade": s.entry_grade,
                    "rationale": s.rationale,
                }
                for s in report.snapshots
            ],
            "metrics": {
                "symbols_analyzed": len(report.snapshots),
                "high_probability_entries": report.high_probability_entries,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "technical_indicator_config.json"
            catalog.write_text(
                json.dumps(
                    {
                        "ema_periods": [EMA_FAST, EMA_MID, EMA_SLOW],
                        "rsi_period": RSI_PERIOD,
                        "atr_period": ATR_PERIOD,
                        "stop_atr_multiple": STOP_ATR_MULTIPLE,
                        "target_rr_multiple": TARGET_RR_MULTIPLE,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        return result


def run_technical_pattern_analysis(output: Path | None = None) -> dict[str, Any]:
    return TechnicalPatternExpert().run(output=output)
