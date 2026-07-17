"""
FTSE 100 Index Analyst Agent
============================
Expert UK equity market analysis tracking the FTSE 100 index and its
largest constituents across sectors.

Dashboard: https://www.londonstockexchange.com/indices/ftse-100
Data: Yahoo Finance chart API (``^FTSE`` + ``.L`` London-listed constituents)
with graceful degradation when a symbol can't be fetched.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base import BaseExpert

DASHBOARD_URL = "https://www.londonstockexchange.com/indices/ftse-100"

INDEX_SYMBOL = "^FTSE"
FX_SYMBOL = "GBPUSD=X"

# A representative cross-section of the largest FTSE 100 constituents,
# grouped by sector, used as breadth/rotation proxies for the index.
CONSTITUENTS: dict[str, dict[str, str]] = {
    "SHEL.L": {"name": "Shell", "sector": "Energy"},
    "BP.L": {"name": "BP", "sector": "Energy"},
    "AZN.L": {"name": "AstraZeneca", "sector": "Health Care"},
    "GSK.L": {"name": "GSK", "sector": "Health Care"},
    "ULVR.L": {"name": "Unilever", "sector": "Consumer Staples"},
    "DGE.L": {"name": "Diageo", "sector": "Consumer Staples"},
    "BATS.L": {"name": "British American Tobacco", "sector": "Consumer Staples"},
    "HSBA.L": {"name": "HSBC Holdings", "sector": "Financials"},
    "LLOY.L": {"name": "Lloyds Banking Group", "sector": "Financials"},
    "BARC.L": {"name": "Barclays", "sector": "Financials"},
    "RIO.L": {"name": "Rio Tinto", "sector": "Materials"},
    "GLEN.L": {"name": "Glencore", "sector": "Materials"},
    "NG.L": {"name": "National Grid", "sector": "Utilities"},
    "VOD.L": {"name": "Vodafone Group", "sector": "Communication"},
    "REL.L": {"name": "RELX", "sector": "Industrials"},
}


@dataclass
class Quote:
    symbol: str
    name: str
    sector: str
    price: float | None
    day_chg_pct: float | None
    week_chg_pct: float | None = None
    volume: int | None = None


@dataclass
class SectorSnapshot:
    sector: str
    day_chg_pct: float | None
    week_chg_pct: float | None
    constituents: int
    rank: int = 0


@dataclass
class FTSEAssessment:
    regime: str
    breadth_signal: str
    sector_rotation: str
    fx_context: str
    volatility_context: str


@dataclass
class FTSEReport:
    index_quote: Quote | None
    constituents: list[Quote]
    sectors: list[SectorSnapshot]
    top_gainers: list[Quote]
    top_losers: list[Quote]
    assessment: FTSEAssessment
    breadth_score: float
    sentiment_score: float
    momentum_score: float
    trend_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FTSE100Expert(BaseExpert):
    """Expert FTSE 100 analyst — index, constituent breadth, and sector rotation."""

    def __init__(
        self,
        delay_seconds: float = 0.35,
        *,
        pipeline_context: dict | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="ftse100")
        self.delay_seconds = delay_seconds

    def _fetch_chart(self, symbol: str, name: str = "", sector: str = "") -> Quote | None:
        meta = self.fetch_yahoo_chart_meta(symbol, range_="1mo", interval="1d")
        if not meta:
            return None
        price = meta.get("price")
        if price is None:
            return None
        return Quote(
            symbol=symbol,
            name=name or symbol,
            sector=sector,
            price=round(float(price), 2),
            day_chg_pct=meta.get("day_chg_pct"),
            week_chg_pct=meta.get("week_chg_pct"),
            volume=meta.get("volume"),
        )

    @staticmethod
    def _avg(rows: list[Quote], field: str = "day_chg_pct") -> float | None:
        vals = [getattr(r, field) for r in rows if getattr(r, field) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    @staticmethod
    def _norm_score(pct: float | None, scale: float = 4.0) -> float:
        if pct is None:
            return 0.5
        return round(max(0.0, min(1.0, 0.5 + (pct / scale) * 0.25)), 4)

    def _sector_snapshots(self, constituents: list[Quote]) -> list[SectorSnapshot]:
        by_sector: dict[str, list[Quote]] = {}
        for q in constituents:
            by_sector.setdefault(q.sector, []).append(q)

        sectors: list[SectorSnapshot] = []
        for sector, rows in by_sector.items():
            sectors.append(
                SectorSnapshot(
                    sector=sector,
                    day_chg_pct=self._avg(rows),
                    week_chg_pct=self._avg(rows, "week_chg_pct"),
                    constituents=len(rows),
                )
            )
        sectors.sort(key=lambda s: s.day_chg_pct if s.day_chg_pct is not None else -999, reverse=True)
        for i, s in enumerate(sectors, 1):
            s.rank = i
        return sectors

    def _assessment(
        self,
        index_quote: Quote | None,
        fx_quote: Quote | None,
        sectors: list[SectorSnapshot],
        breadth: float | None,
    ) -> FTSEAssessment:
        if index_quote and index_quote.day_chg_pct is not None:
            pct = index_quote.day_chg_pct
            if pct > 0.5:
                regime = f"risk-on — FTSE 100 up {pct:+.2f}% on the day"
            elif pct < -0.5:
                regime = f"risk-off — FTSE 100 down {pct:+.2f}% on the day"
            else:
                regime = f"neutral — FTSE 100 little changed ({pct:+.2f}%)"
        else:
            regime = "index data unavailable"

        if breadth is not None:
            if breadth > 0.4:
                breadth_signal = f"broad advance across constituents ({breadth:+.2f}% avg)"
            elif breadth < -0.4:
                breadth_signal = f"broad decline across constituents ({breadth:+.2f}% avg)"
            else:
                breadth_signal = f"mixed constituent breadth ({breadth:+.2f}%)"
        else:
            breadth_signal = "breadth data unavailable"

        if sectors:
            leader = sectors[0]
            laggard = sectors[-1]
            sector_rotation = (
                f"leading {leader.sector} ({leader.day_chg_pct:+.2f}%), "
                f"lagging {laggard.sector} ({laggard.day_chg_pct:+.2f}%)"
            )
        else:
            sector_rotation = "sector data limited"

        if fx_quote and fx_quote.day_chg_pct is not None:
            direction = "strengthening" if fx_quote.day_chg_pct > 0 else "weakening"
            fx_context = f"GBP/USD {direction} {fx_quote.day_chg_pct:+.2f}%"
        else:
            fx_context = "FX context unavailable"

        if index_quote and index_quote.week_chg_pct is not None:
            wpct = index_quote.week_chg_pct
            if abs(wpct) > 2.5:
                volatility_context = f"elevated weekly swing ({wpct:+.2f}%)"
            else:
                volatility_context = f"normal weekly range ({wpct:+.2f}%)"
        else:
            volatility_context = "volatility context unavailable"

        return FTSEAssessment(
            regime=regime,
            breadth_signal=breadth_signal,
            sector_rotation=sector_rotation,
            fx_context=fx_context,
            volatility_context=volatility_context,
        )

    def _expert_summary(
        self,
        assessment: FTSEAssessment,
        sentiment: float,
        momentum: float,
        label: str,
        gainers: list[Quote],
    ) -> str:
        top = f"{gainers[0].name} {gainers[0].day_chg_pct:+.2f}%" if gainers else "n/a"
        return (
            f"FTSE 100 regime is {label.lower()} (sentiment score {sentiment:.2f}). "
            f"{assessment.regime}. "
            f"Breadth: {assessment.breadth_signal}. "
            f"Rotation: {assessment.sector_rotation}. "
            f"FX: {assessment.fx_context}. "
            f"Volatility: {assessment.volatility_context}. "
            f"Momentum score {momentum:.2f}. Top constituent mover: {top}."
        )

    def analyze(self) -> FTSEReport:
        index_quote = self._fetch_chart(INDEX_SYMBOL, name="FTSE 100", sector="Index")
        time.sleep(self.delay_seconds)
        fx_quote = self._fetch_chart(FX_SYMBOL, name="GBP/USD", sector="FX")
        time.sleep(self.delay_seconds)

        constituents: list[Quote] = []
        for symbol, meta in CONSTITUENTS.items():
            row = self._fetch_chart(symbol, name=meta["name"], sector=meta["sector"])
            if row:
                constituents.append(row)
            time.sleep(self.delay_seconds)

        sectors = self._sector_snapshots(constituents)
        breadth = self._avg(constituents)
        breadth_score = self._norm_score(breadth)

        ranked = sorted(
            (c for c in constituents if c.day_chg_pct is not None),
            key=lambda c: c.day_chg_pct,
            reverse=True,
        )
        gainers = ranked[:10]
        losers = list(reversed(ranked))[:10]

        sentiment_raw = index_quote.day_chg_pct if index_quote else breadth
        sentiment = self._norm_score(sentiment_raw, scale=1.5)

        gainer_pcts = [g.day_chg_pct for g in gainers if g.day_chg_pct is not None]
        momentum = self._norm_score(
            sum(gainer_pcts[:5]) / min(len(gainer_pcts), 5) if gainer_pcts else None,
            scale=4.0,
        )

        assessment = self._assessment(index_quote, fx_quote, sectors, breadth)
        label = (
            "Risk-On" if sentiment >= 0.60 else
            "Risk-Off" if sentiment <= 0.40 else
            "Neutral"
        )
        summary = self._expert_summary(assessment, sentiment, momentum, label, gainers)
        signals = self._market_signals(index_quote, sectors, gainers, losers, breadth, sentiment)
        recs = self.append_memory_recommendations(
            self._recommendations(index_quote, fx_quote, sectors, gainers, losers, assessment, sentiment)
        )

        return FTSEReport(
            index_quote=index_quote,
            constituents=constituents,
            sectors=sectors,
            top_gainers=gainers,
            top_losers=losers,
            assessment=assessment,
            breadth_score=breadth_score,
            sentiment_score=sentiment,
            momentum_score=momentum,
            trend_label=label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source="Yahoo Finance API (^FTSE + LSE constituents)",
        )

    def _market_signals(
        self,
        index_quote: Quote | None,
        sectors: list[SectorSnapshot],
        gainers: list[Quote],
        losers: list[Quote],
        breadth: float | None,
        sentiment: float,
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import breadth_risk_signal_confidence, build_market_signal

        signals: list[dict[str, Any]] = []

        if index_quote and index_quote.day_chg_pct is not None and abs(index_quote.day_chg_pct) >= 0.3:
            bias = "BULLISH" if index_quote.day_chg_pct > 0 else "BEARISH"
            signals.append(
                build_market_signal(
                    sector="UK Broad Market",
                    tickers=["^FTSE"],
                    bias=bias,
                    reason=f"FTSE 100 {index_quote.day_chg_pct:+.2f}% today",
                    confidence=self.adjust_signal_confidence(
                        "^FTSE",
                        bias,
                        breadth_risk_signal_confidence(index_quote.day_chg_pct, sentiment),
                    ),
                    evidence={"breadth_pct": breadth, "sentiment": round(sentiment, 3)},
                )
            )

        if sectors:
            leader = sectors[0]
            if (leader.day_chg_pct or 0) > 0.4:
                leader_bias = "BULLISH" if (leader.day_chg_pct or 0) > 0.5 else "NEUTRAL"
                signals.append(
                    build_market_signal(
                        sector=f"Leading — {leader.sector}",
                        tickers=[leader.sector],
                        bias=leader_bias,
                        reason=f"{leader.sector} constituents avg {leader.day_chg_pct:+.2f}% today",
                        confidence=self.adjust_signal_confidence(
                            leader.sector,
                            leader_bias,
                            breadth_risk_signal_confidence(leader.day_chg_pct, sentiment),
                        ),
                    )
                )
            laggard = sectors[-1]
            if (laggard.day_chg_pct or 0) < -0.5:
                signals.append(
                    build_market_signal(
                        sector=f"Lagging — {laggard.sector}",
                        tickers=[laggard.sector],
                        bias="BEARISH",
                        reason=f"{laggard.sector} constituents avg {laggard.day_chg_pct:+.2f}% today",
                        confidence=self.adjust_signal_confidence(
                            laggard.sector,
                            "BEARISH",
                            breadth_risk_signal_confidence(laggard.day_chg_pct, sentiment),
                        ),
                    )
                )

        if gainers and (gainers[0].day_chg_pct or 0) >= 1.5:
            signals.append(
                build_market_signal(
                    sector="Top Movers",
                    tickers=[g.symbol for g in gainers[:5]],
                    bias="BULLISH",
                    reason=f"Leader {gainers[0].name} {gainers[0].day_chg_pct:+.2f}%",
                    confidence=self.adjust_signal_confidence(
                        gainers[0].symbol,
                        "BULLISH",
                        breadth_risk_signal_confidence(gainers[0].day_chg_pct, sentiment),
                    ),
                )
            )

        if not signals:
            signals.append(
                build_market_signal(
                    sector="UK Broad Market",
                    tickers=["^FTSE"],
                    bias="NEUTRAL",
                    reason="No strong directional tilt on the FTSE 100",
                    confidence=self.adjust_signal_confidence("^FTSE", "NEUTRAL", 0.42),
                )
            )
        return signals

    @staticmethod
    def _recommendations(
        index_quote: Quote | None,
        fx_quote: Quote | None,
        sectors: list[SectorSnapshot],
        gainers: list[Quote],
        losers: list[Quote],
        assessment: FTSEAssessment,
        sentiment: float,
    ) -> list[str]:
        recs = [
            assessment.regime,
            assessment.breadth_signal,
            assessment.sector_rotation,
            assessment.fx_context,
            assessment.volatility_context,
        ]
        for s in sectors[:3]:
            recs.append(f"Sector leader #{s.rank}: {s.sector} ({s.day_chg_pct:+.2f}%, {s.constituents} names)")
        if gainers:
            recs.append(
                "Top gainers: "
                + ", ".join(f"{g.name} {g.day_chg_pct:+.2f}%" for g in gainers[:5])
            )
        if losers:
            recs.append(
                "Top losers: "
                + ", ".join(f"{l.name} {l.day_chg_pct:+.2f}%" for l in losers[:5])
            )
        if sentiment >= 0.65:
            recs.append("Risk-on tape — favor FTSE 100 cyclicals and export-heavy names")
        elif sentiment <= 0.35:
            recs.append("Risk-off tape — favor FTSE 100 defensives and GBP hedges")
        return recs

    def to_dict(self, report: FTSEReport) -> dict[str, Any]:
        a = report.assessment

        def _quote(q: Quote | None) -> dict[str, Any] | None:
            if not q:
                return None
            return {
                "symbol": q.symbol,
                "name": q.name,
                "sector": q.sector,
                "price": q.price,
                "day_chg_pct": q.day_chg_pct,
                "week_chg_pct": q.week_chg_pct,
            }

        return {
            "meta": {
                "agent": "FTSE 100 Index Analyst",
                "dashboard": DASHBOARD_URL,
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
            },
            "assessment": {
                "regime": a.regime,
                "breadth_signal": a.breadth_signal,
                "sector_rotation": a.sector_rotation,
                "fx_context": a.fx_context,
                "volatility_context": a.volatility_context,
            },
            "index": _quote(report.index_quote),
            "constituents": [_quote(q) for q in report.constituents],
            "sectors": [
                {
                    "sector": s.sector,
                    "rank": s.rank,
                    "constituents": s.constituents,
                    "day_chg_pct": s.day_chg_pct,
                    "week_chg_pct": s.week_chg_pct,
                }
                for s in report.sectors
            ],
            "top_gainers": [_quote(q) for q in report.top_gainers],
            "top_losers": [_quote(q) for q in report.top_losers],
            "metrics": {
                "breadth_score": report.breadth_score,
                "sentiment_score": report.sentiment_score,
                "momentum_score": report.momentum_score,
                "trend_label": report.trend_label,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result


def run_ftse100_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return FTSE100Expert(pipeline_context=pipeline_context).run(output=output)
