"""
DXY-Commodities Correlation Expert Agent
=========================================
Tracks the structural inverse relationship between the U.S. Dollar Index
(DXY) and the global commodities complex, and flags the macro paradigm
shifts (commodities-driven inflation spirals, geopolitical crisis
divergence) where the two asset classes decouple and move in tandem.

Mechanics modeled:
  * Dollar as global pricing denominator — a stronger DXY raises the local-
    currency cost of dollar-invoiced commodities for foreign buyers,
    suppressing demand and nominal dollar prices (and vice versa).
  * Sector transmission channels — precious metals (opportunity-cost /
    safe-haven rivalry), energy (OPEC invoicing + demand destruction),
    and agribusiness (weather/supply shocks can override the FX linkage).
  * Paradigm shifts — structural commodity-driven inflation forces the Fed
    to hike, pulling the dollar and commodities up together; geopolitical
    shocks push safe-haven dollar/gold and strategic-reserve oil up in a
    simultaneous "dual panic".

Data: Yahoo Finance chart API (via ``agents.market_data.yahoo``), with a
calibrated proxy fallback when live closes are unavailable.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base import BaseExpert

# Dollar Index proxy — DX-Y.NYB is Yahoo's ICE Dollar Index ticker; UUP
# (Invesco DB US Dollar Index Bullish Fund) is a highly-correlated liquid
# ETF fallback used for the market-signal ticker.
DXY_SYMBOL = "DX-Y.NYB"
DXY_ETF_PROXY = "UUP"

# Commodity basket spanning the three sector transmission channels called
# out in the problem statement.
COMMODITY_BASKET: dict[str, dict[str, str]] = {
    "GLD": {"name": "Gold", "sector": "precious_metals", "futures": "GC=F"},
    "SLV": {"name": "Silver", "sector": "precious_metals", "futures": "SI=F"},
    "USO": {"name": "Crude Oil (WTI proxy)", "sector": "energy", "futures": "CL=F"},
    "UNG": {"name": "Natural Gas", "sector": "energy", "futures": "NG=F"},
    "CPER": {"name": "Copper", "sector": "industrial_metals", "futures": "HG=F"},
    "DBA": {"name": "Agribusiness (grains/softs)", "sector": "agribusiness", "futures": ""},
}

DXY_COMMODITIES_RESOURCES: list[dict[str, Any]] = [
    {
        "id": "dxy_chart",
        "name": "ICE U.S. Dollar Index (Yahoo chart)",
        "url": f"https://query1.finance.yahoo.com/v8/finance/chart/{DXY_SYMBOL}",
        "description": "Daily OHLC for the ICE Dollar Index used as the DXY proxy",
    },
    {
        "id": "uup_etf",
        "name": "Invesco DB US Dollar Index Bullish Fund (UUP)",
        "url": "https://query1.finance.yahoo.com/v8/finance/chart/UUP",
        "description": "Liquid tradeable ETF proxy for the Dollar Index",
    },
    {
        "id": "crb_index",
        "name": "Thomson Reuters/CoreCommodity CRB Index",
        "url": "https://tradingeconomics.com/commodity/crb",
        "description": "Broad commodity complex benchmark referenced for sector framing",
    },
]

# Calibrated proxy 20-trading-day return snapshot used when live Yahoo
# closes cannot be fetched (network blocked, rate limited). Values are
# indicative reference points, not live data, and are always labeled.
PROXY_RETURNS_20D_PCT: dict[str, float] = {
    DXY_SYMBOL: 1.1,
    "GLD": 2.4,
    "SLV": 1.8,
    "USO": -1.5,
    "UNG": -0.6,
    "CPER": 0.9,
    "DBA": 0.4,
}

# Correlation threshold below which the historical inverse mechanism is
# considered structurally intact.
INVERSE_CORRELATION_THRESHOLD = -0.30

# Minimum paired observations required before a Pearson correlation is
# considered statistically meaningful rather than noise.
MIN_CORRELATION_SAMPLES = 10

# Minimum daily closes needed for a valid 20-trading-day lookback plus a
# small buffer, used to decide whether to fall back to a proxy symbol/value.
MIN_PRICE_HISTORY = 25

# Confidence calibration for DXY-commodity market signals: a base
# confidence plus a scaled contribution from the strength of the observed
# correlation, capped at a maximum.
SIGNAL_BASE_CONFIDENCE = 0.45
SIGNAL_CORRELATION_WEIGHT = 0.5
SIGNAL_MAX_CONFIDENCE = 0.85


@dataclass
class CommodityCoupling:
    symbol: str
    name: str
    sector: str
    return_20d_pct: float | None
    correlation_20d: float
    regime: str
    summary: str


@dataclass
class DxyCommoditiesReport:
    dxy_symbol: str
    dxy_return_20d_pct: float | None
    couplings: list[CommodityCoupling]
    composite_regime: str
    composite_score: float
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DollarCommoditiesExpert(BaseExpert):
    """Analyst covering DXY <-> commodities inverse correlation and paradigm shifts."""

    def __init__(self, *, pipeline_context: dict | None = None) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="dxy-commodities")

    def _closes(self, symbol: str) -> list[float]:
        try:
            return self.fetch_yahoo_closes(symbol, range_="6mo", interval="1d")
        except Exception:
            return []

    @staticmethod
    def _log_returns(prices: list[float]) -> list[float]:
        returns: list[float] = []
        for i in range(1, len(prices)):
            prev, cur = prices[i - 1], prices[i]
            if prev and prev > 0 and cur and cur > 0:
                returns.append(math.log(cur / prev))
        return returns

    @staticmethod
    def _pct_return(prices: list[float], lookback: int) -> float | None:
        if len(prices) <= lookback:
            return None
        start, end = prices[-lookback - 1], prices[-1]
        if not start:
            return None
        return round((end / start - 1.0) * 100.0, 2)

    @staticmethod
    def _pearson(a: list[float], b: list[float]) -> float:
        n = min(len(a), len(b))
        if n < MIN_CORRELATION_SAMPLES:
            return 0.0
        a, b = a[-n:], b[-n:]
        ma, mb = statistics.mean(a), statistics.mean(b)
        num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
        da = math.sqrt(sum((x - ma) ** 2 for x in a))
        db = math.sqrt(sum((x - mb) ** 2 for x in b))
        if da == 0 or db == 0:
            return 0.0
        return round(num / (da * db), 4)

    def _fetch_dxy(self) -> tuple[list[float], str]:
        prices = self._closes(DXY_SYMBOL)
        if len(prices) >= MIN_PRICE_HISTORY:
            return prices, DXY_SYMBOL
        prices = self._closes(DXY_ETF_PROXY)
        if len(prices) >= MIN_PRICE_HISTORY:
            return prices, DXY_ETF_PROXY
        return [], ""

    def _classify_regime(
        self,
        *,
        sector: str,
        correlation: float,
        dxy_return: float | None,
        commodity_return: float | None,
    ) -> str:
        if correlation <= INVERSE_CORRELATION_THRESHOLD:
            return "Normal Inverse Correlation"

        both_known = dxy_return is not None and commodity_return is not None
        both_up = both_known and dxy_return > 0 and commodity_return > 0
        both_down = both_known and dxy_return < 0 and commodity_return < 0

        if both_up and sector in ("energy", "industrial_metals"):
            return "Positive Decoupling — Commodities-Driven Inflation Spiral"
        if both_up and sector == "precious_metals":
            return "Positive Decoupling — Geopolitical Crisis Divergence"
        if both_down:
            return "Deflationary Compression (both falling)"
        return "Transitional / Weak Coupling"

    def _coupling_summary(
        self,
        *,
        name: str,
        sector: str,
        correlation: float,
        commodity_return: float | None,
        regime: str,
    ) -> str:
        ret_txt = f"{commodity_return:+.2f}%" if commodity_return is not None else "n/a"
        return (
            f"{name} ({sector.replace('_', ' ')}): 20d return {ret_txt}, "
            f"20d correlation to DXY {correlation:+.2f} — {regime}"
        )

    def _market_signal(
        self,
        *,
        symbol: str,
        name: str,
        sector: str,
        regime: str,
        correlation: float,
        dxy_return: float | None,
        commodity_return: float | None,
    ) -> dict[str, Any]:
        from agent_signal_logic import build_market_signal

        if "Inflation Spiral" in regime or "Geopolitical" in regime:
            bias = "BULLISH"
            reason = (
                f"{name} decoupled from the dollar (corr {correlation:+.2f}) — {regime.split('—')[-1].strip()}, "
                "overriding the mechanical FX pricing linkage"
            )
        elif regime == "Normal Inverse Correlation" and dxy_return is not None:
            bias = "BEARISH" if dxy_return > 0 else "BULLISH" if dxy_return < 0 else "NEUTRAL"
            direction = "strengthening" if dxy_return > 0 else "weakening"
            reason = (
                f"DXY {direction} ({dxy_return:+.2f}% 20d) with intact inverse correlation "
                f"({correlation:+.2f}) to {name} — mechanical FX pricing pressure dominates"
            )
        else:
            bias = "NEUTRAL"
            reason = f"{name}/DXY coupling unclear ({regime}); no dominant directional driver"

        confidence = min(
            SIGNAL_MAX_CONFIDENCE,
            SIGNAL_BASE_CONFIDENCE + abs(correlation) * SIGNAL_CORRELATION_WEIGHT,
        )
        return build_market_signal(
            sector=f"DXY-Commodities ({sector.replace('_', ' ')})",
            tickers=[symbol],
            bias=bias,
            reason=reason,
            confidence=confidence,
            evidence={
                "correlation_20d": correlation,
                "dxy_return_20d_pct": dxy_return,
                "commodity_return_20d_pct": commodity_return,
                "regime": regime,
            },
        )

    def _adjust_market_signals(self, signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        adjusted: list[dict[str, Any]] = []
        for sig in signals:
            row = dict(sig)
            tickers = row.get("tickers") or []
            conf = row.get("confidence")
            if tickers and conf is not None:
                row["confidence"] = self.adjust_signal_confidence(
                    str(tickers[0]), str(row.get("bias", "NEUTRAL")), conf
                )
            adjusted.append(row)
        return adjusted

    def _composite(self, couplings: list[CommodityCoupling]) -> tuple[str, float]:
        if not couplings:
            return "Insufficient data", 0.0
        avg_corr = round(sum(c.correlation_20d for c in couplings) / len(couplings), 4)
        decoupled = [c for c in couplings if c.regime != "Normal Inverse Correlation"]
        decoupled_ratio = len(decoupled) / len(couplings)
        inflation_hits = sum(1 for c in decoupled if "Inflation Spiral" in c.regime)
        geopolitical_hits = sum(1 for c in decoupled if "Geopolitical" in c.regime)

        if decoupled_ratio >= 0.5 and inflation_hits >= geopolitical_hits and inflation_hits > 0:
            label = "Broad Decoupling — Commodities-Driven Inflation Spiral Regime"
        elif decoupled_ratio >= 0.5 and geopolitical_hits > 0:
            label = "Broad Decoupling — Geopolitical Crisis Divergence Regime"
        elif decoupled_ratio >= 0.5:
            label = "Broad Decoupling — Correlation Breakdown"
        elif avg_corr <= INVERSE_CORRELATION_THRESHOLD:
            label = "Normal Inverse Regime Intact"
        else:
            label = "Weak / Transitional Coupling"
        return label, avg_corr

    def analyze(self) -> DxyCommoditiesReport:
        sources: list[str] = []
        dxy_prices, dxy_symbol = self._fetch_dxy()
        dxy_returns = self._log_returns(dxy_prices) if dxy_prices else []
        dxy_return_20d = self._pct_return(dxy_prices, 20) if dxy_prices else None

        if dxy_prices:
            sources.append(f"Yahoo Finance chart API ({dxy_symbol})")
        else:
            sources.append("Calibrated proxy (DXY live data unavailable)")
            dxy_return_20d = PROXY_RETURNS_20D_PCT.get(DXY_SYMBOL)

        couplings: list[CommodityCoupling] = []
        signals: list[dict[str, Any]] = []
        live_hits = 0

        for symbol, meta in COMMODITY_BASKET.items():
            name, sector = meta["name"], meta["sector"]
            prices = self._closes(symbol)
            commodity_return = self._pct_return(prices, 20) if prices else None

            if prices and dxy_returns:
                commodity_returns = self._log_returns(prices)
                correlation = self._pearson(dxy_returns, commodity_returns)
                live_hits += 1
            else:
                correlation = 0.0

            if commodity_return is None:
                commodity_return = PROXY_RETURNS_20D_PCT.get(symbol)

            regime = self._classify_regime(
                sector=sector,
                correlation=correlation,
                dxy_return=dxy_return_20d,
                commodity_return=commodity_return,
            )
            summary = self._coupling_summary(
                name=name,
                sector=sector,
                correlation=correlation,
                commodity_return=commodity_return,
                regime=regime,
            )
            couplings.append(
                CommodityCoupling(
                    symbol=symbol,
                    name=name,
                    sector=sector,
                    return_20d_pct=commodity_return,
                    correlation_20d=correlation,
                    regime=regime,
                    summary=summary,
                )
            )
            signals.append(
                self._market_signal(
                    symbol=symbol,
                    name=name,
                    sector=sector,
                    regime=regime,
                    correlation=correlation,
                    dxy_return=dxy_return_20d,
                    commodity_return=commodity_return,
                )
            )

        if live_hits < len(COMMODITY_BASKET):
            sources.append(
                f"Calibrated commodity proxy ({len(COMMODITY_BASKET) - live_hits}/"
                f"{len(COMMODITY_BASKET)} symbols)"
            )
        if live_hits:
            sources.append(f"Yahoo Finance chart API ({live_hits}/{len(COMMODITY_BASKET)} commodity symbols)")

        signals = self._adjust_market_signals(signals)
        composite_regime, composite_score = self._composite(couplings)

        dxy_txt = f"{dxy_return_20d:+.2f}%" if dxy_return_20d is not None else "n/a"
        expert_summary = (
            f"DXY ({dxy_symbol or DXY_SYMBOL}) 20d return {dxy_txt}. Composite regime: "
            f"{composite_regime} (avg correlation {composite_score:+.2f}). "
            + " ".join(c.summary for c in couplings)
        )

        recs = [
            f"Composite DXY-commodities regime: {composite_regime} (avg corr {composite_score:+.2f})",
        ]
        # Weakest-to-strongest correlation ordering surfaces the pairs most
        # likely to be in (or approaching) a decoupling regime first.
        for c in sorted(couplings, key=lambda x: abs(x.correlation_20d)):
            recs.append(c.summary)
        recs.append(
            "Mechanical rule of thumb: dollar strength (DXY up) implies commodity headwinds via FX "
            "purchasing-power translation, unless structural inflation or a geopolitical shock forces "
            "the Fed to hike into a rallying commodities complex, or a safe-haven 'dual panic' lifts "
            "the dollar and gold/oil together."
        )

        return DxyCommoditiesReport(
            dxy_symbol=dxy_symbol or DXY_SYMBOL,
            dxy_return_20d_pct=dxy_return_20d,
            couplings=couplings,
            composite_regime=composite_regime,
            composite_score=composite_score,
            expert_summary=expert_summary,
            market_signals=signals,
            recommendations=self.append_memory_recommendations(recs),
            data_sources=sources,
        )

    def to_dict(self, report: DxyCommoditiesReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "DXY-Commodities Correlation Expert",
                "analyzed_at": report.analyzed_at,
                "expert_summary": report.expert_summary,
                "dxy_symbol": report.dxy_symbol,
                "commodities_analyzed": len(report.couplings),
                "data_sources": report.data_sources,
            },
            "dxy": {
                "symbol": report.dxy_symbol,
                "return_20d_pct": report.dxy_return_20d_pct,
            },
            "couplings": [
                {
                    "symbol": c.symbol,
                    "name": c.name,
                    "sector": c.sector,
                    "return_20d_pct": c.return_20d_pct,
                    "correlation_20d": c.correlation_20d,
                    "regime": c.regime,
                    "summary": c.summary,
                }
                for c in report.couplings
            ],
            "metrics": {
                "composite_regime": report.composite_regime,
                "composite_score": report.composite_score,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            resources_path = output.parent / "dxy_commodities_resources.json"
            resources_path.write_text(
                json.dumps(DXY_COMMODITIES_RESOURCES, indent=2),
                encoding="utf-8",
            )
        return result


def run_dxy_commodities_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return DollarCommoditiesExpert(pipeline_context=pipeline_context).run(output=output)
