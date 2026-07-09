"""
Yahoo Finance Statistical Analyst Agent
=========================================
Mathematician/market analyst with a statistics background analyzing
the Yahoo Finance dashboard and public market APIs.

Dashboard: https://finance.yahoo.com/
"""

from __future__ import annotations

import json
import math
import statistics
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
HEADERS = {"User-Agent": "Finance-Statistical-Analyst/1.0 (shaggychunxx@gmail.com)"}

US_INDICES = {
    "^GSPC": "S&P 500",
    "^DJI": "Dow Jones",
    "^IXIC": "Nasdaq",
    "^RUT": "Russell 2000",
    "^VIX": "VIX",
}
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
BENCHMARK = "SPY"

YAHOO_FINANCE_VIEWS: list[dict[str, Any]] = [
    {
        "id": "market_summary",
        "name": "Market Summary",
        "url": DASHBOARD_URL,
        "description": "US indices, futures, and global overview",
    },
    {
        "id": "sectors",
        "name": "Sectors",
        "url": f"{DASHBOARD_URL}sectors/",
        "description": "SPDR sector ETF performance and rankings",
    },
    {
        "id": "gainers",
        "name": "Top Gainers",
        "url": f"{DASHBOARD_URL}gainers/",
        "description": "Largest percentage advancers on the day",
    },
    {
        "id": "losers",
        "name": "Top Losers",
        "url": f"{DASHBOARD_URL}losers/",
        "description": "Largest percentage decliners on the day",
    },
    {
        "id": "trending",
        "name": "Trending Tickers",
        "url": f"{DASHBOARD_URL}trending-tickers/",
        "description": "Most searched and discussed symbols",
    },
    {
        "id": "most_active",
        "name": "Most Active",
        "url": f"{DASHBOARD_URL}most-active/",
        "description": "Highest volume equities",
    },
]


@dataclass
class SeriesStats:
    symbol: str
    name: str
    last_price: float | None
    return_1d_pct: float | None
    return_5d_pct: float | None
    return_20d_pct: float | None
    vol_20d_ann_pct: float | None
    z_score_20d: float | None
    cross_section_z: float | None = None
    beta_spy: float | None = None


@dataclass
class CrossSectionStats:
    mean_return_pct: float
    median_return_pct: float
    stdev_pct: float
    skewness: float
    excess_kurtosis: float
    advance_decline_ratio: float
    breadth_pct_positive: float
    dispersion_label: str


@dataclass
class CorrelationPair:
    symbol_a: str
    symbol_b: str
    correlation: float
    label: str


@dataclass
class OutlierMover:
    symbol: str
    name: str
    day_chg_pct: float
    z_score_mover: float
    direction: str


@dataclass
class StatisticalAssessment:
    market_regime: str
    volatility_regime: str
    breadth_signal: str
    dispersion_signal: str
    correlation_structure: str
    tail_risk_signal: str
    trend_signal: str
    mathematical_edge: str


@dataclass
class FinancialDataReport:
    indices: list[SeriesStats]
    sectors: list[SeriesStats]
    cross_section: CrossSectionStats
    correlations: list[CorrelationPair]
    outliers: list[OutlierMover]
    top_gainers: list[dict[str, Any]]
    top_losers: list[dict[str, Any]]
    trending: list[str]
    assessment: StatisticalAssessment
    statistical_score: float
    breadth_score: float
    volatility_score: float
    regime_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class YahooFinanceStatisticalAnalyst:
    """Mathematician/market analyst — statistical analysis of Yahoo Finance data."""

    def __init__(self, delay_seconds: float = 0.3) -> None:
        self.delay_seconds = delay_seconds
        self.symbols = list(US_INDICES) + list(SECTOR_ETFS) + [BENCHMARK]

    def _fetch_closes(self, symbol: str, range_: str = "3mo") -> list[float]:
        try:
            resp = requests.get(
                CHART_API.format(symbol=symbol),
                params={"interval": "1d", "range": range_},
                headers=HEADERS,
                timeout=25,
            )
            if resp.status_code == 429:
                time.sleep(3)
                resp = requests.get(
                    CHART_API.format(symbol=symbol),
                    params={"interval": "1d", "range": range_},
                    headers=HEADERS,
                    timeout=25,
                )
            resp.raise_for_status()
            closes = resp.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            return [float(c) for c in closes if c is not None]
        except Exception:
            return []

    @staticmethod
    def _returns(closes: list[float]) -> list[float]:
        return [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]

    @staticmethod
    def _period_return(closes: list[float], days: int) -> float | None:
        if len(closes) <= days:
            return None
        return round(((closes[-1] - closes[-days - 1]) / closes[-days - 1]) * 100, 2)

    @staticmethod
    def _ann_vol(daily_returns: list[float], window: int = 20) -> float | None:
        if len(daily_returns) < window:
            return None
        recent = daily_returns[-window:]
        return round(statistics.stdev(recent) * math.sqrt(252) * 100, 2)

    @staticmethod
    def _z_score(closes: list[float], window: int = 20) -> float | None:
        if len(closes) < window:
            return None
        window_closes = closes[-window:]
        mean = statistics.mean(window_closes)
        stdev = statistics.stdev(window_closes)
        if stdev == 0:
            return 0.0
        return round((closes[-1] - mean) / stdev, 2)

    @staticmethod
    def _skewness(vals: list[float]) -> float:
        n = len(vals)
        if n < 3:
            return 0.0
        m = statistics.mean(vals)
        s = statistics.stdev(vals)
        if s == 0:
            return 0.0
        return round(sum(((x - m) / s) ** 3 for x in vals) / n, 3)

    @staticmethod
    def _excess_kurtosis(vals: list[float]) -> float:
        n = len(vals)
        if n < 4:
            return 0.0
        m = statistics.mean(vals)
        s = statistics.stdev(vals)
        if s == 0:
            return 0.0
        return round(sum(((x - m) / s) ** 4 for x in vals) / n - 3.0, 3)

    @staticmethod
    def _correlation(a: list[float], b: list[float]) -> float | None:
        n = min(len(a), len(b))
        if n < 10:
            return None
        a_tail, b_tail = a[-n:], b[-n:]
        mean_a, mean_b = statistics.mean(a_tail), statistics.mean(b_tail)
        num = sum((a_tail[i] - mean_a) * (b_tail[i] - mean_b) for i in range(n))
        den_a = math.sqrt(sum((x - mean_a) ** 2 for x in a_tail))
        den_b = math.sqrt(sum((x - mean_b) ** 2 for x in b_tail))
        if den_a == 0 or den_b == 0:
            return None
        return round(num / (den_a * den_b), 3)

    @staticmethod
    def _beta(asset_returns: list[float], bench_returns: list[float]) -> float | None:
        n = min(len(asset_returns), len(bench_returns))
        if n < 15:
            return None
        a, b = asset_returns[-n:], bench_returns[-n:]
        mean_a, mean_b = statistics.mean(a), statistics.mean(b)
        cov = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n)) / (n - 1)
        var_b = statistics.variance(b)
        if var_b == 0:
            return None
        return round(cov / var_b, 2)

    @staticmethod
    def _linear_trend(closes: list[float], window: int = 20) -> tuple[float, float] | None:
        if len(closes) < window:
            return None
        y = closes[-window:]
        n = len(y)
        x_mean = (n - 1) / 2
        y_mean = statistics.mean(y)
        num = sum((i - x_mean) * (y[i] - y_mean) for i in range(n))
        den = sum((i - x_mean) ** 2 for i in range(n))
        if den == 0:
            return None
        slope = num / den
        slope_pct = round((slope / y_mean) * 100 * window, 2) if y_mean else 0.0
        ss_tot = sum((y[i] - y_mean) ** 2 for i in range(n))
        ss_res = sum((y[i] - (slope * (i - x_mean) + y_mean)) ** 2 for i in range(n))
        r2 = round(1 - ss_res / ss_tot, 3) if ss_tot else 0.0
        return slope_pct, r2

    def _fetch_screener(self, scr_id: str, count: int = 15) -> list[dict[str, Any]]:
        try:
            resp = requests.get(
                SCREENER_API,
                params={"scrIds": scr_id, "count": count},
                headers=HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
            rows: list[dict[str, Any]] = []
            for q in resp.json()["finance"]["result"][0].get("quotes", []):
                pct = q.get("regularMarketChangePercent")
                if pct is None:
                    continue
                rows.append({
                    "symbol": q.get("symbol", "?"),
                    "name": q.get("shortName") or q.get("symbol", "?"),
                    "price": q.get("regularMarketPrice"),
                    "day_chg_pct": round(float(pct), 2),
                })
            return rows
        except Exception:
            return []

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

    def _build_series(self, symbol: str, name: str, closes: list[float]) -> SeriesStats | None:
        if len(closes) < 2:
            return None
        daily = self._returns(closes)
        return SeriesStats(
            symbol=symbol,
            name=name,
            last_price=round(closes[-1], 2),
            return_1d_pct=round(daily[-1] * 100, 2) if daily else None,
            return_5d_pct=self._period_return(closes, 5),
            return_20d_pct=self._period_return(closes, 20),
            vol_20d_ann_pct=self._ann_vol(daily),
            z_score_20d=self._z_score(closes),
        )

    def _cross_section_stats(
        self,
        sectors: list[SeriesStats],
        gainers: list[dict[str, Any]],
        losers: list[dict[str, Any]],
    ) -> CrossSectionStats:
        returns = [s.return_1d_pct for s in sectors if s.return_1d_pct is not None]
        if not returns:
            returns = [0.0]

        adv = len([g for g in gainers if (g.get("day_chg_pct") or 0) > 0])
        dec = len([l for l in losers if (l.get("day_chg_pct") or 0) < 0])
        ad_ratio = round(adv / max(dec, 1), 2)
        breadth_pos = round(
            len([r for r in returns if r > 0]) / len(returns) * 100, 1
        )

        stdev = statistics.stdev(returns) if len(returns) > 1 else 0.0
        if stdev > 1.5:
            disp_label = "high dispersion — sector returns widely scattered"
        elif stdev < 0.4:
            disp_label = "low dispersion — sectors moving in lockstep"
        else:
            disp_label = "moderate dispersion — typical sector spread"

        return CrossSectionStats(
            mean_return_pct=round(statistics.mean(returns), 2),
            median_return_pct=round(statistics.median(returns), 2),
            stdev_pct=round(stdev, 2),
            skewness=self._skewness(returns),
            excess_kurtosis=self._excess_kurtosis(returns),
            advance_decline_ratio=ad_ratio,
            breadth_pct_positive=breadth_pos,
            dispersion_label=disp_label,
        )

    def _cross_section_zscores(self, sectors: list[SeriesStats], cs: CrossSectionStats) -> None:
        if cs.stdev_pct == 0:
            return
        for s in sectors:
            if s.return_1d_pct is not None:
                s.cross_section_z = round(
                    (s.return_1d_pct - cs.mean_return_pct) / cs.stdev_pct, 2
                )

    def _correlation_matrix(
        self, return_series: dict[str, list[float]]
    ) -> list[CorrelationPair]:
        pairs: list[CorrelationPair] = []
        symbols = sorted(return_series)
        for i, sym_a in enumerate(symbols):
            for sym_b in symbols[i + 1:]:
                corr = self._correlation(return_series[sym_a], return_series[sym_b])
                if corr is None:
                    continue
                if corr >= 0.85:
                    label = "very high — clustered factor risk"
                elif corr >= 0.6:
                    label = "elevated — correlated beta"
                elif corr <= 0.2:
                    label = "low — diversifier"
                else:
                    label = "moderate"
                pairs.append(CorrelationPair(sym_a, sym_b, corr, label))
        pairs.sort(key=lambda p: -abs(p.correlation))
        return pairs[:12]

    def _outlier_movers(
        self,
        gainers: list[dict[str, Any]],
        losers: list[dict[str, Any]],
    ) -> list[OutlierMover]:
        movers = gainers + losers
        pcts = [m["day_chg_pct"] for m in movers if m.get("day_chg_pct") is not None]
        if len(pcts) < 4:
            return []
        mean = statistics.mean(pcts)
        stdev = statistics.stdev(pcts)
        if stdev == 0:
            return []
        outliers: list[OutlierMover] = []
        for m in movers:
            pct = m.get("day_chg_pct")
            if pct is None:
                continue
            z = (pct - mean) / stdev
            if abs(z) >= 1.8:
                outliers.append(OutlierMover(
                    symbol=m["symbol"],
                    name=m["name"],
                    day_chg_pct=pct,
                    z_score_mover=round(z, 2),
                    direction="gainer" if pct > 0 else "loser",
                ))
        outliers.sort(key=lambda o: -abs(o.z_score_mover))
        return outliers[:8]

    def _assessment(
        self,
        indices: list[SeriesStats],
        sectors: list[SeriesStats],
        cs: CrossSectionStats,
        correlations: list[CorrelationPair],
        spy_closes: list[float],
        outliers: list[OutlierMover],
    ) -> StatisticalAssessment:
        spy = next((i for i in indices if i.symbol == "^GSPC"), None)
        vix = next((i for i in indices if i.symbol == "^VIX"), None)

        if cs.mean_return_pct > 0.5 and cs.breadth_pct_positive >= 60:
            regime = "statistically bullish — positive cross-sectional drift with broad participation"
        elif cs.mean_return_pct < -0.5 and cs.breadth_pct_positive <= 40:
            regime = "statistically bearish — negative drift with weak breadth"
        else:
            regime = "neutral — returns near cross-sectional mean with mixed breadth"

        spy_daily = self._returns(spy_closes) if len(spy_closes) > 21 else []
        if spy_daily:
            vol_20 = self._ann_vol(spy_daily, 20) or 0
            vol_60 = self._ann_vol(spy_daily, min(60, len(spy_daily))) or vol_20
            if vol_20 > vol_60 * 1.15:
                vol_regime = f"elevated realized vol ({vol_20:.1f}% vs {vol_60:.1f}% 60d baseline)"
            elif vol_20 < vol_60 * 0.85:
                vol_regime = f"compressed vol ({vol_20:.1f}% — below {vol_60:.1f}% baseline)"
            else:
                vol_regime = f"normal vol regime ({vol_20:.1f}% annualized)"
        else:
            vol_regime = "volatility data limited"

        if cs.advance_decline_ratio >= 2.0:
            breadth = f"strong advance/decline ({cs.advance_decline_ratio:.1f}x gainers vs losers sample)"
        elif cs.advance_decline_ratio <= 0.5:
            breadth = f"weak breadth ({cs.advance_decline_ratio:.1f}x — decliners dominating)"
        else:
            breadth = f"balanced A/D ratio ({cs.advance_decline_ratio:.1f}x)"

        dispersion = (
            f"sector σ={cs.stdev_pct:.2f}%, skew={cs.skewness:+.2f}, "
            f"kurtosis={cs.excess_kurtosis:+.2f} — {cs.dispersion_label}"
        )

        if correlations:
            top = correlations[0]
            corr_struct = (
                f"highest pair {top.symbol_a}/{top.symbol_b} "
                f"ρ={top.correlation:+.2f} ({top.label})"
            )
        else:
            corr_struct = "correlation structure unavailable"

        if abs(cs.excess_kurtosis) > 1.0 or abs(cs.skewness) > 0.8:
            tail = "fat tails or skew detected in sector return distribution"
        else:
            tail = "return distribution near normal — limited tail risk signal"

        trend = self._linear_trend(spy_closes) if spy_closes else None
        if trend:
            slope_pct, r2 = trend
            if slope_pct > 1.0 and r2 > 0.5:
                trend_sig = f"uptrend slope +{slope_pct:.1f}% over 20d (R²={r2:.2f})"
            elif slope_pct < -1.0 and r2 > 0.5:
                trend_sig = f"downtrend slope {slope_pct:.1f}% over 20d (R²={r2:.2f})"
            else:
                trend_sig = f"weak trend (slope {slope_pct:+.1f}%, R²={r2:.2f})"
        else:
            trend_sig = "trend regression unavailable"

        if outliers:
            top_o = outliers[0]
            edge = (
                f"statistical outlier {top_o.symbol} z={top_o.z_score_mover:+.2f} "
                f"({top_o.day_chg_pct:+.2f}%) — investigate mean-reversion vs momentum"
            )
        elif spy and spy.z_score_20d is not None and abs(spy.z_score_20d) >= 1.2:
            edge = f"S&P 500 z-score {spy.z_score_20d:+.2f} vs 20d mean — reversion watch"
        else:
            edge = "no extreme statistical outliers on current tape"

        if vix and vix.return_1d_pct is not None and vix.return_1d_pct > 5:
            regime = "risk-off statistical regime — VIX spike elevates tail risk"
            tail = f"VIX +{vix.return_1d_pct:.2f}% — fear premium rising"

        return StatisticalAssessment(
            market_regime=regime,
            volatility_regime=vol_regime,
            breadth_signal=breadth,
            dispersion_signal=dispersion,
            correlation_structure=corr_struct,
            tail_risk_signal=tail,
            trend_signal=trend_sig,
            mathematical_edge=edge,
        )

    @staticmethod
    def _norm_score(value: float | None, center: float = 0.0, scale: float = 2.0) -> float:
        if value is None:
            return 0.5
        return round(max(0.0, min(1.0, 0.5 + ((value - center) / scale) * 0.25)), 4)

    def _expert_summary(
        self,
        assessment: StatisticalAssessment,
        cs: CrossSectionStats,
        regime_label: str,
        statistical_score: float,
        sectors: list[SeriesStats],
    ) -> str:
        leader = max(sectors, key=lambda s: s.return_1d_pct or -999) if sectors else None
        laggard = min(sectors, key=lambda s: s.return_1d_pct or 999) if sectors else None
        lead_txt = (
            f"{leader.name} z={leader.cross_section_z}" if leader and leader.cross_section_z else "n/a"
        )
        lag_txt = (
            f"{laggard.name} z={laggard.cross_section_z}" if laggard and laggard.cross_section_z else "n/a"
        )
        return (
            f"Yahoo Finance statistical scan: {regime_label} (score {statistical_score:.2f}). "
            f"{assessment.market_regime}. "
            f"Cross-section: μ={cs.mean_return_pct:+.2f}%, σ={cs.stdev_pct:.2f}%, "
            f"{cs.breadth_pct_positive:.0f}% sectors positive. "
            f"{assessment.breadth_signal}. "
            f"{assessment.volatility_regime}. "
            f"{assessment.trend_signal}. "
            f"Outlier leader {lead_txt}; laggard {lag_txt}. "
            f"Edge: {assessment.mathematical_edge}."
        )

    def analyze(self) -> FinancialDataReport:
        price_data: dict[str, list[float]] = {}
        series_rows: list[SeriesStats] = []

        for symbol in self.symbols:
            closes = self._fetch_closes(symbol)
            if closes:
                price_data[symbol] = closes
            name = US_INDICES.get(symbol) or SECTOR_ETFS.get(symbol) or "S&P 500 ETF"
            row = self._build_series(symbol, name, closes)
            if row:
                series_rows.append(row)
            time.sleep(self.delay_seconds)

        return_series = {
            sym: self._returns(closes)
            for sym, closes in price_data.items()
            if len(closes) > 5
        }
        spy_returns = return_series.get(BENCHMARK, return_series.get("^GSPC", []))

        for row in series_rows:
            sym_returns = return_series.get(row.symbol, [])
            if sym_returns and spy_returns:
                row.beta_spy = self._beta(sym_returns, spy_returns)

        indices = [s for s in series_rows if s.symbol in US_INDICES]
        sectors = [s for s in series_rows if s.symbol in SECTOR_ETFS]
        sectors.sort(key=lambda s: s.return_1d_pct or -999, reverse=True)

        gainers = self._fetch_screener("day_gainers", 15)
        time.sleep(self.delay_seconds)
        losers = self._fetch_screener("day_losers", 15)
        time.sleep(self.delay_seconds)
        trending = self._fetch_trending()

        cs = self._cross_section_stats(sectors, gainers, losers)
        self._cross_section_zscores(sectors, cs)
        sector_returns = {s.symbol: return_series[s.symbol] for s in sectors if s.symbol in return_series}
        correlations = self._correlation_matrix(sector_returns)
        outliers = self._outlier_movers(gainers, losers)

        spy_closes = price_data.get(BENCHMARK, price_data.get("^GSPC", []))
        assessment = self._assessment(indices, sectors, cs, correlations, spy_closes, outliers)

        statistical_score = round(
            0.35 * self._norm_score(cs.mean_return_pct, 0, 1.5)
            + 0.25 * self._norm_score(cs.breadth_pct_positive, 50, 30)
            + 0.20 * self._norm_score(cs.advance_decline_ratio, 1.0, 2.0)
            + 0.20 * (1.0 - self._norm_score(cs.stdev_pct, 1.0, 2.0)),
            4,
        )
        breadth_score = self._norm_score(cs.breadth_pct_positive, 50, 25)
        vol_score = 0.5
        spy_row = next((s for s in series_rows if s.symbol in (BENCHMARK, "^GSPC")), None)
        if spy_row and spy_row.vol_20d_ann_pct is not None:
            vol_score = round(max(0.0, min(1.0, 1.0 - spy_row.vol_20d_ann_pct / 40)), 4)

        if statistical_score >= 0.62:
            regime_label = "Statistically Bullish"
        elif statistical_score <= 0.38:
            regime_label = "Statistically Bearish"
        else:
            regime_label = "Statistically Neutral"

        summary = self._expert_summary(assessment, cs, regime_label, statistical_score, sectors)
        signals = self._market_signals(sectors, cs, outliers, indices, statistical_score)
        recs = self._recommendations(assessment, cs, sectors, correlations, outliers, gainers, losers, trending)

        return FinancialDataReport(
            indices=indices,
            sectors=sectors,
            cross_section=cs,
            correlations=correlations,
            outliers=outliers,
            top_gainers=gainers[:10],
            top_losers=losers[:10],
            trending=trending[:10],
            assessment=assessment,
            statistical_score=statistical_score,
            breadth_score=breadth_score,
            volatility_score=vol_score,
            regime_label=regime_label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source="Yahoo Finance API",
        )

    @staticmethod
    def _market_signals(
        sectors: list[SeriesStats],
        cs: CrossSectionStats,
        outliers: list[OutlierMover],
        indices: list[SeriesStats],
        statistical_score: float,
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal, cross_section_confidence

        signals: list[dict[str, Any]] = []

        if statistical_score >= 0.55 or statistical_score <= 0.45:
            bias = (
                "BULLISH" if statistical_score >= 0.6 else
                "BEARISH" if statistical_score <= 0.4 else
                "NEUTRAL"
            )
            signals.append(
                build_market_signal(
                    sector="Cross-Sectional Breadth",
                    tickers=["SPY", "RSP", "IWM"],
                    bias=bias,
                    reason=(
                        f"μ={cs.mean_return_pct:+.2f}%, {cs.breadth_pct_positive:.0f}% sectors up, "
                        f"A/D {cs.advance_decline_ratio:.1f}x"
                    ),
                    confidence=cross_section_confidence(
                        statistical_score,
                        breadth_pct=cs.breadth_pct_positive,
                    ),
                    evidence={"statistical_score": round(statistical_score, 3)},
                )
            )

        if sectors:
            z_leader = max(sectors, key=lambda s: s.cross_section_z or -999)
            if z_leader.cross_section_z and z_leader.cross_section_z >= 1.6:
                signals.append(
                    build_market_signal(
                        sector=f"Statistical Outperformer — {z_leader.name}",
                        tickers=[z_leader.symbol],
                        bias="BULLISH",
                        reason=f"Cross-section z={z_leader.cross_section_z:+.2f} vs sector peers",
                        confidence=cross_section_confidence(
                            statistical_score,
                            z_score=z_leader.cross_section_z,
                        ),
                    )
                )
            z_laggard = min(sectors, key=lambda s: s.cross_section_z or 999)
            if z_laggard.cross_section_z and z_laggard.cross_section_z <= -1.6:
                signals.append(
                    build_market_signal(
                        sector=f"Statistical Laggard — {z_laggard.name}",
                        tickers=[z_laggard.symbol],
                        bias="BEARISH",
                        reason=f"Cross-section z={z_laggard.cross_section_z:+.2f} — relative weakness",
                        confidence=cross_section_confidence(
                            statistical_score,
                            z_score=z_laggard.cross_section_z,
                        ),
                    )
                )

        for o in outliers[:2]:
            if abs(o.z_score_mover) >= 1.8:
                signals.append(
                    build_market_signal(
                        sector=f"Mover Outlier ({o.direction})",
                        tickers=[o.symbol],
                        bias="BULLISH" if o.day_chg_pct > 0 else "BEARISH",
                        reason=f"{o.symbol} mover z={o.z_score_mover:+.2f} ({o.day_chg_pct:+.2f}%)",
                        confidence=cross_section_confidence(
                            statistical_score,
                            z_score=o.z_score_mover,
                        ),
                    )
                )

        vix = next((i for i in indices if i.symbol == "^VIX"), None)
        if vix and vix.z_score_20d is not None and vix.z_score_20d >= 1.4:
            signals.append(
                build_market_signal(
                    sector="Volatility Hedge",
                    tickers=["VIXY", "UVXY", "GLD"],
                    bias="BULLISH",
                    reason=f"VIX z-score {vix.z_score_20d:+.2f} — fear elevated vs 20d",
                    confidence=cross_section_confidence(statistical_score, z_score=vix.z_score_20d),
                )
            )

        if not signals:
            signals.append(
                build_market_signal(
                    sector="Statistical Neutral",
                    tickers=["SPY"],
                    bias="NEUTRAL",
                    reason="No significant statistical edge detected",
                    confidence=0.42,
                )
            )
        return signals

    @staticmethod
    def _recommendations(
        assessment: StatisticalAssessment,
        cs: CrossSectionStats,
        sectors: list[SeriesStats],
        correlations: list[CorrelationPair],
        outliers: list[OutlierMover],
        gainers: list[dict[str, Any]],
        losers: list[dict[str, Any]],
        trending: list[str],
    ) -> list[str]:
        recs = [
            assessment.market_regime,
            assessment.volatility_regime,
            assessment.breadth_signal,
            assessment.dispersion_signal,
            assessment.correlation_structure,
            assessment.tail_risk_signal,
            assessment.trend_signal,
            assessment.mathematical_edge,
            (
                f"Cross-section: mean {cs.mean_return_pct:+.2f}%, median {cs.median_return_pct:+.2f}%, "
                f"σ {cs.stdev_pct:.2f}%, skew {cs.skewness:+.2f}, kurtosis {cs.excess_kurtosis:+.2f}"
            ),
        ]
        for rank, s in enumerate(sectors[:3], 1):
            recs.append(
                f"Sector #{rank} {s.name} ({s.symbol}): "
                f"1d {s.return_1d_pct:+.2f}%, cross-z {s.cross_section_z}, "
                f"β={s.beta_spy}, 20d z={s.z_score_20d}"
            )
        if correlations:
            c = correlations[0]
            recs.append(f"Top sector correlation: {c.symbol_a}/{c.symbol_b} ρ={c.correlation:+.2f}")
        if outliers:
            recs.append(
                "Statistical outliers: "
                + ", ".join(f"{o.symbol} z={o.z_score_mover:+.2f}" for o in outliers[:4])
            )
        if gainers:
            recs.append(
                "Yahoo gainers: "
                + ", ".join(f"{g['symbol']} {g['day_chg_pct']:+.2f}%" for g in gainers[:5])
            )
        if losers:
            recs.append(
                "Yahoo losers: "
                + ", ".join(f"{l['symbol']} {l['day_chg_pct']:+.2f}%" for l in losers[:5])
            )
        if trending:
            recs.append(f"Yahoo trending: {', '.join(trending[:5])}")
        return recs

    def to_dict(self, report: FinancialDataReport) -> dict[str, Any]:
        a = report.assessment
        cs = report.cross_section

        def series_dict(s: SeriesStats) -> dict[str, Any]:
            return {
                "symbol": s.symbol,
                "name": s.name,
                "last_price": s.last_price,
                "return_1d_pct": s.return_1d_pct,
                "return_5d_pct": s.return_5d_pct,
                "return_20d_pct": s.return_20d_pct,
                "vol_20d_ann_pct": s.vol_20d_ann_pct,
                "z_score_20d": s.z_score_20d,
                "cross_section_z": s.cross_section_z,
                "beta_spy": s.beta_spy,
            }

        return {
            "meta": {
                "agent": "Yahoo Finance Statistical Analyst",
                "dashboard": DASHBOARD_URL,
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "data_sources": ["Yahoo Finance Chart API", "Yahoo Finance Screener", "Yahoo Trending"],
                "expert_summary": report.expert_summary,
            },
            "dashboard_views": YAHOO_FINANCE_VIEWS,
            "statistical_assessment": {
                "market_regime": a.market_regime,
                "volatility_regime": a.volatility_regime,
                "breadth_signal": a.breadth_signal,
                "dispersion_signal": a.dispersion_signal,
                "correlation_structure": a.correlation_structure,
                "tail_risk_signal": a.tail_risk_signal,
                "trend_signal": a.trend_signal,
                "mathematical_edge": a.mathematical_edge,
            },
            "cross_section": {
                "mean_return_pct": cs.mean_return_pct,
                "median_return_pct": cs.median_return_pct,
                "stdev_pct": cs.stdev_pct,
                "skewness": cs.skewness,
                "excess_kurtosis": cs.excess_kurtosis,
                "advance_decline_ratio": cs.advance_decline_ratio,
                "breadth_pct_positive": cs.breadth_pct_positive,
                "dispersion_label": cs.dispersion_label,
            },
            "indices": [series_dict(i) for i in report.indices],
            "sectors": [series_dict(s) for s in report.sectors],
            "correlations": [
                {
                    "symbol_a": c.symbol_a,
                    "symbol_b": c.symbol_b,
                    "correlation": c.correlation,
                    "label": c.label,
                }
                for c in report.correlations
            ],
            "statistical_outliers": [
                {
                    "symbol": o.symbol,
                    "name": o.name,
                    "day_chg_pct": o.day_chg_pct,
                    "z_score_mover": o.z_score_mover,
                    "direction": o.direction,
                }
                for o in report.outliers
            ],
            "top_gainers": report.top_gainers,
            "top_losers": report.top_losers,
            "trending": report.trending,
            "metrics": {
                "statistical_score": report.statistical_score,
                "breadth_score": report.breadth_score,
                "volatility_score": report.volatility_score,
                "regime_label": report.regime_label,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            views_path = output.parent / "yahoo_finance_views.json"
            views_path.write_text(
                json.dumps(YAHOO_FINANCE_VIEWS, indent=2),
                encoding="utf-8",
            )
        return result


def run_financial_data_analysis(output: Path | None = None) -> dict[str, Any]:
    return YahooFinanceStatisticalAnalyst().run(output=output)