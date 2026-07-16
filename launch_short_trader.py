#!/usr/bin/env python3
"""Launch E*TRADE Short Trader with crash logging."""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from short_paths import SHORT_APP_LOG, SHORT_APP_USER_MODEL_ID, ensure_short_dirs


def _apply_identity() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(SHORT_APP_USER_MODEL_ID)
    except Exception:
        pass


def _ensure_venv_python() -> None:
    if os.environ.get("ETRADE_SHORT_TRADER_VENV"):
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
    os.environ["ETRADE_SHORT_TRADER_VENV"] = "1"
    import subprocess

    flags = getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(
        [str(launcher), *sys.argv],
        cwd=str(ROOT),
        close_fds=True,
        creationflags=flags,
    )
    raise SystemExit(0)


def _log_crash(text: str) -> None:
    ensure_short_dirs()
    with SHORT_APP_LOG.open("a", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")


if __name__ == "__main__":
    _ensure_venv_python()
    _apply_identity()
    try:
        from short_trader_gui import main

        raise SystemExit(main())
    except Exception:
        _log_crash(traceback.format_exc())
        raise
