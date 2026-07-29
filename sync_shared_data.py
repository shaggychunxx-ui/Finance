#!/usr/bin/env python3
"""Sync Finance output/ artifacts over the dual-PC SMB share.

BOXONE (pipeline role)
  push_pipeline_artifacts  →  \\\\host\\FinanceShare\\pipeline\\
  pull_broker_feed         ←  \\\\host\\FinanceShare\\broker\\

AI-CODING (broker role)
  pull_pipeline_artifacts  ←  \\\\host\\FinanceShare\\pipeline\\
  push_broker_feed         →  \\\\host\\FinanceShare\\broker\\
"""

from __future__ import annotations

import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app_paths import OUTPUT, ROOT
from deployment import (
    BROKER_OWNED_NAMES,
    PIPELINE_SKIP_DIR_NAMES,
    ensure_shared_layout,
    load_deployment,
    shared_broker_dir,
    shared_pipeline_dir,
)

STATUS_NAME = "_sync_status.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_status(folder: Path, *, role: str, action: str, files: int, error: str | None = None) -> None:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        payload = {
            "role": role,
            "action": action,
            "files": files,
            "error": error,
            "updated_at": _utc_now(),
            "host_output": str(OUTPUT),
        }
        (folder / STATUS_NAME).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass


def _should_skip_pipeline_file(rel: Path) -> bool:
    name = rel.name
    if name in BROKER_OWNED_NAMES or name == STATUS_NAME:
        return True
    if name.startswith(".") or name.endswith(".lock"):
        return True
    if name.endswith(".log"):
        return True
    if name.endswith(".pyc"):
        return True
    # Keep secrets out of the share even if someone mis-copied them into output/
    lower = name.lower()
    if "token" in lower or lower in {"etrade_config.json", "short_etrade_config.json", "config.json"}:
        return True
    parts = set(rel.parts)
    if parts & PIPELINE_SKIP_DIR_NAMES:
        return True
    # history/ holds trade journals owned by broker
    if "history" in rel.parts:
        return True
    # Large snapshot trees and temp dirs should never cross the share
    for part in rel.parts:
        low = str(part).lower()
        if low in {"archive", "snapshots", "_agent_tmp", "__pycache__", ".venv"}:
            return True
    return False


def _iter_files(src_root: Path) -> list[Path]:
    if not src_root.is_dir():
        return []
    return [p for p in src_root.rglob("*") if p.is_file()]


def _copy_file(src: Path, dst: Path) -> bool:
    """Copy if missing or source newer. Returns True if copied."""
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            if src.stat().st_mtime <= dst.stat().st_mtime + 0.001:
                if src.stat().st_size == dst.stat().st_size:
                    return False
        shutil.copy2(src, dst)
        return True
    except OSError:
        return False


def push_pipeline_artifacts(
    *,
    output_dir: Path | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """BOXONE → share/pipeline (agent research + status)."""
    layout = ensure_shared_layout(config_path)
    if not layout.get("ok"):
        return {"ok": False, "error": layout.get("error"), "copied": 0}
    dest_root = shared_pipeline_dir(config_path)
    src_root = output_dir or OUTPUT
    if dest_root is None or not src_root.is_dir():
        return {"ok": False, "error": "missing paths", "copied": 0}

    copied = 0
    considered = 0
    for src in _iter_files(src_root):
        rel = src.relative_to(src_root)
        if _should_skip_pipeline_file(rel):
            continue
        considered += 1
        if _copy_file(src, dest_root / rel):
            copied += 1

    # Compact pipeline status for the UI (always refresh)
    status = {
        "source": "pipeline",
        "pushed_at": _utc_now(),
        "files_considered": considered,
        "files_copied": copied,
        "host": str(ROOT),
    }
    try:
        state_path = src_root / "etrade_worker_state.json"
        if state_path.exists():
            status["worker_state"] = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    try:
        (dest_root / "pipeline_status.json").write_text(
            json.dumps(status, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        return {"ok": False, "error": str(exc), "copied": copied}

    _write_status(dest_root, role="pipeline", action="push", files=copied)
    return {"ok": True, "copied": copied, "considered": considered, "dest": str(dest_root)}


def pull_pipeline_artifacts(
    *,
    output_dir: Path | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """share/pipeline → AI-CODING local output (research only)."""
    layout = ensure_shared_layout(config_path)
    if not layout.get("ok"):
        return {"ok": False, "error": layout.get("error"), "copied": 0}
    src_root = shared_pipeline_dir(config_path)
    dest_root = output_dir or OUTPUT
    if src_root is None or not src_root.is_dir():
        return {"ok": False, "error": "pipeline share not reachable", "copied": 0}

    dest_root.mkdir(parents=True, exist_ok=True)
    copied = 0
    considered = 0
    for src in _iter_files(src_root):
        rel = src.relative_to(src_root)
        if rel.name in {STATUS_NAME, "pipeline_status.json"}:
            # Still copy pipeline_status for UI
            if rel.name == "pipeline_status.json":
                if _copy_file(src, dest_root / rel):
                    copied += 1
            continue
        if _should_skip_pipeline_file(rel):
            continue
        # Never clobber broker-owned local files
        if (dest_root / rel).name in BROKER_OWNED_NAMES:
            continue
        considered += 1
        if _copy_file(src, dest_root / rel):
            copied += 1

    _write_status(dest_root, role="broker", action="pull_pipeline", files=copied)
    return {"ok": True, "copied": copied, "considered": considered, "src": str(src_root)}


def push_broker_feed(
    *,
    output_dir: Path | None = None,
    config_path: Path | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """AI-CODING → share/broker (quotes + account snapshot)."""
    layout = ensure_shared_layout(config_path)
    if not layout.get("ok"):
        return {"ok": False, "error": layout.get("error"), "copied": 0}
    dest_root = shared_broker_dir(config_path)
    src_root = output_dir or OUTPUT
    if dest_root is None:
        return {"ok": False, "error": "broker share path missing", "copied": 0}

    dest_root.mkdir(parents=True, exist_ok=True)
    names = (
        "etrade_enhanced_quotes.json",
        "account_snapshot.json",
        "quote_requests.json",
    )
    copied = 0
    for name in names:
        src = src_root / name
        if src.is_file() and _copy_file(src, dest_root / name):
            copied += 1

    meta = {
        "source": "broker",
        "pushed_at": _utc_now(),
        "files_copied": copied,
        "host": str(ROOT),
    }
    if extra:
        meta["extra"] = extra
    try:
        (dest_root / "broker_status.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": str(exc), "copied": copied}

    _write_status(dest_root, role="broker", action="push", files=copied)
    return {"ok": True, "copied": copied, "dest": str(dest_root)}


def pull_broker_feed(
    *,
    output_dir: Path | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """share/broker → BOXONE local output (quotes for agents)."""
    layout = ensure_shared_layout(config_path)
    if not layout.get("ok"):
        return {"ok": False, "error": layout.get("error"), "copied": 0}
    src_root = shared_broker_dir(config_path)
    dest_root = output_dir or OUTPUT
    if src_root is None or not src_root.is_dir():
        return {"ok": False, "error": "broker share not reachable", "copied": 0}

    dest_root.mkdir(parents=True, exist_ok=True)
    names = (
        "etrade_enhanced_quotes.json",
        "account_snapshot.json",
        "broker_status.json",
    )
    copied = 0
    for name in names:
        src = src_root / name
        if src.is_file() and _copy_file(src, dest_root / name):
            copied += 1

    _write_status(dest_root, role="pipeline", action="pull_broker", files=copied)
    return {"ok": True, "copied": copied, "src": str(src_root)}


def sync_for_role(
    role_name: str,
    *,
    config_path: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """One-shot sync appropriate for the machine role."""
    role_name = (role_name or "all").lower()
    results: dict[str, Any] = {"role": role_name, "at": _utc_now()}
    if role_name in {"pipeline", "all"}:
        results["pull_broker"] = pull_broker_feed(output_dir=output_dir, config_path=config_path)
        results["push_pipeline"] = push_pipeline_artifacts(
            output_dir=output_dir, config_path=config_path
        )
    if role_name in {"broker", "all"}:
        results["pull_pipeline"] = pull_pipeline_artifacts(
            output_dir=output_dir, config_path=config_path
        )
        results["push_broker"] = push_broker_feed(output_dir=output_dir, config_path=config_path)
    return results


def main() -> int:
    import argparse

    from deployment import role as deploy_role

    parser = argparse.ArgumentParser(description="Sync Finance dual-PC shared data")
    parser.add_argument(
        "--role",
        choices=["all", "pipeline", "broker", "auto"],
        default="auto",
        help="Which direction to sync (auto = deployment.role)",
    )
    parser.add_argument("--push-pipeline", action="store_true")
    parser.add_argument("--pull-pipeline", action="store_true")
    parser.add_argument("--push-broker", action="store_true")
    parser.add_argument("--pull-broker", action="store_true")
    args = parser.parse_args()

    specific = args.push_pipeline or args.pull_pipeline or args.push_broker or args.pull_broker
    if specific:
        out: dict[str, Any] = {}
        if args.push_pipeline:
            out["push_pipeline"] = push_pipeline_artifacts()
        if args.pull_pipeline:
            out["pull_pipeline"] = pull_pipeline_artifacts()
        if args.push_broker:
            out["push_broker"] = push_broker_feed()
        if args.pull_broker:
            out["pull_broker"] = pull_broker_feed()
        print(json.dumps(out, indent=2))
        return 0

    r = deploy_role() if args.role == "auto" else args.role
    result = sync_for_role(r)
    print(json.dumps(result, indent=2))
    ok = True
    for key, val in result.items():
        if isinstance(val, dict) and val.get("ok") is False:
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
