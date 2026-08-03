"""
ETF Tracker & Vehicle Structure Expert
======================================
Tracks liquid ETFs across equity beta, sector, international, commodity, and
fixed-income vehicles: category relative strength, tracking vs primary
benchmark (SPY / AGG), momentum regime, and held-ETF book awareness.

Domain expertise covered:
  - Vehicle taxonomy: broad equity, sector, factor, international, bond, commodity
  - Tracking error proxy: residual return vs category benchmark
  - Flow/momentum proxy: multi-horizon returns and volume-aware caution notes
  - Implementation: when to use ETF vs single-name (liquidity, diversification)
  - Complements ``etf-mechanics`` (creation/redemption/NAV arb) with **portfolio
    tracking** and category leadership

Data: Yahoo Finance daily closes; optional account_snapshot for held ETFs.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base import BaseExpert

DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "output" / "etf_tracker.json"
DASHBOARD_URL = "https://finance.yahoo.com/etfs/"

# symbol -> category, benchmark, label
ETF_CATALOG: dict[str, dict[str, str]] = {
    # Broad equity
    "SPY": {"category": "us_large", "benchmark": "SPY", "label": "S&P 500"},
    "IVV": {"category": "us_large", "benchmark": "SPY", "label": "S&P 500 (iShares)"},
    "VOO": {"category": "us_large", "benchmark": "SPY", "label": "S&P 500 (Vanguard)"},
    "QQQ": {"category": "us_nasdaq", "benchmark": "QQQ", "label": "Nasdaq-100"},
    "IWM": {"category": "us_small", "benchmark": "IWM", "label": "Russell 2000"},
    "DIA": {"category": "us_dow", "benchmark": "DIA", "label": "Dow 30"},
    # Sectors
    "XLK": {"category": "sector_tech", "benchmark": "SPY", "label": "Technology"},
    "XLF": {"category": "sector_fin", "benchmark": "SPY", "label": "Financials"},
    "XLE": {"category": "sector_energy", "benchmark": "SPY", "label": "Energy"},
    "XLV": {"category": "sector_health", "benchmark": "SPY", "label": "Health Care"},
    "XLI": {"category": "sector_ind", "benchmark": "SPY", "label": "Industrials"},
    "XLY": {"category": "sector_disc", "benchmark": "SPY", "label": "Consumer Disc."},
    "XLP": {"category": "sector_staples", "benchmark": "SPY", "label": "Consumer Staples"},
    "XLU": {"category": "sector_util", "benchmark": "SPY", "label": "Utilities"},
    # International
    "EFA": {"category": "intl_developed", "benchmark": "EFA", "label": "EAFE developed"},
    "EEM": {"category": "intl_em", "benchmark": "EEM", "label": "Emerging markets"},
    "VXUS": {"category": "intl_all", "benchmark": "VXUS", "label": "Total intl equity"},
    # Factors
    "MTUM": {"category": "factor_mom", "benchmark": "SPY", "label": "Momentum factor"},
    "QUAL": {"category": "factor_qual", "benchmark": "SPY", "label": "Quality factor"},
    "USMV": {"category": "factor_minvol", "benchmark": "SPY", "label": "Min volatility"},
    # Fixed income ETFs
    "BND": {"category": "bond_agg", "benchmark": "BND", "label": "US Aggregate"},
    "AGG": {"category": "bond_agg", "benchmark": "AGG", "label": "US Aggregate (iShares)"},
    "TLT": {"category": "bond_long", "benchmark": "TLT", "label": "Long Treasury"},
    "IEF": {"category": "bond_inter", "benchmark": "IEF", "label": "7–10Y Treasury"},
    "LQD": {"category": "bond_ig", "benchmark": "LQD", "label": "IG Corporate"},
    "HYG": {"category": "bond_hy", "benchmark": "HYG", "label": "High Yield"},
    "TIP": {"category": "bond_tips", "benchmark": "TIP", "label": "TIPS"},
    "SGOV": {"category": "bond_tbill", "benchmark": "SGOV", "label": "T-Bill 0–3M"},
    # Commodity / alt
    "GLD": {"category": "commodity_gold", "benchmark": "GLD", "label": "Gold"},
    "SLV": {"category": "commodity_silver", "benchmark": "SLV", "label": "Silver"},
    "USO": {"category": "commodity_oil", "benchmark": "USO", "label": "Crude oil"},
}

ETF_PLAYBOOK: list[dict[str, str]] = [
    {
        "id": "use_case",
        "name": "Vehicle selection",
        "rule": "Use broad ETFs for beta; sector/factor ETFs for tilts; bond ETFs for duration/credit — match vehicle to thesis.",
    },
    {
        "id": "tracking",
        "name": "Tracking quality",
        "rule": "Prefer high-AUM plain-vanilla ETFs for core; avoid exotic structures when simple beta is the goal.",
    },
    {
        "id": "relative_strength",
        "name": "Category RS",
        "rule": "Rotate toward categories beating SPY (equity) or BND (bonds) over 1m; fade chronic underperformers.",
    },
    {
        "id": "overlap",
        "name": "Overlap risk",
        "rule": "SPY+QQQ+XLK stacks tech concentration — count effective factor exposure, not ticker count.",
    },
    {
        "id": "liquidity",
        "name": "Liquidity",
        "rule": "Core positions only in tight-spread ETFs (SPY/QQQ/IWM/BND/TLT/HYG class).",
    },
    {
        "id": "vs_single_name",
        "name": "ETF vs stock",
        "rule": "Prefer ETF when thesis is sector/factor/region; single-name when stock-specific edge exists.",
    },
]

# Mutual fund / non-ETF tickers sometimes held — still classify if they look fund-like
_FUND_SUFFIX_HINTS = ("X",)


@dataclass
class EtfSnapshot:
    symbol: str
    label: str
    category: str
    benchmark: str
    last: float | None = None
    day_chg_pct: float | None = None
    week_chg_pct: float | None = None
    month_chg_pct: float | None = None
    vs_bench_1m_pct: float | None = None
    score: float = 0.0
    held: bool = False
    notes: list[str] = field(default_factory=list)


class EtfTrackerExpert(BaseExpert):
    def __init__(
        self,
        *,
        pipeline_context: dict[str, Any] | None = None,
        delay_seconds: float = 0.25,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="etf-tracker")
        self.delay_seconds = delay_seconds

    def _held_etfs(self) -> set[str]:
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
                if not sym:
                    continue
                if sym in ETF_CATALOG:
                    held.add(sym)
                    continue
                # Common 3–4 letter ETFs already in catalog; skip stock names
        return held

    @staticmethod
    def _pct(closes: list[float], lookback: int) -> float | None:
        if len(closes) <= lookback or closes[-1 - lookback] == 0:
            return None
        return round((closes[-1] / closes[-1 - lookback] - 1.0) * 100.0, 3)

    def analyze(self) -> dict[str, Any]:
        held = self._held_etfs()
        catalog = dict(ETF_CATALOG)
        for sym in held:
            catalog.setdefault(
                sym,
                {"category": "held_etf", "benchmark": "SPY", "label": f"Held ETF {sym}"},
            )

        # Cache benchmark closes
        bench_needed = {meta["benchmark"] for meta in catalog.values()}
        bench_needed.update({"SPY", "BND", "QQQ"})
        bench_closes: dict[str, list[float]] = {}
        errors: list[str] = []
        for b in bench_needed:
            try:
                c = self.fetch_yahoo_closes(b, range_="1y", interval="1d")
                if len(c) >= 25:
                    bench_closes[b] = c
            except Exception as exc:
                errors.append(f"bench {b}: {exc}")

        rows: list[EtfSnapshot] = []
        for sym, meta in catalog.items():
            if self.pipeline_should_skip_symbol(sym):
                continue
            try:
                closes = self.fetch_yahoo_closes(sym, range_="1y", interval="1d")
            except Exception as exc:
                errors.append(f"{sym}: {exc}")
                continue
            if len(closes) < 25:
                errors.append(f"{sym}: insufficient bars")
                continue
            month = self._pct(closes, 21)
            week = self._pct(closes, 5)
            day = self._pct(closes, 1)
            bench = meta.get("benchmark") or "SPY"
            bc = bench_closes.get(bench) or bench_closes.get("SPY")
            bench_m = self._pct(bc, 21) if bc else None
            vs = None
            if month is not None and bench_m is not None and bench != sym:
                vs = round(month - bench_m, 3)
            elif month is not None and bench == sym:
                vs = 0.0

            score = 50.0
            if month is not None:
                score += max(-18.0, min(18.0, month * 1.5))
            if vs is not None:
                score += max(-12.0, min(12.0, vs * 1.2))
            if week is not None:
                score += max(-6.0, min(6.0, week * 0.8))
            notes: list[str] = []
            if vs is not None and vs > 1.5:
                notes.append(f"Beating {bench} over ~1m")
            if vs is not None and vs < -1.5:
                notes.append(f"Trailing {bench} over ~1m")
            cat = meta["category"]
            if cat.startswith("bond") and month is not None and month < -2:
                notes.append("Bond ETF duration/credit pressure")
            if cat.startswith("sector") and vs is not None and vs > 2:
                notes.append("Sector leadership vs broad equity")

            rows.append(
                EtfSnapshot(
                    symbol=sym,
                    label=meta["label"],
                    category=cat,
                    benchmark=bench,
                    last=round(closes[-1], 4),
                    day_chg_pct=day,
                    week_chg_pct=week,
                    month_chg_pct=month,
                    vs_bench_1m_pct=vs,
                    score=round(score * self.pipeline_symbol_confidence_factor(sym), 2),
                    held=sym in held,
                    notes=notes,
                )
            )

        rows.sort(key=lambda r: r.score, reverse=True)

        # Category leaders
        by_cat: dict[str, list[EtfSnapshot]] = {}
        for r in rows:
            by_cat.setdefault(r.category, []).append(r)
        category_leaders = {
            cat: max(items, key=lambda x: x.score).symbol
            for cat, items in by_cat.items()
            if items
        }

        equity_etfs = [r for r in rows if not r.category.startswith("bond") and "commodity" not in r.category]
        bond_etfs = [r for r in rows if r.category.startswith("bond")]
        eq_avg = (
            sum(r.month_chg_pct or 0 for r in equity_etfs) / len(equity_etfs)
            if equity_etfs
            else 0.0
        )
        bond_avg = (
            sum(r.month_chg_pct or 0 for r in bond_etfs) / len(bond_etfs)
            if bond_etfs
            else 0.0
        )

        if eq_avg > 1.0 and eq_avg > bond_avg:
            direction = "BULLISH"
            regime = "etf_risk_on"
        elif eq_avg < -1.0 and bond_avg > eq_avg:
            direction = "BEARISH"
            regime = "etf_defensive_rotation"
        else:
            direction = "NEUTRAL"
            regime = "etf_mixed"

        leaders = [r.symbol for r in rows[:8]]
        laggards = [r.symbol for r in rows[-5:]]
        held_rows = [r for r in rows if r.held]

        recs = [
            f"ETF regime: {regime} (equity ETF 1m avg {eq_avg:.2f}% / bond ETF avg {bond_avg:.2f}%).",
            f"Top vehicles by score: {', '.join(leaders)}.",
            f"Category leaders: "
            + ", ".join(f"{c}={s}" for c, s in list(category_leaders.items())[:10])
            + ".",
        ]
        if held_rows:
            recs.append(
                "Held ETFs: "
                + ", ".join(f"{r.symbol}({r.category},{r.score:.0f})" for r in held_rows[:12])
            )
        if direction == "BULLISH":
            recs.append("Implementation: keep equity beta ETFs; add sector/factor leaders with RS confirmation.")
        elif direction == "BEARISH":
            recs.append("Implementation: raise bond/t-bill ETF weight; cut high-beta sector ETFs.")
        else:
            recs.append("Implementation: barbell core SPY/BND; satellite only into clear category leaders.")
        recs = self.append_memory_recommendations(recs)

        conf = 0.48 + min(0.25, abs(eq_avg - bond_avg) / 12.0)

        return {
            "status": "ok" if rows else "degraded",
            "regime": regime,
            "equity_etf_1m_avg_pct": round(eq_avg, 3),
            "bond_etf_1m_avg_pct": round(bond_avg, 3),
            "etfs": [asdict(r) for r in rows],
            "category_leaders": category_leaders,
            "leaders": leaders,
            "laggards": laggards,
            "held_count": len(held_rows),
            "playbook": ETF_PLAYBOOK,
            "recommendations": recs,
            "errors": errors[:20],
            "related_agents": ["etf-mechanics", "bond-markets", "equity-tracker", "sector-rotation"],
            "signal": {
                "direction": direction,
                "confidence": round(min(0.88, conf), 3),
                "horizon": self.preferred_horizon() or "1wk",
            },
            "tickers_bullish": leaders[:6],
            "tickers_bearish": laggards[:4],
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        body = self.analyze()
        payload = {
            "agent": "etf-tracker",
            "label": "ETF Tracker & Vehicle Structure Expert",
            "temperature": self.temperature,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "Yahoo Finance ETF universe + account_snapshot",
            "dashboard": DASHBOARD_URL,
            "domain": "etfs",
            **body,
        }
        try:
            from agent_groups import apply_group_conduct_to_report

            payload = apply_group_conduct_to_report(payload, "etf-tracker")
        except Exception:
            pass
        out = output or DEFAULT_OUTPUT
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload


def run_etf_tracker_analysis(
    output: Path | None = None,
    pipeline_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return EtfTrackerExpert(pipeline_context=pipeline_context).run(output=output)
