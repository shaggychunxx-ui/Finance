"""
Data Steward Expert Agent
=========================
Expert data stewardship and management for the Finance intelligence platform:
data catalog, lineage, quality assessment, freshness checks, schema validation,
and endpoint health monitoring.

Scope: all agents, output artifacts, and configured data sources.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agents.base import BaseExpert

HEADERS = {"User-Agent": "Finance-Data-Steward/1.0 (shaggychunxx@gmail.com)"}
FRESHNESS_HOURS = 48
STALE_HOURS = 168

AGENT_REGISTRY: list[dict[str, Any]] = [
    {
        "command": "electricity",
        "agent": "EIA Grid Monitor Analyst",
        "primary_output": "electricity.json",
        "sidecars": ["eia_grid_monitor_views.json"],
        "sources": ["EIA Grid Monitor API", "EIA Open Data v2"],
        "owner": "platform",
    },
    {
        "command": "grid",
        "agent": "Electrical Grid Analyst",
        "primary_output": "grid.json",
        "sidecars": ["grid_markets.json"],
        "sources": ["Grid Status.io", "ERCOT", "CAISO", "EIA RTO"],
        "owner": "platform",
    },
    {
        "command": "transportation",
        "agent": "Civil Transportation Analyst",
        "primary_output": "transportation.json",
        "sidecars": ["dot_resources.json"],
        "sources": ["data.transportation.gov"],
        "owner": "platform",
    },
    {
        "command": "patents",
        "agent": "Patent Landscape Analyst",
        "primary_output": "patents.json",
        "sidecars": ["patent_resources.json"],
        "sources": ["OpenAlex", "IPWatchdog RSS", "USPTO feeds"],
        "owner": "platform",
    },
    {
        "command": "events",
        "agent": "World Events Tracker",
        "primary_output": "world_events.json",
        "sidecars": ["world_events_tracker.json"],
        "sources": ["BBC World RSS", "NPR RSS"],
        "owner": "platform",
    },
    {
        "command": "datascience",
        "agent": "Data Science Expert",
        "primary_output": "datascience.json",
        "sidecars": [],
        "sources": ["Yahoo Finance Chart API"],
        "owner": "platform",
    },
    {
        "command": "finance",
        "agent": "Google Finance Beta Analyst",
        "primary_output": "finance.json",
        "sidecars": ["google_finance_views.json"],
        "sources": ["Google Finance Beta", "Yahoo Finance API"],
        "owner": "platform",
    },
    {
        "command": "financial-data",
        "agent": "Yahoo Finance Statistical Analyst",
        "primary_output": "financial_data.json",
        "sidecars": ["yahoo_finance_views.json"],
        "sources": ["Yahoo Finance API"],
        "owner": "platform",
    },
    {
        "command": "markets",
        "agent": "Market Analyst Expert",
        "primary_output": "markets.json",
        "sidecars": [],
        "sources": ["Yahoo Finance API"],
        "owner": "platform",
    },
    {
        "command": "ftse100",
        "agent": "FTSE 100 Index Analyst",
        "primary_output": "ftse100.json",
        "sidecars": [],
        "sources": ["Yahoo Finance API (^FTSE + LSE constituents)"],
        "owner": "platform",
    },
    {
        "command": "geopolitics",
        "agent": "Geopolitics Expert",
        "primary_output": "geopolitics.json",
        "sidecars": [],
        "sources": ["BBC World RSS", "NPR RSS"],
        "owner": "platform",
    },
    {
        "command": "logistics",
        "agent": "Logistics Expert",
        "primary_output": "logistics.json",
        "sidecars": ["marine_traffic_corridors.json"],
        "sources": ["MarineTraffic AIS"],
        "owner": "platform",
    },
    {
        "command": "meteorology",
        "agent": "Meteorology Expert",
        "primary_output": "meteorology.json",
        "sidecars": [],
        "sources": ["weather.gov NWS API"],
        "owner": "platform",
    },
    {
        "command": "theoretical-probability",
        "agent": "Theoretical Probability Expert",
        "primary_output": "theoretical_probability.json",
        "sidecars": ["probability_models.json"],
        "sources": ["Yahoo Finance Chart API"],
        "owner": "platform",
    },
    {
        "command": "empirical-probability",
        "agent": "Empirical Probability Expert",
        "primary_output": "empirical_probability.json",
        "sidecars": ["empirical_experiments.json"],
        "sources": ["Yahoo Finance Chart API"],
        "owner": "platform",
    },
    {
        "command": "combined-conditional",
        "agent": "Combined & Conditional Probability Expert",
        "primary_output": "combined_conditional.json",
        "sidecars": ["probability_concepts.json"],
        "sources": ["Yahoo Finance Chart API"],
        "owner": "platform",
    },
    {
        "command": "research-statistics",
        "agent": "Research Statistics Expert",
        "primary_output": "research_statistics.json",
        "sidecars": ["statistical_methods.json"],
        "sources": ["Yahoo Finance Chart API"],
        "owner": "platform",
    },
    {
        "command": "sales-analytics",
        "agent": "Sales Analytics BI Expert",
        "primary_output": "sales_analytics.json",
        "sidecars": ["sales_dashboard_data.json", "sales_dashboard_panels.json"],
        "sources": ["Yahoo Finance Chart API"],
        "owner": "platform",
    },
    {
        "command": "order-execution",
        "agent": "Order Execution & Market Microstructure Expert",
        "primary_output": "order_execution.json",
        "sidecars": ["order_type_playbook.json"],
        "sources": ["Yahoo Finance Chart API"],
        "owner": "platform",
    },
]

DATA_SOURCES: list[dict[str, Any]] = [
    {
        "id": "yahoo_finance",
        "name": "Yahoo Finance Chart API",
        "type": "market_data",
        "url": "https://query1.finance.yahoo.com/v8/finance/chart/^GSPC",
        "format": "json",
        "refresh_policy": "daily",
        "pii": False,
        "sla_hours": 24,
    },
    {
        "id": "eia_api",
        "name": "EIA Open Data API",
        "type": "energy",
        "url": "https://api.eia.gov/v2/electricity/rto/region-data/data/",
        "format": "json",
        "refresh_policy": "hourly",
        "pii": False,
        "sla_hours": 4,
        "config_key": "eia_api_key",
    },
    {
        "id": "gridstatus",
        "name": "Grid Status API",
        "type": "energy",
        "url": "https://api.gridstatus.io/v1/",
        "format": "json",
        "refresh_policy": "realtime",
        "pii": False,
        "sla_hours": 1,
        "config_key": "gridstatus_api_key",
    },
    {
        "id": "dot_open_data",
        "name": "DOT Open Data",
        "type": "transportation",
        "url": "https://data.transportation.gov/",
        "format": "csv/json",
        "refresh_policy": "weekly",
        "pii": False,
        "sla_hours": 168,
    },
    {
        "id": "openalex",
        "name": "OpenAlex Works API",
        "type": "patents",
        "url": "https://api.openalex.org/works?per_page=1",
        "format": "json",
        "refresh_policy": "daily",
        "pii": False,
        "sla_hours": 24,
    },
    {
        "id": "bbc_rss",
        "name": "BBC World RSS",
        "type": "news",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "format": "rss",
        "refresh_policy": "hourly",
        "pii": False,
        "sla_hours": 6,
    },
    {
        "id": "nws_api",
        "name": "NWS Weather API",
        "type": "weather",
        "url": "https://api.weather.gov/alerts/active?area=US",
        "format": "json",
        "refresh_policy": "realtime",
        "pii": False,
        "sla_hours": 2,
    },
    {
        "id": "marinetraffic",
        "name": "MarineTraffic AIS",
        "type": "logistics",
        "url": "https://www.marinetraffic.com/",
        "format": "api",
        "refresh_policy": "realtime",
        "pii": False,
        "sla_hours": 1,
        "config_key": "marinetraffic_api_key",
    },
]

REQUIRED_REPORT_KEYS = ("meta", "market_signals", "recommendations")
REQUIRED_META_KEYS = ("agent", "analyzed_at", "data_source", "expert_summary")

HEALTH_CHECKS: list[dict[str, str]] = [
    {"source_id": "yahoo_finance", "method": "GET"},
    {"source_id": "openalex", "method": "GET"},
    {"source_id": "bbc_rss", "method": "GET"},
    {"source_id": "nws_api", "method": "GET", "headers": {"User-Agent": "(Finance-Steward, contact@example.com)"}},
]

SIDECAR_FILENAMES: frozenset[str] = frozenset(
    sidecar
    for entry in AGENT_REGISTRY
    for sidecar in entry.get("sidecars", [])
)


@dataclass
class SourceHealth:
    source_id: str
    name: str
    status: str
    latency_ms: int | None
    http_code: int | None
    message: str


@dataclass
class ArtifactQuality:
    filename: str
    agent_command: str | None
    artifact_role: str
    exists: bool
    valid_json: bool
    schema_valid: bool
    freshness_hours: float | None
    freshness_label: str
    completeness_score: float
    issues: list[str]


@dataclass
class StewardshipIssue:
    severity: str
    category: str
    message: str
    remediation: str


@dataclass
class StewardAssessment:
    catalog_coverage: str
    data_quality: str
    freshness_status: str
    lineage_status: str
    governance_signal: str
    stewardship_priority: str


@dataclass
class DataStewardReport:
    source_health: list[SourceHealth]
    artifact_quality: list[ArtifactQuality]
    lineage: list[dict[str, Any]]
    issues: list[StewardshipIssue]
    assessment: StewardAssessment
    stewardship_score: float
    quality_score: float
    freshness_score: float
    regime_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DataStewardExpert(BaseExpert):
    """Expert data steward — catalog, lineage, quality, and governance."""

    def __init__(
        self,
        output_dir: Path | None = None,
        config_path: Path | None = None,
        *,
        pipeline_context: dict | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="data-steward")
        self.output_dir = output_dir or Path("output")
        self.config_path = config_path or Path("config.json")

    def _load_config(self) -> dict[str, Any]:
        if self.config_path.exists():
            try:
                return json.loads(self.config_path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _health_check(self, source: dict[str, Any], extra_headers: dict[str, str] | None = None) -> SourceHealth:
        url = source["url"]
        headers = dict(HEADERS)
        if extra_headers:
            headers.update(extra_headers)
        start = time.perf_counter()
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            latency = int((time.perf_counter() - start) * 1000)
            if resp.status_code < 400:
                status = "online"
                msg = f"HTTP {resp.status_code} in {latency}ms"
            elif resp.status_code == 401:
                status = "auth_required"
                msg = f"HTTP 401 — API key may be required"
            elif resp.status_code == 403:
                status = "restricted"
                msg = f"HTTP 403 — access restricted or rate-limited"
            else:
                status = "degraded"
                msg = f"HTTP {resp.status_code}"
            return SourceHealth(
                source_id=source["id"],
                name=source["name"],
                status=status,
                latency_ms=latency,
                http_code=resp.status_code,
                message=msg,
            )
        except Exception as exc:
            return SourceHealth(
                source_id=source["id"],
                name=source["name"],
                status="offline",
                latency_ms=None,
                http_code=None,
                message=str(exc)[:120],
            )

    def _parse_timestamp(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            ts = value.replace("Z", "+00:00")
            return datetime.fromisoformat(ts)
        except Exception:
            return None

    def _freshness_label(self, hours: float | None) -> str:
        if hours is None:
            return "unknown"
        if hours <= FRESHNESS_HOURS:
            return "fresh"
        if hours <= STALE_HOURS:
            return "aging"
        return "stale"

    def _artifact_role(self, filename: str, agent_command: str | None) -> str:
        if filename in SIDECAR_FILENAMES:
            return "sidecar"
        if agent_command and filename in {e["primary_output"] for e in AGENT_REGISTRY}:
            return "primary"
        return "supplemental"

    def _validate_sidecar(self, data: Any) -> tuple[bool, float, list[str]]:
        issues: list[str] = []
        if isinstance(data, list):
            if data:
                return True, 0.9, issues
            issues.append("empty sidecar list")
            return False, 0.25, issues
        if isinstance(data, dict) and data:
            return True, 0.9, issues
        issues.append("empty or unsupported sidecar structure")
        return False, 0.25, issues

    def _validate_artifact(
        self, path: Path, agent_command: str | None
    ) -> ArtifactQuality:
        role = self._artifact_role(path.name, agent_command)
        issues: list[str] = []
        exists = path.exists()
        valid_json = False
        schema_valid = False
        freshness_hours: float | None = None
        completeness = 0.0

        if not exists:
            issues.append("file missing")
            return ArtifactQuality(
                filename=path.name,
                agent_command=agent_command,
                artifact_role=role,
                exists=False,
                valid_json=False,
                schema_valid=False,
                freshness_hours=None,
                freshness_label="missing",
                completeness_score=0.0,
                issues=issues,
            )

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            valid_json = True
        except Exception:
            issues.append("invalid JSON")
            return ArtifactQuality(
                filename=path.name,
                agent_command=agent_command,
                artifact_role=role,
                exists=True,
                valid_json=False,
                schema_valid=False,
                freshness_hours=None,
                freshness_label="invalid",
                completeness_score=0.0,
                issues=issues,
            )

        if role == "sidecar":
            schema_valid, completeness, sidecar_issues = self._validate_sidecar(data)
            issues.extend(sidecar_issues)
            return ArtifactQuality(
                filename=path.name,
                agent_command=agent_command,
                artifact_role=role,
                exists=True,
                valid_json=True,
                schema_valid=schema_valid,
                freshness_hours=None,
                freshness_label="reference",
                completeness_score=completeness,
                issues=issues,
            )

        score_parts = [0.25]
        if isinstance(data, dict):
            if all(k in data for k in REQUIRED_REPORT_KEYS):
                score_parts.append(0.35)
                schema_valid = True
            else:
                missing = [k for k in REQUIRED_REPORT_KEYS if k not in data]
                issues.append(f"missing keys: {', '.join(missing)}")
            meta = data.get("meta", {})
            if isinstance(meta, dict):
                meta_present = sum(1 for k in REQUIRED_META_KEYS if k in meta and meta[k])
                score_parts.append(0.25 * (meta_present / len(REQUIRED_META_KEYS)))
                if meta_present < len(REQUIRED_META_KEYS):
                    issues.append("incomplete meta block")
                analyzed = meta.get("analyzed_at")
                ts = self._parse_timestamp(analyzed)
                if ts:
                    freshness_hours = round(
                        (datetime.now(timezone.utc) - ts).total_seconds() / 3600, 1
                    )
                else:
                    issues.append("missing analyzed_at timestamp")
            if data.get("market_signals"):
                score_parts.append(0.15)
            if data.get("recommendations"):
                score_parts.append(0.1)

        completeness = round(min(1.0, sum(score_parts)), 4)
        if completeness >= 0.8 and not issues:
            schema_valid = True

        return ArtifactQuality(
            filename=path.name,
            agent_command=agent_command,
            artifact_role=role,
            exists=True,
            valid_json=True,
            schema_valid=schema_valid,
            freshness_hours=freshness_hours,
            freshness_label=self._freshness_label(freshness_hours),
            completeness_score=completeness,
            issues=issues,
        )

    def _lineage(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for entry in AGENT_REGISTRY:
            primary = self.output_dir / entry["primary_output"]
            rows.append({
                "command": entry["command"],
                "agent": entry["agent"],
                "sources": entry["sources"],
                "primary_output": entry["primary_output"],
                "sidecars": entry["sidecars"],
                "owner": entry["owner"],
                "primary_exists": primary.exists(),
            })
        return rows

    def _collect_issues(
        self,
        health: list[SourceHealth],
        artifacts: list[ArtifactQuality],
        config: dict[str, Any],
    ) -> list[StewardshipIssue]:
        issues: list[StewardshipIssue] = []

        for h in health:
            if h.status == "offline":
                issues.append(StewardshipIssue(
                    severity="high",
                    category="availability",
                    message=f"{h.name} is offline — {h.message}",
                    remediation=f"Verify network access and endpoint URL for {h.source_id}",
                ))
            elif h.status in ("auth_required", "restricted"):
                issues.append(StewardshipIssue(
                    severity="medium",
                    category="access",
                    message=f"{h.name}: {h.message}",
                    remediation="Configure API key in config.json if required",
                ))

        missing_primary = [
            a for a in artifacts
            if a.agent_command and not a.exists and a.filename.endswith(".json")
            and a.filename in [e["primary_output"] for e in AGENT_REGISTRY]
        ]
        for a in missing_primary[:5]:
            issues.append(StewardshipIssue(
                severity="medium",
                category="completeness",
                message=f"Primary output missing: {a.filename} ({a.agent_command})",
                remediation=f"Run: run.bat {a.agent_command} -o output/{a.filename}",
            ))

        stale = [a for a in artifacts if a.freshness_label == "stale"]
        for a in stale[:4]:
            issues.append(StewardshipIssue(
                severity="medium",
                category="timeliness",
                message=f"{a.filename} is stale ({a.freshness_hours:.0f}h old)",
                remediation=f"Refresh by re-running agent {a.agent_command or 'unknown'}",
            ))

        invalid = [
            a for a in artifacts
            if a.exists and a.artifact_role == "primary" and not a.schema_valid
        ]
        for a in invalid[:4]:
            detail = "; ".join(a.issues) or "missing required report fields"
            issues.append(StewardshipIssue(
                severity="low",
                category="validity",
                message=f"{a.filename} schema incomplete: {detail}",
                remediation="Re-generate report; ensure meta, signals, and recommendations present",
            ))

        if not self.config_path.exists():
            issues.append(StewardshipIssue(
                severity="low",
                category="governance",
                message="config.json not found — using defaults and proxy fallbacks",
                remediation="Copy config.example.json to config.json for production keys",
            ))
        else:
            unset_keys: list[str] = []
            for src in DATA_SOURCES:
                key = src.get("config_key")
                if not key or key in config:
                    continue
                agent_needs = any(
                    src["name"].split()[0] in " ".join(e["sources"])
                    for e in AGENT_REGISTRY
                )
                if agent_needs:
                    unset_keys.append(key)
            if unset_keys:
                issues.append(StewardshipIssue(
                    severity="low",
                    category="governance",
                    message=(
                        "Optional API keys not defined in config.json: "
                        + ", ".join(unset_keys)
                    ),
                    remediation="Add keys to config.json when live API access is required",
                ))

        return issues

    def _assessment(
        self,
        health: list[SourceHealth],
        artifacts: list[ArtifactQuality],
        lineage: list[dict[str, Any]],
        issues: list[StewardshipIssue],
    ) -> StewardAssessment:
        online = sum(1 for h in health if h.status == "online")
        catalog_cov = f"{len(DATA_SOURCES)} sources cataloged, {online}/{len(health)} health checks online"

        primary_arts = [a for a in artifacts if a.agent_command]
        if primary_arts:
            avg_comp = sum(a.completeness_score for a in primary_arts) / len(primary_arts)
            qual = f"avg completeness {avg_comp:.0%} across {len(primary_arts)} primary artifacts"
        else:
            qual = "no primary artifacts found in output/"

        fresh = sum(1 for a in artifacts if a.freshness_label == "fresh")
        known_fresh = [a for a in artifacts if a.freshness_hours is not None]
        if known_fresh:
            fresh_pct = fresh / len(known_fresh) * 100
            fresh_status = f"{fresh}/{len(known_fresh)} artifacts fresh (<{FRESHNESS_HOURS}h)"
        else:
            fresh_status = "freshness unknown — no timestamps in output files"

        lineage_ok = sum(1 for l in lineage if l["primary_exists"])
        lineage_status = f"{lineage_ok}/{len(lineage)} agent lineage paths have primary output on disk"

        high_issues = sum(1 for i in issues if i.severity == "high")
        if high_issues:
            gov = f"{high_issues} high-severity stewardship issues require immediate attention"
        elif issues:
            gov = f"{len(issues)} stewardship issues — mostly completeness and timeliness"
        else:
            gov = "governance posture healthy — no open stewardship issues"

        if high_issues:
            priority = "remediate offline sources and missing critical outputs first"
        elif any(a.freshness_label == "stale" for a in artifacts):
            priority = "schedule agent refresh runs for stale artifacts"
        elif not self.config_path.exists():
            priority = "establish config.json for API key governance"
        else:
            priority = "maintain current refresh cadence and monitor source health"

        return StewardAssessment(
            catalog_coverage=catalog_cov,
            data_quality=qual,
            freshness_status=fresh_status,
            lineage_status=lineage_status,
            governance_signal=gov,
            stewardship_priority=priority,
        )

    def analyze(self) -> DataStewardReport:
        config = self._load_config()
        source_by_id = {s["id"]: s for s in DATA_SOURCES}

        health: list[SourceHealth] = []
        for check in HEALTH_CHECKS:
            src = source_by_id.get(check["source_id"])
            if not src:
                continue
            extra = check.get("headers")
            if isinstance(extra, dict):
                extra = {k: str(v) for k, v in extra.items()}
            health.append(self._health_check(src, extra))
            time.sleep(0.2)

        artifacts: list[ArtifactQuality] = []
        seen: set[str] = set()
        for entry in AGENT_REGISTRY:
            primary_path = self.output_dir / entry["primary_output"]
            if entry["primary_output"] not in seen:
                artifacts.append(self._validate_artifact(primary_path, entry["command"]))
                seen.add(entry["primary_output"])
            for sidecar in entry["sidecars"]:
                if sidecar not in seen:
                    artifacts.append(self._validate_artifact(
                        self.output_dir / sidecar, entry["command"]
                    ))
                    seen.add(sidecar)

        if self.output_dir.exists():
            for path in sorted(self.output_dir.glob("*.json")):
                if path.name not in seen:
                    artifacts.append(self._validate_artifact(path, None))

        lineage = self._lineage()
        issues = self._collect_issues(health, artifacts, config)
        assessment = self._assessment(health, artifacts, lineage, issues)

        primary = [a for a in artifacts if a.agent_command]
        quality_score = round(
            sum(a.completeness_score for a in primary) / max(len(primary), 1), 4
        )
        fresh_known = [a for a in artifacts if a.freshness_hours is not None]
        freshness_score = round(
            sum(1 for a in fresh_known if a.freshness_label == "fresh") / max(len(fresh_known), 1),
            4,
        ) if fresh_known else 0.5
        online_ratio = sum(1 for h in health if h.status == "online") / max(len(health), 1)
        issue_penalty = min(0.4, len(issues) * 0.04)
        stewardship_score = round(
            0.35 * quality_score + 0.30 * freshness_score + 0.25 * online_ratio - issue_penalty,
            4,
        )
        stewardship_score = max(0.0, min(1.0, stewardship_score))

        if stewardship_score >= 0.65:
            regime_label = "Well-Stewarded"
        elif stewardship_score >= 0.45:
            regime_label = "Needs Attention"
        else:
            regime_label = "At Risk"

        summary = (
            f"Data stewardship scan: {regime_label} (score {stewardship_score:.2f}). "
            f"{assessment.catalog_coverage}. "
            f"{assessment.data_quality}. "
            f"{assessment.freshness_status}. "
            f"{assessment.lineage_status}. "
            f"{assessment.governance_signal}. "
            f"Priority: {assessment.stewardship_priority}."
        )

        signals = self._market_signals(health, artifacts, issues, stewardship_score)
        recs = self._recommendations(assessment, health, artifacts, issues, lineage)

        return DataStewardReport(
            source_health=health,
            artifact_quality=artifacts,
            lineage=lineage,
            issues=issues,
            assessment=assessment,
            stewardship_score=stewardship_score,
            quality_score=quality_score,
            freshness_score=freshness_score,
            regime_label=regime_label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
        )

    @staticmethod
    def _market_signals(
        health: list[SourceHealth],
        artifacts: list[ArtifactQuality],
        issues: list[StewardshipIssue],
        score: float,
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        bias = (
            "BULLISH" if score >= 0.65 else
            "BEARISH" if score <= 0.4 else
            "NEUTRAL"
        )
        signals.append({
            "sector": "Data Platform Health",
            "tickers": ["SPY"],
            "bias": bias,
            "reason": f"Stewardship score {score:.2f} — {len(issues)} open issues",
        })

        offline = [h for h in health if h.status == "offline"]
        if offline:
            signals.append({
                "sector": "Data Availability Risk",
                "tickers": ["GLD", "TLT"],
                "bias": "BEARISH",
                "reason": f"{offline[0].name} offline — agent outputs may use fallbacks",
            })

        stale = [a for a in artifacts if a.freshness_label == "stale" and a.agent_command]
        if stale:
            signals.append({
                "sector": "Stale Intelligence",
                "tickers": ["VIXY"],
                "bias": "BEARISH",
                "reason": f"{stale[0].filename} last updated {stale[0].freshness_hours:.0f}h ago",
            })

        fresh_complete = [
            a for a in artifacts
            if a.freshness_label == "fresh" and a.completeness_score >= 0.85
        ]
        if fresh_complete:
            signals.append({
                "sector": "Quality Data Ready",
                "tickers": ["XLK", "QQQ"],
                "bias": "BULLISH",
                "reason": f"{len(fresh_complete)} artifacts fresh and schema-complete",
            })

        return signals

    @staticmethod
    def _recommendations(
        assessment: StewardAssessment,
        health: list[SourceHealth],
        artifacts: list[ArtifactQuality],
        issues: list[StewardshipIssue],
        lineage: list[dict[str, Any]],
    ) -> list[str]:
        recs = [
            assessment.catalog_coverage,
            assessment.data_quality,
            assessment.freshness_status,
            assessment.lineage_status,
            assessment.governance_signal,
            assessment.stewardship_priority,
        ]
        for h in health:
            recs.append(f"Source {h.name}: {h.status} — {h.message}")
        missing = [l for l in lineage if not l["primary_exists"]]
        for m in missing[:6]:
            recs.append(
                f"Missing output: run.bat {m['command']} -o output/{m['primary_output']}"
            )
        for a in sorted(artifacts, key=lambda x: -x.completeness_score)[:4]:
            if a.exists:
                recs.append(
                    f"{a.filename}: completeness {a.completeness_score:.0%}, "
                    f"freshness {a.freshness_label}"
                    + (f" ({a.freshness_hours:.0f}h)" if a.freshness_hours else "")
                )
        for issue in issues[:8]:
            recs.append(f"[{issue.severity.upper()}] {issue.message} → {issue.remediation}")
        return recs

    def to_dict(self, report: DataStewardReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Data Steward Expert",
                "analyzed_at": report.analyzed_at,
                "data_source": "Finance platform catalog + output/ artifacts + live health checks",
                "expert_summary": report.expert_summary,
                "agents_cataloged": len(AGENT_REGISTRY),
                "sources_cataloged": len(DATA_SOURCES),
            },
            "data_catalog": DATA_SOURCES,
            "agent_registry": AGENT_REGISTRY,
            "source_health": [
                {
                    "source_id": h.source_id,
                    "name": h.name,
                    "status": h.status,
                    "latency_ms": h.latency_ms,
                    "http_code": h.http_code,
                    "message": h.message,
                }
                for h in report.source_health
            ],
            "artifact_quality": [
                {
                    "filename": aq.filename,
                    "agent_command": aq.agent_command,
                    "artifact_role": aq.artifact_role,
                    "exists": aq.exists,
                    "valid_json": aq.valid_json,
                    "schema_valid": aq.schema_valid,
                    "freshness_hours": aq.freshness_hours,
                    "freshness_label": aq.freshness_label,
                    "completeness_score": aq.completeness_score,
                    "issues": aq.issues,
                }
                for aq in report.artifact_quality
            ],
            "data_lineage": report.lineage,
            "stewardship_issues": [
                {
                    "severity": i.severity,
                    "category": i.category,
                    "message": i.message,
                    "remediation": i.remediation,
                }
                for i in report.issues
            ],
            "stewardship_assessment": {
                "catalog_coverage": a.catalog_coverage,
                "data_quality": a.data_quality,
                "freshness_status": a.freshness_status,
                "lineage_status": a.lineage_status,
                "governance_signal": a.governance_signal,
                "stewardship_priority": a.stewardship_priority,
            },
            "metrics": {
                "stewardship_score": report.stewardship_score,
                "quality_score": report.quality_score,
                "freshness_score": report.freshness_score,
                "regime_label": report.regime_label,
                "open_issues": len(report.issues),
            },
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog_path = output.parent / "data_catalog.json"
            catalog_path.write_text(
                json.dumps(DATA_SOURCES, indent=2),
                encoding="utf-8",
            )
            lineage_path = output.parent / "data_lineage.json"
            lineage_path.write_text(
                json.dumps({
                    "agents": AGENT_REGISTRY,
                    "lineage": result["data_lineage"],
                }, indent=2),
                encoding="utf-8",
            )
        return result


def run_data_steward_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return DataStewardExpert(pipeline_context=pipeline_context).run(output=output)