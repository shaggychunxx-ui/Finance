"""
SEC EDGAR Filings Analyst Agent
===============================
Securities/regulatory analyst tracking material corporate disclosures via
the SEC's EDGAR Full Text Search system and surfacing filing-driven market
signals (M&A, insider activity, buybacks, restatements, leadership changes).

Dashboard: https://www.sec.gov/edgar/search/#
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from agents.base import BaseExpert

DASHBOARD_URL = "https://www.sec.gov/edgar/search/#"
FULL_TEXT_SEARCH_API = "https://efts.sec.gov/LATEST/search-index"
HEADERS = {"User-Agent": "Finance-SEC-Filings-Analyst/1.0 (shaggychunxx@gmail.com)"}

SEC_RESOURCES: list[dict[str, Any]] = [
    {
        "id": "edgar_full_text_search",
        "name": "EDGAR Full Text Search",
        "provider": "SEC",
        "url": "https://www.sec.gov/edgar/search/#",
        "coverage": "All EDGAR filings, 2001+",
        "access": "api",
        "api_key_required": False,
        "data_types": ["8-K", "10-K", "10-Q", "4", "13F-HR", "S-1"],
        "notes": "Primary data source for this agent; backed by efts.sec.gov search-index",
    },
    {
        "id": "edgar_submissions",
        "name": "EDGAR Company Submissions API",
        "provider": "SEC",
        "url": "https://data.sec.gov/submissions/",
        "coverage": "All registrants, full filing history",
        "access": "api",
        "api_key_required": False,
        "data_types": ["filing history", "metadata"],
        "notes": "Per-CIK JSON submission index",
    },
    {
        "id": "edgar_xbrl_company_facts",
        "name": "EDGAR XBRL Company Facts API",
        "provider": "SEC",
        "url": "https://data.sec.gov/api/xbrl/companyfacts/",
        "coverage": "Structured financial statement facts",
        "access": "api",
        "api_key_required": False,
        "data_types": ["XBRL facts", "financial statements"],
        "notes": "Standardized fundamentals extracted from filings",
    },
    {
        "id": "edgar_xbrl_frames",
        "name": "EDGAR XBRL Frames API",
        "provider": "SEC",
        "url": "https://data.sec.gov/api/xbrl/frames/",
        "coverage": "Cross-company XBRL concept comparisons",
        "access": "api",
        "api_key_required": False,
        "data_types": ["XBRL frames"],
        "notes": "Compare a single concept across registrants for a period",
    },
    {
        "id": "edgar_daily_index",
        "name": "EDGAR Daily Index",
        "provider": "SEC",
        "url": "https://www.sec.gov/Archives/edgar/daily-index/",
        "coverage": "Daily filing manifests",
        "access": "bulk",
        "api_key_required": False,
        "data_types": ["form index", "company index"],
        "notes": "Full daily list of all filings submitted",
    },
    {
        "id": "edgar_form4_insider",
        "name": "Form 4 Insider Transactions",
        "provider": "SEC",
        "url": "https://www.sec.gov/edgar/search/#/forms=4",
        "coverage": "Officer/director/10% owner transactions",
        "access": "api",
        "api_key_required": False,
        "data_types": ["insider buys", "insider sells"],
        "notes": "Filtered EDGAR full text search by form type 4",
    },
    {
        "id": "edgar_13f",
        "name": "Form 13F Institutional Holdings",
        "provider": "SEC",
        "url": "https://www.sec.gov/edgar/search/#/forms=13F-HR",
        "coverage": "Institutional investment manager holdings",
        "access": "api",
        "api_key_required": False,
        "data_types": ["13F-HR", "13F-NT"],
        "notes": "Quarterly institutional position disclosures",
    },
]

# (category, query, forms, tickers, bias-if-hot)
WATCH_QUERIES: list[tuple[str, str, list[str], list[str], str]] = [
    ("merger-acquisition", "merger agreement", ["8-K"], ["SPY", "MNA"], "BULLISH"),
    ("earnings-guidance", "raises guidance", ["8-K"], ["SPY", "QQQ"], "BULLISH"),
    ("share-buyback", "share repurchase program", ["8-K"], ["SPY"], "BULLISH"),
    ("insider-buying", "open market purchase", ["4"], ["SPY"], "BULLISH"),
    ("restatement", "restatement of previously issued financial statements", ["8-K"], ["SPY"], "BEARISH"),
    ("bankruptcy", "chapter 11", ["8-K"], ["HYG"], "BEARISH"),
    ("ceo-transition", "chief executive officer resignation", ["8-K"], ["SPY"], "NEUTRAL"),
]

DISPLAY_NAME_RE = re.compile(r"^(?P<name>.+?)\s*\((?P<ticker>[A-Z.\-]{1,10})\)\s*\(CIK\s*(?P<cik>\d+)\)$")


@dataclass
class SecFiling:
    title: str
    company: str
    ticker: str
    cik: str
    form: str
    category: str
    filed_date: str
    link: str
    bias: str


@dataclass
class SecFilingsReport:
    resources: list[dict[str, Any]]
    filings: list[SecFiling]
    by_category: dict[str, int]
    by_form: dict[str, int]
    filing_activity_score: float
    activity_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    used_proxy_filings: bool = False
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SecFilingsAnalyst(BaseExpert):
    """Securities/regulatory analyst — EDGAR full text search filing signals."""

    def __init__(
        self,
        lookback_days: int = 14,
        *,
        pipeline_context: dict | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="sec-filings")
        self.lookback_days = lookback_days

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
    def _catalog_resources() -> list[dict[str, Any]]:
        return [dict(res) for res in SEC_RESOURCES]

    @staticmethod
    def _filing_link(hit: dict[str, Any]) -> str:
        accession = str(hit.get("_id", "")).split(":", 1)[0]
        ciks = hit.get("_source", {}).get("ciks") or []
        if not accession or not ciks:
            return "https://www.sec.gov/edgar/search/#"
        cik = str(ciks[0]).lstrip("0") or "0"
        accession_nodash = accession.replace("-", "")
        return (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/"
            f"{accession}-index.htm"
        )

    @staticmethod
    def _parse_display_name(display_name: str) -> tuple[str, str, str]:
        match = DISPLAY_NAME_RE.match(display_name or "")
        if not match:
            return display_name or "Unknown", "", ""
        return match.group("name").strip(), match.group("ticker"), match.group("cik")

    def _fetch_full_text_search(
        self,
        category: str,
        query: str,
        forms: list[str],
        tickers: list[str],
        bias: str,
    ) -> list[SecFiling]:
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=self.lookback_days)
        params = {
            "q": f'"{query}"',
            "forms": ",".join(forms),
            "dateRange": "custom",
            "startdt": start.isoformat(),
            "enddt": end.isoformat(),
        }
        try:
            resp = requests.get(FULL_TEXT_SEARCH_API, params=params, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            hits = resp.json().get("hits", {}).get("hits", [])
        except Exception:
            return []

        filings: list[SecFiling] = []
        for hit in hits[:8]:
            source = hit.get("_source", {})
            display_names = source.get("display_names") or []
            company, ticker, cik = self._parse_display_name(display_names[0] if display_names else "")
            forms_found = source.get("forms") or forms
            filings.append(
                SecFiling(
                    title=f"{query.title()} — {company or 'Unknown filer'}",
                    company=company or "Unknown filer",
                    ticker=ticker,
                    cik=cik or (source.get("ciks") or [""])[0],
                    form=forms_found[0] if forms_found else forms[0],
                    category=category,
                    filed_date=source.get("file_date", ""),
                    link=self._filing_link(hit),
                    bias=bias,
                )
            )
        return filings

    @staticmethod
    def _proxy_filings() -> list[SecFiling]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return [
            SecFiling(
                title="Merger Agreement — Calibrated Industrials Corp",
                company="Calibrated Industrials Corp",
                ticker="CIC",
                cik="",
                form="8-K",
                category="merger-acquisition",
                filed_date=today,
                link="https://www.sec.gov/edgar/search/#",
                bias="BULLISH",
            ),
            SecFiling(
                title="Open Market Purchase — Proxy Semiconductor Inc",
                company="Proxy Semiconductor Inc",
                ticker="PSI",
                cik="",
                form="4",
                category="insider-buying",
                filed_date=today,
                link="https://www.sec.gov/edgar/search/#",
                bias="BULLISH",
            ),
            SecFiling(
                title="Share Repurchase Program — Calibrated Retail Group",
                company="Calibrated Retail Group",
                ticker="CRG",
                cik="",
                form="8-K",
                category="share-buyback",
                filed_date=today,
                link="https://www.sec.gov/edgar/search/#",
                bias="BULLISH",
            ),
            SecFiling(
                title="Chief Executive Officer Resignation — Proxy Energy Partners",
                company="Proxy Energy Partners",
                ticker="PEP1",
                cik="",
                form="8-K",
                category="ceo-transition",
                filed_date=today,
                link="https://www.sec.gov/edgar/search/#",
                bias="NEUTRAL",
            ),
        ]

    def _collect_filings(self) -> tuple[list[SecFiling], list[str], bool]:
        collected: list[SecFiling] = []
        sources: list[str] = []
        used_proxy = False
        for category, query, forms, tickers, bias in WATCH_QUERIES:
            items = self._fetch_full_text_search(category, query, forms, tickers, bias)
            if items:
                collected.extend(items)
                if "EDGAR Full Text Search" not in sources:
                    sources.append("EDGAR Full Text Search")

        if not collected:
            collected = self._proxy_filings()
            sources.append("Calibrated proxy feed")
            used_proxy = True

        seen: set[str] = set()
        deduped: list[SecFiling] = []
        for filing in collected:
            key = f"{filing.company.lower()}::{filing.category}::{filing.filed_date}"
            if key not in seen:
                seen.add(key)
                deduped.append(filing)
        return deduped, sources, used_proxy

    @staticmethod
    def _activity_score(by_category: dict[str, int], online: int) -> tuple[float, str]:
        active_categories = sum(1 for c in by_category.values() if c >= 1)
        score = min(100.0, active_categories * 12 + online * 2 + sum(by_category.values()) * 2.5)
        if score >= 70:
            label = "Elevated disclosure activity"
        elif score >= 40:
            label = "Moderate filing activity"
        else:
            label = "Quiet filing period"
        return round(score, 1), label

    def _market_signals(
        self,
        filings: list[SecFiling],
        by_category: dict[str, int],
        *,
        activity_score: float,
        used_proxy: bool,
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal

        signals: list[dict[str, Any]] = []
        category_lookup = {c: (t, b) for c, _, _, t, b in WATCH_QUERIES}
        ranked = sorted(by_category.items(), key=lambda x: -x[1])

        for category, count in ranked[:3]:
            if count < 1:
                continue
            _, default_bias = category_lookup.get(category, (["SPY"], "NEUTRAL"))
            filing_tickers = sorted({f.ticker for f in filings if f.category == category and f.ticker})
            category_biases = [f.bias for f in filings if f.category == category and f.bias]
            bias = max(set(category_biases), key=category_biases.count) if category_biases else default_bias
            signals.append(
                build_market_signal(
                    sector=category.replace("-", " ").title(),
                    tickers=filing_tickers or category_lookup.get(category, (["SPY"], "NEUTRAL"))[0],
                    bias=bias,
                    reason=f"{count} {category.replace('-', ' ')} filing(s) in {self.lookback_days}-day window",
                    confidence=min(0.85, 0.42 + count * 0.06 + activity_score / 200.0),
                    evidence={
                        "category": category,
                        "filing_count": count,
                        "lookback_days": self.lookback_days,
                        "used_proxy_filings": used_proxy,
                    },
                )
            )

        if not signals:
            signals.append(
                build_market_signal(
                    sector="Broad Market",
                    tickers=["SPY"],
                    bias="NEUTRAL",
                    reason=(
                        f"No material EDGAR filing clusters (activity score {activity_score:.0f})"
                        + (" — proxy feed" if used_proxy else "")
                    ),
                    confidence=0.42,
                    evidence={"filing_activity_score": activity_score, "used_proxy_filings": used_proxy},
                )
            )
        return self._adjust_market_signals(signals)

    def analyze(self) -> SecFilingsReport:
        resources = self._catalog_resources()
        online = len(resources)

        filings, sources, used_proxy = self._collect_filings()

        by_category: dict[str, int] = {}
        by_form: dict[str, int] = {}
        for f in filings:
            by_category[f.category] = by_category.get(f.category, 0) + 1
            by_form[f.form] = by_form.get(f.form, 0) + 1

        score, label = self._activity_score(by_category, online)
        top_category = max(by_category, key=by_category.get) if by_category else "none"

        summary = (
            f"Tracking {len(resources)} EDGAR data sources. "
            f"Surfaced {len(filings)} filing signals from {', '.join(sources)}. "
            f"Leading category: {top_category.replace('-', ' ')} "
            f"({by_category.get(top_category, 0)}). "
            f"Activity: {label} (score {score})."
        )

        signals = self._market_signals(
            filings, by_category, activity_score=score, used_proxy=used_proxy
        )
        recs = [
            summary,
            f"Data source: {DASHBOARD_URL} (EDGAR Full Text Search)",
        ]
        for category, count in sorted(by_category.items(), key=lambda x: -x[1])[:5]:
            recs.append(f"{category.replace('-', ' ').title()}: {count} filing(s)")
        for f in filings[:6]:
            recs.append(f"[{f.category}] {f.title[:80]} — {f.form} ({f.filed_date})")

        return SecFilingsReport(
            resources=resources,
            filings=filings,
            by_category=by_category,
            by_form=by_form,
            filing_activity_score=score,
            activity_label=label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_sources=sources,
            used_proxy_filings=used_proxy,
        )

    def to_dict(self, report: SecFilingsReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "SEC EDGAR Filings Analyst",
                "analyzed_at": report.analyzed_at,
                "data_sources": report.data_sources,
                "expert_summary": report.expert_summary,
                "resources_tracked": len(report.resources),
                "filings_count": len(report.filings),
                "dashboard": DASHBOARD_URL,
                "used_proxy_filings": report.used_proxy_filings,
            },
            "summary": {
                "by_category": report.by_category,
                "by_form": report.by_form,
                "filing_activity_score": report.filing_activity_score,
                "activity_label": report.activity_label,
            },
            "resources": report.resources,
            "filings": [
                {
                    "title": f.title,
                    "company": f.company,
                    "ticker": f.ticker,
                    "cik": f.cik,
                    "form": f.form,
                    "category": f.category,
                    "filed_date": f.filed_date,
                    "link": f.link,
                    "bias": f.bias,
                }
                for f in report.filings
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
            catalog_path = output.parent / "sec_edgar_resources.json"
            catalog_path.write_text(json.dumps(report.resources, indent=2), encoding="utf-8")
        return result


def run_sec_filings_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return SecFilingsAnalyst(pipeline_context=pipeline_context).run(output=output)
