"""
Smart Money Options Flow Expert Agent
=====================================
Institutional order-flow forensics: distinguishes sweeps from blocks, scores
the volume-vs-open-interest "significance ratio" that flags brand-new
directional bets, and screens the nearest-expiration option chain for
"golden sweep" style anomalies while surfacing the hedging/spread caveats
that make raw call/put volume an unreliable directional signal on its own.

Data: Yahoo Finance nearest-expiration option chain (calls + puts).

Caveat: Yahoo's public option chain is an end-of-day snapshot of aggregate
volume/open interest per contract, not a trade-by-trade tape. This agent
uses it as a *proxy* for sweep/block detection (at-the-ask pricing + high
volume vs. open interest on short-dated, out-of-the-money strikes) — it
cannot see venue-by-venue execution splits the way a real tape-scraping
feed (Unusual Whales, FlowAlgo, Cboe LiveVol) can.
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
    "SPY": "S&P 500 (deep options liquidity)",
    "AAPL": "Mega-cap tech (deep options liquidity)",
    "MSFT": "Mega-cap tech (deep options liquidity)",
    "QQQ": "Nasdaq 100 (deep options liquidity)",
    "IWM": "Russell 2000 (moderate options liquidity)",
    "GME": "Retail-driven small/mid cap (volatile)",
    "COIN": "Crypto-adjacent equity (volatile)",
    "PLTR": "High-beta growth name (moderate options liquidity)",
}

# Forensic thresholds for the "golden sweep" style anomaly screen.
GOLDEN_SWEEP_MIN_PREMIUM_USD = 1_000_000.0
GOLDEN_SWEEP_MIN_OTM_PCT = 15.0
SHORT_DATED_MAX_DAYS = 14.0
AT_ASK_PROXY_RATIO = 0.98  # lastPrice >= 98% of ask counts as "paid at/near the ask"

ORDER_FLOW_TYPES: list[dict[str, Any]] = [
    {
        "id": "retail_market_order",
        "name": "Retail Market Order",
        "execution_style": "Single exchange",
        "venue_behavior": "Routed to one venue/market maker",
        "urgency": "Low-to-moderate",
        "price_signal": "High slippage risk, slow relative fill",
        "interpretation": "Baseline noise — not evidence of institutional conviction.",
    },
    {
        "id": "market_sweep",
        "name": "Institutional Sweep",
        "execution_style": "Split across multiple exchanges (NYSEMKT, NASDAQ, Cboe, PHLX, ...)",
        "venue_behavior": "Simultaneously sweeps all available liquidity",
        "urgency": "Extreme — prioritizes speed over price",
        "price_signal": "Aggressive fills at/above ask (buys) or at/below bid (sells)",
        "interpretation": (
            "The buyer/seller wants immediate execution before price moves — the "
            "strongest single tell of urgency in the tape."
        ),
    },
    {
        "id": "block_trade",
        "name": "Block Trade",
        "execution_style": "Privately negotiated, reported to the tape after execution",
        "venue_behavior": "Executes outside the public auction market at one agreed price",
        "urgency": "Lower near-term panic than sweeps despite large size",
        "price_signal": "Single negotiated price, not a multi-venue chase",
        "interpretation": (
            "Massive size alone is not urgency — a block is filled calmly at one "
            "price, unlike a sweep that pays up across venues to get filled now."
        ),
    },
]

HEDGING_CAVEATS: list[dict[str, Any]] = [
    {
        "id": "delta_hedge",
        "name": "The Delta Hedge",
        "mechanism": (
            "A market maker who sells calls immediately becomes short delta and must "
            "buy the underlying to stay neutral."
        ),
        "trap": (
            "That stock buying can trigger a gamma squeeze even though the options "
            "trade itself was purely operational hedging, not a speculative bet."
        ),
    },
    {
        "id": "spread_configuration",
        "name": "Spread Configurations",
        "mechanism": (
            "A large call buy can be the lower leg of a Bear Call Spread or the long "
            "leg of a calendar spread harvesting time decay."
        ),
        "trap": "A single leg printed on the tape can look bullish while the full structure is bearish or neutral.",
    },
    {
        "id": "protective_collar",
        "name": "The Protective Collar",
        "mechanism": (
            "Funds holding large long equity positions buy OTM puts as insurance "
            "against an existing position."
        ),
        "trap": "A spike in put flow often means portfolio protection, not a bet on the company's collapse.",
    },
]

FORENSIC_FILTERS: list[dict[str, Any]] = [
    {
        "id": "golden_sweep",
        "name": "Golden Sweeps",
        "criteria": (
            f"Unusually large sweep paid at the ask, executed far out-of-the-money, "
            f"with premium exceeding ${GOLDEN_SWEEP_MIN_PREMIUM_USD:,.0f}."
        ),
        "signal": "High-conviction institutional bet.",
    },
    {
        "id": "short_dated_otm_concentration",
        "name": "Short-Dated OTM Concentration",
        "criteria": (
            f"Massive volume in contracts expiring in under {SHORT_DATED_MAX_DAYS:.0f} days, "
            f"positioned {GOLDEN_SWEEP_MIN_OTM_PCT:.0f}%+ outside spot."
        ),
        "signal": "Strongly implies knowledge of an imminent corporate/regulatory catalyst.",
    },
    {
        "id": "iv_skew_anomaly",
        "name": "Implied Volatility Skew Anomalies",
        "criteria": "IV of one strike rising materially faster than adjacent strikes under heavy buying.",
        "signal": "Buyers are price-insensitive and aggressively bidding up that exact contract.",
    },
]

FLOW_TOOLS: list[dict[str, Any]] = [
    {
        "id": "unusual_whales",
        "name": "Unusual Whales",
        "type": "Retail-accessible tape scraper",
        "description": "Tracks dark pool activity, large blocks, and sudden historical spikes in specific options chains.",
    },
    {
        "id": "flowalgo",
        "name": "FlowAlgo",
        "type": "Premium real-time algorithmic feed",
        "description": "Strips out market noise to isolate institutional sweeps and blocks as they hit the tape.",
    },
    {
        "id": "cboe_livevol",
        "name": "Cboe LiveVol",
        "type": "Exchange-level data feed",
        "description": "Direct access to granular historical volatility statistics and real-time order routing diagnostics.",
    },
]


@dataclass
class OptionsFlowSignal:
    symbol: str
    name: str
    spot_price: float
    expiration_days: float | None
    call_volume: int
    call_open_interest: int
    put_volume: int
    put_open_interest: int
    put_call_volume_ratio: float | None
    significance_ratio: float | None
    unusual_contract_count: int
    top_contract: dict[str, Any] | None
    golden_sweep_candidate: bool
    bias: str
    note: str


@dataclass
class OptionsFlowAssessment:
    market_bias_signal: str
    volume_oi_signal: str
    forensic_signal: str
    hedging_caveat_signal: str
    tool_recommendation: str


@dataclass
class OptionsFlowReport:
    symbols: list[OptionsFlowSignal]
    assessment: OptionsFlowAssessment
    flow_conviction_score: float
    hedging_ambiguity_score: float
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class OptionsFlowExpert(BaseExpert):
    """Expert analyst — sweeps vs. blocks, volume/OI forensics, and hedging caveats."""

    def __init__(
        self,
        delay_seconds: float = 0.35,
        *,
        pipeline_context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="options-flow")
        self.delay_seconds = delay_seconds

    @staticmethod
    def _otm_pct(strike: float, spot: float, is_call: bool) -> float:
        if spot <= 0:
            return 0.0
        if is_call:
            return max(0.0, (strike - spot) / spot * 100.0)
        return max(0.0, (spot - strike) / spot * 100.0)

    @staticmethod
    def _at_ask(leg: dict[str, Any]) -> bool:
        ask = leg.get("ask") or 0.0
        last = leg.get("last_price") or 0.0
        if ask <= 0:
            return False
        return last >= ask * AT_ASK_PROXY_RATIO

    def _scan_legs(
        self, legs: list[dict[str, Any]], spot: float, is_call: bool, days_to_expiration: float | None
    ) -> tuple[int, int, list[dict[str, Any]]]:
        total_volume = 0
        total_oi = 0
        unusual: list[dict[str, Any]] = []
        for leg in legs:
            volume = int(leg.get("volume") or 0)
            oi = int(leg.get("open_interest") or 0)
            total_volume += volume
            total_oi += oi
            if volume <= 0 or volume <= oi:
                continue
            otm_pct = self._otm_pct(leg["strike"], spot, is_call)
            premium_notional = volume * leg.get("last_price", 0.0) * 100.0
            at_ask = self._at_ask(leg)
            golden = (
                premium_notional >= GOLDEN_SWEEP_MIN_PREMIUM_USD
                and otm_pct >= GOLDEN_SWEEP_MIN_OTM_PCT
                and days_to_expiration is not None
                and days_to_expiration <= SHORT_DATED_MAX_DAYS
                and at_ask
            )
            unusual.append(
                {
                    "type": "call" if is_call else "put",
                    "strike": leg["strike"],
                    "volume": volume,
                    "open_interest": oi,
                    "significance_ratio": round(volume / oi, 2) if oi else None,
                    "otm_pct": round(otm_pct, 2),
                    "premium_notional": round(premium_notional, 0),
                    "at_ask_or_bid": at_ask,
                    "golden_sweep_candidate": golden,
                }
            )
        return total_volume, total_oi, unusual

    def _analyze_symbol(self, symbol: str, name: str) -> OptionsFlowSignal | None:
        chain = self.fetch_yahoo_option_chain(symbol)
        if not chain or not (chain.get("calls") or chain.get("puts")):
            return None

        spot = chain["spot_price"]
        dte = chain.get("days_to_expiration")

        call_volume, call_oi, unusual_calls = self._scan_legs(chain["calls"], spot, True, dte)
        put_volume, put_oi, unusual_puts = self._scan_legs(chain["puts"], spot, False, dte)

        unusual = unusual_calls + unusual_puts
        unusual.sort(key=lambda u: -u["premium_notional"])
        top_contract = unusual[0] if unusual else None
        golden_sweep_candidate = any(u["golden_sweep_candidate"] for u in unusual)

        total_volume = call_volume + put_volume
        total_oi = call_oi + put_oi
        significance_ratio = round(total_volume / total_oi, 2) if total_oi else None
        put_call_ratio = round(put_volume / call_volume, 2) if call_volume else None

        if top_contract is None:
            bias = "No unusual activity"
            note = (
                "Volume did not exceed open interest on any contract — no evidence of "
                "fresh directional positioning today."
            )
        else:
            call_premium = sum(u["premium_notional"] for u in unusual_calls)
            put_premium = sum(u["premium_notional"] for u in unusual_puts)
            if call_premium > put_premium * 1.5:
                bias = "Bullish flow (unusual call-side premium dominant)"
            elif put_premium > call_premium * 1.5:
                bias = "Bearish flow (unusual put-side premium dominant)"
            else:
                bias = "Mixed/hedged flow (call and put premium comparable)"
            note = (
                f"Top unusual contract: {top_contract['type']} ${top_contract['strike']:.2f} "
                f"({top_contract['otm_pct']:.1f}% OTM), volume {top_contract['volume']} vs "
                f"OI {top_contract['open_interest']} — could still be a delta-hedge, spread "
                "leg, or protective collar rather than an outright directional bet; volume "
                "above OI alone does not distinguish new risk from unwinds without T+1 OI "
                "confirmation."
            )

        return OptionsFlowSignal(
            symbol=symbol,
            name=name,
            spot_price=round(spot, 2),
            expiration_days=dte,
            call_volume=call_volume,
            call_open_interest=call_oi,
            put_volume=put_volume,
            put_open_interest=put_oi,
            put_call_volume_ratio=put_call_ratio,
            significance_ratio=significance_ratio,
            unusual_contract_count=len(unusual),
            top_contract=top_contract,
            golden_sweep_candidate=golden_sweep_candidate,
            bias=bias,
            note=note,
        )

    def _assessment(self, symbols: list[OptionsFlowSignal]) -> OptionsFlowAssessment:
        golden_count = sum(1 for s in symbols if s.golden_sweep_candidate)
        unusual_total = sum(s.unusual_contract_count for s in symbols)
        bullish = sum(1 for s in symbols if s.bias.startswith("Bullish"))
        bearish = sum(1 for s in symbols if s.bias.startswith("Bearish"))

        market_bias_signal = (
            f"{bullish}/{len(symbols)} symbols show bullish-dominant unusual flow, "
            f"{bearish}/{len(symbols)} show bearish-dominant unusual flow."
        )
        volume_oi_signal = (
            f"{unusual_total} contracts across the watchlist have volume exceeding open "
            "interest today — new contracts being minted, not confirmed until tomorrow's "
            "T+1 OI update."
        )
        forensic_signal = (
            f"{golden_count}/{len(symbols)} symbols carry a golden-sweep candidate "
            f"(at-ask, ${GOLDEN_SWEEP_MIN_PREMIUM_USD/1e6:.1f}M+ premium, "
            f"{GOLDEN_SWEEP_MIN_OTM_PCT:.0f}%+ OTM, <{SHORT_DATED_MAX_DAYS:.0f}-day expiry)."
        )
        hedging_caveat_signal = (
            "Any single directional read must be cross-checked against delta-hedging, "
            "spread configurations, and protective collars before treating it as a "
            "speculative bet."
        )
        if golden_count:
            tool_recommendation = (
                "Golden-sweep candidates detected — corroborate with a live tape-scraping "
                "feed (Unusual Whales, FlowAlgo, Cboe LiveVol) before acting; this snapshot "
                "cannot see venue-by-venue execution splits."
            )
        else:
            tool_recommendation = (
                "No golden-sweep candidates today — treat unusual volume as noise-level "
                "until a live tape feed confirms at-ask/at-bid sweep behavior."
            )
        return OptionsFlowAssessment(
            market_bias_signal=market_bias_signal,
            volume_oi_signal=volume_oi_signal,
            forensic_signal=forensic_signal,
            hedging_caveat_signal=hedging_caveat_signal,
            tool_recommendation=tool_recommendation,
        )

    def _expert_summary(self, assessment: OptionsFlowAssessment) -> str:
        return (
            f"Smart-money options flow scan: {assessment.market_bias_signal} "
            f"{assessment.volume_oi_signal} {assessment.forensic_signal} "
            f"{assessment.hedging_caveat_signal} {assessment.tool_recommendation}"
        )

    def _market_signals(self, symbols: list[OptionsFlowSignal]) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        def _keep(symbol: str) -> bool:
            return not self.pipeline_should_skip_symbol(symbol)

        golden = [s.symbol for s in symbols if s.golden_sweep_candidate and _keep(s.symbol)]
        if golden:
            signals.append(
                {
                    "sector": "Options Flow",
                    "bias": "golden-sweep",
                    "tickers": golden,
                    "reason": "At-ask, far-OTM, short-dated flow with $1M+ premium — high-conviction institutional bet.",
                }
            )
        bullish = [s.symbol for s in symbols if s.bias.startswith("Bullish") and _keep(s.symbol)]
        if bullish:
            signals.append(
                {
                    "sector": "Options Flow",
                    "bias": "bullish",
                    "tickers": bullish,
                    "reason": "Unusual call-side volume exceeding open interest, dominant over put-side premium.",
                }
            )
        bearish = [s.symbol for s in symbols if s.bias.startswith("Bearish") and _keep(s.symbol)]
        if bearish:
            signals.append(
                {
                    "sector": "Options Flow",
                    "bias": "bearish",
                    "tickers": bearish,
                    "reason": "Unusual put-side volume exceeding open interest, dominant over call-side premium.",
                }
            )
        return signals

    def _recommendations(
        self, symbols: list[OptionsFlowSignal], assessment: OptionsFlowAssessment
    ) -> list[str]:
        recs = [assessment.tool_recommendation]
        for s in sorted(
            symbols, key=lambda x: -(x.top_contract["premium_notional"] if x.top_contract else 0.0)
        )[:6]:
            if s.top_contract is None:
                continue
            recs.append(f"{s.symbol}: {s.bias} — {s.note}")
        return recs

    def analyze(self) -> OptionsFlowReport:
        symbols: list[OptionsFlowSignal] = []
        for symbol, name in WATCHLIST.items():
            row = self._analyze_symbol(symbol, name)
            if row:
                symbols.append(row)
            time.sleep(self.delay_seconds)

        if not any(s.symbol == BENCHMARK for s in symbols):
            raise RuntimeError("Unable to fetch SPY data for options flow analysis")

        assessment = self._assessment(symbols)
        expert_summary = self._expert_summary(assessment)

        golden_count = sum(1 for s in symbols if s.golden_sweep_candidate)
        flow_conviction_score = round(min(10.0, golden_count / len(symbols) * 10 + 2), 1)
        ambiguous = sum(1 for s in symbols if s.top_contract is None)
        hedging_ambiguity_score = round(ambiguous / len(symbols) * 10, 1)

        return OptionsFlowReport(
            symbols=symbols,
            assessment=assessment,
            flow_conviction_score=flow_conviction_score,
            hedging_ambiguity_score=hedging_ambiguity_score,
            expert_summary=expert_summary,
            market_signals=self._market_signals(symbols),
            recommendations=self._recommendations(symbols, assessment),
            data_source="Yahoo Finance nearest-expiration option chain (calls + puts)",
        )

    def to_dict(self, report: OptionsFlowReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Smart Money Options Flow Expert",
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
            "order_flow_types": ORDER_FLOW_TYPES,
            "hedging_caveats": HEDGING_CAVEATS,
            "forensic_filters": FORENSIC_FILTERS,
            "flow_tools": FLOW_TOOLS,
            "symbol_flow": [
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "spot_price": s.spot_price,
                    "expiration_days": s.expiration_days,
                    "call_volume": s.call_volume,
                    "call_open_interest": s.call_open_interest,
                    "put_volume": s.put_volume,
                    "put_open_interest": s.put_open_interest,
                    "put_call_volume_ratio": s.put_call_volume_ratio,
                    "significance_ratio": s.significance_ratio,
                    "unusual_contract_count": s.unusual_contract_count,
                    "top_contract": s.top_contract,
                    "golden_sweep_candidate": s.golden_sweep_candidate,
                    "bias": s.bias,
                    "note": s.note,
                }
                for s in report.symbols
            ],
            "flow_assessment": {
                "market_bias_signal": a.market_bias_signal,
                "volume_oi_signal": a.volume_oi_signal,
                "forensic_signal": a.forensic_signal,
                "hedging_caveat_signal": a.hedging_caveat_signal,
                "tool_recommendation": a.tool_recommendation,
            },
            "metrics": {
                "flow_conviction_score": report.flow_conviction_score,
                "hedging_ambiguity_score": report.hedging_ambiguity_score,
            },
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "smart_money_playbook.json"
            catalog.write_text(
                json.dumps(
                    {
                        "order_flow_types": ORDER_FLOW_TYPES,
                        "hedging_caveats": HEDGING_CAVEATS,
                        "forensic_filters": FORENSIC_FILTERS,
                        "flow_tools": FLOW_TOOLS,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        return result


def run_options_flow_analysis(
    output: Path | None = None,
    pipeline_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return OptionsFlowExpert(pipeline_context=pipeline_context).run(output=output)
