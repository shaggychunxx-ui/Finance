"""
Day Trading Market Microstructure Expert Agent
===============================================
Intra-day liquidity mismatches, order book imbalances, and momentum tactics:

* Opening Range Breakout (ORB) — approximated with a rolling Donchian
  channel since only daily OHLCV is available to this agent.
* Tape Reading / Iceberg detection — volume z-score vs. price displacement
  used as a proxy for absorption at a price level.
* VWAP mean reversion & continuation — rolling volume-weighted average
  price vs. a standard-deviation band.

Data: Yahoo Finance chart API (daily OHLCV, 1-month window).
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base import BaseExpert

BENCHMARK = "SPY"

WATCHLIST: dict[str, str] = {
    "SPY": "S&P 500 (deep liquidity)",
    "QQQ": "Nasdaq 100 (deep liquidity)",
    "IWM": "Russell 2000 (moderate liquidity)",
    "AAPL": "Mega-cap tech (deep liquidity)",
    "NVDA": "High-beta semiconductor (moderate liquidity)",
    "TSLA": "High-beta growth (moderate liquidity)",
    "GME": "Retail-driven small/mid cap (volatile)",
    "COIN": "Crypto-adjacent equity (volatile)",
}

ORB_LOOKBACK_DAYS = 5
VWAP_LOOKBACK_DAYS = 20
VOLUME_LOOKBACK_DAYS = 20
STRETCH_STDEV = 2.0

DAY_TRADING_PLAYBOOK: list[dict[str, Any]] = [
    {
        "id": "opening_range_breakout",
        "name": "Opening Range Breakout (ORB)",
        "mechanism": (
            "Institutional orders accumulate overnight and flood the market at the "
            "open. Traders monitor the high/low of the first 5-15 minutes; a "
            "high-volume breach signals institutional accumulation or distribution."
        ),
        "execution": (
            "Buy a breakout above the opening range high, or short a breakdown "
            "below the low. Place a stop-loss at the midpoint of the opening "
            "range candle."
        ),
        "proxy_used": (
            f"Rolling {ORB_LOOKBACK_DAYS}-day Donchian channel (high/low) as a "
            "daily-bar substitute for the true intraday opening range."
        ),
    },
    {
        "id": "order_flow_tape_reading",
        "name": "Order Flow & Tape Reading (Level 2 / Time & Sales)",
        "mechanism": (
            "Large 'iceberg' orders hide institutional size by splitting big "
            "orders into small, visible pieces. Watch the tape for rapid, "
            "repeated prints at a price level that do not lower available ask size."
        ),
        "execution": (
            "Front-run the iceberg order one tick ahead of it, using the hidden "
            "institutional size as a structural shield for the stop-loss."
        ),
        "proxy_used": (
            "Volume z-score vs. same-day price displacement — a high-volume, "
            "low-displacement session is treated as an absorption/iceberg proxy."
        ),
    },
    {
        "id": "vwap_mean_reversion_continuation",
        "name": "VWAP Mean Reversion & Continuation",
        "mechanism": (
            "VWAP is the true benchmark for institutional execution. Algorithms "
            "try to buy below VWAP and sell above it to get the best average fill."
        ),
        "execution": (
            "In a strong trend, buy pullbacks to a rising VWAP (institutional "
            "support). In a choppy market, short 2+ standard deviations above "
            "VWAP, targeting reversion to the mean."
        ),
        "proxy_used": f"Rolling {VWAP_LOOKBACK_DAYS}-day volume-weighted typical price and stdev band.",
    },
]


@dataclass
class SymbolMicrostructure:
    symbol: str
    liquidity_tier: str
    last_close: float
    orb_high: float
    orb_low: float
    orb_signal: str
    volume_zscore: float
    tape_signal: str
    vwap: float
    vwap_zscore: float
    vwap_signal: str


@dataclass
class DayTradingReport:
    symbols: list[SymbolMicrostructure]
    orb_breakout_count: int
    iceberg_absorption_count: int
    vwap_stretched_count: int
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DayTradingMicrostructureExpert(BaseExpert):
    """Day trading market microstructure tactics: ORB, tape reading, VWAP."""

    def __init__(self, *, pipeline_context: dict | None = None) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="day-trading-microstructure")
        self.delay_seconds = 0.35

    @staticmethod
    def _zscore(value: float, series: list[float]) -> float:
        if len(series) < 2:
            return 0.0
        mean = statistics.mean(series)
        stdev = statistics.pstdev(series)
        if stdev <= 0:
            return 0.0
        return round((value - mean) / stdev, 3)

    def _orb_signal(self, ohlcv: dict[str, list[float]]) -> tuple[float, float, str]:
        highs, lows, closes, volumes = ohlcv["high"], ohlcv["low"], ohlcv["close"], ohlcv["volume"]
        if len(closes) <= ORB_LOOKBACK_DAYS:
            return 0.0, 0.0, "insufficient data"
        window_highs = highs[-ORB_LOOKBACK_DAYS - 1:-1]
        window_lows = lows[-ORB_LOOKBACK_DAYS - 1:-1]
        orb_high = max(window_highs)
        orb_low = min(window_lows)
        last_close = closes[-1]
        volume_window = volumes[-VOLUME_LOOKBACK_DAYS - 1:-1] if len(volumes) > VOLUME_LOOKBACK_DAYS else volumes[:-1]
        avg_volume = statistics.mean(volume_window) if volume_window else 0.0
        last_volume = volumes[-1]
        volume_confirmed = avg_volume > 0 and last_volume > avg_volume * 1.15
        if last_close > orb_high and volume_confirmed:
            signal = "bullish breakout (volume confirmed)"
        elif last_close < orb_low and volume_confirmed:
            signal = "bearish breakdown (volume confirmed)"
        elif last_close > orb_high:
            signal = "breakout (low volume, weak conviction)"
        elif last_close < orb_low:
            signal = "breakdown (low volume, weak conviction)"
        else:
            signal = "inside range"
        return orb_high, orb_low, signal

    def _tape_signal(self, ohlcv: dict[str, list[float]]) -> tuple[float, str]:
        closes, opens, volumes = ohlcv["close"], ohlcv["open"], ohlcv["volume"]
        if len(volumes) < 3:
            return 0.0, "insufficient data"
        window = volumes[-VOLUME_LOOKBACK_DAYS - 1:-1] if len(volumes) > VOLUME_LOOKBACK_DAYS else volumes[:-1]
        vol_z = self._zscore(volumes[-1], window)
        displacement_pct = abs(closes[-1] - opens[-1]) / opens[-1] * 100 if opens[-1] else 0.0
        if vol_z >= 1.5 and displacement_pct < 0.6:
            signal = "absorption / iceberg-like (heavy volume, low displacement)"
        elif vol_z >= 1.5:
            signal = "high-volume directional print"
        else:
            signal = "normal tape"
        return vol_z, signal

    def _vwap_signal(self, ohlcv: dict[str, list[float]]) -> tuple[float, float, str]:
        highs, lows, closes, volumes = ohlcv["high"], ohlcv["low"], ohlcv["close"], ohlcv["volume"]
        if len(closes) < 5:
            return 0.0, 0.0, "insufficient data"
        window = min(VWAP_LOOKBACK_DAYS, len(closes))
        typical_prices = [
            (h + l + c) / 3 for h, l, c in zip(highs[-window:], lows[-window:], closes[-window:])
        ]
        vols = volumes[-window:]
        total_volume = sum(vols)
        vwap = sum(tp * v for tp, v in zip(typical_prices, vols)) / total_volume if total_volume else statistics.mean(typical_prices)
        stdev = statistics.pstdev(typical_prices) if len(typical_prices) > 1 else 0.0
        z = (closes[-1] - vwap) / stdev if stdev > 0 else 0.0
        rising = closes[-1] > closes[-min(5, len(closes))]
        if z >= STRETCH_STDEV:
            signal = "stretched above VWAP — mean-reversion short candidate"
        elif z <= -STRETCH_STDEV:
            signal = "stretched below VWAP — mean-reversion long candidate"
        elif 0 <= z < STRETCH_STDEV and rising:
            signal = "pullback to rising VWAP — trend continuation support"
        else:
            signal = "near VWAP — no edge"
        return round(vwap, 2), round(z, 3), signal

    def _market_signals(self, symbols: list[SymbolMicrostructure]) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal

        signals: list[dict[str, Any]] = []
        breakouts = [s for s in symbols if "bullish breakout" in s.orb_signal or "bearish breakdown" in s.orb_signal]
        if breakouts:
            tickers = [s.symbol for s in breakouts][:5]
            bullish = sum(1 for s in breakouts if "bullish" in s.orb_signal)
            bias = "BULLISH" if bullish >= len(breakouts) / 2 else "BEARISH"
            signals.append(
                build_market_signal(
                    sector="Day Trading / ORB",
                    tickers=tickers,
                    bias=bias,
                    reason=f"{len(breakouts)} symbols with volume-confirmed opening-range breakouts",
                    confidence=min(0.8, 0.5 + 0.06 * len(breakouts)),
                )
            )

        stretched = [s for s in symbols if "mean-reversion" in s.vwap_signal]
        if stretched:
            tickers = [s.symbol for s in stretched][:5]
            shorts = sum(1 for s in stretched if "short" in s.vwap_signal)
            bias = "BEARISH" if shorts >= len(stretched) / 2 else "BULLISH"
            signals.append(
                build_market_signal(
                    sector="Day Trading / VWAP Reversion",
                    tickers=tickers,
                    bias=bias,
                    reason=f"{len(stretched)} symbols stretched {STRETCH_STDEV}σ+ from rolling VWAP",
                    confidence=0.55,
                )
            )

        if not signals:
            signals.append(
                build_market_signal(
                    sector="Day Trading / Microstructure",
                    tickers=[BENCHMARK],
                    bias="NEUTRAL",
                    reason="No confirmed breakout or VWAP-stretch setups in the current watchlist",
                    confidence=0.4,
                )
            )
        return signals

    def analyze(self) -> DayTradingReport:
        rows: list[SymbolMicrostructure] = []
        for symbol, tier in WATCHLIST.items():
            ohlcv = self.fetch_yahoo_ohlcv(symbol, range_="1mo", interval="1d")
            if not ohlcv["close"]:
                continue
            orb_high, orb_low, orb_signal = self._orb_signal(ohlcv)
            vol_z, tape_signal = self._tape_signal(ohlcv)
            vwap, vwap_z, vwap_signal = self._vwap_signal(ohlcv)
            rows.append(
                SymbolMicrostructure(
                    symbol=symbol,
                    liquidity_tier=tier,
                    last_close=round(ohlcv["close"][-1], 2),
                    orb_high=round(orb_high, 2),
                    orb_low=round(orb_low, 2),
                    orb_signal=orb_signal,
                    volume_zscore=round(vol_z, 3),
                    tape_signal=tape_signal,
                    vwap=vwap,
                    vwap_zscore=vwap_z,
                    vwap_signal=vwap_signal,
                )
            )

        if not any(s.symbol == BENCHMARK for s in rows):
            raise RuntimeError("Unable to fetch SPY data for day trading microstructure analysis")

        orb_count = sum(1 for s in rows if "breakout" in s.orb_signal or "breakdown" in s.orb_signal)
        iceberg_count = sum(1 for s in rows if "absorption" in s.tape_signal)
        stretched_count = sum(1 for s in rows if "mean-reversion" in s.vwap_signal)

        summary = (
            f"Scanned {len(rows)} liquid day-trading symbols: {orb_count} ORB setups, "
            f"{iceberg_count} iceberg/absorption prints, {stretched_count} VWAP-stretched names."
        )

        recs = [summary]
        for s in sorted(rows, key=lambda r: abs(r.vwap_zscore), reverse=True)[:5]:
            recs.append(
                f"{s.symbol} [{s.liquidity_tier}]: ORB {s.orb_signal}; tape {s.tape_signal}; "
                f"VWAP {s.vwap_signal} (z={s.vwap_zscore})"
            )
        recs.append("1% rule still applies: size day trades off the opening-range stop distance.")

        return DayTradingReport(
            symbols=rows,
            orb_breakout_count=orb_count,
            iceberg_absorption_count=iceberg_count,
            vwap_stretched_count=stretched_count,
            expert_summary=summary,
            market_signals=self._market_signals(rows),
            recommendations=recs,
        )

    def to_dict(self, report: DayTradingReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Day Trading Market Microstructure Expert",
                "analyzed_at": report.analyzed_at,
                "data_sources": ["Yahoo Finance Chart API"],
                "expert_summary": report.expert_summary,
                "temperature": self.temperature,
            },
            "metrics": {
                "orb_breakout_count": report.orb_breakout_count,
                "iceberg_absorption_count": report.iceberg_absorption_count,
                "vwap_stretched_count": report.vwap_stretched_count,
            },
            "symbol_microstructure": [
                {
                    "symbol": s.symbol,
                    "liquidity_tier": s.liquidity_tier,
                    "last_close": s.last_close,
                    "orb_high": s.orb_high,
                    "orb_low": s.orb_low,
                    "orb_signal": s.orb_signal,
                    "volume_zscore": s.volume_zscore,
                    "tape_signal": s.tape_signal,
                    "vwap": s.vwap,
                    "vwap_zscore": s.vwap_zscore,
                    "vwap_signal": s.vwap_signal,
                }
                for s in report.symbols
            ],
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "day_trading_playbook.json"
            catalog.write_text(json.dumps(DAY_TRADING_PLAYBOOK, indent=2), encoding="utf-8")
        return result


def run_day_trading_microstructure_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return DayTradingMicrostructureExpert(pipeline_context=pipeline_context).run(output=output)
