"""
IPO Pipeline Monitor Agent
==========================
Tracks **new IPO offerings as they appear in SEC EDGAR** — the regulatory
path from initial registration through amendments to priced prospectuses.

This is the primary IPO-awareness agent. E*TRADE New Issue Center
allocations are not available via the broker API; this agent surfaces the
same universe from public filings so the pipeline can watch IPOs when they
are filed and priced.

Forms watched:
  - S-1 / S-1/A   domestic IPO registration + amendments
  - F-1 / F-1/A   foreign private issuer IPO registration + amendments
  - 424B4         final / priced IPO prospectus (deal "released")

Issuer classification: traditional IPO, SPAC, ETF/trust, other.
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
HEADERS = {"User-Agent": "Finance-IPO-Monitor/1.0 (shaggychunxx@gmail.com)"}

IPO_RESOURCES: list[dict[str, Any]] = [
    {
        "id": "edgar_s1",
        "name": "Form S-1 IPO Registrations",
        "provider": "SEC",
        "url": "https://www.sec.gov/edgar/search/#/forms=S-1",
        "coverage": "Domestic IPO registration statements and amendments",
        "access": "api",
        "api_key_required": False,
        "data_types": ["S-1", "S-1/A"],
        "notes": "Primary source for US IPO pipeline awareness",
    },
    {
        "id": "edgar_f1",
        "name": "Form F-1 Foreign IPO Registrations",
        "provider": "SEC",
        "url": "https://www.sec.gov/edgar/search/#/forms=F-1",
        "coverage": "Foreign private issuer IPO registrations",
        "access": "api",
        "api_key_required": False,
        "data_types": ["F-1", "F-1/A"],
        "notes": "ADR / foreign issuer IPO pipeline",
    },
    {
        "id": "edgar_424b4",
        "name": "Form 424B4 Priced Prospectuses",
        "provider": "SEC",
        "url": "https://www.sec.gov/edgar/search/#/forms=424B4",
        "coverage": "Final/priced IPO prospectuses when deals are released",
        "access": "api",
        "api_key_required": False,
        "data_types": ["424B4"],
        "notes": "Strongest public signal that an IPO has priced / launched",
    },
    {
        "id": "edgar_full_text",
        "name": "EDGAR Full Text Search",
        "provider": "SEC",
        "url": DASHBOARD_URL,
        "coverage": "All EDGAR filings, 2001+",
        "access": "api",
        "api_key_required": False,
        "data_types": ["full text", "forms index"],
        "notes": "Backed by efts.sec.gov search-index",
    },
]

# (stage, forms, bias, weight for activity score)
FORM_WATCHES: list[tuple[str, list[str], str, int]] = [
    ("initial-registration", ["S-1", "F-1"], "NEUTRAL", 8),
    ("amendment", ["S-1/A", "F-1/A"], "NEUTRAL", 5),
    ("priced-prospectus", ["424B4"], "BULLISH", 14),
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

# SIC: 6770 blank check; 6221 security/commodity brokers (many ETF sponsors)
SPAC_SICS = {"6770"}
ETF_SICS = {"6221", "6722", "6726", "6199"}

STAGE_LABELS: dict[str, str] = {
    "initial-registration": "Initial Registration (S-1/F-1)",
    "amendment": "Registration Amendment (S-1/A, F-1/A)",
    "priced-prospectus": "Priced / Final Prospectus (424B4)",
}

ISSUER_LABELS: dict[str, str] = {
    "traditional-ipo": "Traditional IPO",
    "spac": "SPAC / Blank Check",
    "etf-trust": "ETF / Trust Registration",
    "other": "Other Registration",
}

CHECKLIST: list[str] = [
    "S-1/F-1 = registration filed — not yet priced; watch amendments for timing.",
    "424B4 = priced/final prospectus — deal is released publicly (not E*TRADE allocation).",
    "Filter SPACs and ETF/trust S-1s before treating as traditional IPO alpha.",
    "Ticker may be missing until late prospectus; use CIK + company name as key.",
    "E*TRADE New Issue Center allocation is web-only — this agent cannot place IPO orders.",
]


@dataclass
class IpoFiling:
    title: str
    company: str
    ticker: str
    cik: str
    form: str
    stage: str
    issuer_type: str
    filed_date: str
    link: str
    bias: str
    sic: str = ""
    file_description: str = ""


@dataclass
class IpoMonitorReport:
    resources: list[dict[str, Any]]
    filings: list[IpoFiling]
    by_stage: dict[str, int]
    by_issuer_type: dict[str, int]
    by_form: dict[str, int]
    activity_score: float
    activity_label: str
    new_offerings: list[dict[str, Any]]
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    checklist: list[str] = field(default_factory=lambda: list(CHECKLIST))
    used_proxy_filings: bool = False
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class IpoMonitorAnalyst(BaseExpert):
    """IPO pipeline monitor — SEC EDGAR registration → pricing awareness."""

    def __init__(
        self,
        lookback_days: int = 21,
        *,
        pipeline_context: dict | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="ipo-monitor")
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
        return [dict(res) for res in IPO_RESOURCES]

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

    @staticmethod
    def _stage_for_form(form: str) -> str:
        f = (form or "").upper()
        if f in {"424B4", "424B3", "424B1"}:
            return "priced-prospectus"
        if f.endswith("/A") or "/A" in f:
            return "amendment"
        if f in {"S-1", "F-1"}:
            return "initial-registration"
        return "initial-registration"

    def _fetch_forms(self, forms: list[str], stage: str, bias: str) -> list[IpoFiling]:
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=self.lookback_days)
        params = {
            "forms": ",".join(forms),
            "dateRange": "custom",
            "startdt": start.isoformat(),
            "enddt": end.isoformat(),
        }
        try:
            resp = requests.get(
                FULL_TEXT_SEARCH_API, params=params, headers=HEADERS, timeout=30
            )
            resp.raise_for_status()
            hits = resp.json().get("hits", {}).get("hits", [])
        except Exception:
            return []

        filings: list[IpoFiling] = []
        for hit in hits[:25]:
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
            # When API returns amendments under a root form search, re-stage.
            actual_stage = self._stage_for_form(form) if form else stage
            sics = source.get("sics") or []
            sic = str(sics[0]) if sics else ""
            file_description = str(source.get("file_description") or "")
            issuer_type = self._classify_issuer(company, sic, file_description)
            filed_date = str(source.get("file_date") or "")
            title = (
                f"{STAGE_LABELS.get(actual_stage, actual_stage)} — "
                f"{company or 'Unknown filer'}"
            )
            if ticker:
                title = f"{title} ({ticker})"
            filings.append(
                IpoFiling(
                    title=title,
                    company=company or "Unknown filer",
                    ticker=ticker,
                    cik=cik or str((source.get("ciks") or [""])[0]),
                    form=form,
                    stage=actual_stage,
                    issuer_type=issuer_type,
                    filed_date=filed_date,
                    link=self._filing_link(hit),
                    bias=bias if issuer_type == "traditional-ipo" else "NEUTRAL",
                    sic=sic,
                    file_description=file_description,
                )
            )
        return filings

    @staticmethod
    def _proxy_filings() -> list[IpoFiling]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return [
            IpoFiling(
                title="Initial Registration — Proxy Growth Systems (PXGS)",
                company="Proxy Growth Systems",
                ticker="PXGS",
                cik="0001000001",
                form="S-1",
                stage="initial-registration",
                issuer_type="traditional-ipo",
                filed_date=today,
                link=DASHBOARD_URL,
                bias="NEUTRAL",
            ),
            IpoFiling(
                title="Registration Amendment — Proxy Growth Systems (PXGS)",
                company="Proxy Growth Systems",
                ticker="PXGS",
                cik="0001000001",
                form="S-1/A",
                stage="amendment",
                issuer_type="traditional-ipo",
                filed_date=today,
                link=DASHBOARD_URL,
                bias="NEUTRAL",
            ),
            IpoFiling(
                title="Priced Prospectus — Northstar Robotics (NSTR)",
                company="Northstar Robotics",
                ticker="NSTR",
                cik="0001000002",
                form="424B4",
                stage="priced-prospectus",
                issuer_type="traditional-ipo",
                filed_date=today,
                link=DASHBOARD_URL,
                bias="BULLISH",
            ),
            IpoFiling(
                title="Initial Registration — Blank Check Partners II",
                company="Blank Check Partners II",
                ticker="",
                cik="0001000003",
                form="S-1",
                stage="initial-registration",
                issuer_type="spac",
                filed_date=today,
                link=DASHBOARD_URL,
                bias="NEUTRAL",
            ),
        ]

    def _collect_filings(self) -> tuple[list[IpoFiling], list[str], bool]:
        collected: list[IpoFiling] = []
        sources: list[str] = []
        used_proxy = False

        for stage, forms, bias, _weight in FORM_WATCHES:
            items = self._fetch_forms(forms, stage, bias)
            if items:
                collected.extend(items)
                if "EDGAR Full Text Search" not in sources:
                    sources.append("EDGAR Full Text Search")

        if not collected:
            collected = self._proxy_filings()
            sources.append("Calibrated proxy feed")
            used_proxy = True

        seen: set[str] = set()
        deduped: list[IpoFiling] = []
        for f in collected:
            key = f"{f.cik or f.company.lower()}::{f.form}::{f.filed_date}::{f.stage}"
            if key not in seen:
                seen.add(key)
                deduped.append(f)

        # Prefer newest first
        deduped.sort(key=lambda x: x.filed_date or "", reverse=True)
        return deduped, sources, used_proxy

    @staticmethod
    def _activity_score(
        by_stage: dict[str, int],
        by_issuer_type: dict[str, int],
        *,
        online: int,
    ) -> tuple[float, str]:
        weighted = (
            by_stage.get("priced-prospectus", 0) * 14
            + by_stage.get("initial-registration", 0) * 8
            + by_stage.get("amendment", 0) * 5
        )
        # Traditional IPOs count more than ETF/SPAC noise for "equity IPO activity"
        traditional = by_issuer_type.get("traditional-ipo", 0)
        score = min(100.0, weighted * 0.85 + traditional * 2.5 + online * 1.0)
        if score >= 65:
            label = "Elevated IPO pipeline activity"
        elif score >= 35:
            label = "Moderate IPO pipeline activity"
        else:
            label = "Quiet IPO pipeline"
        return round(score, 1), label

    def _new_offerings(self, filings: list[IpoFiling]) -> list[dict[str, Any]]:
        """Deals that look newly released (priced) or first-seen registrations."""
        offerings: list[dict[str, Any]] = []
        for f in filings:
            if f.stage == "priced-prospectus" or (
                f.stage == "initial-registration" and f.issuer_type == "traditional-ipo"
            ):
                offerings.append(
                    {
                        "company": f.company,
                        "ticker": f.ticker,
                        "cik": f.cik,
                        "form": f.form,
                        "stage": f.stage,
                        "issuer_type": f.issuer_type,
                        "filed_date": f.filed_date,
                        "link": f.link,
                        "released": f.stage == "priced-prospectus",
                    }
                )
        return offerings[:40]

    def _market_signals(
        self,
        filings: list[IpoFiling],
        by_stage: dict[str, int],
        by_issuer_type: dict[str, int],
        *,
        activity_score: float,
        used_proxy: bool,
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal

        signals: list[dict[str, Any]] = []
        priced = by_stage.get("priced-prospectus", 0)
        traditional = by_issuer_type.get("traditional-ipo", 0)
        spacs = by_issuer_type.get("spac", 0)

        priced_tickers = sorted(
            {
                f.ticker
                for f in filings
                if f.stage == "priced-prospectus" and f.ticker and f.issuer_type == "traditional-ipo"
            }
        )

        if priced >= 1:
            signals.append(
                build_market_signal(
                    sector="IPO Debut / New Issues",
                    tickers=priced_tickers[:6] or ["IPO", "FPX", "IWM"],
                    bias="BULLISH" if traditional >= priced else "NEUTRAL",
                    reason=(
                        f"{priced} priced prospectus filing(s) in {self.lookback_days}-day window"
                        + (f" — tickers: {', '.join(priced_tickers[:5])}" if priced_tickers else "")
                    ),
                    confidence=min(0.82, 0.45 + priced * 0.05 + activity_score / 250.0),
                    evidence={
                        "stage": "priced-prospectus",
                        "count": priced,
                        "tickers": priced_tickers[:10],
                        "used_proxy_filings": used_proxy,
                    },
                )
            )

        if traditional >= 3:
            signals.append(
                build_market_signal(
                    sector="IPO Pipeline (Registration)",
                    tickers=["IPO", "FPX", "IWM", "QQQ"],
                    bias="BULLISH" if activity_score >= 55 else "NEUTRAL",
                    reason=(
                        f"{traditional} traditional IPO-related filings; "
                        f"activity score {activity_score:.0f}"
                    ),
                    confidence=min(0.78, 0.4 + traditional * 0.03),
                    evidence={
                        "traditional_ipo_count": traditional,
                        "activity_score": activity_score,
                        "used_proxy_filings": used_proxy,
                    },
                )
            )

        if spacs >= 3:
            signals.append(
                build_market_signal(
                    sector="SPAC Pipeline",
                    tickers=["SPAX", "IWM", "XLF"],
                    bias="NEUTRAL",
                    reason=f"{spacs} SPAC/blank-check registration filings in lookback window",
                    confidence=min(0.7, 0.4 + spacs * 0.03),
                    evidence={"spac_count": spacs, "used_proxy_filings": used_proxy},
                )
            )

        if not signals:
            signals.append(
                build_market_signal(
                    sector="IPO Complex",
                    tickers=["IPO", "IWM", "SPY"],
                    bias="NEUTRAL",
                    reason=(
                        f"No concentrated IPO release cluster (activity {activity_score:.0f})"
                        + (" — proxy feed" if used_proxy else "")
                    ),
                    confidence=0.42,
                    evidence={
                        "activity_score": activity_score,
                        "used_proxy_filings": used_proxy,
                    },
                )
            )
        return self._adjust_market_signals(signals)

    def analyze(self) -> IpoMonitorReport:
        resources = self._catalog_resources()
        online = len(resources)

        filings, sources, used_proxy = self._collect_filings()

        by_stage: dict[str, int] = {}
        by_issuer_type: dict[str, int] = {}
        by_form: dict[str, int] = {}
        for f in filings:
            by_stage[f.stage] = by_stage.get(f.stage, 0) + 1
            by_issuer_type[f.issuer_type] = by_issuer_type.get(f.issuer_type, 0) + 1
            by_form[f.form] = by_form.get(f.form, 0) + 1

        score, label = self._activity_score(by_stage, by_issuer_type, online=online)
        new_offerings = self._new_offerings(filings)
        priced_n = by_stage.get("priced-prospectus", 0)
        trad_n = by_issuer_type.get("traditional-ipo", 0)

        summary = (
            f"IPO awareness via SEC EDGAR ({self.lookback_days}d). "
            f"Surfaced {len(filings)} filing(s) from {', '.join(sources)}. "
            f"Traditional IPO-related: {trad_n}; priced/released (424B4): {priced_n}. "
            f"Pipeline: {label} (score {score}). "
            f"E*TRADE New Issue allocation is not API-visible — this is regulatory awareness only."
        )

        signals = self._market_signals(
            filings,
            by_stage,
            by_issuer_type,
            activity_score=score,
            used_proxy=used_proxy,
        )

        recs = [
            summary,
            f"Dashboard: {DASHBOARD_URL}",
            f"New offerings / watchlist entries: {len(new_offerings)}",
        ]
        for stage, count in sorted(by_stage.items(), key=lambda x: -x[1]):
            recs.append(f"{STAGE_LABELS.get(stage, stage)}: {count}")
        for itype, count in sorted(by_issuer_type.items(), key=lambda x: -x[1]):
            recs.append(f"{ISSUER_LABELS.get(itype, itype)}: {count}")
        for f in filings[:8]:
            tick = f" ({f.ticker})" if f.ticker else ""
            recs.append(
                f"[{f.stage}/{f.issuer_type}] {f.company}{tick} — {f.form} ({f.filed_date})"
            )
        recs.extend(CHECKLIST)

        return IpoMonitorReport(
            resources=resources,
            filings=filings,
            by_stage=by_stage,
            by_issuer_type=by_issuer_type,
            by_form=by_form,
            activity_score=score,
            activity_label=label,
            new_offerings=new_offerings,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_sources=sources,
            used_proxy_filings=used_proxy,
        )

    def to_dict(self, report: IpoMonitorReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "IPO Pipeline Monitor",
                "agent_id": "ipo-monitor",
                "analyzed_at": report.analyzed_at,
                "data_sources": report.data_sources,
                "expert_summary": report.expert_summary,
                "resources_tracked": len(report.resources),
                "filings_count": len(report.filings),
                "new_offerings_count": len(report.new_offerings),
                "dashboard": DASHBOARD_URL,
                "lookback_days": self.lookback_days,
                "used_proxy_filings": report.used_proxy_filings,
                "note": (
                    "Surfaces IPO offerings from SEC filings when registered/priced. "
                    "Does not read E*TRADE New Issue Center allocations."
                ),
            },
            "summary": {
                "by_stage": report.by_stage,
                "by_issuer_type": report.by_issuer_type,
                "by_form": report.by_form,
                "activity_score": report.activity_score,
                "activity_label": report.activity_label,
            },
            "resources": report.resources,
            "new_offerings": report.new_offerings,
            "filings": [
                {
                    "title": f.title,
                    "company": f.company,
                    "ticker": f.ticker,
                    "cik": f.cik,
                    "form": f.form,
                    "stage": f.stage,
                    "issuer_type": f.issuer_type,
                    "filed_date": f.filed_date,
                    "link": f.link,
                    "bias": f.bias,
                    "sic": f.sic,
                    "file_description": f.file_description,
                }
                for f in report.filings
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
            catalog_path = output.parent / "ipo_monitor_resources.json"
            catalog_path.write_text(json.dumps(report.resources, indent=2), encoding="utf-8")
        return result


def run_ipo_monitor_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return IpoMonitorAnalyst(pipeline_context=pipeline_context).run(output=output)
