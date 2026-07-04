"""
Portfolio Management Expert Agent
=================================
Modern Portfolio Theory (MPT) analyst: asset allocation modeling, the four
phases of portfolio management (security analysis, portfolio selection,
portfolio revision, portfolio evaluation), Sharpe-ratio risk-adjusted
performance, and behavioral blind-spot monitoring.

Data: Yahoo Finance chart API (1-year daily history) with a fixed-income
proxy for the risk-free rate.
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
HEADERS = {"User-Agent": "Finance-Portfolio-Management/1.0 (shaggychunxx@gmail.com)"}

RISK_FREE_SYMBOL = "^IRX"
DEFAULT_RISK_FREE_PCT = 4.0
CORRELATION_THRESHOLD = 0.5

# Representative, liquid ETF proxies for each asset class.
ASSET_CLASSES: dict[str, dict[str, str]] = {
    "equities": {"symbol": "SPY", "name": "S&P 500 Equities"},
    "fixed_income": {"symbol": "AGG", "name": "Aggregate Bonds"},
    "alternatives": {"symbol": "GLD", "name": "Gold / Alternatives"},
}

ALLOCATION_MODELS: list[dict[str, Any]] = [
    {
        "id": "60_40",
        "name": "60/40 Portfolio (Balanced Growth)",
        "description": (
            "60% equities in diversified index funds for long-term growth, "
            "40% fixed income in government/corporate bonds for income and "
            "downside buffering. Designed for moderate-risk investors seeking "
            "stable, long-term wealth accumulation."
        ),
        "weights": {"equities": 0.60, "fixed_income": 0.40},
    },
    {
        "id": "60_20_20",
        "name": "60/20/20 Portfolio (Modern Diversification)",
        "description": (
            "60% equities split across domestic large-cap, international, and "
            "emerging markets; 20% high-quality treasuries/TIPS; 20% "
            "alternatives (commodities, REITs, gold) to reduce inter-asset "
            "correlation and combat inflation and volatility."
        ),
        "weights": {"equities": 0.60, "fixed_income": 0.20, "alternatives": 0.20},
    },
]

FOUR_PHASES: list[dict[str, Any]] = [
    {
        "id": "security_analysis",
        "name": "1. Security Analysis",
        "actions": [
            "Evaluate assets — inspect individual securities for intrinsic value and risk profile.",
            "Fundamental analysis — corporate financial statements, earnings growth, competitive advantages.",
            "Macro analysis — interest rate trends, inflation forecasts, global economic data.",
        ],
    },
    {
        "id": "portfolio_selection",
        "name": "2. Portfolio Selection",
        "actions": [
            "Construct the mix — combine analyzed assets to build the target allocation.",
            "Calculate correlation — favor assets with correlation coefficient ρ < 0.5.",
            "Optimize efficiency — place assets on the efficient frontier for the chosen risk profile.",
        ],
    },
    {
        "id": "portfolio_revision",
        "name": "3. Portfolio Revision",
        "actions": [
            "Monitor drifts — review the portfolio as market movements alter target weights.",
            "Rebalance assets — sell overperforming, buy underperforming to restore target weights.",
            "Deploy capital — direct new contributions to underweight classes to minimize tax drag.",
        ],
    },
    {
        "id": "portfolio_evaluation",
        "name": "4. Portfolio Evaluation",
        "actions": [
            "Assess performance — measure actual returns against a relevant benchmark (e.g. S&P 500).",
            "Calculate risk-adjusted return — Sharpe Ratio = (Rp - Rf) / σp.",
            "Compare across allocation models to confirm the risk taken is justified.",
        ],
    },
]

BLIND_SPOTS: list[dict[str, str]] = [
    {
        "id": "emotional_biases",
        "name": "Emotional Biases",
        "description": "Panic-selling during market downturns permanently locks in paper losses.",
    },
    {
        "id": "under_diversification",
        "name": "Under-Diversification",
        "description": (
            "Familiarity bias leads investors to over-allocate to their employer's "
            "stock or domestic markets only."
        ),
    },
    {
        "id": "ignoring_fees",
        "name": "Ignoring Fees",
        "description": "High expense ratios and frequent trading commissions quietly erode compounding returns.",
    },
]


@dataclass
class AssetStats:
    asset_class: str
    symbol: str
    name: str
    annual_return_pct: float
    annual_vol_pct: float
    sample_size: int


@dataclass
class CorrelationPair:
    asset_a: str
    asset_b: str
    correlation: float
    diversified: bool
    interpretation: str


@dataclass
class AllocationAssessment:
    model_id: str
    name: str
    description: str
    weights: dict[str, float]
    expected_annual_return_pct: float
    expected_annual_vol_pct: float
    sharpe_ratio: float
    diversification_score: float
    interpretation: str


@dataclass
class PortfolioAssessment:
    allocation_signal: str
    diversification_signal: str
    revision_signal: str
    evaluation_signal: str
    blind_spot_alert: str
    conclusion: str


@dataclass
class PortfolioManagementReport:
    risk_free_rate_pct: float
    asset_stats: list[AssetStats]
    correlations: list[CorrelationPair]
    allocations: list[AllocationAssessment]
    phases: list[dict[str, Any]]
    blind_spots: list[dict[str, str]]
    assessment: PortfolioAssessment
    best_allocation_id: str
    portfolio_quality_score: float
    regime_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    data_source: str = "Yahoo Finance API"
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PortfolioManagementExpert:
    """Portfolio manager — MPT asset allocation, phased process, and risk-adjusted evaluation."""

    def __init__(self, delay_seconds: float = 0.3) -> None:
        self.delay_seconds = delay_seconds

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
    def _pearson(a: list[float], b: list[float]) -> float:
        n = min(len(a), len(b))
        if n < 2:
            return 0.0
        a, b = a[-n:], b[-n:]
        mean_a, mean_b = statistics.mean(a), statistics.mean(b)
        cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
        var_a = sum((x - mean_a) ** 2 for x in a)
        var_b = sum((y - mean_b) ** 2 for y in b)
        denom = math.sqrt(var_a * var_b)
        return round(cov / denom, 4) if denom else 0.0

    def _risk_free_rate(self) -> float:
        closes = self._fetch_closes(RISK_FREE_SYMBOL)
        if closes:
            return round(closes[-1], 4)
        return DEFAULT_RISK_FREE_PCT

    def _asset_stats(self, asset_class: str, symbol: str, name: str, returns: list[float]) -> AssetStats:
        mean_daily = statistics.mean(returns)
        stdev_daily = statistics.stdev(returns) if len(returns) > 1 else 0.0
        annual_return = mean_daily * 252 * 100
        annual_vol = stdev_daily * math.sqrt(252) * 100
        return AssetStats(
            asset_class=asset_class,
            symbol=symbol,
            name=name,
            annual_return_pct=round(annual_return, 2),
            annual_vol_pct=round(annual_vol, 2),
            sample_size=len(returns),
        )

    def _correlations(self, return_map: dict[str, list[float]]) -> list[CorrelationPair]:
        classes = list(return_map.keys())
        pairs: list[CorrelationPair] = []
        for i in range(len(classes)):
            for j in range(i + 1, len(classes)):
                a_cls, b_cls = classes[i], classes[j]
                rho = self._pearson(return_map[a_cls], return_map[b_cls])
                diversified = abs(rho) < CORRELATION_THRESHOLD
                interpretation = (
                    f"ρ={rho:+.2f} — sufficiently diversified (ρ < {CORRELATION_THRESHOLD})"
                    if diversified else
                    f"ρ={rho:+.2f} — high correlation, limited diversification benefit"
                )
                pairs.append(CorrelationPair(
                    asset_a=a_cls, asset_b=b_cls, correlation=rho,
                    diversified=diversified, interpretation=interpretation,
                ))
        return pairs

    def _allocation_assessment(
        self,
        model: dict[str, Any],
        stats_by_class: dict[str, AssetStats],
        return_map: dict[str, list[float]],
        risk_free_pct: float,
    ) -> AllocationAssessment | None:
        weights = model["weights"]
        if not all(cls in stats_by_class for cls in weights):
            return None

        expected_return = sum(weights[cls] * stats_by_class[cls].annual_return_pct for cls in weights)

        variance = 0.0
        for a_cls, w_a in weights.items():
            sigma_a = stats_by_class[a_cls].annual_vol_pct / 100
            for b_cls, w_b in weights.items():
                sigma_b = stats_by_class[b_cls].annual_vol_pct / 100
                rho = 1.0 if a_cls == b_cls else self._pearson(return_map[a_cls], return_map[b_cls])
                variance += w_a * w_b * rho * sigma_a * sigma_b
        vol_pct = math.sqrt(max(variance, 0.0)) * 100

        sharpe = (expected_return - risk_free_pct) / vol_pct if vol_pct else 0.0

        cross_pairs = [
            self._pearson(return_map[a], return_map[b])
            for idx_a, a in enumerate(weights)
            for b in list(weights)[idx_a + 1:]
        ]
        diversification_score = (
            round(1 - (sum(abs(r) for r in cross_pairs) / len(cross_pairs)), 4)
            if cross_pairs else 1.0
        )

        if sharpe >= 1.0:
            interpretation = f"Sharpe {sharpe:.2f} — strong risk-adjusted return, allocation well compensated for risk taken"
        elif sharpe >= 0.5:
            interpretation = f"Sharpe {sharpe:.2f} — moderate risk-adjusted return"
        else:
            interpretation = f"Sharpe {sharpe:.2f} — weak risk-adjusted return, revisit allocation or timing"

        return AllocationAssessment(
            model_id=model["id"],
            name=model["name"],
            description=model["description"],
            weights=weights,
            expected_annual_return_pct=round(expected_return, 2),
            expected_annual_vol_pct=round(vol_pct, 2),
            sharpe_ratio=round(sharpe, 4),
            diversification_score=diversification_score,
            interpretation=interpretation,
        )

    @staticmethod
    def _assessment(
        allocations: list[AllocationAssessment],
        correlations: list[CorrelationPair],
        stats_by_class: dict[str, AssetStats],
    ) -> PortfolioAssessment:
        if allocations:
            best = max(allocations, key=lambda a: a.sharpe_ratio)
            allocation_signal = (
                f"{best.name} leads on risk-adjusted return — {best.interpretation}"
            )
        else:
            allocation_signal = "insufficient asset class data to compare allocation models"

        undiversified = [c for c in correlations if not c.diversified]
        if undiversified:
            diversification_signal = (
                f"{len(undiversified)}/{len(correlations)} asset-class pairs exceed the "
                f"ρ<{CORRELATION_THRESHOLD} diversification threshold — "
                + undiversified[0].interpretation
            )
        else:
            diversification_signal = f"all asset-class pairs sit below the ρ<{CORRELATION_THRESHOLD} threshold — well diversified"

        equities = stats_by_class.get("equities")
        fixed_income = stats_by_class.get("fixed_income")
        if equities and fixed_income:
            drift = equities.annual_return_pct - fixed_income.annual_return_pct
            revision_signal = (
                f"equities have outpaced fixed income by {drift:+.1f}pts annualized — "
                "rebalance to trim equity overweight and restore target weights"
                if abs(drift) > 5
                else "equity/bond drift within tolerance — no urgent rebalancing signal"
            )
        else:
            revision_signal = "insufficient data to assess rebalancing drift"

        if allocations:
            evaluation_signal = (
                f"best Sharpe ratio observed: {max(a.sharpe_ratio for a in allocations):.2f} "
                f"across {len(allocations)} modeled allocations"
            )
        else:
            evaluation_signal = "no allocations evaluated"

        blind_spot_alert = BLIND_SPOTS[0]["description"]

        if allocations and max(a.sharpe_ratio for a in allocations) >= 0.75 and not undiversified:
            conclusion = "Well-constructed, diversified portfolio with favorable risk-adjusted returns"
        elif allocations:
            conclusion = "Portfolio shows room for improvement in diversification and/or risk-adjusted return"
        else:
            conclusion = "Unable to reach a portfolio-level conclusion with available data"

        return PortfolioAssessment(
            allocation_signal=allocation_signal,
            diversification_signal=diversification_signal,
            revision_signal=revision_signal,
            evaluation_signal=evaluation_signal,
            blind_spot_alert=blind_spot_alert,
            conclusion=conclusion,
        )

    @staticmethod
    def _expert_summary(assessment: PortfolioAssessment, label: str, quality: float) -> str:
        return (
            f"Portfolio management scan: {label} (portfolio quality score {quality:.2f}). "
            f"{assessment.allocation_signal}. "
            f"{assessment.diversification_signal}. "
            f"{assessment.revision_signal}. "
            f"{assessment.evaluation_signal}. "
            f"Blind spot watch: {assessment.blind_spot_alert} "
            f"{assessment.conclusion}."
        )

    def analyze(self) -> PortfolioManagementReport:
        return_map: dict[str, list[float]] = {}
        stats_by_class: dict[str, AssetStats] = {}

        for asset_class, info in ASSET_CLASSES.items():
            closes = self._fetch_closes(info["symbol"])
            if closes:
                returns = self._daily_returns(closes)
                return_map[asset_class] = returns
                stats_by_class[asset_class] = self._asset_stats(
                    asset_class, info["symbol"], info["name"], returns
                )
            time.sleep(self.delay_seconds)

        if "equities" not in return_map:
            raise RuntimeError("Unable to fetch SPY data for portfolio management analysis")

        risk_free_pct = self._risk_free_rate()

        correlations = self._correlations(return_map)
        allocations = [
            a for a in (
                self._allocation_assessment(model, stats_by_class, return_map, risk_free_pct)
                for model in ALLOCATION_MODELS
            )
            if a is not None
        ]

        assessment = self._assessment(allocations, correlations, stats_by_class)

        best_allocation = max(allocations, key=lambda a: a.sharpe_ratio) if allocations else None
        avg_diversification = (
            round(statistics.mean(a.diversification_score for a in allocations), 4)
            if allocations else 0.0
        )
        best_sharpe = max((a.sharpe_ratio for a in allocations), default=0.0)
        portfolio_quality = round(
            0.5 * min(1.0, max(best_sharpe, 0.0) / 1.5)
            + 0.3 * avg_diversification
            + 0.2 * min(1.0, len(return_map) / len(ASSET_CLASSES)),
            4,
        )

        if portfolio_quality >= 0.65:
            regime_label = "Efficient Allocation"
        elif portfolio_quality >= 0.4:
            regime_label = "Adequate Allocation"
        else:
            regime_label = "Suboptimal Allocation"

        summary = self._expert_summary(assessment, regime_label, portfolio_quality)
        signals = self._market_signals(allocations, correlations, stats_by_class)
        recs = self._recommendations(assessment, allocations, correlations, stats_by_class)

        return PortfolioManagementReport(
            risk_free_rate_pct=risk_free_pct,
            asset_stats=list(stats_by_class.values()),
            correlations=correlations,
            allocations=allocations,
            phases=FOUR_PHASES,
            blind_spots=BLIND_SPOTS,
            assessment=assessment,
            best_allocation_id=best_allocation.model_id if best_allocation else "",
            portfolio_quality_score=portfolio_quality,
            regime_label=regime_label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source="Yahoo Finance API",
        )

    @staticmethod
    def _market_signals(
        allocations: list[AllocationAssessment],
        correlations: list[CorrelationPair],
        stats_by_class: dict[str, AssetStats],
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        for a in allocations:
            bias = "BULLISH" if a.sharpe_ratio >= 0.75 else "NEUTRAL" if a.sharpe_ratio >= 0.3 else "BEARISH"
            signals.append({
                "sector": a.name,
                "tickers": [ASSET_CLASSES[c]["symbol"] for c in a.weights],
                "bias": bias,
                "reason": f"Sharpe={a.sharpe_ratio:.2f}, E[R]={a.expected_annual_return_pct:+.1f}%, σ={a.expected_annual_vol_pct:.1f}%",
            })

        for c in correlations:
            if not c.diversified:
                signals.append({
                    "sector": f"Correlation Risk — {c.asset_a}/{c.asset_b}",
                    "tickers": [
                        ASSET_CLASSES.get(c.asset_a, {}).get("symbol", c.asset_a),
                        ASSET_CLASSES.get(c.asset_b, {}).get("symbol", c.asset_b),
                    ],
                    "bias": "BEARISH",
                    "reason": c.interpretation,
                })

        if not signals:
            signals.append({
                "sector": "Portfolio Neutral",
                "tickers": ["SPY"],
                "bias": "NEUTRAL",
                "reason": "Insufficient data to model allocations",
            })
        return signals

    @staticmethod
    def _recommendations(
        assessment: PortfolioAssessment,
        allocations: list[AllocationAssessment],
        correlations: list[CorrelationPair],
        stats_by_class: dict[str, AssetStats],
    ) -> list[str]:
        recs = [
            assessment.allocation_signal,
            assessment.diversification_signal,
            assessment.revision_signal,
            assessment.evaluation_signal,
            assessment.conclusion,
        ]
        for a in sorted(allocations, key=lambda x: -x.sharpe_ratio):
            recs.append(
                f"{a.name}: E[R]={a.expected_annual_return_pct:+.1f}%, σ={a.expected_annual_vol_pct:.1f}%, "
                f"Sharpe={a.sharpe_ratio:.2f}, diversification={a.diversification_score:.2f}"
            )
        for stat in stats_by_class.values():
            recs.append(
                f"{stat.name} ({stat.symbol}): annualized return {stat.annual_return_pct:+.1f}%, "
                f"volatility {stat.annual_vol_pct:.1f}%"
            )
        for c in correlations:
            recs.append(f"{c.asset_a} vs {c.asset_b}: {c.interpretation}")
        for spot in BLIND_SPOTS:
            recs.append(f"Blind spot — {spot['name']}: {spot['description']}")
        return recs

    def to_dict(self, report: PortfolioManagementReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Portfolio Management Expert",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "risk_free_rate_pct": report.risk_free_rate_pct,
                "expert_summary": report.expert_summary,
                "allocation_models_applied": [m["id"] for m in ALLOCATION_MODELS],
            },
            "allocation_models": ALLOCATION_MODELS,
            "four_phases": report.phases,
            "blind_spots": report.blind_spots,
            "asset_stats": [
                {
                    "asset_class": s.asset_class,
                    "symbol": s.symbol,
                    "name": s.name,
                    "annual_return_pct": s.annual_return_pct,
                    "annual_vol_pct": s.annual_vol_pct,
                    "sample_size": s.sample_size,
                }
                for s in report.asset_stats
            ],
            "correlations": [
                {
                    "asset_a": c.asset_a,
                    "asset_b": c.asset_b,
                    "correlation": c.correlation,
                    "diversified": c.diversified,
                    "interpretation": c.interpretation,
                }
                for c in report.correlations
            ],
            "allocations": [
                {
                    "model_id": al.model_id,
                    "name": al.name,
                    "description": al.description,
                    "weights": al.weights,
                    "expected_annual_return_pct": al.expected_annual_return_pct,
                    "expected_annual_vol_pct": al.expected_annual_vol_pct,
                    "sharpe_ratio": al.sharpe_ratio,
                    "diversification_score": al.diversification_score,
                    "interpretation": al.interpretation,
                }
                for al in report.allocations
            ],
            "portfolio_assessment": {
                "allocation_signal": a.allocation_signal,
                "diversification_signal": a.diversification_signal,
                "revision_signal": a.revision_signal,
                "evaluation_signal": a.evaluation_signal,
                "blind_spot_alert": a.blind_spot_alert,
                "conclusion": a.conclusion,
            },
            "metrics": {
                "portfolio_quality_score": report.portfolio_quality_score,
                "regime_label": report.regime_label,
                "best_allocation_id": report.best_allocation_id,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "portfolio_frameworks.json"
            catalog.write_text(
                json.dumps(
                    {
                        "allocation_models": ALLOCATION_MODELS,
                        "four_phases": FOUR_PHASES,
                        "blind_spots": BLIND_SPOTS,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        return result


def run_portfolio_management_analysis(output: Path | None = None) -> dict[str, Any]:
    return PortfolioManagementExpert().run(output=output)
