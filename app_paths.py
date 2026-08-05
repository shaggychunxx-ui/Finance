"""Shared Finance application paths for dev runs and frozen executables.

Broker / OAuth / live status must use :mod:`etrade_runtime` (live root), not
only this module's ``ROOT`` (which follows the script location and may be a
GitHub clone).
"""

from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT = app_root()
OUTPUT = ROOT / "output"
ICON_FILE = ROOT / "app_icon.ico"


def ensure_app_path() -> Path:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    return ROOT


def live_runtime_root(*, allow_non_live: bool = False) -> Path:
    """Canonical live Finance tree (worker + tokens). See etrade_runtime."""

    from etrade_runtime import resolve_live_root

    return resolve_live_root(allow_non_live=allow_non_live).root
