#!/usr/bin/env python3
"""Load short-trader config, optionally inheriting long-app credentials."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from short_paths import SHORT_CONFIG, SHORT_CONFIG_EXAMPLE, ensure_short_dirs


def ensure_short_config() -> Path:
    ensure_short_dirs()
    if not SHORT_CONFIG.exists() and SHORT_CONFIG_EXAMPLE.exists():
        shutil.copy2(SHORT_CONFIG_EXAMPLE, SHORT_CONFIG)
    return SHORT_CONFIG


def read_short_config_raw(path: Path | None = None) -> dict[str, Any]:
    path = path or ensure_short_config()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def write_short_config_raw(data: dict[str, Any], path: Path | None = None) -> None:
    path = path or SHORT_CONFIG
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _merge_inherited_credentials(raw: dict[str, Any]) -> dict[str, Any]:
    """Fill empty API keys / account from long etrade_config.json when requested."""
    inherit = raw.get("inherit_credentials_from") or "etrade_config.json"
    if not inherit:
        return raw
    parent = SHORT_CONFIG.parent / str(inherit)
    if not parent.exists():
        return raw
    try:
        long_raw = json.loads(parent.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return raw
    if not isinstance(long_raw, dict):
        return raw
    out = dict(raw)
    for key in ("consumer_key", "consumer_secret", "token_path", "callback_url", "use_oob"):
        val = out.get(key)
        if not val or str(val).startswith("YOUR_"):
            if long_raw.get(key):
                out[key] = long_raw[key]
    # Prefer explicit sandbox in short config; else inherit
    if "sandbox" not in out and "sandbox" in long_raw:
        out["sandbox"] = long_raw["sandbox"]
    sel = out.get("selected_account") or {}
    if not sel.get("account_id_key"):
        long_sel = long_raw.get("selected_account") or {}
        if long_sel.get("account_id_key"):
            out["selected_account"] = dict(long_sel)
    return out


def load_merged_short_config(path: Path | None = None) -> dict[str, Any]:
    raw = read_short_config_raw(path)
    return _merge_inherited_credentials(raw)


def worker_settings(path: Path | None = None) -> dict[str, Any]:
    defaults = {
        "auto_execute": False,
        "live_trading": False,
        "day_trading": True,
        "paused": False,
        "dry_run": True,
        "pipeline_interval_minutes": 5,
        "plan_interval_minutes": 30,
        "execute_min_interval_minutes": 20,
        "day_trading_interval_minutes": 5,
        "allow_off_hours_trading": False,
        "reuse_long_agent_pipeline": True,
    }
    raw = load_merged_short_config(path)
    user = raw.get("background_worker") or {}
    if isinstance(user, dict):
        defaults.update({k: user[k] for k in user})
    return defaults


def get_selected_account(path: Path | None = None) -> dict[str, Any] | None:
    raw = load_merged_short_config(path)
    sel = raw.get("selected_account") or {}
    if not sel.get("account_id_key"):
        return None
    return sel
