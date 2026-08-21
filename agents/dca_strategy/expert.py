"""
DCA Strategy Expert Agent
=========================
Dollar-cost averaging knowledge + calendar buy plan for the Finance pipeline.

This agent does **not** time entries from fusion signals. It proposes fixed-dollar
purchases on a schedule into a diversified ETF core, isolated from the long
rebalance sleeve and the day-trade sleeve.

Execution lives in ``dca_engine.py`` (E*TRADE worker hook). Live orders stay
off until ``dca_strategy.enabled`` is true in etrade_config.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base import BaseExpert

AGENT_ID = "dca-strategy"
AGENT_LABEL = "DCA Strategy Expert"

# Fallback marks used only when no live quote is cached (illustrative).
PROXY_PRICES: dict[str, float] = {
    "VTI": 280.0,
    "ITOT": 130.0,
    "SPY": 560.0,
    "VXUS": 65.0,
    "IXUS": 75.0,
    "BND": 73.0,
    "AGG": 100.0,
    "QQQ": 480.0,
    "SCHD": 80.0,
}

DCA_KNOWLEDGE: dict[str, Any] = {
    "definition": (
        "Dollar-cost averaging (DCA) invests a fixed dollar amount on a fixed "
        "calendar (weekly or monthly) regardless of price. Share count floats: "
        "more shares when cheap, fewer when expensive."
    ),
    "purpose": [
        "Remove market-timing decisions from new cash that arrives on a schedule.",
        "Smooth entry price versus a single lump-sum buy of the same cash.",
        "Build a long-term core that the signal rebalance sleeve must not sell.",
    ],
    "vs_lump_sum": (
        "Historical studies (e.g. Vanguard) find lump-sum often beats DCA about "
        "two-thirds of the time in rising equity markets because cash sits in "
        "the market longer. DCA still wins on regret/volatility of the path and "
        "is the right tool when cash arrives over time (paycheck), not when a "
        "pile of cash is already idle and the mandate is maximize expected wealth."
    ),
    "cadence": {
        "weekly": "Closer to investing cash as it arrives; more lots; leftover cash smaller.",
        "monthly": "Fewer tickets; typical payday match; larger leftover if prices are high.",
        "rule": "Cadence should match when cash actually becomes available, not a guessed 'best day'.",
    },
    "vehicles": (
        "Default core is broad, low-cost, highly liquid ETFs (total US, intl, bonds). "
        "Single-name DCA concentrates idiosyncratic risk and fights the long sleeve. "
        "Do not DCA into illiquid, leveraged, or inverse products."
    ),
    "execution_rules": [
        "BUY only. DCA never sells, short, or flattens.",
        "Whole shares only (E*TRADE equity tickets). Leftover cash rolls to the next period.",
        "US cash-session only. No extended-hours routing.",
        "Skip the period if already filled, trading paused, cash below floor, or opposite short exists.",
        "A buy that is held overnight is not a PDT day-trade. Do not flatten before close.",
        "Protect filled lots from strategy_engine SELL / trim so rebalance cannot harvest the core.",
        "Reserve this period's dollars in sleeve_policy so day/swing sleeves do not spend them.",
    ],
    "tax": [
        "Each buy is a tax lot. Long-term holding period starts the trade date (typically 1 year + 1 day).",
        "Avoid selling the same symbol in another sleeve around a DCA buy (wash-sale risk in taxable accounts).",
        "Dividends on core ETFs should be set to reinvest or swept; this agent does not place DRIP tickets.",
    ],
    "overlays": {
        "off": "Ignore VIX. Pure calendar. Default.",
        "skip_high": "Skip the period when VIX is above vix_high (optional freeze in a panic).",
        "lean_in": "Multiply amount when VIX is above vix_high (buy more of the dip). Use only with spare cash.",
    },
    "what_this_is_not": [
        "Not target-weight rebalance (strategy_engine).",
        "Not intraday alpha (day_trader).",
        "Not a short sleeve.",
        "Not a forecast agent. Directional accuracy scoring does not apply.",
    ],
    "default_core": [
        {"symbol": "VTI", "weight_pct": 70.0, "role": "US total market"},
        {"symbol": "VXUS", "weight_pct": 20.0, "role": "International ex-US"},
        {"symbol": "BND", "weight_pct": 10.0, "role": "US aggregate bonds"},
    ],
}

DCA_METHODOLOGY: dict[str, Any] = {
    "id": "dca-strategy",
    "name": "Scheduled dollar-cost averaging",
    "pipeline_lane": "research",
    "group": "dca_invest",
    "horizon": "1yr",
    "execution": "dca_engine.py via etrade_worker after long rebalance, before day trading",
    "knowledge": DCA_KNOWLEDGE,
}


@dataclass
class DcaLot:
    symbol: str
    name: str
    weight_pct: float
    amount_usd: float
    price: float
    shares: int
    leftover_usd: float
    data_source: str


@dataclass
class DcaReport:
    analyzed_at: str
    enabled: bool
    cadence: str
    period_key: str
    due: bool
    already_filled: bool
    amount_usd: float
    lots: list[DcaLot] = field(default_factory=list)
    expert_summary: str = ""
    market_signals: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    data_sources: list[str] = field(default_factory=list)
    schedule: dict[str, Any] = field(default_factory=dict)
    settings_public: dict[str, Any] = field(default_factory=dict)


class DcaStrategyExpert(BaseExpert):
    def __init__(self, pipeline_context: dict[str, Any] | None = None) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id=AGENT_ID)

    def _settings(self) -> dict[str, Any]:
        from dca_engine import load_dca_settings

        return load_dca_settings()

    def _price(self, symbol: str) -> tuple[float, str]:
        live = self.live_price(symbol)
        if live and live > 0:
            return float(live), "etrade_enhanced_quote"
        return float(PROXY_PRICES.get(symbol.upper(), 100.0)), "proxy"

    def analyze(self) -> DcaReport:
        from dca_engine import (
            already_filled,
            is_period_due,
            load_dca_settings,
            period_key,
            planned_lots,
            public_settings,
        )

        settings = load_dca_settings()
        now = datetime.now(timezone.utc)
        key = period_key(settings, now=now)
        due = is_period_due(settings, now=now)
        filled = already_filled(key)
        amount = float(settings.get("amount_usd") or 0)
        lots_raw = planned_lots(settings, price_fn=self._price)
        lots = [
            DcaLot(
                symbol=row["symbol"],
                name=row.get("name") or row["symbol"],
                weight_pct=float(row.get("weight_pct") or 0),
                amount_usd=float(row.get("amount_usd") or 0),
                price=float(row.get("price") or 0),
                shares=int(row.get("shares") or 0),
                leftover_usd=float(row.get("leftover_usd") or 0),
                data_source=str(row.get("data_source") or ""),
            )
            for row in lots_raw
        ]
        sources = sorted({lot.data_source for lot in lots if lot.data_source})
        enabled = bool(settings.get("enabled"))
        cadence = str(settings.get("cadence") or "weekly")

        if not enabled:
            summary = (
                "DCA sleeve is implemented and wired, but live buys are OFF "
                "(dca_strategy.enabled=false). Set enabled true and amount_usd "
                "in etrade_config.json to start scheduled purchases."
            )
        elif filled:
            summary = f"Period {key} already filled. Next calendar period waits."
        elif due:
            buyable = [lot for lot in lots if lot.shares > 0]
            summary = (
                f"Period {key} is due. {len(buyable)} whole-share BUY(s) from "
                f"${amount:.2f} {cadence} into the core ETF mix."
            )
        else:
            summary = (
                f"DCA armed. Period {key} is not due yet "
                f"({cadence}, weekday={settings.get('weekday')}, "
                f"after {settings.get('execute_after_et')} ET)."
            )

        signals = [
            {
                "sector": "core_allocation",
                "bias": "NEUTRAL",
                "tickers": [lot.symbol for lot in lots],
                "reason": (
                    "Scheduled DCA core. Not a directional forecast. "
                    "Buy on calendar; do not time with fusion."
                ),
            }
        ]
        recs = [
            DCA_KNOWLEDGE["definition"],
            "Live execution: etrade_worker -> dca_engine after long rebalance, before day trading.",
            "Protect filled lots from strategy SELL. Reserve cash on due days.",
        ]
        if not enabled:
            recs.append(
                "To go live: set dca_strategy.enabled=true, pick amount_usd and universe, "
                "keep background_worker.dry_run true for a rehearsal first."
            )
        for lot in lots:
            if lot.shares <= 0 and lot.amount_usd > 0:
                recs.append(
                    f"{lot.symbol}: ${lot.amount_usd:.2f} < 1 share at ${lot.price:.2f}; leftover rolls."
                )

        return DcaReport(
            analyzed_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            enabled=enabled,
            cadence=cadence,
            period_key=key,
            due=due,
            already_filled=filled,
            amount_usd=amount,
            lots=lots,
            expert_summary=summary,
            market_signals=signals,
            recommendations=self.append_memory_recommendations(recs),
            data_sources=sources or ["config"],
            schedule={
                "period_key": key,
                "due": due,
                "already_filled": filled,
                "weekday": settings.get("weekday"),
                "month_day": settings.get("month_day"),
                "execute_after_et": settings.get("execute_after_et"),
            },
            settings_public=public_settings(settings),
        )

    def to_dict(self, report: DcaReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": AGENT_LABEL,
                "agent_id": AGENT_ID,
                "analyzed_at": report.analyzed_at,
                "expert_summary": report.expert_summary,
                "data_sources": report.data_sources,
                "pipeline_lane": "research",
                "group": "dca_invest",
                "horizon": "1yr",
            },
            "knowledge": DCA_KNOWLEDGE,
            "settings": report.settings_public,
            "schedule": report.schedule,
            "lots": [
                {
                    "symbol": lot.symbol,
                    "name": lot.name,
                    "weight_pct": round(lot.weight_pct, 2),
                    "amount_usd": round(lot.amount_usd, 2),
                    "price": round(lot.price, 4),
                    "shares": lot.shares,
                    "leftover_usd": round(lot.leftover_usd, 2),
                    "data_source": lot.data_source,
                }
                for lot in report.lots
            ],
            "metrics": {
                "enabled": report.enabled,
                "cadence": report.cadence,
                "amount_usd": round(report.amount_usd, 2),
                "due": report.due,
                "already_filled": report.already_filled,
                "buyable_shares": sum(lot.shares for lot in report.lots),
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            (output.parent / "dca_methodology.json").write_text(
                json.dumps(DCA_METHODOLOGY, indent=2),
                encoding="utf-8",
            )
        return result


def run_dca_strategy_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return DcaStrategyExpert(pipeline_context=pipeline_context).run(output=output)
