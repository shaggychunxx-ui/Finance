"""
Corporate Equity Structuring Analyst Agent
===========================================
Tracks the toolkit public companies use to manage post-IPO equity capital —
dilution, At-the-Market (ATM) offerings, shelf registrations, and secondary
(follow-on) offerings — via the SEC's EDGAR Full Text Search system, and
classifies filing-driven dilution pressure signals.

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
HEADERS = {"User-Agent": "Finance-Equity-Structuring-Analyst/1.0 (shaggychunxx@gmail.com)"}

EQUITY_STRUCTURING_RESOURCES: list[dict[str, Any]] = [
    {
        "id": "edgar_full_text_search",
        "name": "EDGAR Full Text Search",
        "provider": "SEC",
        "url": "https://www.sec.gov/edgar/search/#",
        "coverage": "All EDGAR filings, 2001+",
        "access": "api",
        "api_key_required": False,
        "data_types": ["S-3", "424B5", "8-K", "S-1"],
        "notes": "Primary data source for this agent; backed by efts.sec.gov search-index",
    },
    {
        "id": "edgar_shelf_registrations",
        "name": "Form S-3 Shelf Registrations",
        "provider": "SEC",
        "url": "https://www.sec.gov/edgar/search/#/forms=S-3",
        "coverage": "Universal shelf registrations (multi-year equity facilities)",
        "access": "api",
        "api_key_required": False,
        "data_types": ["S-3", "S-3ASR"],
        "notes": "Upper-limit dollar authorization filed ahead of ATM/follow-on issuance",
    },
    {
        "id": "edgar_prospectus_supplements",
        "name": "Form 424B5 Prospectus Supplements",
        "provider": "SEC",
        "url": "https://www.sec.gov/edgar/search/#/forms=424B5",
        "coverage": "ATM sales agreements, follow-on/secondary pricing supplements",
        "access": "api",
        "api_key_required": False,
        "data_types": ["424B5"],
        "notes": "Discloses sales agent, offering size, and use of proceeds",
    },
    {
        "id": "edgar_form4_insider",
        "name": "Form 4 Insider Transactions",
        "provider": "SEC",
        "url": "https://www.sec.gov/edgar/search/#/forms=4",
        "coverage": "Officer/director/10% owner sales during secondary offerings",
        "access": "api",
        "api_key_required": False,
        "data_types": ["insider sells"],
        "notes": "Used to gauge insider alignment on non-dilutive secondary sales",
    },
    {
        "id": "edgar_xbrl_company_facts",
        "name": "EDGAR XBRL Company Facts API",
        "provider": "SEC",
        "url": "https://data.sec.gov/api/xbrl/companyfacts/",
        "coverage": "Structured financial statement facts",
        "access": "api",
        "api_key_required": False,
        "data_types": ["shares outstanding", "additional paid-in capital"],
        "notes": "Used to compute dilution percentage vs prior shares outstanding",
    },
]

# (category, query, forms, tickers, offering_type, bias)
WATCH_QUERIES: list[tuple[str, str, list[str], list[str], str, str]] = [
    (
        "atm-shelf-registration",
        "at-the-market offering",
        ["424B5"],
        ["SPY", "IWM"],
        "atm",
        "BEARISH",
    ),
    (
        "shelf-registration",
        "shelf registration statement",
        ["S-3"],
        ["SPY"],
        "shelf",
        "NEUTRAL",
    ),
    (
        "dilutive-follow-on",
        "follow-on public offering",
        ["424B5"],
        ["SPY", "IWM"],
        "dilutive",
        "BEARISH",
    ),
    (
        "secondary-non-dilutive",
        "selling stockholders",
        ["424B5"],
        ["SPY"],
        "non-dilutive",
        "NEUTRAL",
    ),
    (
        "convertible-death-spiral",
        "convertible notes",
        ["8-K"],
        ["IWM"],
        "dilutive",
        "BEARISH",
    ),
]

DISPLAY_NAME_RE = re.compile(r"^(?P<name>.+?)\s*\((?P<ticker>[A-Z.\-]{1,10})\)\s*\(CIK\s*(?P<cik>\d+)\)$")

OFFERING_TYPE_LABELS: dict[str, str] = {
    "atm": "At-the-Market (ATM) Offering",
    "shelf": "Shelf Registration (S-3)",
    "dilutive": "Dilutive Follow-On (Primary Shares)",
    "non-dilutive": "Non-Dilutive Secondary (Insider Shares)",
}

CHECKLIST: list[str] = [
    "Read the Prospectus: determine primary (dilutive) vs secondary (non-dilutive insider) offering.",
    "Calculate the Dilution Percentage: new shares divided by current shares outstanding.",
    "Identify the Use of Proceeds: debt retirement or cash-burn funding are red flags; high-yield capex is a green flag.",
    "Track Insider Alignment: if secondary, flag CEO/insider sales exceeding 20% of their stake.",
]


@dataclass
class EquityOffering:
    title: str
    company: str
    ticker: str
    cik: str
    form: str
    category: str
    offering_type: str
    filed_date: str
    link: str
    bias: str


@dataclass
class EquityStructuringReport:
    resources: list[dict[str, Any]]
    offerings: list[EquityOffering]
    by_category: dict[str, int]
    by_offering_type: dict[str, int]
    dilution_pressure_score: float
    pressure_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    checklist: list[str] = field(default_factory=lambda: list(CHECKLIST))
    used_proxy_filings: bool = False
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EquityStructuringAnalyst(BaseExpert):
    """Corporate finance analyst — dilution / ATM / secondary offering signals."""

    def __init__(
        self,
        lookback_days: int = 14,
        *,
        pipeline_context: dict | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="equity-structuring")
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
        return [dict(res) for res in EQUITY_STRUCTURING_RESOURCES]

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
        offering_type: str,
        bias: str,
    ) -> list[EquityOffering]:
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

        offerings: list[EquityOffering] = []
        for hit in hits[:8]:
            source = hit.get("_source", {})
            display_names = source.get("display_names") or []
            company, ticker, cik = self._parse_display_name(display_names[0] if display_names else "")
            forms_found = source.get("forms") or forms
            offerings.append(
                EquityOffering(
                    title=f"{query.title()} — {company or 'Unknown filer'}",
                    company=company or "Unknown filer",
                    ticker=ticker,
                    cik=cik or (source.get("ciks") or [""])[0],
                    form=forms_found[0] if forms_found else forms[0],
                    category=category,
                    offering_type=offering_type,
                    filed_date=source.get("file_date", ""),
                    link=self._filing_link(hit),
                    bias=bias,
                )
            )
        return offerings

    @staticmethod
    def _proxy_offerings() -> list[EquityOffering]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return [
            EquityOffering(
                title="At-The-Market Offering — Calibrated Growth Corp",
                company="Calibrated Growth Corp",
                ticker="CGC1",
                cik="",
                form="424B5",
                category="atm-shelf-registration",
                offering_type="atm",
                filed_date=today,
                link="https://www.sec.gov/edgar/search/#",
                bias="BEARISH",
            ),
            EquityOffering(
                title="Shelf Registration Statement — Proxy Industrials Inc",
                company="Proxy Industrials Inc",
                ticker="PII",
                cik="",
                form="S-3",
                category="shelf-registration",
                offering_type="shelf",
                filed_date=today,
                link="https://www.sec.gov/edgar/search/#",
                bias="NEUTRAL",
            ),
            EquityOffering(
                title="Follow-On Public Offering — Calibrated Biotech Partners",
                company="Calibrated Biotech Partners",
                ticker="CBP",
                cik="",
                form="424B5",
                category="dilutive-follow-on",
                offering_type="dilutive",
                filed_date=today,
                link="https://www.sec.gov/edgar/search/#",
                bias="BEARISH",
            ),
            EquityOffering(
                title="Selling Stockholders Prospectus — Proxy Retail Holdings",
                company="Proxy Retail Holdings",
                ticker="PRH",
                cik="",
                form="424B5",
                category="secondary-non-dilutive",
                offering_type="non-dilutive",
                filed_date=today,
                link="https://www.sec.gov/edgar/search/#",
                bias="NEUTRAL",
            ),
        ]

    def _collect_offerings(self) -> tuple[list[EquityOffering], list[str], bool]:
        collected: list[EquityOffering] = []
        sources: list[str] = []
        used_proxy = False
        for category, query, forms, tickers, offering_type, bias in WATCH_QUERIES:
            items = self._fetch_full_text_search(category, query, forms, tickers, offering_type, bias)
            if items:
                collected.extend(items)
                if "EDGAR Full Text Search" not in sources:
                    sources.append("EDGAR Full Text Search")

        if not collected:
            collected = self._proxy_offerings()
            sources.append("Calibrated proxy feed")
            used_proxy = True

        seen: set[str] = set()
        deduped: list[EquityOffering] = []
        for offering in collected:
            key = f"{offering.company.lower()}::{offering.category}::{offering.filed_date}"
            if key not in seen:
                seen.add(key)
                deduped.append(offering)
        return deduped, sources, used_proxy

    @staticmethod
    def _pressure_score(by_offering_type: dict[str, int], online: int) -> tuple[float, str]:
        # ATM and dilutive follow-ons weigh heavier on the dilution pressure gauge
        # than shelf registrations (authorization only) or non-dilutive secondaries.
        weighted = (
            by_offering_type.get("atm", 0) * 14
            + by_offering_type.get("dilutive", 0) * 12
            + by_offering_type.get("shelf", 0) * 5
            + by_offering_type.get("non-dilutive", 0) * 4
        )
        score = min(100.0, weighted + online * 1.5)
        if score >= 65:
            label = "Elevated dilution pressure"
        elif score >= 35:
            label = "Moderate equity issuance activity"
        else:
            label = "Quiet issuance period"
        return round(score, 1), label

    def _market_signals(
        self,
        offerings: list[EquityOffering],
        by_offering_type: dict[str, int],
        *,
        pressure_score: float,
        used_proxy: bool,
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal

        signals: list[dict[str, Any]] = []
        type_lookup = {ot: (t, b) for _, _, _, t, ot, b in WATCH_QUERIES}
        ranked = sorted(by_offering_type.items(), key=lambda x: -x[1])

        for offering_type, count in ranked[:3]:
            if count < 1:
                continue
            default_tickers, default_bias = type_lookup.get(offering_type, (["SPY"], "NEUTRAL"))
            type_tickers = sorted({o.ticker for o in offerings if o.offering_type == offering_type and o.ticker})
            type_biases = [o.bias for o in offerings if o.offering_type == offering_type and o.bias]
            bias = max(set(type_biases), key=type_biases.count) if type_biases else default_bias
            label = OFFERING_TYPE_LABELS.get(offering_type, offering_type.title())
            signals.append(
                build_market_signal(
                    sector=label,
                    tickers=type_tickers or default_tickers,
                    bias=bias,
                    reason=f"{count} {label.lower()} filing(s) in {self.lookback_days}-day window",
                    confidence=min(0.85, 0.42 + count * 0.06 + pressure_score / 200.0),
                    evidence={
                        "offering_type": offering_type,
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
                        f"No material equity issuance clusters (pressure score {pressure_score:.0f})"
                        + (" — proxy feed" if used_proxy else "")
                    ),
                    confidence=0.42,
                    evidence={"dilution_pressure_score": pressure_score, "used_proxy_filings": used_proxy},
                )
            )
        return self._adjust_market_signals(signals)

    def analyze(self) -> EquityStructuringReport:
        resources = self._catalog_resources()
        online = len(resources)

        offerings, sources, used_proxy = self._collect_offerings()

        by_category: dict[str, int] = {}
        by_offering_type: dict[str, int] = {}
        for o in offerings:
            by_category[o.category] = by_category.get(o.category, 0) + 1
            by_offering_type[o.offering_type] = by_offering_type.get(o.offering_type, 0) + 1

        score, label = self._pressure_score(by_offering_type, online)
        top_category = max(by_category, key=by_category.get) if by_category else "none"
        top_category_count = by_category.get(top_category, 0) if by_category else 0

        summary = (
            f"Tracking {len(resources)} EDGAR data sources. "
            f"Surfaced {len(offerings)} equity structuring signals from {', '.join(sources)}. "
            f"Leading category: {top_category.replace('-', ' ')} "
            f"({top_category_count}). "
            f"Dilution pressure: {label} (score {score})."
        )

        signals = self._market_signals(
            offerings, by_offering_type, pressure_score=score, used_proxy=used_proxy
        )
        recs = [
            summary,
            f"Data source: {DASHBOARD_URL} (EDGAR Full Text Search)",
        ]
        for offering_type, count in sorted(by_offering_type.items(), key=lambda x: -x[1]):
            recs.append(f"{OFFERING_TYPE_LABELS.get(offering_type, offering_type.title())}: {count} filing(s)")
        for o in offerings[:6]:
            recs.append(f"[{o.offering_type}] {o.title[:80]} — {o.form} ({o.filed_date})")
        recs.extend(CHECKLIST)

        return EquityStructuringReport(
            resources=resources,
            offerings=offerings,
            by_category=by_category,
            by_offering_type=by_offering_type,
            dilution_pressure_score=score,
            pressure_label=label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_sources=sources,
            used_proxy_filings=used_proxy,
        )

    def to_dict(self, report: EquityStructuringReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Corporate Equity Structuring Analyst",
                "analyzed_at": report.analyzed_at,
                "data_sources": report.data_sources,
                "expert_summary": report.expert_summary,
                "resources_tracked": len(report.resources),
                "offerings_count": len(report.offerings),
                "dashboard": DASHBOARD_URL,
                "used_proxy_filings": report.used_proxy_filings,
            },
            "summary": {
                "by_category": report.by_category,
                "by_offering_type": report.by_offering_type,
                "dilution_pressure_score": report.dilution_pressure_score,
                "pressure_label": report.pressure_label,
            },
            "resources": report.resources,
            "offerings": [
                {
                    "title": o.title,
                    "company": o.company,
                    "ticker": o.ticker,
                    "cik": o.cik,
                    "form": o.form,
                    "category": o.category,
                    "offering_type": o.offering_type,
                    "filed_date": o.filed_date,
                    "link": o.link,
                    "bias": o.bias,
                }
                for o in report.offerings
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
            catalog_path = output.parent / "equity_structuring_resources.json"
            catalog_path.write_text(json.dumps(report.resources, indent=2), encoding="utf-8")
        return result


def run_equity_structuring_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return EquityStructuringAnalyst(pipeline_context=pipeline_context).run(output=output)
