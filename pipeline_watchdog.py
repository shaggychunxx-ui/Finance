#!/usr/bin/env python3
"""External pipeline watchdog — quiet mode.

Only restarts the worker when the heartbeat is DEAD (process gone).
Does NOT kill live workers on progress stalls (that caused restart thrash + popups).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from process_guard import (  # noqa: E402
    WORKER_HEARTBEAT,
    WORKER_LOCK,
    WATCHDOG_HEARTBEAT,
    WATCHDOG_LOCK,
    heartbeat_age_sec,
    kill_tree,
    pid_is_python,
    read_heartbeat,
    spawn_detached,
    write_heartbeat,
)

STATE_FILE = ROOT / "output" / "etrade_worker_state.json"
LOG_FILE = ROOT / "output" / "pipeline_watchdog.log"
WORKER = ROOT / "etrade_worker.py"
LOCK_FILE = WORKER_LOCK


def _log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def _load_state() -> dict:
    try:
        if not STATE_FILE.exists():
            return {}
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass


def _read_lock_pid() -> int:
    try:
        if not LOCK_FILE.exists():
            return 0
        return int(LOCK_FILE.read_text(encoding="utf-8").strip().split()[0])
    except Exception:
        return 0


def _acquire_singleton() -> bool:
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.kernel32.SetLastError(0)
            handle = ctypes.windll.kernel32.CreateMutexW(
                None, False, "Local\\FinancePipelineWatchdog"
            )
            if int(ctypes.windll.kernel32.GetLastError()) == 183:
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                return False
            global _WATCHDOG_MUTEX_HANDLE  # noqa: PLW0603
            _WATCHDOG_MUTEX_HANDLE = int(handle) if handle else None
        except Exception:
            pass
    try:
        WATCHDOG_LOCK.parent.mkdir(parents=True, exist_ok=True)
        if WATCHDOG_LOCK.exists():
            try:
                old = int(WATCHDOG_LOCK.read_text(encoding="utf-8").strip().split()[0])
            except Exception:
                old = 0
            if old and old != os.getpid() and pid_is_python(old):
                return False
            try:
                WATCHDOG_LOCK.unlink(missing_ok=True)
            except OSError:
                pass
        WATCHDOG_LOCK.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except Exception:
        return True


_WATCHDOG_MUTEX_HANDLE: int | None = None


def _clear_state() -> None:
    state = _load_state()
    state.pop("pipeline_active", None)
    state.pop("pipeline_progress", None)
    state.pop("pipeline_progress_at", None)
    state["last_pipeline_at"] = 0
    _save_state(state)


def _worker_alive() -> bool:
    """True only if the worker process is up (or was just spawned).

    Do not treat a fresh heartbeat as alive when the lock PID is dead — that
    left the stack stuck for up to 2 minutes after a crash (heartbeat grace).
    """
    lock_pid = _read_lock_pid()
    if lock_pid and pid_is_python(lock_pid):
        # Process is running; allow a short window of stale heartbeats.
        return heartbeat_age_sec(WORKER_HEARTBEAT) < 180
    # No live process. Brief grace only for spawn race (watchdog just started it).
    return heartbeat_age_sec(WORKER_HEARTBEAT) < 30


def _start_worker() -> None:
    from process_guard import resolve_pythonw

    py = resolve_pythonw()
    _log(f"Starting worker: {py}")
    spawn_detached([str(py), str(WORKER), "--service"], cwd=ROOT)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-sec", type=int, default=30)
    parser.add_argument("--no-restart", action="store_true")
    args = parser.parse_args()

    if not _acquire_singleton():
        return 0

    _log(f"Watchdog UP pid={os.getpid()} (quiet: restart only if worker dead)")

    while True:
        try:
            write_heartbeat(WATCHDOG_HEARTBEAT, pid=os.getpid(), extra="ok")
            try:
                WATCHDOG_LOCK.write_text(str(os.getpid()), encoding="utf-8")
            except OSError:
                pass

            if not args.no_restart and not _worker_alive():
                lock_pid = _read_lock_pid()
                if lock_pid and pid_is_python(lock_pid):
                    # process exists, wait for heartbeat
                    pass
                else:
                    _log("Worker missing — restarting once")
                    try:
                        LOCK_FILE.unlink(missing_ok=True)
                    except OSError:
                        pass
                    _clear_state()
                    if lock_pid:
                        kill_tree(lock_pid)
                    time.sleep(2)
                    _start_worker()
                    time.sleep(15)  # cooldown so we do not thrash
        except KeyboardInterrupt:
            break
        except BaseException as exc:
            _log(f"loop error: {exc}")
            try:
                _log(traceback.format_exc()[-300:])
            except Exception:
                pass
            time.sleep(30)
            continue

        time.sleep(max(15, int(args.check_sec)))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
