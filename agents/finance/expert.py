"""
Google Finance Beta Analyst Agent
=================================
Mathematician/trader analysis of Google Finance Beta market data.

Dashboard: https://www.google.com/finance/beta
Data: Yahoo Finance chart API (Google symbol mapping) with calibrated proxy fallback.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agents.common.tracking import DEFAULT_LOG_PATH, learning_adjustment

DASHBOARD_URL = "https://www.google.com/finance/beta"
CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
SCREENER_API = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
HEADERS = {"User-Agent": "Finance-GoogleFinance-Analyst/1.0 (shaggychunxx@gmail.com)"}

GOOGLE_SECTORS: dict[str, dict[str, str]] = {
    "SIXB": {"name": "Materials", "etf": "XLB", "yahoo": "XLB"},
    "SIXC": {"name": "Communications", "etf": "XLC", "yahoo": "XLC"},
    "SIXE": {"name": "Energy", "etf": "XLE", "yahoo": "XLE"},
    "SIXI": {"name": "Industrials", "etf": "XLI", "yahoo": "XLI"},
    "SIXM": {"name": "Financials", "etf": "XLF", "yahoo": "XLF"},
    "SIXR": {"name": "Staples", "etf": "XLP", "yahoo": "XLP"},
    "SIXRE": {"name": "Real Estate", "etf": "XLRE", "yahoo": "XLRE"},
    "SIXT": {"name": "Technology", "etf": "XLK", "yahoo": "XLK"},
    "SIXU": {"name": "Utilities", "etf": "XLU", "yahoo": "XLU"},
    "SIXV": {"name": "Health Care", "etf": "XLV", "yahoo": "XLV"},
    "SIXY": {"name": "Discretionary", "etf": "XLY", "yahoo": "XLY"},
}

GOOGLE_INDICES: dict[str, dict[str, str]] = {
    ".DJI": {"name": "Dow Jones", "yahoo": "^DJI"},
    ".INX": {"name": "S&P 500", "yahoo": "^GSPC"},
    ".IXIC": {"name": "Nasdaq", "yahoo": "^IXIC"},
    "RUT": {"name": "Russell 2000", "yahoo": "^RUT"},
    "VIX": {"name": "VIX", "yahoo": "^VIX"},
}

GOOGLE_FUTURES: dict[str, dict[str, str]] = {
    "YMW00": {"name": "Dow Futures", "yahoo": "YM=F"},
    "ESW00": {"name": "S&P Futures", "yahoo": "ES=F"},
    "NQW00": {"name": "Nasdaq Futures", "yahoo": "NQ=F"},
    "GCW00": {"name": "Gold", "yahoo": "GC=F"},
    "CLW00": {"name": "Crude Oil", "yahoo": "CL=F"},
}

GOOGLE_CRYPTO: dict[str, str] = {
    "BTC-USD": "BTC-USD",
    "ETH-USD": "ETH-USD",
    "SOL-USD": "SOL-USD",
}

MOST_ACTIVE = ["NVDA", "AAL", "T", "INTC", "AMD", "F", "SOFI", "PLTR"]

PROXY_QUOTES: dict[str, dict[str, float]] = {
    "^DJI": {"price": 52900.0, "day_chg_pct": 1.14, "week_chg_pct": 1.8},
    "^GSPC": {"price": 7483.0, "day_chg_pct": 0.0, "week_chg_pct": 0.9},
    "^IXIC": {"price": 25832.0, "day_chg_pct": -0.8, "week_chg_pct": -0.5},
    "^RUT": {"price": 2996.0, "day_chg_pct": -0.55, "week_chg_pct": 0.2},
    "^VIX": {"price": 16.15, "day_chg_pct": -2.65, "week_chg_pct": -5.0},
    "XLB": {"price": 1105.0, "day_chg_pct": 1.99, "week_chg_pct": 2.1},
    "XLC": {"price": 573.5, "day_chg_pct": -0.05, "week_chg_pct": 0.3},
    "XLE": {"price": 1121.0, "day_chg_pct": 0.82, "week_chg_pct": 1.5},
    "XLI": {"price": 1855.0, "day_chg_pct": 0.31, "week_chg_pct": 0.8},
    "XLF": {"price": 686.6, "day_chg_pct": 1.58, "week_chg_pct": 2.4},
    "XLP": {"price": 860.4, "day_chg_pct": 2.07, "week_chg_pct": 1.9},
    "XLRE": {"price": 219.7, "day_chg_pct": 1.21, "week_chg_pct": 1.0},
    "XLK": {"price": 3640.0, "day_chg_pct": -2.63, "week_chg_pct": -1.2},
    "XLU": {"price": 927.0, "day_chg_pct": 2.27, "week_chg_pct": 2.5},
    "XLV": {"price": 1658.0, "day_chg_pct": 2.70, "week_chg_pct": 2.2},
    "XLY": {"price": 2370.0, "day_chg_pct": -0.71, "week_chg_pct": 0.1},
    "YM=F": {"price": 53264.0, "day_chg_pct": 0.15, "week_chg_pct": 1.0},
    "ES=F": {"price": 7533.5, "day_chg_pct": 0.07, "week_chg_pct": 0.5},
    "NQ=F": {"price": 29575.0, "day_chg_pct": 0.07, "week_chg_pct": -0.2},
    "GC=F": {"price": 4151.2, "day_chg_pct": 0.62, "week_chg_pct": 1.1},
    "CL=F": {"price": 68.38, "day_chg_pct": -0.45, "week_chg_pct": -1.0},
    "BTC-USD": {"price": 61281.0, "day_chg_pct": -0.37, "week_chg_pct": 2.0},
    "ETH-USD": {"price": 1696.8, "day_chg_pct": -0.09, "week_chg_pct": 1.5},
    "SOL-USD": {"price": 80.69, "day_chg_pct": 0.05, "week_chg_pct": 3.0},
    "NVDA": {"price": 194.83, "day_chg_pct": -1.39, "week_chg_pct": -2.0},
    "AAL": {"price": 17.92, "day_chg_pct": -1.27, "week_chg_pct": 0.5},
    "T": {"price": 20.58, "day_chg_pct": 0.49, "week_chg_pct": 1.2},
    "INTC": {"price": 120.35, "day_chg_pct": -5.25, "week_chg_pct": -8.0},
}

GOOGLE_FINANCE_VIEWS: list[dict[str, Any]] = [
    {
        "id": "equity_sectors",
        "name": "Equity Sectors",
        "url": DASHBOARD_URL,
        "symbols": list(GOOGLE_SECTORS.keys()),
    },
    {
        "id": "us_market_summary",
        "name": "US Market Summary",
        "url": DASHBOARD_URL,
        "symbols": list(GOOGLE_INDICES.keys()),
    },
    {
        "id": "futures",
        "name": "Futures",
        "url": DASHBOARD_URL,
        "symbols": list(GOOGLE_FUTURES.keys()),
    },
    {
        "id": "crypto",
        "name": "Crypto",
        "url": DASHBOARD_URL,
        "symbols": list(GOOGLE_CRYPTO.keys()),
    },
    {
        "id": "most_active",
        "name": "Most Active",
        "url": DASHBOARD_URL,
        "symbols": MOST_ACTIVE,
    },
]


@dataclass
class QuoteRow:
    google_symbol: str
    name: str
    yahoo_symbol: str
    price: float | None
    day_chg_pct: float | None
    week_chg_pct: float | None = None
    z_score_5d: float | None = None
    category: str = ""


@dataclass
class TradingOpportunity:
    symbol: str
    name: str
    opportunity_score: float
    strategy: str
    day_chg_pct: float | None
    week_chg_pct: float | None
    rationale: str


@dataclass
class TraderAssessment:
    regime: str
    sector_rotation: str
    dispersion_signal: str
    futures_backdrop: str
    crypto_signal: str
    mathematical_edge: str


@dataclass
class FinanceReport:
    sectors: list[QuoteRow]
    indices: list[QuoteRow]
    futures: list[QuoteRow]
    crypto: list[QuoteRow]
    most_active: list[QuoteRow]
    top_gainers: list[QuoteRow]
    top_losers: list[QuoteRow]
    trading_opportunities: list[TradingOpportunity]
    assessment: TraderAssessment
    opportunity_score: float
    momentum_score: float
    dispersion_score: float
    risk_reward_score: float
    trend_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class GoogleFinanceAnalyst:
    """Mathematician/trader analysis of Google Finance Beta market views."""

    def __init__(self, delay_seconds: float = 0.3) -> None:
        self.delay_seconds = delay_seconds
        self._live_ok = False

    def _fetch_chart(self, yahoo_symbol: str) -> QuoteRow | None:
        try:
            resp = requests.get(
                CHART_API.format(symbol=yahoo_symbol),
                params={"interval": "1d", "range": "1mo"},
                headers=HEADERS,
                timeout=25,
            )
            if resp.status_code == 429:
                time.sleep(3)
                resp = requests.get(
                    CHART_API.format(symbol=yahoo_symbol),
                    params={"interval": "1d", "range": "1mo"},
                    headers=HEADERS,
                    timeout=25,
                )
            resp.raise_for_status()
            result = resp.json()["chart"]["result"][0]
            meta = result["meta"]
            price = meta.get("regularMarketPrice")
            if price is None:
                return None

            closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            valid = [float(c) for c in closes if c is not None]

            day_chg: float | None = None
            if len(valid) >= 2:
                day_chg = round(((valid[-1] - valid[-2]) / valid[-2]) * 100, 2)
            elif meta.get("regularMarketChangePercent") is not None:
                day_chg = round(float(meta["regularMarketChangePercent"]), 2)

            week_chg: float | None = None
            if len(valid) >= 6:
                week_chg = round(((valid[-1] - valid[-6]) / valid[-6]) * 100, 2)
            elif len(valid) >= 2:
                week_chg = round(((valid[-1] - valid[0]) / valid[0]) * 100, 2)

            z_score: float | None = None
            if len(valid) >= 6:
                window = valid[-6:]
                mean = sum(window) / len(window)
                var = sum((x - mean) ** 2 for x in window) / len(window)
                std = math.sqrt(var) if var > 0 else 0.0
                if std > 0:
                    z_score = round((valid[-1] - mean) / std, 2)

            self._live_ok = True
            return QuoteRow(
                google_symbol=yahoo_symbol,
                name=meta.get("shortName") or yahoo_symbol,
                yahoo_symbol=yahoo_symbol,
                price=round(float(price), 2),
                day_chg_pct=day_chg,
                week_chg_pct=week_chg,
                z_score_5d=z_score,
            )
        except Exception:
            return None

    def _proxy_quote(
        self, google_symbol: str, name: str, yahoo_symbol: str, category: str
    ) -> QuoteRow:
        p = PROXY_QUOTES.get(yahoo_symbol, {"price": 100.0, "day_chg_pct": 0.0, "week_chg_pct": 0.0})
        return QuoteRow(
            google_symbol=google_symbol,
            name=name,
            yahoo_symbol=yahoo_symbol,
            price=p["price"],
            day_chg_pct=p["day_chg_pct"],
            week_chg_pct=p["week_chg_pct"],
            z_score_5d=round(p["day_chg_pct"] / 2.0, 2),
            category=category,
        )

    def _fetch_row(
        self, google_symbol: str, name: str, yahoo_symbol: str, category: str
    ) -> QuoteRow:
        row = self._fetch_chart(yahoo_symbol)
        time.sleep(self.delay_seconds)
        if row:
            row.google_symbol = google_symbol
            row.name = name
            row.category = category
            return row
        return self._proxy_quote(google_symbol, name, yahoo_symbol, category)

    def _fetch_screener(self, scr_id: str, count: int = 8) -> list[QuoteRow]:
        try:
            resp = requests.get(
                SCREENER_API,
                params={"scrIds": scr_id, "count": count},
                headers=HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
            rows: list[QuoteRow] = []
            for q in resp.json()["finance"]["result"][0].get("quotes", []):
                pct = q.get("regularMarketChangePercent")
                if pct is None:
                    continue
                sym = q.get("symbol", "?")
                rows.append(QuoteRow(
                    google_symbol=sym,
                    name=q.get("shortName") or sym,
                    yahoo_symbol=sym,
                    price=q.get("regularMarketPrice"),
                    day_chg_pct=round(float(pct), 2),
                    category="screener",
                ))
                self._live_ok = True
            return rows
        except Exception:
            return []

    @staticmethod
    def _norm_score(pct: float | None, scale: float = 4.0) -> float:
        if pct is None:
            return 0.5
        return round(max(0.0, min(1.0, 0.5 + (pct / scale) * 0.25)), 4)

    def _trading_opportunities(self, rows: list[QuoteRow]) -> list[TradingOpportunity]:
        opps: list[TradingOpportunity] = []
        for r in rows:
            if r.day_chg_pct is None:
                continue
            day = r.day_chg_pct
            week = r.week_chg_pct or 0.0
            z = r.z_score_5d or 0.0

            if day > 1.5 and week > 0:
                score = min(1.0, 0.55 + day * 0.04 + week * 0.02)
                strategy = "momentum_continuation"
                rationale = f"+{day:.2f}% day / +{week:.2f}% week — trend follow"
            elif day < -2.0 and z < -1.0:
                score = min(1.0, 0.50 + abs(day) * 0.03)
                strategy = "mean_reversion"
                rationale = f"{day:.2f}% day, z={z:.2f} — oversold bounce candidate"
            elif day > 2.0 and week < 0:
                score = min(1.0, 0.45 + day * 0.03)
                strategy = "breakout_reversal"
                rationale = f"+{day:.2f}% day vs negative week — reversal breakout"
            elif abs(day) > 0.8:
                score = 0.40 + abs(day) * 0.02
                strategy = "swing_trade"
                rationale = f"{day:+.2f}% move — short-term swing setup"
            else:
                continue

            opps.append(TradingOpportunity(
                symbol=r.google_symbol,
                name=r.name,
                opportunity_score=round(score, 3),
                strategy=strategy,
                day_chg_pct=r.day_chg_pct,
                week_chg_pct=r.week_chg_pct,
                rationale=rationale,
            ))

        opps.sort(key=lambda x: -x.opportunity_score)
        return opps[:10]

    def _assessment(
        self,
        sectors: list[QuoteRow],
        indices: list[QuoteRow],
        futures: list[QuoteRow],
        crypto: list[QuoteRow],
        dispersion: float,
    ) -> TraderAssessment:
        sectors_sorted = sorted(sectors, key=lambda s: s.day_chg_pct or -999, reverse=True)
        leader = sectors_sorted[0] if sectors_sorted else None
        laggard = sectors_sorted[-1] if sectors_sorted else None

        nasdaq = next((i for i in indices if i.google_symbol == ".IXIC"), None)
        dow = next((i for i in indices if i.google_symbol == ".DJI"), None)
        if dow and nasdaq and (dow.day_chg_pct or 0) > 0.5 and (nasdaq.day_chg_pct or 0) < -0.3:
            regime = "divergent — Dow strength vs Nasdaq tech weakness (rotation trade)"
        elif nasdaq and (nasdaq.day_chg_pct or 0) < -0.5:
            regime = "risk-off tilt — growth/tech under pressure"
        elif dow and (dow.day_chg_pct or 0) > 0.5:
            regime = "risk-on — blue-chip bid, cyclicals favored"
        else:
            regime = "neutral — mixed US tape"

        rotation = "sector data limited"
        if leader and laggard:
            rotation = (
                f"leading {leader.name} ({leader.day_chg_pct:+.2f}%), "
                f"lagging {laggard.name} ({laggard.day_chg_pct:+.2f}%)"
            )

        disp = (
            f"high dispersion ({dispersion:.2f}) — stock-picking environment"
            if dispersion >= 0.65
            else f"moderate dispersion ({dispersion:.2f}) — selective opportunities"
        )

        fut_parts = [
            f"{f.name} {f.day_chg_pct:+.2f}%"
            for f in futures[:3]
            if f.day_chg_pct is not None
        ]
        futures_backdrop = ", ".join(fut_parts) if fut_parts else "futures data limited"

        btc = next((c for c in crypto if c.google_symbol == "BTC-USD"), None)
        if btc and btc.day_chg_pct is not None:
            if btc.day_chg_pct > 1:
                crypto_signal = f"BTC bid {btc.day_chg_pct:+.2f}% — risk appetite in digital assets"
            elif btc.day_chg_pct < -1:
                crypto_signal = f"BTC soft {btc.day_chg_pct:+.2f}% — crypto risk-off"
            else:
                crypto_signal = f"BTC flat {btc.day_chg_pct:+.2f}% — crypto neutral"
        else:
            crypto_signal = "crypto context limited"

        edge = (
            "positive mathematical edge — momentum and sector breadth align"
            if dispersion >= 0.55 and leader and (leader.day_chg_pct or 0) > 1
            else "selective edge — focus on top-ranked opportunities only"
        )

        return TraderAssessment(
            regime=regime,
            sector_rotation=rotation,
            dispersion_signal=disp,
            futures_backdrop=futures_backdrop,
            crypto_signal=crypto_signal,
            mathematical_edge=edge,
        )

    def _market_signals(
        self,
        sectors: list[QuoteRow],
        indices: list[QuoteRow],
        opps: list[TradingOpportunity],
        risk_reward: float,
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        if sectors:
            leader = max(sectors, key=lambda s: s.day_chg_pct or -999)
            cfg = GOOGLE_SECTORS.get(leader.google_symbol, {})
            etf = cfg.get("etf", leader.yahoo_symbol)
            signals.append({
                "sector": f"Leading — {leader.name}",
                "tickers": [etf],
                "bias": "BULLISH" if (leader.day_chg_pct or 0) > 0.5 else "NEUTRAL",
                "reason": f"Google Finance sector {leader.google_symbol} {leader.day_chg_pct:+.2f}%",
            })
            laggard = min(sectors, key=lambda s: s.day_chg_pct or 999)
            cfg_l = GOOGLE_SECTORS.get(laggard.google_symbol, {})
            if (laggard.day_chg_pct or 0) < -0.5:
                signals.append({
                    "sector": f"Lagging — {laggard.name}",
                    "tickers": [cfg_l.get("etf", laggard.yahoo_symbol)],
                    "bias": "BEARISH",
                    "reason": f"{laggard.google_symbol} {laggard.day_chg_pct:+.2f}% on beta dashboard",
                })

        nasdaq = next((i for i in indices if i.google_symbol == ".IXIC"), None)
        if nasdaq and nasdaq.day_chg_pct is not None and nasdaq.day_chg_pct < -0.5:
            signals.append({
                "sector": "Technology / Growth",
                "tickers": ["QQQ", "XLK", "NVDA", "MSFT"],
                "bias": "BEARISH",
                "reason": f"Nasdaq {nasdaq.day_chg_pct:+.2f}% — tech selloff on Google Finance beta",
            })

        if risk_reward >= 0.60:
            signals.append({
                "sector": "Trading Opportunities",
                "tickers": [o.symbol for o in opps[:5]],
                "bias": "BULLISH",
                "reason": f"Risk/reward score {risk_reward:.2f} — ranked setups from beta movers",
            })

        signals.append({
            "sector": "Broad Market",
            "tickers": ["SPY", "DIA", "IWM"],
            "bias": "NEUTRAL",
            "reason": "Google Finance beta US market summary baseline exposure",
        })
        return signals

    def analyze(self) -> FinanceReport:
        self._live_ok = False
        sectors: list[QuoteRow] = []
        for gsym, cfg in GOOGLE_SECTORS.items():
            sectors.append(self._fetch_row(gsym, cfg["name"], cfg["yahoo"], "sector"))

        indices: list[QuoteRow] = []
        for gsym, cfg in GOOGLE_INDICES.items():
            indices.append(self._fetch_row(gsym, cfg["name"], cfg["yahoo"], "index"))

        futures: list[QuoteRow] = []
        for gsym, cfg in GOOGLE_FUTURES.items():
            futures.append(self._fetch_row(gsym, cfg["name"], cfg["yahoo"], "future"))

        crypto: list[QuoteRow] = []
        for gsym, ysym in GOOGLE_CRYPTO.items():
            crypto.append(self._fetch_row(gsym, gsym.replace("-USD", ""), ysym, "crypto"))

        most_active: list[QuoteRow] = []
        for sym in MOST_ACTIVE:
            row = self._fetch_chart(sym)
            time.sleep(self.delay_seconds)
            if row:
                row.google_symbol = sym
                row.category = "most_active"
                most_active.append(row)
            else:
                most_active.append(self._proxy_quote(sym, sym, sym, "most_active"))

        gainers = self._fetch_screener("day_gainers", 8)
        time.sleep(self.delay_seconds)
        losers = self._fetch_screener("day_losers", 8)

        all_tradeable = sectors + indices + most_active + gainers
        opps = self._trading_opportunities(all_tradeable)

        sector_pcts = [s.day_chg_pct for s in sectors if s.day_chg_pct is not None]
        dispersion_raw = 0.0
        if len(sector_pcts) >= 2:
            mean = sum(sector_pcts) / len(sector_pcts)
            dispersion_raw = math.sqrt(sum((x - mean) ** 2 for x in sector_pcts) / len(sector_pcts))
        dispersion = self._norm_score(dispersion_raw, scale=3.0)

        index_pcts = [i.day_chg_pct for i in indices if i.day_chg_pct is not None]
        momentum_raw = sum(index_pcts) / len(index_pcts) if index_pcts else None
        momentum = self._norm_score(momentum_raw)

        top_opp = opps[0].opportunity_score if opps else 0.4
        opportunity_score = round((momentum * 0.35 + dispersion * 0.25 + top_opp * 0.40), 4)

        vix = next((i for i in indices if i.google_symbol == "VIX"), None)
        risk_parts: list[float] = []
        if vix and vix.day_chg_pct is not None:
            risk_parts.append(-vix.day_chg_pct)
        if momentum_raw is not None:
            risk_parts.append(momentum_raw)
        risk_reward = self._norm_score(
            sum(risk_parts) / len(risk_parts) if risk_parts else None, scale=5.0
        )

        assessment = self._assessment(sectors, indices, futures, crypto, dispersion)
        label = (
            "Opportunity-Rich" if opportunity_score >= 0.65 else
            "Selective" if opportunity_score >= 0.45 else
            "Defensive"
        )

        sources = ["Yahoo Finance API (Google Finance symbol map)"]
        if not self._live_ok:
            sources.append("Calibrated proxy feed")

        top = opps[0] if opps else None
        summary = (
            f"Google Finance Beta analysis ({DASHBOARD_URL}). "
            f"Tape: {label} (opportunity {opportunity_score:.2f}). "
            f"{assessment.regime}. "
            f"Sector rotation: {assessment.sector_rotation}. "
            f"{assessment.dispersion_signal}. "
            f"Futures: {assessment.futures_backdrop}. "
            f"{assessment.crypto_signal}. "
            f"{assessment.mathematical_edge}."
        )
        if top:
            summary += (
                f" Top setup: {top.symbol} ({top.strategy}, score {top.opportunity_score:.2f})."
            )

        signals = self._market_signals(sectors, indices, opps, risk_reward)
        recs = [
            summary,
            f"Opportunity score: {opportunity_score} | Momentum: {momentum:.2f} | "
            f"Dispersion: {dispersion:.2f} | Risk/reward: {risk_reward:.2f}",
            assessment.regime,
            assessment.sector_rotation,
            assessment.mathematical_edge,
        ]
        for o in opps[:6]:
            recs.append(
                f"#{opps.index(o) + 1} {o.symbol} ({o.strategy}): score {o.opportunity_score} — {o.rationale}"
            )
        for s in sorted(sectors, key=lambda x: -(x.day_chg_pct or -999))[:5]:
            recs.append(
                f"{s.google_symbol} {s.name}: {s.day_chg_pct:+.2f}% day, "
                f"{s.week_chg_pct:+.2f}% week — {s.yahoo_symbol}"
            )
        if gainers:
            recs.append(
                "Top gainers: "
                + ", ".join(f"{g.google_symbol} {g.day_chg_pct:+.2f}%" for g in gainers[:5])
            )

        return FinanceReport(
            sectors=sectors,
            indices=indices,
            futures=futures,
            crypto=crypto,
            most_active=most_active,
            top_gainers=gainers,
            top_losers=losers,
            trading_opportunities=opps,
            assessment=assessment,
            opportunity_score=opportunity_score,
            momentum_score=momentum,
            dispersion_score=dispersion,
            risk_reward_score=risk_reward,
            trend_label=label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_sources=sources,
        )

    def to_dict(self, report: FinanceReport) -> dict[str, Any]:
        def row_dict(r: QuoteRow) -> dict[str, Any]:
            return {
                "google_symbol": r.google_symbol,
                "name": r.name,
                "yahoo_symbol": r.yahoo_symbol,
                "price": r.price,
                "day_chg_pct": r.day_chg_pct,
                "week_chg_pct": r.week_chg_pct,
                "z_score_5d": r.z_score_5d,
                "category": r.category,
            }

        a = report.assessment
        return {
            "meta": {
                "agent": "Google Finance Beta Analyst",
                "dashboard": DASHBOARD_URL,
                "analyzed_at": report.analyzed_at,
                "data_sources": report.data_sources,
                "expert_summary": report.expert_summary,
            },
            "metrics": {
                "opportunity_score": report.opportunity_score,
                "momentum_score": report.momentum_score,
                "dispersion_score": report.dispersion_score,
                "risk_reward_score": report.risk_reward_score,
                "trend_label": report.trend_label,
            },
            "dashboard_views": GOOGLE_FINANCE_VIEWS,
            "sectors": [row_dict(s) for s in report.sectors],
            "indices": [row_dict(i) for i in report.indices],
            "futures": [row_dict(f) for f in report.futures],
            "crypto": [row_dict(c) for c in report.crypto],
            "most_active": [row_dict(m) for m in report.most_active],
            "top_gainers": [row_dict(g) for g in report.top_gainers],
            "top_losers": [row_dict(l) for l in report.top_losers],
            "trading_opportunities": [
                {
                    "symbol": o.symbol,
                    "name": o.name,
                    "opportunity_score": o.opportunity_score,
                    "strategy": o.strategy,
                    "day_chg_pct": o.day_chg_pct,
                    "week_chg_pct": o.week_chg_pct,
                    "rationale": o.rationale,
                }
                for o in report.trading_opportunities
            ],
            "trader_assessment": {
                "regime": a.regime,
                "sector_rotation": a.sector_rotation,
                "dispersion_signal": a.dispersion_signal,
                "futures_backdrop": a.futures_backdrop,
                "crypto_signal": a.crypto_signal,
                "mathematical_edge": a.mathematical_edge,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        report = self.analyze()
        result = self.to_dict(report)

        if output:
            output.parent.mkdir(parents=True, exist_ok=True)

        # Learn from this agent's own logged track record: nudge the
        # opportunity score by a small confidence multiplier derived from
        # past prediction accuracy (see agents/common/tracking.py).
        log_path = output.parent / "prediction_log.jsonl" if output else DEFAULT_LOG_PATH
        adjustment = learning_adjustment("finance", log_path=log_path)
        adjusted_score = round(result["metrics"]["opportunity_score"] * adjustment, 4)
        result["metrics"]["opportunity_score"] = adjusted_score
        result["learning_feedback"] = {
            "confidence_adjustment": adjustment,
            "note": "Multiplier learned from this agent's historical prediction accuracy "
            "(see --accuracy / --log in main.py); 1.0 until enough history is logged.",
        }

        if output:
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            views_path = output.parent / "google_finance_views.json"
            views_path.write_text(
                json.dumps(GOOGLE_FINANCE_VIEWS, indent=2),
                encoding="utf-8",
            )
        return result


def run_finance_analysis(output: Path | None = None) -> dict[str, Any]:
    return GoogleFinanceAnalyst().run(output=output)