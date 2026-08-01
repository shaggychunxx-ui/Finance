#!/usr/bin/env python3
"""Durable journal of walk-forward backtest trials for agent learning.

Night continuous full-day runs append rows here so learning can use more than
aggregate leaderboard percentages.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app_paths import OUTPUT

HISTORY_ROOT = OUTPUT / "history"
TRIALS_DIR = HISTORY_ROOT / "backtest_trials"
LATEST_FILE = TRIALS_DIR / "latest_cycle.json"
INDEX_FILE = TRIALS_DIR / "index.json"
JSONL_FILE = TRIALS_DIR / "trials.jsonl"

# Keep journal bounded for disk / rebuild speed
MAX_JSONL_LINES = 80_000
MAX_CYCLE_TRIALS = 12_000
MAX_INDEX_ENTRIES = 60


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def new_cycle_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"bt{stamp}_{uuid.uuid4().hex[:6]}"


def trial_to_row(trial: Any, *, cycle_id: str) -> dict[str, Any]:
    """Normalize SimTrial dataclass or dict into a journal row."""
    if isinstance(trial, dict):
        row = dict(trial)
    else:
        row = {
            "agent_id": getattr(trial, "agent_id", ""),
            "symbol": getattr(trial, "symbol", ""),
            "horizon": getattr(trial, "horizon", ""),
            "predicted_direction": getattr(trial, "predicted_direction", ""),
            "actual_direction": getattr(trial, "actual_direction", ""),
            "predicted_return_pct": getattr(trial, "predicted_return_pct", None),
            "actual_return_pct": getattr(trial, "actual_return_pct", None),
            "hit": bool(getattr(trial, "hit", False)),
            "confidence": getattr(trial, "confidence", None),
            "source": getattr(trial, "source", ""),
            "simulated_at": getattr(trial, "simulated_at", ""),
        }
    row["cycle_id"] = cycle_id
    row["agent_id"] = str(row.get("agent_id") or "")
    row["symbol"] = str(row.get("symbol") or "").upper()
    row["horizon"] = str(row.get("horizon") or "")
    row["predicted_direction"] = str(row.get("predicted_direction") or "flat").lower()
    row["actual_direction"] = str(row.get("actual_direction") or "flat").lower()
    row["hit"] = bool(row.get("hit"))
    return row


def append_trials(
    trials: Iterable[Any],
    *,
    cycle_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist a backtest cycle's trials (JSONL + latest snapshot + index)."""
    TRIALS_DIR.mkdir(parents=True, exist_ok=True)
    cid = cycle_id or new_cycle_id()
    rows = [trial_to_row(t, cycle_id=cid) for t in trials]
    if len(rows) > MAX_CYCLE_TRIALS:
        # Prefer keeping a stride sample rather than only the tail.
        stride = max(1, len(rows) // MAX_CYCLE_TRIALS)
        rows = rows[::stride][:MAX_CYCLE_TRIALS]

    cycle_payload = {
        "cycle_id": cid,
        "written_at": _now_iso(),
        "trial_count": len(rows),
        "meta": meta or {},
        "trials": rows,
    }
    _write_json(LATEST_FILE, cycle_payload)

    # Append JSONL
    with JSONL_FILE.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    _trim_jsonl()

    index = _load_json(INDEX_FILE)
    if not isinstance(index, dict):
        index = {"cycles": []}
    cycles = list(index.get("cycles") or [])
    cycles.append(
        {
            "cycle_id": cid,
            "written_at": cycle_payload["written_at"],
            "trial_count": len(rows),
            "meta": meta or {},
        }
    )
    index["cycles"] = cycles[-MAX_INDEX_ENTRIES:]
    index["updated_at"] = _now_iso()
    index["jsonl_path"] = str(JSONL_FILE.name)
    _write_json(INDEX_FILE, index)
    return cycle_payload


def _trim_jsonl() -> None:
    if not JSONL_FILE.exists():
        return
    try:
        lines = JSONL_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) <= MAX_JSONL_LINES:
        return
    keep = lines[-MAX_JSONL_LINES:]
    JSONL_FILE.write_text("\n".join(keep) + "\n", encoding="utf-8")


def load_recent_trials(
    *,
    max_rows: int = 20_000,
    agent_id: str | None = None,
    prefer_latest_cycle: bool = True,
) -> list[dict[str, Any]]:
    """Load trials for learning rebuild (latest cycle first, then JSONL)."""
    rows: list[dict[str, Any]] = []
    if prefer_latest_cycle and LATEST_FILE.exists():
        latest = _load_json(LATEST_FILE)
        if isinstance(latest, dict):
            for row in latest.get("trials") or []:
                if isinstance(row, dict):
                    rows.append(row)
    if len(rows) < max_rows and JSONL_FILE.exists():
        try:
            lines = JSONL_FILE.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for line in lines[-max_rows:]:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    # Dedupe by coarse key (cycle, agent, symbol, horizon, simulated_at)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in reversed(rows):
        key = "|".join(
            [
                str(row.get("cycle_id") or ""),
                str(row.get("agent_id") or ""),
                str(row.get("symbol") or ""),
                str(row.get("horizon") or ""),
                str(row.get("simulated_at") or ""),
                str(row.get("predicted_direction") or ""),
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        if agent_id and str(row.get("agent_id") or "") != agent_id:
            continue
        out.append(row)
        if len(out) >= max_rows:
            break
    out.reverse()
    return out


def load_latest_cycle_meta() -> dict[str, Any]:
    latest = _load_json(LATEST_FILE)
    if not isinstance(latest, dict):
        return {}
    return {
        "cycle_id": latest.get("cycle_id"),
        "written_at": latest.get("written_at"),
        "trial_count": latest.get("trial_count"),
        "meta": latest.get("meta") or {},
    }
