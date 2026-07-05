"""Shared Finance application paths for dev runs and frozen executables."""

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