"""
Sentiment & Alternative Data Agent — "The Psychology Tracker"
==============================================================
Mission: quantify mass human behavior, emotional escalation, and
retail/institutional momentum before it shows up on a stock chart.

API interfacing: subscribes to per-symbol Yahoo Finance headline RSS feeds
(a real-time financial news firehose that requires no API key) as a stand-in
for social/media web-scraping interfaces described in the spec.

Mathematical processing: headline text is tokenized and scored by a
lightweight, dependency-free FinBERT-style lexicon classifier, producing
three numeric matrices per symbol:
  1. Polarity Score        — direction of sentiment (-1.0 .. +1.0)
  2. Subjectivity Level    — factual vs speculative/hype language (0.0 .. 1.0)
  3. Volume Acceleration   — d/dt of headline chatter, comparing the newest
                              half of the fetched window against the older
                              half of the same window.

How it ensures accuracy: even when price consolidates sideways, a sudden
acceleration in positive mention velocity + high subjectivity is flagged as
a pending-breakout alert before the order book shifts.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import requests

from agents.base import BaseExpert

NEWS_RSS_API = "https://feeds.finance.yahoo.com/rss/2.0/headline"
HEADERS = {"User-Agent": "Finance-Sentiment-Tracker/1.0 (shaggychunxx@gmail.com)"}

WATCHLIST: dict[str, str] = {
    "AAPL": "Mega-cap tech",
    "TSLA": "High-beta EV/tech",
    "NVDA": "AI/semiconductor leader",
    "GME": "Retail-driven small/mid cap",
    "PLTR": "High-beta growth name",
    "COIN": "Crypto-adjacent equity",
    "AMD": "Semiconductor",
    "AMC": "Retail-driven small/mid cap",
}

# Lightweight lexicon standing in for a fine-tuned FinBERT classifier.
POSITIVE_WORDS = {
    "surge", "soar", "rally", "beat", "beats", "record", "upgrade", "bullish",
    "gain", "gains", "jump", "jumps", "outperform", "breakout", "strong",
    "profit", "growth", "buy", "buying", "boom", "rebound", "win", "wins",
}
NEGATIVE_WORDS = {
    "plunge", "plummet", "crash", "miss", "misses", "downgrade", "bearish",
    "loss", "losses", "fall", "falls", "drop", "drops", "slump", "sell",
    "selling", "recall", "lawsuit", "fraud", "warning", "cut", "cuts",
    "layoff", "layoffs", "investigation", "default", "bankrupt",
}
SPECULATIVE_WORDS = {
    "rumor", "rumored", "could", "might", "may", "speculat", "hype",
    "meme", "moonshot", "squeeze", "target", "forecast", "expects",
    "expected", "potential", "plans", "reportedly", "sources say",
}
FACTUAL_WORDS = {
    "reported", "filed", "announced", "quarter", "earnings", "revenue",
    "sec", "10-q", "10-k", "dividend", "results", "confirmed", "closed",
}

BREAKOUT_POLARITY_THRESHOLD = 0.35
BREAKOUT_ACCEL_THRESHOLD = 1.5  # ratio of newest-half to older-half mention density


@dataclass
class SentimentSnapshot:
    symbol: str
    name: str
    headline_count: int
    polarity_score: float
    subjectivity_level: float
    volume_acceleration: float
    breakout_alert: bool
    sample_headlines: list[str]
    rationale: str


@dataclass
class SentimentReport:
    snapshots: list[SentimentSnapshot]
    breakout_alerts: list[str]
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SentimentAltDataExpert(BaseExpert):
    """The 'psychology tracker' — quantifies chatter, tone, and acceleration."""

    def __init__(self) -> None:
        super().__init__()

    # -- data fetching -------------------------------------------------
    def _fetch_headlines(self, symbol: str) -> list[dict[str, Any]]:
        try:
            resp = requests.get(
                NEWS_RSS_API,
                params={"s": symbol, "region": "US", "lang": "en-US"},
                headers=HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except Exception:
            return []

        items: list[dict[str, Any]] = []
        for item in root.findall(".//item")[:30]:
            title_el = item.find("title")
            if title_el is None or not title_el.text:
                continue
            pub_el = item.find("pubDate")
            desc_el = item.find("description")
            items.append(
                {
                    "title": title_el.text.strip(),
                    "pub_date": self._parse_pub_date(pub_el.text if pub_el is not None else ""),
                    "description": (desc_el.text or "").strip() if desc_el is not None else "",
                }
            )
        return items

    @staticmethod
    def _parse_pub_date(raw: str) -> datetime:
        if not raw:
            return datetime.now(timezone.utc)
        try:
            return parsedate_to_datetime(raw)
        except Exception:
            return datetime.now(timezone.utc)

    # -- math ------------------------------------------------------------
    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[a-z']+", text.lower())

    def _score_headline(self, text: str) -> tuple[float, float]:
        """Return (polarity, subjectivity) for one headline+description blob."""
        tokens = self._tokenize(text)
        if not tokens:
            return 0.0, 0.0
        pos_hits = sum(1 for t in tokens if t in POSITIVE_WORDS)
        neg_hits = sum(1 for t in tokens if t in NEGATIVE_WORDS)
        spec_hits = sum(1 for t in tokens if any(t.startswith(s) for s in SPECULATIVE_WORDS))
        fact_hits = sum(1 for t in tokens if t in FACTUAL_WORDS)

        total_charged = pos_hits + neg_hits
        polarity = (pos_hits - neg_hits) / total_charged if total_charged else 0.0

        total_tone = spec_hits + fact_hits
        subjectivity = spec_hits / total_tone if total_tone else 0.3  # neutral default
        return polarity, subjectivity

    def _analyze_symbol(self, symbol: str, name: str) -> SentimentSnapshot | None:
        items = self._fetch_headlines(symbol)
        if not items:
            return None

        items.sort(key=lambda i: i["pub_date"], reverse=True)
        polarities: list[float] = []
        subjectivities: list[float] = []
        for item in items:
            blob = f"{item['title']} {item['description']}"
            pol, subj = self._score_headline(blob)
            polarities.append(pol)
            subjectivities.append(subj)

        polarity_score = round(sum(polarities) / len(polarities), 3) if polarities else 0.0
        subjectivity_level = round(sum(subjectivities) / len(subjectivities), 3) if subjectivities else 0.0

        # Volume Acceleration Vector: newest half density vs older half density,
        # using elapsed time spans as a proxy for d/dt of chatter.
        half = max(1, len(items) // 2)
        newest_half = items[:half]
        older_half = items[half:]
        if older_half:
            newest_span_hr = max(
                (newest_half[0]["pub_date"] - newest_half[-1]["pub_date"]).total_seconds() / 3600, 0.5
            )
            older_span_hr = max(
                (older_half[0]["pub_date"] - older_half[-1]["pub_date"]).total_seconds() / 3600, 0.5
            )
            newest_rate = len(newest_half) / newest_span_hr
            older_rate = len(older_half) / older_span_hr
            volume_acceleration = round(newest_rate / older_rate, 2) if older_rate else 1.0
        else:
            volume_acceleration = 1.0

        breakout_alert = (
            polarity_score >= BREAKOUT_POLARITY_THRESHOLD
            and volume_acceleration >= BREAKOUT_ACCEL_THRESHOLD
        )
        rationale = (
            f"Polarity {polarity_score:+.2f}, subjectivity {subjectivity_level:.2f}, "
            f"mention acceleration {volume_acceleration}x"
        )
        if breakout_alert:
            rationale += " — chatter acceleration + positive tone precede a possible breakout"

        return SentimentSnapshot(
            symbol=symbol,
            name=name,
            headline_count=len(items),
            polarity_score=polarity_score,
            subjectivity_level=subjectivity_level,
            volume_acceleration=volume_acceleration,
            breakout_alert=breakout_alert,
            sample_headlines=[i["title"] for i in items[:5]],
            rationale=rationale,
        )

    def _market_signals(self, snapshots: list[SentimentSnapshot]) -> list[dict[str, Any]]:
        signals = []
        for s in snapshots:
            if s.breakout_alert:
                signals.append(
                    {
                        "sector": s.name,
                        "bias": "bullish",
                        "tickers": [s.symbol],
                        "reason": f"Pending breakout signal — {s.rationale}",
                    }
                )
            elif s.polarity_score <= -BREAKOUT_POLARITY_THRESHOLD and s.volume_acceleration >= BREAKOUT_ACCEL_THRESHOLD:
                signals.append(
                    {
                        "sector": s.name,
                        "bias": "bearish",
                        "tickers": [s.symbol],
                        "reason": f"Negative chatter acceleration — {s.rationale}",
                    }
                )
        return signals

    def _recommendations(self, snapshots: list[SentimentSnapshot]) -> list[str]:
        recs = []
        for s in snapshots:
            if s.breakout_alert:
                recs.append(f"{s.symbol}: flag pending-breakout alert ahead of price confirmation.")
            elif s.subjectivity_level > 0.6:
                recs.append(f"{s.symbol}: chatter is speculative/hype-heavy — corroborate with fundamentals.")
            else:
                recs.append(f"{s.symbol}: sentiment stable, no escalation detected.")
        return recs

    def analyze(self) -> SentimentReport:
        snapshots: list[SentimentSnapshot] = []
        for symbol, name in WATCHLIST.items():
            snap = self._analyze_symbol(symbol, name)
            if snap:
                snapshots.append(snap)

        breakout_alerts = [s.symbol for s in snapshots if s.breakout_alert]
        expert_summary = (
            f"Scanned {len(snapshots)} symbols' headline chatter via polarity, subjectivity, "
            f"and mention-acceleration vectors. {len(breakout_alerts)} pending-breakout alert(s) detected."
        )

        return SentimentReport(
            snapshots=snapshots,
            breakout_alerts=breakout_alerts,
            expert_summary=expert_summary,
            market_signals=self._market_signals(snapshots),
            recommendations=self._recommendations(snapshots),
            data_source="Yahoo Finance per-symbol headline RSS feed",
        )

    def to_dict(self, report: SentimentReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Sentiment & Alternative Data Agent (The Psychology Tracker)",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
                "temperature": self.temperature,
            },
            "snapshots": [
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "headline_count": s.headline_count,
                    "polarity_score": s.polarity_score,
                    "subjectivity_level": s.subjectivity_level,
                    "volume_acceleration": s.volume_acceleration,
                    "breakout_alert": s.breakout_alert,
                    "sample_headlines": s.sample_headlines,
                    "rationale": s.rationale,
                }
                for s in report.snapshots
            ],
            "metrics": {
                "symbols_analyzed": len(report.snapshots),
                "breakout_alerts": report.breakout_alerts,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "sentiment_lexicon.json"
            catalog.write_text(
                json.dumps(
                    {
                        "positive_words": sorted(POSITIVE_WORDS),
                        "negative_words": sorted(NEGATIVE_WORDS),
                        "speculative_words": sorted(SPECULATIVE_WORDS),
                        "factual_words": sorted(FACTUAL_WORDS),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        return result


def run_sentiment_alt_data_analysis(output: Path | None = None) -> dict[str, Any]:
    return SentimentAltDataExpert().run(output=output)
