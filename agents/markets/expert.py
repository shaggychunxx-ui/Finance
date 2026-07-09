"""
Market Analyst Expert Agent
===========================
Expert US market analysis from Yahoo Finance public APIs.

Dashboard: https://finance.yahoo.com/
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

DASHBOARD_URL = "https://finance.yahoo.com/"
CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
TRENDING_API = "https://query1.finance.yahoo.com/v1/finance/trending/US"
SCREENER_API = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
HEADERS = {"User-Agent": "Finance-Market-Analyst/1.0 (shaggychunxx@gmail.com)"}

US_INDICES = ["^GSPC", "^DJI", "^IXIC", "^RUT"]
RISK_SYMBOLS = ["^VIX"]
SECTOR_ETFS = {
    "XLK": "Technology",
    "XLE": "Energy",
    "XLU": "Utilities",
    "XLF": "Financials",
    "XLI": "Industrials",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLRE": "Real Estate",
    "XLV": "Health Care",
    "XLB": "Materials",
    "XLC": "Communication",
}
DEFENSIVE = {"XLU", "XLP", "XLRE", "XLV"}
CYCLICAL = {"XLE", "XLI", "XLY", "XLF", "XLB"}
GROWTH_PROXY = "QQQ"
VALUE_PROXY = "IWM"
COMMODITIES = {"CL=F": "Crude Oil", "GC=F": "Gold"}


@dataclass
class Quote:
    symbol: str
    name: str
    price: float | None
    day_chg_pct: float | None
    week_chg_pct: float | None = None
    volume: int | None = None


@dataclass
class SectorSnapshot:
    etf: str
    sector: str
    day_chg_pct: float | None
    week_chg_pct: float | None
    rank: int = 0


@dataclass
class MarketAssessment:
    regime: str
    breadth_signal: str
    sector_rotation: str
    volatility_context: str
    style_tilt: str
    commodity_backdrop: str


@dataclass
class MarketReport:
    indices: list[Quote]
    sectors: list[SectorSnapshot]
    top_gainers: list[Quote]
    top_losers: list[Quote]
    trending: list[str]
    assessment: MarketAssessment
    risk_on_score: float
    breadth_score: float
    momentum_score: float
    dispersion_score: float
    trend_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MarketAnalystExpert:
    """Expert market analyst — indices, sectors, movers, and regime assessment."""

    def __init__(self, delay_seconds: float = 0.35) -> None:
        self.delay_seconds = delay_seconds
        self.symbols = (
            US_INDICES + RISK_SYMBOLS + list(SECTOR_ETFS)
            + [GROWTH_PROXY, VALUE_PROXY] + list(COMMODITIES)
        )

    def _fetch_chart(self, symbol: str) -> Quote | None:
        try:
            resp = requests.get(
                CHART_API.format(symbol=symbol),
                params={"interval": "1d", "range": "1mo"},
                headers=HEADERS,
                timeout=25,
            )
            if resp.status_code == 429:
                time.sleep(3)
                resp = requests.get(
                    CHART_API.format(symbol=symbol),
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
            else:
                prev = meta.get("previousClose")
                if prev is not None:
                    day_chg = round(((float(price) - float(prev)) / float(prev)) * 100, 2)

            week_chg: float | None = None
            if len(valid) >= 6:
                week_chg = round(((valid[-1] - valid[-6]) / valid[-6]) * 100, 2)
            elif len(valid) >= 2:
                week_chg = round(((valid[-1] - valid[0]) / valid[0]) * 100, 2)

            return Quote(
                symbol=symbol,
                name=meta.get("shortName") or symbol,
                price=round(float(price), 2),
                day_chg_pct=day_chg,
                week_chg_pct=week_chg,
                volume=meta.get("regularMarketVolume"),
            )
        except Exception:
            return None

    def _fetch_trending(self) -> list[str]:
        try:
            resp = requests.get(TRENDING_API, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            return [
                q["symbol"]
                for q in resp.json()["finance"]["result"][0].get("quotes", [])
                if q.get("symbol")
            ]
        except Exception:
            return []

    def _fetch_screener(self, scr_id: str, count: int = 10) -> list[Quote]:
        try:
            resp = requests.get(
                SCREENER_API,
                params={"scrIds": scr_id, "count": count},
                headers=HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
            rows: list[Quote] = []
            for q in resp.json()["finance"]["result"][0].get("quotes", []):
                pct = q.get("regularMarketChangePercent")
                if pct is None:
                    continue
                rows.append(Quote(
                    symbol=q.get("symbol", "?"),
                    name=q.get("shortName") or q.get("symbol", "?"),
                    price=q.get("regularMarketPrice"),
                    day_chg_pct=round(float(pct), 2),
                ))
            return rows
        except Exception:
            return []

    @staticmethod
    def _avg(rows: list[Quote], field: str = "day_chg_pct") -> float | None:
        vals = [getattr(r, field) for r in rows if getattr(r, field) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    @staticmethod
    def _norm_score(pct: float | None, scale: float = 4.0) -> float:
        if pct is None:
            return 0.5
        return round(max(0.0, min(1.0, 0.5 + (pct / scale) * 0.25)), 4)

    def _sector_snapshots(self, by_sym: dict[str, Quote]) -> list[SectorSnapshot]:
        sectors: list[SectorSnapshot] = []
        for etf, name in SECTOR_ETFS.items():
            q = by_sym.get(etf)
            if not q:
                continue
            sectors.append(SectorSnapshot(
                etf=etf,
                sector=name,
                day_chg_pct=q.day_chg_pct,
                week_chg_pct=q.week_chg_pct,
            ))
        sectors.sort(key=lambda s: s.day_chg_pct or -999, reverse=True)
        for i, s in enumerate(sectors, 1):
            s.rank = i
        return sectors

    def _assessment(
        self,
        by_sym: dict[str, Quote],
        sectors: list[SectorSnapshot],
        breadth: float | None,
        risk_on: float,
    ) -> MarketAssessment:
        vix = by_sym.get("^VIX")
        qqq = by_sym.get("QQQ")
        iwm = by_sym.get("IWM")
        oil = by_sym.get("CL=F")
        gold = by_sym.get("GC=F")

        if risk_on >= 0.60:
            regime = "risk-on — growth and cyclicals favored"
        elif risk_on <= 0.40:
            regime = "risk-off — defensives and quality bid"
        else:
            regime = "neutral — mixed risk appetite"

        if breadth is not None:
            if breadth > 0.4:
                breadth_signal = f"broad advance ({breadth:+.2f}% avg across major indices)"
            elif breadth < -0.4:
                breadth_signal = f"broad decline ({breadth:+.2f}% index breadth)"
            else:
                breadth_signal = f"mixed breadth ({breadth:+.2f}%)"
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

        if vix and vix.day_chg_pct is not None:
            if vix.day_chg_pct > 5:
                vol_ctx = f"VIX spiking {vix.day_chg_pct:+.2f}% — elevated fear"
            elif vix.day_chg_pct < -3:
                vol_ctx = f"VIX compressing {vix.day_chg_pct:+.2f}% — complacency building"
            else:
                vol_ctx = f"VIX {vix.day_chg_pct:+.2f}% — normal volatility"
        else:
            vol_ctx = "volatility context unavailable"

        if qqq and iwm and qqq.day_chg_pct is not None and iwm.day_chg_pct is not None:
            spread = qqq.day_chg_pct - iwm.day_chg_pct
            if spread > 0.5:
                style = f"large-cap growth leading (QQQ {qqq.day_chg_pct:+.2f}% vs IWM {iwm.day_chg_pct:+.2f}%)"
            elif spread < -0.5:
                style = f"small-cap/value catching bid (IWM {iwm.day_chg_pct:+.2f}% vs QQQ {qqq.day_chg_pct:+.2f}%)"
            else:
                style = "balanced style performance"
        else:
            style = "style tilt unclear"

        commodity_parts: list[str] = []
        if oil and oil.day_chg_pct is not None:
            commodity_parts.append(f"oil {oil.day_chg_pct:+.2f}%")
        if gold and gold.day_chg_pct is not None:
            commodity_parts.append(f"gold {gold.day_chg_pct:+.2f}%")
        commodity_backdrop = (
            ", ".join(commodity_parts) if commodity_parts else "commodity data limited"
        )

        return MarketAssessment(
            regime=regime,
            breadth_signal=breadth_signal,
            sector_rotation=sector_rotation,
            volatility_context=vol_ctx,
            style_tilt=style,
            commodity_backdrop=commodity_backdrop,
        )

    def _expert_summary(
        self,
        assessment: MarketAssessment,
        breadth: float | None,
        risk_on: float,
        momentum: float,
        label: str,
        gainers: list[Quote],
    ) -> str:
        top = f"{gainers[0].symbol} {gainers[0].day_chg_pct:+.2f}%" if gainers else "n/a"
        return (
            f"US market regime is {label.lower()} (risk-on score {risk_on:.2f}). "
            f"{assessment.regime}. "
            f"Breadth: {assessment.breadth_signal}. "
            f"Rotation: {assessment.sector_rotation}. "
            f"Volatility: {assessment.volatility_context}. "
            f"Style: {assessment.style_tilt}. "
            f"Commodities: {assessment.commodity_backdrop}. "
            f"Momentum score {momentum:.2f}. Top gainer: {top}."
        )

    def analyze(self) -> MarketReport:
        quotes: list[Quote] = []
        for symbol in self.symbols:
            row = self._fetch_chart(symbol)
            if row:
                quotes.append(row)
            time.sleep(self.delay_seconds)

        by_sym = {q.symbol: q for q in quotes}
        indices = [by_sym[s] for s in US_INDICES + RISK_SYMBOLS if s in by_sym]
        sectors = self._sector_snapshots(by_sym)

        trending = self._fetch_trending()
        time.sleep(self.delay_seconds)
        gainers = self._fetch_screener("day_gainers", 10)
        time.sleep(self.delay_seconds)
        losers = self._fetch_screener("day_losers", 10)

        index_rows = [by_sym[s] for s in US_INDICES if s in by_sym]
        breadth_pct = self._avg(index_rows)
        breadth_score = self._norm_score(breadth_pct)

        risk_parts: list[float] = []
        vix = by_sym.get("^VIX")
        nasdaq = by_sym.get("^IXIC")
        tech = by_sym.get("XLK")
        if vix and vix.day_chg_pct is not None:
            risk_parts.append(-vix.day_chg_pct)
        if nasdaq and nasdaq.day_chg_pct is not None:
            risk_parts.append(nasdaq.day_chg_pct)
        if tech and tech.day_chg_pct is not None:
            risk_parts.append(tech.day_chg_pct)
        risk_on_raw = sum(risk_parts) / len(risk_parts) if risk_parts else None
        risk_on = self._norm_score(risk_on_raw, scale=5.0)

        gainer_pcts = [g.day_chg_pct for g in gainers if g.day_chg_pct is not None]
        momentum = self._norm_score(
            sum(gainer_pcts[:5]) / min(len(gainer_pcts), 5) if gainer_pcts else None,
            scale=8.0,
        )

        top_gain = gainers[0].day_chg_pct if gainers else None
        top_loss = losers[0].day_chg_pct if losers else None
        dispersion = (
            self._norm_score(top_gain - top_loss if top_gain is not None and top_loss is not None else None, 30.0)
        )

        assessment = self._assessment(by_sym, sectors, breadth_pct, risk_on)
        label = (
            "Risk-On" if risk_on >= 0.60 else
            "Risk-Off" if risk_on <= 0.40 else
            "Neutral"
        )
        summary = self._expert_summary(assessment, breadth_pct, risk_on, momentum, label, gainers)
        signals = self._market_signals(by_sym, sectors, gainers, losers, breadth_pct, risk_on)
        recs = self._recommendations(by_sym, sectors, gainers, losers, trending, assessment, risk_on)

        return MarketReport(
            indices=indices,
            sectors=sectors,
            top_gainers=gainers[:10],
            top_losers=losers[:10],
            trending=trending[:10],
            assessment=assessment,
            risk_on_score=risk_on,
            breadth_score=breadth_score,
            momentum_score=momentum,
            dispersion_score=dispersion,
            trend_label=label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source="Yahoo Finance API",
        )

    @staticmethod
    def _market_signals(
        by_sym: dict[str, Quote],
        sectors: list[SectorSnapshot],
        gainers: list[Quote],
        losers: list[Quote],
        breadth: float | None,
        risk_on: float,
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import breadth_risk_signal_confidence, build_market_signal

        signals: list[dict[str, Any]] = []

        if breadth is not None and abs(breadth) >= 0.2:
            bias = "BULLISH" if breadth > 0.3 else ("BEARISH" if breadth < -0.3 else "NEUTRAL")
            signals.append(
                build_market_signal(
                    sector="US Broad Market",
                    tickers=["SPY", "QQQ", "IWM"],
                    bias=bias,
                    reason=f"Index breadth {breadth:+.2f}%",
                    confidence=breadth_risk_signal_confidence(breadth, risk_on),
                    evidence={"breadth_pct": round(breadth, 3), "risk_on": round(risk_on, 3)},
                )
            )

        if risk_on >= 0.60:
            signals.append(
                build_market_signal(
                    sector="Growth / Tech",
                    tickers=["QQQ", "XLK", "NVDA", "MSFT"],
                    bias="BULLISH",
                    reason=f"Risk-on score {risk_on:.2f}",
                    confidence=breadth_risk_signal_confidence(breadth, risk_on),
                )
            )
        elif risk_on <= 0.40:
            signals.append(
                build_market_signal(
                    sector="Defensives",
                    tickers=["XLU", "XLP", "GLD", "TLT"],
                    bias="BULLISH",
                    reason=f"Risk-off score {risk_on:.2f}",
                    confidence=breadth_risk_signal_confidence(breadth, risk_on),
                )
            )

        if sectors:
            leader = sectors[0]
            if (leader.day_chg_pct or 0) > 0.4:
                signals.append(
                    build_market_signal(
                        sector=f"Leading — {leader.sector}",
                        tickers=[leader.etf],
                        bias="BULLISH" if (leader.day_chg_pct or 0) > 0.5 else "NEUTRAL",
                        reason=f"{leader.etf} {leader.day_chg_pct:+.2f}% today",
                        confidence=breadth_risk_signal_confidence(
                            leader.day_chg_pct,
                            risk_on,
                            momentum=0.55 + min((leader.day_chg_pct or 0) / 5.0, 0.2),
                        ),
                    )
                )
            laggard = sectors[-1]
            if (laggard.day_chg_pct or 0) < -0.5:
                signals.append(
                    build_market_signal(
                        sector=f"Lagging — {laggard.sector}",
                        tickers=[laggard.etf],
                        bias="BEARISH",
                        reason=f"{laggard.etf} {laggard.day_chg_pct:+.2f}% today",
                        confidence=breadth_risk_signal_confidence(laggard.day_chg_pct, risk_on),
                    )
                )

        xle = by_sym.get("XLE")
        if xle and xle.day_chg_pct is not None and abs(xle.day_chg_pct) > 0.75:
            signals.append(
                build_market_signal(
                    sector="Energy",
                    tickers=["XLE", "USO", "XOM"],
                    bias="BULLISH" if xle.day_chg_pct > 0 else "BEARISH",
                    reason=f"Energy {xle.day_chg_pct:+.2f}%",
                    confidence=breadth_risk_signal_confidence(xle.day_chg_pct, risk_on),
                )
            )

        if gainers and (gainers[0].day_chg_pct or 0) >= 2.0:
            signals.append(
                build_market_signal(
                    sector="Top Movers",
                    tickers=[g.symbol for g in gainers[:5]],
                    bias="BULLISH",
                    reason=f"Leader {gainers[0].symbol} {gainers[0].day_chg_pct:+.2f}%",
                    confidence=breadth_risk_signal_confidence(gainers[0].day_chg_pct, risk_on),
                )
            )

        if not signals:
            signals.append(
                build_market_signal(
                    sector="Broad Market",
                    tickers=["SPY"],
                    bias="NEUTRAL",
                    reason="No strong directional tilt on tape",
                    confidence=0.42,
                )
            )
        return signals

    @staticmethod
    def _recommendations(
        by_sym: dict[str, Quote],
        sectors: list[SectorSnapshot],
        gainers: list[Quote],
        losers: list[Quote],
        trending: list[str],
        assessment: MarketAssessment,
        risk_on: float,
    ) -> list[str]:
        recs = [
            assessment.regime,
            assessment.breadth_signal,
            assessment.sector_rotation,
            assessment.volatility_context,
            assessment.style_tilt,
            f"Commodities: {assessment.commodity_backdrop}",
        ]
        for s in sectors[:3]:
            recs.append(f"Sector leader #{s.rank}: {s.sector} ({s.etf}) {s.day_chg_pct:+.2f}%")
        if gainers:
            recs.append(
                "Top gainers: "
                + ", ".join(f"{g.symbol} {g.day_chg_pct:+.2f}%" for g in gainers[:5])
            )
        if losers:
            recs.append(
                "Top losers: "
                + ", ".join(f"{l.symbol} {l.day_chg_pct:+.2f}%" for l in losers[:5])
            )
        if trending:
            recs.append(f"Yahoo trending: {', '.join(trending[:5])}")
        if risk_on >= 0.65:
            recs.append("Risk-on environment — favor growth, cyclicals, and momentum leaders")
        elif risk_on <= 0.35:
            recs.append("Risk-off environment — raise cash, defensives, and hedges")
        return recs

    def to_dict(self, report: MarketReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Market Analyst Expert",
                "dashboard": DASHBOARD_URL,
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
            },
            "assessment": {
                "regime": a.regime,
                "breadth_signal": a.breadth_signal,
                "sector_rotation": a.sector_rotation,
                "volatility_context": a.volatility_context,
                "style_tilt": a.style_tilt,
                "commodity_backdrop": a.commodity_backdrop,
            },
            "indices": [
                {
                    "symbol": q.symbol,
                    "name": q.name,
                    "price": q.price,
                    "day_chg_pct": q.day_chg_pct,
                    "week_chg_pct": q.week_chg_pct,
                }
                for q in report.indices
            ],
            "sectors": [
                {
                    "etf": s.etf,
                    "sector": s.sector,
                    "rank": s.rank,
                    "day_chg_pct": s.day_chg_pct,
                    "week_chg_pct": s.week_chg_pct,
                }
                for s in report.sectors
            ],
            "top_gainers": [
                {"symbol": g.symbol, "name": g.name, "day_chg_pct": g.day_chg_pct}
                for g in report.top_gainers
            ],
            "top_losers": [
                {"symbol": l.symbol, "name": l.name, "day_chg_pct": l.day_chg_pct}
                for l in report.top_losers
            ],
            "trending": report.trending,
            "metrics": {
                "risk_on_score": report.risk_on_score,
                "breadth_score": report.breadth_score,
                "momentum_score": report.momentum_score,
                "dispersion_score": report.dispersion_score,
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


def run_markets_analysis(output: Path | None = None) -> dict[str, Any]:
    return MarketAnalystExpert().run(output=output)