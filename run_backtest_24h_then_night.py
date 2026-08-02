#!/usr/bin/env python3
"""Run continuous full-day walk-forward for N hours, then restore night service.

Usage (background)::

    pythonw run_backtest_24h_then_night.py
    python run_backtest_24h_then_night.py --hours 24
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app_paths import ensure_app_path  # noqa: E402

ensure_app_path()

from run_backtest_loop import (  # noqa: E402
    LOG_FILE,
    SERVICE_LOCK,
    _log,
    acquire_service_lock,
    full_day_defaults,
    release_service_lock,
    run_loop,
)


def _stop_other_loops() -> None:
    """Best-effort stop of other run_backtest_loop processes on this host."""
    my_pid = os.getpid()
    try:
        import ctypes
        from ctypes import wintypes

        # Prefer taskkill by command line via PowerShell (reliable on Windows)
        ps = (
            f"$my={my_pid}; "
            "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | "
            "Where-Object { $_.CommandLine -and $_.CommandLine -match 'run_backtest_loop' "
            "-and $_.ProcessId -ne $my } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; "
            "Write-Output ('stopped ' + $_.ProcessId) }"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(ROOT),
        )
        for line in (r.stdout or "").splitlines():
            if line.strip():
                _log(line.strip())
    except Exception as exc:
        _log(f"stop other loops note: {exc}")
    try:
        if SERVICE_LOCK.exists():
            SERVICE_LOCK.unlink(missing_ok=True)
            _log("Cleared backtest_loop.lock")
    except OSError:
        pass
    time.sleep(2)


def _start_night_service() -> None:
    vbs = ROOT / "Start Night Backtest Service.vbs"
    if vbs.exists():
        _log(f"Restarting normal night service via {vbs.name}")
        subprocess.Popen(
            ["wscript.exe", "//B", "//Nologo", str(vbs)],
            cwd=str(ROOT),
            close_fds=True,
        )
        return
    pyw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if not pyw.exists():
        pyw = Path(sys.executable)
    _log("Restarting normal night service via run_backtest_loop.py --service")
    subprocess.Popen(
        [str(pyw), str(ROOT / "run_backtest_loop.py"), "--service"],
        cwd=str(ROOT),
        close_fds=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Continuous walk-forward for N hours, then night-only service"
    )
    parser.add_argument("--hours", type=float, default=24.0, help="Burst duration (default 24)")
    args = parser.parse_args()
    hours = float(args.hours)
    if hours <= 0:
        print("--hours must be > 0", file=sys.stderr)
        return 2

    defaults = full_day_defaults()
    _log(f"=== 24h walk-forward BURST starting ({hours:g}h continuous, RTH allowed) ===")
    _log(f"Log: {LOG_FILE}")
    _stop_other_loops()

    if not acquire_service_lock():
        _log("Service lock busy after stop — clearing and retrying")
        try:
            SERVICE_LOCK.unlink(missing_ok=True)
        except OSError:
            pass
        if not acquire_service_lock():
            _log("FATAL: could not hold service lock")
            return 3

    code = 1
    try:
        code = run_loop(
            interval_minutes=0,
            target_trials=int(defaults["target_trials"]),
            max_symbols=int(defaults["max_symbols"]),
            full=bool(defaults["full"]),
            once=False,
            night_only=False,
            continuous=True,
            hours=hours,
        )
    finally:
        release_service_lock()
        _log("Burst finished — restoring normal night-only schedule")
        try:
            _start_night_service()
        except Exception as exc:
            _log(f"Failed to restart night service: {exc}")
        _log("=== 24h burst complete; night service restart requested ===")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
