"""
Professional Portfolio Building Frameworks Expert Agent
========================================================
Structured, rules-based factor allocation frameworks for long-term alpha:

* Core-Satellite Architecture — 70-80% core beta / 20-30% satellite alpha.
* Systematic Factor Investing — momentum and quality factor tilts.
* Dynamic Risk-Parity Asset Allocation — weight assets by risk contribution
  rather than dollar weight.

Data: Yahoo Finance chart API (6-month daily history).
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
TRADING_DAYS_PER_YEAR = 252

CORE_UNIVERSE: dict[str, str] = {
    "SPY": "S&P 500 core beta",
    "QQQ": "Nasdaq 100 core growth tilt",
}

FACTOR_UNIVERSE: dict[str, str] = {
    "MTUM": "Momentum factor ETF",
    "QUAL": "Quality factor ETF",
}

RISK_PARITY_ASSETS: dict[str, str] = {
    "SPY": "US equities",
    "TLT": "Long-duration Treasuries",
    "GLD": "Gold",
}

TRADITIONAL_WEIGHTS: dict[str, float] = {"SPY": 0.6, "TLT": 0.4, "GLD": 0.0}

PORTFOLIO_FRAMEWORKS: list[dict[str, Any]] = [
    {
        "id": "core_satellite_architecture",
        "name": "Core-Satellite Architecture",
        "mechanism": (
            "Deploy 70-80% into highly liquid, low-cost index ETFs (broad market "
            "beta) and 20-30% into high-conviction thematic plays, individual "
            "equities, or systematic factor strategies to drive alpha."
        ),
        "flow": "Define Capital -> Core Beta Allocation (70-80%) -> Satellite Alpha Factors (20-30%) -> Systemic Rebalancing Matrix",
    },
    {
        "id": "systematic_factor_investing",
        "name": "Systematic Factor Investing",
        "mechanism": (
            "Allocate capital based on mathematically proven, historically "
            "persistent drivers of stock returns: the Momentum factor "
            "(3-12 month outperformers) and the Quality factor (low debt, high "
            "ROE, stable earnings growth)."
        ),
    },
    {
        "id": "dynamic_risk_parity",
        "name": "Dynamic Risk-Parity Asset Allocation",
        "mechanism": (
            "Balance a portfolio by risk contribution rather than simple dollar "
            "weights. Instead of a traditional 60/40 stock/bond split, assets are "
            "scaled so each asset class contributes equal volatility risk to the "
            "portfolio, smoothing the long-term equity curve."
        ),
    },
]


@dataclass
class FactorReading:
    symbol: str
    label: str
    trailing_return_pct: float
    annualized_vol_pct: float


@dataclass
class RiskParityWeight:
    symbol: str
    label: str
    annualized_vol_pct: float
    risk_parity_weight_pct: float
    traditional_weight_pct: float


@dataclass
class PortfolioFrameworksReport:
    core_satellite_split: dict[str, float]
    factor_readings: list[FactorReading]
    risk_parity_weights: list[RiskParityWeight]
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PortfolioFrameworksExpert(BaseExpert):
    """Core-satellite, factor investing, and risk-parity allocation frameworks."""

    def __init__(self, *, pipeline_context: dict | None = None) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="portfolio-frameworks")
        self.delay_seconds = 0.35

    @staticmethod
    def _daily_returns(closes: list[float]) -> list[float]:
        return [(closes[i] / closes[i - 1]) - 1 for i in range(1, len(closes)) if closes[i - 1]]

    def _annualized_vol_pct(self, closes: list[float]) -> float:
        returns = self._daily_returns(closes)
        if len(returns) < 2:
            return 0.0
        daily_vol = statistics.pstdev(returns)
        return round(daily_vol * (TRADING_DAYS_PER_YEAR**0.5) * 100, 2)

    @staticmethod
    def _trailing_return_pct(closes: list[float]) -> float:
        if len(closes) < 2 or not closes[0]:
            return 0.0
        return round((closes[-1] / closes[0] - 1) * 100, 2)

    def _fetch(self, universe: dict[str, str]) -> dict[str, list[float]]:
        data: dict[str, list[float]] = {}
        for symbol in universe:
            closes = self.fetch_yahoo_closes(symbol, range_="6mo")
            if closes:
                data[symbol] = closes
        return data

    def _factor_readings(self, factor_closes: dict[str, list[float]]) -> list[FactorReading]:
        readings: list[FactorReading] = []
        for symbol, label in FACTOR_UNIVERSE.items():
            closes = factor_closes.get(symbol)
            if not closes:
                continue
            readings.append(
                FactorReading(
                    symbol=symbol,
                    label=label,
                    trailing_return_pct=self._trailing_return_pct(closes),
                    annualized_vol_pct=self._annualized_vol_pct(closes),
                )
            )
        return readings

    def _risk_parity_weights(self, rp_closes: dict[str, list[float]]) -> list[RiskParityWeight]:
        vols: dict[str, float] = {}
        for symbol in RISK_PARITY_ASSETS:
            closes = rp_closes.get(symbol)
            if not closes:
                continue
            vol = self._annualized_vol_pct(closes)
            if vol > 0:
                vols[symbol] = vol
        if not vols:
            return []
        inverse_vol = {s: 1.0 / v for s, v in vols.items()}
        total_inverse = sum(inverse_vol.values())
        weights: list[RiskParityWeight] = []
        for symbol, label in RISK_PARITY_ASSETS.items():
            if symbol not in vols:
                continue
            weight_pct = round(inverse_vol[symbol] / total_inverse * 100, 2)
            weights.append(
                RiskParityWeight(
                    symbol=symbol,
                    label=label,
                    annualized_vol_pct=vols[symbol],
                    risk_parity_weight_pct=weight_pct,
                    traditional_weight_pct=round(TRADITIONAL_WEIGHTS.get(symbol, 0.0) * 100, 2),
                )
            )
        return weights

    def _core_satellite_split(self, factor_readings: list[FactorReading]) -> dict[str, float]:
        momentum = next((r for r in factor_readings if r.symbol == "MTUM"), None)
        satellite_pct = 25.0
        if momentum is not None:
            if momentum.trailing_return_pct >= 10:
                satellite_pct = 30.0
            elif momentum.trailing_return_pct <= -5:
                satellite_pct = 20.0
        return {"core_pct": round(100 - satellite_pct, 1), "satellite_pct": round(satellite_pct, 1)}

    def _market_signals(
        self,
        factor_readings: list[FactorReading],
        risk_parity_weights: list[RiskParityWeight],
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal

        signals: list[dict[str, Any]] = []
        momentum = next((r for r in factor_readings if r.symbol == "MTUM"), None)
        if momentum is not None:
            bias = "BULLISH" if momentum.trailing_return_pct > 0 else "BEARISH"
            signals.append(
                build_market_signal(
                    sector="Factor Investing / Momentum",
                    tickers=["MTUM", "SPY"],
                    bias=bias,
                    reason=f"Momentum factor 6mo trailing return {momentum.trailing_return_pct}%",
                    confidence=min(0.75, 0.45 + abs(momentum.trailing_return_pct) * 0.01),
                )
            )
        gold_weight = next((w for w in risk_parity_weights if w.symbol == "GLD"), None)
        if gold_weight is not None and gold_weight.risk_parity_weight_pct > gold_weight.traditional_weight_pct + 10:
            signals.append(
                build_market_signal(
                    sector="Risk Parity Rebalance",
                    tickers=["GLD", "TLT"],
                    bias="NEUTRAL",
                    reason=(
                        f"Risk-parity model overweights GLD ({gold_weight.risk_parity_weight_pct}%) "
                        f"vs traditional 60/40 ({gold_weight.traditional_weight_pct}%) on low realized volatility"
                    ),
                    confidence=0.5,
                )
            )
        if not signals:
            signals.append(
                build_market_signal(
                    sector="Portfolio Frameworks",
                    tickers=[BENCHMARK],
                    bias="NEUTRAL",
                    reason="No strong factor or risk-parity rebalancing signal detected",
                    confidence=0.4,
                )
            )
        return signals

    def analyze(self) -> PortfolioFrameworksReport:
        core_closes = self._fetch(CORE_UNIVERSE)
        factor_closes = self._fetch(FACTOR_UNIVERSE)
        rp_closes = self._fetch(RISK_PARITY_ASSETS)

        if BENCHMARK not in core_closes and BENCHMARK not in rp_closes:
            raise RuntimeError("Unable to fetch SPY data for portfolio frameworks analysis")

        factor_readings = self._factor_readings(factor_closes)
        risk_parity_weights = self._risk_parity_weights(rp_closes)
        core_satellite_split = self._core_satellite_split(factor_readings)

        summary = (
            f"Core-satellite split recommends {core_satellite_split['core_pct']}% core / "
            f"{core_satellite_split['satellite_pct']}% satellite. "
            f"Tracking {len(factor_readings)} factor ETFs and "
            f"{len(risk_parity_weights)} risk-parity asset classes."
        )

        recs = [summary]
        for r in factor_readings:
            recs.append(
                f"{r.symbol} ({r.label}): 6mo return {r.trailing_return_pct}%, "
                f"annualized vol {r.annualized_vol_pct}%"
            )
        for w in risk_parity_weights:
            recs.append(
                f"{w.symbol} ({w.label}): risk-parity weight {w.risk_parity_weight_pct}% "
                f"vs traditional {w.traditional_weight_pct}% (vol {w.annualized_vol_pct}%)"
            )
        recs.append("Rebalance the satellite sleeve on a quarterly systemic rebalancing matrix.")

        return PortfolioFrameworksReport(
            core_satellite_split=core_satellite_split,
            factor_readings=factor_readings,
            risk_parity_weights=risk_parity_weights,
            expert_summary=summary,
            market_signals=self._market_signals(factor_readings, risk_parity_weights),
            recommendations=recs,
        )

    def to_dict(self, report: PortfolioFrameworksReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Portfolio Building Frameworks Expert",
                "analyzed_at": report.analyzed_at,
                "data_sources": ["Yahoo Finance Chart API"],
                "expert_summary": report.expert_summary,
                "temperature": self.temperature,
            },
            "core_satellite_split": report.core_satellite_split,
            "factor_readings": [
                {
                    "symbol": r.symbol,
                    "label": r.label,
                    "trailing_return_pct": r.trailing_return_pct,
                    "annualized_vol_pct": r.annualized_vol_pct,
                }
                for r in report.factor_readings
            ],
            "risk_parity_weights": [
                {
                    "symbol": w.symbol,
                    "label": w.label,
                    "annualized_vol_pct": w.annualized_vol_pct,
                    "risk_parity_weight_pct": w.risk_parity_weight_pct,
                    "traditional_weight_pct": w.traditional_weight_pct,
                }
                for w in report.risk_parity_weights
            ],
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "portfolio_frameworks_catalog.json"
            catalog.write_text(json.dumps(PORTFOLIO_FRAMEWORKS, indent=2), encoding="utf-8")
        return result


def run_portfolio_frameworks_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return PortfolioFrameworksExpert(pipeline_context=pipeline_context).run(output=output)
