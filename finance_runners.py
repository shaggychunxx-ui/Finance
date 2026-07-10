"""Load Finance agent runners from main.py with module caching."""

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
        raise ImportError(f"Cannot load Finance runners from {main_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules["finance_platform_main"] = module
    spec.loader.exec_module(module)
    return module.RUNNERS