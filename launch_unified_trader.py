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
    if os.environ.get("ETRADE_UNIFIED_VENV"):
        return
    venv = (ROOT / ".venv" / "Scripts").resolve()
    current = Path(sys.executable).resolve()
    try:
        current.relative_to(venv)
        return
    except ValueError:
        pass
    launcher = venv / "pythonw.exe"
    if not launcher.exists():
        launcher = venv / "python.exe"
    if not launcher.exists():
        return
    os.environ["ETRADE_UNIFIED_VENV"] = "1"
    import subprocess

    flags = getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen([str(launcher), *sys.argv], cwd=str(ROOT), close_fds=True, creationflags=flags)
    raise SystemExit(0)


if __name__ == "__main__":
    _ensure_venv()
    try:
        from unified_trader_gui import main

        raise SystemExit(main())
    except Exception:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        LOG.open("a", encoding="utf-8").write(traceback.format_exc() + "\n")
        raise
