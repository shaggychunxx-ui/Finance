"""
Elite Risk & Capital Protection Protocols Expert Agent
=======================================================
Disciplined capital-preservation rules computed from live market data:

* The 1% Rule — position sizing from account equity, risk limit, and an
  ATR-based stop distance.
* The Kelly Criterion Framework — f* = (p*b - (1-p)) / b, where p is the
  empirical daily win rate and b is the average win/loss payout ratio.
* Correlated Risk Caps — pairwise correlation of sector ETFs to flag
  concentration risk that should be capped in the active book.

Data: Yahoo Finance chart API (3-month daily OHLCV).
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
DEFAULT_ACCOUNT_EQUITY = 50_000.0
MAX_RISK_PER_TRADE_PCT = 1.0
ATR_LOOKBACK_DAYS = 14
CORRELATION_CAP_THRESHOLD = 0.75
SECTOR_CAP_PCT = 20.0

WATCHLIST: dict[str, str] = {
    "SPY": "S&P 500 (baseline stop-sizing reference)",
    "AAPL": "Mega-cap tech",
    "TSLA": "High-beta growth",
    "NVDA": "High-beta semiconductor",
}

SECTOR_UNIVERSE: dict[str, str] = {
    "SMH": "Semiconductors",
    "KRE": "Regional Banking",
    "XLK": "Technology",
    "XLF": "Financials",
}

RISK_PROTOCOLS: list[dict[str, Any]] = [
    {
        "id": "one_percent_rule",
        "name": "The 1% Rule",
        "description": (
            f"Never risk more than {MAX_RISK_PER_TRADE_PCT}% of total liquid trading "
            "account equity on a single day trade. Max shares = (equity * risk%) / stop-width."
        ),
    },
    {
        "id": "kelly_criterion",
        "name": "The Kelly Criterion Framework",
        "description": (
            "A mathematical formula used to size long-term portfolio bets based on "
            "historical win rate and profit-to-loss ratio: "
            "f* = (p*b - (1-p)) / b, where f* is the optimal bet size, p is the "
            "probability of a win, and b is the payout ratio."
        ),
    },
    {
        "id": "correlated_risk_caps",
        "name": "Correlated Risk Caps",
        "description": (
            "Ensure day trades or portfolio satellites are not quietly tied to the "
            f"same underlying risk. Cap exposure to any single sector at "
            f"{SECTOR_CAP_PCT}% of active capital to prevent a single sector event "
            "from wiping out progress."
        ),
    },
]


@dataclass
class PositionSizeGuard:
    symbol: str
    label: str
    last_close: float
    atr: float
    stop_width: float
    max_shares: int
    max_risk_dollars: float


@dataclass
class KellyReading:
    symbol: str
    label: str
    win_rate: float
    payout_ratio: float
    kelly_fraction: float
    half_kelly_fraction: float


@dataclass
class SectorCorrelation:
    sector_a: str
    sector_b: str
    correlation: float
    capped: bool


@dataclass
class RiskProtectionReport:
    account_equity: float
    position_size_guards: list[PositionSizeGuard]
    kelly_readings: list[KellyReading]
    sector_correlations: list[SectorCorrelation]
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RiskProtectionExpert(BaseExpert):
    """1% rule, Kelly criterion, and correlated risk cap protocols."""

    def __init__(self, *, pipeline_context: dict | None = None, account_equity: float = DEFAULT_ACCOUNT_EQUITY) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="risk-protection")
        self.delay_seconds = 0.35
        self.account_equity = account_equity

    @staticmethod
    def _average_true_range(ohlcv: dict[str, list[float]], lookback: int) -> float:
        highs, lows, closes = ohlcv["high"], ohlcv["low"], ohlcv["close"]
        if len(closes) < 2:
            return 0.0
        true_ranges: list[float] = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            true_ranges.append(tr)
        window = true_ranges[-lookback:] if len(true_ranges) > lookback else true_ranges
        return statistics.mean(window) if window else 0.0

    def _position_size_guard(self, symbol: str, label: str, ohlcv: dict[str, list[float]]) -> PositionSizeGuard | None:
        closes = ohlcv["close"]
        if not closes:
            return None
        atr = self._average_true_range(ohlcv, ATR_LOOKBACK_DAYS)
        stop_width = round(atr, 2) if atr > 0 else round(closes[-1] * 0.02, 2)
        max_risk_dollars = round(self.account_equity * (MAX_RISK_PER_TRADE_PCT / 100), 2)
        max_shares = int(max_risk_dollars // stop_width) if stop_width > 0 else 0
        return PositionSizeGuard(
            symbol=symbol,
            label=label,
            last_close=round(closes[-1], 2),
            atr=round(atr, 2),
            stop_width=stop_width,
            max_shares=max_shares,
            max_risk_dollars=max_risk_dollars,
        )

    @staticmethod
    def _daily_returns(closes: list[float]) -> list[float]:
        return [(closes[i] / closes[i - 1]) - 1 for i in range(1, len(closes)) if closes[i - 1]]

    def _kelly_reading(self, symbol: str, label: str, closes: list[float]) -> KellyReading | None:
        returns = self._daily_returns(closes)
        if len(returns) < 10:
            return None
        wins = [r for r in returns if r > 0]
        losses = [abs(r) for r in returns if r < 0]
        if not wins or not losses:
            return None
        win_rate = round(len(wins) / len(returns), 4)
        avg_win = statistics.mean(wins)
        avg_loss = statistics.mean(losses)
        payout_ratio = round(avg_win / avg_loss, 4) if avg_loss > 0 else 0.0
        if payout_ratio <= 0:
            return None
        kelly = (win_rate * payout_ratio - (1 - win_rate)) / payout_ratio
        kelly = max(0.0, min(kelly, 1.0))
        return KellyReading(
            symbol=symbol,
            label=label,
            win_rate=win_rate,
            payout_ratio=payout_ratio,
            kelly_fraction=round(kelly, 4),
            half_kelly_fraction=round(kelly / 2, 4),
        )

    def _sector_correlations(self, sector_closes: dict[str, list[float]]) -> list[SectorCorrelation]:
        symbols = list(sector_closes.keys())
        results: list[SectorCorrelation] = []
        for i in range(len(symbols)):
            for j in range(i + 1, len(symbols)):
                a, b = symbols[i], symbols[j]
                returns_a = self._daily_returns(sector_closes[a])
                returns_b = self._daily_returns(sector_closes[b])
                n = min(len(returns_a), len(returns_b))
                if n < 10:
                    continue
                ra, rb = returns_a[-n:], returns_b[-n:]
                try:
                    corr = statistics.correlation(ra, rb)
                except (statistics.StatisticsError, ZeroDivisionError):
                    continue
                results.append(
                    SectorCorrelation(
                        sector_a=SECTOR_UNIVERSE.get(a, a),
                        sector_b=SECTOR_UNIVERSE.get(b, b),
                        correlation=round(corr, 3),
                        capped=abs(corr) >= CORRELATION_CAP_THRESHOLD,
                    )
                )
        return results

    def _market_signals(
        self,
        kelly_readings: list[KellyReading],
        sector_correlations: list[SectorCorrelation],
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal

        signals: list[dict[str, Any]] = []
        aggressive = [k for k in kelly_readings if k.kelly_fraction >= 0.2]
        if aggressive:
            signals.append(
                build_market_signal(
                    sector="Risk Sizing / Kelly Criterion",
                    tickers=[k.symbol for k in aggressive][:5],
                    bias="NEUTRAL",
                    reason=f"{len(aggressive)} symbols with Kelly fraction >= 0.2 (favorable historical edge)",
                    confidence=0.5,
                )
            )
        capped = [c for c in sector_correlations if c.capped]
        if capped:
            signals.append(
                build_market_signal(
                    sector="Correlated Risk Cap",
                    tickers=list(SECTOR_UNIVERSE.keys()),
                    bias="NEUTRAL",
                    reason=f"{len(capped)} sector pairs correlated >= {CORRELATION_CAP_THRESHOLD} — cap combined exposure",
                    confidence=0.55,
                )
            )
        if not signals:
            signals.append(
                build_market_signal(
                    sector="Capital Protection",
                    tickers=[BENCHMARK],
                    bias="NEUTRAL",
                    reason="No elevated Kelly edge or sector correlation risk detected",
                    confidence=0.4,
                )
            )
        return signals

    def analyze(self) -> RiskProtectionReport:
        position_guards: list[PositionSizeGuard] = []
        kelly_readings: list[KellyReading] = []
        for symbol, label in WATCHLIST.items():
            ohlcv = self.fetch_yahoo_ohlcv(symbol, range_="3mo", interval="1d")
            if not ohlcv["close"]:
                continue
            guard = self._position_size_guard(symbol, label, ohlcv)
            if guard:
                position_guards.append(guard)
            kelly = self._kelly_reading(symbol, label, ohlcv["close"])
            if kelly:
                kelly_readings.append(kelly)

        if not any(g.symbol == BENCHMARK for g in position_guards):
            raise RuntimeError("Unable to fetch SPY data for risk protection analysis")

        sector_closes: dict[str, list[float]] = {}
        for symbol in SECTOR_UNIVERSE:
            closes = self.fetch_yahoo_closes(symbol, range_="3mo")
            if closes:
                sector_closes[symbol] = closes
        sector_correlations = self._sector_correlations(sector_closes)

        capped_count = sum(1 for c in sector_correlations if c.capped)
        summary = (
            f"Sized {len(position_guards)} symbols under the 1% rule (${self.account_equity:,.0f} equity), "
            f"computed Kelly fractions for {len(kelly_readings)} symbols, "
            f"and flagged {capped_count} sector pairs above the {CORRELATION_CAP_THRESHOLD} correlation cap."
        )

        recs = [summary]
        for g in position_guards:
            recs.append(
                f"{g.symbol} ({g.label}): stop-width ${g.stop_width} (ATR {ATR_LOOKBACK_DAYS}) -> "
                f"max {g.max_shares} shares (${g.max_risk_dollars} at risk)"
            )
        for k in kelly_readings:
            recs.append(
                f"{k.symbol} ({k.label}): win rate {k.win_rate:.1%}, payout {k.payout_ratio}, "
                f"Kelly f*={k.kelly_fraction} (half-Kelly {k.half_kelly_fraction})"
            )
        for c in sector_correlations:
            if c.capped:
                recs.append(
                    f"Cap combined exposure: {c.sector_a} / {c.sector_b} correlated at {c.correlation}"
                )
        recs.append(f"Cap any single sector at {SECTOR_CAP_PCT}% of active capital.")

        return RiskProtectionReport(
            account_equity=self.account_equity,
            position_size_guards=position_guards,
            kelly_readings=kelly_readings,
            sector_correlations=sector_correlations,
            expert_summary=summary,
            market_signals=self._market_signals(kelly_readings, sector_correlations),
            recommendations=recs,
        )

    def to_dict(self, report: RiskProtectionReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Elite Risk & Capital Protection Protocols Expert",
                "analyzed_at": report.analyzed_at,
                "data_sources": ["Yahoo Finance Chart API"],
                "expert_summary": report.expert_summary,
                "temperature": self.temperature,
                "account_equity": report.account_equity,
            },
            "position_size_guards": [
                {
                    "symbol": g.symbol,
                    "label": g.label,
                    "last_close": g.last_close,
                    "atr": g.atr,
                    "stop_width": g.stop_width,
                    "max_shares": g.max_shares,
                    "max_risk_dollars": g.max_risk_dollars,
                }
                for g in report.position_size_guards
            ],
            "kelly_readings": [
                {
                    "symbol": k.symbol,
                    "label": k.label,
                    "win_rate": k.win_rate,
                    "payout_ratio": k.payout_ratio,
                    "kelly_fraction": k.kelly_fraction,
                    "half_kelly_fraction": k.half_kelly_fraction,
                }
                for k in report.kelly_readings
            ],
            "sector_correlations": [
                {
                    "sector_a": c.sector_a,
                    "sector_b": c.sector_b,
                    "correlation": c.correlation,
                    "capped": c.capped,
                }
                for c in report.sector_correlations
            ],
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "risk_protocols.json"
            catalog.write_text(json.dumps(RISK_PROTOCOLS, indent=2), encoding="utf-8")
        return result


def run_risk_protection_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return RiskProtectionExpert(pipeline_context=pipeline_context).run(output=output)
