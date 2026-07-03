"""
Database Administrator Expert Agent
===================================
Expert database administration for the Finance intelligence platform:
logical schema inventory, storage metrics, index recommendations,
referential integrity, backup posture, connection health, and
performance tuning for JSON data stores.

Scope: output/ artifacts, archive snapshots, config, and external APIs.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

HEADERS = {"User-Agent": "Finance-Database-Admin/1.0 (shaggychunxx@gmail.com)"}

DATA_STORES: list[dict[str, Any]] = [
    {
        "store_id": "output_primary",
        "name": "Primary Intelligence Store",
        "path": "output/",
        "engine": "json_document",
        "role": "oltp_reports",
        "backup_policy": "daily_snapshot",
    },
    {
        "store_id": "archive_cold",
        "name": "Cold Archive Store",
        "path": "output/archive/snapshots/",
        "engine": "json_document",
        "role": "cold_archive",
        "backup_policy": "retain_730d",
    },
    {
        "store_id": "platform_config",
        "name": "Platform Configuration",
        "path": "config.json",
        "engine": "json_config",
        "role": "configuration",
        "backup_policy": "version_control",
    },
]

TABLE_REGISTRY: list[dict[str, Any]] = [
    {"table": "electricity", "file": "electricity.json", "agent": "electricity", "tier": "primary"},
    {"table": "grid", "file": "grid.json", "agent": "grid", "tier": "primary"},
    {"table": "transportation", "file": "transportation.json", "agent": "transportation", "tier": "primary"},
    {"table": "patents", "file": "patents.json", "agent": "patents", "tier": "primary"},
    {"table": "world_events", "file": "world_events.json", "agent": "events", "tier": "primary"},
    {"table": "datascience", "file": "datascience.json", "agent": "datascience", "tier": "primary"},
    {"table": "finance", "file": "finance.json", "agent": "finance", "tier": "primary"},
    {"table": "financial_data", "file": "financial_data.json", "agent": "financial-data", "tier": "primary"},
    {"table": "markets", "file": "markets.json", "agent": "markets", "tier": "primary"},
    {"table": "geopolitics", "file": "geopolitics.json", "agent": "geopolitics", "tier": "primary"},
    {"table": "logistics", "file": "logistics.json", "agent": "logistics", "tier": "primary"},
    {"table": "meteorology", "file": "meteorology.json", "agent": "meteorology", "tier": "primary"},
    {"table": "theoretical_probability", "file": "theoretical_probability.json", "agent": "theoretical-probability", "tier": "primary"},
    {"table": "empirical_probability", "file": "empirical_probability.json", "agent": "empirical-probability", "tier": "primary"},
    {"table": "combined_conditional", "file": "combined_conditional.json", "agent": "combined-conditional", "tier": "primary"},
    {"table": "research_statistics", "file": "research_statistics.json", "agent": "research-statistics", "tier": "primary"},
    {"table": "sales_analytics", "file": "sales_analytics.json", "agent": "sales-analytics", "tier": "primary"},
    {"table": "data_steward", "file": "data_steward.json", "agent": "data-steward", "tier": "governance"},
    {"table": "records_management", "file": "records_management.json", "agent": "records-management", "tier": "governance"},
    {"table": "database_admin", "file": "database_admin.json", "agent": "database-admin", "tier": "governance"},
    {"table": "data_processor", "file": "data_processor.json", "agent": "data-processor", "tier": "governance"},
    {"table": "data_entry", "file": "data_entry.json", "agent": "data-entry", "tier": "governance"},
    {"table": "data_catalog", "file": "data_catalog.json", "agent": "data-steward", "tier": "reference"},
    {"table": "data_lineage", "file": "data_lineage.json", "agent": "data-steward", "tier": "reference"},
    {"table": "archive_catalog", "file": "archive_catalog.json", "agent": "records-management", "tier": "reference"},
    {"table": "retention_schedule", "file": "retention_schedule.json", "agent": "records-management", "tier": "reference"},
    {"table": "sales_dashboard_data", "file": "sales_dashboard_data.json", "agent": "sales-analytics", "tier": "dashboard"},
    {"table": "sales_dashboard_panels", "file": "sales_dashboard_panels.json", "agent": "sales-analytics", "tier": "dashboard"},
]

FOREIGN_KEYS: list[dict[str, str]] = [
    {"child": "eia_grid_monitor_views.json", "parent": "electricity.json", "relationship": "sidecar_catalog"},
    {"child": "grid_markets.json", "parent": "grid.json", "relationship": "sidecar_catalog"},
    {"child": "dot_resources.json", "parent": "transportation.json", "relationship": "sidecar_catalog"},
    {"child": "patent_resources.json", "parent": "patents.json", "relationship": "sidecar_catalog"},
    {"child": "world_events_tracker.json", "parent": "world_events.json", "relationship": "dashboard_feed"},
    {"child": "yahoo_finance_views.json", "parent": "financial_data.json", "relationship": "sidecar_catalog"},
    {"child": "google_finance_views.json", "parent": "finance.json", "relationship": "sidecar_catalog"},
    {"child": "probability_models.json", "parent": "theoretical_probability.json", "relationship": "sidecar_catalog"},
    {"child": "empirical_experiments.json", "parent": "empirical_probability.json", "relationship": "sidecar_catalog"},
    {"child": "probability_concepts.json", "parent": "combined_conditional.json", "relationship": "sidecar_catalog"},
    {"child": "statistical_methods.json", "parent": "research_statistics.json", "relationship": "sidecar_catalog"},
    {"child": "marine_traffic_corridors.json", "parent": "logistics.json", "relationship": "sidecar_catalog"},
    {"child": "sales_dashboard_data.json", "parent": "sales_analytics.json", "relationship": "dashboard_feed"},
    {"child": "sales_dashboard_panels.json", "parent": "sales_analytics.json", "relationship": "dashboard_feed"},
    {"child": "data_catalog.json", "parent": "data_steward.json", "relationship": "governance_sidecar"},
    {"child": "data_lineage.json", "parent": "data_steward.json", "relationship": "governance_sidecar"},
    {"child": "archive_catalog.json", "parent": "records_management.json", "relationship": "governance_sidecar"},
    {"child": "database_schema.json", "parent": "database_admin.json", "relationship": "governance_sidecar"},
    {"child": "database_indexes.json", "parent": "database_admin.json", "relationship": "governance_sidecar"},
    {"child": "processing_pipelines.json", "parent": "data_processor.json", "relationship": "governance_sidecar"},
    {"child": "transformation_catalog.json", "parent": "data_processor.json", "relationship": "governance_sidecar"},
    {"child": "entry_templates.json", "parent": "data_entry.json", "relationship": "governance_sidecar"},
    {"child": "validation_rules.json", "parent": "data_entry.json", "relationship": "governance_sidecar"},
]

CONNECTION_ENDPOINTS: list[dict[str, Any]] = [
    {"id": "yahoo_finance", "name": "Yahoo Finance", "url": "https://query1.finance.yahoo.com/v8/finance/chart/^GSPC"},
    {"id": "openalex", "name": "OpenAlex", "url": "https://api.openalex.org/works?per_page=1"},
    {"id": "nws_api", "name": "NWS Weather", "url": "https://api.weather.gov/alerts/active?area=US"},
    {"id": "bbc_rss", "name": "BBC World RSS", "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
]

RECOMMENDED_INDEXES: list[dict[str, Any]] = [
    {"table": "*", "columns": ["meta.analyzed_at"], "type": "btree", "purpose": "freshness queries"},
    {"table": "*", "columns": ["meta.agent"], "type": "hash", "purpose": "agent lookup"},
    {"table": "archive_catalog", "columns": ["series", "modified_at"], "type": "composite", "purpose": "retention scans"},
    {"table": "world_events", "columns": ["events.published_at"], "type": "btree", "purpose": "timeline queries"},
    {"table": "markets", "columns": ["market_signals.bias"], "type": "hash", "purpose": "signal filtering"},
    {"table": "sales_dashboard_data", "columns": ["retailers.symbol"], "type": "hash", "purpose": "dashboard drill-down"},
]

LARGE_FILE_THRESHOLD = 500_000
DEEP_NEST_THRESHOLD = 8


@dataclass
class SchemaColumn:
    path: str
    dtype: str
    nullable: bool
    sample_count: int | None = None


@dataclass
class TableSchema:
    table_name: str
    filename: str
    exists: bool
    size_bytes: int
    row_estimate: int | None
    max_depth: int
    top_level_keys: list[str]
    columns: list[SchemaColumn]
    index_candidates: list[str]
    issues: list[str]


@dataclass
class ConnectionStatus:
    endpoint_id: str
    name: str
    status: str
    latency_ms: int | None
    http_code: int | None
    message: str


@dataclass
class ReferentialCheck:
    child: str
    parent: str
    relationship: str
    child_exists: bool
    parent_exists: bool
    integrity: str


@dataclass
class BackupStatus:
    snapshot_count: int
    latest_snapshot: str | None
    latest_manifest_valid: bool
    total_archive_bytes: int
    recovery_ready: bool


@dataclass
class DbaIssue:
    severity: str
    category: str
    message: str
    remediation: str


@dataclass
class DbaAssessment:
    schema_coverage: str
    storage_health: str
    integrity_status: str
    backup_posture: str
    connection_health: str
    maintenance_priority: str


@dataclass
class DatabaseAdminReport:
    schemas: list[TableSchema]
    connections: list[ConnectionStatus]
    referential_checks: list[ReferentialCheck]
    backup: BackupStatus
    issues: list[DbaIssue]
    assessment: DbaAssessment
    storage_score: float
    integrity_score: float
    performance_score: float
    regime_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DatabaseAdminExpert:
    """Expert database administrator — schema, storage, integrity, and tuning."""

    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or Path("output")

    def _infer_dtype(self, value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "float"
        if isinstance(value, str):
            return "string"
        if isinstance(value, list):
            return "array"
        if isinstance(value, dict):
            return "object"
        return "unknown"

    def _max_depth(self, obj: Any, depth: int = 0) -> int:
        if isinstance(obj, dict):
            if not obj:
                return depth
            return max(self._max_depth(v, depth + 1) for v in obj.values())
        if isinstance(obj, list):
            if not obj:
                return depth
            return max(self._max_depth(item, depth + 1) for item in obj[:50])
        return depth

    def _collect_columns(
        self, obj: Any, prefix: str = "", limit: int = 40
    ) -> list[SchemaColumn]:
        columns: list[SchemaColumn] = []
        if isinstance(obj, dict):
            for key, value in list(obj.items())[:limit]:
                path = f"{prefix}.{key}" if prefix else key
                dtype = self._infer_dtype(value)
                count = len(value) if isinstance(value, list) else None
                columns.append(SchemaColumn(path=path, dtype=dtype, nullable=value is None, sample_count=count))
                if isinstance(value, dict) and len(columns) < limit:
                    columns.extend(self._collect_columns(value, path, limit - len(columns)))
                elif isinstance(value, list) and value and isinstance(value[0], dict) and len(columns) < limit:
                    columns.extend(self._collect_columns(value[0], f"{path}[]", limit - len(columns)))
        return columns[:limit]

    def _row_estimate(self, data: Any) -> int | None:
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            for key in ("events", "archive_inventory", "artifact_quality", "source_health",
                        "retailers", "signals", "records", "recommendations"):
                if key in data and isinstance(data[key], list):
                    return len(data[key])
        return None

    def _index_candidates(self, columns: list[SchemaColumn], filename: str) -> list[str]:
        candidates: list[str] = []
        for col in columns:
            if any(token in col.path.lower() for token in ("analyzed_at", "modified_at", "published_at", "timestamp")):
                candidates.append(col.path)
            if any(token in col.path.lower() for token in ("agent", "series", "symbol", "bias", "status")):
                candidates.append(col.path)
        if filename == "archive_catalog.json":
            candidates.extend(["series", "checksum_sha256"])
        return list(dict.fromkeys(candidates))[:8]

    def _analyze_table(self, entry: dict[str, Any]) -> TableSchema:
        path = self.output_dir / entry["file"]
        issues: list[str] = []
        if not path.exists():
            return TableSchema(
                table_name=entry["table"],
                filename=entry["file"],
                exists=False,
                size_bytes=0,
                row_estimate=None,
                max_depth=0,
                top_level_keys=[],
                columns=[],
                index_candidates=[],
                issues=["table file missing"],
            )

        size = path.stat().st_size
        if size > LARGE_FILE_THRESHOLD:
            issues.append(f"large table: {size:,} bytes — consider partitioning")

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return TableSchema(
                table_name=entry["table"],
                filename=entry["file"],
                exists=True,
                size_bytes=size,
                row_estimate=None,
                max_depth=0,
                top_level_keys=[],
                columns=[],
                index_candidates=[],
                issues=[f"parse error: {str(exc)[:80]}"],
            )

        depth = self._max_depth(data)
        if depth > DEEP_NEST_THRESHOLD:
            issues.append(f"deep nesting depth {depth} — flatten for query performance")

        top_keys = list(data.keys()) if isinstance(data, dict) else []
        columns = self._collect_columns(data)
        row_est = self._row_estimate(data)
        index_cands = self._index_candidates(columns, entry["file"])

        if isinstance(data, dict) and "meta" not in data and entry["tier"] == "primary":
            issues.append("missing meta block — add analyzed_at for index maintenance")

        return TableSchema(
            table_name=entry["table"],
            filename=entry["file"],
            exists=True,
            size_bytes=size,
            row_estimate=row_est,
            max_depth=depth,
            top_level_keys=top_keys,
            columns=columns,
            index_candidates=index_cands,
            issues=issues,
        )

    def _check_connection(self, endpoint: dict[str, Any]) -> ConnectionStatus:
        url = endpoint["url"]
        headers = dict(HEADERS)
        if endpoint["id"] == "nws_api":
            headers["User-Agent"] = "(Finance-DBA, contact@example.com)"
        start = time.perf_counter()
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            latency = int((time.perf_counter() - start) * 1000)
            if resp.status_code < 400:
                status, msg = "online", f"HTTP {resp.status_code} in {latency}ms"
            elif resp.status_code in (401, 403):
                status, msg = "restricted", f"HTTP {resp.status_code} — auth or rate limit"
            else:
                status, msg = "degraded", f"HTTP {resp.status_code}"
            return ConnectionStatus(
                endpoint_id=endpoint["id"],
                name=endpoint["name"],
                status=status,
                latency_ms=latency,
                http_code=resp.status_code,
                message=msg,
            )
        except Exception as exc:
            return ConnectionStatus(
                endpoint_id=endpoint["id"],
                name=endpoint["name"],
                status="offline",
                latency_ms=None,
                http_code=None,
                message=str(exc)[:120],
            )

    def _referential_integrity(self) -> list[ReferentialCheck]:
        checks: list[ReferentialCheck] = []
        for fk in FOREIGN_KEYS:
            child_path = self.output_dir / fk["child"]
            parent_path = self.output_dir / fk["parent"]
            child_exists = child_path.exists()
            parent_exists = parent_path.exists()
            if child_exists and parent_exists:
                integrity = "valid"
            elif parent_exists and not child_exists:
                integrity = "orphan_parent"
            elif child_exists and not parent_exists:
                integrity = "orphan_child"
            else:
                integrity = "missing_both"
            checks.append(ReferentialCheck(
                child=fk["child"],
                parent=fk["parent"],
                relationship=fk["relationship"],
                child_exists=child_exists,
                parent_exists=parent_exists,
                integrity=integrity,
            ))
        return checks

    def _backup_status(self) -> BackupStatus:
        snap_dir = self.output_dir / "archive" / "snapshots"
        if not snap_dir.exists():
            return BackupStatus(0, None, False, 0, False)

        snapshots = sorted(
            [d for d in snap_dir.iterdir() if d.is_dir()],
            key=lambda p: p.name,
            reverse=True,
        )
        total_bytes = (
            sum(f.stat().st_size for f in snap_dir.rglob("*") if f.is_file())
            if snapshots else 0
        )

        latest = snapshots[0].name if snapshots else None
        manifest_valid = False
        if snapshots:
            manifest = snapshots[0] / "manifest.json"
            if manifest.exists():
                try:
                    json.loads(manifest.read_text(encoding="utf-8"))
                    manifest_valid = True
                except Exception:
                    manifest_valid = False

        return BackupStatus(
            snapshot_count=len(snapshots),
            latest_snapshot=latest,
            latest_manifest_valid=manifest_valid,
            total_archive_bytes=total_bytes,
            recovery_ready=len(snapshots) > 0 and manifest_valid,
        )

    def _collect_issues(
        self,
        schemas: list[TableSchema],
        connections: list[ConnectionStatus],
        refs: list[ReferentialCheck],
        backup: BackupStatus,
    ) -> list[DbaIssue]:
        issues: list[DbaIssue] = []

        missing_primary = [s for s in schemas if not s.exists and s.table_name in {
            e["table"] for e in TABLE_REGISTRY if e["tier"] == "primary"
        }]
        for s in missing_primary[:6]:
            entry = next(e for e in TABLE_REGISTRY if e["table"] == s.table_name)
            issues.append(DbaIssue(
                severity="high",
                category="schema",
                message=f"Primary table {s.filename} missing",
                remediation=f"run.bat {entry['agent']} -o output/{s.filename}",
            ))

        for s in schemas:
            for issue in s.issues:
                sev = "medium" if "large" in issue or "deep" in issue else "low"
                issues.append(DbaIssue(
                    severity=sev,
                    category="performance",
                    message=f"{s.filename}: {issue}",
                    remediation="Run records-management snapshot and consider schema flattening",
                ))

        for c in connections:
            if c.status == "offline":
                issues.append(DbaIssue(
                    severity="high",
                    category="connectivity",
                    message=f"{c.name} offline — {c.message}",
                    remediation=f"Verify network and endpoint for {c.endpoint_id}",
                ))

        orphan_children = [r for r in refs if r.integrity == "orphan_child"]
        for r in orphan_children[:5]:
            issues.append(DbaIssue(
                severity="medium",
                category="integrity",
                message=f"Orphan sidecar {r.child} without parent {r.parent}",
                remediation=f"Regenerate parent report or remove stale {r.child}",
            ))

        if not backup.recovery_ready:
            issues.append(DbaIssue(
                severity="medium",
                category="backup",
                message="No valid archive snapshot for point-in-time recovery",
                remediation="run.bat records-management -o output/records_management.json",
            ))

        return issues

    def _scores(
        self,
        schemas: list[TableSchema],
        refs: list[ReferentialCheck],
        backup: BackupStatus,
        connections: list[ConnectionStatus],
        issues: list[DbaIssue],
    ) -> tuple[float, float, float, str]:
        primary = [s for s in schemas if s.exists and any(
            e["table"] == s.table_name and e["tier"] == "primary" for e in TABLE_REGISTRY
        )]
        primary_total = len([e for e in TABLE_REGISTRY if e["tier"] == "primary"])
        storage_score = round(len(primary) / max(primary_total, 1), 4)

        valid_refs = [r for r in refs if r.integrity == "valid"]
        integrity_score = round(len(valid_refs) / max(len(refs), 1), 4)

        perf_penalty = sum(1 for s in schemas for i in s.issues if "large" in i or "deep" in i)
        perf_base = 1.0 - min(0.4, perf_penalty * 0.05)
        online = sum(1 for c in connections if c.status == "online")
        conn_factor = online / max(len(connections), 1)
        performance_score = round(perf_base * (0.7 + 0.3 * conn_factor), 4)

        if backup.recovery_ready:
            storage_score = min(1.0, storage_score + 0.05)

        high_issues = sum(1 for i in issues if i.severity == "high")
        avg = (storage_score + integrity_score + performance_score) / 3
        if avg >= 0.75 and high_issues == 0:
            regime = "Database Healthy"
        elif avg >= 0.5:
            regime = "Maintenance Recommended"
        else:
            regime = "Database At Risk"

        return storage_score, integrity_score, performance_score, regime

    def _assessment(
        self,
        schemas: list[TableSchema],
        backup: BackupStatus,
        refs: list[ReferentialCheck],
        connections: list[ConnectionStatus],
    ) -> DbaAssessment:
        primary_exist = sum(
            1 for e in TABLE_REGISTRY if e["tier"] == "primary"
            and (self.output_dir / e["file"]).exists()
        )
        primary_total = sum(1 for e in TABLE_REGISTRY if e["tier"] == "primary")
        total_bytes = sum(s.size_bytes for s in schemas if s.exists)

        valid = sum(1 for r in refs if r.integrity == "valid")
        online = sum(1 for c in connections if c.status == "online")

        return DbaAssessment(
            schema_coverage=(
                f"{primary_exist}/{primary_total} primary tables present — "
                f"{len(schemas)} logical tables cataloged"
            ),
            storage_health=(
                f"{total_bytes:,} bytes across output store; "
                f"{backup.snapshot_count} cold-archive snapshot(s)"
            ),
            integrity_status=(
                f"{valid}/{len(refs)} referential links valid; "
                f"{sum(1 for r in refs if r.integrity == 'orphan_child')} orphan sidecars"
            ),
            backup_posture=(
                f"Recovery {'ready' if backup.recovery_ready else 'not ready'} — "
                f"latest snapshot {backup.latest_snapshot or 'none'}"
            ),
            connection_health=(
                f"{online}/{len(connections)} external endpoints online"
            ),
            maintenance_priority=(
                "Run missing agent reports, then records-management snapshot"
                if primary_exist < primary_total
                else "Schedule index review and archive compaction quarterly"
            ),
        )

    def analyze(self) -> DatabaseAdminReport:
        schemas = [self._analyze_table(e) for e in TABLE_REGISTRY]
        connections = [self._check_connection(e) for e in CONNECTION_ENDPOINTS]
        refs = self._referential_integrity()
        backup = self._backup_status()
        issues = self._collect_issues(schemas, connections, refs, backup)
        assessment = self._assessment(schemas, backup, refs, connections)
        storage_score, integrity_score, performance_score, regime = self._scores(
            schemas, refs, backup, connections, issues
        )

        summary = (
            f"Database administration review: {regime}. "
            f"Storage {storage_score:.0%}, integrity {integrity_score:.0%}, "
            f"performance {performance_score:.0%}. "
            f"{len(issues)} maintenance item(s) flagged."
        )

        signals = self._market_signals(storage_score, integrity_score, connections, issues)
        recs = self._recommendations(assessment, schemas, backup, refs, connections, issues)

        return DatabaseAdminReport(
            schemas=schemas,
            connections=connections,
            referential_checks=refs,
            backup=backup,
            issues=issues,
            assessment=assessment,
            storage_score=storage_score,
            integrity_score=integrity_score,
            performance_score=performance_score,
            regime_label=regime,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
        )

    @staticmethod
    def _market_signals(
        storage: float,
        integrity: float,
        connections: list[ConnectionStatus],
        issues: list[DbaIssue],
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        score = (storage + integrity) / 2
        bias = "BULLISH" if score >= 0.7 else "BEARISH" if score <= 0.4 else "NEUTRAL"
        signals.append({
            "sector": "Data Infrastructure Health",
            "tickers": ["SPY", "IGV"],
            "bias": bias,
            "reason": f"Storage {storage:.0%}, integrity {integrity:.0%} — {len(issues)} DBA issues",
        })

        offline = [c for c in connections if c.status == "offline"]
        if offline:
            signals.append({
                "sector": "Connectivity Risk",
                "tickers": ["TLT", "GLD"],
                "bias": "BEARISH",
                "reason": f"{offline[0].name} offline — ingestion pipelines may stall",
            })

        if integrity >= 0.8:
            signals.append({
                "sector": "Schema Integrity Strong",
                "tickers": ["XLK", "MSFT"],
                "bias": "BULLISH",
                "reason": "Referential links between reports and sidecars are consistent",
            })

        return signals

    @staticmethod
    def _recommendations(
        assessment: DbaAssessment,
        schemas: list[TableSchema],
        backup: BackupStatus,
        refs: list[ReferentialCheck],
        connections: list[ConnectionStatus],
        issues: list[DbaIssue],
    ) -> list[str]:
        recs = [
            assessment.schema_coverage,
            assessment.storage_health,
            assessment.integrity_status,
            assessment.backup_posture,
            assessment.connection_health,
            assessment.maintenance_priority,
        ]
        for idx in RECOMMENDED_INDEXES[:6]:
            recs.append(
                f"Index {idx['table']}.{','.join(idx['columns'])} "
                f"({idx['type']}) — {idx['purpose']}"
            )
        for s in sorted(schemas, key=lambda x: -x.size_bytes)[:5]:
            if s.exists:
                recs.append(
                    f"Table {s.table_name}: {s.size_bytes:,} bytes, "
                    f"depth {s.max_depth}"
                    + (f", ~{s.row_estimate} rows" if s.row_estimate else "")
                )
        for c in connections:
            recs.append(f"Connection {c.name}: {c.status} — {c.message}")
        for r in refs:
            if r.integrity != "valid":
                recs.append(f"FK {r.child} → {r.parent}: {r.integrity}")
        if backup.latest_snapshot:
            recs.append(f"Latest backup snapshot: {backup.latest_snapshot}")
        for issue in issues[:8]:
            recs.append(f"[{issue.severity.upper()}] {issue.message} → {issue.remediation}")
        return recs

    def to_dict(self, report: DatabaseAdminReport) -> dict[str, Any]:
        a = report.assessment
        schema_entries = [
            {
                "table_name": s.table_name,
                "filename": s.filename,
                "exists": s.exists,
                "size_bytes": s.size_bytes,
                "row_estimate": s.row_estimate,
                "max_depth": s.max_depth,
                "top_level_keys": s.top_level_keys,
                "columns": [
                    {"path": c.path, "dtype": c.dtype, "nullable": c.nullable, "sample_count": c.sample_count}
                    for c in s.columns
                ],
                "index_candidates": s.index_candidates,
                "issues": s.issues,
            }
            for s in report.schemas
        ]
        return {
            "meta": {
                "agent": "Database Administrator Expert",
                "analyzed_at": report.analyzed_at,
                "data_source": "Finance output/ JSON stores + external API connectivity",
                "expert_summary": report.expert_summary,
                "stores_cataloged": len(DATA_STORES),
                "tables_cataloged": len(TABLE_REGISTRY),
            },
            "data_stores": DATA_STORES,
            "table_registry": TABLE_REGISTRY,
            "schema_inventory": schema_entries,
            "connection_status": [
                {
                    "endpoint_id": c.endpoint_id,
                    "name": c.name,
                    "status": c.status,
                    "latency_ms": c.latency_ms,
                    "http_code": c.http_code,
                    "message": c.message,
                }
                for c in report.connections
            ],
            "referential_integrity": [
                {
                    "child": r.child,
                    "parent": r.parent,
                    "relationship": r.relationship,
                    "child_exists": r.child_exists,
                    "parent_exists": r.parent_exists,
                    "integrity": r.integrity,
                }
                for r in report.referential_checks
            ],
            "backup_status": {
                "snapshot_count": report.backup.snapshot_count,
                "latest_snapshot": report.backup.latest_snapshot,
                "latest_manifest_valid": report.backup.latest_manifest_valid,
                "total_archive_bytes": report.backup.total_archive_bytes,
                "recovery_ready": report.backup.recovery_ready,
            },
            "recommended_indexes": RECOMMENDED_INDEXES,
            "dba_issues": [
                {
                    "severity": i.severity,
                    "category": i.category,
                    "message": i.message,
                    "remediation": i.remediation,
                }
                for i in report.issues
            ],
            "dba_assessment": {
                "schema_coverage": a.schema_coverage,
                "storage_health": a.storage_health,
                "integrity_status": a.integrity_status,
                "backup_posture": a.backup_posture,
                "connection_health": a.connection_health,
                "maintenance_priority": a.maintenance_priority,
            },
            "metrics": {
                "storage_score": report.storage_score,
                "integrity_score": report.integrity_score,
                "performance_score": report.performance_score,
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
            schema_path = output.parent / "database_schema.json"
            schema_path.write_text(
                json.dumps(result["schema_inventory"], indent=2),
                encoding="utf-8",
            )
            index_path = output.parent / "database_indexes.json"
            index_path.write_text(
                json.dumps({
                    "recommended_indexes": RECOMMENDED_INDEXES,
                    "table_index_candidates": {
                        s["table_name"]: s["index_candidates"]
                        for s in result["schema_inventory"]
                        if s.get("index_candidates")
                    },
                }, indent=2),
                encoding="utf-8",
            )
        return result


def run_database_admin_analysis(output: Path | None = None) -> dict[str, Any]:
    return DatabaseAdminExpert().run(output=output)