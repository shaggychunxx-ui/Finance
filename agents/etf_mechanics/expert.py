"""
ETF Creation & Redemption Mechanics Expert Agent
=================================================
Primary-market view of how Authorized Participants (APs) arbitrage the gap
between an ETF's secondary-market price and its underlying NAV via in-kind
or cash creation/redemption, and how that activity shows up as fund flow.

Data: Yahoo Finance chart API (3-month daily OHLCV). Real primary-market
Portfolio Composition Files (PCF) and shares-outstanding series are not
available from this feed, so the NAV, premium/discount, and fund-flow
figures below are calibrated proxies derived from price/volume action, not
a live feed of AP creation-unit activity.
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

# Representative ETF across each structural variation described in the
# creation/redemption model: standard equity in-kind, fixed income (cash),
# emerging markets (cash, capital controls), and physical commodity (cash).
WATCHLIST: dict[str, str] = {
    "SPY": "SPDR S&P 500 (large-cap equity, in-kind)",
    "QQQ": "Invesco Nasdaq-100 (large-cap equity, in-kind)",
    "IWM": "iShares Russell 2000 (small-cap equity, in-kind)",
    "LQD": "iShares iBoxx IG Corporate Bond (fixed income, cash)",
    "EEM": "iShares MSCI Emerging Markets (EM equity, cash/hybrid)",
    "GLD": "SPDR Gold Shares (physical commodity, cash)",
}

# Typical creation-unit size (ETF shares per primary-market block), used
# purely to illustrate the scale of an AP's basket trade.
CREATION_UNIT_SHARES: dict[str, int] = {
    "SPY": 50_000,
    "QQQ": 50_000,
    "IWM": 50_000,
    "LQD": 100_000,
    "EEM": 100_000,
    "GLD": 100_000,
}

PREMIUM_ARB_THRESHOLD_PCT = 0.15  # deviation beyond which an AP would step in
VOLUME_ZSCORE_ARB_THRESHOLD = 1.0

CREATION_MECHANISM_PLAYBOOK: list[dict[str, Any]] = [
    {
        "step": 1,
        "id": "basket_assembly",
        "name": "Basket Assembly",
        "actor": "Authorized Participant (AP)",
        "action": (
            "Reads the sponsor's daily Portfolio Composition File (PCF) and buys "
            "the exact underlying securities required for one Creation Unit."
        ),
    },
    {
        "step": 2,
        "id": "in_kind_transfer",
        "name": "In-Kind Transfer",
        "actor": "Authorized Participant (AP)",
        "action": "Delivers the creation basket of securities to the ETF custodian bank.",
    },
    {
        "step": 3,
        "id": "share_issuance",
        "name": "Share Issuance",
        "actor": "ETF Sponsor / Trustee",
        "action": (
            "Issues a brand-new Creation Unit of ETF shares to the AP, typically "
            "swapped in-kind with no cash changing hands."
        ),
    },
    {
        "step": 4,
        "id": "arbitrage_realization",
        "name": "Arbitrage Realization",
        "actor": "Authorized Participant (AP)",
        "action": (
            "Sells the new ETF shares on the secondary market, increasing supply "
            "and driving the premium back toward NAV."
        ),
    },
]

REDEMPTION_MECHANISM_PLAYBOOK: list[dict[str, Any]] = [
    {
        "step": 1,
        "id": "share_accumulation",
        "name": "Share Accumulation",
        "actor": "Authorized Participant (AP)",
        "action": "Buys underpriced ETF shares on the secondary exchange at a discount.",
    },
    {
        "step": 2,
        "id": "in_kind_delivery",
        "name": "In-Kind Delivery",
        "actor": "Authorized Participant (AP)",
        "action": "Aggregates shares into a full Creation Unit and delivers them to the ETF custodian.",
    },
    {
        "step": 3,
        "id": "basket_return",
        "name": "Basket Return",
        "actor": "ETF Sponsor / Trustee",
        "action": (
            "Cancels the returned ETF shares and delivers the corresponding "
            "redemption basket of underlying assets back to the AP."
        ),
    },
    {
        "step": 4,
        "id": "arbitrage_realization",
        "name": "Arbitrage Realization",
        "actor": "Authorized Participant (AP)",
        "action": (
            "Sells the underlying securities on the open market, reducing secondary "
            "supply and driving the discount back toward NAV."
        ),
    },
]

STRUCTURAL_MODEL: dict[str, dict[str, str]] = {
    "SPY": {
        "model": "in_kind",
        "rationale": "Liquid, exchange-listed large-cap basket — securities move in-kind.",
    },
    "QQQ": {
        "model": "in_kind",
        "rationale": "Liquid, exchange-listed large-cap basket — securities move in-kind.",
    },
    "IWM": {
        "model": "in_kind",
        "rationale": "Exchange-listed small-cap basket — securities move in-kind.",
    },
    "LQD": {
        "model": "cash",
        "rationale": (
            "Corporate bond markets are decentralized/OTC — assembling a precise "
            "basket of hundreds of illiquid bonds is impractical, so cash is used."
        ),
    },
    "EEM": {
        "model": "cash",
        "rationale": (
            "Foreign capital controls and local transfer rules can prevent moving "
            "local shares to a foreign custodian — cash or hybrid baskets are used."
        ),
    },
    "GLD": {
        "model": "cash",
        "rationale": (
            "Spot-commodity ETFs typically settle in cash; the manager buys/sells "
            "the physical asset rather than the AP delivering it directly."
        ),
    },
}

SYSTEMIC_ADVANTAGES: list[dict[str, str]] = [
    {
        "id": "intraday_liquidity",
        "name": "Arbitrage-Driven Pricing (Intraday Liquidity)",
        "summary": (
            "AP arbitrage keeps the market price within a few basis points of "
            "intraday NAV, unlike mutual funds priced once daily at 4:00 PM EST."
        ),
    },
    {
        "id": "tax_efficiency",
        "name": "Total Tax Efficiency",
        "summary": (
            "In-kind redemptions (IRC Section 851) let ETFs hand off low-cost-basis "
            "shares to APs without realizing capital gains, avoiding the forced "
            "gains distributions mutual funds face on heavy redemptions."
        ),
    },
    {
        "id": "externalized_costs",
        "name": "Externalized Transaction Costs",
        "summary": (
            "The AP bears the brokerage fees, spreads, and commissions of assembling "
            "the basket, insulating existing ETF shareholders from new-money flows."
        ),
    },
]


@dataclass
class ETFArbitrageSnapshot:
    symbol: str
    name: str
    creation_model: str
    creation_model_rationale: str
    creation_unit_shares: int
    last_close: float
    nav_proxy: float
    premium_discount_pct: float
    volume_zscore: float
    arbitrage_signal: str
    flow_proxy_direction: str
    rationale: str


@dataclass
class FundFlowAssessment:
    creation_count: int
    redemption_count: int
    neutral_count: int
    avg_abs_premium_discount_pct: float
    tightest_symbol: str
    widest_symbol: str
    conclusion: str


@dataclass
class ETFMechanicsReport:
    symbols: list[ETFArbitrageSnapshot]
    assessment: FundFlowAssessment
    arbitrage_tightness_score: float
    fund_flow_signal_score: float
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ETFMechanicsExpert(BaseExpert):
    """Expert market analyst — ETF creation/redemption mechanics and fund flow."""

    def __init__(
        self,
        delay_seconds: float = 0.35,
        *,
        pipeline_context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="etf-mechanics")
        self.delay_seconds = delay_seconds

    def _analyze_symbol(self, symbol: str, name: str) -> ETFArbitrageSnapshot | None:
        data = self.fetch_yahoo_ohlcv(symbol, range_="3mo", interval="1d")
        closes = data["close"]
        volumes = data["volume"]
        if len(closes) < 10:
            return None

        last_close = closes[-1]

        # NAV proxy: a short trailing average smooths out the noise of secondary
        # market supply/demand friction, standing in for the "true" basket value
        # an AP would compare the traded price against.
        nav_window = closes[-6:-1] if len(closes) >= 6 else closes[:-1] or closes
        nav_proxy = statistics.mean(nav_window) if nav_window else last_close
        premium_discount_pct = (
            (last_close - nav_proxy) / nav_proxy * 100 if nav_proxy else 0.0
        )

        recent_volumes = volumes[-20:] if len(volumes) >= 20 else volumes
        if len(recent_volumes) >= 2 and statistics.stdev(recent_volumes) > 0:
            vol_mean = statistics.mean(recent_volumes)
            vol_std = statistics.stdev(recent_volumes)
            volume_zscore = (recent_volumes[-1] - vol_mean) / vol_std
        else:
            volume_zscore = 0.0

        model_info = STRUCTURAL_MODEL.get(
            symbol, {"model": "in_kind", "rationale": "Standard in-kind equity basket."}
        )

        arb_active = (
            abs(premium_discount_pct) >= PREMIUM_ARB_THRESHOLD_PCT
            and volume_zscore >= VOLUME_ZSCORE_ARB_THRESHOLD
        )
        if arb_active and premium_discount_pct > 0:
            arbitrage_signal = "premium-creation-arb"
            flow_proxy_direction = "creation (inflow)"
            rationale = (
                f"Trading {premium_discount_pct:.2f}% above its NAV proxy with a volume "
                f"z-score of {volume_zscore:.2f} — consistent with an AP assembling a "
                "creation basket to sell new shares and close the premium."
            )
        elif arb_active and premium_discount_pct < 0:
            arbitrage_signal = "discount-redemption-arb"
            flow_proxy_direction = "redemption (outflow)"
            rationale = (
                f"Trading {abs(premium_discount_pct):.2f}% below its NAV proxy with a "
                f"volume z-score of {volume_zscore:.2f} — consistent with an AP redeeming "
                "shares for the underlying basket to close the discount."
            )
        else:
            arbitrage_signal = "none"
            flow_proxy_direction = "neutral"
            rationale = (
                f"Price tracking its NAV proxy within {abs(premium_discount_pct):.2f}% — "
                "high secondary-market volume here would be balanced buy/sell activity, "
                "not primary-market flow."
            )

        return ETFArbitrageSnapshot(
            symbol=symbol,
            name=name,
            creation_model=model_info["model"],
            creation_model_rationale=model_info["rationale"],
            creation_unit_shares=CREATION_UNIT_SHARES.get(symbol, 50_000),
            last_close=round(last_close, 2),
            nav_proxy=round(nav_proxy, 2),
            premium_discount_pct=round(premium_discount_pct, 3),
            volume_zscore=round(volume_zscore, 2),
            arbitrage_signal=arbitrage_signal,
            flow_proxy_direction=flow_proxy_direction,
            rationale=rationale,
        )

    def _assessment(self, symbols: list[ETFArbitrageSnapshot]) -> FundFlowAssessment:
        creation_count = sum(1 for s in symbols if s.arbitrage_signal == "premium-creation-arb")
        redemption_count = sum(1 for s in symbols if s.arbitrage_signal == "discount-redemption-arb")
        neutral_count = len(symbols) - creation_count - redemption_count

        avg_abs = statistics.mean([abs(s.premium_discount_pct) for s in symbols])
        by_tightness = sorted(symbols, key=lambda s: abs(s.premium_discount_pct))
        tightest = by_tightness[0].symbol
        widest = by_tightness[-1].symbol

        if creation_count == 0 and redemption_count == 0:
            conclusion = (
                "No AP arbitrage triggers across the watchlist — secondary market "
                "prices are tracking NAV, so trading volume here reflects balanced "
                "buy/sell activity rather than primary-market fund flow."
            )
        elif creation_count >= redemption_count:
            conclusion = (
                f"{creation_count}/{len(symbols)} symbols show premium-driven creation "
                "arbitrage — net fund flow proxy is skewed toward inflows."
            )
        else:
            conclusion = (
                f"{redemption_count}/{len(symbols)} symbols show discount-driven redemption "
                "arbitrage — net fund flow proxy is skewed toward outflows."
            )

        return FundFlowAssessment(
            creation_count=creation_count,
            redemption_count=redemption_count,
            neutral_count=neutral_count,
            avg_abs_premium_discount_pct=round(avg_abs, 3),
            tightest_symbol=tightest,
            widest_symbol=widest,
            conclusion=conclusion,
        )

    def _expert_summary(self, assessment: FundFlowAssessment) -> str:
        return (
            f"ETF mechanics scan: avg |premium/discount| of "
            f"{assessment.avg_abs_premium_discount_pct:.2f}% across the watchlist "
            f"({assessment.creation_count} creation-arb, {assessment.redemption_count} "
            f"redemption-arb, {assessment.neutral_count} neutral). "
            f"Tightest tracking: {assessment.tightest_symbol}; widest: "
            f"{assessment.widest_symbol}. {assessment.conclusion}"
        )

    def _market_signals(self, symbols: list[ETFArbitrageSnapshot]) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        def _keep(symbol: str) -> bool:
            return not self.pipeline_should_skip_symbol(symbol)

        creation = [s.symbol for s in symbols if s.arbitrage_signal == "premium-creation-arb" and _keep(s.symbol)]
        if creation:
            signals.append(
                {
                    "sector": "ETF Mechanics",
                    "bias": "creation-inflow",
                    "tickers": creation,
                    "reason": "Premium to NAV proxy with elevated volume — APs likely creating new shares.",
                }
            )
        redemption = [s.symbol for s in symbols if s.arbitrage_signal == "discount-redemption-arb" and _keep(s.symbol)]
        if redemption:
            signals.append(
                {
                    "sector": "ETF Mechanics",
                    "bias": "redemption-outflow",
                    "tickers": redemption,
                    "reason": "Discount to NAV proxy with elevated volume — APs likely redeeming shares.",
                }
            )
        cash_model = [s.symbol for s in symbols if s.creation_model == "cash" and _keep(s.symbol)]
        if cash_model:
            signals.append(
                {
                    "sector": "ETF Mechanics",
                    "bias": "cash-creation-structure",
                    "tickers": cash_model,
                    "reason": "Cash-model ETF — sponsor charges a transaction fee to the AP to internalize trading costs.",
                }
            )
        return signals

    def _recommendations(
        self, symbols: list[ETFArbitrageSnapshot], assessment: FundFlowAssessment
    ) -> list[str]:
        recs = [assessment.conclusion]
        for s in sorted(symbols, key=lambda x: -abs(x.premium_discount_pct))[:6]:
            recs.append(
                f"{s.symbol} ({s.creation_model} model, {s.creation_unit_shares:,} share "
                f"creation unit): {s.arbitrage_signal} — {s.rationale}"
            )
        return recs

    def analyze(self) -> ETFMechanicsReport:
        symbols: list[ETFArbitrageSnapshot] = []
        for symbol, name in WATCHLIST.items():
            row = self._analyze_symbol(symbol, name)
            if row:
                symbols.append(row)
            time.sleep(self.delay_seconds)

        if not any(s.symbol == BENCHMARK for s in symbols):
            raise RuntimeError("Unable to fetch SPY data for etf-mechanics analysis")

        assessment = self._assessment(symbols)
        expert_summary = self._expert_summary(assessment)

        arbitrage_tightness_score = round(
            max(0.0, 10 - assessment.avg_abs_premium_discount_pct * 10), 1
        )
        fund_flow_signal_score = round(
            (assessment.creation_count + assessment.redemption_count) / len(symbols) * 10, 1
        )

        return ETFMechanicsReport(
            symbols=symbols,
            assessment=assessment,
            arbitrage_tightness_score=arbitrage_tightness_score,
            fund_flow_signal_score=fund_flow_signal_score,
            expert_summary=expert_summary,
            market_signals=self._market_signals(symbols),
            recommendations=self._recommendations(symbols, assessment),
            data_source="Yahoo Finance Chart API (3mo daily OHLCV)",
        )

    def to_dict(self, report: ETFMechanicsReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "ETF Creation & Redemption Mechanics Expert",
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
            "creation_mechanism_playbook": CREATION_MECHANISM_PLAYBOOK,
            "redemption_mechanism_playbook": REDEMPTION_MECHANISM_PLAYBOOK,
            "systemic_advantages": SYSTEMIC_ADVANTAGES,
            "etf_arbitrage_snapshot": [
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "creation_model": s.creation_model,
                    "creation_model_rationale": s.creation_model_rationale,
                    "creation_unit_shares": s.creation_unit_shares,
                    "last_close": s.last_close,
                    "nav_proxy": s.nav_proxy,
                    "premium_discount_pct": s.premium_discount_pct,
                    "volume_zscore": s.volume_zscore,
                    "arbitrage_signal": s.arbitrage_signal,
                    "flow_proxy_direction": s.flow_proxy_direction,
                    "rationale": s.rationale,
                }
                for s in report.symbols
            ],
            "fund_flow_assessment": {
                "creation_count": a.creation_count,
                "redemption_count": a.redemption_count,
                "neutral_count": a.neutral_count,
                "avg_abs_premium_discount_pct": a.avg_abs_premium_discount_pct,
                "tightest_symbol": a.tightest_symbol,
                "widest_symbol": a.widest_symbol,
                "conclusion": a.conclusion,
            },
            "metrics": {
                "arbitrage_tightness_score": report.arbitrage_tightness_score,
                "fund_flow_signal_score": report.fund_flow_signal_score,
            },
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "creation_redemption_playbook.json"
            catalog.write_text(
                json.dumps(
                    {
                        "creation_mechanism": CREATION_MECHANISM_PLAYBOOK,
                        "redemption_mechanism": REDEMPTION_MECHANISM_PLAYBOOK,
                        "systemic_advantages": SYSTEMIC_ADVANTAGES,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        return result


def run_etf_mechanics_analysis(
    output: Path | None = None,
    pipeline_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return ETFMechanicsExpert(pipeline_context=pipeline_context).run(output=output)
