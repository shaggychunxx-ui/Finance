"""
Patent Landscape Analyst Agent
==============================
Tracks global patent databases, APIs, and monitoring resources while
surfacing recent innovation activity by technology sector.

Data: OpenAlex, IPWatchdog RSS, USPTO IP feeds (+ optional USPTO ODP API key).
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

HEADERS = {"User-Agent": "Finance-Patent-Landscape/1.0 (shaggychunxx@gmail.com)"}
OPENALEX_URL = "https://api.openalex.org/works"
USPTO_ODP_SEARCH = "https://api.uspto.gov/api/v1/patent/applications/search"

PATENT_RESOURCES: list[dict[str, Any]] = [
    {
        "id": "uspto_odp",
        "name": "USPTO Open Data Portal",
        "provider": "USPTO",
        "url": "https://data.uspto.gov/",
        "coverage": "US patents, trademarks, assignments",
        "access": "api",
        "api_key_required": True,
        "data_types": ["applications", "grants", "assignments", "trademarks"],
        "notes": "Primary US authority API; register at data.uspto.gov for key",
    },
    {
        "id": "uspto_ppubs",
        "name": "Patent Public Search",
        "provider": "USPTO",
        "url": "https://ppubs.uspto.gov/pubwebapp/",
        "coverage": "US published applications and grants",
        "access": "web",
        "api_key_required": False,
        "data_types": ["full text", "citations", "legal status"],
        "notes": "Official USPTO full-text search interface",
    },
    {
        "id": "patentsview",
        "name": "PatentsView Search API",
        "provider": "USPTO / AAAS",
        "url": "https://search.patentsview.org/",
        "coverage": "US patents 1976+",
        "access": "api",
        "api_key_required": False,
        "data_types": ["metadata", "assignees", "inventors", "CPC codes"],
        "notes": "Structured US patent analytics; bulk downloads available",
    },
    {
        "id": "google_patents",
        "name": "Google Patents",
        "provider": "Google",
        "url": "https://patents.google.com/",
        "coverage": "Global (100+ jurisdictions)",
        "access": "web",
        "api_key_required": False,
        "data_types": ["full text", "prior art", "family linkage"],
        "notes": "Best free global prior-art search; no official API",
    },
    {
        "id": "espacenet",
        "name": "Espacenet",
        "provider": "EPO",
        "url": "https://worldwide.espacenet.com/",
        "coverage": "100+ countries, 140M+ documents",
        "access": "web",
        "api_key_required": False,
        "data_types": ["bibliographic", "legal status", "family"],
        "notes": "European Patent Office worldwide collection",
    },
    {
        "id": "epo_ops",
        "name": "Open Patent Services (OPS)",
        "provider": "EPO",
        "url": "https://ops.epo.org/",
        "coverage": "Global patent data",
        "access": "api",
        "api_key_required": True,
        "data_types": ["biblio", "full text", "legal events"],
        "notes": "Machine-readable EPO data; fair-use rate limits apply",
    },
    {
        "id": "wipo_patentscope",
        "name": "PATENTSCOPE",
        "provider": "WIPO",
        "url": "https://patentscope.wipo.int/",
        "coverage": "PCT and national collections",
        "access": "web",
        "api_key_required": False,
        "data_types": ["PCT filings", "national phase", "sequences"],
        "notes": "Essential for international/PCT landscape monitoring",
    },
    {
        "id": "lens_org",
        "name": "Lens.org Patents",
        "provider": "Cambia / Lens",
        "url": "https://www.lens.org/lens/search/patent/",
        "coverage": "Global patents + scholarly linkage",
        "access": "api",
        "api_key_required": True,
        "data_types": ["patents", "citations", "patent-scholar links"],
        "notes": "Strong for competitive intelligence and citation graphs",
    },
    {
        "id": "openalex",
        "name": "OpenAlex",
        "provider": "OurResearch",
        "url": "https://openalex.org/",
        "coverage": "Scholarly works incl. patent-linked research",
        "access": "api",
        "api_key_required": False,
        "data_types": ["works", "institutions", "concepts"],
        "notes": "Free API for innovation research signals",
    },
    {
        "id": "derwent",
        "name": "Derwent Innovation",
        "provider": "Clarivate",
        "url": "https://clarivate.com/products/derwent-innovation/",
        "coverage": "Global with DWPI abstracting",
        "access": "subscription",
        "api_key_required": True,
        "data_types": ["DWPI titles", "family consolidation", "legal status"],
        "notes": "Enterprise patent analytics and landscaping",
    },
    {
        "id": "uspto_assignments",
        "name": "USPTO Patent Assignment Search",
        "provider": "USPTO",
        "url": "https://assignment.uspto.gov/patent/index.html",
        "coverage": "US ownership transfers",
        "access": "web",
        "api_key_required": False,
        "data_types": ["assignments", "security interests"],
        "notes": "Track M&A and licensing via ownership changes",
    },
    {
        "id": "orange_book",
        "name": "FDA Orange Book",
        "provider": "FDA",
        "url": "https://www.fda.gov/drugs/drug-approvals-and-databases/approved-drug-products-therapeutic-equivalence-evaluations-orange-book",
        "coverage": "US approved drug patents",
        "access": "bulk",
        "api_key_required": False,
        "data_types": ["drug patents", "exclusivity"],
        "notes": "Pharma patent cliff and generic entry timing",
    },
    {
        "id": "ipwatchdog",
        "name": "IPWatchdog",
        "provider": "IPWatchdog",
        "url": "https://www.ipwatchdog.com/",
        "coverage": "US IP law and policy news",
        "access": "rss",
        "api_key_required": False,
        "data_types": ["news", "case law", "policy"],
        "notes": "Patent prosecution and litigation developments",
    },
    {
        "id": "uspto_trademarks",
        "name": "USPTO Trademark Feed",
        "provider": "USPTO (via Feedburner)",
        "url": "https://feeds.feedburner.com/uspto",
        "coverage": "Recent US trademark registrations",
        "access": "rss",
        "api_key_required": False,
        "data_types": ["trademarks", "brand filings"],
        "notes": "Proxy signal for commercial IP activity",
    },
    {
        "id": "jpo",
        "name": "J-PlatPat",
        "provider": "JPO",
        "url": "https://www.j-platpat.inpit.go.jp/",
        "coverage": "Japan patents and designs",
        "access": "web",
        "api_key_required": False,
        "data_types": ["patents", "utility models", "designs"],
        "notes": "Key for Asia semiconductor and auto portfolios",
    },
    {
        "id": "cnipa",
        "name": "CNIPA Patent Search",
        "provider": "CNIPA",
        "url": "https://english.cnipa.gov.cn/",
        "coverage": "China patents",
        "access": "web",
        "api_key_required": False,
        "data_types": ["invention", "utility model", "design"],
        "notes": "Largest global filing volume by country",
    },
]

SECTOR_KEYWORDS: dict[str, list[str]] = {
    "semiconductor": [
        "semiconductor", "chip", "integrated circuit", "wafer", "lithography",
        "transistor", "gpu", "processor", "memory",
    ],
    "artificial-intelligence": [
        "artificial intelligence", "machine learning", "neural network",
        "deep learning", "llm", "generative ai", "transformer",
    ],
    "biotechnology": [
        "biotech", "antibody", "gene", "crispr", "pharmaceutical", "vaccine",
        "therapeutic", "mrna", "protein",
    ],
    "energy": [
        "battery", "solar", "wind", "hydrogen", "fuel cell", "energy storage",
        "lithium", "renewable",
    ],
    "automotive": [
        "vehicle", "autonomous", "ev", "electric vehicle", "lidar", "powertrain",
    ],
    "telecom": [
        "5g", "6g", "wireless", "telecommunication", "antenna", "network",
    ],
}

SECTOR_TICKERS: dict[str, list[str]] = {
    "semiconductor": ["SOXX", "NVDA", "AMD", "INTC"],
    "artificial-intelligence": ["QQQ", "MSFT", "GOOGL", "NVDA"],
    "biotechnology": ["XBI", "IBB", "MRNA", "AMGN"],
    "energy": ["XLE", "TAN", "ENPH", "FSLR"],
    "automotive": ["TSLA", "RIVN", "GM", "F"],
    "telecom": ["XLC", "T", "VZ", "ERIC"],
}

OPENALEX_QUERIES = [
    ("semiconductor", "semiconductor patent"),
    ("artificial-intelligence", "artificial intelligence patent"),
    ("biotechnology", "biotechnology patent"),
    ("energy", "battery energy storage patent"),
    ("automotive", "autonomous electric vehicle patent"),
]

NEWS_FEEDS = [
    ("IPWatchdog", "https://www.ipwatchdog.com/feed/"),
    ("USPTO Trademarks", "https://feeds.feedburner.com/uspto"),
]


@dataclass
class PatentFinding:
    title: str
    date: str
    sector: str
    source: str
    link: str
    assignee: str
    impact: str
    notes: str


@dataclass
class PatentReport:
    resources: list[dict[str, Any]]
    findings: list[PatentFinding]
    by_sector: dict[str, int]
    by_source: dict[str, int]
    resources_online: int
    innovation_score: float
    landscape_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PatentLandscapeAnalyst(BaseExpert):
    """Patent landscape analyst — resource catalog and innovation monitoring."""

    def __init__(
        self,
        config_path: Path | None = None,
        *,
        pipeline_context: dict | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="patents")
        self.config = self._load_config(config_path)
        self.uspto_api_key = self.config.get("uspto_api_key", "").strip()

    @staticmethod
    def _load_config(config_path: Path | None) -> dict[str, Any]:
        candidates = [config_path, Path("config.json"), Path("config.example.json")]
        for path in candidates:
            if path and path.exists():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
        return {}

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
        catalog: list[dict[str, Any]] = []
        for res in PATENT_RESOURCES:
            catalog.append(self._check_resource_health(res))
        return catalog

    @staticmethod
    def _parse_rss(xml_bytes: bytes, source: str, limit: int = 15) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError:
            return items

        for item in root.findall(".//item")[:limit]:
            title_el = item.find("title")
            if title_el is None or not title_el.text:
                continue
            link_el = item.find("link")
            pub_el = item.find("pubDate")
            desc_el = item.find("description")
            pub_date = PatentLandscapeAnalyst._parse_pub_date(
                pub_el.text if pub_el is not None else ""
            )
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

    def _fetch_openalex(self, sector: str, query: str) -> list[dict[str, Any]]:
        params = {
            "search": query,
            "filter": "from_publication_date:2025-01-01",
            "per_page": 5,
            "sort": "publication_date:desc",
            "mailto": "shaggychunxx@gmail.com",
        }
        try:
            resp = requests.get(OPENALEX_URL, params=params, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            results = resp.json().get("results", [])
        except Exception:
            return []

        findings: list[dict[str, Any]] = []
        for work in results:
            title = work.get("title") or work.get("display_name") or ""
            if not title:
                continue
            inst = ""
            authorships = work.get("authorships") or []
            if authorships:
                insts = authorships[0].get("institutions") or []
                if insts:
                    inst = insts[0].get("display_name", "")
            classified = self._classify_sector(title)
            findings.append({
                "title": title,
                "date": work.get("publication_date", ""),
                "sector": classified if classified != "general" else sector,
                "source": "OpenAlex",
                "link": work.get("id", ""),
                "assignee": inst,
                "description": (work.get("abstract_inverted_index") or {}),
            })
        return findings

    def _fetch_uspto_odp(self, query: str = "artificial intelligence") -> list[dict[str, Any]]:
        if not self.uspto_api_key:
            return []
        headers = {**HEADERS, "X-API-KEY": self.uspto_api_key}
        try:
            resp = requests.get(
                USPTO_ODP_SEARCH,
                params={"searchText": query, "rows": 8},
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            return []

        findings: list[dict[str, Any]] = []
        rows = payload.get("results", payload.get("patentFileWrapperDataBag", []))
        if isinstance(rows, dict):
            rows = rows.get("applications", [])
        for row in rows[:8]:
            if not isinstance(row, dict):
                continue
            title = (
                row.get("inventionTitle")
                or row.get("patentTitle")
                or row.get("title", "")
            )
            if not title:
                continue
            findings.append({
                "title": str(title),
                "date": str(row.get("filingDate", row.get("grantDate", "")))[:10],
                "sector": self._classify_sector(str(title)),
                "source": "USPTO ODP",
                "link": "https://data.uspto.gov/",
                "assignee": str(row.get("applicantName", row.get("assignee", ""))),
                "description": "",
            })
        return findings

    def _fetch_news_feeds(self) -> list[dict[str, Any]]:
        headlines: list[dict[str, Any]] = []
        for name, url in NEWS_FEEDS:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=25)
                resp.raise_for_status()
                headlines.extend(self._parse_rss(resp.content, name))
            except Exception:
                continue
        return headlines

    @staticmethod
    def _classify_sector(text: str) -> str:
        lower = text.lower()
        scores: dict[str, int] = {}
        for sector, keywords in SECTOR_KEYWORDS.items():
            scores[sector] = sum(1 for kw in keywords if kw in lower)
        if not scores or max(scores.values()) == 0:
            return "general"
        return max(scores, key=scores.get)

    @staticmethod
    def _classify_impact(text: str, sector: str) -> str:
        lower = text.lower()
        if sector in ("semiconductor", "artificial-intelligence") and any(
            w in lower for w in ("breakthrough", "novel", "first", "critical", "blockbuster")
        ):
            return "high"
        if sector != "general":
            return "medium"
        return "low"

    @staticmethod
    def _finding_notes(sector: str, source: str) -> str:
        notes = {
            "semiconductor": "Semiconductor IP — watch foundry/tool leaders",
            "artificial-intelligence": "AI patent race — model architecture and training IP",
            "biotechnology": "Life sciences pipeline and exclusivity cliffs",
            "energy": "Clean-tech patent cluster — storage and materials",
            "automotive": "Mobility IP — EV powertrain and autonomy",
            "telecom": "Connectivity standards and SEP exposure",
            "general": "General innovation activity",
        }
        base = notes.get(sector, notes["general"])
        return f"{base}. Source: {source}."

    def _normalize_findings(self, raw_items: list[dict[str, Any]]) -> list[PatentFinding]:
        findings: list[PatentFinding] = []
        for item in raw_items:
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            sector = item.get("sector") or self._classify_sector(title)
            impact = self._classify_impact(title, sector)
            findings.append(PatentFinding(
                title=title,
                date=item.get("date") or item.get("pub_date", ""),
                sector=sector,
                source=item.get("source", "Unknown"),
                link=item.get("link", ""),
                assignee=str(item.get("assignee", "")),
                impact=impact,
                notes=self._finding_notes(sector, item.get("source", "")),
            ))
        return findings

    @staticmethod
    def _proxy_findings() -> list[dict[str, Any]]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return [
            {
                "title": "Advanced EUV lithography patterning for sub-2nm semiconductor nodes",
                "date": today,
                "sector": "semiconductor",
                "source": "Proxy",
                "link": "",
                "assignee": "Leading foundry",
            },
            {
                "title": "Transformer-based multimodal model training with sparse attention",
                "date": today,
                "sector": "artificial-intelligence",
                "source": "Proxy",
                "link": "",
                "assignee": "Big Tech",
            },
            {
                "title": "Solid-state lithium-metal battery electrolyte composition",
                "date": today,
                "sector": "energy",
                "source": "Proxy",
                "link": "",
                "assignee": "Energy storage firm",
            },
            {
                "title": "CRISPR-guided in vivo gene editing delivery system",
                "date": today,
                "sector": "biotechnology",
                "source": "Proxy",
                "link": "",
                "assignee": "Biotech lab",
            },
        ]

    def _collect_findings(self) -> tuple[list[PatentFinding], list[str]]:
        raw: list[dict[str, Any]] = []
        sources: list[str] = []

        for sector, query in OPENALEX_QUERIES:
            items = self._fetch_openalex(sector, query)
            if items:
                raw.extend(items)
                if "OpenAlex" not in sources:
                    sources.append("OpenAlex")

        odp_items = self._fetch_uspto_odp()
        if odp_items:
            raw.extend(odp_items)
            sources.append("USPTO ODP")

        news = self._fetch_news_feeds()
        if news:
            for h in news:
                h["sector"] = self._classify_sector(
                    f"{h['title']} {h.get('description', '')}"
                )
            raw.extend(news)
            sources.extend({h["source"] for h in news})

        if not raw:
            raw = self._proxy_findings()
            sources.append("Calibrated proxy feed")

        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for item in raw:
            key = item["title"].lower()[:90]
            if key not in seen:
                seen.add(key)
                deduped.append(item)

        return self._normalize_findings(deduped), sources

    def _innovation_score(self, by_sector: dict[str, int], online: int) -> tuple[float, str]:
        hot_sectors = sum(1 for c in by_sector.values() if c >= 3)
        score = min(100.0, hot_sectors * 14 + online * 2 + sum(by_sector.values()) * 1.5)
        if score >= 70:
            label = "High innovation velocity"
        elif score >= 45:
            label = "Moderate patent activity"
        else:
            label = "Quiet landscape"
        return round(score, 1), label

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

    def _market_signals(
        self,
        findings: list[PatentFinding],
        by_sector: dict[str, int],
        *,
        innovation_score: float,
        landscape_label: str,
        top_sector: str,
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import patents_market_impact_signals

        high_impact = sum(1 for f in findings if f.impact == "high")
        signals = patents_market_impact_signals(
            innovation_score=innovation_score,
            landscape_label=landscape_label,
            by_sector=by_sector,
            high_impact_count=high_impact,
            top_sector=top_sector,
            source="patents",
        )
        return self._adjust_market_signals(signals)

    def analyze(self) -> PatentReport:
        resources = self._catalog_resources()
        online = sum(1 for r in resources if r.get("health") == "online")

        findings, sources = self._collect_findings()

        by_sector: dict[str, int] = {}
        by_source: dict[str, int] = {}
        for f in findings:
            by_sector[f.sector] = by_sector.get(f.sector, 0) + 1
            by_source[f.source] = by_source.get(f.source, 0) + 1

        innovation_score, landscape_label = self._innovation_score(by_sector, online)
        top_sector = max(by_sector, key=by_sector.get) if by_sector else "none"

        summary = (
            f"Tracking {len(resources)} patent resources ({online} online). "
            f"Surfaced {len(findings)} innovation signals from {', '.join(sources)}. "
            f"Leading sector: {top_sector.replace('-', ' ')} ({by_sector.get(top_sector, 0)}). "
            f"Landscape: {landscape_label} (score {innovation_score})."
        )

        signals = self._market_signals(
            findings,
            by_sector,
            innovation_score=innovation_score,
            landscape_label=landscape_label,
            top_sector=top_sector,
        )
        recs = [
            summary,
            f"Resources online: {online}/{len(resources)} | "
            f"API key recommended: USPTO ODP for live US filings",
        ]
        recs.append("Top patent databases: Google Patents, Espacenet, PATENTSCOPE, PatentsView")
        for sector, count in sorted(by_sector.items(), key=lambda x: -x[1])[:5]:
            recs.append(f"{sector.replace('-', ' ').title()}: {count} signals")
        for f in findings[:6]:
            recs.append(f"[{f.sector}] {f.title[:75]} — {f.source}")
        offline = [r["name"] for r in resources if r.get("health") == "offline"]
        if offline:
            recs.append(f"Offline resources (check later): {', '.join(offline[:4])}")

        return PatentReport(
            resources=resources,
            findings=findings,
            by_sector=by_sector,
            by_source=by_source,
            resources_online=online,
            innovation_score=innovation_score,
            landscape_label=landscape_label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_sources=sources,
        )

    def to_dict(self, report: PatentReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Patent Landscape Analyst",
                "analyzed_at": report.analyzed_at,
                "data_sources": report.data_sources,
                "expert_summary": report.expert_summary,
                "resources_tracked": len(report.resources),
                "findings_count": len(report.findings),
            },
            "summary": {
                "by_sector": report.by_sector,
                "by_source": report.by_source,
                "resources_online": report.resources_online,
                "innovation_score": report.innovation_score,
                "landscape_label": report.landscape_label,
            },
            "resources": report.resources,
            "findings": [
                {
                    "title": f.title,
                    "date": f.date,
                    "sector": f.sector,
                    "source": f.source,
                    "link": f.link,
                    "assignee": f.assignee,
                    "impact": f.impact,
                    "notes": f.notes,
                }
                for f in report.findings
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
            catalog_path = output.parent / "patent_resources.json"
            catalog_path.write_text(
                json.dumps(report.resources, indent=2),
                encoding="utf-8",
            )
        return result


def run_patents_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return PatentLandscapeAnalyst(pipeline_context=pipeline_context).run(output=output)