"""
Data Processor Expert Agent
===========================
Expert data processing for the Finance intelligence platform:
ETL pipeline inventory, transformation workflows, batch orchestration,
format normalization checks, throughput assessment, and processing backlog.

Scope: agent pipelines, output/ artifacts, and sidecar generation flows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FRESHNESS_HOURS = 48
STALE_HOURS = 168

PIPELINE_REGISTRY: list[dict[str, Any]] = [
    {
        "pipeline_id": "electricity_etl",
        "command": "electricity",
        "agent": "EIA Grid Monitor Analyst",
        "extract": {"source": "EIA Grid Monitor API", "format": "json"},
        "transform": ["normalize_grid_metrics", "compute_disruption_scores", "map_sector_signals"],
        "load": {"primary": "electricity.json", "sidecars": ["eia_grid_monitor_views.json"]},
        "schedule": "hourly",
        "depends_on": [],
    },
    {
        "pipeline_id": "grid_etl",
        "command": "grid",
        "agent": "Electrical Grid Analyst",
        "extract": {"source": "Grid Status.io + ERCOT + CAISO", "format": "json"},
        "transform": ["merge_rto_feeds", "score_grid_stress", "build_market_catalog"],
        "load": {"primary": "grid.json", "sidecars": ["grid_markets.json"]},
        "schedule": "hourly",
        "depends_on": [],
    },
    {
        "pipeline_id": "transportation_etl",
        "command": "transportation",
        "agent": "Civil Transportation Analyst",
        "extract": {"source": "data.transportation.gov", "format": "csv/json"},
        "transform": ["aggregate_dot_datasets", "score_infrastructure_risk"],
        "load": {"primary": "transportation.json", "sidecars": ["dot_resources.json"]},
        "schedule": "daily",
        "depends_on": [],
    },
    {
        "pipeline_id": "patents_etl",
        "command": "patents",
        "agent": "Patent Landscape Analyst",
        "extract": {"source": "OpenAlex + RSS feeds", "format": "json/rss"},
        "transform": ["dedupe_patent_hits", "classify_technology_sectors"],
        "load": {"primary": "patents.json", "sidecars": ["patent_resources.json"]},
        "schedule": "daily",
        "depends_on": [],
    },
    {
        "pipeline_id": "events_etl",
        "command": "events",
        "agent": "World Events Tracker",
        "extract": {"source": "BBC World + NPR RSS", "format": "rss"},
        "transform": ["parse_headlines", "geotag_events", "build_tracker_feed"],
        "load": {"primary": "world_events.json", "sidecars": ["world_events_tracker.json"]},
        "schedule": "hourly",
        "depends_on": [],
    },
    {
        "pipeline_id": "datascience_etl",
        "command": "datascience",
        "agent": "Data Science Expert",
        "extract": {"source": "Yahoo Finance Chart API", "format": "json"},
        "transform": ["compute_returns", "rolling_stats", "feature_engineering"],
        "load": {"primary": "datascience.json", "sidecars": []},
        "schedule": "daily",
        "depends_on": [],
    },
    {
        "pipeline_id": "finance_etl",
        "command": "finance",
        "agent": "Google Finance Beta Analyst",
        "extract": {"source": "Google Finance Beta + Yahoo", "format": "json"},
        "transform": ["beta_screening", "opportunity_scoring", "build_views_catalog"],
        "load": {"primary": "finance.json", "sidecars": ["google_finance_views.json"]},
        "schedule": "daily",
        "depends_on": [],
    },
    {
        "pipeline_id": "financial_data_etl",
        "command": "financial-data",
        "agent": "Yahoo Finance Statistical Analyst",
        "extract": {"source": "Yahoo Finance API", "format": "json"},
        "transform": ["cross_sectional_stats", "correlation_matrix", "build_yahoo_views"],
        "load": {"primary": "financial_data.json", "sidecars": ["yahoo_finance_views.json"]},
        "schedule": "daily",
        "depends_on": [],
    },
    {
        "pipeline_id": "markets_etl",
        "command": "markets",
        "agent": "Market Analyst Expert",
        "extract": {"source": "Yahoo Finance API", "format": "json"},
        "transform": ["sector_rotation", "breadth_analysis", "signal_generation"],
        "load": {"primary": "markets.json", "sidecars": []},
        "schedule": "daily",
        "depends_on": ["financial_data_etl"],
    },
    {
        "pipeline_id": "geopolitics_etl",
        "command": "geopolitics",
        "agent": "Geopolitics Expert",
        "extract": {"source": "BBC World + NPR RSS", "format": "rss"},
        "transform": ["risk_scoring", "region_clustering", "sanctions_watch"],
        "load": {"primary": "geopolitics.json", "sidecars": []},
        "schedule": "hourly",
        "depends_on": ["events_etl"],
    },
    {
        "pipeline_id": "logistics_etl",
        "command": "logistics",
        "agent": "Logistics Expert",
        "extract": {"source": "MarineTraffic AIS", "format": "api"},
        "transform": ["corridor_mapping", "congestion_scoring"],
        "load": {"primary": "logistics.json", "sidecars": ["marine_traffic_corridors.json"]},
        "schedule": "hourly",
        "depends_on": [],
    },
    {
        "pipeline_id": "meteorology_etl",
        "command": "meteorology",
        "agent": "Meteorology Expert",
        "extract": {"source": "NWS Weather API", "format": "json"},
        "transform": ["alert_aggregation", "stress_indexing"],
        "load": {"primary": "meteorology.json", "sidecars": []},
        "schedule": "hourly",
        "depends_on": [],
    },
    {
        "pipeline_id": "theoretical_probability_etl",
        "command": "theoretical-probability",
        "agent": "Theoretical Probability Expert",
        "extract": {"source": "Yahoo Finance Chart API", "format": "json"},
        "transform": ["markov_chain_fit", "bayesian_update", "kelly_sizing"],
        "load": {"primary": "theoretical_probability.json", "sidecars": ["probability_models.json"]},
        "schedule": "daily",
        "depends_on": [],
    },
    {
        "pipeline_id": "empirical_probability_etl",
        "command": "empirical-probability",
        "agent": "Empirical Probability Expert",
        "extract": {"source": "Yahoo Finance Chart API", "format": "json"},
        "transform": ["frequency_tables", "wilson_ci", "bootstrap_resample"],
        "load": {"primary": "empirical_probability.json", "sidecars": ["empirical_experiments.json"]},
        "schedule": "daily",
        "depends_on": [],
    },
    {
        "pipeline_id": "combined_conditional_etl",
        "command": "combined-conditional",
        "agent": "Combined & Conditional Probability Expert",
        "extract": {"source": "Yahoo Finance Chart API", "format": "json"},
        "transform": ["joint_distributions", "conditional_probability", "union_rules"],
        "load": {"primary": "combined_conditional.json", "sidecars": ["probability_concepts.json"]},
        "schedule": "daily",
        "depends_on": ["theoretical_probability_etl", "empirical_probability_etl"],
    },
    {
        "pipeline_id": "research_statistics_etl",
        "command": "research-statistics",
        "agent": "Research Statistics Expert",
        "extract": {"source": "Yahoo Finance Chart API", "format": "json"},
        "transform": ["hypothesis_tests", "ols_regression", "normality_checks"],
        "load": {"primary": "research_statistics.json", "sidecars": ["statistical_methods.json"]},
        "schedule": "daily",
        "depends_on": [],
    },
    {
        "pipeline_id": "sales_analytics_etl",
        "command": "sales-analytics",
        "agent": "Sales Analytics BI Expert",
        "extract": {"source": "Yahoo Finance retail proxies", "format": "json"},
        "transform": ["retail_momentum", "dashboard_panel_build", "kpi_aggregation"],
        "load": {
            "primary": "sales_analytics.json",
            "sidecars": ["sales_dashboard_data.json", "sales_dashboard_panels.json"],
        },
        "schedule": "daily",
        "depends_on": ["markets_etl"],
    },
    {
        "pipeline_id": "data_steward_etl",
        "command": "data-steward",
        "agent": "Data Steward Expert",
        "extract": {"source": "output/ artifacts + live APIs", "format": "json"},
        "transform": ["catalog_build", "quality_scoring", "lineage_mapping"],
        "load": {"primary": "data_steward.json", "sidecars": ["data_catalog.json", "data_lineage.json"]},
        "schedule": "daily",
        "depends_on": [],
    },
    {
        "pipeline_id": "records_management_etl",
        "command": "records-management",
        "agent": "Records Management Expert",
        "extract": {"source": "output/ inventory", "format": "json"},
        "transform": ["checksum_inventory", "retention_scan", "snapshot_archive"],
        "load": {
            "primary": "records_management.json",
            "sidecars": ["archive_catalog.json", "retention_schedule.json"],
        },
        "schedule": "daily",
        "depends_on": ["data_steward_etl"],
    },
    {
        "pipeline_id": "database_admin_etl",
        "command": "database-admin",
        "agent": "Database Administrator Expert",
        "extract": {"source": "output/ JSON stores + APIs", "format": "json"},
        "transform": ["schema_inference", "integrity_checks", "index_recommendations"],
        "load": {"primary": "database_admin.json", "sidecars": ["database_schema.json", "database_indexes.json"]},
        "schedule": "daily",
        "depends_on": ["records_management_etl"],
    },
    {
        "pipeline_id": "data_processor_etl",
        "command": "data-processor",
        "agent": "Data Processor Expert",
        "extract": {"source": "pipeline registry + output/", "format": "json"},
        "transform": ["pipeline_status_scan", "orchestration_plan", "format_validation"],
        "load": {
            "primary": "data_processor.json",
            "sidecars": ["processing_pipelines.json", "transformation_catalog.json"],
        },
        "schedule": "daily",
        "depends_on": ["database_admin_etl"],
    },
]

TRANSFORMATION_CATALOG: list[dict[str, Any]] = [
    {
        "transform_id": "normalize_grid_metrics",
        "category": "normalization",
        "description": "Standardize EIA grid metrics to platform schema",
        "input_fields": ["demand_mw", "generation_mw", "interchange_mw"],
        "output_fields": ["metrics.disruption_score", "metrics.energy_demand_score"],
    },
    {
        "transform_id": "compute_returns",
        "category": "feature_engineering",
        "description": "Daily log returns and rolling volatility",
        "input_fields": ["close", "adjclose"],
        "output_fields": ["returns", "volatility_20d"],
    },
    {
        "transform_id": "cross_sectional_stats",
        "category": "aggregation",
        "description": "Cross-sectional mean, std, z-score across ticker universe",
        "input_fields": ["symbol", "close", "volume"],
        "output_fields": ["stats.mean_return", "stats.std_return", "stats.z_score"],
    },
    {
        "transform_id": "parse_headlines",
        "category": "text_processing",
        "description": "RSS headline parsing and entity extraction",
        "input_fields": ["title", "description", "pubDate"],
        "output_fields": ["events.headline", "events.published_at", "events.region"],
    },
    {
        "transform_id": "checksum_inventory",
        "category": "integrity",
        "description": "SHA-256 checksum generation for archive records",
        "input_fields": ["filename", "content"],
        "output_fields": ["checksum_sha256", "integrity"],
    },
    {
        "transform_id": "schema_inference",
        "category": "metadata",
        "description": "Infer JSON schema from agent output artifacts",
        "input_fields": ["json_document"],
        "output_fields": ["columns", "max_depth", "index_candidates"],
    },
    {
        "transform_id": "pipeline_status_scan",
        "category": "orchestration",
        "description": "Assess ETL stage completion from output file presence and freshness",
        "input_fields": ["pipeline_registry", "output_dir"],
        "output_fields": ["stage_status", "backlog", "orchestration_plan"],
    },
    {
        "transform_id": "retail_momentum",
        "category": "aggregation",
        "description": "Retail proxy momentum scoring for BI dashboard",
        "input_fields": ["symbol", "return_20d_pct", "volume"],
        "output_fields": ["retailers.momentum_score", "dashboard_feed"],
    },
]

BATCH_ORCHESTRATION: list[dict[str, Any]] = [
    {"wave": 1, "pipelines": ["electricity_etl", "grid_etl", "events_etl", "meteorology_etl", "logistics_etl"], "parallel": True},
    {"wave": 2, "pipelines": ["financial_data_etl", "datascience_etl", "finance_etl", "patents_etl", "transportation_etl"], "parallel": True},
    {"wave": 3, "pipelines": ["markets_etl", "geopolitics_etl", "theoretical_probability_etl", "empirical_probability_etl", "research_statistics_etl"], "parallel": True},
    {"wave": 4, "pipelines": ["combined_conditional_etl", "sales_analytics_etl"], "parallel": True},
    {"wave": 5, "pipelines": ["data_steward_etl", "records_management_etl", "database_admin_etl", "data_processor_etl"], "parallel": False},
]

REQUIRED_OUTPUT_KEYS = ("meta", "market_signals", "recommendations")


@dataclass
class PipelineStageStatus:
    pipeline_id: str
    command: str
    extract_status: str
    transform_status: str
    load_status: str
    primary_exists: bool
    sidecars_present: int
    sidecars_expected: int
    freshness_hours: float | None
    freshness_label: str
    overall_status: str
    issues: list[str]


@dataclass
class FormatCheck:
    filename: str
    valid_json: bool
    has_required_keys: bool
    normalized: bool
    issues: list[str]


@dataclass
class ProcessingIssue:
    severity: str
    category: str
    message: str
    remediation: str


@dataclass
class ProcessorAssessment:
    pipeline_coverage: str
    transformation_health: str
    format_compliance: str
    orchestration_status: str
    backlog_summary: str
    processing_priority: str


@dataclass
class DataProcessorReport:
    pipelines: list[PipelineStageStatus]
    format_checks: list[FormatCheck]
    issues: list[ProcessingIssue]
    assessment: ProcessorAssessment
    throughput_score: float
    compliance_score: float
    backlog_score: float
    regime_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DataProcessorExpert:
    """Expert data processor — ETL pipelines, transforms, and orchestration."""

    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or Path("output")

    def _parse_timestamp(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
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

    def _freshness_hours(self, path: Path) -> float | None:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            meta = data.get("meta", {}) if isinstance(data, dict) else {}
            ts = self._parse_timestamp(meta.get("analyzed_at"))
            if ts:
                return round((datetime.now(timezone.utc) - ts).total_seconds() / 3600, 1)
        except Exception:
            pass
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return round((datetime.now(timezone.utc) - mtime).total_seconds() / 3600, 1)

    def _format_check(self, filename: str) -> FormatCheck:
        path = self.output_dir / filename
        issues: list[str] = []
        if not path.exists():
            return FormatCheck(filename, False, False, False, ["file missing"])

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            valid = True
        except Exception as exc:
            return FormatCheck(filename, False, False, False, [f"invalid JSON: {str(exc)[:60]}"])

        has_keys = isinstance(data, dict) and all(k in data for k in REQUIRED_OUTPUT_KEYS)
        if not has_keys:
            missing = [k for k in REQUIRED_OUTPUT_KEYS if k not in (data if isinstance(data, dict) else {})]
            issues.append(f"missing keys: {', '.join(missing)}")

        normalized = has_keys and isinstance(data.get("meta"), dict) and bool(data["meta"].get("analyzed_at"))
        if not normalized:
            issues.append("meta.analyzed_at not normalized")

        return FormatCheck(filename, valid, has_keys, normalized, issues)

    def _pipeline_status(self, pipe: dict[str, Any]) -> PipelineStageStatus:
        load = pipe["load"]
        primary = self.output_dir / load["primary"]
        sidecars = load.get("sidecars", [])
        issues: list[str] = []

        primary_exists = primary.exists()
        sidecars_present = sum(1 for s in sidecars if (self.output_dir / s).exists())
        freshness = self._freshness_hours(primary) if primary_exists else None
        freshness_label = self._freshness_label(freshness)

        extract_status = "ready" if pipe.get("extract") else "unknown"
        transform_status = "configured" if pipe.get("transform") else "missing"
        if primary_exists:
            load_status = "complete"
        elif sidecars_present > 0:
            load_status = "partial"
            issues.append(f"primary {load['primary']} missing")
        else:
            load_status = "pending"
            issues.append(f"pipeline not run: run.bat {pipe['command']}")

        if primary_exists and sidecars and sidecars_present < len(sidecars):
            missing = [s for s in sidecars if not (self.output_dir / s).exists()]
            issues.append(f"missing sidecars: {', '.join(missing)}")

        if freshness_label == "stale":
            issues.append(f"output stale ({freshness:.0f}h)")
        elif freshness_label == "aging":
            issues.append(f"output aging ({freshness:.0f}h)")

        deps = pipe.get("depends_on", [])
        for dep in deps:
            dep_pipe = next((p for p in PIPELINE_REGISTRY if p["pipeline_id"] == dep), None)
            if dep_pipe:
                dep_primary = self.output_dir / dep_pipe["load"]["primary"]
                if not dep_primary.exists():
                    issues.append(f"dependency {dep} not satisfied")

        if load_status == "complete" and not issues:
            overall = "healthy"
        elif load_status in ("complete", "partial") and freshness_label in ("fresh", "aging"):
            overall = "degraded"
        elif load_status == "pending":
            overall = "backlog"
        else:
            overall = "failed"

        return PipelineStageStatus(
            pipeline_id=pipe["pipeline_id"],
            command=pipe["command"],
            extract_status=extract_status,
            transform_status=transform_status,
            load_status=load_status,
            primary_exists=primary_exists,
            sidecars_present=sidecars_present,
            sidecars_expected=len(sidecars),
            freshness_hours=freshness,
            freshness_label=freshness_label,
            overall_status=overall,
            issues=issues,
        )

    def _collect_issues(
        self,
        pipelines: list[PipelineStageStatus],
        formats: list[FormatCheck],
    ) -> list[ProcessingIssue]:
        issues: list[ProcessingIssue] = []

        pipe_by_id = {p["pipeline_id"]: p for p in PIPELINE_REGISTRY}
        for p in pipelines:
            if p.overall_status == "backlog":
                primary = pipe_by_id[p.pipeline_id]["load"]["primary"]
                issues.append(ProcessingIssue(
                    severity="high",
                    category="backlog",
                    message=f"Pipeline {p.pipeline_id} not executed",
                    remediation=f"run.bat {p.command} -o output/{primary}",
                ))
            for issue in p.issues:
                if "dependency" in issue:
                    issues.append(ProcessingIssue(
                        severity="medium",
                        category="dependency",
                        message=f"{p.pipeline_id}: {issue}",
                        remediation="Run upstream pipeline first",
                    ))
                elif "stale" in issue or "aging" in issue:
                    issues.append(ProcessingIssue(
                        severity="medium",
                        category="freshness",
                        message=f"{p.pipeline_id}: {issue}",
                        remediation=f"Re-run run.bat {p.command}",
                    ))
                elif "sidecar" in issue:
                    issues.append(ProcessingIssue(
                        severity="low",
                        category="load",
                        message=f"{p.pipeline_id}: {issue}",
                        remediation=f"Re-run run.bat {p.command} to regenerate sidecars",
                    ))

        for f in formats:
            if not f.valid_json:
                issues.append(ProcessingIssue(
                    severity="high",
                    category="format",
                    message=f"{f.filename}: invalid JSON",
                    remediation="Regenerate output from source agent",
                ))
            elif not f.normalized:
                issues.append(ProcessingIssue(
                    severity="low",
                    category="format",
                    message=f"{f.filename}: output not fully normalized",
                    remediation="Ensure meta.analyzed_at and required keys present",
                ))

        return issues

    def _scores(
        self,
        pipelines: list[PipelineStageStatus],
        formats: list[FormatCheck],
        issues: list[ProcessingIssue],
    ) -> tuple[float, float, float, str]:
        healthy = sum(1 for p in pipelines if p.overall_status == "healthy")
        throughput_score = round(healthy / max(len(pipelines), 1), 4)

        complete = sum(1 for p in pipelines if p.load_status == "complete")
        backlog_score = round(complete / max(len(pipelines), 1), 4)

        normalized = sum(1 for f in formats if f.normalized and f.valid_json)
        present_formats = [f for f in formats if f.valid_json or (self.output_dir / f.filename).exists()]
        compliance_score = round(
            normalized / max(len([f for f in formats if (self.output_dir / f.filename).exists()]), 1),
            4,
        )

        high = sum(1 for i in issues if i.severity == "high")
        avg = (throughput_score + compliance_score + backlog_score) / 3
        if avg >= 0.75 and high == 0:
            regime = "Pipelines Healthy"
        elif avg >= 0.5:
            regime = "Processing Backlog"
        else:
            regime = "Pipeline At Risk"

        return throughput_score, compliance_score, backlog_score, regime

    def _assessment(
        self,
        pipelines: list[PipelineStageStatus],
        formats: list[FormatCheck],
    ) -> ProcessorAssessment:
        healthy = sum(1 for p in pipelines if p.overall_status == "healthy")
        backlog = sum(1 for p in pipelines if p.overall_status == "backlog")
        stale = sum(1 for p in pipelines if p.freshness_label == "stale")
        normalized = sum(1 for f in formats if f.normalized)

        return ProcessorAssessment(
            pipeline_coverage=f"{healthy}/{len(pipelines)} pipelines healthy, {backlog} in backlog",
            transformation_health=f"{len(TRANSFORMATION_CATALOG)} transforms cataloged across ETL stages",
            format_compliance=f"{normalized}/{len(formats)} primary outputs normalized to platform schema",
            orchestration_status=f"{len(BATCH_ORCHESTRATION)}-wave batch plan defined",
            backlog_summary=f"{backlog} pending pipelines, {stale} stale outputs",
            processing_priority=(
                "Execute wave 1 ingestion pipelines, then governance wave 5"
                if backlog > 0
                else "Maintain daily refresh cadence; run data-processor after governance wave"
            ),
        )

    def analyze(self) -> DataProcessorReport:
        pipelines = [self._pipeline_status(p) for p in PIPELINE_REGISTRY]
        primary_files = [p["load"]["primary"] for p in PIPELINE_REGISTRY]
        formats = [self._format_check(f) for f in primary_files]
        issues = self._collect_issues(pipelines, formats)
        assessment = self._assessment(pipelines, formats)
        throughput, compliance, backlog, regime = self._scores(pipelines, formats, issues)

        summary = (
            f"Data processing review: {regime}. "
            f"Throughput {throughput:.0%}, compliance {compliance:.0%}, "
            f"completion {backlog:.0%}. {len(issues)} processing item(s) flagged."
        )

        signals = self._market_signals(throughput, backlog, pipelines, issues)
        recs = self._recommendations(assessment, pipelines, formats, issues)

        return DataProcessorReport(
            pipelines=pipelines,
            format_checks=formats,
            issues=issues,
            assessment=assessment,
            throughput_score=throughput,
            compliance_score=compliance,
            backlog_score=backlog,
            regime_label=regime,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
        )

    @staticmethod
    def _market_signals(
        throughput: float,
        backlog: float,
        pipelines: list[PipelineStageStatus],
        issues: list[ProcessingIssue],
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        score = (throughput + backlog) / 2
        bias = "BULLISH" if score >= 0.7 else "BEARISH" if score <= 0.4 else "NEUTRAL"
        signals.append({
            "sector": "ETL Pipeline Health",
            "tickers": ["SPY", "SNOW"],
            "bias": bias,
            "reason": f"Throughput {throughput:.0%}, completion {backlog:.0%} — {len(issues)} issues",
        })

        stale = [p for p in pipelines if p.freshness_label == "stale"]
        if stale:
            signals.append({
                "sector": "Stale Data Pipeline",
                "tickers": ["VIXY"],
                "bias": "BEARISH",
                "reason": f"{stale[0].pipeline_id} output stale — downstream transforms affected",
            })

        healthy = [p for p in pipelines if p.overall_status == "healthy"]
        if len(healthy) >= len(pipelines) * 0.7:
            signals.append({
                "sector": "Processing Ready",
                "tickers": ["XLK", "NOW"],
                "bias": "BULLISH",
                "reason": f"{len(healthy)} pipelines healthy and normalized",
            })

        return signals

    @staticmethod
    def _recommendations(
        assessment: ProcessorAssessment,
        pipelines: list[PipelineStageStatus],
        formats: list[FormatCheck],
        issues: list[ProcessingIssue],
    ) -> list[str]:
        recs = [
            assessment.pipeline_coverage,
            assessment.transformation_health,
            assessment.format_compliance,
            assessment.orchestration_status,
            assessment.backlog_summary,
            assessment.processing_priority,
        ]
        for wave in BATCH_ORCHESTRATION:
            recs.append(
                f"Wave {wave['wave']}: {', '.join(wave['pipelines'])} "
                f"({'parallel' if wave['parallel'] else 'sequential'})"
            )
        for t in TRANSFORMATION_CATALOG[:6]:
            recs.append(f"Transform {t['transform_id']} ({t['category']}): {t['description']}")
        for p in sorted(pipelines, key=lambda x: (x.overall_status != "healthy", x.pipeline_id))[:8]:
            recs.append(
                f"Pipeline {p.pipeline_id}: {p.overall_status} — "
                f"load {p.load_status}, {p.sidecars_present}/{p.sidecars_expected} sidecars, "
                f"{p.freshness_label}"
            )
        for issue in issues[:8]:
            recs.append(f"[{issue.severity.upper()}] {issue.message} → {issue.remediation}")
        return recs

    def to_dict(self, report: DataProcessorReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Data Processor Expert",
                "analyzed_at": report.analyzed_at,
                "data_source": "Finance ETL pipeline registry + output/ artifacts",
                "expert_summary": report.expert_summary,
                "pipelines_cataloged": len(PIPELINE_REGISTRY),
                "transforms_cataloged": len(TRANSFORMATION_CATALOG),
            },
            "pipeline_registry": PIPELINE_REGISTRY,
            "transformation_catalog": TRANSFORMATION_CATALOG,
            "batch_orchestration": BATCH_ORCHESTRATION,
            "pipeline_status": [
                {
                    "pipeline_id": p.pipeline_id,
                    "command": p.command,
                    "extract_status": p.extract_status,
                    "transform_status": p.transform_status,
                    "load_status": p.load_status,
                    "primary_exists": p.primary_exists,
                    "sidecars_present": p.sidecars_present,
                    "sidecars_expected": p.sidecars_expected,
                    "freshness_hours": p.freshness_hours,
                    "freshness_label": p.freshness_label,
                    "overall_status": p.overall_status,
                    "issues": p.issues,
                }
                for p in report.pipelines
            ],
            "format_checks": [
                {
                    "filename": f.filename,
                    "valid_json": f.valid_json,
                    "has_required_keys": f.has_required_keys,
                    "normalized": f.normalized,
                    "issues": f.issues,
                }
                for f in report.format_checks
            ],
            "processing_issues": [
                {
                    "severity": i.severity,
                    "category": i.category,
                    "message": i.message,
                    "remediation": i.remediation,
                }
                for i in report.issues
            ],
            "processor_assessment": {
                "pipeline_coverage": a.pipeline_coverage,
                "transformation_health": a.transformation_health,
                "format_compliance": a.format_compliance,
                "orchestration_status": a.orchestration_status,
                "backlog_summary": a.backlog_summary,
                "processing_priority": a.processing_priority,
            },
            "metrics": {
                "throughput_score": report.throughput_score,
                "compliance_score": report.compliance_score,
                "backlog_score": report.backlog_score,
                "regime_label": report.regime_label,
                "open_issues": len(report.issues),
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            pipelines_path = output.parent / "processing_pipelines.json"
            pipelines_path.write_text(
                json.dumps({
                    "pipeline_registry": PIPELINE_REGISTRY,
                    "pipeline_status": result["pipeline_status"],
                    "batch_orchestration": BATCH_ORCHESTRATION,
                }, indent=2),
                encoding="utf-8",
            )
            transforms_path = output.parent / "transformation_catalog.json"
            transforms_path.write_text(
                json.dumps(TRANSFORMATION_CATALOG, indent=2),
                encoding="utf-8",
            )
        return result


def run_data_processor_analysis(output: Path | None = None) -> dict[str, Any]:
    return DataProcessorExpert().run(output=output)