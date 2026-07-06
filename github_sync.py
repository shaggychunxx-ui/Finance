"""Pull platform updates from GitHub, install dependencies, and run new agents."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
REQUIREMENTS = ROOT / "requirements.txt"
CATALOG_CACHE = OUTPUT / "agent_catalog_cache.json"

PROTECTED_PREFIXES = (
    "output/",
    ".venv/",
    "build/",
    "dist/",
    "terminals/",
)
PROTECTED_FILES = frozenset(
    {
        "etrade_config.json",
        "etrade_tokens.json",
    }
)

ProgressFn = Callable[[str], None]


@dataclass
class SyncResult:
    updated_files: list[str] = field(default_factory=list)
    new_packages: list[str] = field(default_factory=list)
    pip_ok: bool = False
    agents_run: int = 0
    pipeline_ran: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _say(on_progress: ProgressFn | None, message: str) -> None:
    if on_progress:
        on_progress(message)


def _git(args: list[str], *, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _is_protected(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if normalized in PROTECTED_FILES:
        return True
    return any(normalized.startswith(prefix) for prefix in PROTECTED_PREFIXES)


def _discover_packages() -> set[str]:
    from agents.platform_catalog import discover_local_packages

    return set(discover_local_packages())


def _list_remote_changes() -> list[str]:
    fetch = _git(["fetch", "origin", "main"])
    if fetch.returncode != 0:
        raise RuntimeError(fetch.stderr or fetch.stdout or "git fetch failed")
    diff = _git(["diff", "--name-only", "HEAD", "origin/main"])
    if diff.returncode != 0:
        raise RuntimeError(diff.stderr or diff.stdout or "git diff failed")
    paths = [line.strip() for line in diff.stdout.splitlines() if line.strip()]
    paths = [p for p in paths if not _is_protected(p)]
    # Always refresh agents and Python deps even if diff is empty.
    for required in ("agents/", "requirements.txt"):
        if required not in paths:
            paths.append(required)
    return sorted(set(paths))


def _checkout_paths(paths: list[str], on_progress: ProgressFn | None) -> list[str]:
    if not paths:
        return []
    _say(on_progress, f"Updating {len(paths)} file(s) from GitHub…")
    chunk_size = 40
    checked: list[str] = []
    for start in range(0, len(paths), chunk_size):
        batch = paths[start : start + chunk_size]
        result = _git(["checkout", "origin/main", "--", *batch], timeout=240)
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout or "git checkout failed")
        checked.extend(batch)
    return checked


def _install_requirements(on_progress: ProgressFn | None) -> bool:
    if not REQUIREMENTS.exists():
        return True
    py = VENV_PY if VENV_PY.exists() else Path(sys.executable)
    _say(on_progress, "Installing Python dependencies…")
    result = subprocess.run(
        [str(py), "-m", "pip", "install", "-r", str(REQUIREMENTS)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "pip install failed")
    return True


def _run_new_agents(
    new_packages: list[str],
    on_progress: ProgressFn | None,
) -> int:
    if not new_packages:
        return 0
    from agents.platform_catalog import (
        _folder_to_id,
        _output_file,
        resolve_runner,
    )

    OUTPUT.mkdir(parents=True, exist_ok=True)
    ok = 0
    for index, package in enumerate(new_packages, start=1):
        agent_id = _folder_to_id(package)
        label = package.replace("_", " ").title()
        _say(on_progress, f"Running new agent {index}/{len(new_packages)}: {label}…")
        runner = resolve_runner(agent_id)
        if runner is None:
            raise RuntimeError(f"New agent `{package}` has no runnable entry point")
        out_path = OUTPUT / _output_file(agent_id, package)
        runner(output=out_path)
        try:
            from analysis_history import archive_agent_output

            archive_agent_output(agent_id, out_path)
        except Exception:
            pass
        ok += 1
    return ok


def _run_full_pipeline(on_progress: ProgressFn | None) -> None:
    from strategy_engine import run_agent_pipeline

    _say(on_progress, "Running full agent pipeline…")
    run_agent_pipeline(on_progress=on_progress, check_remote=False)


def sync_github_repository(*, on_progress: ProgressFn | None = None) -> SyncResult:
    """Fetch GitHub main, update local platform files, pip install, run new agents."""
    result = SyncResult()
    if not (ROOT / ".git").exists():
        raise RuntimeError("Finance folder is not a git repository — clone from GitHub first.")

    before = _discover_packages()
    _say(on_progress, "Fetching latest from GitHub…")

    try:
        result.updated_files = _checkout_paths(_list_remote_changes(), on_progress)
    except Exception as exc:
        result.errors.append(str(exc))
        return result

    after = _discover_packages()
    result.new_packages = sorted(after - before)

    if CATALOG_CACHE.exists():
        CATALOG_CACHE.unlink()

    try:
        result.pip_ok = _install_requirements(on_progress)
    except Exception as exc:
        result.errors.append(f"Dependencies: {exc}")

    agents_updated = any(p.startswith("agents/") for p in result.updated_files)
    try:
        if result.new_packages:
            _say(
                on_progress,
                f"Detected {len(result.new_packages)} new agent(s): {', '.join(result.new_packages)}",
            )
            result.agents_run = _run_new_agents(result.new_packages, on_progress)
            _say(on_progress, "Fusing Market Predictor…")
            from agents.market_predictor import run_market_predictor_analysis

            run_market_predictor_analysis(output=OUTPUT / "market_predictions.json")
            try:
                from analysis_history import archive_agent_output, archive_pipeline_cycle

                archive_agent_output("market-predictor", OUTPUT / "market_predictions.json")
                archive_pipeline_cycle()
            except Exception:
                pass
            result.pipeline_ran = True
        elif agents_updated:
            _run_full_pipeline(on_progress)
            result.pipeline_ran = True
        else:
            _say(on_progress, "Platform files updated — refreshing Market Predictor…")
            from agents.market_predictor import run_market_predictor_analysis

            run_market_predictor_analysis(output=OUTPUT / "market_predictions.json")
    except Exception as exc:
        result.errors.append(f"Agent run: {exc}")

    _say(on_progress, "GitHub sync complete")
    return result


def format_sync_summary(result: SyncResult) -> str:
    lines = [
        "Synced from https://github.com/shaggychunxx-ui/Finance (main)",
        "",
        f"Updated files: {len(result.updated_files)}",
    ]
    if result.new_packages:
        lines.append(f"New agents installed: {', '.join(result.new_packages)}")
    if result.agents_run:
        lines.append(f"New agents run immediately: {result.agents_run}")
    if result.pip_ok:
        lines.append("Python dependencies: installed/updated")
    if result.pipeline_ran:
        lines.append("Agent pipeline: completed")
    if result.errors:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"• {err}" for err in result.errors)
    return "\n".join(lines)