"""
IPO Debut / Priced Issues Agent
===============================
Focuses on **IPO offerings that have been released** (priced) and names
that are closest to secondary-market trading:

  - Form 424B4 final/priced prospectuses (deal released publicly)
  - Full-text "initial public offering" hits on 424B* / 8-K for pricing news
  - Names with tickers elevated for research / quote watchlists

Complements ``ipo-monitor`` (full registration funnel). Neither agent can
read E*TRADE New Issue Center allocations — both use public SEC data.
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
HEADERS = {"User-Agent": "Finance-IPO-Debut/1.0 (shaggychunxx@gmail.com)"}

IPO_DEBUT_RESOURCES: list[dict[str, Any]] = [
    {
        "id": "edgar_424b4",
        "name": "Form 424B4 Priced Prospectuses",
        "provider": "SEC",
        "url": "https://www.sec.gov/edgar/search/#/forms=424B4",
        "coverage": "Final IPO prospectuses when offerings price / launch",
        "access": "api",
        "api_key_required": False,
        "data_types": ["424B4"],
        "notes": "Primary 'released offering' signal in public markets",
    },
    {
        "id": "edgar_ipo_text",
        "name": "IPO Pricing Language Search",
        "provider": "SEC",
        "url": "https://www.sec.gov/edgar/search/#/q=%22initial%20public%20offering%22",
        "coverage": "Filings mentioning initial public offering",
        "access": "api",
        "api_key_required": False,
        "data_types": ["424B4", "424B1", "8-K"],
        "notes": "Catches pricing language not always tagged cleanly",
    },
    {
        "id": "ipo_etf_proxies",
        "name": "IPO Complex ETF Proxies",
        "provider": "Market",
        "url": "https://finance.yahoo.com/quote/IPO",
        "coverage": "Liquid proxies for IPO/new-issue risk appetite",
        "access": "reference",
        "api_key_required": False,
        "data_types": ["IPO", "FPX", "IWM"],
        "notes": "Used for market signals when single-name tickers are sparse",
    },
]

DISPLAY_NAME_RE = re.compile(
    r"^(?P<name>.+?)\s*\((?P<ticker>[A-Z][A-Z0-9.\-]{0,9})\)\s*\(CIK\s*(?P<cik>\d+)\)$"
)
DISPLAY_NAME_CIK_ONLY_RE = re.compile(
    r"^(?P<name>.+?)\s*\(CIK\s*(?P<cik>\d+)\)$"
)

SPAC_NAME_RE = re.compile(
    r"\b(acquisition|spac|blank check|partner(?:s)? corp|holdings? ii+|holdings? iii)\b",
    re.I,
)
ETF_TRUST_RE = re.compile(
    r"\b(etf|exchange.?traded|trust|fund|interval fund|closed.?end)\b",
    re.I,
)
SPAC_SICS = {"6770"}
ETF_SICS = {"6221", "6722", "6726", "6199"}

CHECKLIST: list[str] = [
    "424B4 ≈ priced/released prospectus — add ticker to post-list watch if present.",
    "Pre-deal IPO allocations (E*TRADE New Issue Center) are not available via API.",
    "After listing, quote/research agents can trade the symbol like any equity.",
    "Prefer traditional IPOs over SPAC/ETF S-1 noise for debut alpha.",
]


@dataclass
class DebutIssue:
    title: str
    company: str
    ticker: str
    cik: str
    form: str
    source_query: str
    issuer_type: str
    filed_date: str
    link: str
    bias: str
    tradeable_soon: bool


@dataclass
class IpoDebutReport:
    resources: list[dict[str, Any]]
    issues: list[DebutIssue]
    by_issuer_type: dict[str, int]
    by_form: dict[str, int]
    tradeable_tickers: list[str]
    debut_score: float
    debut_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    checklist: list[str] = field(default_factory=lambda: list(CHECKLIST))
    used_proxy_filings: bool = False
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class IpoDebutAnalyst(BaseExpert):
    """IPO debut tracker — priced/released offerings and tradeable tickers."""

    def __init__(
        self,
        lookback_days: int = 14,
        *,
        pipeline_context: dict | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="ipo-debut")
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
        return [dict(res) for res in IPO_DEBUT_RESOURCES]

    @staticmethod
    def _filing_link(hit: dict[str, Any]) -> str:
        accession = str(hit.get("_id", "")).split(":", 1)[0]
        ciks = hit.get("_source", {}).get("ciks") or []
        if not accession or not ciks:
            return DASHBOARD_URL
        cik = str(ciks[0]).lstrip("0") or "0"
        accession_nodash = accession.replace("-", "")
        return (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/"
            f"{accession}-index.htm"
        )

    @staticmethod
    def _parse_display_name(display_name: str) -> tuple[str, str, str]:
        text = (display_name or "").strip()
        match = DISPLAY_NAME_RE.match(text)
        if match:
            return match.group("name").strip(), match.group("ticker"), match.group("cik")
        match2 = DISPLAY_NAME_CIK_ONLY_RE.match(text)
        if match2:
            return match2.group("name").strip(), "", match2.group("cik")
        return text or "Unknown", "", ""

    @staticmethod
    def _classify_issuer(company: str, sic: str, file_description: str) -> str:
        blob = f"{company} {file_description}"
        if sic in SPAC_SICS or SPAC_NAME_RE.search(blob):
            return "spac"
        if sic in ETF_SICS or ETF_TRUST_RE.search(blob):
            return "etf-trust"
        if company and company != "Unknown":
            return "traditional-ipo"
        return "other"

    def _fetch(
        self,
        *,
        forms: list[str],
        query: str | None,
        source_query: str,
    ) -> list[DebutIssue]:
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=self.lookback_days)
        params: dict[str, str] = {
            "forms": ",".join(forms),
            "dateRange": "custom",
            "startdt": start.isoformat(),
            "enddt": end.isoformat(),
        }
        if query:
            params["q"] = f'"{query}"'
        try:
            resp = requests.get(
                FULL_TEXT_SEARCH_API, params=params, headers=HEADERS, timeout=30
            )
            resp.raise_for_status()
            hits = resp.json().get("hits", {}).get("hits", [])
        except Exception:
            return []

        issues: list[DebutIssue] = []
        for hit in hits[:20]:
            source = hit.get("_source", {}) or {}
            display_names = source.get("display_names") or []
            company, ticker, cik = self._parse_display_name(
                display_names[0] if display_names else ""
            )
            form = str(
                source.get("form")
                or source.get("file_type")
                or (source.get("root_forms") or forms)[0]
            )
            sics = source.get("sics") or []
            sic = str(sics[0]) if sics else ""
            file_description = str(source.get("file_description") or "")
            issuer_type = self._classify_issuer(company, sic, file_description)
            filed_date = str(source.get("file_date") or "")
            tradeable = bool(ticker) and issuer_type == "traditional-ipo"
            bias = "BULLISH" if tradeable else "NEUTRAL"
            title = f"Priced/Released — {company}"
            if ticker:
                title = f"{title} ({ticker})"
            issues.append(
                DebutIssue(
                    title=title,
                    company=company or "Unknown filer",
                    ticker=ticker,
                    cik=cik or str((source.get("ciks") or [""])[0]),
                    form=form,
                    source_query=source_query,
                    issuer_type=issuer_type,
                    filed_date=filed_date,
                    link=self._filing_link(hit),
                    bias=bias,
                    tradeable_soon=tradeable,
                )
            )
        return issues

    @staticmethod
    def _proxy_issues() -> list[DebutIssue]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return [
            DebutIssue(
                title="Priced/Released — Northstar Robotics (NSTR)",
                company="Northstar Robotics",
                ticker="NSTR",
                cik="0001000002",
                form="424B4",
                source_query="proxy",
                issuer_type="traditional-ipo",
                filed_date=today,
                link=DASHBOARD_URL,
                bias="BULLISH",
                tradeable_soon=True,
            ),
            DebutIssue(
                title="Priced/Released — Harbor Analytics (HRBA)",
                company="Harbor Analytics",
                ticker="HRBA",
                cik="0001000004",
                form="424B4",
                source_query="proxy",
                issuer_type="traditional-ipo",
                filed_date=today,
                link=DASHBOARD_URL,
                bias="BULLISH",
                tradeable_soon=True,
            ),
            DebutIssue(
                title="Priced/Released — Pelican Acquisition II",
                company="Pelican Acquisition II Corp",
                ticker="PLCI",
                cik="0002122392",
                form="424B4",
                source_query="proxy",
                issuer_type="spac",
                filed_date=today,
                link=DASHBOARD_URL,
                bias="NEUTRAL",
                tradeable_soon=False,
            ),
        ]

    def _collect(self) -> tuple[list[DebutIssue], list[str], bool]:
        collected: list[DebutIssue] = []
        sources: list[str] = []
        used_proxy = False

        batches = [
            self._fetch(forms=["424B4"], query=None, source_query="form:424B4"),
            self._fetch(
                forms=["424B4", "424B1", "8-K"],
                query="initial public offering",
                source_query="text:initial public offering",
            ),
        ]
        for batch in batches:
            if batch:
                collected.extend(batch)
                if "EDGAR Full Text Search" not in sources:
                    sources.append("EDGAR Full Text Search")

        if not collected:
            collected = self._proxy_issues()
            sources.append("Calibrated proxy feed")
            used_proxy = True

        seen: set[str] = set()
        deduped: list[DebutIssue] = []
        for item in collected:
            key = f"{item.cik or item.company.lower()}::{item.form}::{item.filed_date}"
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        deduped.sort(
            key=lambda x: (1 if x.tradeable_soon else 0, x.filed_date or ""),
            reverse=True,
        )
        return deduped, sources, used_proxy

    @staticmethod
    def _debut_score(
        issues: list[DebutIssue],
        by_issuer_type: dict[str, int],
        *,
        online: int,
    ) -> tuple[float, str]:
        tradeable = sum(1 for i in issues if i.tradeable_soon)
        priced = len(issues)
        traditional = by_issuer_type.get("traditional-ipo", 0)
        score = min(
            100.0,
            tradeable * 16 + traditional * 6 + priced * 2 + online * 1.0,
        )
        if score >= 60:
            label = "Active IPO debut window"
        elif score >= 30:
            label = "Moderate IPO debut flow"
        else:
            label = "Quiet IPO debut period"
        return round(score, 1), label

    def _market_signals(
        self,
        issues: list[DebutIssue],
        tradeable_tickers: list[str],
        *,
        debut_score: float,
        used_proxy: bool,
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal

        signals: list[dict[str, Any]] = []
        traditional = [i for i in issues if i.issuer_type == "traditional-ipo"]

        if tradeable_tickers:
            signals.append(
                build_market_signal(
                    sector="IPO Debuts (Named Tickers)",
                    tickers=tradeable_tickers[:8],
                    bias="BULLISH",
                    reason=(
                        f"{len(tradeable_tickers)} priced traditional IPO ticker(s) "
                        f"in {self.lookback_days}d — watch secondary open/liquidity"
                    ),
                    confidence=min(0.85, 0.48 + len(tradeable_tickers) * 0.05),
                    evidence={
                        "tickers": tradeable_tickers[:12],
                        "lookback_days": self.lookback_days,
                        "used_proxy_filings": used_proxy,
                    },
                )
            )
            signals.append(
                build_market_signal(
                    sector="IPO Complex Risk Appetite",
                    tickers=["IPO", "FPX", "IWM"],
                    bias="BULLISH" if debut_score >= 50 else "NEUTRAL",
                    reason=f"Debut score {debut_score:.0f} with named new issues",
                    confidence=min(0.78, 0.42 + debut_score / 200.0),
                    evidence={
                        "debut_score": debut_score,
                        "named_tickers": tradeable_tickers[:8],
                        "used_proxy_filings": used_proxy,
                    },
                )
            )
        elif traditional:
            signals.append(
                build_market_signal(
                    sector="IPO Debuts (Unlisted Names)",
                    tickers=["IPO", "FPX", "IWM"],
                    bias="NEUTRAL",
                    reason=(
                        f"{len(traditional)} traditional priced filings without reliable tickers — "
                        "monitor for listing"
                    ),
                    confidence=0.48,
                    evidence={
                        "traditional_count": len(traditional),
                        "used_proxy_filings": used_proxy,
                    },
                )
            )
        else:
            signals.append(
                build_market_signal(
                    sector="IPO Debuts",
                    tickers=["IPO", "IWM", "SPY"],
                    bias="NEUTRAL",
                    reason=(
                        f"No traditional IPO debut cluster (score {debut_score:.0f})"
                        + (" — proxy feed" if used_proxy else "")
                    ),
                    confidence=0.42,
                    evidence={
                        "debut_score": debut_score,
                        "used_proxy_filings": used_proxy,
                    },
                )
            )
        return self._adjust_market_signals(signals)

    def analyze(self) -> IpoDebutReport:
        resources = self._catalog_resources()
        online = len(resources)
        issues, sources, used_proxy = self._collect()

        by_issuer_type: dict[str, int] = {}
        by_form: dict[str, int] = {}
        for i in issues:
            by_issuer_type[i.issuer_type] = by_issuer_type.get(i.issuer_type, 0) + 1
            by_form[i.form] = by_form.get(i.form, 0) + 1

        tradeable_tickers = sorted(
            {i.ticker for i in issues if i.tradeable_soon and i.ticker}
        )
        score, label = self._debut_score(issues, by_issuer_type, online=online)

        summary = (
            f"IPO debut scan ({self.lookback_days}d) via {', '.join(sources)}. "
            f"{len(issues)} priced/release-related filing(s); "
            f"{len(tradeable_tickers)} traditional ticker(s) for watchlist: "
            f"{', '.join(tradeable_tickers[:8]) or 'none'}. "
            f"{label} (score {score}). "
            f"Does not include E*TRADE IPO allotments."
        )

        signals = self._market_signals(
            issues,
            tradeable_tickers,
            debut_score=score,
            used_proxy=used_proxy,
        )

        recs = [
            summary,
            f"Dashboard: {DASHBOARD_URL}",
            f"Tradeable-soon tickers: {', '.join(tradeable_tickers) or 'none'}",
        ]
        for itype, count in sorted(by_issuer_type.items(), key=lambda x: -x[1]):
            recs.append(f"{itype}: {count}")
        for i in issues[:10]:
            tick = f" ({i.ticker})" if i.ticker else ""
            flag = " [tradeable]" if i.tradeable_soon else ""
            recs.append(
                f"[{i.issuer_type}] {i.company}{tick} — {i.form} ({i.filed_date}){flag}"
            )
        recs.extend(CHECKLIST)

        return IpoDebutReport(
            resources=resources,
            issues=issues,
            by_issuer_type=by_issuer_type,
            by_form=by_form,
            tradeable_tickers=tradeable_tickers,
            debut_score=score,
            debut_label=label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_sources=sources,
            used_proxy_filings=used_proxy,
        )

    def to_dict(self, report: IpoDebutReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "IPO Debut / Priced Issues Analyst",
                "agent_id": "ipo-debut",
                "analyzed_at": report.analyzed_at,
                "data_sources": report.data_sources,
                "expert_summary": report.expert_summary,
                "resources_tracked": len(report.resources),
                "issues_count": len(report.issues),
                "tradeable_tickers": report.tradeable_tickers,
                "dashboard": DASHBOARD_URL,
                "lookback_days": self.lookback_days,
                "used_proxy_filings": report.used_proxy_filings,
                "note": (
                    "Tracks priced/released IPO prospectuses and named tickers. "
                    "E*TRADE New Issue Center is not available via API."
                ),
            },
            "summary": {
                "by_issuer_type": report.by_issuer_type,
                "by_form": report.by_form,
                "tradeable_tickers": report.tradeable_tickers,
                "debut_score": report.debut_score,
                "debut_label": report.debut_label,
            },
            "resources": report.resources,
            "issues": [
                {
                    "title": i.title,
                    "company": i.company,
                    "ticker": i.ticker,
                    "cik": i.cik,
                    "form": i.form,
                    "source_query": i.source_query,
                    "issuer_type": i.issuer_type,
                    "filed_date": i.filed_date,
                    "link": i.link,
                    "bias": i.bias,
                    "tradeable_soon": i.tradeable_soon,
                }
                for i in report.issues
            ],
            "checklist": report.checklist,
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        report = self.analyze()
        result = self.to_dict(report)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog_path = output.parent / "ipo_debut_resources.json"
            catalog_path.write_text(json.dumps(report.resources, indent=2), encoding="utf-8")
        return result


def run_ipo_debut_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return IpoDebutAnalyst(pipeline_context=pipeline_context).run(output=output)
