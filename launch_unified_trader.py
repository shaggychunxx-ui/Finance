#!/usr/bin/env python3
"""Launch unified Long+Short trader with venv + crash log."""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOG = ROOT / "output" / "unified_trader.log"


def _ensure_venv() -> None:
    """Point this process at Finance .venv packages without re-exec (avoids double process flash)."""
    if os.environ.get("ETRADE_UNIFIED_VENV"):
        return
    os.environ["ETRADE_UNIFIED_VENV"] = "1"
    venv = ROOT / ".venv"
    site = venv / "Lib" / "site-packages"
    scripts = venv / "Scripts"
    if venv.is_dir():
        os.environ["VIRTUAL_ENV"] = str(venv)
        os.environ["PATH"] = str(scripts) + os.pathsep + os.environ.get("PATH", "")
    path_parts = [str(ROOT)]
    if site.is_dir():
        path_parts.append(str(site))
    prev = os.environ.get("PYTHONPATH", "")
    if prev:
        path_parts.append(prev)
    os.environ["PYTHONPATH"] = os.pathsep.join(path_parts)
    for p in path_parts:
        if p and p not in sys.path:
            sys.path.insert(0, p)


if __name__ == "__main__":
    _ensure_venv()
    try:
        from unified_trader_gui import main

        raise SystemExit(main())
    except Exception:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        LOG.open("a", encoding="utf-8").write(traceback.format_exc() + "\n")
        raise
