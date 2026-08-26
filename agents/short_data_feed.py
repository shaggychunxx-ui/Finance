"""Real short-interest / CTB / Reg SHO feeds.

Yahoo vol proxies are not borrow fees. These agents stay silent until a
file or env-backed feed is present, then turn back on automatically.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app_paths import OUTPUT, ROOT

FEED_ENV = "FINANCE_SHORT_FEED"
KEY_ENVS = ("FINANCE_IBORROW_KEY", "IBORROWDESK_API_KEY", "FINANCE_S3_KEY")
DEFAULT_FILES = (
    OUTPUT / "short_borrow_feed.json",
    ROOT / "config" / "short_borrow_feed.json",
    OUTPUT / "finra_threshold.json",
)


def _fresh(path: Path, *, max_age_hours: float = 72.0) -> bool:
    try:
        age = (datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) / 3600.0
    except OSError:
        return False
    return 0 <= age <= max_age_hours


def short_feed_status() -> dict[str, Any]:
    env_path = str(os.environ.get(FEED_ENV) or "").strip()
    if env_path:
        p = Path(env_path)
        if p.is_file():
            return {
                "available": True,
                "kind": "file",
                "path": str(p),
                "resume": "",
            }
    for key in KEY_ENVS:
        if str(os.environ.get(key) or "").strip():
            return {
                "available": True,
                "kind": "api",
                "path": key,
                "resume": "",
            }
    for path in DEFAULT_FILES:
        if path.is_file() and _fresh(path):
            return {
                "available": True,
                "kind": "file",
                "path": str(path),
                "resume": "",
            }
    return {
        "available": False,
        "kind": "none",
        "path": "",
        "resume": (
            "Auto-on when FINANCE_SHORT_FEED points at a JSON file, "
            "or output/short_borrow_feed.json / output/finra_threshold.json is present, "
            "or FINANCE_IBORROW_KEY is set."
        ),
    }


def load_short_feed_rows() -> list[dict[str, Any]]:
    st = short_feed_status()
    if not st["available"] or st["kind"] != "file":
        return []
    try:
        raw = json.loads(Path(st["path"]).read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    if isinstance(raw, dict):
        rows = raw.get("rows") or raw.get("symbols") or raw.get("data")
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
        out = []
        for sym, payload in raw.items():
            if sym in {"updated_at", "source", "ok"}:
                continue
            if isinstance(payload, dict):
                row = dict(payload)
                row.setdefault("symbol", sym)
                out.append(row)
        return out
    return []


def unavailable_payload(agent_id: str, *, label: str) -> dict[str, Any]:
    st = short_feed_status()
    return {
        "meta": {
            "agent": label,
            "agent_id": agent_id,
            "feed_available": False,
            "feed_status": st,
            "expert_summary": (
                f"{label} is silent: no real CTB/HTB/Reg SHO feed. "
                f"{st.get('resume') or ''}"
            ),
        },
        "summary": {"feed_available": False, "auto_resume": st.get("resume")},
        "symbols": [],
        "market_signals": [],
        "recommendations": [
            "No Yahoo-vol proxy for borrow fees / HTB / FTD.",
            str(st.get("resume") or ""),
        ],
        "data_source": "none",
    }
