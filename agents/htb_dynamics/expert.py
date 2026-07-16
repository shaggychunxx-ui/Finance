"""
Hard-to-Borrow (HTB) Microstructure Expert Agent
=================================================
Models the institutional routing and pricing mechanics that kick in once a
stock's short interest spikes or its float is tightly held: the Reg SHO
locate requirement, the daily borrow-cost matrix, and the rebate-rate
dynamics that can turn negative for the most squeezed names.

Data: Yahoo Finance chart API (3-month daily OHLCV). Real-time short
interest / borrow-rate feeds (e.g. IHS Markit, S3 Partners) are not
reachable from this sandbox, so per-symbol borrow-cost figures are
transparent, disclosed proxies derived from realized volatility and
average dollar volume — not live locate-desk quotes.
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
    "AAPL": "Mega-cap tech (easy-to-borrow)",
    "MSFT": "Mega-cap tech (easy-to-borrow)",
    "QQQ": "Nasdaq 100 (easy-to-borrow)",
    "IWM": "Russell 2000 (moderate borrow)",
    "GME": "Retail-driven small/mid cap (historically HTB)",
    "COIN": "Crypto-adjacent equity (volatile borrow)",
    "PLTR": "High-beta growth name (moderate-thin borrow)",
}

LOCATE_REQUIREMENT: dict[str, str] = {
    "rule": "SEC Regulation SHO Rule 203(b)(1)",
    "reference_url": "https://www.sec.gov/investor/pubs/regsho.htm",
    "summary": (
        "Broker-dealers cannot accept a short sale order unless they have borrowed "
        "the security, entered into an arrangement to borrow it, or have reasonable "
        "grounds to believe it can be borrowed for delivery on settlement date."
    ),
}

# Standard borrow fees are sub-1% APR; HTB names can spike from ~20% to 300%+ APR.
BORROW_RATE_TIERS: list[dict[str, Any]] = [
    {
        "tier": "General Collateral (GC)",
        "apr_range": "0.10% – 1.0%",
        "description": "Easy-to-borrow, deep float, abundant lendable supply.",
        "rebate_direction": "Positive rebate paid to the short seller on posted cash collateral.",
    },
    {
        "tier": "Warm / Special",
        "apr_range": "1% – 20%",
        "description": "Supply tightening; broker begins flagging elevated borrow rates.",
        "rebate_direction": "Rebate compresses toward zero.",
    },
    {
        "tier": "Hard-to-Borrow (HTB)",
        "apr_range": "20% – 100%",
        "description": "Locate desk actively rationing supply; daily fee resets are common.",
        "rebate_direction": "Rebate at or near zero; short seller earns little/no interest on collateral.",
    },
    {
        "tier": "Extreme / Squeeze-Grade HTB",
        "apr_range": "100% – 300%+",
        "description": "Retail/institutional tug-of-war on a tightly held float.",
        "rebate_direction": (
            "Negative rebate — the short seller pays the lender an additional daily "
            "premium just to hold the borrow."
        ),
    },
]

COLLATERAL_MECHANICS: dict[str, str] = {
    "standard_collateral_pct": "102% of the short position's value (typical for domestic equities)",
    "note": (
        "The stock lender earns interest on this cash (the rebate rate). For extreme "
        "HTB names this rebate turns negative, so the short seller effectively pays "
        "twice: the borrow fee and a negative-rebate premium."
    ),
}


@dataclass
class SymbolBorrowProfile:
    symbol: str
    name: str
    last_close: float
    realized_vol_pct: float
    avg_dollar_volume: float
    htb_proxy_score: float
    rate_tier: str
    estimated_borrow_apr_pct: float
    estimated_rebate_pct: float
    daily_borrow_cost_per_100k_usd: float
    rationale: str


@dataclass
class HTBAssessment:
    htb_names_count: int
    average_borrow_apr_pct: float
    tightest_symbol: str
    locate_friction_signal: str
    collateral_signal: str
    conclusion: str


@dataclass
class HTBDynamicsReport:
    symbols: list[SymbolBorrowProfile]
    assessment: HTBAssessment
    htb_pressure_score: float
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class HTBDynamicsExpert(BaseExpert):
    """Expert market analyst — Hard-to-Borrow locate/borrow-fee microstructure."""

    def __init__(
        self,
        delay_seconds: float = 0.35,
        *,
        pipeline_context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="htb-dynamics")
        self.delay_seconds = delay_seconds

    @staticmethod
    def _rate_tier_for_score(score: float) -> tuple[str, float, float]:
        """Map an HTB proxy score (0-100) to a rate tier, APR estimate, rebate estimate."""
        if score < 20:
            return "General Collateral (GC)", round(0.10 + score / 20 * 0.9, 2), round(2.0 - score / 20 * 1.0, 2)
        if score < 45:
            frac = (score - 20) / 25
            return "Warm / Special", round(1.0 + frac * 19.0, 2), round(1.0 - frac * 1.0, 2)
        if score < 75:
            frac = (score - 45) / 30
            return "Hard-to-Borrow (HTB)", round(20.0 + frac * 80.0, 2), round(0.0 - frac * 0.5, 2)
        frac = min((score - 75) / 25, 1.0)
        return "Extreme / Squeeze-Grade HTB", round(100.0 + frac * 220.0, 2), round(-0.5 - frac * 4.0, 2)

    def _analyze_symbol(self, symbol: str, name: str) -> SymbolBorrowProfile | None:
        data = self.fetch_yahoo_ohlcv(symbol, range_="3mo", interval="1d")
        closes = data.get("close", [])
        volumes = data.get("volume", [])
        if len(closes) < 15:
            return None

        last_close = closes[-1]
        window = min(len(closes), 20)
        recent_closes = closes[-window:]
        recent_volumes = volumes[-window:]

        daily_returns = [
            abs(recent_closes[i] / recent_closes[i - 1] - 1) * 100
            for i in range(1, len(recent_closes))
            if recent_closes[i - 1]
        ]
        realized_vol_pct = round(statistics.mean(daily_returns) if daily_returns else 0.0, 2)

        avg_dollar_volume = statistics.mean(
            [c * v for c, v in zip(recent_closes, recent_volumes)]
        )

        # HTB proxy: elevated realized volatility on thinner dollar-volume float is
        # the closest observable proxy for "float tightly held / short interest spike"
        # without a real short-interest feed.
        vol_component = min(realized_vol_pct / 8.0 * 60, 60)
        liquidity_component = max(0.0, 40 - min(avg_dollar_volume / 25_000_000, 1) * 40)
        htb_proxy_score = round(min(vol_component + liquidity_component, 100), 1)

        rate_tier, estimated_apr, estimated_rebate = self._rate_tier_for_score(htb_proxy_score)

        # Daily Borrow Cost = Short Position Value * Borrow Rate (APR) / 360
        daily_cost = round(100_000 * (estimated_apr / 100) / 360, 2)

        rationale = (
            f"Realized volatility {realized_vol_pct:.2f}%/day on "
            f"${avg_dollar_volume / 1e6:,.1f}M avg $ volume → HTB proxy score {htb_proxy_score:.0f}/100 "
            f"→ {rate_tier} ({estimated_apr:.1f}% APR est.)."
        )

        return SymbolBorrowProfile(
            symbol=symbol,
            name=name,
            last_close=round(last_close, 2),
            realized_vol_pct=realized_vol_pct,
            avg_dollar_volume=round(avg_dollar_volume, 0),
            htb_proxy_score=htb_proxy_score,
            rate_tier=rate_tier,
            estimated_borrow_apr_pct=estimated_apr,
            estimated_rebate_pct=estimated_rebate,
            daily_borrow_cost_per_100k_usd=daily_cost,
            rationale=rationale,
        )

    def _assessment(self, symbols: list[SymbolBorrowProfile]) -> HTBAssessment:
        htb_names = [s for s in symbols if s.htb_proxy_score >= 45]
        tightest = max(symbols, key=lambda s: s.htb_proxy_score) if symbols else None
        avg_apr = round(statistics.mean([s.estimated_borrow_apr_pct for s in symbols]), 2) if symbols else 0.0

        locate_friction_signal = (
            f"{len(htb_names)}/{len(symbols)} symbols screen as Hard-to-Borrow or tighter — "
            "Rule 203(b)(1) locates on these names require an affirmative determination "
            "before a short order can be accepted."
        )
        negative_rebate = [s for s in symbols if s.estimated_rebate_pct < 0]
        collateral_signal = (
            f"{len(negative_rebate)}/{len(symbols)} symbols carry a negative-rebate proxy — "
            "short sellers there pay a daily premium on top of the borrow fee just to hold the position."
        )
        if tightest and tightest.htb_proxy_score >= 75:
            conclusion = (
                f"{tightest.symbol} screens as squeeze-grade HTB ({tightest.estimated_borrow_apr_pct:.0f}% "
                "APR proxy) — locate desks will ration supply and borrow cost can reset intraday."
            )
        elif htb_names:
            conclusion = (
                "Mixed borrow regime: reserve short exposure sizing for names outside the HTB tier "
                "unless the thesis specifically compensates for elevated borrow drag."
            )
        else:
            conclusion = "Watchlist is broadly General-Collateral — borrow friction is not a binding constraint today."

        return HTBAssessment(
            htb_names_count=len(htb_names),
            average_borrow_apr_pct=avg_apr,
            tightest_symbol=tightest.symbol if tightest else "",
            locate_friction_signal=locate_friction_signal,
            collateral_signal=collateral_signal,
            conclusion=conclusion,
        )

    def _expert_summary(self, assessment: HTBAssessment) -> str:
        return (
            f"HTB scan: avg borrow-rate proxy {assessment.average_borrow_apr_pct:.1f}% APR. "
            f"{assessment.locate_friction_signal} {assessment.collateral_signal} {assessment.conclusion}"
        )

    def _market_signals(self, symbols: list[SymbolBorrowProfile]) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        def _keep(symbol: str) -> bool:
            return not self.pipeline_should_skip_symbol(symbol)

        htb = [s.symbol for s in symbols if s.htb_proxy_score >= 45 and _keep(s.symbol)]
        if htb:
            signals.append(
                {
                    "sector": "HTB Microstructure",
                    "bias": "borrow-cost-headwind",
                    "tickers": htb,
                    "reason": "Elevated borrow-rate proxy — short carry cost erodes thesis P&L over time.",
                }
            )
        negative_rebate = [s.symbol for s in symbols if s.estimated_rebate_pct < 0 and _keep(s.symbol)]
        if negative_rebate:
            signals.append(
                {
                    "sector": "HTB Microstructure",
                    "bias": "negative-rebate",
                    "tickers": negative_rebate,
                    "reason": "Negative rebate proxy — short sellers pay the lender a daily premium.",
                }
            )
        gc = [s.symbol for s in symbols if s.htb_proxy_score < 20 and _keep(s.symbol)]
        if gc:
            signals.append(
                {
                    "sector": "HTB Microstructure",
                    "bias": "cheap-to-borrow",
                    "tickers": gc,
                    "reason": "General-collateral borrow — minimal carry drag on short exposure.",
                }
            )
        return signals

    def _recommendations(
        self, symbols: list[SymbolBorrowProfile], assessment: HTBAssessment
    ) -> list[str]:
        recs = [assessment.conclusion]
        for s in sorted(symbols, key=lambda x: -x.htb_proxy_score)[:6]:
            recs.append(
                f"{s.symbol} ({s.rate_tier}): {s.estimated_borrow_apr_pct:.1f}% APR proxy, "
                f"~${s.daily_borrow_cost_per_100k_usd:.2f}/day per $100k short — {s.rationale}"
            )
        return recs

    def analyze(self) -> HTBDynamicsReport:
        symbols: list[SymbolBorrowProfile] = []
        for symbol, name in WATCHLIST.items():
            row = self._analyze_symbol(symbol, name)
            if row:
                symbols.append(row)
            time.sleep(self.delay_seconds)

        if not any(s.symbol == BENCHMARK for s in symbols):
            raise RuntimeError("Unable to fetch SPY data for htb-dynamics analysis")

        assessment = self._assessment(symbols)
        expert_summary = self._expert_summary(assessment)
        htb_pressure_score = round(
            statistics.mean([s.htb_proxy_score for s in symbols]) / 10, 1
        )

        return HTBDynamicsReport(
            symbols=symbols,
            assessment=assessment,
            htb_pressure_score=htb_pressure_score,
            expert_summary=expert_summary,
            market_signals=self._market_signals(symbols),
            recommendations=self._recommendations(symbols, assessment),
            data_source="Yahoo Finance Chart API (3mo daily OHLCV) — borrow rates are volatility/liquidity proxies",
        )

    def to_dict(self, report: HTBDynamicsReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Hard-to-Borrow (HTB) Microstructure Expert",
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
            "locate_requirement": LOCATE_REQUIREMENT,
            "borrow_rate_tiers": BORROW_RATE_TIERS,
            "collateral_mechanics": COLLATERAL_MECHANICS,
            "symbol_borrow_profiles": [
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "last_close": s.last_close,
                    "realized_vol_pct": s.realized_vol_pct,
                    "avg_dollar_volume": s.avg_dollar_volume,
                    "htb_proxy_score": s.htb_proxy_score,
                    "rate_tier": s.rate_tier,
                    "estimated_borrow_apr_pct": s.estimated_borrow_apr_pct,
                    "estimated_rebate_pct": s.estimated_rebate_pct,
                    "daily_borrow_cost_per_100k_usd": s.daily_borrow_cost_per_100k_usd,
                    "rationale": s.rationale,
                }
                for s in report.symbols
            ],
            "htb_assessment": {
                "htb_names_count": a.htb_names_count,
                "average_borrow_apr_pct": a.average_borrow_apr_pct,
                "tightest_symbol": a.tightest_symbol,
                "locate_friction_signal": a.locate_friction_signal,
                "collateral_signal": a.collateral_signal,
                "conclusion": a.conclusion,
            },
            "metrics": {"htb_pressure_score": report.htb_pressure_score},
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "htb_rate_matrix.json"
            catalog.write_text(json.dumps(BORROW_RATE_TIERS, indent=2), encoding="utf-8")
        return result


def run_htb_dynamics_analysis(
    output: Path | None = None,
    pipeline_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return HTBDynamicsExpert(pipeline_context=pipeline_context).run(output=output)
