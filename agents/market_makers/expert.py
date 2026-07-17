"""
Market Maker & Specialist Microstructure Expert Agent
======================================================
Institutional-analyst view of the entities that actually price immediacy and
absorb inventory risk: quantitative electronic market makers (EMMs) on
Nasdaq/BATS/Direct Edge vs. NYSE Designated Market Makers (DMMs)/specialists.

Models three structural mechanics from classic market microstructure theory:

* Ho-Stoll inventory paradigm — quotes are a function of inventory position,
  not fundamental view. Long inventory -> quotes marked down; short
  inventory -> quotes marked up.
* Informed vs. uninformed order-flow toxicity — uninformed (retail) flow is
  uncorrelated and profitable to intermediate; informed (institutional) flow
  is directional/correlated and creates adverse-selection risk. Approximated
  here with lag-1 return autocorrelation.
* Spread compression / phantom liquidity — narrow quoted (inside touch)
  spreads at the minimum price variation mask thin real depth, so effective
  execution cost can be a large multiple of the quoted spread.

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

import requests

from agents.base import BaseExpert

CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Finance-Market-Makers/1.0 (shaggychunxx@gmail.com)"}

BENCHMARK = "SPY"
VOLATILITY_SYMBOL = "^VIX"
MIN_PRICE_VARIATION = 0.01  # $0.01 tick — the floor for a "quoted" spread

# Illustrative primary-listing venue/regime per symbol. Real market structure
# is more nuanced (many names trade across dozens of venues), but this
# approximates which structural regime (EMM-dominated vs. NYSE DMM) governs
# each name's designated/lead market maker obligations.
WATCHLIST: dict[str, str] = {
    "SPY": "NYSE Arca ETP — electronic lead market maker",
    "AAPL": "Nasdaq mega-cap — electronic market maker (EMM) regime",
    "MSFT": "Nasdaq mega-cap — electronic market maker (EMM) regime",
    "QQQ": "Nasdaq/Cboe ETP — electronic market maker (EMM) regime",
    "IWM": "NYSE Arca ETP — electronic lead market maker",
    "KO": "NYSE listing — Designated Market Maker (DMM) regime",
    "DIS": "NYSE listing — Designated Market Maker (DMM) regime",
    "GME": "NYSE listing — Designated Market Maker (DMM), retail-driven flow",
    "COIN": "Nasdaq listing — electronic market maker (EMM) regime",
    "PLTR": "NYSE listing — Designated Market Maker (DMM) regime",
}

DEEP_LIQUIDITY_USD = 200_000_000     # avg daily dollar volume threshold
MODERATE_LIQUIDITY_USD = 25_000_000

# Lag-1 autocorrelation thresholds used to classify order-flow toxicity.
TOXIC_FLOW_THRESHOLD = 0.15
UNINFORMED_FLOW_THRESHOLD = -0.15

INVENTORY_BIAS_THRESHOLD_PCT = 3.0  # 3% 5-day cumulative return that signals a lean

INVENTORY_PLAYBOOK: list[dict[str, Any]] = [
    {
        "id": "long_inventory",
        "name": "Long Inventory Bias",
        "trigger": "Market maker accumulates an excess long position after heavy public selling",
        "quote_response": "Lowers both bid and ask",
        "public_effect": "Discourages further selling, incentivizes buyers to sweep the cheap ask",
        "objective": "Bleed off inventory risk back toward a flat/neutral baseline",
    },
    {
        "id": "short_inventory",
        "name": "Short Inventory Bias",
        "trigger": "Market maker accumulates an excess short position after a wave of aggressive buying",
        "quote_response": "Raises both bid and ask",
        "public_effect": "Attracts sellers to hit the elevated bid while choking off buyers at the expensive ask",
        "objective": "Force inventory back toward a flat/neutral baseline",
    },
    {
        "id": "flat_inventory",
        "name": "Flat / Target Inventory",
        "trigger": "Inventory near the market maker's target (zero) level",
        "quote_response": "Quotes centered on fair value, spread reflects pure adverse-selection/order-processing cost",
        "public_effect": "Symmetric two-sided market, no directional skew",
        "objective": "Maintain velocity — continue capturing spread without directional risk",
    },
]

ORDER_FLOW_TAXONOMY: dict[str, dict[str, str]] = {
    "uninformed": {
        "name": "Uninformed / Retail Flow",
        "description": "Random and uncorrelated — a buy is usually followed by a sell",
        "market_maker_effect": "The profit engine: spread captured repeatedly without inventory getting run over",
    },
    "informed": {
        "name": "Informed / Institutional Flow",
        "description": "Directional and correlated — driven by fundamental data or algorithmic conviction",
        "market_maker_effect": (
            "The toxic threat: adverse selection — spread captured on the first few fills, then a "
            "large, toxic position accumulates as price moves against it"
        ),
    },
}

STRUCTURAL_MATRIX: list[dict[str, str]] = [
    {
        "vector": "Market Concentration",
        "emm": "Dozens competing simultaneously per ticker",
        "dmm": "Exactly one assigned exclusive firm per ticker",
    },
    {
        "vector": "Regulatory Mandate",
        "emm": "Low; can widen quotes or exit during extreme stress",
        "dmm": 'High; legal "affirmative obligations" to stabilize',
    },
    {
        "vector": "Auction Management",
        "emm": "None; completely passive during market crosses",
        "dmm": "Total; physically coordinates opening/closing auctions",
    },
    {
        "vector": "Order Routing Edge",
        "emm": "Relies on PFOF and dark pool internalization",
        "dmm": "Relies on exchange-granted order book parity",
    },
    {
        "vector": "Risk Architecture",
        "emm": "Pure algorithmic delta-hedging via options/futures",
        "dmm": "Structural capital deployment and physical floor oversight",
    },
]


@dataclass
class SymbolMicrostructure:
    symbol: str
    regime: str
    last_close: float
    avg_dollar_volume: float
    liquidity_tier: str
    quoted_spread_bps: float
    effective_spread_bps: float
    phantom_liquidity_ratio: float
    flow_autocorrelation: float
    flow_classification: str
    five_day_return_pct: float
    inventory_bias: str
    inventory_rationale: str


@dataclass
class MarketMakerAssessment:
    volatility_regime: str
    toxicity_signal: str
    phantom_liquidity_signal: str
    inventory_signal: str
    fragility_signal: str
    structural_conclusion: str


@dataclass
class MarketMakerReport:
    vix_level: float | None
    symbols: list[SymbolMicrostructure]
    assessment: MarketMakerAssessment
    toxicity_score: float
    phantom_liquidity_score: float
    fragility_score: float
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MarketMakerExpert(BaseExpert):
    """Expert analyst — market maker/specialist inventory, toxicity, and structure."""

    def __init__(self, delay_seconds: float = 0.35) -> None:
        super().__init__()
        self.delay_seconds = delay_seconds

    def _fetch_ohlcv(self, symbol: str) -> dict[str, list[float]]:
        try:
            resp = requests.get(
                CHART_API.format(symbol=symbol),
                params={"interval": "1d", "range": "3mo"},
                headers=HEADERS,
                timeout=25,
            )
            if resp.status_code == 429:
                time.sleep(3)
                resp = requests.get(
                    CHART_API.format(symbol=symbol),
                    params={"interval": "1d", "range": "3mo"},
                    headers=HEADERS,
                    timeout=25,
                )
            resp.raise_for_status()
            quote = resp.json()["chart"]["result"][0]["indicators"]["quote"][0]
            rows = zip(
                quote.get("open", []),
                quote.get("high", []),
                quote.get("low", []),
                quote.get("close", []),
                quote.get("volume", []),
            )
            opens, highs, lows, closes, volumes = [], [], [], [], []
            for o, h, l, c, v in rows:
                if o is None or h is None or l is None or c is None:
                    continue
                opens.append(float(o))
                highs.append(float(h))
                lows.append(float(l))
                closes.append(float(c))
                volumes.append(float(v) if v is not None else 0.0)
            return {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes}
        except Exception:
            return {"open": [], "high": [], "low": [], "close": [], "volume": []}

    def _fetch_last_close(self, symbol: str) -> float | None:
        data = self._fetch_ohlcv(symbol)
        closes = data["close"]
        return closes[-1] if closes else None

    @staticmethod
    def _liquidity_tier(avg_dollar_volume: float) -> str:
        if avg_dollar_volume >= DEEP_LIQUIDITY_USD:
            return "Deep"
        if avg_dollar_volume >= MODERATE_LIQUIDITY_USD:
            return "Moderate"
        return "Thin"

    @staticmethod
    def _daily_returns(closes: list[float]) -> list[float]:
        return [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes))
            if closes[i - 1]
        ]

    @staticmethod
    def _lag1_autocorrelation(returns: list[float]) -> float:
        if len(returns) < 5:
            return 0.0
        mean = statistics.mean(returns)
        var = sum((r - mean) ** 2 for r in returns)
        if var == 0:
            return 0.0
        cov = sum((returns[i] - mean) * (returns[i - 1] - mean) for i in range(1, len(returns)))
        return cov / var

    def _classify_flow(self, autocorr: float) -> str:
        if autocorr >= TOXIC_FLOW_THRESHOLD:
            return "Informed/toxic flow risk (trending, directionally correlated)"
        if autocorr <= UNINFORMED_FLOW_THRESHOLD:
            return "Uninformed/retail-dominated flow (mean-reverting, profit engine)"
        return "Mixed flow (no strong directional signature)"

    def _analyze_symbol(self, symbol: str, regime: str) -> SymbolMicrostructure | None:
        data = self._fetch_ohlcv(symbol)
        closes = data["close"]
        if len(closes) < 15:
            return None

        last_close = closes[-1]
        window = min(len(closes), 20)
        recent_closes = closes[-window:]
        recent_highs = data["high"][-window:]
        recent_lows = data["low"][-window:]
        recent_volumes = data["volume"][-window:]

        avg_dollar_volume = statistics.mean(
            [c * v for c, v in zip(recent_closes, recent_volumes)]
        )
        liquidity_tier = self._liquidity_tier(avg_dollar_volume)

        # Quoted (displayed inside-touch) spread: modern mega-caps trade at
        # the $0.01 minimum price variation, so the quoted spread in bps
        # shrinks purely as price rises — this is the "spread compression"
        # phenomenon, independent of real depth.
        quoted_spread_bps = round((MIN_PRICE_VARIATION / last_close) * 10_000, 2) if last_close else 0.0

        # Effective spread: proxy for the real cost of walking the book,
        # scaled up for thinner liquidity tiers where displayed depth is
        # shallow relative to typical trade size ("phantom liquidity").
        avg_range_pct = statistics.mean(
            [(h - l) / c * 100 for h, l, c in zip(recent_highs, recent_lows, recent_closes) if c]
        )
        tier_multiplier = {"Deep": 1.5, "Moderate": 3.0, "Thin": 6.0}[liquidity_tier]
        effective_spread_bps = round(avg_range_pct / 2 * tier_multiplier * 100, 2)

        phantom_liquidity_ratio = (
            round(effective_spread_bps / quoted_spread_bps, 1) if quoted_spread_bps else 0.0
        )

        returns = self._daily_returns(recent_closes)
        autocorr = round(self._lag1_autocorrelation(returns), 3)
        flow_classification = self._classify_flow(autocorr)

        five_day_return_pct = (
            round((recent_closes[-1] - recent_closes[-6]) / recent_closes[-6] * 100, 2)
            if len(recent_closes) >= 6
            else 0.0
        )

        if five_day_return_pct <= -INVENTORY_BIAS_THRESHOLD_PCT:
            inventory_bias = "Long inventory bias"
            inventory_rationale = (
                f"Heavy public selling ({five_day_return_pct:+.2f}% over 5 days) likely leaves "
                "market makers net long — expect the whole quote window marked down to bleed "
                "off inventory."
            )
        elif five_day_return_pct >= INVENTORY_BIAS_THRESHOLD_PCT:
            inventory_bias = "Short inventory bias"
            inventory_rationale = (
                f"Heavy public buying ({five_day_return_pct:+.2f}% over 5 days) likely leaves "
                "market makers net short — expect the whole quote window marked up to force "
                "inventory back toward flat."
            )
        else:
            inventory_bias = "Flat / near-target inventory"
            inventory_rationale = (
                f"Modest 5-day drift ({five_day_return_pct:+.2f}%) suggests inventory near target — "
                "quotes should be centered on fair value."
            )

        return SymbolMicrostructure(
            symbol=symbol,
            regime=regime,
            last_close=round(last_close, 2),
            avg_dollar_volume=round(avg_dollar_volume, 0),
            liquidity_tier=liquidity_tier,
            quoted_spread_bps=quoted_spread_bps,
            effective_spread_bps=effective_spread_bps,
            phantom_liquidity_ratio=phantom_liquidity_ratio,
            flow_autocorrelation=autocorr,
            flow_classification=flow_classification,
            five_day_return_pct=five_day_return_pct,
            inventory_bias=inventory_bias,
            inventory_rationale=inventory_rationale,
        )

    @staticmethod
    def _volatility_regime(vix: float | None) -> str:
        if vix is None:
            return "Unknown (VIX unavailable)"
        if vix >= 25:
            return "High volatility — elevated adverse-selection and liquidity-vacuum risk"
        if vix >= 18:
            return "Moderate volatility — normal market-making risk"
        return "Low volatility — calm, orderly two-sided markets"

    def _assessment(
        self, symbols: list[SymbolMicrostructure], vix: float | None
    ) -> MarketMakerAssessment:
        regime = self._volatility_regime(vix)
        toxic = [s for s in symbols if "toxic" in s.flow_classification]
        biased = [s for s in symbols if s.inventory_bias != "Flat / near-target inventory"]
        avg_phantom_ratio = statistics.mean([s.phantom_liquidity_ratio for s in symbols]) if symbols else 0.0

        toxicity_signal = (
            f"{len(toxic)}/{len(symbols)} symbols show trending, directionally correlated order "
            "flow — a market maker intermediating this flow risks holding a toxic, adversely "
            "selected position."
        )
        phantom_liquidity_signal = (
            f"Effective spreads average {avg_phantom_ratio:.1f}x the quoted (inside-touch) spread — "
            "the narrow displayed spread is largely phantom liquidity; real depth behind the touch "
            "is much thinner than it appears."
        )
        inventory_signal = (
            f"{len(biased)}/{len(symbols)} symbols show a meaningful 5-day directional skew — "
            "consistent with market makers actively marking quotes to bleed off a long or short "
            "inventory position rather than quoting fair value."
        )
        toxic_count = len(toxic)
        if vix is not None and vix >= 25 and toxic_count >= len(symbols) / 3:
            fragility_signal = (
                "Correlated toxic flow plus elevated VIX is the classic precondition for an "
                "adverse-selection cascade — competing market makers pulling/repricing bids "
                "simultaneously can turn an orderly selloff into a liquidity vacuum."
            )
        elif vix is not None and vix >= 25:
            fragility_signal = (
                "Elevated volatility alone; toxic-flow concentration is not broad enough yet to "
                "signal an imminent liquidity vacuum, but risk algorithms are likely widening quotes."
            )
        else:
            fragility_signal = (
                "Calm regime — low probability of a synchronized quote-pulling / flash-crash event."
            )

        if vix is not None and vix >= 25:
            conclusion = (
                "High-stress regime: EMMs are structurally likely to widen spreads or pull quotes "
                "(weak affirmative obligation); DMM-covered names retain an obligated capital "
                "buffer at the open/close that EMM-only names lack."
            )
        elif toxic_count >= len(symbols) / 2:
            conclusion = (
                "Order flow is broadly directional/correlated across the watchlist — adverse "
                "selection risk is elevated even without a volatility spike."
            )
        else:
            conclusion = (
                "Uninformed, mean-reverting flow dominates — market makers should be able to "
                "intermediate the tape profitably without structural inventory stress."
            )

        return MarketMakerAssessment(
            volatility_regime=regime,
            toxicity_signal=toxicity_signal,
            phantom_liquidity_signal=phantom_liquidity_signal,
            inventory_signal=inventory_signal,
            fragility_signal=fragility_signal,
            structural_conclusion=conclusion,
        )

    def _expert_summary(self, assessment: MarketMakerAssessment) -> str:
        return (
            f"Market maker/specialist scan: {assessment.volatility_regime}. "
            f"{assessment.toxicity_signal} {assessment.phantom_liquidity_signal} "
            f"{assessment.inventory_signal} {assessment.fragility_signal} "
            f"{assessment.structural_conclusion}"
        )

    def _market_signals(self, symbols: list[SymbolMicrostructure]) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        toxic = [s.symbol for s in symbols if "toxic" in s.flow_classification]
        if toxic:
            signals.append(
                {
                    "sector": "Microstructure",
                    "bias": "adverse-selection-risk",
                    "tickers": toxic,
                    "reason": "Directionally correlated order flow — market makers likely holding toxic inventory.",
                }
            )
        phantom = [s.symbol for s in symbols if s.phantom_liquidity_ratio >= 3.0]
        if phantom:
            signals.append(
                {
                    "sector": "Microstructure",
                    "bias": "phantom-liquidity",
                    "tickers": phantom,
                    "reason": "Effective spread far exceeds the quoted spread — displayed depth is thin.",
                }
            )
        long_bias = [s.symbol for s in symbols if s.inventory_bias == "Long inventory bias"]
        if long_bias:
            signals.append(
                {
                    "sector": "Microstructure",
                    "bias": "mm-long-inventory",
                    "tickers": long_bias,
                    "reason": "Market makers likely net long and marking quotes down to bleed inventory.",
                }
            )
        short_bias = [s.symbol for s in symbols if s.inventory_bias == "Short inventory bias"]
        if short_bias:
            signals.append(
                {
                    "sector": "Microstructure",
                    "bias": "mm-short-inventory",
                    "tickers": short_bias,
                    "reason": "Market makers likely net short and marking quotes up to force inventory back to flat.",
                }
            )
        dmm_names = [s.symbol for s in symbols if "DMM" in s.regime]
        if dmm_names:
            signals.append(
                {
                    "sector": "Microstructure",
                    "bias": "dmm-auction-obligation",
                    "tickers": dmm_names,
                    "reason": "NYSE DMM-covered names carry affirmative capital obligations at the open/close cross.",
                }
            )
        return signals

    def _recommendations(
        self, symbols: list[SymbolMicrostructure], assessment: MarketMakerAssessment
    ) -> list[str]:
        recs = [assessment.structural_conclusion]
        for s in sorted(symbols, key=lambda x: -x.phantom_liquidity_ratio)[:6]:
            recs.append(
                f"{s.symbol} [{s.liquidity_tier}, {s.regime.split(' — ')[-1]}]: "
                f"{s.inventory_bias} — {s.flow_classification} "
                f"(effective/quoted spread {s.phantom_liquidity_ratio}x)."
            )
        return recs

    def analyze(self) -> MarketMakerReport:
        symbols: list[SymbolMicrostructure] = []
        for symbol, regime in WATCHLIST.items():
            row = self._analyze_symbol(symbol, regime)
            if row:
                symbols.append(row)
            time.sleep(self.delay_seconds)

        if not any(s.symbol == BENCHMARK for s in symbols):
            raise RuntimeError("Unable to fetch SPY data for market maker analysis")

        vix = self._fetch_last_close(VOLATILITY_SYMBOL)

        assessment = self._assessment(symbols, vix)
        expert_summary = self._expert_summary(assessment)

        toxic_count = sum(1 for s in symbols if "toxic" in s.flow_classification)
        toxicity_score = round(toxic_count / len(symbols) * 10, 1)
        phantom_liquidity_score = round(
            min(statistics.mean([s.phantom_liquidity_ratio for s in symbols]), 10), 1
        )
        vix_component = min((vix or 0) / 40 * 10, 10) if vix is not None else 0.0
        fragility_score = round(min((toxicity_score + vix_component) / 2, 10), 1)

        return MarketMakerReport(
            vix_level=round(vix, 2) if vix is not None else None,
            symbols=symbols,
            assessment=assessment,
            toxicity_score=toxicity_score,
            phantom_liquidity_score=phantom_liquidity_score,
            fragility_score=fragility_score,
            expert_summary=expert_summary,
            market_signals=self._market_signals(symbols),
            recommendations=self._recommendations(symbols, assessment),
            data_source="Yahoo Finance Chart API (3mo daily OHLCV)",
        )

    def to_dict(self, report: MarketMakerReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Market Maker & Specialist Microstructure Expert",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
                "temperature": self.temperature,
                "vix_level": report.vix_level,
            },
            "inventory_playbook": INVENTORY_PLAYBOOK,
            "order_flow_taxonomy": ORDER_FLOW_TAXONOMY,
            "structural_matrix": STRUCTURAL_MATRIX,
            "symbol_microstructure": [
                {
                    "symbol": s.symbol,
                    "regime": s.regime,
                    "last_close": s.last_close,
                    "avg_dollar_volume": s.avg_dollar_volume,
                    "liquidity_tier": s.liquidity_tier,
                    "quoted_spread_bps": s.quoted_spread_bps,
                    "effective_spread_bps": s.effective_spread_bps,
                    "phantom_liquidity_ratio": s.phantom_liquidity_ratio,
                    "flow_autocorrelation": s.flow_autocorrelation,
                    "flow_classification": s.flow_classification,
                    "five_day_return_pct": s.five_day_return_pct,
                    "inventory_bias": s.inventory_bias,
                    "inventory_rationale": s.inventory_rationale,
                }
                for s in report.symbols
            ],
            "structural_assessment": {
                "volatility_regime": a.volatility_regime,
                "toxicity_signal": a.toxicity_signal,
                "phantom_liquidity_signal": a.phantom_liquidity_signal,
                "inventory_signal": a.inventory_signal,
                "fragility_signal": a.fragility_signal,
                "structural_conclusion": a.structural_conclusion,
            },
            "metrics": {
                "toxicity_score": report.toxicity_score,
                "phantom_liquidity_score": report.phantom_liquidity_score,
                "fragility_score": report.fragility_score,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "market_maker_structural_matrix.json"
            catalog.write_text(
                json.dumps(STRUCTURAL_MATRIX, indent=2),
                encoding="utf-8",
            )
        return result


def run_market_maker_analysis(output: Path | None = None) -> dict[str, Any]:
    return MarketMakerExpert().run(output=output)
