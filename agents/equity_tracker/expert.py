"""
Equity Tracker & Single-Name Stock Expert
=========================================
Institutional-style equity tracking for liquid U.S. common stocks: multi-horizon
returns, trend regime (SMA stack), relative strength vs SPY, liquidity/volume
context, and a structured long-only equity playbook.

Domain expertise covered:
  - Factor lens: momentum, quality proxies (drawdown control), beta vs SPY
  - Position tracking: merges pipeline/live quotes and broker snapshot equities
  - Risk: extended drawdowns, high beta, underperformance vs benchmark
  - Horizon: 24h tactical + 1wk swing bias (not fixed-income duration)

Data: Yahoo Finance daily OHLCV via ``agents.market_data.yahoo`` (+ optional
E*TRADE enhanced quotes / account_snapshot for held names).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base import BaseExpert

DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "output" / "equity_tracker.json"
DASHBOARD_URL = "https://finance.yahoo.com/"

# Core liquid single-name equity universe (common stock, not bond/ETF sleeves)
CORE_EQUITIES: dict[str, str] = {
    "AAPL": "Apple — mega-cap quality / consumer tech",
    "MSFT": "Microsoft — mega-cap software / cloud",
    "NVDA": "NVIDIA — semiconductors / AI infrastructure",
    "AMZN": "Amazon — consumer discretionary / cloud",
    "META": "Meta — communication services / ads",
    "GOOGL": "Alphabet — search / cloud / ads",
    "TSLA": "Tesla — EV / high-beta growth",
    "JPM": "JPMorgan — money-center bank",
    "XOM": "Exxon — integrated energy",
    "UNH": "UnitedHealth — managed care",
    "JNJ": "Johnson & Johnson — defensive healthcare",
    "V": "Visa — payments network",
    "MA": "Mastercard — payments network",
    "AVGO": "Broadcom — semis / infrastructure software",
    "COST": "Costco — consumer staples retail",
}

# Names that look like equities in the book but are funds — exclude from equity-only
_NON_EQUITY_HINTS = (
    "ETF", "BOND", "TREAS", "AGG", "BND", "LQD", "HYG", "TLT", "IEF", "SHY",
    "TIP", "GLD", "SLV", "VIX", "PRBLX", "TAIBX", "PHYZX", "ETBOX", "ETMUX",
    "SPCX", "SAGMF",
)

EQUITY_PLAYBOOK: list[dict[str, str]] = [
    {
        "id": "trend_alignment",
        "name": "Trend alignment",
        "rule": "Prefer longs when price > 50-day SMA and 50-day > 200-day (bull stack).",
    },
    {
        "id": "rs_vs_spy",
        "name": "Relative strength",
        "rule": "Favor names outperforming SPY over 1 month; fade chronic laggards unless mean-reversion setup.",
    },
    {
        "id": "liquidity",
        "name": "Liquidity filter",
        "rule": "Prioritize high ADV names for position sizing; avoid illiquid microcaps for core book.",
    },
    {
        "id": "drawdown_discipline",
        "name": "Drawdown discipline",
        "rule": "Flag >15% peak-to-trough over 3 months as elevated risk; require catalyst to add.",
    },
    {
        "id": "earnings_event",
        "name": "Event risk",
        "rule": "Around earnings, cut size or use defined-risk structures; do not size as quiet tape.",
    },
]


@dataclass
class EquitySnapshot:
    symbol: str
    label: str
    last: float | None = None
    day_chg_pct: float | None = None
    week_chg_pct: float | None = None
    month_chg_pct: float | None = None
    vs_spy_1m_pct: float | None = None
    sma50: float | None = None
    sma200: float | None = None
    trend: str = "unknown"
    score: float = 0.0
    held: bool = False
    notes: list[str] = field(default_factory=list)


class EquityTrackerExpert(BaseExpert):
    def __init__(
        self,
        *,
        pipeline_context: dict[str, Any] | None = None,
        delay_seconds: float = 0.25,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="equity-tracker")
        self.delay_seconds = delay_seconds

    def _held_equities(self) -> set[str]:
        held: set[str] = set()
        root = Path(__file__).resolve().parents[2]
        for base in (Path.home() / "Finance", root):
            snap = base / "output" / "account_snapshot.json"
            if not snap.is_file():
                continue
            try:
                data = json.loads(snap.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            for row in data.get("positions") or []:
                if not isinstance(row, dict):
                    continue
                sym = str(row.get("symbol") or "").upper().strip()
                if not sym or any(h in sym for h in _NON_EQUITY_HINTS):
                    continue
                # Skip obvious mutual fund ticker patterns (often 5 letters ending X)
                if len(sym) == 5 and sym.endswith("X") and sym.isalpha():
                    continue
                held.add(sym)
        return held

    @staticmethod
    def _pct(closes: list[float], lookback: int) -> float | None:
        if len(closes) <= lookback or closes[-1 - lookback] == 0:
            return None
        return round((closes[-1] / closes[-1 - lookback] - 1.0) * 100.0, 3)

    @staticmethod
    def _sma(closes: list[float], window: int) -> float | None:
        if len(closes) < window or window <= 0:
            return None
        return sum(closes[-window:]) / window

    def _score(self, row: EquitySnapshot) -> float:
        s = 50.0
        if row.trend == "bull_stack":
            s += 18
        elif row.trend == "uptrend":
            s += 10
        elif row.trend == "downtrend":
            s -= 12
        elif row.trend == "bear_stack":
            s -= 18
        if row.vs_spy_1m_pct is not None:
            s += max(-15.0, min(15.0, row.vs_spy_1m_pct))
        if row.month_chg_pct is not None:
            s += max(-10.0, min(10.0, row.month_chg_pct * 0.35))
        if row.held:
            s += 3  # slight bias to monitor held names
        return round(max(0.0, min(100.0, s)), 2)

    def analyze(self) -> dict[str, Any]:
        held = self._held_equities()
        universe = dict(CORE_EQUITIES)
        for sym in held:
            universe.setdefault(sym, f"Held equity — {sym}")
        # Pipeline watchlist merge
        for sym in self.pipeline_watchlist_symbols(list(universe.keys()), limit=40):
            if sym in CORE_EQUITIES or sym in held:
                universe.setdefault(sym, CORE_EQUITIES.get(sym, f"Watchlist equity — {sym}"))

        spy_closes = self.fetch_yahoo_closes("SPY", range_="1y", interval="1d")
        spy_1m = self._pct(spy_closes, 21) if spy_closes else None

        rows: list[EquitySnapshot] = []
        errors: list[str] = []
        for sym, label in universe.items():
            if self.pipeline_should_skip_symbol(sym):
                continue
            if not self.domain_allows_symbol(sym, sector_hint="equity"):
                continue
            try:
                closes = self.fetch_yahoo_closes(sym, range_="1y", interval="1d")
            except Exception as exc:
                errors.append(f"{sym}: {exc}")
                continue
            if len(closes) < 30:
                errors.append(f"{sym}: insufficient bars")
                continue
            sma50 = self._sma(closes, 50)
            sma200 = self._sma(closes, 200)
            last = closes[-1]
            if sma50 and sma200:
                if last > sma50 > sma200:
                    trend = "bull_stack"
                elif last > sma50:
                    trend = "uptrend"
                elif last < sma50 < sma200:
                    trend = "bear_stack"
                else:
                    trend = "downtrend"
            elif sma50:
                trend = "uptrend" if last > sma50 else "downtrend"
            else:
                trend = "unknown"

            month = self._pct(closes, 21)
            vs_spy = None
            if month is not None and spy_1m is not None:
                vs_spy = round(month - spy_1m, 3)

            notes: list[str] = []
            if vs_spy is not None and vs_spy > 3:
                notes.append("Outperforming SPY over ~1m")
            if vs_spy is not None and vs_spy < -3:
                notes.append("Lagging SPY over ~1m")
            peak = max(closes[-63:]) if len(closes) >= 63 else max(closes)
            dd = (last / peak - 1.0) * 100.0 if peak else 0.0
            if dd <= -15:
                notes.append(f"Elevated drawdown from 3m peak ({dd:.1f}%)")

            live = self.live_price(sym)
            row = EquitySnapshot(
                symbol=sym,
                label=label,
                last=round(float(live if live is not None else last), 4),
                day_chg_pct=self._pct(closes, 1),
                week_chg_pct=self._pct(closes, 5),
                month_chg_pct=month,
                vs_spy_1m_pct=vs_spy,
                sma50=round(sma50, 4) if sma50 else None,
                sma200=round(sma200, 4) if sma200 else None,
                trend=trend,
                held=sym in held,
                notes=notes,
            )
            row.score = self._score(row) * self.pipeline_symbol_confidence_factor(sym)
            rows.append(row)

        rows.sort(key=lambda r: r.score, reverse=True)
        leaders = [r.symbol for r in rows if r.score >= 62][:8]
        laggards = [r.symbol for r in rows if r.score <= 40][:8]
        held_rows = [r for r in rows if r.held]

        bullish = sum(1 for r in rows if r.trend in ("bull_stack", "uptrend"))
        bearish = sum(1 for r in rows if r.trend in ("bear_stack", "downtrend"))
        if bullish > bearish * 1.4:
            direction = "BULLISH"
            regime = "equity_risk_on"
        elif bearish > bullish * 1.4:
            direction = "BEARISH"
            regime = "equity_risk_off"
        else:
            direction = "NEUTRAL"
            regime = "mixed"

        recs = [
            f"Equity regime: {regime} ({bullish} uptrend / {bearish} downtrend of {len(rows)} tracked).",
            f"Leaders by composite score: {', '.join(leaders) or 'n/a'}.",
            f"Laggards / caution: {', '.join(laggards) or 'n/a'}.",
        ]
        if held_rows:
            held_txt = ", ".join(f"{r.symbol}({r.trend},{r.score:.0f})" for r in held_rows[:10])
            recs.append(f"Held equities tracked: {held_txt}.")
        if direction == "BULLISH":
            recs.append("Lean long high-score equities with bull SMA stack; size by liquidity.")
        elif direction == "BEARISH":
            recs.append("Reduce beta / prefer quality defensives; avoid adding weak RS names.")
        else:
            recs.append("Mixed equity tape — favor relative-strength leaders only, keep cash optional.")
        recs = self.append_memory_recommendations(recs)

        conf = 0.45 + 0.25 * min(1.0, abs(bullish - bearish) / max(1, len(rows)))
        return {
            "status": "ok" if rows else "degraded",
            "regime": regime,
            "benchmark": "SPY",
            "spy_1m_chg_pct": spy_1m,
            "equities": [asdict(r) for r in rows],
            "leaders": leaders,
            "laggards": laggards,
            "held_count": len(held_rows),
            "playbook": EQUITY_PLAYBOOK,
            "recommendations": recs,
            "errors": errors[:20],
            "signal": {
                "direction": direction,
                "confidence": round(min(0.9, conf), 3),
                "horizon": self.preferred_horizon() or "1wk",
            },
            "tickers_bullish": leaders[:6],
            "tickers_bearish": laggards[:6],
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        body = self.analyze()
        payload = {
            "agent": "equity-tracker",
            "label": "Equity Tracker & Single-Name Stock Expert",
            "temperature": self.temperature,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "Yahoo Finance + account_snapshot equities",
            "dashboard": DASHBOARD_URL,
            "domain": "equities",
            **body,
        }
        try:
            from agent_groups import apply_group_conduct_to_report

            payload = apply_group_conduct_to_report(payload, "equity-tracker")
        except Exception:
            pass
        out = output or DEFAULT_OUTPUT
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload


def run_equity_tracker_analysis(
    output: Path | None = None,
    pipeline_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return EquityTrackerExpert(pipeline_context=pipeline_context).run(output=output)
