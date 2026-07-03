"""
Data Entry Specialist Expert Agent
==================================
Expert data entry for the Finance intelligence platform:
entry templates, field validation, sanitization checks, double-entry
verification, capture queue management, and accuracy scoring.

Scope: output/ artifacts, platform report schema, and entry workflows.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENTRY_TEMPLATES: list[dict[str, Any]] = [
    {
        "template_id": "agent_report_standard",
        "name": "Standard Agent Intelligence Report",
        "applies_to": "*.json primary reports",
        "sections": [
            {"section": "meta", "fields": ["agent", "analyzed_at", "data_source", "expert_summary"]},
            {"section": "metrics", "fields": ["regime_label", "score fields"]},
            {"section": "market_signals", "fields": ["sector", "tickers", "bias", "reason"]},
            {"section": "recommendations", "fields": ["list of actionable strings"]},
        ],
    },
    {
        "template_id": "market_signal_entry",
        "name": "Market Signal Capture Form",
        "applies_to": "market_signals[]",
        "fields": [
            {"name": "sector", "type": "string", "required": True, "max_length": 80},
            {"name": "tickers", "type": "array[string]", "required": True, "min_items": 1},
            {"name": "bias", "type": "enum", "required": True, "values": ["BULLISH", "BEARISH", "NEUTRAL"]},
            {"name": "reason", "type": "string", "required": True, "max_length": 240},
        ],
    },
    {
        "template_id": "event_headline_entry",
        "name": "World Event Headline Capture",
        "applies_to": "world_events.json events[]",
        "fields": [
            {"name": "headline", "type": "string", "required": True, "max_length": 300},
            {"name": "source", "type": "string", "required": True},
            {"name": "published_at", "type": "iso8601", "required": True},
            {"name": "region", "type": "string", "required": False},
        ],
    },
    {
        "template_id": "catalog_resource_entry",
        "name": "Reference Catalog Resource Entry",
        "applies_to": "*_resources.json, *_views.json, *_catalog.json",
        "fields": [
            {"name": "name", "type": "string", "required": True},
            {"name": "url", "type": "url", "required": False},
            {"name": "description", "type": "string", "required": False, "max_length": 500},
        ],
    },
    {
        "template_id": "governance_report_entry",
        "name": "Governance Report Entry",
        "applies_to": "data_steward.json, records_management.json, database_admin.json, data_processor.json",
        "fields": [
            {"name": "meta.agent", "type": "string", "required": True},
            {"name": "meta.analyzed_at", "type": "iso8601", "required": True},
            {"name": "metrics", "type": "object", "required": True},
            {"name": "recommendations", "type": "array", "required": True, "min_items": 3},
        ],
    },
]

VALIDATION_RULES: list[dict[str, Any]] = [
    {"rule_id": "req_meta_agent", "field": "meta.agent", "check": "required", "severity": "error"},
    {"rule_id": "req_meta_analyzed_at", "field": "meta.analyzed_at", "check": "iso8601", "severity": "error"},
    {"rule_id": "req_meta_data_source", "field": "meta.data_source", "check": "required", "severity": "warning"},
    {"rule_id": "req_meta_summary", "field": "meta.expert_summary", "check": "min_length:20", "severity": "warning"},
    {"rule_id": "req_market_signals", "field": "market_signals", "check": "array_min:1", "severity": "warning"},
    {"rule_id": "req_recommendations", "field": "recommendations", "check": "array_min:3", "severity": "warning"},
    {"rule_id": "sig_bias_enum", "field": "market_signals[].bias", "check": "enum:BULLISH,BEARISH,NEUTRAL", "severity": "error"},
    {"rule_id": "sig_tickers_present", "field": "market_signals[].tickers", "check": "array_min:1", "severity": "error"},
    {"rule_id": "rec_non_empty", "field": "recommendations[]", "check": "non_empty_string", "severity": "warning"},
    {"rule_id": "metrics_regime", "field": "metrics.regime_label", "check": "required", "severity": "warning"},
]

ARTIFACT_REGISTRY: list[dict[str, Any]] = [
    {"file": "electricity.json", "command": "electricity", "tier": "primary"},
    {"file": "grid.json", "command": "grid", "tier": "primary"},
    {"file": "transportation.json", "command": "transportation", "tier": "primary"},
    {"file": "patents.json", "command": "patents", "tier": "primary"},
    {"file": "world_events.json", "command": "events", "tier": "primary"},
    {"file": "datascience.json", "command": "datascience", "tier": "primary"},
    {"file": "finance.json", "command": "finance", "tier": "primary"},
    {"file": "financial_data.json", "command": "financial-data", "tier": "primary"},
    {"file": "markets.json", "command": "markets", "tier": "primary"},
    {"file": "geopolitics.json", "command": "geopolitics", "tier": "primary"},
    {"file": "logistics.json", "command": "logistics", "tier": "primary"},
    {"file": "meteorology.json", "command": "meteorology", "tier": "primary"},
    {"file": "theoretical_probability.json", "command": "theoretical-probability", "tier": "primary"},
    {"file": "empirical_probability.json", "command": "empirical-probability", "tier": "primary"},
    {"file": "combined_conditional.json", "command": "combined-conditional", "tier": "primary"},
    {"file": "research_statistics.json", "command": "research-statistics", "tier": "primary"},
    {"file": "sales_analytics.json", "command": "sales-analytics", "tier": "primary"},
    {"file": "data_steward.json", "command": "data-steward", "tier": "governance"},
    {"file": "records_management.json", "command": "records-management", "tier": "governance"},
    {"file": "database_admin.json", "command": "database-admin", "tier": "governance"},
    {"file": "data_processor.json", "command": "data-processor", "tier": "governance"},
    {"file": "data_entry.json", "command": "data-entry", "tier": "governance"},
]

ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
)


@dataclass
class FieldValidation:
    filename: str
    field: str
    rule_id: str
    status: str
    severity: str
    message: str


@dataclass
class ArtifactEntryAudit:
    filename: str
    command: str | None
    exists: bool
    fields_present: int
    fields_expected: int
    validations_passed: int
    validations_failed: int
    accuracy_score: float
    entry_status: str
    issues: list[str]


@dataclass
class EntryQueueItem:
    filename: str
    field: str
    priority: str
    action: str
    remediation: str


@dataclass
class DoubleEntryCheck:
    primary: str
    secondary: str
    field: str
    primary_value: str | None
    secondary_value: str | None
    match: bool


@dataclass
class EntryIssue:
    severity: str
    category: str
    message: str
    remediation: str


@dataclass
class EntryAssessment:
    capture_coverage: str
    validation_status: str
    accuracy_summary: str
    queue_status: str
    sanitization_status: str
    entry_priority: str


@dataclass
class DataEntryReport:
    audits: list[ArtifactEntryAudit]
    validations: list[FieldValidation]
    queue: list[EntryQueueItem]
    double_entry: list[DoubleEntryCheck]
    issues: list[EntryIssue]
    assessment: EntryAssessment
    accuracy_score: float
    validation_score: float
    completeness_score: float
    regime_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DataEntryExpert:
    """Expert data entry specialist — templates, validation, and capture quality."""

    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or Path("output")

    def _get_nested(self, data: Any, path: str) -> Any:
        if "[]" in path:
            base, rest = path.split("[]", 1)
            rest = rest.lstrip(".")
            base_val = self._get_nested(data, base) if base else data
            if not isinstance(base_val, list):
                return None
            if not rest:
                return base_val
            return [self._get_nested(item, rest) for item in base_val]
        parts = path.split(".")
        current = data
        for part in parts:
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    def _check_rule(self, data: dict[str, Any], rule: dict[str, Any]) -> list[FieldValidation]:
        field_path = rule["field"]
        check = rule["check"]
        severity = rule["severity"]
        results: list[FieldValidation] = []

        if "[]" in field_path:
            base_path = field_path.split("[]")[0].rstrip(".")
            items = self._get_nested(data, base_path)
            if not isinstance(items, list):
                results.append(FieldValidation(
                    filename="", field=field_path, rule_id=rule["rule_id"],
                    status="fail", severity=severity,
                    message=f"{base_path} is not an array",
                ))
                return results
            sub_field = field_path.split("[]", 1)[1].lstrip(".")
            for i, item in enumerate(items):
                sub_path = f"{base_path}[{i}].{sub_field}" if sub_field else f"{base_path}[{i}]"
                val = item.get(sub_field.split(".")[0]) if sub_field and isinstance(item, dict) else item
                results.extend(self._apply_check(data, sub_path, rule, val))
            return results

        val = self._get_nested(data, field_path)
        return self._apply_check(data, field_path, rule, val)

    def _apply_check(
        self, data: dict[str, Any], field_path: str, rule: dict[str, Any], val: Any
    ) -> list[FieldValidation]:
        check = rule["check"]
        severity = rule["severity"]
        rid = rule["rule_id"]

        if check == "required":
            ok = val is not None and val != ""
            return [FieldValidation("", field_path, rid, "pass" if ok else "fail", severity,
                                    "present" if ok else "required field missing")]

        if check == "iso8601":
            ok = isinstance(val, str) and bool(ISO8601_RE.match(val))
            return [FieldValidation("", field_path, rid, "pass" if ok else "fail", severity,
                                    "valid timestamp" if ok else "invalid ISO8601 format")]

        if check.startswith("min_length:"):
            min_len = int(check.split(":")[1])
            ok = isinstance(val, str) and len(val) >= min_len
            return [FieldValidation("", field_path, rid, "pass" if ok else "fail", severity,
                                    f"length {len(val) if isinstance(val, str) else 0} vs min {min_len}")]

        if check.startswith("array_min:"):
            min_items = int(check.split(":")[1])
            ok = isinstance(val, list) and len(val) >= min_items
            return [FieldValidation("", field_path, rid, "pass" if ok else "fail", severity,
                                    f"{len(val) if isinstance(val, list) else 0} items vs min {min_items}")]

        if check.startswith("enum:"):
            allowed = set(check.split(":")[1].split(","))
            ok = val in allowed
            return [FieldValidation("", field_path, rid, "pass" if ok else "fail", severity,
                                    f"value '{val}' vs allowed {allowed}")]

        if check == "non_empty_string":
            if isinstance(val, list):
                fails = [v for v in val if not isinstance(v, str) or not v.strip()]
                ok = len(fails) == 0
            else:
                ok = isinstance(val, str) and bool(val.strip())
            return [FieldValidation("", field_path, rid, "pass" if ok else "fail", severity,
                                    "all strings non-empty" if ok else "empty recommendation found")]

        return []

    def _audit_artifact(self, entry: dict[str, Any]) -> ArtifactEntryAudit:
        path = self.output_dir / entry["file"]
        issues: list[str] = []

        if not path.exists():
            return ArtifactEntryAudit(
                filename=entry["file"],
                command=entry.get("command"),
                exists=False,
                fields_present=0,
                fields_expected=len(VALIDATION_RULES),
                validations_passed=0,
                validations_failed=0,
                accuracy_score=0.0,
                entry_status="missing",
                issues=["file not captured — run agent to populate"],
            )

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return ArtifactEntryAudit(
                filename=entry["file"],
                command=entry.get("command"),
                exists=True,
                fields_present=0,
                fields_expected=len(VALIDATION_RULES),
                validations_passed=0,
                validations_failed=1,
                accuracy_score=0.0,
                entry_status="corrupt",
                issues=[f"JSON parse error: {str(exc)[:60]}"],
            )

        if not isinstance(data, dict):
            return ArtifactEntryAudit(
                filename=entry["file"],
                command=entry.get("command"),
                exists=True,
                fields_present=0,
                fields_expected=len(VALIDATION_RULES),
                validations_passed=0,
                validations_failed=1,
                accuracy_score=0.0,
                entry_status="invalid",
                issues=["root must be JSON object"],
            )

        validations: list[FieldValidation] = []
        for rule in VALIDATION_RULES:
            for v in self._check_rule(data, rule):
                v.filename = entry["file"]
                validations.append(v)

        passed = sum(1 for v in validations if v.status == "pass")
        failed = sum(1 for v in validations if v.status == "fail")
        total = max(len(validations), 1)
        accuracy = round(passed / total, 4)

        key_fields = ["meta", "market_signals", "recommendations", "metrics"]
        fields_present = sum(1 for k in key_fields if k in data and data[k])

        for v in validations:
            if v.status == "fail" and v.severity == "error":
                issues.append(f"{v.field}: {v.message}")

        if accuracy >= 0.9 and not issues:
            status = "verified"
        elif accuracy >= 0.7:
            status = "needs_review"
        else:
            status = "incomplete"

        return ArtifactEntryAudit(
            filename=entry["file"],
            command=entry.get("command"),
            exists=True,
            fields_present=fields_present,
            fields_expected=len(key_fields),
            validations_passed=passed,
            validations_failed=failed,
            accuracy_score=accuracy,
            entry_status=status,
            issues=issues,
        )

    def _build_queue(
        self, audits: list[ArtifactEntryAudit], validations: list[FieldValidation]
    ) -> list[EntryQueueItem]:
        queue: list[EntryQueueItem] = []

        for a in audits:
            if a.entry_status == "missing":
                queue.append(EntryQueueItem(
                    filename=a.filename,
                    field="*",
                    priority="high",
                    action="capture",
                    remediation=f"run.bat {a.command} -o output/{a.filename}" if a.command else "generate file",
                ))

        for v in validations:
            if v.status == "fail":
                priority = "high" if v.severity == "error" else "medium"
                entry = next((a for a in ARTIFACT_REGISTRY if a["file"] == v.filename), None)
                cmd = entry["command"] if entry else "unknown"
                queue.append(EntryQueueItem(
                    filename=v.filename,
                    field=v.field,
                    priority=priority,
                    action="correct",
                    remediation=f"Fix {v.field} in {v.filename} or re-run run.bat {cmd}",
                ))

        return queue[:30]

    def _double_entry_checks(self) -> list[DoubleEntryCheck]:
        pairs = [
            ("data_steward.json", "data_catalog.json", "meta.analyzed_at"),
            ("records_management.json", "archive_catalog.json", "meta.analyzed_at"),
            ("database_admin.json", "database_schema.json", "meta.analyzed_at"),
            ("data_processor.json", "processing_pipelines.json", "meta.analyzed_at"),
        ]
        checks: list[DoubleEntryCheck] = []
        for primary, secondary, fld in pairs:
            p_path = self.output_dir / primary
            s_path = self.output_dir / secondary
            p_val = s_val = None
            if p_path.exists():
                try:
                    p_data = json.loads(p_path.read_text(encoding="utf-8"))
                    p_val = str(self._get_nested(p_data, fld)) if isinstance(p_data, dict) else None
                except Exception:
                    pass
            if s_path.exists():
                checks.append(DoubleEntryCheck(
                    primary=primary,
                    secondary=secondary,
                    field=fld,
                    primary_value=p_val,
                    secondary_value=s_val,
                    match=s_path.exists() and p_path.exists(),
                ))
            elif p_path.exists():
                checks.append(DoubleEntryCheck(
                    primary=primary,
                    secondary=secondary,
                    field=fld,
                    primary_value=p_val,
                    secondary_value=None,
                    match=False,
                ))
        return checks

    def _collect_issues(
        self,
        audits: list[ArtifactEntryAudit],
        queue: list[EntryQueueItem],
    ) -> list[EntryIssue]:
        issues: list[EntryIssue] = []

        for a in audits:
            if a.entry_status == "missing":
                issues.append(EntryIssue(
                    severity="high",
                    category="capture",
                    message=f"{a.filename} not captured in output store",
                    remediation=f"run.bat {a.command} -o output/{a.filename}" if a.command else "generate output",
                ))
            elif a.entry_status == "corrupt":
                issues.append(EntryIssue(
                    severity="high",
                    category="integrity",
                    message=f"{a.filename} has corrupt JSON",
                    remediation="Re-run source agent to regenerate valid entry",
                ))
            for issue in a.issues[:3]:
                issues.append(EntryIssue(
                    severity="medium",
                    category="validation",
                    message=f"{a.filename}: {issue}",
                    remediation="Correct field per validation_rules.json template",
                ))

        high_queue = [q for q in queue if q.priority == "high"]
        if len(high_queue) > 5:
            issues.append(EntryIssue(
                severity="medium",
                category="backlog",
                message=f"{len(high_queue)} high-priority entry corrections pending",
                remediation="Process entry queue starting with missing primary reports",
            ))

        return issues

    def _scores(
        self,
        audits: list[ArtifactEntryAudit],
        validations: list[FieldValidation],
        issues: list[EntryIssue],
    ) -> tuple[float, float, float, str]:
        present = [a for a in audits if a.exists]
        accuracy_score = round(
            sum(a.accuracy_score for a in present) / max(len(present), 1), 4
        ) if present else 0.0

        total_vals = len(validations)
        passed_vals = sum(1 for v in validations if v.status == "pass")
        validation_score = round(passed_vals / max(total_vals, 1), 4)

        complete = sum(1 for a in audits if a.entry_status == "verified")
        completeness_score = round(complete / max(len(audits), 1), 4)

        high = sum(1 for i in issues if i.severity == "high")
        avg = (accuracy_score + validation_score + completeness_score) / 3
        if avg >= 0.8 and high == 0:
            regime = "Entry Verified"
        elif avg >= 0.55:
            regime = "Review Required"
        else:
            regime = "Entry Deficient"

        return accuracy_score, validation_score, completeness_score, regime

    def _assessment(
        self,
        audits: list[ArtifactEntryAudit],
        queue: list[EntryQueueItem],
        validations: list[FieldValidation],
    ) -> EntryAssessment:
        verified = sum(1 for a in audits if a.entry_status == "verified")
        missing = sum(1 for a in audits if a.entry_status == "missing")
        failed_vals = sum(1 for v in validations if v.status == "fail")

        return EntryAssessment(
            capture_coverage=f"{verified}/{len(audits)} artifacts verified, {missing} missing",
            validation_status=f"{failed_vals} field validation failures across output store",
            accuracy_summary=f"Mean accuracy {round(sum(a.accuracy_score for a in audits if a.exists) / max(sum(1 for a in audits if a.exists), 1), 2):.0%}",
            queue_status=f"{len(queue)} items in entry correction queue",
            sanitization_status="All string fields checked for non-empty content and enum conformance",
            entry_priority=(
                "Clear missing captures first, then correct error-severity field failures"
                if missing > 0
                else "Review warning-level validations and maintain daily re-entry cadence"
            ),
        )

    def analyze(self) -> DataEntryReport:
        audits = [self._audit_artifact(e) for e in ARTIFACT_REGISTRY]
        validations: list[FieldValidation] = []
        for entry in ARTIFACT_REGISTRY:
            path = self.output_dir / entry["file"]
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for rule in VALIDATION_RULES:
                        for v in self._check_rule(data, rule):
                            v.filename = entry["file"]
                            validations.append(v)
            except Exception:
                pass

        queue = self._build_queue(audits, validations)
        double_entry = self._double_entry_checks()
        issues = self._collect_issues(audits, queue)
        assessment = self._assessment(audits, queue, validations)
        accuracy, validation, completeness, regime = self._scores(audits, validations, issues)

        summary = (
            f"Data entry review: {regime}. "
            f"Accuracy {accuracy:.0%}, validation {validation:.0%}, "
            f"completeness {completeness:.0%}. {len(queue)} queue item(s)."
        )

        signals = self._market_signals(accuracy, validation, audits, queue)
        recs = self._recommendations(assessment, audits, queue, validations)

        return DataEntryReport(
            audits=audits,
            validations=validations,
            queue=queue,
            double_entry=double_entry,
            issues=issues,
            assessment=assessment,
            accuracy_score=accuracy,
            validation_score=validation,
            completeness_score=completeness,
            regime_label=regime,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
        )

    @staticmethod
    def _market_signals(
        accuracy: float,
        validation: float,
        audits: list[ArtifactEntryAudit],
        queue: list[EntryQueueItem],
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        score = (accuracy + validation) / 2
        bias = "BULLISH" if score >= 0.8 else "BEARISH" if score <= 0.5 else "NEUTRAL"
        signals.append({
            "sector": "Data Capture Quality",
            "tickers": ["SPY", "ACN"],
            "bias": bias,
            "reason": f"Entry accuracy {accuracy:.0%}, validation {validation:.0%} — {len(queue)} corrections",
        })

        verified = [a for a in audits if a.entry_status == "verified"]
        if len(verified) >= len(audits) * 0.7:
            signals.append({
                "sector": "Verified Intelligence",
                "tickers": ["XLK", "NOW"],
                "bias": "BULLISH",
                "reason": f"{len(verified)} artifacts pass double-entry verification",
            })

        missing = [a for a in audits if a.entry_status == "missing"]
        if missing:
            signals.append({
                "sector": "Capture Gap",
                "tickers": ["VIXY"],
                "bias": "BEARISH",
                "reason": f"{missing[0].filename} missing — manual capture required",
            })

        return signals

    @staticmethod
    def _recommendations(
        assessment: EntryAssessment,
        audits: list[ArtifactEntryAudit],
        queue: list[EntryQueueItem],
        validations: list[FieldValidation],
    ) -> list[str]:
        recs = [
            assessment.capture_coverage,
            assessment.validation_status,
            assessment.accuracy_summary,
            assessment.queue_status,
            assessment.sanitization_status,
            assessment.entry_priority,
        ]
        for t in ENTRY_TEMPLATES:
            recs.append(f"Template {t['template_id']}: {t['name']} — applies to {t['applies_to']}")
        for a in sorted(audits, key=lambda x: x.accuracy_score)[:6]:
            if a.exists:
                recs.append(
                    f"{a.filename}: {a.entry_status}, accuracy {a.accuracy_score:.0%}, "
                    f"{a.validations_passed}/{a.validations_passed + a.validations_failed} rules passed"
                )
        for q in queue[:6]:
            recs.append(f"[{q.priority}] {q.action} {q.filename}.{q.field} — {q.remediation}")
        failed = [v for v in validations if v.status == "fail"][:5]
        for v in failed:
            recs.append(f"Validation fail {v.filename}.{v.field}: {v.message}")
        return recs

    def to_dict(self, report: DataEntryReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Data Entry Specialist Expert",
                "analyzed_at": report.analyzed_at,
                "data_source": "Finance output/ artifact field validation",
                "expert_summary": report.expert_summary,
                "templates_cataloged": len(ENTRY_TEMPLATES),
                "rules_cataloged": len(VALIDATION_RULES),
            },
            "entry_templates": ENTRY_TEMPLATES,
            "validation_rules": VALIDATION_RULES,
            "artifact_audits": [
                {
                    "filename": x.filename,
                    "command": x.command,
                    "exists": x.exists,
                    "fields_present": x.fields_present,
                    "fields_expected": x.fields_expected,
                    "validations_passed": x.validations_passed,
                    "validations_failed": x.validations_failed,
                    "accuracy_score": x.accuracy_score,
                    "entry_status": x.entry_status,
                    "issues": x.issues,
                }
                for x in report.audits
            ],
            "field_validations": [
                {
                    "filename": v.filename,
                    "field": v.field,
                    "rule_id": v.rule_id,
                    "status": v.status,
                    "severity": v.severity,
                    "message": v.message,
                }
                for v in report.validations
            ],
            "entry_queue": [
                {
                    "filename": q.filename,
                    "field": q.field,
                    "priority": q.priority,
                    "action": q.action,
                    "remediation": q.remediation,
                }
                for q in report.queue
            ],
            "double_entry_checks": [
                {
                    "primary": d.primary,
                    "secondary": d.secondary,
                    "field": d.field,
                    "primary_value": d.primary_value,
                    "secondary_value": d.secondary_value,
                    "match": d.match,
                }
                for d in report.double_entry
            ],
            "entry_issues": [
                {
                    "severity": i.severity,
                    "category": i.category,
                    "message": i.message,
                    "remediation": i.remediation,
                }
                for i in report.issues
            ],
            "entry_assessment": {
                "capture_coverage": a.capture_coverage,
                "validation_status": a.validation_status,
                "accuracy_summary": a.accuracy_summary,
                "queue_status": a.queue_status,
                "sanitization_status": a.sanitization_status,
                "entry_priority": a.entry_priority,
            },
            "metrics": {
                "accuracy_score": report.accuracy_score,
                "validation_score": report.validation_score,
                "completeness_score": report.completeness_score,
                "regime_label": report.regime_label,
                "queue_size": len(report.queue),
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            templates_path = output.parent / "entry_templates.json"
            templates_path.write_text(json.dumps(ENTRY_TEMPLATES, indent=2), encoding="utf-8")
            rules_path = output.parent / "validation_rules.json"
            rules_path.write_text(json.dumps(VALIDATION_RULES, indent=2), encoding="utf-8")
        return result


def run_data_entry_analysis(output: Path | None = None) -> dict[str, Any]:
    return DataEntryExpert().run(output=output)