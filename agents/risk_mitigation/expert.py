"""
Institutional Short Risk Mitigation Expert Agent
=================================================
Because short selling carries theoretically infinite capital-loss risk,
professional desks apply rigorous defensive parameters before deploying
capital into a bear thesis: position sizing caps, synthetic short structures
(long puts / bear put spreads), and hard VWAP-anchored stop-loss triggers.

Data: Yahoo Finance chart API (3-month daily OHLCV). Live options-chain
premium data is not reachable from this sandbox, so per-symbol synthetic-
short premium and VWAP stop levels are transparent, disclosed proxies built
from realized volatility/price action — not live options quotes.
"""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base import BaseExpert

BENCHMARK = "SPY"

WATCHLIST: dict[str, str] = {
    "SPY": "S&P 500 (deep liquidity proxy)",
    "AAPL": "Mega-cap tech (lower defensive priority)",
    "MSFT": "Mega-cap tech (lower defensive priority)",
    "QQQ": "Nasdaq 100 (lower defensive priority)",
    "IWM": "Russell 2000 (moderate defensive priority)",
    "GME": "Retail-driven small/mid cap (high defensive priority)",
    "COIN": "Crypto-adjacent equity (high defensive priority)",
    "PLTR": "High-beta growth name (moderate-high defensive priority)",
}

# Reference portfolio notional used purely to make the position-sizing cap concrete.
REFERENCE_PORTFOLIO_USD = 1_000_000.0

POSITION_SIZING_CAPS: dict[str, str] = {
    "cap_range": "0.5% – 1.0% of total portfolio risk per single high-short-interest position",
    "note": "Limits catastrophic loss exposure from an unexpected squeeze on any one name.",
}

SYNTHETIC_SHORTS: dict[str, str] = {
    "technique": "Long put options or bear put spreads instead of borrowing equity",
    "benefit": "Caps the maximum potential loss to the premium paid — no unlimited upside risk.",
}

HARD_STOP_LOSS: dict[str, str] = {
    "technique": "Algorithmic stop-orders tied to volume-weighted average price (VWAP) benchmarks",
    "benefit": "Exit positions before market liquidity completely dries up in a squeeze.",
}


@dataclass
class SymbolRiskProfile:
    symbol: str
    name: str
    last_close: float
    realized_vol_pct: float
    vwap_20d: float
    vwap_stop_trigger_price: float
    max_position_size_usd: float
    max_shares_at_cap: int
    synthetic_short_premium_proxy_pct: float
    defensive_priority: str
    rationale: str


@dataclass
class RiskMitigationAssessment:
    high_priority_count: int
    average_vol_pct: float
    tightest_symbol: str
    sizing_signal: str
    stop_signal: str
    conclusion: str


@dataclass
class RiskMitigationReport:
    symbols: list[SymbolRiskProfile]
    assessment: RiskMitigationAssessment
    portfolio_defensive_score: float
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RiskMitigationExpert(BaseExpert):
    """Expert market analyst — institutional risk mitigation framework for short exposure."""

    def __init__(
        self,
        delay_seconds: float = 0.35,
        *,
        pipeline_context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="risk-mitigation")
        self.delay_seconds = delay_seconds

    @staticmethod
    def _defensive_priority(realized_vol_pct: float) -> str:
        if realized_vol_pct >= 5.0:
            return "High"
        if realized_vol_pct >= 2.5:
            return "Moderate"
        return "Low"

    def _analyze_symbol(self, symbol: str, name: str) -> SymbolRiskProfile | None:
        data = self.fetch_yahoo_ohlcv(symbol, range_="3mo", interval="1d")
        closes = data.get("close", [])
        highs = data.get("high", [])
        lows = data.get("low", [])
        volumes = data.get("volume", [])
        if len(closes) < 15:
            return None

        last_close = closes[-1]
        window = min(len(closes), 20)
        recent_closes = closes[-window:]
        recent_highs = highs[-window:]
        recent_lows = lows[-window:]
        recent_volumes = volumes[-window:]

        typical_prices = [
            (h + l + c) / 3 for h, l, c in zip(recent_highs, recent_lows, recent_closes)
        ]
        total_volume = sum(recent_volumes)
        vwap_20d = round(
            sum(tp * v for tp, v in zip(typical_prices, recent_volumes)) / total_volume, 2
        ) if total_volume else round(last_close, 2)

        daily_returns = [
            abs(recent_closes[i] / recent_closes[i - 1] - 1) * 100
            for i in range(1, len(recent_closes))
            if recent_closes[i - 1]
        ]
        realized_vol_pct = round(statistics.mean(daily_returns) if daily_returns else 0.0, 2)

        # Hard stop-loss trigger: a VWAP-anchored buy-to-cover level scaled by realized
        # volatility, so tighter-range names get a tighter stop and vice versa.
        vwap_stop_trigger_price = round(vwap_20d * (1 + max(realized_vol_pct, 1.0) / 100 * 1.5), 2)

        # Position sizing cap: 0.5%-1% of portfolio risk, scaled down further for the
        # most volatile (defensive-priority) names within that band.
        priority = self._defensive_priority(realized_vol_pct)
        cap_pct = {"High": 0.5, "Moderate": 0.75, "Low": 1.0}[priority]
        max_position_size_usd = round(REFERENCE_PORTFOLIO_USD * cap_pct / 100, 2)
        max_shares_at_cap = int(max_position_size_usd / last_close) if last_close else 0

        # Synthetic-short premium proxy: realized volatility is the dominant driver of
        # option premium (Black-Scholes vega), used here as a rough put-cost stand-in.
        synthetic_short_premium_proxy_pct = round(min(realized_vol_pct * 1.8, 25.0), 2)

        rationale = (
            f"Realized vol {realized_vol_pct:.2f}%/day → {priority} defensive priority: "
            f"cap ${max_position_size_usd:,.0f} ({cap_pct:.2f}% of ${REFERENCE_PORTFOLIO_USD:,.0f} "
            f"reference book), VWAP stop at ${vwap_stop_trigger_price:,.2f}."
        )

        return SymbolRiskProfile(
            symbol=symbol,
            name=name,
            last_close=round(last_close, 2),
            realized_vol_pct=realized_vol_pct,
            vwap_20d=vwap_20d,
            vwap_stop_trigger_price=vwap_stop_trigger_price,
            max_position_size_usd=max_position_size_usd,
            max_shares_at_cap=max_shares_at_cap,
            synthetic_short_premium_proxy_pct=synthetic_short_premium_proxy_pct,
            defensive_priority=priority,
            rationale=rationale,
        )

    def _assessment(self, symbols: list[SymbolRiskProfile]) -> RiskMitigationAssessment:
        high_priority = [s for s in symbols if s.defensive_priority == "High"]
        tightest = max(symbols, key=lambda s: s.realized_vol_pct) if symbols else None
        avg_vol = round(statistics.mean([s.realized_vol_pct for s in symbols]), 2) if symbols else 0.0

        sizing_signal = (
            f"{len(high_priority)}/{len(symbols)} symbols warrant the tightest 0.5% position-sizing "
            "cap given realized volatility."
        )
        stop_signal = (
            "VWAP-anchored stop triggers scale with realized volatility — tighter-range names get "
            "tighter stops to preserve exit liquidity before a squeeze accelerates."
        )
        if tightest and tightest.defensive_priority == "High":
            conclusion = (
                f"{tightest.symbol} needs the full defensive stack: {POSITION_SIZING_CAPS['cap_range']}, "
                f"synthetic short structuring, and a hard VWAP stop."
            )
        elif high_priority:
            conclusion = "Some names warrant tightened sizing and hard stops; most remain standard risk."
        else:
            conclusion = "Watchlist is broadly low-volatility — standard risk parameters apply."

        return RiskMitigationAssessment(
            high_priority_count=len(high_priority),
            average_vol_pct=avg_vol,
            tightest_symbol=tightest.symbol if tightest else "",
            sizing_signal=sizing_signal,
            stop_signal=stop_signal,
            conclusion=conclusion,
        )

    def _expert_summary(self, assessment: RiskMitigationAssessment) -> str:
        return (
            f"Risk-mitigation scan: avg realized vol {assessment.average_vol_pct:.2f}%/day. "
            f"{assessment.sizing_signal} {assessment.stop_signal} {assessment.conclusion}"
        )

    def _market_signals(self, symbols: list[SymbolRiskProfile]) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        def _keep(symbol: str) -> bool:
            return not self.pipeline_should_skip_symbol(symbol)

        high_priority = [s.symbol for s in symbols if s.defensive_priority == "High" and _keep(s.symbol)]
        if high_priority:
            signals.append(
                {
                    "sector": "Risk Mitigation",
                    "bias": "tighten-sizing",
                    "tickers": high_priority,
                    "reason": "High realized volatility — cap position size at 0.5% of portfolio risk and use synthetic shorts.",
                }
            )
        moderate = [
            s.symbol for s in symbols if s.defensive_priority == "Moderate" and _keep(s.symbol)
        ]
        if moderate:
            signals.append(
                {
                    "sector": "Risk Mitigation",
                    "bias": "standard-sizing",
                    "tickers": moderate,
                    "reason": "Moderate volatility — standard 0.75% sizing cap with VWAP stop-loss.",
                }
            )
        low = [s.symbol for s in symbols if s.defensive_priority == "Low" and _keep(s.symbol)]
        if low:
            signals.append(
                {
                    "sector": "Risk Mitigation",
                    "bias": "relaxed-sizing",
                    "tickers": low,
                    "reason": "Low volatility — full 1.0% sizing cap is defensible.",
                }
            )
        return signals

    def _recommendations(
        self, symbols: list[SymbolRiskProfile], assessment: RiskMitigationAssessment
    ) -> list[str]:
        recs = [assessment.conclusion]
        for s in sorted(symbols, key=lambda x: -x.realized_vol_pct)[:6]:
            recs.append(f"{s.symbol} [{s.defensive_priority}]: {s.rationale}")
        return recs

    def analyze(self) -> RiskMitigationReport:
        symbols: list[SymbolRiskProfile] = []
        for symbol, name in WATCHLIST.items():
            row = self._analyze_symbol(symbol, name)
            if row:
                symbols.append(row)
            time.sleep(self.delay_seconds)

        if not any(s.symbol == BENCHMARK for s in symbols):
            raise RuntimeError("Unable to fetch SPY data for risk-mitigation analysis")

        assessment = self._assessment(symbols)
        expert_summary = self._expert_summary(assessment)
        portfolio_defensive_score = round(
            statistics.mean([s.realized_vol_pct for s in symbols]), 1
        )

        return RiskMitigationReport(
            symbols=symbols,
            assessment=assessment,
            portfolio_defensive_score=portfolio_defensive_score,
            expert_summary=expert_summary,
            market_signals=self._market_signals(symbols),
            recommendations=self._recommendations(symbols, assessment),
            data_source=(
                "Yahoo Finance Chart API (3mo daily OHLCV) — VWAP stops and synthetic-short premium "
                "are volatility-based proxies, not live options quotes"
            ),
        )

    def to_dict(self, report: RiskMitigationReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Institutional Short Risk Mitigation Expert",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
                "temperature": self.temperature,
                "pipeline_memory": {
                    "posture": self.pipeline_context.get("posture"),
                    "lessons": self.pipeline_memory_notes(),
                    "preferred_horizon": self.pipeline_context.get("preferred_horizon"),
                },
            },
            "position_sizing_caps": POSITION_SIZING_CAPS,
            "synthetic_shorts": SYNTHETIC_SHORTS,
            "hard_stop_loss": HARD_STOP_LOSS,
            "reference_portfolio_usd": REFERENCE_PORTFOLIO_USD,
            "symbol_risk_profiles": [
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "last_close": s.last_close,
                    "realized_vol_pct": s.realized_vol_pct,
                    "vwap_20d": s.vwap_20d,
                    "vwap_stop_trigger_price": s.vwap_stop_trigger_price,
                    "max_position_size_usd": s.max_position_size_usd,
                    "max_shares_at_cap": s.max_shares_at_cap,
                    "synthetic_short_premium_proxy_pct": s.synthetic_short_premium_proxy_pct,
                    "defensive_priority": s.defensive_priority,
                    "rationale": s.rationale,
                }
                for s in report.symbols
            ],
            "risk_assessment": {
                "high_priority_count": a.high_priority_count,
                "average_vol_pct": a.average_vol_pct,
                "tightest_symbol": a.tightest_symbol,
                "sizing_signal": a.sizing_signal,
                "stop_signal": a.stop_signal,
                "conclusion": a.conclusion,
            },
            "metrics": {"portfolio_defensive_score": report.portfolio_defensive_score},
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "risk_mitigation_framework.json"
            catalog.write_text(
                json.dumps(
                    {
                        "position_sizing_caps": POSITION_SIZING_CAPS,
                        "synthetic_shorts": SYNTHETIC_SHORTS,
                        "hard_stop_loss": HARD_STOP_LOSS,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        return result


def run_risk_mitigation_analysis(
    output: Path | None = None,
    pipeline_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return RiskMitigationExpert(pipeline_context=pipeline_context).run(output=output)
