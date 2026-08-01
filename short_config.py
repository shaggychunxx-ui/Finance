#!/usr/bin/env python3
"""Load short-trader config. API always follows long etrade_config.json."""

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
    # Keep API fields mirrored from long whenever short config is touched.
    try:
        from shared_etrade_api import mirror_shared_api_into_short

        mirror_shared_api_into_short(short_path=SHORT_CONFIG)
    except Exception:
        pass
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
    # Never persist a divergent API — force shared fields from long first.
    try:
        from shared_etrade_api import shared_api_fields_from_long

        for key, value in shared_api_fields_from_long().items():
            data[key] = value
        data["shared_api_from"] = "etrade_config.json"
        data["inherit_credentials_from"] = "etrade_config.json"
    except Exception:
        data.setdefault("shared_api_from", "etrade_config.json")
        data.setdefault("inherit_credentials_from", "etrade_config.json")
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _merge_shared_api(raw: dict[str, Any]) -> dict[str, Any]:
    """Force short runtime view to use long's API credentials/account/sandbox."""
    try:
        from shared_etrade_api import shared_api_fields_from_long

        api = shared_api_fields_from_long()
    except Exception:
        api = {}
        # Fallback: optional legacy inherit if shared module fails
        inherit = raw.get("inherit_credentials_from") or raw.get("shared_api_from") or "etrade_config.json"
        parent = SHORT_CONFIG.parent / str(inherit)
        if parent.exists():
            try:
                long_raw = json.loads(parent.read_text(encoding="utf-8"))
                if isinstance(long_raw, dict):
                    for key in (
                        "consumer_key",
                        "consumer_secret",
                        "token_path",
                        "callback_url",
                        "use_oob",
                        "sandbox",
                        "selected_account",
                    ):
                        if key in long_raw:
                            api[key] = long_raw[key]
            except (json.JSONDecodeError, OSError):
                pass

    out = dict(raw)
    for key, value in api.items():
        out[key] = value
    out["shared_api_from"] = "etrade_config.json"
    out["inherit_credentials_from"] = "etrade_config.json"
    return out


def load_merged_short_config(path: Path | None = None) -> dict[str, Any]:
    """Short strategy + worker settings, with **shared** API fields from long."""
    raw = read_short_config_raw(path)
    return _merge_shared_api(raw)


def worker_settings(path: Path | None = None) -> dict[str, Any]:
    """Short sleeve worker flags — dry_run / auto_execute are independent of long."""
    defaults = {
        "auto_execute": False,
        "live_trading": False,
        "day_trading": True,
        "paused": False,
        "dry_run": True,
        # Keep practice fills on a timer even when live sizing produces 0 orders.
        "schedule_dry_run": True,
        "dry_run_interval_minutes": 20,
        "dry_run_force_min_share": True,
        "dry_run_max_names": 5,
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
    """Account always comes from the shared (long) API config."""
    try:
        from shared_etrade_api import get_shared_selected_account

        sel = get_shared_selected_account()
        if sel:
            return sel
    except Exception:
        pass
    raw = load_merged_short_config(path)
    sel = raw.get("selected_account") or {}
    if not sel.get("account_id_key"):
        return None
    return sel
