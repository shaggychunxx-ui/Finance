#!/usr/bin/env python3
"""External recovery when etrade_worker dies mid-pipeline.

Does NOT depend on wmic. Writes its own heartbeat. Clears stuck UI flags and
restarts a single worker when the worker heartbeat is dead.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
STATE = OUTPUT / "etrade_worker_state.json"
LOCK = OUTPUT / "etrade_worker.lock"
HB = OUTPUT / "etrade_worker_heartbeat.txt"
ENSURE_LOCK = OUTPUT / "ensure_silent_worker.lock"
ENSURE_HB = OUTPUT / "ensure_silent_worker_heartbeat.txt"
LOG = OUTPUT / "ensure_silent_worker.log"

CHECK_SEC = 25
HB_DEAD_SEC = 75
STUCK_SEC = 100


def _log(msg: str) -> None:
    try:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {msg}\n")
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=0x08000000,
            )
            return str(pid) in (r.stdout or "")
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _hb_age(path: Path = HB) -> float:
    try:
        if not path.exists():
            return 9_999.0
        parts = path.read_text(encoding="utf-8").strip().splitlines()
        if len(parts) < 2:
            return 9_999.0
        return max(0.0, time.time() - float(parts[1]))
    except Exception:
        return 9_999.0


def _lock_pid() -> int:
    try:
        if not LOCK.exists():
            return 0
        return int(LOCK.read_text(encoding="utf-8").strip().split()[0])
    except Exception:
        return 0


def _worker_alive() -> bool:
    # Heartbeat is primary — updated every ~12s by worker thread
    if _hb_age(HB) < HB_DEAD_SEC:
        return True
    pid = _lock_pid()
    return bool(pid and _pid_alive(pid))


def _load_state() -> dict:
    try:
        if STATE.exists():
            return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_state(state: dict) -> None:
    try:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:
        pass


def _clear_stuck() -> None:
    state = _load_state()
    if not state.get("pipeline_active"):
        return
    prog = state.get("pipeline_progress") or "?"
    try:
        age = time.time() - float(state.get("pipeline_progress_at") or 0)
    except Exception:
        age = 0
    _log(f"Clear stuck UI flag age={age:.0f}s progress={prog}")
    state.pop("pipeline_active", None)
    state.pop("pipeline_progress", None)
    state.pop("pipeline_progress_at", None)
    _save_state(state)
    try:
        if LOCK.exists() and not _pid_alive(_lock_pid()):
            LOCK.unlink(missing_ok=True)
    except OSError:
        pass


def _start_worker() -> None:
    py = Path(os.environ.get("FINANCE_PYTHON", ""))
    if not py.is_file():
        py = Path(r"C:\Users\Box One\AppData\Local\Programs\Python\Python312\python.exe")
    if not py.is_file():
        py = ROOT / ".venv" / "Scripts" / "python.exe"
    if not py.is_file():
        py = Path(sys.executable)

    venv = ROOT / ".venv"
    env = dict(os.environ)
    env["VIRTUAL_ENV"] = str(venv)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + str(venv / "Lib" / "site-packages")
    env["PATH"] = str(venv / "Scripts") + os.pathsep + env.get("PATH", "")
    env["FINANCE_AGENT_SUBPROCESS"] = "1"
    env["FINANCE_SPLIT_PIPELINES"] = "1"
    # Always on: research was historically forced off by Ensure Worker Tick.vbs
    # and then starved for days. Parent env must not re-disable it.
    env["FINANCE_RUN_RESEARCH"] = "1"
    env["FINANCE_RESEARCH_DEDICATED"] = "1"
    env["FINANCE_PREDICTOR_FETCH_PRICES"] = "0"
    env["FINANCE_PIPELINE_TIMEOUT_SEC"] = "1500"
    env["FINANCE_PIPELINE_STALL_SEC"] = "90"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    kwargs: dict = {
        "cwd": str(ROOT),
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000
    subprocess.Popen([str(py), "-u", str(ROOT / "etrade_worker.py"), "--service"], **kwargs)
    _log(f"Started worker via {py.name}")


def _touch_ensure_hb() -> None:
    try:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        ENSURE_HB.write_text(f"{os.getpid()}\n{time.time():.3f}\nensure\n", encoding="utf-8")
    except OSError:
        pass


def _acquire() -> bool:
    try:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        if ENSURE_LOCK.exists():
            try:
                old = int(ENSURE_LOCK.read_text(encoding="utf-8").strip().split()[0])
            except Exception:
                old = 0
            if old and old != os.getpid() and _pid_alive(old):
                return False
        ENSURE_LOCK.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except OSError:
        return True


def main() -> int:
    if not _acquire():
        return 0
    _log(f"Ensure up pid={os.getpid()}")
    while True:
        try:
            _touch_ensure_hb()
            alive = _worker_alive()
            state = _load_state()
            active = bool(state.get("pipeline_active"))
            try:
                prog_age = time.time() - float(state.get("pipeline_progress_at") or 0)
            except Exception:
                prog_age = 0.0

            if not alive:
                if active:
                    _clear_stuck()
                _log(f"Worker dead (hb={_hb_age():.0f}s) — restarting")
                _start_worker()
                time.sleep(20)
            elif active and prog_age > STUCK_SEC * 5:
                # Worker heartbeat alive but progress frozen a long time — clear UI only
                _log(f"Progress frozen {prog_age:.0f}s with live worker — clear UI flag")
                _clear_stuck()
        except Exception as exc:
            _log(f"loop error: {exc}")
        time.sleep(CHECK_SEC)


if __name__ == "__main__":
    raise SystemExit(main())
