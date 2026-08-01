#!/usr/bin/env python3
"""Single E*TRADE API source of truth for long + short sleeves.

Both sleeves talk to the **same** brokerage API:

- Credentials (`consumer_key` / `consumer_secret`)
- Environment (`sandbox` vs production base URL)
- OAuth tokens (`token_path` / `etrade_tokens.json`)
- Selected account (`selected_account`)

Live only in ``etrade_config.json``. Short strategy knobs stay in
``short_etrade_config.json``.

**Practice mode is independent per sleeve** via each file's
``background_worker.dry_run`` — long can be live while short stays in
practice (or the reverse).

E*TRADE Trader **phone app** summary: ``feature_snapshot()`` (via phone_bridge
``/api/dashboard`` + ``/api/features``). Not the GitStatus phone bus.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from app_paths import ROOT
from etrade_api.config import (
    DEFAULT_CONFIG_PATH,
    ETradeConfig,
    get_selected_account,
    load_config,
    read_config_raw,
    save_selected_account,
    write_config_raw,
)

SleeveName = Literal["long", "short"]

LONG_CONFIG_PATH = ROOT / "etrade_config.json"
SHORT_CONFIG_PATH = ROOT / "short_etrade_config.json"

# Fields that must never diverge between sleeves — always read from long config.
SHARED_API_FIELDS = (
    "consumer_key",
    "consumer_secret",
    "sandbox",
    "token_path",
    "callback_url",
    "use_oob",
    "selected_account",
)


def long_config_path() -> Path:
    return LONG_CONFIG_PATH if LONG_CONFIG_PATH.exists() else DEFAULT_CONFIG_PATH


def short_config_path() -> Path:
    return SHORT_CONFIG_PATH


def sleeve_config_path(sleeve: SleeveName) -> Path:
    return long_config_path() if sleeve == "long" else short_config_path()


def read_long_raw() -> dict[str, Any]:
    return read_config_raw(long_config_path())


def read_short_raw() -> dict[str, Any]:
    path = short_config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def write_short_raw(data: dict[str, Any]) -> None:
    path = short_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_shared_api_config(path: Path | None = None) -> ETradeConfig:
    """Load the one E*TRADE API config both sleeves must use."""
    return load_config(path or long_config_path())


def get_shared_selected_account(path: Path | None = None) -> dict[str, Any] | None:
    return get_selected_account(path or long_config_path())


def save_shared_selected_account(
    account_id_key: str,
    *,
    display_label: str = "",
    account_opened_at: str | None = None,
) -> None:
    """Persist account on long config and mirror onto short for display."""
    save_selected_account(
        account_id_key,
        display_label=display_label,
        account_opened_at=account_opened_at,
        path=long_config_path(),
    )
    mirror_shared_api_into_short()


def shared_api_fields_from_long(long_raw: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = long_raw if long_raw is not None else read_long_raw()
    out: dict[str, Any] = {}
    for key in SHARED_API_FIELDS:
        if key in raw:
            out[key] = raw[key]
    return out


def mirror_shared_api_into_short(*, short_path: Path | None = None) -> dict[str, Any]:
    """Copy shared API fields into short config (display/compat only).

    Runtime always loads the API from long config; this keeps the short
    file from showing stale keys/sandbox/account in editors.
    """
    path = short_path or short_config_path()
    long_raw = read_long_raw()
    if not long_raw:
        return read_short_raw() if path.exists() else {}

    short_raw: dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                short_raw = data
        except (json.JSONDecodeError, OSError):
            short_raw = {}

    changed = False
    for key, value in shared_api_fields_from_long(long_raw).items():
        if short_raw.get(key) != value:
            short_raw[key] = value
            changed = True

    # Mark short as API-follower (no independent credentials).
    if short_raw.get("shared_api_from") != "etrade_config.json":
        short_raw["shared_api_from"] = "etrade_config.json"
        changed = True
    if short_raw.get("inherit_credentials_from") != "etrade_config.json":
        short_raw["inherit_credentials_from"] = "etrade_config.json"
        changed = True

    if changed or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(short_raw, indent=2), encoding="utf-8")
    return short_raw


def connect_shared_client():
    """Build one ETradeClient from long API config + shared tokens."""
    from etrade_api.client import ETradeClient
    from etrade_api.oauth import load_tokens

    cfg = load_shared_api_config()
    tokens = load_tokens(cfg.token_path, cfg.sandbox)
    if not tokens:
        return None
    return ETradeClient(cfg, tokens)


def _worker_block(raw: dict[str, Any]) -> dict[str, Any]:
    worker = raw.get("background_worker")
    return dict(worker) if isinstance(worker, dict) else {}


def sleeve_practice_mode(sleeve: SleeveName) -> bool:
    """Independent practice (dry_run) flag for long or short."""
    if sleeve == "long":
        worker = _worker_block(read_long_raw())
        return bool(worker.get("dry_run", False))
    worker = _worker_block(read_short_raw())
    return bool(worker.get("dry_run", True))


def set_sleeve_practice_mode(sleeve: SleeveName, dry_run: bool) -> dict[str, Any]:
    """Toggle practice mode for one sleeve without touching the other."""
    path = sleeve_config_path(sleeve)
    if sleeve == "short" and not path.exists():
        mirror_shared_api_into_short()
    raw = read_config_raw(path) if path.exists() else {}
    if sleeve == "short" and not raw:
        raw = read_short_raw()
    worker = _worker_block(raw)
    worker["dry_run"] = bool(dry_run)
    if dry_run:
        worker["live_trading"] = False
    elif worker.get("auto_execute"):
        worker["live_trading"] = True
    raw["background_worker"] = worker
    if sleeve == "short":
        # Keep short API fields mirrored; never invent separate keys.
        for key, value in shared_api_fields_from_long().items():
            raw[key] = value
        raw["shared_api_from"] = "etrade_config.json"
        write_short_raw(raw)
    else:
        write_config_raw(path, raw)
    return worker


def feature_snapshot() -> dict[str, Any]:
    """Compact feature/data snapshot for the E*TRADE Trader phone app."""
    long_raw = read_long_raw()
    short_raw = read_short_raw()
    lw = _worker_block(long_raw)
    sw = _worker_block(short_raw)
    acct = get_shared_selected_account() or {}
    sandbox = bool(long_raw.get("sandbox", True))
    return {
        "feature": "shared_etrade_api",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "api": {
            "source": "etrade_config.json",
            "sandbox": sandbox,
            "environment": "sandbox" if sandbox else "production",
            "token_path": str(long_raw.get("token_path") or "etrade_tokens.json"),
            "account_label": str(acct.get("display_label") or "").strip() or None,
            "has_account": bool(str(acct.get("account_id_key") or "").strip()),
            "keys_configured": bool(
                long_raw.get("consumer_key")
                and not str(long_raw.get("consumer_key", "")).startswith("YOUR_")
            ),
        },
        "practice_mode": {
            "long_dry_run": bool(lw.get("dry_run", False)),
            "short_dry_run": bool(sw.get("dry_run", True)),
            "independent": True,
        },
        "automation": {
            "long_auto_execute": bool(lw.get("auto_execute", True)),
            "short_auto_execute": bool(sw.get("auto_execute", False)),
            "long_paused": bool(lw.get("paused", False)),
            "short_paused": bool(sw.get("paused", False)),
        },
        "notes": [
            "Long and short use one E*TRADE API (keys, sandbox, tokens, account).",
            "Practice mode (dry_run) can be ON/OFF per sleeve independently.",
            "Short strategy settings stay in short_etrade_config.json.",
        ],
    }


def feature_snapshot_markdown() -> str:
    snap = feature_snapshot()
    api = snap["api"]
    pm = snap["practice_mode"]
    auto = snap["automation"]
    lines = [
        "### Shared E*TRADE API (long + short)",
        f"- **API source:** `{api['source']}` · **env:** {api['environment']}",
        f"- **Account:** {api['account_label'] or '(not selected)'} · keys: "
        f"{'yes' if api['keys_configured'] else 'no'}",
        f"- **Practice long:** {'ON' if pm['long_dry_run'] else 'OFF'} · "
        f"**Practice short:** {'ON' if pm['short_dry_run'] else 'OFF'} "
        f"(independent)",
        f"- **Auto long:** {'ON' if auto['long_auto_execute'] else 'OFF'} · "
        f"**Auto short:** {'ON' if auto['short_auto_execute'] else 'OFF'}",
        "- Both sleeves share credentials/tokens/account; only practice + strategy diverge.",
    ]
    return "\n".join(lines)
