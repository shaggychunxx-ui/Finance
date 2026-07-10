"""
Geopolitics Expert Agent
========================
Expert geopolitical risk analysis from global news feeds and theater monitoring.

Primary data: BBC World RSS, NPR World RSS, Al Jazeera RSS, France 24 RSS,
NHK World RSS, DW RSS, GDELT DOC API (rate-limited, optional).
"""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agents.base import BaseExpert

HEADERS = {"User-Agent": "Finance-Geopolitics-Expert/1.0 (shaggychunxx@gmail.com)"}
GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

NEWS_FEEDS = [
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("NPR World", "https://feeds.npr.org/1004/rss.xml"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("France 24", "https://www.france24.com/en/rss"),
    ("NHK World", "https://www3.nhk.or.jp/nhkworld/en/news/rss/all.xml"),
    ("DW", "https://rss.dw.com/rdf/rss-en-all"),
]

THEATERS = {
    "ukraine_russia": {
        "name": "Ukraine / Russia",
        "keywords": [
            "ukraine", "russia", "kyiv", "kiev", "moscow", "crimea", "donbas",
            "zelensky", "putin", "nato",
        ],
        "weight": 1.0,
    },
    "middle_east": {
        "name": "Middle East",
        "keywords": [
            "israel", "gaza", "iran", "syria", "yemen", "lebanon", "hamas",
            "hezbollah", "saudi", "iraq", "damascus", "tehran",
        ],
        "weight": 1.0,
    },
    "china_taiwan": {
        "name": "China / Taiwan",
        "keywords": [
            "china", "taiwan", "beijing", "xi jinping", "south china sea",
            "semiconductor", "huawei",
        ],
        "weight": 0.9,
    },
    "trade_sanctions": {
        "name": "Trade / Sanctions",
        "keywords": [
            "sanction", "tariff", "trade war", "embargo", "export control",
            "decoupling",
        ],
        "weight": 0.85,
    },
    "energy_security": {
        "name": "Energy Security",
        "keywords": [
            "opec", "pipeline", "oil supply", "lng", "strait of hormuz",
            "energy crisis", "gas supply",
        ],
        "weight": 0.8,
    },
    "americas": {
        "name": "Americas",
        "keywords": [
            "venezuela", "cuba", "mexico border", "latin america", "brazil",
            "argentina",
        ],
        "weight": 0.7,
    },
}

ESCALATION_WORDS = {
    "attack", "strike", "bomb", "missile", "war", "invasion", "killed", "dead",
    "sanction", "escalat", "nuclear", "troops", "mobiliz", "blockade",
}
DEESCALATION_WORDS = {
    "ceasefire", "peace", "talks", "agreement", "deal", "truce", "diplomat",
    "negotiat", "de-escalat",
}


@dataclass
class NewsArticle:
    title: str
    source: str
    link: str
    published: str
    theaters: list[str] = field(default_factory=list)
    escalation_score: float = 0.0


@dataclass
class TheaterRisk:
    theater_id: str
    theater_name: str
    article_count: int
    escalation_score: float
    risk_score: float
    risk_label: str
    top_headlines: list[str] = field(default_factory=list)


@dataclass
class GeopoliticalAssessment:
    dominant_theater: str
    escalation_trend: str
    sanctions_pressure: str
    energy_flashpoint: str
    safe_haven_signal: str
    defense_spending_signal: str


@dataclass
class GeopoliticsReport:
    articles: list[NewsArticle]
    theaters: list[TheaterRisk]
    assessment: GeopoliticalAssessment
    global_risk_score: float
    escalation_index: float
    risk_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class GeopoliticsExpert(BaseExpert):
    """Expert geopolitical analyst — news-driven theater risk and market implications."""

    def __init__(
        self,
        use_gdelt: bool = True,
        *,
        pipeline_context: dict | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="geopolitics")
        self.use_gdelt = use_gdelt

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

    @staticmethod
    def _parse_rss(xml_bytes: bytes, source: str) -> list[NewsArticle]:
        articles: list[NewsArticle] = []
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError:
            return articles

        for item in root.findall(".//item")[:30]:
            title_el = item.find("title")
            link_el = item.find("link")
            pub_el = item.find("pubDate")
            if title_el is None or not title_el.text:
                continue
            title = title_el.text.strip()
            articles.append(NewsArticle(
                title=title,
                source=source,
                link=(link_el.text or "").strip() if link_el is not None else "",
                published=(pub_el.text or "").strip() if pub_el is not None else "",
            ))
        return articles

    def _fetch_news(self) -> tuple[list[NewsArticle], list[str]]:
        all_articles: list[NewsArticle] = []
        sources: list[str] = []

        for name, url in NEWS_FEEDS:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=30)
                resp.raise_for_status()
                parsed = self._parse_rss(resp.content, name)
                if parsed:
                    all_articles.extend(parsed)
                    sources.append(name)
            except Exception:
                continue

        if self.use_gdelt and len(all_articles) < 8:
            gdelt = self._fetch_gdelt_headlines()
            if gdelt:
                all_articles.extend(gdelt)
                sources.append("GDELT DOC API")

        if not all_articles:
            all_articles = self._proxy_headlines()
            sources.append("Calibrated headline proxy (feeds unavailable)")

        seen: set[str] = set()
        deduped: list[NewsArticle] = []
        for a in all_articles:
            key = a.title.lower()[:80]
            if key not in seen:
                seen.add(key)
                deduped.append(a)
        return deduped, sources

    def _fetch_gdelt_headlines(self) -> list[NewsArticle]:
        try:
            time.sleep(6)
            resp = requests.get(
                GDELT_DOC_URL,
                params={
                    "query": "(conflict OR sanctions OR geopolitical) sourcelang:english",
                    "mode": "ArtList",
                    "maxrecords": 15,
                    "format": "json",
                    "timespan": "3d",
                },
                headers=HEADERS,
                timeout=30,
            )
            if resp.status_code == 429 or not resp.text.strip().startswith("{"):
                return []
            data = resp.json()
            return [
                NewsArticle(
                    title=str(a.get("title", "")).strip(),
                    source=str(a.get("source", "GDELT")),
                    link=str(a.get("url", "")),
                    published=str(a.get("seendate", "")),
                )
                for a in data.get("articles", [])
                if a.get("title")
            ]
        except Exception:
            return []

    @staticmethod
    def _proxy_headlines() -> list[NewsArticle]:
        proxy_titles = [
            ("Russia launches large-scale strikes on Kyiv infrastructure", "Proxy"),
            ("Middle East tensions rise after regional security incident", "Proxy"),
            ("US considers new export controls on advanced semiconductors", "Proxy"),
            ("OPEC+ maintains production cuts amid demand uncertainty", "Proxy"),
            ("Latin America political shift raises commodity policy risk", "Proxy"),
            ("NATO allies increase defense spending commitments", "Proxy"),
            ("Global sanctions regime expands on energy sector entities", "Proxy"),
            ("Taiwan strait military exercises raise regional alert level", "Proxy"),
        ]
        return [
            NewsArticle(title=t, source=s, link="", published="")
            for t, s in proxy_titles
        ]

    @staticmethod
    def _escalation_score(text: str) -> float:
        lower = text.lower()
        esc = sum(1 for w in ESCALATION_WORDS if w in lower)
        deesc = sum(1 for w in DEESCALATION_WORDS if w in lower)
        raw = (esc - deesc * 0.5) / 4.0
        return round(max(0.0, min(1.0, 0.25 + raw)), 4)

    def _classify_article(self, article: NewsArticle) -> NewsArticle:
        lower = article.title.lower()
        matched: list[str] = []
        for tid, cfg in THEATERS.items():
            if any(kw in lower for kw in cfg["keywords"]):
                matched.append(tid)
        article.theaters = matched
        article.escalation_score = self._escalation_score(article.title)
        return article

    def _score_theaters(self, articles: list[NewsArticle]) -> list[TheaterRisk]:
        theater_articles: dict[str, list[NewsArticle]] = {tid: [] for tid in THEATERS}
        for a in articles:
            for tid in a.theaters:
                theater_articles[tid].append(a)

        risks: list[TheaterRisk] = []
        for tid, cfg in THEATERS.items():
            arts = theater_articles[tid]
            count = len(arts)
            esc = (
                sum(a.escalation_score for a in arts) / count if count else 0.0
            )
            weight = cfg["weight"]
            volume_score = min(1.0, count / 6.0)
            risk = round(min(1.0, volume_score * 0.45 + esc * 0.55) * weight, 4)
            label = (
                "Critical" if risk >= 0.75 else
                "Elevated" if risk >= 0.55 else
                "Moderate" if risk >= 0.35 else
                "Low"
            )
            risks.append(TheaterRisk(
                theater_id=tid,
                theater_name=cfg["name"],
                article_count=count,
                escalation_score=round(esc, 4),
                risk_score=risk,
                risk_label=label,
                top_headlines=[a.title for a in arts[:3]],
            ))
        return sorted(risks, key=lambda t: t.risk_score, reverse=True)

    def _global_risk(self, theaters: list[TheaterRisk], articles: list[NewsArticle]) -> float:
        if not theaters:
            return 0.3
        top_scores = [t.risk_score for t in theaters[:3]]
        avg_top = sum(top_scores) / len(top_scores)
        avg_esc = sum(a.escalation_score for a in articles) / max(len(articles), 1)
        return round(min(1.0, avg_top * 0.65 + avg_esc * 0.35), 4)

    def _escalation_index(self, articles: list[NewsArticle]) -> float:
        if not articles:
            return 0.3
        return round(
            sum(a.escalation_score for a in articles) / len(articles), 4
        )

    def _assessment(
        self, theaters: list[TheaterRisk], articles: list[NewsArticle]
    ) -> GeopoliticalAssessment:
        active = [t for t in theaters if t.article_count > 0]
        dominant = active[0] if active else theaters[0]

        esc_scores = [a.escalation_score for a in articles]
        avg_esc = sum(esc_scores) / max(len(esc_scores), 1)
        escalation_trend = (
            "rising — multiple escalation keywords in headlines"
            if avg_esc >= 0.55 else
            "stable — mixed headlines"
            if avg_esc >= 0.35 else
            "contained — limited escalation language"
        )

        sanctions = next((t for t in theaters if t.theater_id == "trade_sanctions"), None)
        sanctions_pressure = (
            f"active — {sanctions.article_count} trade/sanctions headlines"
            if sanctions and sanctions.article_count >= 2 else
            "moderate policy risk in background"
            if sanctions and sanctions.article_count >= 1 else
            "low immediate sanctions pressure"
        )

        energy = next((t for t in theaters if t.theater_id == "energy_security"), None)
        me = next((t for t in theaters if t.theater_id == "middle_east"), None)
        energy_flash = "stable supply outlook"
        if energy and energy.risk_score >= 0.45:
            energy_flash = f"energy security headlines active (risk {energy.risk_score:.2f})"
        elif me and me.risk_score >= 0.55:
            energy_flash = "Middle East tension — Hormuz / OPEC sensitivity elevated"

        global_risk = self._global_risk(theaters, articles)
        safe_haven = (
            "elevated — favor gold and long-duration Treasuries"
            if global_risk >= 0.60 else
            "neutral — no acute flight-to-quality signal"
        )

        ukraine = next((t for t in theaters if t.theater_id == "ukraine_russia"), None)
        defense_signal = "baseline NATO spending theme"
        if ukraine and ukraine.risk_score >= 0.50:
            defense_signal = f"Ukraine theater active — defense contractors in focus (risk {ukraine.risk_score:.2f})"
        elif global_risk >= 0.55:
            defense_signal = "Elevated global risk — defense spending tailwind"

        return GeopoliticalAssessment(
            dominant_theater=dominant.theater_name,
            escalation_trend=escalation_trend,
            sanctions_pressure=sanctions_pressure,
            energy_flashpoint=energy_flash,
            safe_haven_signal=safe_haven,
            defense_spending_signal=defense_signal,
        )

    def _expert_summary(
        self,
        assessment: GeopoliticalAssessment,
        global_risk: float,
        escalation: float,
        label: str,
        article_count: int,
    ) -> str:
        return (
            f"Global geopolitical risk is {label.lower()} (score {global_risk:.2f}) "
            f"based on {article_count} headlines. "
            f"Dominant theater: {assessment.dominant_theater}. "
            f"Escalation index {escalation:.2f} — {assessment.escalation_trend}. "
            f"Sanctions: {assessment.sanctions_pressure}. "
            f"Energy: {assessment.energy_flashpoint}. "
            f"Safe haven: {assessment.safe_haven_signal}. "
            f"Defense: {assessment.defense_spending_signal}."
        )

    def analyze(self) -> GeopoliticsReport:
        raw_articles, sources = self._fetch_news()
        articles = [self._classify_article(a) for a in raw_articles]
        theaters = self._score_theaters(articles)
        assessment = self._assessment(theaters, articles)
        global_risk = self._global_risk(theaters, articles)
        escalation = self._escalation_index(articles)

        label = (
            "Critical" if global_risk >= 0.75 else
            "Elevated" if global_risk >= 0.55 else
            "Moderate" if global_risk >= 0.35 else
            "Low"
        )

        summary = self._expert_summary(
            assessment, global_risk, escalation, label, len(articles)
        )
        signals = self._market_signals(theaters, assessment, global_risk, escalation)
        recs = self._recommendations(theaters, assessment, articles, global_risk)

        return GeopoliticsReport(
            articles=articles,
            theaters=theaters,
            assessment=assessment,
            global_risk_score=global_risk,
            escalation_index=escalation,
            risk_label=label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_sources=sources,
        )

    def _market_signals(
        self,
        theaters: list[TheaterRisk],
        assessment: GeopoliticalAssessment,
        global_risk: float,
        escalation: float,
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal

        signals: list[dict[str, Any]] = []
        by_id = {t.theater_id: t for t in theaters}

        if global_risk >= 0.48:
            signals.append(
                build_market_signal(
                    sector="Safe Haven / Gold",
                    tickers=["GLD", "IAU", "GDX"],
                    bias="BULLISH" if global_risk >= 0.62 else "NEUTRAL",
                    reason=assessment.safe_haven_signal,
                    confidence=min(0.82, 0.45 + global_risk * 0.45),
                    evidence={"global_risk": round(global_risk, 3), "escalation": round(escalation, 3)},
                )
            )
            if escalation >= 0.5:
                signals.append(
                    build_market_signal(
                        sector="Long Treasuries",
                        tickers=["TLT", "IEF", "SHY"],
                        bias="BULLISH" if escalation >= 0.58 else "NEUTRAL",
                        reason=f"Escalation index {escalation:.2f} — flight-to-quality bid",
                        confidence=min(0.78, 0.42 + escalation * 0.5),
                    )
                )

        ukraine = by_id.get("ukraine_russia")
        if ukraine and ukraine.risk_score >= 0.45 and ukraine.article_count >= 2:
            signals.append(
                build_market_signal(
                    sector="Defense",
                    tickers=["LMT", "RTX", "NOC", "GD"],
                    bias="BULLISH" if ukraine.risk_score >= 0.62 else "NEUTRAL",
                    reason=assessment.defense_spending_signal,
                    confidence=min(0.8, 0.4 + ukraine.risk_score * 0.55),
                )
            )
            signals.append({
                "sector": "European Equities",
                "tickers": ["FEZ", "EWG", "VGK"],
                "bias": "BEARISH" if ukraine.risk_score >= 0.65 else "NEUTRAL",
                "reason": f"Ukraine theater risk {ukraine.risk_score:.2f}",
            })

        middle_east = by_id.get("middle_east")
        energy = by_id.get("energy_security")
        if (middle_east and middle_east.risk_score >= 0.40) or (energy and energy.risk_score >= 0.40):
            signals.append({
                "sector": "Energy / Oil",
                "tickers": ["USO", "XLE", "XOM", "CVX"],
                "bias": "BULLISH" if (middle_east or energy).risk_score >= 0.60 else "NEUTRAL",
                "reason": assessment.energy_flashpoint,
            })

        china = by_id.get("china_taiwan")
        if china and china.risk_score >= 0.40:
            signals.append({
                "sector": "Semiconductors / China Exposure",
                "tickers": ["SOXX", "TSM", "NVDA", "FXI"],
                "bias": "BEARISH" if china.risk_score >= 0.60 else "NEUTRAL",
                "reason": f"China/Taiwan headlines ({china.article_count}) — supply chain & export control risk",
            })

        sanctions = by_id.get("trade_sanctions")
        if sanctions and sanctions.risk_score >= 0.35:
            signals.append({
                "sector": "Trade / EM Risk",
                "tickers": ["EEM", "INDA", "KWEB"],
                "bias": "BEARISH" if sanctions.risk_score >= 0.55 else "NEUTRAL",
                "reason": assessment.sanctions_pressure,
            })

        if not signals:
            signals.append({
                "sector": "Global Risk",
                "tickers": ["SPY", "GLD"],
                "bias": "NEUTRAL",
                "reason": "No acute geopolitical stress in current headlines",
            })

        return self._adjust_market_signals(signals)

    @staticmethod
    def _recommendations(
        theaters: list[TheaterRisk],
        assessment: GeopoliticalAssessment,
        articles: list[NewsArticle],
        global_risk: float,
    ) -> list[str]:
        recs = [
            f"Global risk {global_risk:.2f} — dominant theater: {assessment.dominant_theater}",
            f"Escalation: {assessment.escalation_trend}",
            f"Sanctions: {assessment.sanctions_pressure}",
            f"Energy: {assessment.energy_flashpoint}",
            f"Safe haven: {assessment.safe_haven_signal}",
            f"Defense: {assessment.defense_spending_signal}",
        ]
        active = [t for t in theaters if t.article_count > 0][:4]
        for t in active:
            headlines = "; ".join(t.top_headlines[:2]) if t.top_headlines else "none"
            recs.append(
                f"{t.theater_name}: risk {t.risk_score:.2f} ({t.article_count} articles) — {headlines}"
            )
        hot = sorted(articles, key=lambda a: a.escalation_score, reverse=True)[:3]
        if hot:
            recs.append(
                "Highest escalation headlines: " + " | ".join(a.title[:60] for a in hot)
            )
        if global_risk >= 0.60:
            recs.append("Elevated geopolitical risk — increase hedges (GLD, TLT) and monitor defense exposure")
        return recs

    def to_dict(self, report: GeopoliticsReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Geopolitics Expert",
                "analyzed_at": report.analyzed_at,
                "expert_summary": report.expert_summary,
                "headlines_analyzed": len(report.articles),
                "data_sources": report.data_sources,
            },
            "assessment": {
                "dominant_theater": a.dominant_theater,
                "escalation_trend": a.escalation_trend,
                "sanctions_pressure": a.sanctions_pressure,
                "energy_flashpoint": a.energy_flashpoint,
                "safe_haven_signal": a.safe_haven_signal,
                "defense_spending_signal": a.defense_spending_signal,
            },
            "theaters": [
                {
                    "id": t.theater_id,
                    "name": t.theater_name,
                    "article_count": t.article_count,
                    "escalation_score": t.escalation_score,
                    "risk_score": t.risk_score,
                    "risk_label": t.risk_label,
                    "top_headlines": t.top_headlines,
                }
                for t in report.theaters
            ],
            "headlines": [
                {
                    "title": art.title,
                    "source": art.source,
                    "theaters": art.theaters,
                    "escalation_score": art.escalation_score,
                    "link": art.link,
                }
                for art in report.articles[:20]
            ],
            "metrics": {
                "global_risk_score": report.global_risk_score,
                "escalation_index": report.escalation_index,
                "risk_label": report.risk_label,
            },
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result


def run_geopolitics_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return GeopoliticsExpert(pipeline_context=pipeline_context).run(output=output)