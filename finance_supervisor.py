#!/usr/bin/env python3
"""Top-level immortal supervisor for Finance background services.

Layer 1 (this process): always running; restarts pipeline_watchdog if missing.
Layer 2 (pipeline_watchdog): restarts etrade_worker if dead/stalled.
Layer 3 (etrade_worker): service loop never exits; pipeline runs in a child.

Scheduled ensure_etrade_worker.ps1 also restarts this supervisor every minute.
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from process_guard import (  # noqa: E402
    SUPERVISOR_HEARTBEAT,
    SUPERVISOR_LOCK,
    WATCHDOG_HEARTBEAT,
    WATCHDOG_LOCK,
    heartbeat_age_sec,
    pid_is_python,
    read_heartbeat,
    spawn_detached,
    write_heartbeat,
)

LOG = ROOT / "output" / "finance_supervisor.log"
WATCHDOG = ROOT / "pipeline_watchdog.py"


def _log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def _read_pid(path: Path) -> int:
    try:
        if not path.exists():
            return 0
        return int(path.read_text(encoding="utf-8").strip().split()[0])
    except Exception:
        return 0


def _acquire() -> bool:
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.kernel32.SetLastError(0)
            handle = ctypes.windll.kernel32.CreateMutexW(
                None, False, "Local\\FinanceSupervisor"
            )
            err = int(ctypes.windll.kernel32.GetLastError())
            if err == 183:  # ERROR_ALREADY_EXISTS
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                _log("Another supervisor holds the mutex; exiting")
                return False
            global _SUPERVISOR_MUTEX  # noqa: PLW0603
            _SUPERVISOR_MUTEX = int(handle) if handle else None
        except Exception as exc:
            _log(f"supervisor mutex note: {exc}")
    try:
        SUPERVISOR_LOCK.parent.mkdir(parents=True, exist_ok=True)
        if SUPERVISOR_LOCK.exists():
            old = _read_pid(SUPERVISOR_LOCK)
            if old and old != os.getpid() and pid_is_python(old):
                _log(f"Another supervisor running (pid={old}); exiting")
                return False
            try:
                SUPERVISOR_LOCK.unlink(missing_ok=True)
            except OSError:
                pass
        SUPERVISOR_LOCK.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except Exception as exc:
        _log(f"supervisor lock failed (continuing): {exc}")
        return True


_SUPERVISOR_MUTEX: int | None = None


def _watchdog_alive() -> bool:
    pid = _read_pid(WATCHDOG_LOCK)
    if pid and pid_is_python(pid):
        return True
    hb_pid, _ = read_heartbeat(WATCHDOG_HEARTBEAT)
    if hb_pid and pid_is_python(hb_pid) and heartbeat_age_sec(WATCHDOG_HEARTBEAT) < 90:
        return True
    return False


def _start_watchdog() -> None:
    from process_guard import resolve_pythonw

    py = resolve_pythonw()
    _log(f"Starting pipeline_watchdog via {py}")
    try:
        WATCHDOG_LOCK.unlink(missing_ok=True)
    except OSError:
        pass
    # pipeline_watchdog quiet mode: only --check-sec / --no-restart (no --stall-sec)
    spawn_detached(
        [str(py), str(WATCHDOG), "--check-sec", "8"],
        cwd=ROOT,
    )


def main() -> int:
    if not _acquire():
        return 0

    _log(f"Finance SUPERVISOR UP pid={os.getpid()} (immortal layer)")
    consecutive = 0
    while True:
        try:
            write_heartbeat(SUPERVISOR_HEARTBEAT, pid=os.getpid(), extra="ok")
            SUPERVISOR_LOCK.write_text(str(os.getpid()), encoding="utf-8")

            if not _watchdog_alive():
                _log("Watchdog missing/dead — restarting")
                # Do not kill unknown PIDs; only clear stale lock
                try:
                    old = _read_pid(WATCHDOG_LOCK)
                    if old and not pid_is_python(old):
                        WATCHDOG_LOCK.unlink(missing_ok=True)
                except OSError:
                    pass
                _start_watchdog()
                time.sleep(3)

            consecutive = 0
        except KeyboardInterrupt:
            _log("Supervisor KeyboardInterrupt — exiting")
            break
        except BaseException as exc:
            consecutive += 1
            _log(f"supervisor loop error ({consecutive}): {exc}")
            try:
                _log(traceback.format_exc()[-400:])
            except Exception:
                pass
            time.sleep(min(30, 3 * consecutive))
            continue

        time.sleep(10)

    try:
        if _read_pid(SUPERVISOR_LOCK) == os.getpid():
            SUPERVISOR_LOCK.unlink(missing_ok=True)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    # Never raise out of main — restart via ensure if needed
    while True:
        try:
            code = main()
            if code == 0:
                # Clean exit (another instance or KeyboardInterrupt)
                raise SystemExit(0)
        except SystemExit:
            raise
        except BaseException as exc:
            try:
                _log(f"supervisor crashed hard: {exc} — respawning in 5s")
            except Exception:
                pass
            time.sleep(5)
