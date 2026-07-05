"""Agent report freshness helpers for the Agents UI."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from app_paths import OUTPUT


def agent_mtime(agent: dict[str, str], *, output_dir: Path = OUTPUT) -> float:
    path = output_dir / agent["output"]
    try:
        return path.stat().st_mtime if path.exists() else 0.0
    except OSError:
        return 0.0


def agent_age_info(agent: dict[str, str], *, output_dir: Path = OUTPUT) -> tuple[str, str, str]:
    path = output_dir / agent["output"]
    if not path.exists():
        return "none", "—", "none"
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        age_s = max(0.0, (datetime.now() - mtime).total_seconds())
        age_h = age_s / 3600
        if age_h < 1:
            age_m = int(age_s / 60)
            label = "just now" if age_m < 1 else f"{age_m}m ago"
        elif age_h < 24:
            label = f"{int(age_h)}h ago"
        else:
            label = f"{int(age_h / 24)}d ago"
        if age_h < 6:
            return "fresh", label, "fresh"
        if age_h < 24:
            return "stale", label, "stale"
        return "old", label, "old"
    except OSError:
        return "old", "?", "old"


def agent_status(agent: dict[str, str], *, output_dir: Path = OUTPUT) -> str:
    bucket, _, _ = agent_age_info(agent, output_dir=output_dir)
    return {"fresh": "Fresh", "stale": "Stale", "old": "Old"}.get(bucket, "—")


def fresh_report_counts(catalog: list[dict[str, Any]], *, output_dir: Path = OUTPUT) -> tuple[int, int]:
    fresh = sum(1 for agent in catalog if agent_status(agent, output_dir=output_dir) == "Fresh")
    return fresh, len(catalog)