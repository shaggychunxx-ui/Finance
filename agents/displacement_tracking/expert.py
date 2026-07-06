"""
Displacement Tracking Expert Agent
===================================
Expert analysis of forced displacement and human mobility signals inspired by
the IOM Displacement Tracking Matrix (DTM, https://dtm.iom.int/).

DTM itself does not expose a stable, documented public REST API, so this
agent draws on IOM DTM situation reports and assessments indexed by the
ReliefWeb API (a documented, stable humanitarian data service operated by
UN OCHA) and cross-references them against a curated registry of major
displacement crises with known market-relevant exposure (origin-country
commodities, remittance corridors, refugee-hosting fiscal stress, and
humanitarian logistics).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agents.base import BaseExpert

HEADERS = {"User-Agent": "Finance-Displacement-Tracking-Expert/1.0 (shaggychunxx@gmail.com)"}
RELIEFWEB_REPORTS_URL = "https://api.reliefweb.int/v1/reports"
DTM_PORTAL_URL = "https://dtm.iom.int/"
DTM_DATA_PORTAL_URL = "https://data.dtm.iom.int/"

CRISES: dict[str, dict[str, Any]] = {
    "sudan": {
        "name": "Sudan Conflict Displacement",
        "keywords": ["sudan", "khartoum", "darfur", "rsf", "el fasher", "el fashir"],
        "weight": 1.0,
        "commodity_exposure": "Gold, gum arabic, and livestock export disruption",
        "market_tickers": ["GLD", "DBA"],
    },
    "gaza_palestine": {
        "name": "Gaza / Palestine Displacement",
        "keywords": ["gaza", "palestin", "rafah", "west bank"],
        "weight": 0.95,
        "commodity_exposure": "Regional energy and shipping-lane risk premium",
        "market_tickers": ["USO", "XLE"],
    },
    "drc_great_lakes": {
        "name": "DR Congo / Great Lakes Displacement",
        "keywords": ["congo", "drc", "goma", "kivu", "m23"],
        "weight": 0.9,
        "commodity_exposure": "Cobalt, copper, and coltan supply-chain risk",
        "market_tickers": ["COPX", "LIT"],
    },
    "ukraine": {
        "name": "Ukraine Displacement",
        "keywords": ["ukraine", "kyiv", "kharkiv", "donbas", "kherson"],
        "weight": 0.9,
        "commodity_exposure": "Wheat, corn, and sunflower oil export disruption",
        "market_tickers": ["WEAT", "CORN", "DBA"],
    },
    "sahel": {
        "name": "Sahel Displacement (Mali / Burkina Faso / Niger)",
        "keywords": ["sahel", "mali", "burkina faso", "niger", "lake chad"],
        "weight": 0.75,
        "commodity_exposure": "Gold mining and uranium supply risk",
        "market_tickers": ["GLD", "URA"],
    },
    "afghanistan": {
        "name": "Afghanistan Displacement",
        "keywords": ["afghanistan", "kabul", "herat", "afghan return"],
        "weight": 0.7,
        "commodity_exposure": "Regional remittance and border-trade stress",
        "market_tickers": ["EEM"],
    },
    "myanmar": {
        "name": "Myanmar Displacement",
        "keywords": ["myanmar", "rakhine", "rohingya"],
        "weight": 0.7,
        "commodity_exposure": "Rice and garment supply-chain risk",
        "market_tickers": ["DBA"],
    },
    "horn_of_africa": {
        "name": "Horn of Africa Drought & Conflict Displacement",
        "keywords": ["somalia", "ethiopia", "tigray", "horn of africa", "drought"],
        "weight": 0.75,
        "commodity_exposure": "Coffee and livestock export disruption",
        "market_tickers": ["JO", "DBA"],
    },
    "venezuela": {
        "name": "Venezuela Displacement",
        "keywords": ["venezuela", "venezuelan migrant", "darien gap", "caracas"],
        "weight": 0.7,
        "commodity_exposure": "Oil export and regional remittance flows",
        "market_tickers": ["USO"],
    },
    "haiti": {
        "name": "Haiti Displacement",
        "keywords": ["haiti", "port-au-prince", "haitian gang"],
        "weight": 0.6,
        "commodity_exposure": "Regional remittance dependency",
        "market_tickers": ["EEM"],
    },
}

REMITTANCE_TICKERS = ["WU", "EEM", "CEW"]
HUMANITARIAN_LOGISTICS_TICKERS = ["FDX", "UPS", "CHRW"]
CATASTROPHE_INSURANCE_TICKERS = ["RNR", "EG", "ACGL"]
SOVEREIGN_STRESS_TICKERS = ["EMB", "EMLC"]


@dataclass
class DisplacementReport:
    title: str
    source: str
    countries: list[str] = field(default_factory=list)
    published: str = ""
    link: str = ""
    crises: list[str] = field(default_factory=list)
    severity_score: float = 0.0


@dataclass
class CrisisRisk:
    crisis_id: str
    crisis_name: str
    report_count: int
    severity_score: float
    risk_score: float
    risk_label: str
    commodity_exposure: str
    market_tickers: list[str]
    top_reports: list[str] = field(default_factory=list)


@dataclass
class DisplacementAssessment:
    dominant_crisis: str
    displacement_trend: str
    commodity_disruption_signal: str
    remittance_stress_signal: str
    humanitarian_logistics_signal: str
    catastrophe_insurance_signal: str


@dataclass
class DisplacementTrackingReport:
    reports: list[DisplacementReport]
    crises: list[CrisisRisk]
    assessment: DisplacementAssessment
    global_displacement_score: float
    risk_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DisplacementTrackingExpert(BaseExpert):
    """Expert displacement/migration analyst modeled on IOM's DTM (dtm.iom.int)."""

    def __init__(self, use_reliefweb: bool = True) -> None:
        super().__init__()
        self.use_reliefweb = use_reliefweb

    def _fetch_reports(self) -> tuple[list[DisplacementReport], list[str]]:
        reports: list[DisplacementReport] = []
        sources: list[str] = []

        if self.use_reliefweb:
            try:
                resp = requests.post(
                    RELIEFWEB_REPORTS_URL,
                    json={
                        "appname": "finance-displacement-tracking-expert",
                        "query": {
                            "value": "DTM displacement",
                            "operator": "AND",
                        },
                        "filter": {
                            "field": "source.shortname",
                            "value": "IOM",
                        },
                        "sort": ["date:desc"],
                        "limit": 40,
                        "fields": {"include": ["title", "date.created", "country.name", "source.name", "url_alias"]},
                    },
                    headers=HEADERS,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("data", []):
                    fields = item.get("fields", {})
                    title = str(fields.get("title", "")).strip()
                    if not title:
                        continue
                    countries = [c.get("name", "") for c in fields.get("country", []) if c.get("name")]
                    src = [s.get("name", "") for s in fields.get("source", []) if s.get("name")]
                    reports.append(
                        DisplacementReport(
                            title=title,
                            source=", ".join(src) or "IOM DTM",
                            countries=countries,
                            published=str(fields.get("date", {}).get("created", "")),
                            link=str(fields.get("url_alias", "")),
                        )
                    )
                if reports:
                    sources.append("ReliefWeb API (IOM DTM reports)")
            except Exception:
                pass

        if not reports:
            reports = self._proxy_reports()
            sources.append("Calibrated DTM crisis proxy (ReliefWeb API unavailable)")

        return reports, sources

    @staticmethod
    def _proxy_reports() -> list[DisplacementReport]:
        proxy = [
            ("Sudan: Over 12 million people displaced amid ongoing conflict", ["Sudan"]),
            ("Gaza Strip displacement tracking update", ["occupied Palestinian territory"]),
            ("DR Congo: New displacement waves reported in North Kivu", ["Democratic Republic of the Congo"]),
            ("Ukraine internal displacement report", ["Ukraine"]),
            ("Sahel crisis displacement overview: Mali, Burkina Faso, Niger", ["Mali", "Burkina Faso", "Niger"]),
            ("Afghanistan: Returnee and displacement monitoring update", ["Afghanistan"]),
            ("Myanmar displacement tracking matrix update", ["Myanmar"]),
            ("Horn of Africa: Drought-driven displacement assessment", ["Somalia", "Ethiopia"]),
            ("Venezuela regional migration flows monitoring report", ["Venezuela"]),
            ("Haiti: Internal displacement update amid gang violence", ["Haiti"]),
        ]
        return [
            DisplacementReport(title=t, source="IOM DTM (proxy)", countries=c, published="", link="")
            for t, c in proxy
        ]

    @staticmethod
    def _severity_score(text: str) -> float:
        lower = text.lower()
        escalation_words = {
            "displaced", "conflict", "attack", "violence", "flee", "fled",
            "crisis", "emergency", "drought", "flood", "return",
        }
        hits = sum(1 for w in escalation_words if w in lower)
        return round(max(0.0, min(1.0, 0.3 + hits * 0.12)), 4)

    def _classify(self, r: DisplacementReport) -> DisplacementReport:
        lower = (r.title + " " + " ".join(r.countries)).lower()
        matched = [cid for cid, cfg in CRISES.items() if any(kw in lower for kw in cfg["keywords"])]
        r.crises = matched
        r.severity_score = self._severity_score(r.title)
        return r

    def _score_crises(self, reports: list[DisplacementReport]) -> list[CrisisRisk]:
        by_crisis: dict[str, list[DisplacementReport]] = {cid: [] for cid in CRISES}
        for r in reports:
            for cid in r.crises:
                by_crisis[cid].append(r)

        risks: list[CrisisRisk] = []
        for cid, cfg in CRISES.items():
            arts = by_crisis[cid]
            count = len(arts)
            severity = sum(a.severity_score for a in arts) / count if count else 0.0
            volume_score = min(1.0, count / 4.0)
            risk = round(min(1.0, volume_score * 0.5 + severity * 0.5) * cfg["weight"], 4)
            label = (
                "Critical" if risk >= 0.7 else
                "Elevated" if risk >= 0.5 else
                "Moderate" if risk >= 0.3 else
                "Low"
            )
            risks.append(
                CrisisRisk(
                    crisis_id=cid,
                    crisis_name=cfg["name"],
                    report_count=count,
                    severity_score=round(severity, 4),
                    risk_score=risk,
                    risk_label=label,
                    commodity_exposure=cfg["commodity_exposure"],
                    market_tickers=cfg["market_tickers"],
                    top_reports=[a.title for a in arts[:3]],
                )
            )
        return sorted(risks, key=lambda c: c.risk_score, reverse=True)

    @staticmethod
    def _global_score(crises: list[CrisisRisk], reports: list[DisplacementReport]) -> float:
        if not crises:
            return 0.3
        top = [c.risk_score for c in crises[:3]]
        avg_top = sum(top) / len(top)
        avg_sev = sum(r.severity_score for r in reports) / max(len(reports), 1)
        return round(min(1.0, avg_top * 0.65 + avg_sev * 0.35), 4)

    def _assessment(
        self, crises: list[CrisisRisk], global_score: float
    ) -> DisplacementAssessment:
        active = [c for c in crises if c.report_count > 0]
        dominant = active[0] if active else (crises[0] if crises else None)
        dominant_name = dominant.crisis_name if dominant else "No active crisis"

        trend = (
            "escalating — multiple active displacement crises reporting high severity"
            if global_score >= 0.6 else
            "elevated — sustained displacement pressure across several crises"
            if global_score >= 0.4 else
            "contained — limited new displacement signals"
        )

        commodity_hits = [c for c in active if c.risk_score >= 0.4]
        commodity_signal = (
            "active — " + "; ".join(f"{c.crisis_name}: {c.commodity_exposure}" for c in commodity_hits[:2])
            if commodity_hits else
            "muted — no acute origin-country commodity disruption"
        )

        remittance_signal = (
            "elevated — EM remittance-dependent economies (Venezuela, Haiti, Afghanistan) under strain"
            if any(c.crisis_id in {"venezuela", "haiti", "afghanistan"} and c.risk_score >= 0.35 for c in crises)
            else "stable — no acute remittance-corridor stress"
        )

        logistics_signal = (
            f"strained — {dominant_name} driving humanitarian airlift/freight demand"
            if global_score >= 0.5 else
            "normal — baseline humanitarian logistics demand"
        )

        insurance_signal = (
            "elevated — disaster-driven displacement (drought/flood) raising catastrophe-bond exposure"
            if any(c.crisis_id in {"horn_of_africa", "sahel"} and c.risk_score >= 0.35 for c in crises)
            else "baseline — no acute catastrophe-insurance trigger"
        )

        return DisplacementAssessment(
            dominant_crisis=dominant_name,
            displacement_trend=trend,
            commodity_disruption_signal=commodity_signal,
            remittance_stress_signal=remittance_signal,
            humanitarian_logistics_signal=logistics_signal,
            catastrophe_insurance_signal=insurance_signal,
        )

    def _expert_summary(
        self, assessment: DisplacementAssessment, global_score: float, label: str, report_count: int
    ) -> str:
        return (
            f"Global displacement pressure is {label.lower()} (score {global_score:.2f}) "
            f"based on {report_count} IOM DTM-linked reports. "
            f"Dominant crisis: {assessment.dominant_crisis}. "
            f"Trend: {assessment.displacement_trend}. "
            f"Commodity disruption: {assessment.commodity_disruption_signal}. "
            f"Remittance stress: {assessment.remittance_stress_signal}. "
            f"Humanitarian logistics: {assessment.humanitarian_logistics_signal}. "
            f"Catastrophe insurance: {assessment.catastrophe_insurance_signal}."
        )

    @staticmethod
    def _market_signals(
        crises: list[CrisisRisk], assessment: DisplacementAssessment, global_score: float
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        for c in crises:
            if c.risk_score >= 0.4:
                signals.append(
                    {
                        "sector": f"Commodity Exposure — {c.crisis_name}",
                        "tickers": c.market_tickers,
                        "bias": "BULLISH" if c.risk_score >= 0.6 else "NEUTRAL",
                        "reason": f"{c.commodity_exposure} (risk {c.risk_score:.2f})",
                    }
                )

        if global_score >= 0.35:
            signals.append(
                {
                    "sector": "Remittance / Money Transfer",
                    "tickers": REMITTANCE_TICKERS,
                    "bias": "NEUTRAL" if global_score < 0.55 else "BEARISH",
                    "reason": assessment.remittance_stress_signal,
                }
            )
            signals.append(
                {
                    "sector": "Humanitarian Logistics & Freight",
                    "tickers": HUMANITARIAN_LOGISTICS_TICKERS,
                    "bias": "BULLISH" if global_score >= 0.55 else "NEUTRAL",
                    "reason": assessment.humanitarian_logistics_signal,
                }
            )
            signals.append(
                {
                    "sector": "Catastrophe Reinsurance",
                    "tickers": CATASTROPHE_INSURANCE_TICKERS,
                    "bias": "BULLISH" if global_score >= 0.55 else "NEUTRAL",
                    "reason": assessment.catastrophe_insurance_signal,
                }
            )
            signals.append(
                {
                    "sector": "EM Sovereign Debt (Refugee-Hosting Fiscal Stress)",
                    "tickers": SOVEREIGN_STRESS_TICKERS,
                    "bias": "BEARISH" if global_score >= 0.6 else "NEUTRAL",
                    "reason": f"Global displacement score {global_score:.2f} — hosting-country fiscal burden",
                }
            )

        if not signals:
            signals.append(
                {
                    "sector": "Global Displacement",
                    "tickers": ["EEM"],
                    "bias": "NEUTRAL",
                    "reason": "No acute displacement-driven market stress detected",
                }
            )
        return signals

    @staticmethod
    def _recommendations(
        crises: list[CrisisRisk], assessment: DisplacementAssessment, global_score: float
    ) -> list[str]:
        recs = [
            f"Global displacement score {global_score:.2f} — dominant crisis: {assessment.dominant_crisis}",
            f"Trend: {assessment.displacement_trend}",
            f"Commodity disruption: {assessment.commodity_disruption_signal}",
            f"Remittance stress: {assessment.remittance_stress_signal}",
            f"Humanitarian logistics: {assessment.humanitarian_logistics_signal}",
            f"Catastrophe insurance: {assessment.catastrophe_insurance_signal}",
        ]
        for c in [c for c in crises if c.report_count > 0][:4]:
            reports = "; ".join(c.top_reports[:2]) if c.top_reports else "none"
            recs.append(f"{c.crisis_name}: risk {c.risk_score:.2f} ({c.report_count} reports) — {reports}")
        if global_score >= 0.6:
            recs.append(
                "Elevated global displacement pressure — monitor EM currency/sovereign risk and "
                "humanitarian logistics demand"
            )
        return recs

    def analyze(self) -> DisplacementTrackingReport:
        raw_reports, sources = self._fetch_reports()
        reports = [self._classify(r) for r in raw_reports]
        crises = self._score_crises(reports)
        global_score = self._global_score(crises, reports)
        assessment = self._assessment(crises, global_score)

        label = (
            "Critical" if global_score >= 0.7 else
            "Elevated" if global_score >= 0.5 else
            "Moderate" if global_score >= 0.3 else
            "Low"
        )

        summary = self._expert_summary(assessment, global_score, label, len(reports))
        signals = self._market_signals(crises, assessment, global_score)
        recs = self._recommendations(crises, assessment, global_score)

        return DisplacementTrackingReport(
            reports=reports,
            crises=crises,
            assessment=assessment,
            global_displacement_score=global_score,
            risk_label=label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_sources=sources,
        )

    def to_dict(self, report: DisplacementTrackingReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Displacement Tracking Expert (IOM DTM)",
                "analyzed_at": report.analyzed_at,
                "expert_summary": report.expert_summary,
                "reports_analyzed": len(report.reports),
                "data_sources": report.data_sources,
                "temperature": self.temperature,
                "reference_portals": [DTM_PORTAL_URL, DTM_DATA_PORTAL_URL],
            },
            "assessment": {
                "dominant_crisis": a.dominant_crisis,
                "displacement_trend": a.displacement_trend,
                "commodity_disruption_signal": a.commodity_disruption_signal,
                "remittance_stress_signal": a.remittance_stress_signal,
                "humanitarian_logistics_signal": a.humanitarian_logistics_signal,
                "catastrophe_insurance_signal": a.catastrophe_insurance_signal,
            },
            "crises": [
                {
                    "id": c.crisis_id,
                    "name": c.crisis_name,
                    "report_count": c.report_count,
                    "severity_score": c.severity_score,
                    "risk_score": c.risk_score,
                    "risk_label": c.risk_label,
                    "commodity_exposure": c.commodity_exposure,
                    "market_tickers": c.market_tickers,
                    "top_reports": c.top_reports,
                }
                for c in report.crises
            ],
            "reports": [
                {
                    "title": r.title,
                    "source": r.source,
                    "countries": r.countries,
                    "crises": r.crises,
                    "severity_score": r.severity_score,
                    "link": r.link,
                }
                for r in report.reports[:20]
            ],
            "metrics": {
                "global_displacement_score": report.global_displacement_score,
                "risk_label": report.risk_label,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog_path = output.parent / "dtm_crisis_registry.json"
            catalog_path.write_text(
                json.dumps(
                    [{"id": cid, **cfg} for cid, cfg in CRISES.items()],
                    indent=2,
                ),
                encoding="utf-8",
            )
        return result


def run_displacement_tracking_analysis(output: Path | None = None) -> dict[str, Any]:
    return DisplacementTrackingExpert().run(output=output)
