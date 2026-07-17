"""Discover Finance platform agents locally and on GitHub for the trading pipeline."""

from __future__ import annotations

import importlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

AGENTS_DIR = Path(__file__).resolve().parent
ROOT = AGENTS_DIR.parent
OUTPUT = ROOT / "output"
CATALOG_CACHE = OUTPUT / "agent_catalog_cache.json"

GITHUB_REPO = "shaggychunxx-ui/Finance"
GITHUB_AGENTS_API = f"https://api.github.com/repos/{GITHUB_REPO}/contents/agents"
REMOTE_CHECK_TTL_SECONDS = 6 * 60 * 60  # 6 hours

SKIP_DIRS = {
    "__pycache__",
}
SKIP_FILES = {
    "__init__.py",
    "platform_catalog.py",
    "market_predictor.py",
}

# CLI id -> default output filename when not listed in data steward registry.
OUTPUT_OVERRIDES: dict[str, str] = {
    "events": "world_events.json",
}

CATEGORY_BY_ID: dict[str, str] = {
    "electricity": "Energy & Infrastructure",
    "grid": "Energy & Infrastructure",
    "meteorology": "Energy & Infrastructure",
    "transportation": "Energy & Infrastructure",
    "logistics": "Energy & Infrastructure",
    "markets": "Markets & Finance",
    "order-execution": "Markets & Finance",
    "options-flow": "Markets & Finance",
    "finance": "Markets & Finance",
    "financial-data": "Markets & Finance",
    "datascience": "Markets & Finance",
    "sales-analytics": "Markets & Finance",
    "sec-filings": "Markets & Finance",
    "trading-economics": "Markets & Finance",
    "census": "Markets & Finance",
    "agriculture": "Energy & Infrastructure",
    "theoretical-probability": "Probability & Stats",
    "empirical-probability": "Probability & Stats",
    "combined-conditional": "Probability & Stats",
    "research-statistics": "Probability & Stats",
    "events": "Intelligence",
    "geopolitics": "Intelligence",
    "migration": "Intelligence",
    "patents": "Intelligence",
    "data-steward": "Data Platform",
    "records-management": "Data Platform",
}


def _folder_to_id(folder: str) -> str:
    return folder.replace("_", "-")


def _id_to_folder(agent_id: str) -> str:
    return agent_id.replace("-", "_")


def _humanize(folder: str) -> str:
    return folder.replace("_", " ").replace("-", " ").title()


def _registry_rows() -> list[dict[str, Any]]:
    try:
        from agents.data_steward.expert import AGENT_REGISTRY

        return list(AGENT_REGISTRY)
    except Exception:
        return []


def _registry_lookup() -> dict[str, dict[str, Any]]:
    return {row["command"]: row for row in _registry_rows()}


def _output_file(agent_id: str, package: str) -> str:
    row = _registry_lookup().get(agent_id)
    if row and row.get("primary_output"):
        return str(row["primary_output"])
    return OUTPUT_OVERRIDES.get(agent_id, f"{package}.json")


def _label_for(agent_id: str, package: str) -> str:
    row = _registry_lookup().get(agent_id)
    if row and row.get("agent"):
        return str(row["agent"])
    return _humanize(package)


def _runner_ids_from_main() -> dict[str, Callable[..., Any]]:
    try:
        from main import RUNNERS

        return dict(RUNNERS)
    except Exception:
        return {}


def _runner_from_package(package: str) -> Callable[..., Any] | None:
    try:
        module = importlib.import_module(f"agents.{package}")
    except Exception:
        return None
    for name, value in vars(module).items():
        if name.startswith("run_") and name.endswith("_analysis") and callable(value):
            return value
    return None


def resolve_runner(agent_id: str, runners: dict[str, Callable[..., Any]] | None = None) -> Callable[..., Any] | None:
    """Return a runnable agent function by CLI id."""
    if runners and agent_id in runners:
        return runners[agent_id]
    main_runners = _runner_ids_from_main()
    if agent_id in main_runners:
        return main_runners[agent_id]
    return _runner_from_package(_id_to_folder(agent_id))


def discover_local_packages() -> list[str]:
    """Agent package folders under agents/ that expose run_*_analysis."""
    packages: list[str] = []
    for entry in sorted(AGENTS_DIR.iterdir()):
        if not entry.is_dir() or entry.name in SKIP_DIRS:
            continue
        if not (entry / "__init__.py").exists():
            continue
        if _runner_from_package(entry.name) is None:
            continue
        packages.append(entry.name)
    return packages


def fetch_remote_packages(*, force: bool = False) -> list[str] | None:
    """List agent package folder names from GitHub (None if unavailable)."""
    cached = _read_cache()
    now = time.time()
    if (
        not force
        and cached.get("remote_packages")
        and (now - float(cached.get("checked_at", 0))) < REMOTE_CHECK_TTL_SECONDS
    ):
        return list(cached["remote_packages"])

    request = urllib.request.Request(
        GITHUB_AGENTS_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Finance-ETrade-Trader",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        if cached.get("remote_packages"):
            return list(cached["remote_packages"])
        return None

    remote: list[str] = []
    for item in payload:
        if item.get("type") != "dir":
            continue
        name = str(item.get("name", "")).strip()
        if name and name not in SKIP_DIRS:
            remote.append(name)

    _write_cache({"remote_packages": remote, "checked_at": now})
    return remote


def _read_cache() -> dict[str, Any]:
    if not CATALOG_CACHE.exists():
        return {}
    try:
        return json.loads(CATALOG_CACHE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_cache(data: dict[str, Any]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    existing = _read_cache()
    existing.update(data)
    CATALOG_CACHE.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def detect_catalog_changes(*, check_remote: bool = True) -> dict[str, list[str]]:
    """Compare local install vs GitHub and note newly seen remote agents."""
    local_pkgs = set(discover_local_packages())
    local_ids = {_folder_to_id(pkg) for pkg in local_pkgs}

    remote_pkgs: set[str] = set()
    if check_remote:
        fetched = fetch_remote_packages()
        if fetched is not None:
            remote_pkgs = set(fetched)

    cache = _read_cache()
    seen_remote = set(cache.get("seen_remote_packages", []))
    remote_only = sorted(remote_pkgs - local_pkgs)
    new_on_github = sorted(remote_pkgs - seen_remote) if remote_pkgs else []

    if remote_pkgs:
        cache["seen_remote_packages"] = sorted(remote_pkgs)
        _write_cache(cache)

    return {
        "local_packages": sorted(local_pkgs),
        "local_ids": sorted(local_ids),
        "remote_packages": sorted(remote_pkgs),
        "remote_only": remote_only,
        "new_on_github": new_on_github,
        "missing_runner": sorted(
            agent_id
            for agent_id in local_ids
            if resolve_runner(agent_id) is None
        ),
    }


def log_catalog_changes(
    on_progress: Callable[[str], None] | None = None,
    *,
    check_remote: bool = True,
) -> dict[str, list[str]]:
    changes = detect_catalog_changes(check_remote=check_remote)

    def say(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    if changes["remote_packages"]:
        say(
            f"Agent catalog: {len(changes['local_packages'])} local, "
            f"{len(changes['remote_packages'])} on GitHub."
        )
    else:
        say(f"Agent catalog: {len(changes['local_packages'])} local agents discovered.")

    if changes["remote_only"]:
        names = ", ".join(changes["remote_only"])
        say(f"New on GitHub (not installed locally): {names}. Run git pull in Finance to add them.")

    if changes["new_on_github"]:
        names = ", ".join(changes["new_on_github"])
        say(f"New agent folders detected on GitHub: {names}")

    if changes["missing_runner"]:
        names = ", ".join(changes["missing_runner"])
        say(f"Agents missing runners (skipped): {names}")

    return changes


def build_platform_catalog(*, check_remote: bool = True) -> list[dict[str, Any]]:
    """Build the full catalog from local packages, registry metadata, and GitHub."""
    if check_remote:
        fetch_remote_packages()

    registry_order = [row["command"] for row in _registry_rows()]
    packages = discover_local_packages()
    by_id: dict[str, dict[str, Any]] = {}

    for package in packages:
        agent_id = _folder_to_id(package)
        if resolve_runner(agent_id) is None:
            continue
        by_id[agent_id] = {
            "id": agent_id,
            "label": _label_for(agent_id, package),
            "file": _output_file(agent_id, package),
            "package": package,
            "category": CATEGORY_BY_ID.get(agent_id, "Platform"),
            "desc": f"Finance agent package `{package}`",
        }

    ordered: list[dict[str, Any]] = []
    for agent_id in registry_order:
        if agent_id in by_id:
            ordered.append(by_id.pop(agent_id))
    for agent_id in sorted(by_id):
        ordered.append(by_id[agent_id])
    return ordered


def active_agent_sources(*, check_remote: bool = True) -> list[dict[str, Any]]:
    """Agents to run in the background pipeline."""
    return build_platform_catalog(check_remote=check_remote)


def full_agent_catalog(*, check_remote: bool = True) -> list[dict[str, Any]]:
    """Catalog entries for GUI lists (includes market predictor)."""
    try:
        from agent_personality import personality_label as _personality_label
    except Exception:
        _personality_label = None

    catalog = [
        {
            "id": entry["id"],
            "label": entry["label"],
            "category": entry.get("category", "Platform"),
            "output": entry["file"],
            "desc": entry.get("desc", ""),
            **(
                {"personality": _personality_label(entry["id"])}
                if _personality_label
                else {}
            ),
        }
        for entry in build_platform_catalog(check_remote=check_remote)
    ]
    catalog.append(
        {
            "id": "market-predictor",
            "label": "Market Predictor",
            "category": "Ensemble",
            "output": "market_predictions.json",
            "desc": "Fuses all agents into top market mover predictions.",
            **(
                {"personality": _personality_label("market-predictor")}
                if _personality_label
                else {}
            ),
        }
    )
    return catalog