#!/usr/bin/env python3
"""Dual-PC deployment: BOXONE = pipeline, AI-CODING = UI + E*TRADE broker.

Roles
-----
- ``pipeline`` — agent research, fusion, accuracy/backtests; no order placement.
- ``broker``   — UI host, E*TRADE OAuth, plan build, order placement, quote feed.
- ``all``      — legacy single-machine (default when deployment section missing).

Shared data (SMB)
-----------------
Recommended share on AI-CODING (10.10.10.1)::

    \\\\10.10.10.1\\FinanceShare
        pipeline\\   # BOXONE sole writer (agent JSON, portfolio, status)
        broker\\     # AI-CODING sole writer (live quotes, account snapshot)

Secrets (tokens, consumer keys) stay local on the broker machine only.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any, Literal

from app_paths import ROOT

Role = Literal["all", "pipeline", "broker"]

CONFIG_PATH = ROOT / "etrade_config.json"
DEPLOYMENT_FILE = ROOT / "deployment.json"

DEFAULT_DEPLOYMENT: dict[str, Any] = {
    # all | pipeline | broker
    "role": "all",
    # UNC or local path to the FinanceShare root (contains pipeline/ and broker/)
    # Prefer dedicated FinanceShare if installed; HelperDrop path works out of the box.
    "shared_root": r"\\10.10.10.1\HelperDrop\FinanceShare",
    # How often the broker publishes quotes / account snapshot to the share
    "quote_publish_interval_seconds": 60,
    # How often each side syncs from the peer folder into local output/
    "sync_interval_seconds": 30,
    # When true, broker publishes live quotes for pipeline consumption
    "publish_quotes": True,
    # When true, pipeline pulls quotes before agent enhance steps
    "consume_shared_quotes": True,
    # Practice mode enforcement hint (worker still reads background_worker.dry_run)
    "prefer_dry_run": True,
}

# Files the broker owns — never overwrite local copies from pipeline pull.
BROKER_OWNED_NAMES = frozenset(
    {
        "strategy_plan.json",
        "day_trade_state.json",
        "short_day_state.json",
        "sleeve_policy_state.json",
        "etrade_worker.lock",
        "etrade_worker_heartbeat.txt",
        "ensure_silent_worker_heartbeat.txt",
        "etrade_trader.log",
        "unified_trader.log",
        "etrade_worker.log",
        "account_values.json",
        "trade_history.json",
        "ui_prefs.json",
    }
)

# Subtrees under output/ that pipeline may publish (relative patterns handled in sync).
PIPELINE_SKIP_DIR_NAMES = frozenset({"history", "_agent_tmp", "__pycache__"})


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        # utf-8-sig tolerates BOM from Windows editors / PowerShell Set-Content
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def load_deployment(config_path: Path | None = None) -> dict[str, Any]:
    """Merge defaults ← etrade_config.deployment ← deployment.json ← env.

    ``deployment.json`` wins over config so ops can flip roles without editing
    secrets-bearing etrade_config.json. Env vars win last.
    """
    settings = dict(DEFAULT_DEPLOYMENT)

    cfg_path = Path(config_path) if config_path is not None else CONFIG_PATH
    raw = _read_json(cfg_path)
    section = raw.get("deployment")
    if isinstance(section, dict):
        settings.update({k: section[k] for k in section})

    file_data = _read_json(DEPLOYMENT_FILE)
    if file_data:
        settings.update({k: file_data[k] for k in file_data})

    env_role = (os.environ.get("FINANCE_ROLE") or "").strip().lower()
    if env_role in {"all", "pipeline", "broker"}:
        settings["role"] = env_role
    env_share = (os.environ.get("FINANCE_SHARED_ROOT") or "").strip()
    if env_share:
        settings["shared_root"] = env_share

    role = str(settings.get("role") or "all").strip().lower()
    if role not in {"all", "pipeline", "broker"}:
        role = "all"
    settings["role"] = role
    return settings


def machine_name() -> str:
    return (os.environ.get("COMPUTERNAME") or socket.gethostname() or "").strip().upper()


def role(config_path: Path | None = None) -> Role:
    return load_deployment(config_path)["role"]  # type: ignore[return-value]


def is_pipeline_machine(config_path: Path | None = None) -> bool:
    r = role(config_path)
    return r in {"pipeline", "all"}


def is_broker_machine(config_path: Path | None = None) -> bool:
    r = role(config_path)
    return r in {"broker", "all"}


def runs_pipeline(config_path: Path | None = None) -> bool:
    return role(config_path) in {"pipeline", "all"}


def runs_trading(config_path: Path | None = None) -> bool:
    """Plan build + order execution (not agent research)."""
    return role(config_path) in {"broker", "all"}


def shared_root(config_path: Path | None = None) -> Path | None:
    settings = load_deployment(config_path)
    raw = str(settings.get("shared_root") or "").strip()
    if not raw:
        return None
    return Path(raw)


def shared_pipeline_dir(config_path: Path | None = None) -> Path | None:
    root = shared_root(config_path)
    return None if root is None else root / "pipeline"


def shared_broker_dir(config_path: Path | None = None) -> Path | None:
    root = shared_root(config_path)
    return None if root is None else root / "broker"


def ensure_shared_layout(config_path: Path | None = None) -> dict[str, Any]:
    """Create pipeline/ and broker/ under shared_root when reachable."""
    root = shared_root(config_path)
    if root is None:
        return {"ok": False, "error": "shared_root not configured"}
    try:
        pipe = root / "pipeline"
        brok = root / "broker"
        pipe.mkdir(parents=True, exist_ok=True)
        brok.mkdir(parents=True, exist_ok=True)
        marker = root / "README_FINANCE_SHARE.txt"
        if not marker.exists():
            marker.write_text(
                "Finance dual-PC share\n"
                "  pipeline/  — written by BOXONE (agent research)\n"
                "  broker/    — written by AI-CODING (quotes, account snapshot)\n"
                "Do not put etrade tokens or consumer secrets here.\n",
                encoding="utf-8",
            )
        return {"ok": True, "root": str(root), "pipeline": str(pipe), "broker": str(brok)}
    except OSError as exc:
        return {"ok": False, "error": str(exc), "root": str(root)}


def deployment_summary(config_path: Path | None = None) -> str:
    d = load_deployment(config_path)
    return (
        f"role={d.get('role')} machine={machine_name()} "
        f"shared={d.get('shared_root')}"
    )
