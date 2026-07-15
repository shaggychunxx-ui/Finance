"""
Consumer Sentiment Analyst Agent
================================
Tracks the University of Michigan Surveys of Consumers (SCA) — the Index of
Consumer Sentiment (ICS), Current Economic Conditions (ICC), and Index of
Consumer Expectations (ICE) — and maps sentiment regime/momentum to
consumer-facing market sectors.

Data: sca.isr.umich.edu / data.sca.isr.umich.edu monthly tables (+ calibrated
proxy fallback since sca.isr.umich.edu is DNS-blocked in the sandbox).
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agents.base import BaseExpert

HEADERS = {"User-Agent": "Finance-ConsumerSentiment-Analyst/1.0 (shaggychunxx@gmail.com)"}

SCA_TABLE_CSV_URL = "https://data.sca.isr.umich.edu/data-archive/mine.php"

SCA_RESOURCES: list[dict[str, Any]] = [
    {
        "id": "sca_home",
        "name": "Surveys of Consumers (SCA)",
        "provider": "University of Michigan",
        "url": "https://www.sca.isr.umich.edu/",
        "coverage": "US households, monthly since 1978 (quarterly since 1952)",
        "access": "web",
        "api_key_required": False,
        "data_types": ["sentiment index", "expectations", "current conditions"],
        "notes": "Home page for the Surveys of Consumers program",
    },
    {
        "id": "sca_tables",
        "name": "Tables and CSVs",
        "provider": "University of Michigan",
        "url": "https://www.sca.isr.umich.edu/tables.html",
        "coverage": "Monthly/quarterly/yearly ICS, ICC, ICE tables",
        "access": "web",
        "api_key_required": False,
        "data_types": ["csv", "historical time series"],
        "notes": "Primary landing page for downloadable index tables",
    },
    {
        "id": "sca_data_archive",
        "name": "Data Archive",
        "provider": "University of Michigan",
        "url": "https://data.sca.isr.umich.edu/",
        "coverage": "Full historical microdata and index archive",
        "access": "web",
        "api_key_required": False,
        "data_types": ["csv", "microdata", "codebooks"],
        "notes": "Structured archive powering the public CSV downloads",
    },
    {
        "id": "sca_chart",
        "name": "Chart: Index of Consumer Sentiment",
        "provider": "University of Michigan",
        "url": "https://www.sca.isr.umich.edu/",
        "coverage": "ICS trend chart, most recent release",
        "access": "web",
        "api_key_required": False,
        "data_types": ["chart"],
        "notes": "Headline chart displayed on the SCA home page",
    },
    {
        "id": "sca_news_release",
        "name": "Press Release / Commentary",
        "provider": "University of Michigan",
        "url": "https://www.sca.isr.umich.edu/",
        "coverage": "Monthly release commentary by survey director",
        "access": "web",
        "api_key_required": False,
        "data_types": ["press release", "commentary"],
        "notes": "Narrative context accompanying each monthly release",
    },
    {
        "id": "fred_umcsent",
        "name": "FRED — UMCSENT",
        "provider": "Federal Reserve Bank of St. Louis",
        "url": "https://fred.stlouisfed.org/series/UMCSENT",
        "coverage": "Index of Consumer Sentiment, 1952+",
        "access": "api",
        "api_key_required": False,
        "data_types": ["time series", "csv", "json"],
        "notes": "Mirrors the SCA headline index for programmatic access",
    },
]

# Calibrated proxy monthly series (oldest -> newest) used when the live SCA
# data archive cannot be reached (sandboxed/DNS-blocked environments).
# Values approximate the publicly reported Index of Consumer Sentiment (ICS),
# Current Economic Conditions (ICC), and Index of Consumer Expectations (ICE).
PROXY_MONTHLY_SERIES: list[dict[str, Any]] = [
    {"month": "2025-01", "ics": 71.1, "icc": 74.0, "ice": 69.3},
    {"month": "2025-02", "ics": 64.7, "icc": 65.7, "ice": 64.0},
    {"month": "2025-03", "ics": 57.0, "icc": 63.8, "ice": 52.6},
    {"month": "2025-04", "ics": 52.2, "icc": 59.8, "ice": 47.3},
    {"month": "2025-05", "ics": 52.2, "icc": 58.9, "ice": 47.9},
    {"month": "2025-06", "ics": 60.7, "icc": 64.8, "ice": 58.1},
    {"month": "2025-07", "ics": 61.7, "icc": 68.0, "ice": 57.7},
    {"month": "2025-08", "ics": 58.2, "icc": 61.7, "ice": 55.9},
    {"month": "2025-09", "ics": 55.1, "icc": 60.4, "ice": 51.7},
    {"month": "2025-10", "ics": 53.6, "icc": 59.7, "ice": 49.9},
    {"month": "2025-11", "ics": 51.0, "icc": 56.6, "ice": 47.5},
    {"month": "2025-12", "ics": 53.3, "icc": 58.8, "ice": 49.6},
]

SENTIMENT_REGIMES: list[tuple[float, str]] = [
    (55.0, "distressed"),
    (70.0, "weak"),
    (85.0, "neutral"),
    (100.0, "improving"),
    (float("inf"), "robust"),
]

SECTOR_TICKERS: dict[str, list[str]] = {
    "consumer-discretionary": ["XLY", "AMZN", "HD", "MCD"],
    "consumer-staples": ["XLP", "PG", "KO", "WMT"],
    "retail": ["XRT", "TGT", "COST"],
    "travel-leisure": ["JETS", "BKNG", "CCL"],
    "broad-market": ["SPY"],
}


@dataclass
class SentimentDataPoint:
    month: str
    ics: float
    icc: float
    ice: float


@dataclass
class SentimentReport:
    resources: list[dict[str, Any]]
    resources_online: int
    series: list[SentimentDataPoint]
    latest_month: str
    latest_ics: float
    latest_icc: float
    latest_ice: float
    trailing_avg_ics: float
    momentum_pct: float
    regime_label: str
    sentiment_score: float
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ConsumerSentimentAnalyst(BaseExpert):
    """Consumer Sentiment Analyst — University of Michigan Surveys of Consumers."""

    def __init__(self, *, pipeline_context: dict | None = None) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="consumer-sentiment")

    def _check_resource_health(self, resource: dict[str, Any]) -> dict[str, Any]:
        entry = dict(resource)
        url = resource.get("url", "")
        status = "unknown"
        try:
            resp = requests.head(url, headers=HEADERS, timeout=5, allow_redirects=True)
            if resp.status_code < 400:
                status = "online"
            elif resp.status_code == 403:
                status = "restricted"
            else:
                status = "offline"
        except Exception:
            status = "offline"
        entry["health"] = status
        return entry

    def _catalog_resources(self) -> list[dict[str, Any]]:
        return [self._check_resource_health(res) for res in SCA_RESOURCES]

    @staticmethod
    def _parse_sca_csv(raw_text: str) -> list[dict[str, Any]]:
        """Best-effort parse of an SCA/FRED-style monthly CSV export."""
        rows: list[dict[str, Any]] = []
        try:
            reader = csv.reader(io.StringIO(raw_text))
            for row in reader:
                if len(row) < 2:
                    continue
                month, *values = row
                try:
                    ics = float(values[0])
                except (ValueError, IndexError):
                    continue
                icc = float(values[1]) if len(values) > 1 else ics
                ice = float(values[2]) if len(values) > 2 else ics
                rows.append({"month": month.strip(), "ics": ics, "icc": icc, "ice": ice})
        except Exception:
            return []
        return rows

    def _fetch_series(self) -> tuple[list[dict[str, Any]], list[str]]:
        try:
            resp = requests.get(SCA_TABLE_CSV_URL, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            parsed = self._parse_sca_csv(resp.text)
            if parsed:
                return parsed, ["Surveys of Consumers data archive"]
        except Exception:
            pass
        return list(PROXY_MONTHLY_SERIES), ["Calibrated proxy series (sca.isr.umich.edu unreachable)"]

    @staticmethod
    def _classify_regime(value: float) -> str:
        for threshold, label in SENTIMENT_REGIMES:
            if value < threshold:
                return label
        return "robust"

    def _market_signals(
        self,
        regime: str,
        momentum_pct: float,
        latest_ics: float,
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal

        signals: list[dict[str, Any]] = []

        if regime in ("distressed", "weak"):
            bias = "BEARISH" if regime == "distressed" else "NEUTRAL"
            signals.append(
                build_market_signal(
                    sector="Consumer Discretionary",
                    tickers=SECTOR_TICKERS["consumer-discretionary"],
                    bias=bias,
                    reason=(
                        f"ICS at {latest_ics:.1f} ({regime}) signals weaker discretionary "
                        f"spending appetite"
                    ),
                    confidence=self.adjust_signal_confidence(
                        SECTOR_TICKERS["consumer-discretionary"][0],
                        bias,
                        min(0.8, 0.45 + (70 - latest_ics) / 100),
                    ),
                )
            )
            signals.append(
                build_market_signal(
                    sector="Consumer Staples (Defensive)",
                    tickers=SECTOR_TICKERS["consumer-staples"],
                    bias="BULLISH" if regime == "distressed" else "NEUTRAL",
                    reason=f"Weak sentiment ({regime}) favors defensive rotation into staples",
                    confidence=self.adjust_signal_confidence(
                        SECTOR_TICKERS["consumer-staples"][0],
                        "BULLISH",
                        0.55,
                    ),
                )
            )
        elif regime in ("improving", "robust"):
            bias = "BULLISH"
            signals.append(
                build_market_signal(
                    sector="Consumer Discretionary",
                    tickers=SECTOR_TICKERS["consumer-discretionary"],
                    bias=bias,
                    reason=f"ICS at {latest_ics:.1f} ({regime}) supports discretionary spending",
                    confidence=self.adjust_signal_confidence(
                        SECTOR_TICKERS["consumer-discretionary"][0],
                        bias,
                        min(0.82, 0.5 + (latest_ics - 85) / 100),
                    ),
                )
            )
            signals.append(
                build_market_signal(
                    sector="Travel & Leisure",
                    tickers=SECTOR_TICKERS["travel-leisure"],
                    bias=bias,
                    reason="Improving consumer sentiment tends to lift discretionary travel demand",
                    confidence=self.adjust_signal_confidence(
                        SECTOR_TICKERS["travel-leisure"][0],
                        bias,
                        0.58,
                    ),
                )
            )
        else:
            signals.append(
                build_market_signal(
                    sector="Retail",
                    tickers=SECTOR_TICKERS["retail"],
                    bias="NEUTRAL",
                    reason=f"ICS at {latest_ics:.1f} sits in a neutral band",
                    confidence=0.45,
                )
            )

        if abs(momentum_pct) >= 8.0:
            bias = "BULLISH" if momentum_pct > 0 else "BEARISH"
            signals.append(
                build_market_signal(
                    sector="Broad Market",
                    tickers=SECTOR_TICKERS["broad-market"],
                    bias=bias,
                    reason=(
                        f"Sentiment momentum {momentum_pct:+.1f}% vs trailing average — "
                        "consumer mood shifting sharply"
                    ),
                    confidence=min(0.75, 0.4 + abs(momentum_pct) / 40),
                )
            )

        return signals

    def analyze(self) -> SentimentReport:
        raw_series, sources = self._fetch_series()
        series = [
            SentimentDataPoint(
                month=str(row["month"]),
                ics=float(row["ics"]),
                icc=float(row["icc"]),
                ice=float(row["ice"]),
            )
            for row in raw_series
        ]
        series.sort(key=lambda d: d.month)

        resources = self._catalog_resources()
        resources_online = sum(1 for r in resources if r.get("health") == "online")

        latest = series[-1]
        trailing = series[-4:-1] if len(series) >= 4 else series[:-1]
        trailing_avg = sum(d.ics for d in trailing) / len(trailing) if trailing else latest.ics
        momentum_pct = ((latest.ics - trailing_avg) / trailing_avg) * 100 if trailing_avg else 0.0

        regime = self._classify_regime(latest.ics)
        # Sentiment score normalized ~0-1 against a 40-110 historical band.
        sentiment_score = max(0.0, min(1.0, (latest.ics - 40) / 70))

        summary = (
            f"University of Michigan Index of Consumer Sentiment at {latest.ics:.1f} "
            f"({latest.month}), regime: {regime}. Current conditions {latest.icc:.1f}, "
            f"expectations {latest.ice:.1f}. Momentum {momentum_pct:+.1f}% vs trailing "
            f"3-month average of {trailing_avg:.1f}. Source: {', '.join(sources)}."
        )

        signals = self._market_signals(regime, momentum_pct, latest.ics)
        recs = [
            summary,
            f"ICS {latest.ics:.1f} | ICC {latest.icc:.1f} | ICE {latest.ice:.1f} — regime: {regime}",
            f"Momentum vs trailing 3mo avg: {momentum_pct:+.1f}%",
            f"Resource catalog: {resources_online}/{len(resources)} SCA/FRED endpoints online",
        ]
        if regime in ("distressed", "weak"):
            recs.append("Consumer weakness — favor staples/defensives over discretionary")
        elif regime in ("improving", "robust"):
            recs.append("Consumer strength — discretionary and travel/leisure exposure supported")

        return SentimentReport(
            resources=resources,
            resources_online=resources_online,
            series=series,
            latest_month=latest.month,
            latest_ics=latest.ics,
            latest_icc=latest.icc,
            latest_ice=latest.ice,
            trailing_avg_ics=round(trailing_avg, 2),
            momentum_pct=round(momentum_pct, 2),
            regime_label=regime,
            sentiment_score=round(sentiment_score, 3),
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_sources=sources,
        )

    def to_dict(self, report: SentimentReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Consumer Sentiment Analyst",
                "analyzed_at": report.analyzed_at,
                "data_sources": report.data_sources,
                "expert_summary": report.expert_summary,
                "resources_cataloged": len(report.resources),
                "resources_online": report.resources_online,
            },
            "series": [
                {"month": d.month, "ics": d.ics, "icc": d.icc, "ice": d.ice}
                for d in report.series
            ],
            "metrics": {
                "latest_month": report.latest_month,
                "latest_ics": report.latest_ics,
                "latest_icc": report.latest_icc,
                "latest_ice": report.latest_ice,
                "trailing_avg_ics": report.trailing_avg_ics,
                "momentum_pct": report.momentum_pct,
                "regime_label": report.regime_label,
                "sentiment_score": report.sentiment_score,
            },
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        report = self.analyze()
        result = self.to_dict(report)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "sca_resources.json"
            catalog.write_text(
                json.dumps(report.resources, indent=2),
                encoding="utf-8",
            )
        return result


def run_consumer_sentiment_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return ConsumerSentimentAnalyst(pipeline_context=pipeline_context).run(output=output)
