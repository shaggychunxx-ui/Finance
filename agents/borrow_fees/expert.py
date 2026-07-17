"""
Cost-to-Borrow (Short Borrow Fee) Expert Agent
===============================================
Expert analyst view of stock borrow fees ("cost-to-borrow"/CTB) — the
annualized interest rate a short seller pays to borrow shares from a
lender. Fees are dynamic, computed daily, and billed monthly:

    Daily Fee = (Shares Shorted * Stock Price * Borrow Fee Rate) / 360

Since no brokerage CTB feed (Shares Available / CTB Min / Max / Average /
Days to Cover) is reachable from this sandbox, the agent derives a
calibrated CTB-rate proxy from public Yahoo Finance data: realized
volatility, overnight-gap frequency, and dollar-volume thinness stand in
for the scarcity signals (short interest pressure, shares-available
depletion) that drive real borrow desks.

Data: Yahoo Finance chart API (3-month daily OHLCV).
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

# Mix of hard-to-borrow-prone names alongside easy-to-borrow mega-caps so the
# ETB/HTB contrast in the borrow-fee proxy is grounded in real market data.
WATCHLIST: dict[str, str] = {
    "SPY": "S&P 500 ETF (deep lending pool)",
    "AAPL": "Mega-cap tech (easy-to-borrow)",
    "MSFT": "Mega-cap tech (easy-to-borrow)",
    "QQQ": "Nasdaq 100 ETF (deep lending pool)",
    "IWM": "Russell 2000 ETF (moderate lending pool)",
    "GME": "Retail-driven small/mid cap (hard-to-borrow prone)",
    "COIN": "Crypto-adjacent equity (hard-to-borrow prone)",
    "PLTR": "High-beta growth name (moderate-to-thin lending pool)",
}

# Annualized-fee brackets used purely as an illustrative CTB scale, per the
# ETB (0.25%-1.5%) / HTB (5%-300%+) split described by clearing firms.
ETB_MIN_RATE_PCT = 0.25
ETB_MAX_RATE_PCT = 1.5
HTB_MIN_RATE_PCT = 5.0
HTB_MAX_RATE_PCT = 300.0

# Broker convention used in the daily-fee worked example (some brokers use a
# 365-day year instead).
FEE_DAY_COUNT = 360
SAMPLE_POSITION_USD = 50_000.0  # notional short size used for the $/day illustration

DEEP_LIQUIDITY_USD = 200_000_000
MODERATE_LIQUIDITY_USD = 25_000_000

SQUEEZE_SCORE_THRESHOLD = 6.5  # 0-10 squeeze-risk score that flags "ticking time bomb" names

# Scarcity/CTB-rate proxy tuning constants (see _ctb_avg_pct/_analyze_symbol).
SCARCITY_TO_CTB_MULTIPLIER = 8.0  # scales the volatility/gap/liquidity scarcity score into an annualized CTB %
ABUNDANT_SPREAD_FACTOR = 0.15  # CTB min/max spread (as a fraction of the average) for Abundant lending pools
SCARCE_SPREAD_FACTOR = 0.4  # wider CTB min/max spread for Limited/Scarce lending pools
DAYS_TO_COVER_SCALING_FACTOR = 15.0  # scales sample-position-vs-dollar-volume ratio into a days-to-cover proxy
MAX_DAYS_TO_COVER_PROXY = 30.0  # cap on the days-to-cover proxy
SQUEEZE_CTB_WEIGHT = 6.0  # weight of the CTB-rate component (out of 10) in the squeeze-risk score
SQUEEZE_DTC_WEIGHT = 4.0  # weight of the days-to-cover component (out of 10) in the squeeze-risk score

CTB_DATA_METRICS: list[dict[str, str]] = [
    {
        "metric": "Shares Available",
        "meaning": "The physical pool of shares a broker has left to lend out.",
        "how_to_use": "If this drops near 0, expect the fee rate to explode shortly after.",
    },
    {
        "metric": "CTB Min / Max",
        "meaning": "The lowest and highest fee rates being quoted across different lenders.",
        "how_to_use": "Wide spreads mean high market volatility and disjointed broker inventory.",
    },
    {
        "metric": "CTB Average",
        "meaning": "The blended average rate short sellers are actively paying right now.",
        "how_to_use": "Use this as your baseline for calculating daily holding costs.",
    },
    {
        "metric": "Days to Cover",
        "meaning": "Short Interest divided by Average Daily Trading Volume.",
        "how_to_use": "Higher numbers (> 5 days) mean short sellers cannot exit quickly if a squeeze starts.",
    },
]

SQUEEZE_CHAIN_REACTION: list[str] = [
    "High Borrow Fees",
    "Erodes Short Seller Capital Daily",
    "Sellers Forced to Buy to Close",
    "Stock Price Surges",
    "More Short Sellers Liquidated",
]


@dataclass
class SymbolBorrowFee:
    symbol: str
    name: str
    last_close: float
    atr_pct: float
    max_overnight_gap_pct: float
    avg_dollar_volume: float
    shares_available_tier: str
    borrow_category: str
    ctb_min_pct: float
    ctb_max_pct: float
    ctb_avg_pct: float
    days_to_cover_proxy: float
    daily_fee_usd: float
    squeeze_risk_score: float
    rationale: str


@dataclass
class BorrowFeeAssessment:
    market_regime: str
    scarcity_signal: str
    squeeze_watch_signal: str
    billing_note: str
    conclusion: str


@dataclass
class BorrowFeeReport:
    symbols: list[SymbolBorrowFee]
    assessment: BorrowFeeAssessment
    avg_ctb_pct: float
    htb_count: int
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class BorrowFeeExpert(BaseExpert):
    """Expert analyst — stock borrow fees (cost-to-borrow) and squeeze risk."""

    def __init__(
        self,
        delay_seconds: float = 0.35,
        *,
        pipeline_context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="borrow-fees")
        self.delay_seconds = delay_seconds

    @staticmethod
    def _true_ranges(data: dict[str, list[float]]) -> list[float]:
        highs, lows, closes = data["high"], data["low"], data["close"]
        ranges: list[float] = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            ranges.append(tr)
        return ranges

    @staticmethod
    def _shares_available_tier(avg_dollar_volume: float) -> str:
        if avg_dollar_volume >= DEEP_LIQUIDITY_USD:
            return "Abundant"
        if avg_dollar_volume >= MODERATE_LIQUIDITY_USD:
            return "Limited"
        return "Scarce"

    @staticmethod
    def _ctb_avg_pct(atr_pct: float, gap_pct: float, tier: str) -> float:
        """Calibrated CTB-rate proxy: volatility + gap frequency + thinness -> scarcity."""
        tier_multiplier = {"Abundant": 0.2, "Limited": 1.0, "Scarce": 2.6}[tier]
        scarcity_score = (atr_pct * 0.6 + gap_pct * 0.4) * tier_multiplier
        # Map the scarcity score onto the ETB..HTB annualized-rate spectrum.
        rate = ETB_MIN_RATE_PCT + scarcity_score * SCARCITY_TO_CTB_MULTIPLIER
        return round(min(max(rate, ETB_MIN_RATE_PCT), HTB_MAX_RATE_PCT), 2)

    def _analyze_symbol(self, symbol: str, name: str) -> SymbolBorrowFee | None:
        data = self.fetch_yahoo_ohlcv(symbol, range_="3mo", interval="1d")
        closes = data["close"]
        if len(closes) < 15:
            return None

        last_close = closes[-1]
        window = min(len(closes), 20)
        recent_closes = closes[-window:]
        recent_opens = data["open"][-window:]
        recent_volumes = data["volume"][-window:]

        true_ranges = self._true_ranges(data)
        atr = statistics.mean(true_ranges[-14:]) if true_ranges else 0.0
        atr_pct = (atr / last_close) * 100 if last_close else 0.0

        gaps = [
            abs(recent_opens[i] - recent_closes[i - 1]) / recent_closes[i - 1] * 100
            for i in range(1, len(recent_closes))
            if recent_closes[i - 1]
        ]
        max_overnight_gap_pct = max(gaps) if gaps else 0.0

        avg_dollar_volume = statistics.mean(
            [c * v for c, v in zip(recent_closes, recent_volumes)]
        )
        shares_available_tier = self._shares_available_tier(avg_dollar_volume)

        ctb_avg_pct = self._ctb_avg_pct(atr_pct, max_overnight_gap_pct, shares_available_tier)
        borrow_category = "Hard-to-Borrow (HTB)" if ctb_avg_pct >= HTB_MIN_RATE_PCT else "Easy-to-Borrow (ETB)"
        # Min/max spread widens with scarcity — thin, hard-to-borrow names see
        # much more dispersion across lenders than deep-pool mega-caps.
        spread_pct = ctb_avg_pct * (ABUNDANT_SPREAD_FACTOR if shares_available_tier == "Abundant" else SCARCE_SPREAD_FACTOR)
        ctb_min_pct = round(max(ETB_MIN_RATE_PCT * 0.5, ctb_avg_pct - spread_pct), 2)
        ctb_max_pct = round(min(HTB_MAX_RATE_PCT, ctb_avg_pct + spread_pct), 2)

        # Days to Cover proxy: thinner dollar volume relative to position size
        # implies more days needed to unwind a short without moving the tape.
        days_to_cover_proxy = round(
            min(
                SAMPLE_POSITION_USD / max(avg_dollar_volume, 1.0) * DAYS_TO_COVER_SCALING_FACTOR,
                MAX_DAYS_TO_COVER_PROXY,
            ),
            1,
        )

        shares_shorted = SAMPLE_POSITION_USD / last_close if last_close else 0.0
        daily_fee_usd = round(
            (shares_shorted * last_close * (ctb_avg_pct / 100.0)) / FEE_DAY_COUNT, 2
        )

        squeeze_risk_score = round(
            min(
                (ctb_avg_pct / HTB_MAX_RATE_PCT) * SQUEEZE_CTB_WEIGHT
                + (days_to_cover_proxy / MAX_DAYS_TO_COVER_PROXY) * SQUEEZE_DTC_WEIGHT,
                10.0,
            ),
            1,
        )

        if borrow_category.startswith("Hard"):
            rationale = (
                f"{shares_available_tier} lending pool, {atr_pct:.2f}% ATR and "
                f"{max_overnight_gap_pct:.2f}% max overnight gap imply elevated short "
                f"demand pressure — proxy CTB {ctb_avg_pct:.2f}% annualized "
                f"(${daily_fee_usd:.2f}/day on a ${SAMPLE_POSITION_USD:,.0f} short)."
            )
        else:
            rationale = (
                f"{shares_available_tier} lending pool with calm volatility "
                f"({atr_pct:.2f}% ATR) — proxy CTB {ctb_avg_pct:.2f}% annualized, "
                f"a minimal ${daily_fee_usd:.2f}/day on a ${SAMPLE_POSITION_USD:,.0f} short."
            )

        return SymbolBorrowFee(
            symbol=symbol,
            name=name,
            last_close=round(last_close, 2),
            atr_pct=round(atr_pct, 2),
            max_overnight_gap_pct=round(max_overnight_gap_pct, 2),
            avg_dollar_volume=round(avg_dollar_volume, 0),
            shares_available_tier=shares_available_tier,
            borrow_category=borrow_category,
            ctb_min_pct=ctb_min_pct,
            ctb_max_pct=ctb_max_pct,
            ctb_avg_pct=ctb_avg_pct,
            days_to_cover_proxy=days_to_cover_proxy,
            daily_fee_usd=daily_fee_usd,
            squeeze_risk_score=squeeze_risk_score,
            rationale=rationale,
        )

    def _assessment(self, symbols: list[SymbolBorrowFee]) -> BorrowFeeAssessment:
        htb = [s for s in symbols if s.borrow_category.startswith("Hard")]
        scarce = [s for s in symbols if s.shares_available_tier == "Scarce"]
        squeeze_watch = [s for s in symbols if s.squeeze_risk_score >= SQUEEZE_SCORE_THRESHOLD]

        avg_ctb = statistics.mean([s.ctb_avg_pct for s in symbols]) if symbols else 0.0
        market_regime = (
            f"{len(htb)}/{len(symbols)} watchlist names proxy as Hard-to-Borrow "
            f"(blended CTB avg {avg_ctb:.2f}%)."
        )
        scarcity_signal = (
            f"{len(scarce)}/{len(symbols)} names show a scarce lending-pool proxy — "
            "shares-available pressure that typically precedes a CTB spike."
        )
        squeeze_watch_signal = (
            f"{len(squeeze_watch)}/{len(symbols)} names score >= {SQUEEZE_SCORE_THRESHOLD} on the "
            "squeeze-risk scale (borrow-fee drag + slow days-to-cover)."
        )
        billing_note = (
            f"Fees are calculated daily but billed monthly using a "
            f"{FEE_DAY_COUNT}-day convention: Daily Fee = (Shares x Price x Rate) / {FEE_DAY_COUNT}."
        )
        if squeeze_watch:
            conclusion = (
                "Elevated borrow-fee drag on "
                + ", ".join(s.symbol for s in squeeze_watch)
                + " — daily capital erosion raises the odds of forced short covering "
                "and a squeeze if price momentum turns higher."
            )
        elif htb:
            conclusion = (
                "Borrow fees are elevated but days-to-cover remains manageable — "
                "monitor shares-available for further tightening before flagging squeeze risk."
            )
        else:
            conclusion = (
                "Lending pools are broadly abundant across the watchlist — borrow "
                "costs are a minor drag on short positions right now."
            )
        return BorrowFeeAssessment(
            market_regime=market_regime,
            scarcity_signal=scarcity_signal,
            squeeze_watch_signal=squeeze_watch_signal,
            billing_note=billing_note,
            conclusion=conclusion,
        )

    def _expert_summary(self, assessment: BorrowFeeAssessment) -> str:
        return (
            f"Cost-to-borrow scan: {assessment.market_regime} {assessment.scarcity_signal} "
            f"{assessment.squeeze_watch_signal} {assessment.billing_note} "
            f"{assessment.conclusion}"
        )

    def _market_signals(self, symbols: list[SymbolBorrowFee]) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        def _keep(symbol: str) -> bool:
            return not self.pipeline_should_skip_symbol(symbol)

        squeeze_watch = [
            s.symbol for s in symbols if s.squeeze_risk_score >= SQUEEZE_SCORE_THRESHOLD and _keep(s.symbol)
        ]
        if squeeze_watch:
            signals.append(
                {
                    "sector": "Short Borrow / Squeeze Risk",
                    "bias": "squeeze-watch",
                    "tickers": squeeze_watch,
                    "reason": "High proxy CTB + slow days-to-cover — short capital erosion favors a squeeze.",
                }
            )
        htb = [s.symbol for s in symbols if s.borrow_category.startswith("Hard") and _keep(s.symbol)]
        if htb:
            signals.append(
                {
                    "sector": "Short Borrow / Squeeze Risk",
                    "bias": "hard-to-borrow",
                    "tickers": htb,
                    "reason": "Proxy CTB in the Hard-to-Borrow range — shorting carries a meaningful daily fee drag.",
                }
            )
        etb = [s.symbol for s in symbols if s.borrow_category.startswith("Easy") and _keep(s.symbol)]
        if etb:
            signals.append(
                {
                    "sector": "Short Borrow / Squeeze Risk",
                    "bias": "easy-to-borrow",
                    "tickers": etb,
                    "reason": "Abundant lending pool — borrow fees are a minor cost for short positions.",
                }
            )
        return signals

    def _recommendations(
        self, symbols: list[SymbolBorrowFee], assessment: BorrowFeeAssessment
    ) -> list[str]:
        recs = [assessment.conclusion, assessment.billing_note]
        for s in sorted(symbols, key=lambda x: -x.squeeze_risk_score)[:6]:
            recs.append(
                f"{s.symbol} ({s.borrow_category}): CTB avg {s.ctb_avg_pct:.2f}% "
                f"(min {s.ctb_min_pct:.2f}% / max {s.ctb_max_pct:.2f}%), "
                f"days-to-cover proxy {s.days_to_cover_proxy:.1f}, "
                f"squeeze-risk {s.squeeze_risk_score:.1f}/10 — {s.rationale}"
            )
        return recs

    def analyze(self) -> BorrowFeeReport:
        symbols: list[SymbolBorrowFee] = []
        for symbol, name in WATCHLIST.items():
            row = self._analyze_symbol(symbol, name)
            if row:
                symbols.append(row)
            time.sleep(self.delay_seconds)

        if not any(s.symbol == BENCHMARK for s in symbols):
            raise RuntimeError("Unable to fetch SPY data for borrow fee analysis")

        assessment = self._assessment(symbols)
        expert_summary = self._expert_summary(assessment)
        avg_ctb_pct = round(statistics.mean([s.ctb_avg_pct for s in symbols]), 2)
        htb_count = sum(1 for s in symbols if s.borrow_category.startswith("Hard"))

        return BorrowFeeReport(
            symbols=symbols,
            assessment=assessment,
            avg_ctb_pct=avg_ctb_pct,
            htb_count=htb_count,
            expert_summary=expert_summary,
            market_signals=self._market_signals(symbols),
            recommendations=self._recommendations(symbols, assessment),
            data_source="Yahoo Finance Chart API (3mo daily OHLCV)",
        )

    def to_dict(self, report: BorrowFeeReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Cost-to-Borrow (Short Borrow Fee) Expert",
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
            "fee_formula": {
                "description": "Daily Fee = (Shares Shorted * Stock Price * Borrow Fee Rate) / day_count",
                "day_count_convention": FEE_DAY_COUNT,
                "sample_position_usd": SAMPLE_POSITION_USD,
            },
            "ctb_rate_bands_pct": {
                "easy_to_borrow": {"min": ETB_MIN_RATE_PCT, "max": ETB_MAX_RATE_PCT},
                "hard_to_borrow": {"min": HTB_MIN_RATE_PCT, "max": HTB_MAX_RATE_PCT},
            },
            "data_metrics_glossary": CTB_DATA_METRICS,
            "squeeze_chain_reaction": SQUEEZE_CHAIN_REACTION,
            "symbol_borrow_fees": [
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "last_close": s.last_close,
                    "atr_pct": s.atr_pct,
                    "max_overnight_gap_pct": s.max_overnight_gap_pct,
                    "avg_dollar_volume": s.avg_dollar_volume,
                    "shares_available_tier": s.shares_available_tier,
                    "borrow_category": s.borrow_category,
                    "ctb_min_pct": s.ctb_min_pct,
                    "ctb_max_pct": s.ctb_max_pct,
                    "ctb_avg_pct": s.ctb_avg_pct,
                    "days_to_cover_proxy": s.days_to_cover_proxy,
                    "daily_fee_usd": s.daily_fee_usd,
                    "squeeze_risk_score": s.squeeze_risk_score,
                    "rationale": s.rationale,
                }
                for s in report.symbols
            ],
            "borrow_fee_assessment": {
                "market_regime": a.market_regime,
                "scarcity_signal": a.scarcity_signal,
                "squeeze_watch_signal": a.squeeze_watch_signal,
                "billing_note": a.billing_note,
                "conclusion": a.conclusion,
            },
            "metrics": {
                "avg_ctb_pct": report.avg_ctb_pct,
                "htb_count": report.htb_count,
            },
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "borrow_fee_data_metrics.json"
            catalog.write_text(
                json.dumps(CTB_DATA_METRICS, indent=2),
                encoding="utf-8",
            )
        return result


def run_borrow_fees_analysis(
    output: Path | None = None,
    pipeline_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return BorrowFeeExpert(pipeline_context=pipeline_context).run(output=output)
