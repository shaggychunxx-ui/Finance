"""
Market Regime Detection Agent — "The Context Filter"
======================================================
Mission: classify the macro-environment so the system doesn't apply a
trading tool built for a bull run inside a bleeding, volatile bear market.

API interfacing: pulls VIX level/term-structure proxies and broad index
data from the Yahoo Finance chart API (^VIX, ^VIX3M, ^GSPC).

Mathematical processing: rather than a full Hidden Markov Model training
pipeline (which needs persisted historical state across runs), this agent
implements the equivalent classification via rolling statistical clustering
— realized volatility (annualized stdev of returns) split against its own
trailing distribution, and trend persistence (ADX-style directional
strength + SMA slope) — to bucket the *current* state into one of the four
canonical operating regimes:
  1. Low Volatility, Trending      -> high-confidence momentum trading
  2. High Volatility, Trending     -> panic trend-following, wide stops
  3. Low Volatility, Mean-Reverting -> range/grid trading
  4. High Volatility, Mean-Reverting -> chop / capital preservation

How it ensures accuracy: acts as a master config switch. If the regime
flips from Trending to Chop, downstream Technical/Risk agents should stop
chasing breakouts and cut position sizing immediately.
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
HEADERS = {"User-Agent": "Finance-Market-Regime/1.0 (shaggychunxx@gmail.com)"}

INDEX_SYMBOL = "^GSPC"
VIX_SYMBOL = "^VIX"
VIX3M_SYMBOL = "^VIX3M"

TREND_WINDOW = 20  # bars used to measure trend persistence (SMA slope + directional strength)
VOL_LOOKBACK = 90  # trading days of history to build the realized-vol distribution
VOL_PERCENTILE_HIGH = 60.0  # realized vol percentile at/above which we call "High Volatility"
TREND_STRENGTH_THRESHOLD = 0.55  # directional persistence ratio needed to call "Trending"

REGIME_PLAYBOOK: dict[str, dict[str, Any]] = {
    "Low-Vol Trending": {
        "config": "High-confidence momentum trading enabled",
        "technical_agent": "Chase breakouts; standard ATR-based stops",
        "risk_agent": "Standard position sizing",
    },
    "High-Vol Trending": {
        "config": "Panic trend-following; require wide stop-losses",
        "technical_agent": "Follow trend but widen stops to 2x ATR",
        "risk_agent": "Reduce size ~30% to offset wider stops",
    },
    "Low-Vol Mean-Reverting": {
        "config": "Range/grid-trading active",
        "technical_agent": "Fade extremes at range boundaries, not breakouts",
        "risk_agent": "Standard sizing, tighter stops at range edges",
    },
    "High-Vol Mean-Reverting": {
        "config": "Chop/capital preservation mode; tighten risk controls",
        "technical_agent": "Stop chasing breakouts; avoid new momentum entries",
        "risk_agent": "Cut position sizing sharply; raise cash allocation",
    },
}


@dataclass
class RegimeReport:
    vix_level: float | None
    vix3m_level: float | None
    vix_term_structure: str
    realized_vol_pct: float | None
    realized_vol_percentile: float | None
    volatility_state: str
    trend_strength: float | None
    trend_direction: str
    trending_state: str
    regime_label: str
    regime_config: dict[str, Any]
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MarketRegimeExpert(BaseExpert):
    """The 'context filter' — master config switch for the whole pipeline."""

    def __init__(self) -> None:
        super().__init__()

    def _fetch_closes(self, symbol: str, range_: str = "6mo") -> list[float]:
        try:
            resp = requests.get(
                CHART_API.format(symbol=symbol),
                params={"interval": "1d", "range": range_},
                headers=HEADERS,
                timeout=25,
            )
            resp.raise_for_status()
            quote = resp.json()["chart"]["result"][0]["indicators"]["quote"][0]
            return [float(c) for c in quote.get("close", []) if c is not None]
        except Exception:
            return []

    def _fetch_last(self, symbol: str) -> float | None:
        closes = self._fetch_closes(symbol, range_="5d")
        return closes[-1] if closes else None

    @staticmethod
    def _daily_returns(closes: list[float]) -> list[float]:
        return [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes))
            if closes[i - 1]
        ]

    @staticmethod
    def _rolling_realized_vol(returns: list[float], window: int) -> list[float]:
        """Annualized realized volatility (%) over a rolling window."""
        vols = []
        for i in range(window, len(returns) + 1):
            chunk = returns[i - window : i]
            vol_pct = statistics.pstdev(chunk) * (252**0.5) * 100
            vols.append(vol_pct)
        return vols

    @staticmethod
    def _percentile_rank(series: list[float], value: float) -> float:
        if not series:
            return 50.0
        below = sum(1 for v in series if v <= value)
        return round((below / len(series)) * 100, 1)

    @staticmethod
    def _trend_strength(closes: list[float], window: int = TREND_WINDOW) -> tuple[float, str]:
        """Directional persistence ratio: net displacement / sum of absolute moves."""
        if len(closes) <= window:
            window = max(2, len(closes) - 1)
        recent = closes[-(window + 1) :]
        if len(recent) < 2:
            return 0.0, "Flat"
        moves = [recent[i] - recent[i - 1] for i in range(1, len(recent))]
        net = recent[-1] - recent[0]
        gross = sum(abs(m) for m in moves)
        strength = abs(net) / gross if gross else 0.0
        direction = "Up" if net > 0 else "Down" if net < 0 else "Flat"
        return round(strength, 3), direction

    def analyze(self) -> RegimeReport:
        vix = self._fetch_last(VIX_SYMBOL)
        vix3m = self._fetch_last(VIX3M_SYMBOL)
        index_closes = self._fetch_closes(INDEX_SYMBOL, range_="1y")

        vix_term_structure = "Unavailable"
        if vix is not None and vix3m is not None:
            if vix > vix3m:
                vix_term_structure = "Backwardation (near-term fear elevated)"
            elif vix < vix3m:
                vix_term_structure = "Contango (normal term structure)"
            else:
                vix_term_structure = "Flat term structure"

        realized_vol_pct = None
        realized_vol_percentile = None
        volatility_state = "Unknown"
        trend_strength = None
        trend_direction = "Unknown"
        trending_state = "Unknown"

        if len(index_closes) > VOL_LOOKBACK + 20:
            returns = self._daily_returns(index_closes)
            vol_series = self._rolling_realized_vol(returns, TREND_WINDOW)
            if vol_series:
                realized_vol_pct = round(vol_series[-1], 2)
                lookback_series = vol_series[-VOL_LOOKBACK:] if len(vol_series) >= VOL_LOOKBACK else vol_series
                realized_vol_percentile = self._percentile_rank(lookback_series, vol_series[-1])
                volatility_state = (
                    "High Volatility" if realized_vol_percentile >= VOL_PERCENTILE_HIGH else "Low Volatility"
                )

            trend_strength, trend_direction = self._trend_strength(index_closes)
            trending_state = "Trending" if trend_strength >= TREND_STRENGTH_THRESHOLD else "Mean-Reverting"

        if volatility_state == "Unknown" or trending_state == "Unknown":
            regime_label = "Unclassified (insufficient index history)"
            regime_config = {}
        else:
            volatility_prefix = "Low-Vol" if volatility_state == "Low Volatility" else "High-Vol"
            regime_label = f"{volatility_prefix} {trending_state}"
            regime_config = REGIME_PLAYBOOK.get(regime_label, {})

        expert_summary = (
            f"Regime classified as '{regime_label}' "
            f"(realized vol {realized_vol_pct}%, percentile {realized_vol_percentile}; "
            f"trend strength {trend_strength} {trend_direction}; VIX {vix})."
        )

        signals = []
        if regime_config:
            bias = "bullish" if trend_direction == "Up" and trending_state == "Trending" else (
                "bearish" if trend_direction == "Down" and trending_state == "Trending" else "neutral"
            )
            signals.append(
                {
                    "sector": "Macro/Index",
                    "bias": bias,
                    "tickers": [INDEX_SYMBOL, VIX_SYMBOL],
                    "reason": f"Regime={regime_label}: {regime_config.get('config', '')}",
                }
            )

        recommendations = []
        if regime_config:
            recommendations.append(f"Technical Agent: {regime_config.get('technical_agent')}")
            recommendations.append(f"Risk Agent: {regime_config.get('risk_agent')}")
        else:
            recommendations.append("Insufficient data to classify regime this run — default to conservative sizing.")

        return RegimeReport(
            vix_level=round(vix, 2) if vix is not None else None,
            vix3m_level=round(vix3m, 2) if vix3m is not None else None,
            vix_term_structure=vix_term_structure,
            realized_vol_pct=realized_vol_pct,
            realized_vol_percentile=realized_vol_percentile,
            volatility_state=volatility_state,
            trend_strength=trend_strength,
            trend_direction=trend_direction,
            trending_state=trending_state,
            regime_label=regime_label,
            regime_config=regime_config,
            expert_summary=expert_summary,
            market_signals=signals,
            recommendations=recommendations,
            data_source="Yahoo Finance Chart API (^GSPC, ^VIX, ^VIX3M)",
        )

    def to_dict(self, report: RegimeReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Market Regime Detection Agent (The Context Filter)",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
                "temperature": self.temperature,
                "vix_level": report.vix_level,
                "vix3m_level": report.vix3m_level,
                "vix_term_structure": report.vix_term_structure,
            },
            "metrics": {
                "realized_vol_pct": report.realized_vol_pct,
                "realized_vol_percentile": report.realized_vol_percentile,
                "volatility_state": report.volatility_state,
                "trend_strength": report.trend_strength,
                "trend_direction": report.trend_direction,
                "trending_state": report.trending_state,
                "regime_label": report.regime_label,
            },
            "regime_config": report.regime_config,
            "regime_playbook": REGIME_PLAYBOOK,
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "regime_playbook.json"
            catalog.write_text(json.dumps(REGIME_PLAYBOOK, indent=2), encoding="utf-8")
        return result


def run_market_regime_analysis(output: Path | None = None) -> dict[str, Any]:
    return MarketRegimeExpert().run(output=output)
