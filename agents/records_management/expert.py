"""
Records Management / Archivist Expert Agent
============================================
Expert records manager and archivist for the Finance intelligence platform:
archive inventory, retention schedules, classification, integrity checksums,
disposition recommendations, and timestamped snapshot archiving.

Scope: output/ artifacts, archive snapshots, and record series registry.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RETENTION_SCHEDULE: list[dict[str, Any]] = [
    {
        "series": "agent_primary_report",
        "description": "Primary JSON intelligence reports from platform agents",
        "retention_days": 90,
        "disposition": "archive_then_review",
        "storage_tier": "active",
    },
    {
        "series": "reference_catalog",
        "description": "Sidecar catalogs, views, and resource indexes",
        "retention_days": 365,
        "disposition": "retain_permanent",
        "storage_tier": "reference",
    },
    {
        "series": "dashboard_feed",
        "description": "BI dashboard data feeds and panel definitions",
        "retention_days": 30,
        "disposition": "rolling_replace",
        "storage_tier": "active",
    },
    {
        "series": "stewardship_metadata",
        "description": "Data catalog, lineage, and stewardship reports",
        "retention_days": 180,
        "disposition": "archive_then_review",
        "storage_tier": "governance",
    },
    {
        "series": "archive_snapshot",
        "description": "Point-in-time archive snapshots with manifest",
        "retention_days": 730,
        "disposition": "retain_permanent",
        "storage_tier": "cold_archive",
    },
]

RECORD_SERIES: list[dict[str, Any]] = [
    {"pattern": "electricity.json", "series": "agent_primary_report", "agent": "electricity"},
    {"pattern": "grid.json", "series": "agent_primary_report", "agent": "grid"},
    {"pattern": "transportation.json", "series": "agent_primary_report", "agent": "transportation"},
    {"pattern": "patents.json", "series": "agent_primary_report", "agent": "patents"},
    {"pattern": "world_events.json", "series": "agent_primary_report", "agent": "events"},
    {"pattern": "datascience.json", "series": "agent_primary_report", "agent": "datascience"},
    {"pattern": "finance.json", "series": "agent_primary_report", "agent": "finance"},
    {"pattern": "financial_data.json", "series": "agent_primary_report", "agent": "financial-data"},
    {"pattern": "markets.json", "series": "agent_primary_report", "agent": "markets"},
    {"pattern": "geopolitics.json", "series": "agent_primary_report", "agent": "geopolitics"},
    {"pattern": "logistics.json", "series": "agent_primary_report", "agent": "logistics"},
    {"pattern": "meteorology.json", "series": "agent_primary_report", "agent": "meteorology"},
    {"pattern": "theoretical_probability.json", "series": "agent_primary_report", "agent": "theoretical-probability"},
    {"pattern": "empirical_probability.json", "series": "agent_primary_report", "agent": "empirical-probability"},
    {"pattern": "combined_conditional.json", "series": "agent_primary_report", "agent": "combined-conditional"},
    {"pattern": "research_statistics.json", "series": "agent_primary_report", "agent": "research-statistics"},
    {"pattern": "sales_analytics.json", "series": "agent_primary_report", "agent": "sales-analytics"},
    {"pattern": "wisdom_judgment.json", "series": "agent_primary_report", "agent": "wisdom"},
    {"pattern": "data_steward.json", "series": "stewardship_metadata", "agent": "data-steward"},
    {"pattern": "records_management.json", "series": "stewardship_metadata", "agent": "records-management"},
    {"pattern": "_views.json", "series": "reference_catalog", "agent": None},
    {"pattern": "_resources.json", "series": "reference_catalog", "agent": None},
    {"pattern": "_catalog.json", "series": "reference_catalog", "agent": None},
    {"pattern": "_panels.json", "series": "dashboard_feed", "agent": None},
    {"pattern": "sales_dashboard_data.json", "series": "dashboard_feed", "agent": "sales-analytics"},
    {"pattern": "_experiments.json", "series": "reference_catalog", "agent": None},
    {"pattern": "_models.json", "series": "reference_catalog", "agent": None},
    {"pattern": "_concepts.json", "series": "reference_catalog", "agent": None},
    {"pattern": "_methods.json", "series": "reference_catalog", "agent": None},
    {"pattern": "_lineage.json", "series": "stewardship_metadata", "agent": None},
    {"pattern": "world_events_tracker.json", "series": "dashboard_feed", "agent": "events"},
    {"pattern": "wisdom_frameworks.json", "series": "reference_catalog", "agent": "wisdom"},
]


@dataclass
class ArchiveRecord:
    record_id: str
    filename: str
    series: str
    agent_command: str | None
    size_bytes: int
    modified_at: str
    checksum_sha256: str
    retention_days: int
    age_days: float
    disposition: str
    storage_tier: str
    integrity: str


@dataclass
class SnapshotResult:
    snapshot_id: str
    path: str
    files_copied: int
    total_bytes: int
    manifest_path: str


@dataclass
class DispositionAction:
    filename: str
    action: str
    reason: str
    priority: str


@dataclass
class ArchivistAssessment:
    inventory_status: str
    retention_compliance: str
    integrity_status: str
    archive_coverage: str
    disposition_summary: str
    archival_priority: str


@dataclass
class RecordsManagementReport:
    records: list[ArchiveRecord]
    snapshots: list[SnapshotResult]
    disposition_actions: list[DispositionAction]
    assessment: ArchivistAssessment
    archive_score: float
    compliance_score: float
    volume_bytes: int
    record_count: int
    regime_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RecordsManagementExpert:
    """Expert records manager / archivist — inventory, retention, and snapshots."""

    def __init__(
        self,
        output_dir: Path | None = None,
        archive_dir: Path | None = None,
        create_snapshot: bool = True,
    ) -> None:
        self.output_dir = output_dir or Path("output")
        self.archive_dir = archive_dir or self.output_dir / "archive" / "snapshots"
        self.create_snapshot = create_snapshot

    def _classify(self, filename: str) -> tuple[str, str | None]:
        for entry in RECORD_SERIES:
            pattern = entry["pattern"]
            if pattern.startswith("_") and pattern[1:] in filename:
                return entry["series"], entry.get("agent")
            if filename == pattern or filename.endswith(pattern):
                return entry["series"], entry.get("agent")
        if filename.endswith(".json"):
            return "agent_primary_report", None
        return "unclassified", None

    def _retention_for_series(self, series: str) -> dict[str, Any]:
        for r in RETENTION_SCHEDULE:
            if r["series"] == series:
                return r
        return RETENTION_SCHEDULE[0]

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def _inventory_record(self, path: Path) -> ArchiveRecord | None:
        if not path.is_file() or path.suffix != ".json":
            return None
        if "archive" in path.parts and path.parent != self.output_dir:
            return None

        stat = path.stat()
        modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        age_days = (datetime.now(timezone.utc) - modified).total_seconds() / 86400
        series, agent = self._classify(path.name)
        policy = self._retention_for_series(series)
        retention_days = policy["retention_days"]

        if age_days > retention_days * 1.5:
            disposition = "dispose_candidate"
        elif age_days > retention_days:
            disposition = "archive_candidate"
        else:
            disposition = "active_retention"

        try:
            checksum = self._sha256(path)
            json.loads(path.read_text(encoding="utf-8"))
            integrity = "valid"
        except json.JSONDecodeError:
            checksum = ""
            integrity = "corrupt"
        except Exception:
            checksum = ""
            integrity = "unreadable"

        return ArchiveRecord(
            record_id=f"rec-{path.stem}",
            filename=path.name,
            series=series,
            agent_command=agent,
            size_bytes=stat.st_size,
            modified_at=modified.isoformat(),
            checksum_sha256=checksum,
            retention_days=retention_days,
            age_days=round(age_days, 2),
            disposition=disposition,
            storage_tier=policy["storage_tier"],
            integrity=integrity,
        )

    def _create_snapshot(self, records: list[ArchiveRecord]) -> SnapshotResult | None:
        active_files = [
            self.output_dir / r.filename
            for r in records
            if r.integrity == "valid" and (self.output_dir / r.filename).exists()
        ]
        if not active_files:
            return None

        snapshot_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        snap_path = self.archive_dir / snapshot_id
        snap_path.mkdir(parents=True, exist_ok=True)

        copied = 0
        total_bytes = 0
        manifest_entries: list[dict[str, Any]] = []

        for src in active_files:
            if not src.exists():
                continue
            dest = snap_path / src.name
            shutil.copy2(src, dest)
            copied += 1
            total_bytes += src.stat().st_size
            rec = next((r for r in records if r.filename == src.name), None)
            manifest_entries.append({
                "filename": src.name,
                "checksum_sha256": rec.checksum_sha256 if rec else "",
                "size_bytes": src.stat().st_size,
                "series": rec.series if rec else "unknown",
            })

        manifest = {
            "snapshot_id": snapshot_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "record_count": copied,
            "total_bytes": total_bytes,
            "files": manifest_entries,
        }
        manifest_path = snap_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        return SnapshotResult(
            snapshot_id=snapshot_id,
            path=str(snap_path),
            files_copied=copied,
            total_bytes=total_bytes,
            manifest_path=str(manifest_path),
        )

    def _disposition_actions(self, records: list[ArchiveRecord]) -> list[DispositionAction]:
        actions: list[DispositionAction] = []
        for r in records:
            if r.integrity == "corrupt":
                actions.append(DispositionAction(
                    filename=r.filename,
                    action="quarantine",
                    reason="JSON integrity failure — record corrupt",
                    priority="high",
                ))
            elif r.disposition == "dispose_candidate":
                actions.append(DispositionAction(
                    filename=r.filename,
                    action="dispose",
                    reason=f"Exceeded retention {r.retention_days}d (age {r.age_days:.0f}d)",
                    priority="medium",
                ))
            elif r.disposition == "archive_candidate":
                actions.append(DispositionAction(
                    filename=r.filename,
                    action="archive",
                    reason=f"Past retention window ({r.age_days:.0f}d > {r.retention_days}d)",
                    priority="low",
                ))
        return actions

    def _list_existing_snapshots(self) -> list[dict[str, Any]]:
        if not self.archive_dir.exists():
            return []
        snapshots: list[dict[str, Any]] = []
        for d in sorted(self.archive_dir.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            manifest = d / "manifest.json"
            if manifest.exists():
                try:
                    m = json.loads(manifest.read_text(encoding="utf-8"))
                    snapshots.append({
                        "snapshot_id": m.get("snapshot_id", d.name),
                        "path": str(d),
                        "created_at": m.get("created_at"),
                        "record_count": m.get("record_count", 0),
                        "total_bytes": m.get("total_bytes", 0),
                    })
                except Exception:
                    snapshots.append({"snapshot_id": d.name, "path": str(d)})
            else:
                snapshots.append({"snapshot_id": d.name, "path": str(d), "record_count": 0})
        return snapshots[:10]

    def _assessment(
        self,
        records: list[ArchiveRecord],
        snapshots: list[SnapshotResult],
        existing_snapshots: list[dict[str, Any]],
        actions: list[DispositionAction],
    ) -> ArchivistAssessment:
        total = len(records)
        valid = sum(1 for r in records if r.integrity == "valid")
        inventory = f"{total} records inventoried in output/, {valid} integrity-valid"

        overdue = sum(1 for r in records if r.disposition in ("archive_candidate", "dispose_candidate"))
        if overdue == 0:
            retention = "100% retention compliance — no records past policy window"
        else:
            pct = round((1 - overdue / max(total, 1)) * 100)
            retention = f"{pct}% retention compliance — {overdue} records past retention window"

        corrupt = [r for r in records if r.integrity != "valid"]
        if corrupt:
            integrity = f"{len(corrupt)} integrity failures require quarantine"
        else:
            integrity = "all records pass JSON integrity verification"

        snap_count = len(existing_snapshots) + len(snapshots)
        if snap_count:
            archive_cov = f"{snap_count} archive snapshot(s) on file in output/archive/snapshots/"
        else:
            archive_cov = "no archive snapshots yet — snapshot created on this run"

        if actions:
            high = sum(1 for a in actions if a.priority == "high")
            disp = f"{len(actions)} disposition actions ({high} high priority)"
        else:
            disp = "no disposition actions required"

        if corrupt:
            priority = "quarantine corrupt records before next agent refresh cycle"
        elif overdue:
            priority = "move overdue records to cold archive tier or dispose per schedule"
        elif snap_count < 2:
            priority = "establish regular snapshot cadence (weekly agent batch runs)"
        else:
            priority = "maintain snapshot cadence and annual catalog review"

        return ArchivistAssessment(
            inventory_status=inventory,
            retention_compliance=retention,
            integrity_status=integrity,
            archive_coverage=archive_cov,
            disposition_summary=disp,
            archival_priority=priority,
        )

    def analyze(self) -> RecordsManagementReport:
        records: list[ArchiveRecord] = []
        if self.output_dir.exists():
            for path in sorted(self.output_dir.glob("*.json")):
                rec = self._inventory_record(path)
                if rec:
                    records.append(rec)

        snapshots: list[SnapshotResult] = []
        if self.create_snapshot and records:
            snap = self._create_snapshot(records)
            if snap:
                snapshots.append(snap)

        existing = self._list_existing_snapshots()
        actions = self._disposition_actions(records)
        assessment = self._assessment(records, snapshots, existing, actions)

        volume = sum(r.size_bytes for r in records)
        compliance = round(
            sum(1 for r in records if r.disposition == "active_retention") / max(len(records), 1),
            4,
        )
        integrity_ratio = sum(1 for r in records if r.integrity == "valid") / max(len(records), 1)
        snap_bonus = 0.15 if snapshots or existing else 0.0
        archive_score = round(
            0.4 * compliance + 0.35 * integrity_ratio + 0.25 * min(1.0, len(existing) / 3) + snap_bonus,
            4,
        )
        archive_score = min(1.0, archive_score)

        if archive_score >= 0.75 and not actions:
            regime_label = "Archive Compliant"
        elif archive_score >= 0.55:
            regime_label = "Archive Adequate"
        else:
            regime_label = "Archive Needs Improvement"

        summary = (
            f"Records management scan: {regime_label} (score {archive_score:.2f}). "
            f"{assessment.inventory_status}. "
            f"{assessment.retention_compliance}. "
            f"{assessment.integrity_status}. "
            f"{assessment.archive_coverage}. "
            f"{assessment.disposition_summary}. "
            f"Volume {volume:,} bytes across {len(records)} records. "
            f"Priority: {assessment.archival_priority}."
        )

        signals = self._market_signals(records, actions, archive_score)
        recs = self._recommendations(assessment, records, snapshots, existing, actions)

        return RecordsManagementReport(
            records=records,
            snapshots=snapshots,
            disposition_actions=actions,
            assessment=assessment,
            archive_score=archive_score,
            compliance_score=compliance,
            volume_bytes=volume,
            record_count=len(records),
            regime_label=regime_label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
        )

    @staticmethod
    def _market_signals(
        records: list[ArchiveRecord],
        actions: list[DispositionAction],
        score: float,
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        bias = (
            "BULLISH" if score >= 0.7 else
            "BEARISH" if score <= 0.45 else
            "NEUTRAL"
        )
        signals.append({
            "sector": "Records & Archive Health",
            "tickers": ["SPY"],
            "bias": bias,
            "reason": f"Archive score {score:.2f}, {len(records)} records, {len(actions)} actions pending",
        })

        corrupt = [r for r in records if r.integrity != "valid"]
        if corrupt:
            signals.append({
                "sector": "Data Integrity Risk",
                "tickers": ["VIXY", "GLD"],
                "bias": "BEARISH",
                "reason": f"{corrupt[0].filename} failed integrity check",
            })

        primary = [r for r in records if r.series == "agent_primary_report" and r.integrity == "valid"]
        if len(primary) >= 10:
            signals.append({
                "sector": "Intelligence Archive Ready",
                "tickers": ["XLK", "QQQ"],
                "bias": "BULLISH",
                "reason": f"{len(primary)} primary agent reports archived and valid",
            })

        return signals

    @staticmethod
    def _recommendations(
        assessment: ArchivistAssessment,
        records: list[ArchiveRecord],
        snapshots: list[SnapshotResult],
        existing: list[dict[str, Any]],
        actions: list[DispositionAction],
    ) -> list[str]:
        recs = [
            assessment.inventory_status,
            assessment.retention_compliance,
            assessment.integrity_status,
            assessment.archive_coverage,
            assessment.disposition_summary,
            assessment.archival_priority,
        ]
        by_series: dict[str, list[ArchiveRecord]] = {}
        for r in records:
            by_series.setdefault(r.series, []).append(r)
        for series, rows in sorted(by_series.items()):
            total_size = sum(x.size_bytes for x in rows)
            recs.append(f"Series {series}: {len(rows)} records, {total_size:,} bytes")
        for snap in snapshots:
            recs.append(
                f"Created snapshot {snap.snapshot_id}: {snap.files_copied} files, "
                f"{snap.total_bytes:,} bytes → {snap.path}"
            )
        for ex in existing[:3]:
            recs.append(
                f"Existing snapshot {ex.get('snapshot_id')}: "
                f"{ex.get('record_count', 0)} files"
            )
        for a in actions[:6]:
            recs.append(f"[{a.priority}] {a.action} {a.filename} — {a.reason}")
        for pol in RETENTION_SCHEDULE:
            recs.append(
                f"Policy {pol['series']}: retain {pol['retention_days']}d, "
                f"{pol['disposition']}, tier {pol['storage_tier']}"
            )
        return recs

    def to_dict(self, report: RecordsManagementReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Records Management / Archivist Expert",
                "analyzed_at": report.analyzed_at,
                "data_source": "Finance output/ archive inventory",
                "expert_summary": report.expert_summary,
                "record_count": report.record_count,
                "volume_bytes": report.volume_bytes,
            },
            "retention_schedule": RETENTION_SCHEDULE,
            "record_series": RECORD_SERIES,
            "archive_inventory": [
                {
                    "record_id": r.record_id,
                    "filename": r.filename,
                    "series": r.series,
                    "agent_command": r.agent_command,
                    "size_bytes": r.size_bytes,
                    "modified_at": r.modified_at,
                    "checksum_sha256": r.checksum_sha256,
                    "retention_days": r.retention_days,
                    "age_days": r.age_days,
                    "disposition": r.disposition,
                    "storage_tier": r.storage_tier,
                    "integrity": r.integrity,
                }
                for r in report.records
            ],
            "snapshots_created": [
                {
                    "snapshot_id": s.snapshot_id,
                    "path": s.path,
                    "files_copied": s.files_copied,
                    "total_bytes": s.total_bytes,
                    "manifest_path": s.manifest_path,
                }
                for s in report.snapshots
            ],
            "disposition_actions": [
                {
                    "filename": d.filename,
                    "action": d.action,
                    "reason": d.reason,
                    "priority": d.priority,
                }
                for d in report.disposition_actions
            ],
            "archivist_assessment": {
                "inventory_status": a.inventory_status,
                "retention_compliance": a.retention_compliance,
                "integrity_status": a.integrity_status,
                "archive_coverage": a.archive_coverage,
                "disposition_summary": a.disposition_summary,
                "archival_priority": a.archival_priority,
            },
            "metrics": {
                "archive_score": report.archive_score,
                "compliance_score": report.compliance_score,
                "regime_label": report.regime_label,
                "pending_actions": len(report.disposition_actions),
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog_path = output.parent / "archive_catalog.json"
            catalog_path.write_text(
                json.dumps(result["archive_inventory"], indent=2),
                encoding="utf-8",
            )
            retention_path = output.parent / "retention_schedule.json"
            retention_path.write_text(
                json.dumps(RETENTION_SCHEDULE, indent=2),
                encoding="utf-8",
            )
        return result


def run_records_management_analysis(output: Path | None = None) -> dict[str, Any]:
    return RecordsManagementExpert().run(output=output)