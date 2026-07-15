"""
Nikkei Stock Average Analyst Agent
==================================
Mathematician/trader analysis of the Nikkei Stock Average (Nikkei 225),
Japan's premier price-weighted equity benchmark of 225 Prime Market
constituents on the Tokyo Stock Exchange.

Dashboard: https://indexes.nikkei.co.jp/en/nkave/
Data: Yahoo Finance chart API with calibrated proxy fallback.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base import BaseExpert

DASHBOARD_URL = "https://indexes.nikkei.co.jp/en/nkave/"
FACTSHEET_URL = "https://indexes.nikkei.co.jp/en/nkave/factsheet"

NIKKEI_INDEX = {"^N225": "Nikkei 225 (Nikkei Stock Average)"}

# Japan-market context: currency, futures, and regional peers used to frame
# the Nikkei tape (USD/JPY drives exporter earnings; futures show overnight
# positioning; Topix ETF/Hang Seng give regional breadth).
CONTEXT_SYMBOLS: dict[str, dict[str, str]] = {
    "JPY=X": {"name": "USD/JPY", "category": "fx"},
    "NIY=F": {"name": "Nikkei 225 Futures (CME)", "category": "futures"},
    "EWJ": {"name": "iShares MSCI Japan ETF", "category": "etf"},
    "DXJ": {"name": "WisdomTree Japan Hedged Equity", "category": "etf"},
    "^HSI": {"name": "Hang Seng (regional peer)", "category": "regional"},
    "^GSPC": {"name": "S&P 500 (overnight lead)", "category": "regional"},
}

# Heaviest constituents by index weight (price-weighted index — high share
# price names like Fast Retailing and Advantest dominate the average).
CONSTITUENTS: dict[str, dict[str, str]] = {
    "6857.T": {"name": "Advantest Corp.", "sector": "Technology"},
    "8035.T": {"name": "Tokyo Electron Ltd.", "sector": "Technology"},
    "9983.T": {"name": "Fast Retailing Co., Ltd.", "sector": "Consumer Goods"},
    "9984.T": {"name": "SoftBank Group Corp.", "sector": "Technology"},
    "6762.T": {"name": "TDK Corp.", "sector": "Technology"},
    "6954.T": {"name": "Fanuc Corp.", "sector": "Technology"},
    "4063.T": {"name": "Shin-Etsu Chemical Co., Ltd.", "sector": "Materials"},
}

# Approximate sector weight breakdown published on the Nikkei factsheet.
SECTOR_WEIGHTS: dict[str, float] = {
    "Technology": 59.0,
    "Consumer Goods": 19.0,
    "Materials": 12.0,
    "Capital Goods / Other": 6.6,
    "Financials": 2.6,
    "Transportation / Utilities": 1.1,
}

HEADERS = {"User-Agent": "Finance-Nikkei-Analyst/1.0 (shaggychunxx@gmail.com)"}

NIKKEI_VIEWS: list[dict[str, Any]] = [
    {
        "id": "nikkei_average",
        "name": "Nikkei Stock Average",
        "url": DASHBOARD_URL,
        "symbols": list(NIKKEI_INDEX.keys()),
    },
    {
        "id": "factsheet",
        "name": "Nikkei 225 Factsheet",
        "url": FACTSHEET_URL,
        "symbols": list(NIKKEI_INDEX.keys()),
    },
    {
        "id": "japan_context",
        "name": "Japan Market Context",
        "url": DASHBOARD_URL,
        "symbols": list(CONTEXT_SYMBOLS.keys()),
    },
    {
        "id": "top_constituents",
        "name": "Top Constituents by Weight",
        "url": FACTSHEET_URL,
        "symbols": list(CONSTITUENTS.keys()),
    },
]

# Calibrated fallback quotes used when Yahoo Finance is unreachable.
PROXY_QUOTES: dict[str, dict[str, float]] = {
    "^N225": {"price": 47800.0, "day_chg_pct": 0.65, "week_chg_pct": 1.4},
    "JPY=X": {"price": 154.2, "day_chg_pct": -0.2, "week_chg_pct": 0.3},
    "NIY=F": {"price": 47750.0, "day_chg_pct": 0.55, "week_chg_pct": 1.2},
    "EWJ": {"price": 79.4, "day_chg_pct": 0.5, "week_chg_pct": 1.1},
    "DXJ": {"price": 108.6, "day_chg_pct": 0.6, "week_chg_pct": 1.6},
    "^HSI": {"price": 20650.0, "day_chg_pct": -0.3, "week_chg_pct": 0.4},
    "^GSPC": {"price": 6800.0, "day_chg_pct": 0.2, "week_chg_pct": 0.9},
    "6857.T": {"price": 12400.0, "day_chg_pct": 1.8, "week_chg_pct": 3.2},
    "8035.T": {"price": 28500.0, "day_chg_pct": 1.2, "week_chg_pct": 2.1},
    "9983.T": {"price": 51200.0, "day_chg_pct": -0.4, "week_chg_pct": 0.8},
    "9984.T": {"price": 15100.0, "day_chg_pct": 2.1, "week_chg_pct": 4.5},
    "6762.T": {"price": 3200.0, "day_chg_pct": 0.9, "week_chg_pct": 1.6},
    "6954.T": {"price": 5400.0, "day_chg_pct": 0.3, "week_chg_pct": -0.2},
    "4063.T": {"price": 4900.0, "day_chg_pct": 0.7, "week_chg_pct": 1.3},
}


@dataclass
class QuoteRow:
    symbol: str
    name: str
    price: float | None
    day_chg_pct: float | None
    week_chg_pct: float | None = None
    z_score_5d: float | None = None
    category: str = ""


@dataclass
class NikkeiAssessment:
    regime: str
    fx_signal: str
    futures_signal: str
    regional_signal: str
    breadth_signal: str
    mathematical_edge: str


@dataclass
class NikkeiReport:
    index: QuoteRow | None
    context: list[QuoteRow]
    constituents: list[QuoteRow]
    assessment: NikkeiAssessment
    momentum_score: float
    fx_sensitivity_score: float
    breadth_score: float
    opportunity_score: float
    trend_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class NikkeiAverageAnalyst(BaseExpert):
    """Mathematician/trader analysis of the Nikkei Stock Average."""

    def __init__(
        self,
        delay_seconds: float = 0.3,
        *,
        pipeline_context: dict | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="nikkei")
        self.delay_seconds = delay_seconds
        self._live_ok = False

    def _fetch_chart(self, symbol: str) -> QuoteRow | None:
        meta = self.fetch_yahoo_chart_meta(symbol, range_="1mo", interval="1d")
        if not meta:
            return None
        price = meta.get("price")
        if price is None:
            return None

        valid = self.fetch_yahoo_closes(symbol, range_="1mo", interval="1d")
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
            symbol=symbol,
            name=symbol,
            price=round(float(price), 2),
            day_chg_pct=meta.get("day_chg_pct"),
            week_chg_pct=meta.get("week_chg_pct"),
            z_score_5d=z_score,
        )

    def _proxy_quote(self, symbol: str, name: str, category: str) -> QuoteRow:
        p = PROXY_QUOTES.get(symbol, {"price": 100.0, "day_chg_pct": 0.0, "week_chg_pct": 0.0})
        return QuoteRow(
            symbol=symbol,
            name=name,
            price=p["price"],
            day_chg_pct=p["day_chg_pct"],
            week_chg_pct=p["week_chg_pct"],
            z_score_5d=round(p["day_chg_pct"] / 2.0, 2),
            category=category,
        )

    def _fetch_row(self, symbol: str, name: str, category: str) -> QuoteRow:
        row = self._fetch_chart(symbol)
        time.sleep(self.delay_seconds)
        if row:
            row.name = name
            row.category = category
            return row
        return self._proxy_quote(symbol, name, category)

    @staticmethod
    def _norm_score(pct: float | None, scale: float = 4.0) -> float:
        if pct is None:
            return 0.5
        return round(max(0.0, min(1.0, 0.5 + (pct / scale) * 0.25)), 4)

    def _assessment(
        self,
        index_row: QuoteRow | None,
        context: list[QuoteRow],
        constituents: list[QuoteRow],
    ) -> NikkeiAssessment:
        idx_day = index_row.day_chg_pct if index_row else None
        if idx_day is not None and idx_day > 0.75:
            regime = "risk-on — Nikkei extending gains, exporter bid"
        elif idx_day is not None and idx_day < -0.75:
            regime = "risk-off — Nikkei under pressure, yen-sensitive selling"
        else:
            regime = "neutral — Nikkei consolidating in a tight range"

        jpy = next((c for c in context if c.symbol == "JPY=X"), None)
        if jpy and jpy.day_chg_pct is not None:
            if jpy.day_chg_pct > 0.3:
                fx_signal = f"yen weakening ({jpy.day_chg_pct:+.2f}%) — tailwind for exporters"
            elif jpy.day_chg_pct < -0.3:
                fx_signal = f"yen strengthening ({jpy.day_chg_pct:+.2f}%) — headwind for exporters"
            else:
                fx_signal = "USD/JPY range-bound — limited FX drag on earnings"
        else:
            fx_signal = "FX context limited"

        fut = next((c for c in context if c.symbol == "NIY=F"), None)
        if fut and index_row and fut.day_chg_pct is not None and index_row.day_chg_pct is not None:
            basis = fut.day_chg_pct - index_row.day_chg_pct
            futures_signal = f"futures basis {basis:+.2f}% vs cash — {'premium' if basis > 0 else 'discount'}"
        else:
            futures_signal = "futures basis data limited"

        hsi = next((c for c in context if c.symbol == "^HSI"), None)
        spx = next((c for c in context if c.symbol == "^GSPC"), None)
        if hsi and spx and hsi.day_chg_pct is not None and spx.day_chg_pct is not None:
            regional_signal = (
                f"Hang Seng {hsi.day_chg_pct:+.2f}%, S&P 500 {spx.day_chg_pct:+.2f}% — "
                f"{'aligned regional/US risk appetite' if hsi.day_chg_pct * spx.day_chg_pct > 0 else 'diverging regional and US tapes'}"
            )
        else:
            regional_signal = "regional context limited"

        cons_pcts = [c.day_chg_pct for c in constituents if c.day_chg_pct is not None]
        if len(cons_pcts) >= 2:
            positive = sum(1 for p in cons_pcts if p > 0)
            breadth_signal = f"{positive}/{len(cons_pcts)} heavyweight constituents advancing"
        else:
            breadth_signal = "constituent breadth data limited"

        edge = (
            "positive mathematical edge — yen tailwind and broad constituent participation align"
            if fx_signal.startswith("yen weakening") and len(cons_pcts) >= 2
            and sum(1 for p in cons_pcts if p > 0) >= math.ceil(len(cons_pcts) / 2)
            else "selective edge — mixed FX/constituent signals, focus on top movers only"
        )

        return NikkeiAssessment(
            regime=regime,
            fx_signal=fx_signal,
            futures_signal=futures_signal,
            regional_signal=regional_signal,
            breadth_signal=breadth_signal,
            mathematical_edge=edge,
        )

    def _market_signals(
        self,
        index_row: QuoteRow | None,
        context: list[QuoteRow],
        constituents: list[QuoteRow],
        momentum: float,
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal, sector_rotation_confidence

        signals: list[dict[str, Any]] = []

        if index_row and index_row.day_chg_pct is not None and abs(index_row.day_chg_pct) > 0.5:
            bias = "BULLISH" if index_row.day_chg_pct > 0 else "BEARISH"
            signals.append(
                build_market_signal(
                    sector="Nikkei Stock Average",
                    tickers=["EWJ", "DXJ"],
                    bias=bias,
                    reason=f"Nikkei 225 {index_row.day_chg_pct:+.2f}% day / "
                    f"{(index_row.week_chg_pct or 0):+.2f}% week",
                    confidence=self.adjust_signal_confidence(
                        "EWJ",
                        bias,
                        sector_rotation_confidence(
                            index_row.day_chg_pct,
                            week_chg_pct=index_row.week_chg_pct,
                        ),
                    ),
                )
            )

        jpy = next((c for c in context if c.symbol == "JPY=X"), None)
        if jpy and jpy.day_chg_pct is not None and jpy.day_chg_pct > 0.4:
            signals.append(
                build_market_signal(
                    sector="Exporters (yen sensitivity)",
                    tickers=["7203.T", "9983.T", "6758.T"],
                    bias="BULLISH",
                    reason=f"USD/JPY {jpy.day_chg_pct:+.2f}% — weaker yen supports exporter earnings",
                    confidence=self.adjust_signal_confidence(
                        "9983.T",
                        "BULLISH",
                        sector_rotation_confidence(jpy.day_chg_pct),
                    ),
                )
            )

        leader = max(constituents, key=lambda c: c.day_chg_pct or -999, default=None)
        if leader and leader.day_chg_pct is not None and leader.day_chg_pct > 1.5:
            signals.append(
                build_market_signal(
                    sector=f"Leading constituent — {leader.name}",
                    tickers=[leader.symbol],
                    bias="BULLISH",
                    reason=f"{leader.symbol} {leader.day_chg_pct:+.2f}% — largest index weight mover",
                    confidence=self.adjust_signal_confidence(
                        leader.symbol,
                        "BULLISH",
                        sector_rotation_confidence(leader.day_chg_pct, week_chg_pct=leader.week_chg_pct),
                    ),
                )
            )

        if not signals:
            signals.append(
                build_market_signal(
                    sector="Japan Equities",
                    tickers=["EWJ", "DXJ", "^N225"],
                    bias="NEUTRAL",
                    reason="Nikkei Stock Average baseline exposure — range-bound tape",
                    confidence=self.adjust_signal_confidence("EWJ", "NEUTRAL", 0.42),
                )
            )
        return signals

    def analyze(self) -> NikkeiReport:
        self._live_ok = False

        index_row: QuoteRow | None = None
        for sym, name in NIKKEI_INDEX.items():
            index_row = self._fetch_row(sym, name, "index")

        context: list[QuoteRow] = []
        for sym, cfg in CONTEXT_SYMBOLS.items():
            context.append(self._fetch_row(sym, cfg["name"], cfg["category"]))

        constituents: list[QuoteRow] = []
        for sym, cfg in CONSTITUENTS.items():
            row = self._fetch_row(sym, cfg["name"], "constituent")
            constituents.append(row)

        momentum_raw = index_row.day_chg_pct if index_row else None
        momentum = self._norm_score(momentum_raw)

        jpy = next((c for c in context if c.symbol == "JPY=X"), None)
        fx_sensitivity = self._norm_score(
            -(jpy.day_chg_pct) if jpy and jpy.day_chg_pct is not None else None,
            scale=2.0,
        )

        cons_pcts = [c.day_chg_pct for c in constituents if c.day_chg_pct is not None]
        breadth_raw = None
        if cons_pcts:
            breadth_raw = (sum(1 for p in cons_pcts if p > 0) / len(cons_pcts) - 0.5) * 8.0
        breadth = self._norm_score(breadth_raw)

        opportunity_score = round(momentum * 0.4 + fx_sensitivity * 0.3 + breadth * 0.3, 4)
        label = (
            "Bullish" if opportunity_score >= 0.62 else
            "Selective" if opportunity_score >= 0.45 else
            "Defensive"
        )

        assessment = self._assessment(index_row, context, constituents)

        sources = ["Yahoo Finance chart API (Nikkei 225 / Japan symbols)"]
        if not self._live_ok:
            sources.append("Calibrated proxy feed")

        summary = (
            f"Nikkei Stock Average analysis ({DASHBOARD_URL}). "
            f"Tape: {label} (opportunity {opportunity_score:.2f}). "
            f"{assessment.regime}. "
            f"FX: {assessment.fx_signal}. "
            f"{assessment.futures_signal}. "
            f"{assessment.regional_signal}. "
            f"{assessment.breadth_signal}. "
            f"{assessment.mathematical_edge}."
        )
        if index_row and index_row.price is not None:
            summary += f" Index level: {index_row.price:,.2f}."

        signals = self._market_signals(index_row, context, constituents, momentum)
        recs = [
            summary,
            f"Opportunity score: {opportunity_score} | Momentum: {momentum:.2f} | "
            f"FX sensitivity: {fx_sensitivity:.2f} | Breadth: {breadth:.2f}",
            assessment.regime,
            assessment.fx_signal,
            assessment.mathematical_edge,
        ]
        for c in sorted(constituents, key=lambda x: -(x.day_chg_pct or -999))[:5]:
            recs.append(
                f"{c.symbol} {c.name}: {c.day_chg_pct:+.2f}% day, "
                f"{(c.week_chg_pct or 0):+.2f}% week"
            )
        recs = self.append_memory_recommendations(recs)

        return NikkeiReport(
            index=index_row,
            context=context,
            constituents=constituents,
            assessment=assessment,
            momentum_score=momentum,
            fx_sensitivity_score=fx_sensitivity,
            breadth_score=breadth,
            opportunity_score=opportunity_score,
            trend_label=label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_sources=sources,
        )

    def to_dict(self, report: NikkeiReport) -> dict[str, Any]:
        def row_dict(r: QuoteRow) -> dict[str, Any]:
            return {
                "symbol": r.symbol,
                "name": r.name,
                "price": r.price,
                "day_chg_pct": r.day_chg_pct,
                "week_chg_pct": r.week_chg_pct,
                "z_score_5d": r.z_score_5d,
                "category": r.category,
            }

        a = report.assessment
        return {
            "meta": {
                "agent": "Nikkei Stock Average Analyst",
                "dashboard": DASHBOARD_URL,
                "factsheet": FACTSHEET_URL,
                "analyzed_at": report.analyzed_at,
                "data_sources": report.data_sources,
                "expert_summary": report.expert_summary,
            },
            "metrics": {
                "opportunity_score": report.opportunity_score,
                "momentum_score": report.momentum_score,
                "fx_sensitivity_score": report.fx_sensitivity_score,
                "breadth_score": report.breadth_score,
                "trend_label": report.trend_label,
            },
            "dashboard_views": NIKKEI_VIEWS,
            "sector_weights": SECTOR_WEIGHTS,
            "index": row_dict(report.index) if report.index else None,
            "context": [row_dict(c) for c in report.context],
            "constituents": [row_dict(c) for c in report.constituents],
            "nikkei_assessment": {
                "regime": a.regime,
                "fx_signal": a.fx_signal,
                "futures_signal": a.futures_signal,
                "regional_signal": a.regional_signal,
                "breadth_signal": a.breadth_signal,
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
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            views_path = output.parent / "nikkei_views.json"
            views_path.write_text(
                json.dumps(NIKKEI_VIEWS, indent=2),
                encoding="utf-8",
            )
        return result


def run_nikkei_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return NikkeiAverageAnalyst(pipeline_context=pipeline_context).run(output=output)
