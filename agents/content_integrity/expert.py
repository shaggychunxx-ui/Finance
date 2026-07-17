"""
Content Integrity Expert Agent
==============================
Catalogs the multi-layered pipeline used by modern news toxicity and social
spoof filters (adversarial text normalization, transformer/semantic
analysis, graph-based identity forensics, visual/deepfake forensics, and
news provenance tracking), then screens live world headlines for
market-relevant disinformation / impersonation risk signals (e.g. fake
executive announcements, spoofed accounts, deepfake claims) that could
trigger stock-market manipulation or false volatility.

Data: BBC World / NPR RSS feeds (same public feeds as the Events and
Geopolitics agents), scored with a heuristic ensemble risk proxy — this is
not a production NLP/vision toxicity or deepfake classifier.
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

HEADERS = {"User-Agent": "Finance-ContentIntegrity-Expert/1.0 (shaggychunxx@gmail.com)"}

NEWS_FEEDS = [
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("NPR World", "https://feeds.npr.org/1004/rss.xml"),
]

# ---------------------------------------------------------------------------
# Pipeline / methodology catalog (mirrors the pillars in the problem brief).
# ---------------------------------------------------------------------------

FILTER_PIPELINE_STAGES: list[str] = [
    "Real-Time Normalization",
    "Contextual NLP (Transformer)",
    "Vector DB / Graph Networks",
    "Heuristic / Pattern Match",
    "Semantic & Intent",
    "Identity & Provenance",
    "Ensemble Risk Scoring Engine",
    "Moderation Action",
]

TOXICITY_PILLAR: dict[str, Any] = {
    "id": "toxicity_filtering_engine",
    "name": "Toxicity Filtering Engine",
    "summary": (
        "Moves beyond regex keyword blocking to LLM/SLM transformer classifiers "
        "trained on domain-specific toxic content."
    ),
    "techniques": [
        {
            "id": "adversarial_text_normalization",
            "name": "Adversarial Text Normalization",
            "methods": [
                "Leet-speak & Homoglyph De-obfuscation",
                "Text Salting Removal (zero-width spaces / invisible tags)",
            ],
        },
        {
            "id": "deep_transformer_semantic_analysis",
            "name": "Deep Transformer & Semantic Analysis",
            "methods": [
                "Tokenization & Context Windows",
                "Vector Embeddings & Cosine Similarity vs toxic clusters",
            ],
        },
        {
            "id": "intent_vs_keyword_classification",
            "name": "Intent vs. Keyword Classification",
            "methods": [
                "Sub-category Isolation (profanity/insult/threat/sexual/severe)",
                "Reclaimed Language Handling (demographic-aware training)",
            ],
        },
    ],
}

SPOOF_PILLAR: dict[str, Any] = {
    "id": "social_spoof_impersonation_filters",
    "name": "Social Spoof & Impersonation Filters",
    "summary": (
        "Targets corporate fraud, stock-market manipulation via fake executive "
        "announcements, and geopolitical disinformation via metadata, visual "
        "media, and behavioral graph analysis."
    ),
    "techniques": [
        {
            "id": "graph_based_identity_forensics",
            "name": "Graph-Based Identity & Account Forensics",
            "methods": [
                "Velocity Metrics (rapid handle/photo/bio mimicry)",
                "Graph Convolutional Networks (coordinated inauthentic behavior)",
            ],
        },
        {
            "id": "visual_forensics_deepfake_detection",
            "name": "Visual Forensics & Deepfake Detection",
            "methods": [
                "OCR Checking of embedded image/meme text",
                "Error Level Analysis (JPEG compression artifacts)",
                "Synthetic Artifact Detection (blink rate, PPG, audio/video sync)",
            ],
        },
    ],
}

NEWS_INTEGRITY_PILLAR: dict[str, Any] = {
    "id": "automated_news_integrity_checking",
    "name": "Automated News Integrity Checking",
    "summary": (
        "Does not judge \"truth\" directly — evaluates structures, origins, and "
        "distribution patterns of credible journalism vs. misinformation."
    ),
    "techniques": [
        {
            "id": "domain_url_provenance_tracking",
            "name": "Domain & URL Provenance Tracking",
            "methods": [
                "Passive DNS & Registration Auditing",
                "Crawl Map Analysis (local -> wire service -> global syndicate)",
            ],
        },
        {
            "id": "cross_verification_claim_matching",
            "name": "Cross-Verification & Claim-Matching Networks",
            "methods": [
                "Vector Database Lookups against trusted/official feeds",
                "Contradiction Modeling (high-velocity vs. verified data pools)",
            ],
        },
    ],
}

FILTER_PILLARS: list[dict[str, Any]] = [TOXICITY_PILLAR, SPOOF_PILLAR, NEWS_INTEGRITY_PILLAR]

COMMERCIAL_ECOSYSTEM: list[dict[str, str]] = [
    {
        "name": "ZeroFox",
        "focus": "Enterprise brand protection — social spoof / impersonation stack",
        "url": "https://www.zerofox.com/",
    },
    {
        "name": "BrandShield",
        "focus": "Enterprise brand protection — phishing/fake-account takedowns",
        "url": "https://www.brandshield.com/",
    },
    {
        "name": "Lasso Moderation",
        "focus": "Community platform toxicity pipeline",
        "url": "https://www.lassomoderation.com/",
    },
    {
        "name": "Disqus",
        "focus": "Comment-section spam/slur/hostile-engagement filtering",
        "url": "https://www.disqus.com/",
    },
    {
        "name": "Perspective API",
        "focus": "Toxicity/severe-toxicity scoring API (Google)",
        "url": "https://perspectiveapi.com/",
    },
    {
        "name": "AWS Rekognition",
        "focus": "Cloud multi-modal content safety (image/video)",
        "url": "https://aws.amazon.com/rekognition/",
    },
    {
        "name": "Azure Content Safety",
        "focus": "Cloud multi-modal content safety (text/image)",
        "url": "https://azure.microsoft.com/en-us/products/ai-services/ai-content-safety",
    },
]

STRUCTURAL_TRADEOFFS: list[dict[str, str]] = [
    {
        "id": "false_positive_information_tax",
        "name": "False-Positive Wealth/Information Tax",
        "description": (
            "Aggressive toxicity settings choke legitimate high-value conversation — "
            "filtering on \"bombing\"/\"shooting\"/\"fraud\" can suppress investigative "
            "journalism and public safety warnings."
        ),
    },
    {
        "id": "latency_compute_costs",
        "name": "Exploding Latency & Compute Costs",
        "description": (
            "Multi-modal analysis (text NLP + video deepfake scans + graph DB "
            "cross-checks) in live feeds bottlenecks throughput and cloud spend."
        ),
    },
    {
        "id": "chilling_effect_algorithmic_bias",
        "name": "Chilling Effect & Algorithmic Biases",
        "description": (
            "Models trained mainly on sanitized corporate text misclassify regional "
            "slang or passionate political debate, quieting marginalized voices."
        ),
    },
]

# ---------------------------------------------------------------------------
# Market manipulation / disinformation risk heuristics.
# ---------------------------------------------------------------------------

# Company/ticker names screened for spoof-driven headline risk (corporate
# fraud, fake executive announcements) — shares the standard 8-symbol
# watchlist used across the repo's short-selling/execution agents.
WATCHLIST: dict[str, str] = {
    "SPY": "S&P 500",
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "QQQ": "Nasdaq 100",
    "IWM": "Russell 2000",
    "GME": "GameStop",
    "COIN": "Coinbase",
    "PLTR": "Palantir",
}

CRITICAL_MANIPULATION_KEYWORDS = {
    "deepfake", "hacked account", "fabricated filing", "fraudulent statement", "hoax",
}
HIGH_MANIPULATION_KEYWORDS = {
    "fake screenshot", "impersonat", "spoofed account", "doctored", "bogus statement",
    "phishing", "fake tweet",
}
MEDIUM_MANIPULATION_KEYWORDS = {
    "unverified claim", "denies report", "clarifies statement", "rumor", "unconfirmed",
}

# Homoglyph / leet-speak de-obfuscation table — a small illustrative slice of
# the "Real-Time Normalization" stage described in the pipeline.
_HOMOGLYPH_MAP = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a",
    "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p", "\u0441": "c",
})

_ZERO_WIDTH_RE = re.compile("[\u200b\u200c\u200d\ufeff]")


@dataclass
class ContentIntegrityFlag:
    title: str
    date: str
    source: str
    link: str
    risk_tier: str
    pillar: str
    matched_signals: list[str]
    related_tickers: list[str]
    notes: str


@dataclass
class ContentIntegrityReport:
    flags: list[ContentIntegrityFlag]
    by_risk_tier: dict[str, int]
    ensemble_risk_score: float
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ContentIntegrityExpert(BaseExpert):
    """Content integrity analyst — toxicity/spoof/news-provenance risk screen."""

    def __init__(self, *, pipeline_context: dict[str, Any] | None = None) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="content-integrity")

    @staticmethod
    def normalize_text(text: str) -> str:
        """Illustrative Stage 1 normalization: strip salting, de-obfuscate."""
        cleaned = _ZERO_WIDTH_RE.sub("", text or "")
        return cleaned.lower().translate(_HOMOGLYPH_MAP)

    def _parse_rss(self, xml_bytes: bytes, source: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError:
            return items

        for item in root.findall(".//item")[:25]:
            title_el = item.find("title")
            if title_el is None or not title_el.text:
                continue
            link_el = item.find("link")
            pub_el = item.find("pubDate")
            desc_el = item.find("description")
            pub_date = self._parse_pub_date(pub_el.text if pub_el is not None else "")
            items.append({
                "title": title_el.text.strip(),
                "link": (link_el.text or "").strip() if link_el is not None else "",
                "pub_date": pub_date,
                "description": (desc_el.text or "").strip() if desc_el is not None else "",
                "source": source,
            })
        return items

    @staticmethod
    def _parse_pub_date(raw: str) -> str:
        if not raw:
            return datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            return parsedate_to_datetime(raw).strftime("%Y-%m-%d")
        except Exception:
            return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _fetch_headlines(self) -> tuple[list[dict[str, Any]], list[str]]:
        headlines: list[dict[str, Any]] = []
        sources: list[str] = []
        for name, url in NEWS_FEEDS:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=30)
                resp.raise_for_status()
                parsed = self._parse_rss(resp.content, name)
                if parsed:
                    headlines.extend(parsed)
                    sources.append(name)
            except Exception:
                continue

        if not headlines:
            headlines = self._proxy_headlines()
            sources.append("Calibrated proxy feed")

        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for h in headlines:
            key = h["title"].lower()[:80]
            if key not in seen:
                seen.add(key)
                deduped.append(h)
        return deduped, sources

    @staticmethod
    def _proxy_headlines() -> list[dict[str, Any]]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return [
            {"title": "Company denies report of executive resignation after fake tweet circulates", "pub_date": today, "source": "Proxy", "link": "", "description": ""},
            {"title": "Regulators investigate coordinated bot network amplifying stock rumor", "pub_date": today, "source": "Proxy", "link": "", "description": ""},
            {"title": "Deepfake video of CEO announcement spreads before company clarifies statement", "pub_date": today, "source": "Proxy", "link": "", "description": ""},
            {"title": "Central bank holds rates steady amid inflation data review", "pub_date": today, "source": "Proxy", "link": "", "description": ""},
            {"title": "Spoofed account impersonating newswire posts unverified claim about merger", "pub_date": today, "source": "Proxy", "link": "", "description": ""},
        ]

    def _classify(self, text: str) -> tuple[str, list[str], str]:
        normalized = self.normalize_text(text)
        matched: list[str] = []
        pillar = NEWS_INTEGRITY_PILLAR["name"]

        for kw in CRITICAL_MANIPULATION_KEYWORDS:
            if kw in normalized:
                matched.append(kw)
        if matched:
            pillar = SPOOF_PILLAR["name"]
            return "critical", matched, pillar

        for kw in HIGH_MANIPULATION_KEYWORDS:
            if kw in normalized:
                matched.append(kw)
        if matched:
            pillar = SPOOF_PILLAR["name"]
            return "high", matched, pillar

        for kw in MEDIUM_MANIPULATION_KEYWORDS:
            if kw in normalized:
                matched.append(kw)
        if matched:
            pillar = NEWS_INTEGRITY_PILLAR["name"]
            return "medium", matched, pillar

        return "low", matched, pillar

    @staticmethod
    def _related_tickers(text: str) -> list[str]:
        lower = text.lower()
        tokens = set(re.findall(r"[a-z0-9]+", lower))
        hits: list[str] = []
        for ticker, name in WATCHLIST.items():
            if name.lower() in lower or ticker.lower() in tokens:
                hits.append(ticker)
        return hits

    def _headline_to_flag(self, headline: dict[str, Any]) -> ContentIntegrityFlag:
        text = f"{headline['title']} {headline.get('description', '')}"
        risk_tier, matched, pillar = self._classify(text)
        tickers = self._related_tickers(text)
        notes = (
            f"[{risk_tier.upper()}] {pillar} — matched: {', '.join(matched) or 'none'}"
        )
        if tickers:
            notes += f" — related tickers: {', '.join(tickers)}"
        return ContentIntegrityFlag(
            title=headline["title"],
            date=headline["pub_date"],
            source=headline["source"],
            link=headline.get("link", ""),
            risk_tier=risk_tier,
            pillar=pillar,
            matched_signals=matched,
            related_tickers=tickers,
            notes=notes,
        )

    def _market_signals(self, flags: list[ContentIntegrityFlag]) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal, weighted_event_score

        signals: list[dict[str, Any]] = []
        rows = [{"impact": f.risk_tier, "date": f.date} for f in flags]
        stress_score = weighted_event_score(rows)

        critical_or_high = [f for f in flags if f.risk_tier in ("critical", "high")]
        ticker_hits: dict[str, list[ContentIntegrityFlag]] = {}
        for f in critical_or_high:
            for t in f.related_tickers:
                ticker_hits.setdefault(t, []).append(f)

        for ticker, hits in ticker_hits.items():
            conf = min(0.85, 0.5 + len(hits) * 0.12)
            signals.append(
                build_market_signal(
                    sector=f"Equity — {WATCHLIST.get(ticker, ticker)}",
                    tickers=[ticker],
                    bias="NEUTRAL",
                    reason=(
                        f"{len(hits)} spoof/disinformation-risk headline(s) referencing "
                        f"{WATCHLIST.get(ticker, ticker)} — elevated false-volatility risk."
                    ),
                    confidence=conf,
                )
            )

        if stress_score >= 0.9 or len(critical_or_high) >= 2:
            signals.append(
                build_market_signal(
                    sector="Broad Market",
                    tickers=["SPY"],
                    bias="NEUTRAL",
                    reason=(
                        f"Recency-weighted disinformation risk score {stress_score:.2f} "
                        f"from {len(critical_or_high)} critical/high-risk headlines."
                    ),
                    confidence=min(0.8, 0.45 + stress_score * 0.2),
                )
            )

        if not signals:
            signals.append(
                build_market_signal(
                    sector="Broad Market",
                    tickers=["SPY"],
                    bias="NEUTRAL",
                    reason="No acute spoof/disinformation risk detected in tracked headlines",
                    confidence=0.4,
                )
            )
        return signals

    def analyze(self) -> ContentIntegrityReport:
        headlines, sources = self._fetch_headlines()
        flags = [self._headline_to_flag(h) for h in headlines]

        by_tier: dict[str, int] = {}
        for f in flags:
            by_tier[f.risk_tier] = by_tier.get(f.risk_tier, 0) + 1

        from agent_signal_logic import weighted_event_score

        ensemble_risk_score = weighted_event_score(
            [{"impact": f.risk_tier, "date": f.date} for f in flags]
        )

        critical_count = by_tier.get("critical", 0)
        high_count = by_tier.get("high", 0)

        summary = (
            f"Screened {len(flags)} headlines from {', '.join(sources)} through the "
            f"toxicity/spoof/news-integrity pipeline. {critical_count} critical, "
            f"{high_count} high spoof/disinformation-risk flags. Ensemble risk score "
            f"{ensemble_risk_score:.2f}."
        )

        recs = [
            summary,
            f"Critical: {critical_count} | High: {high_count} | "
            f"Medium: {by_tier.get('medium', 0)} | Low: {by_tier.get('low', 0)}",
        ]
        for f in [x for x in flags if x.risk_tier in ("critical", "high")][:5]:
            recs.append(f"[{f.risk_tier.upper()}] {f.title[:80]} — {f.pillar}")
        recs.append(
            "Trade-offs to monitor: false-positive information tax, latency/compute "
            "cost, and chilling-effect algorithmic bias (see structural_tradeoffs)."
        )

        return ContentIntegrityReport(
            flags=flags,
            by_risk_tier=by_tier,
            ensemble_risk_score=ensemble_risk_score,
            expert_summary=summary,
            market_signals=self._market_signals(flags),
            recommendations=recs,
            data_sources=sources,
        )

    def to_dict(self, report: ContentIntegrityReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Content Integrity Expert",
                "analyzed_at": report.analyzed_at,
                "data_sources": report.data_sources,
                "expert_summary": report.expert_summary,
                "temperature": self.temperature,
                "headlines_screened": len(report.flags),
                "pipeline_memory": {
                    "posture": self.pipeline_context.get("posture"),
                    "lessons": self.pipeline_memory_notes(),
                    "preferred_horizon": self.pipeline_context.get("preferred_horizon"),
                },
            },
            "filter_pipeline_stages": FILTER_PIPELINE_STAGES,
            "filter_pillars": FILTER_PILLARS,
            "commercial_ecosystem": COMMERCIAL_ECOSYSTEM,
            "structural_tradeoffs": STRUCTURAL_TRADEOFFS,
            "summary": {
                "by_risk_tier": report.by_risk_tier,
                "ensemble_risk_score": report.ensemble_risk_score,
            },
            "flags": [
                {
                    "title": f.title,
                    "date": f.date,
                    "source": f.source,
                    "link": f.link,
                    "risk_tier": f.risk_tier,
                    "pillar": f.pillar,
                    "matched_signals": f.matched_signals,
                    "related_tickers": f.related_tickers,
                    "notes": f.notes,
                }
                for f in report.flags
            ],
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        report = self.analyze()
        result = self.to_dict(report)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "content_integrity_playbook.json"
            catalog.write_text(
                json.dumps(
                    {
                        "filter_pipeline_stages": FILTER_PIPELINE_STAGES,
                        "filter_pillars": FILTER_PILLARS,
                        "commercial_ecosystem": COMMERCIAL_ECOSYSTEM,
                        "structural_tradeoffs": STRUCTURAL_TRADEOFFS,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        return result


def run_content_integrity_analysis(
    output: Path | None = None,
    pipeline_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return ContentIntegrityExpert(pipeline_context=pipeline_context).run(output=output)
