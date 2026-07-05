#!/usr/bin/env python3
"""Launch E*TRADE Trader with crash logging (used by desktop shortcut)."""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from win_app_identity import apply_windows_app_identity

apply_windows_app_identity()


def _ensure_venv_python() -> None:
    """Re-launch with the project venv if started from system Python."""

    if os.environ.get("ETRADE_TRADER_VENV"):
        return

    venv_scripts = (ROOT / ".venv" / "Scripts").resolve()
    current = Path(sys.executable).resolve()
    try:
        current.relative_to(venv_scripts)
        return
    except ValueError:
        pass

    launcher = venv_scripts / "pythonw.exe"
    if not launcher.exists():
        launcher = venv_scripts / "python.exe"
    if not launcher.exists():
        return

    os.environ["ETRADE_TRADER_VENV"] = "1"
    import subprocess

    flags = getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(
        [str(launcher), *sys.argv],
        cwd=str(ROOT),
        close_fds=True,
        creationflags=flags,
    )
    raise SystemExit(0)

LOG = ROOT / "output" / "etrade_trader.log"


def _log_crash(text: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")


if __name__ == "__main__":
    _ensure_venv_python()
    try:
        from etrade_trader_gui import main

        raise SystemExit(main())
    except Exception:
        _log_crash(traceback.format_exc())
        raise