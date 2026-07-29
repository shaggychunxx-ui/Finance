"""Load Finance agent runners from main.py with module caching.

Falls back to per-package discovery when main.py imports fail (e.g. a package
was deleted or not yet installed), so the Agents UI can still list/run what is
available instead of blanking the whole panel.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from typing import Any, Callable

from app_paths import ROOT

_AGENT_PACKAGES = (
    "electricity",
    "grid",
    "transportation",
    "meteorology",
    "logistics",
    "patents",
    "sales_analytics",
)


def _reload_agent_packages() -> None:
    for package in _AGENT_PACKAGES:
        for name in (f"agents.{package}", f"agents.{package}.expert"):
            module = sys.modules.get(name)
            if module is not None:
                try:
                    importlib.reload(module)
                except Exception:
                    pass


def _runners_from_packages() -> dict[str, Callable[..., Any]]:
    """Build RUNNERS from agents/* packages that expose run_*_analysis."""
    try:
        from agents.platform_catalog import (
            _folder_to_id,
            _runner_from_package,
            discover_local_packages,
        )
    except Exception:
        return {}

    runners: dict[str, Callable[..., Any]] = {}
    for package in discover_local_packages():
        fn = _runner_from_package(package)
        if fn is None:
            continue
        runners[_folder_to_id(package)] = fn

    # Single-module agents (not package folders)
    for module_name, agent_id in (("market_predictor", "market-predictor"),):
        try:
            mod = importlib.import_module(f"agents.{module_name}")
        except Exception:
            continue
        for name, value in vars(mod).items():
            if name.startswith("run_") and name.endswith("_analysis") and callable(value):
                runners[agent_id] = value
                break
    return runners


def load_finance_runners(*, reload: bool = False) -> dict[str, Callable[..., Any]]:
    if reload:
        sys.modules.pop("finance_platform_main", None)
        _reload_agent_packages()

    cached = sys.modules.get("finance_platform_main")
    if cached is not None and hasattr(cached, "RUNNERS"):
        return cached.RUNNERS

    main_path = ROOT / "main.py"
    spec = importlib.util.spec_from_file_location("finance_platform_main", main_path)
    if spec is None or spec.loader is None:
        return _runners_from_packages()

    module = importlib.util.module_from_spec(spec)
    # Register before exec so circular imports see a partial module if needed.
    sys.modules["finance_platform_main"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("finance_platform_main", None)
        return _runners_from_packages()

    runners = getattr(module, "RUNNERS", None)
    if isinstance(runners, dict) and runners:
        return runners
    return _runners_from_packages()
