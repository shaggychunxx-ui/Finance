"""
PDT & Margin Stress Expert Agent
================================
Market analyst view of Pattern Day Trader (PDT, FINRA Rule 4210) buying-power
mechanics: how the $25,000 net-equity threshold flips intraday leverage from
4x/2x above the line to 0x below it, the three-phase "margin stress" cycle
(trapped position, maintenance-margin squeeze, phantom day-trading margin
call), the wealth-degrading violation penalties (90-day cash-only restriction,
forced liquidation), and the strategic blueprint to avoid all of it.

Data: Yahoo Finance chart API (3-month daily OHLCV) is used to ground the
maintenance-margin-requirement tiering and overnight-gap/one-day-move stress
tests in real, current volatility rather than only static rules.
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

# Shared 8-symbol watchlist used across the short-selling/microstructure agent
# family so cross-agent fusion can compare signals on the same names.
WATCHLIST: dict[str, str] = {
    "SPY": "S&P 500 (deep liquidity proxy)",
    "AAPL": "Mega-cap tech (deep liquidity)",
    "MSFT": "Mega-cap tech (deep liquidity)",
    "QQQ": "Nasdaq 100 (deep liquidity)",
    "IWM": "Russell 2000 (moderate liquidity)",
    "GME": "Retail-driven small/mid cap (volatile)",
    "COIN": "Crypto-adjacent equity (volatile)",
    "PLTR": "High-beta growth name (moderate-thin liquidity)",
}

PDT_THRESHOLD_USD = 25_000

# FINRA Rule 4210 intraday/overnight day-trading buying-power multipliers.
INTRADAY_LEVERAGE_ABOVE_THRESHOLD = 4.0
OVERNIGHT_LEVERAGE_ABOVE_THRESHOLD = 2.0
INTRADAY_LEVERAGE_BELOW_THRESHOLD = 0.0

# Maintenance Margin Requirement (MMR) tiers used to size the overnight
# margin-squeeze illustration below.
MMR_STANDARD_PCT = 27.5   # blue-chip stocks: 25%-30% MMR, midpoint used
MMR_VOLATILE_PCT = 75.0   # volatile/penny/leveraged ETFs: 50%-100% MMR, midpoint used
VOLATILE_ATR_THRESHOLD_PCT = 4.0  # ATR% at/above this -> broker likely requires elevated MMR

# Illustrative below-threshold margin account used for the maintenance-margin
# squeeze walkthrough (mirrors the $20k equity / $40k overnight position /
# 100% utilization example in the strategic brief).
ASSUMED_BELOW_THRESHOLD_EQUITY_USD = 20_000
# Illustrative above-threshold margin account used for the leverage-engine /
# overnight-margin-call walkthrough (mirrors the $30k equity example).
ASSUMED_ABOVE_THRESHOLD_EQUITY_USD = 30_000

TRAPPED_POSITION_GAP_THRESHOLD_PCT = 10.0  # overnight gap risk flag for the "trapped position" dilemma
SQUEEZE_MOVE_THRESHOLD_PCT = 1.0  # a "typical" daily move at/above this can instantly breach a 100%-utilized cushion

PDT_MECHANICS: list[dict[str, Any]] = [
    {
        "id": "above_threshold",
        "regime": f"Above ${PDT_THRESHOLD_USD:,} net equity",
        "label": "The Leverage Engine",
        "intraday_leverage": f"{INTRADAY_LEVERAGE_ABOVE_THRESHOLD:.0f}x (Net Equity - MMR)",
        "overnight_leverage": f"{OVERNIGHT_LEVERAGE_ABOVE_THRESHOLD:.0f}x equity",
        "description": (
            "Buying power is 4x (Net Equity - Maintenance Margin Requirement) intraday, "
            "provided the position is closed by 4:00 PM. At the close, the calculation "
            "drops to 2x equity — any 4x intraday position held overnight instantly "
            "triggers an overnight margin call for the shortfall."
        ),
    },
    {
        "id": "below_threshold",
        "regime": f"Below ${PDT_THRESHOLD_USD:,} net equity",
        "label": "The Trap Slams Shut",
        "intraday_leverage": f"{INTRADAY_LEVERAGE_BELOW_THRESHOLD:.0f}x",
        "overnight_leverage": "Cash-only / standard Reg T",
        "description": (
            "The moment equity closes below $25,000, intraday day-trading buying power "
            "drops to 0x. Day trades are hard-blocked or, if executed, trigger a Day "
            "Trading Margin Call (DTMC)."
        ),
    },
]

MARGIN_STRESS_PHASES: list[dict[str, Any]] = [
    {
        "id": "trapped_position",
        "phase": 1,
        "name": "The \"Trapped Position\" Dilemma",
        "trigger": "A volatile intraday position drops sharply while account equity is below $25,000.",
        "stress": (
            "Selling to cut losses is a same-day round trip -> PDT violation and margin "
            "call. Holding overnight exposes the account to gapping risk at the next open."
        ),
        "outcome": "Traders freeze, letting manageable losses balloon rather than risk a PDT violation.",
    },
    {
        "id": "maintenance_margin_squeeze",
        "phase": 2,
        "name": "The Maintenance Margin Squeeze",
        "trigger": (
            "An overnight position is sized near the 2x overnight buying-power cap "
            "against a broker-set Maintenance Margin Requirement (MMR)."
        ),
        "stress": (
            "Standard blue-chip MMR runs 25%-30%; volatile/penny/leveraged-ETF names run "
            "50%-100%. At 100% utilization of the 2x cap, even a 1% overnight drop can "
            "push required MMR above actual equity."
        ),
        "outcome": "Instant Maintenance Margin Call with no cushion left to absorb normal volatility.",
    },
    {
        "id": "phantom_dtmc",
        "phase": 3,
        "name": "The Phantom Day-Trading Margin Call (DTMC)",
        "trigger": "Day-trading buying power is exceeded, even briefly, regardless of the trade's outcome.",
        "stress": (
            "Unlike a standard margin call (2-5 business days to cure), a DTMC demands "
            "immediate action. Even a profitable round trip closed minutes later can "
            "still generate a five-figure margin call because the buying power was never "
            "legally available."
        ),
        "outcome": "Forced liquidation risk or a 90-day cash-only restriction if the call is not met.",
    },
]

VIOLATION_RULES: list[dict[str, Any]] = [
    {
        "id": "cash_only_restriction",
        "name": "90-Day Cash-Only Restriction (Rule 4210)",
        "trigger": "Failing to meet a DTMC by depositing cash/securities within the broker's timeline (often 2-3 days).",
        "penalty": [
            "Margin privileges completely revoked for 90 days.",
            "Only fully settled cash can be used to trade.",
            "Short-selling and options strategies are fully paralyzed for three months.",
        ],
    },
    {
        "id": "forced_liquidation",
        "name": "Automated Forced Liquidation",
        "trigger": "Equity drops dangerously close to the maintenance minimum, or markets turn highly volatile.",
        "penalty": [
            "No phone call — the broker's risk algorithm liquidates positions at market price.",
            "Liquidation typically executes during high-volatility spikes, at the worst of the bid-ask spread.",
            "Many brokers charge a flat $25-$50 fee per position liquidated by the risk desk.",
        ],
    },
]

STRATEGY_BLUEPRINT: list[dict[str, Any]] = [
    {
        "id": "cash_account_pivot",
        "name": "The Cash Account Pivot",
        "best_for": f"Accounts under ${PDT_THRESHOLD_USD:,}",
        "benefit": "Cash accounts are entirely exempt from PDT rules — day trade as often as you want.",
        "catch": "Only settled funds can be traded; equities and options both settle T+1.",
    },
    {
        "id": "equity_buffer",
        "name": "Build a Permanent Equity Buffer",
        "best_for": "Margin accounts that want to keep day-trading leverage",
        "benefit": "Maintain a $5,000 buffer; avoid using day-trading leverage unless equity is safely above $30,000.",
        "catch": "Requires discipline not to trade right at the $25,000 line, since a 2% index drop can breach it.",
    },
    {
        "id": "alternative_assets",
        "name": "Pivot to Alternative Asset Classes",
        "best_for": "Traders wanting high leverage without the $25,000 headache",
        "benefit": "Micro-futures (e.g. MES, MNQ) are CFTC-regulated, not FINRA — no PDT rule applies.",
        "catch": "Futures leverage and overnight margin risk still apply; account balances as low as $1,000 are possible depending on broker margins.",
    },
]


@dataclass
class SymbolMarginProfile:
    symbol: str
    name: str
    last_close: float
    atr_pct: float
    avg_range_pct: float
    max_overnight_gap_pct: float
    mmr_tier: str
    assumed_mmr_pct: float
    overnight_position_value_usd: float
    required_overnight_mmr_usd: float
    margin_cushion_usd: float
    squeeze_risk_flag: bool
    trapped_position_gap_flag: bool
    rationale: str


@dataclass
class MarginStressAssessment:
    above_threshold_scenario: dict[str, Any]
    below_threshold_scenario: dict[str, Any]
    trapped_position_signal: str
    maintenance_squeeze_signal: str
    phantom_dtmc_signal: str
    blueprint_conclusion: str


@dataclass
class MarginStressReport:
    symbols: list[SymbolMarginProfile]
    assessment: MarginStressAssessment
    margin_stress_score: float
    trapped_position_score: float
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MarginStressExpert(BaseExpert):
    """Expert market analyst — PDT buying-power mechanics and margin stress."""

    def __init__(
        self,
        delay_seconds: float = 0.35,
        *,
        pipeline_context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="margin-stress")
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

    def _analyze_symbol(self, symbol: str, name: str) -> SymbolMarginProfile | None:
        data = self.fetch_yahoo_ohlcv(symbol, range_="3mo", interval="1d")
        closes = data["close"]
        if len(closes) < 15:
            return None

        last_close = closes[-1]
        window = min(len(closes), 20)
        recent_closes = closes[-window:]
        recent_opens = data["open"][-window:]
        recent_highs = data["high"][-window:]
        recent_lows = data["low"][-window:]

        true_ranges = self._true_ranges(data)
        atr = statistics.mean(true_ranges[-14:]) if true_ranges else 0.0
        atr_pct = (atr / last_close) * 100 if last_close else 0.0

        avg_range_pct = statistics.mean(
            [(h - l) / c * 100 for h, l, c in zip(recent_highs, recent_lows, recent_closes) if c]
        )

        gaps = [
            abs(recent_opens[i] - recent_closes[i - 1]) / recent_closes[i - 1] * 100
            for i in range(1, len(recent_closes))
            if recent_closes[i - 1]
        ]
        max_overnight_gap_pct = max(gaps) if gaps else 0.0

        is_volatile = atr_pct >= VOLATILE_ATR_THRESHOLD_PCT
        mmr_tier = "Volatile (50%-100% MMR)" if is_volatile else "Standard (25%-30% MMR)"
        assumed_mmr_pct = MMR_VOLATILE_PCT if is_volatile else MMR_STANDARD_PCT

        overnight_position_value_usd = (
            ASSUMED_BELOW_THRESHOLD_EQUITY_USD * OVERNIGHT_LEVERAGE_ABOVE_THRESHOLD
        )
        required_overnight_mmr_usd = overnight_position_value_usd * assumed_mmr_pct / 100
        margin_cushion_usd = ASSUMED_BELOW_THRESHOLD_EQUITY_USD - required_overnight_mmr_usd

        squeeze_risk_flag = avg_range_pct >= SQUEEZE_MOVE_THRESHOLD_PCT
        trapped_position_gap_flag = max_overnight_gap_pct >= TRAPPED_POSITION_GAP_THRESHOLD_PCT

        if trapped_position_gap_flag:
            rationale = (
                f"Overnight gaps up to {max_overnight_gap_pct:.2f}% — holding a losing "
                "position past the close on this name risks a severe gap against a "
                "PDT-blocked account."
            )
        elif squeeze_risk_flag and margin_cushion_usd < 0:
            rationale = (
                f"{mmr_tier} against a fully-utilized 2x overnight position already "
                f"exceeds the illustrative ${ASSUMED_BELOW_THRESHOLD_EQUITY_USD:,} equity "
                "cushion — a routine daily move can trigger an immediate maintenance call."
            )
        elif squeeze_risk_flag:
            rationale = (
                f"Typical daily range of {avg_range_pct:.2f}% is at/above the "
                f"{SQUEEZE_MOVE_THRESHOLD_PCT:.1f}% breach threshold used in the "
                "maintenance-margin-squeeze walkthrough — thin cushion for overnight holds."
            )
        else:
            rationale = (
                f"{mmr_tier} with calmer {avg_range_pct:.2f}% daily range — overnight "
                "margin cushion is comparatively stable."
            )

        return SymbolMarginProfile(
            symbol=symbol,
            name=name,
            last_close=round(last_close, 2),
            atr_pct=round(atr_pct, 2),
            avg_range_pct=round(avg_range_pct, 2),
            max_overnight_gap_pct=round(max_overnight_gap_pct, 2),
            mmr_tier=mmr_tier,
            assumed_mmr_pct=assumed_mmr_pct,
            overnight_position_value_usd=round(overnight_position_value_usd, 2),
            required_overnight_mmr_usd=round(required_overnight_mmr_usd, 2),
            margin_cushion_usd=round(margin_cushion_usd, 2),
            squeeze_risk_flag=squeeze_risk_flag,
            trapped_position_gap_flag=trapped_position_gap_flag,
            rationale=rationale,
        )

    @staticmethod
    def _above_threshold_scenario() -> dict[str, Any]:
        equity = ASSUMED_ABOVE_THRESHOLD_EQUITY_USD
        intraday_bp = equity * INTRADAY_LEVERAGE_ABOVE_THRESHOLD
        overnight_bp = equity * OVERNIGHT_LEVERAGE_ABOVE_THRESHOLD
        overnight_call_usd = intraday_bp - overnight_bp
        return {
            "equity_usd": equity,
            "intraday_buying_power_usd": intraday_bp,
            "overnight_buying_power_usd": overnight_bp,
            "overnight_margin_call_if_held_usd": overnight_call_usd,
            "narrative": (
                f"${equity:,} equity -> ${intraday_bp:,.0f} intraday (4x) buying power. "
                f"Holding that full position overnight collapses the cap to "
                f"${overnight_bp:,.0f} (2x), triggering an immediate "
                f"${overnight_call_usd:,.0f} overnight margin call."
            ),
        }

    @staticmethod
    def _below_threshold_scenario() -> dict[str, Any]:
        equity = ASSUMED_BELOW_THRESHOLD_EQUITY_USD
        overnight_position_value = equity * OVERNIGHT_LEVERAGE_ABOVE_THRESHOLD
        required_mmr_usd = overnight_position_value * MMR_VOLATILE_PCT / 100
        return {
            "equity_usd": equity,
            "intraday_day_trading_buying_power_usd": equity * INTRADAY_LEVERAGE_BELOW_THRESHOLD,
            "overnight_position_value_usd": overnight_position_value,
            "utilization_of_overnight_cap_pct": 100.0,
            "required_mmr_at_volatile_tier_usd": round(required_mmr_usd, 2),
            "narrative": (
                f"${equity:,} equity is below the ${PDT_THRESHOLD_USD:,} PDT threshold: day-trading "
                "buying power drops to 0x, and a fully-utilized "
                f"${overnight_position_value:,.0f} overnight position at a volatile-tier MMR "
                f"already requires ${required_mmr_usd:,.0f} of maintenance margin against "
                f"just ${equity:,} of equity."
            ),
        }

    def _assessment(self, symbols: list[SymbolMarginProfile]) -> MarginStressAssessment:
        trapped = [s for s in symbols if s.trapped_position_gap_flag]
        squeezed = [s for s in symbols if s.squeeze_risk_flag]
        underwater = [s for s in symbols if s.margin_cushion_usd < 0]

        trapped_position_signal = (
            f"{len(trapped)}/{len(symbols)} symbols show overnight gaps ≥ "
            f"{TRAPPED_POSITION_GAP_THRESHOLD_PCT:.0f}% — the classic setup for the "
            "trapped-position dilemma when equity is below $25,000."
        )
        maintenance_squeeze_signal = (
            f"{len(squeezed)}/{len(symbols)} symbols have a typical daily range ≥ "
            f"{SQUEEZE_MOVE_THRESHOLD_PCT:.1f}%, enough to breach a fully-utilized "
            f"overnight cushion; {len(underwater)}/{len(symbols)} already exceed the "
            "illustrative cushion at a volatile-tier MMR."
        )
        phantom_dtmc_signal = (
            "Any day trade opened while day-trading buying power is 0x can trigger a DTMC "
            "regardless of whether the trade is ultimately profitable."
        )
        if underwater:
            blueprint_conclusion = (
                "Elevated squeeze risk across the watchlist: prioritize the cash-account "
                "pivot or a $5,000+ equity buffer before holding these names on margin overnight."
            )
        elif squeezed:
            blueprint_conclusion = (
                "Moderate squeeze risk: keep overnight margin utilization under 30% of the "
                "2x cap and avoid trading right at the $25,000 line."
            )
        else:
            blueprint_conclusion = (
                "Calm regime across the watchlist, but PDT mechanics remain unforgiving — "
                "maintain the equity buffer regardless of current volatility."
            )

        return MarginStressAssessment(
            above_threshold_scenario=self._above_threshold_scenario(),
            below_threshold_scenario=self._below_threshold_scenario(),
            trapped_position_signal=trapped_position_signal,
            maintenance_squeeze_signal=maintenance_squeeze_signal,
            phantom_dtmc_signal=phantom_dtmc_signal,
            blueprint_conclusion=blueprint_conclusion,
        )

    def _expert_summary(self, assessment: MarginStressAssessment) -> str:
        return (
            f"PDT & margin stress scan: {assessment.trapped_position_signal} "
            f"{assessment.maintenance_squeeze_signal} {assessment.phantom_dtmc_signal} "
            f"{assessment.blueprint_conclusion}"
        )

    def _market_signals(self, symbols: list[SymbolMarginProfile]) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        def _keep(symbol: str) -> bool:
            return not self.pipeline_should_skip_symbol(symbol)

        trapped = [s.symbol for s in symbols if s.trapped_position_gap_flag and _keep(s.symbol)]
        if trapped:
            signals.append(
                {
                    "sector": "Margin Stress",
                    "bias": "trapped-position-risk",
                    "tickers": trapped,
                    "reason": "Large overnight gaps — a PDT-blocked account risks a forced hold through a gap.",
                }
            )
        squeezed = [
            s.symbol
            for s in symbols
            if s.squeeze_risk_flag and s.margin_cushion_usd < 0 and _keep(s.symbol)
        ]
        if squeezed:
            signals.append(
                {
                    "sector": "Margin Stress",
                    "bias": "maintenance-squeeze-risk",
                    "tickers": squeezed,
                    "reason": "Fully-utilized overnight margin cushion already exceeded at a volatile-tier MMR.",
                }
            )
        stable = [
            s.symbol
            for s in symbols
            if not s.squeeze_risk_flag and not s.trapped_position_gap_flag and _keep(s.symbol)
        ]
        if stable:
            signals.append(
                {
                    "sector": "Margin Stress",
                    "bias": "stable-cushion",
                    "tickers": stable,
                    "reason": "Calmer volatility profile — lower overnight margin-squeeze risk at standard MMR tiers.",
                }
            )
        return signals

    def _recommendations(
        self, symbols: list[SymbolMarginProfile], assessment: MarginStressAssessment
    ) -> list[str]:
        recs = [assessment.blueprint_conclusion]
        for s in sorted(symbols, key=lambda x: -x.avg_range_pct)[:6]:
            recs.append(f"{s.symbol} ({s.mmr_tier}): {s.rationale}")
        for strat in STRATEGY_BLUEPRINT:
            recs.append(f"{strat['name']}: {strat['benefit']}")
        return recs

    def analyze(self) -> MarginStressReport:
        symbols: list[SymbolMarginProfile] = []
        for symbol, name in WATCHLIST.items():
            row = self._analyze_symbol(symbol, name)
            if row:
                symbols.append(row)
            time.sleep(self.delay_seconds)

        if not any(s.symbol == BENCHMARK for s in symbols):
            raise RuntimeError("Unable to fetch SPY data for margin stress analysis")

        assessment = self._assessment(symbols)
        expert_summary = self._expert_summary(assessment)

        margin_stress_score = round(
            sum(1 for s in symbols if s.margin_cushion_usd < 0) / len(symbols) * 10, 1
        )
        trapped_position_score = round(
            sum(1 for s in symbols if s.trapped_position_gap_flag) / len(symbols) * 10, 1
        )

        return MarginStressReport(
            symbols=symbols,
            assessment=assessment,
            margin_stress_score=margin_stress_score,
            trapped_position_score=trapped_position_score,
            expert_summary=expert_summary,
            market_signals=self._market_signals(symbols),
            recommendations=self._recommendations(symbols, assessment),
            data_source="Yahoo Finance Chart API (3mo daily OHLCV)",
        )

    def to_dict(self, report: MarginStressReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "PDT & Margin Stress Expert",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
                "temperature": self.temperature,
                "pdt_threshold_usd": PDT_THRESHOLD_USD,
                "pipeline_memory": {
                    "posture": self.pipeline_context.get("posture"),
                    "lessons": self.pipeline_memory_notes(),
                    "preferred_horizon": self.pipeline_context.get("preferred_horizon"),
                },
            },
            "pdt_mechanics": PDT_MECHANICS,
            "margin_stress_phases": MARGIN_STRESS_PHASES,
            "violation_rules": VIOLATION_RULES,
            "strategy_blueprint": STRATEGY_BLUEPRINT,
            "symbol_margin_profiles": [
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "last_close": s.last_close,
                    "atr_pct": s.atr_pct,
                    "avg_range_pct": s.avg_range_pct,
                    "max_overnight_gap_pct": s.max_overnight_gap_pct,
                    "mmr_tier": s.mmr_tier,
                    "assumed_mmr_pct": s.assumed_mmr_pct,
                    "overnight_position_value_usd": s.overnight_position_value_usd,
                    "required_overnight_mmr_usd": s.required_overnight_mmr_usd,
                    "margin_cushion_usd": s.margin_cushion_usd,
                    "squeeze_risk_flag": s.squeeze_risk_flag,
                    "trapped_position_gap_flag": s.trapped_position_gap_flag,
                    "rationale": s.rationale,
                }
                for s in report.symbols
            ],
            "margin_stress_assessment": {
                "above_threshold_scenario": a.above_threshold_scenario,
                "below_threshold_scenario": a.below_threshold_scenario,
                "trapped_position_signal": a.trapped_position_signal,
                "maintenance_squeeze_signal": a.maintenance_squeeze_signal,
                "phantom_dtmc_signal": a.phantom_dtmc_signal,
                "blueprint_conclusion": a.blueprint_conclusion,
            },
            "metrics": {
                "margin_stress_score": report.margin_stress_score,
                "trapped_position_score": report.trapped_position_score,
            },
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "pdt_strategy_blueprint.json"
            catalog.write_text(
                json.dumps(STRATEGY_BLUEPRINT, indent=2),
                encoding="utf-8",
            )
        return result


def run_margin_stress_analysis(
    output: Path | None = None,
    pipeline_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return MarginStressExpert(pipeline_context=pipeline_context).run(output=output)
