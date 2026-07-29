#!/usr/bin/env python3
"""Process continuum watchdog — keep Finance background layers alive.

Layers (bottom → top):
  1. finance_supervisor   — restarts pipeline_watchdog
  2. pipeline_watchdog    — restarts etrade_worker when dead
  3. etrade_worker        — broker loop + optional agent fallback

This process is a *fourth* immortal layer:
  - Checks lock PID + heartbeat for each layer every ~20s
  - Restarts only what is dead (no thrash of healthy processes)
  - Clears orphaned locks / stuck pipeline_active flags
  - Writes its own heartbeat so a 1‑minute Task Scheduler tick can re-spawn us

Install:  powershell -ExecutionPolicy Bypass -File "Install Continuum Watchdog.ps1"
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from process_guard import (  # noqa: E402
    SUPERVISOR_HEARTBEAT,
    SUPERVISOR_LOCK,
    WATCHDOG_HEARTBEAT,
    WATCHDOG_LOCK,
    WORKER_HEARTBEAT,
    WORKER_LOCK,
    heartbeat_age_sec,
    pid_is_alive,
    pid_matches_script,
    resolve_pythonw,
    spawn_detached,
    write_heartbeat,
)

OUTPUT = ROOT / "output"
STATE = OUTPUT / "etrade_worker_state.json"
LOG = OUTPUT / "process_continuum_watchdog.log"
CONTINUUM_LOCK = OUTPUT / "process_continuum_watchdog.lock"
CONTINUUM_HB = OUTPUT / "process_continuum_watchdog_heartbeat.txt"

CHECK_SEC = 20
# Layer is dead if lock PID is gone AND heartbeat older than this.
HB_DEAD_SEC = 90
# Brief grace after we spawn a layer (spawn race).
SPAWN_GRACE_SEC = 25
# Clear pipeline_active if no progress this long (UI stuck flag only).
STUCK_PIPELINE_SEC = 600

SUPERVISOR_SCRIPT = ROOT / "finance_supervisor.py"
WATCHDOG_SCRIPT = ROOT / "pipeline_watchdog.py"
WORKER_SCRIPT = ROOT / "etrade_worker.py"


def _log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def _read_lock_pid(path: Path) -> int:
    try:
        if not path.exists():
            return 0
        return int(path.read_text(encoding="utf-8").strip().split()[0])
    except Exception:
        return 0


def _layer_alive(lock: Path, heartbeat: Path, script_needle: str) -> bool:
    """True if the *correct* process is running, or heartbeat is very fresh."""
    pid = _read_lock_pid(lock)
    if pid and pid_matches_script(pid, script_needle):
        # Also require heartbeat not ancient (process hung without dying)
        age = heartbeat_age_sec(heartbeat)
        if age < max(HB_DEAD_SEC * 3, 300):
            return True
        # Process exists but has not heartbeated for a long time — treat as dead.
        _log(
            f"layer hung pid={pid} script={script_needle} hb_age={age:.0f}s — treating dead"
        )
        return False
    # No live matching process — only grace for a just-spawned layer.
    return heartbeat_age_sec(heartbeat) < SPAWN_GRACE_SEC


def _clear_dead_lock(lock: Path, script_needle: str = "") -> None:
    pid = _read_lock_pid(lock)
    if pid and (
        pid_matches_script(pid, script_needle) if script_needle else pid_is_alive(pid)
    ):
        return
    try:
        lock.unlink(missing_ok=True)
    except OSError:
        pass


def _venv_env() -> dict[str, str]:
    env = dict(os.environ)
    venv = ROOT / ".venv"
    site = venv / "Lib" / "site-packages"
    scripts = venv / "Scripts"
    if venv.is_dir():
        env["VIRTUAL_ENV"] = str(venv)
        env["PATH"] = str(scripts) + os.pathsep + env.get("PATH", "")
    parts = [str(ROOT)]
    if site.is_dir():
        parts.append(str(site))
    prev = env.get("PYTHONPATH", "")
    if prev:
        parts.append(prev)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("FINANCE_SPLIT_PIPELINES", "1")
    env.setdefault("FINANCE_AGENT_SUBPROCESS", "1")
    return env


def _start_supervisor() -> None:
    _clear_dead_lock(SUPERVISOR_LOCK, "finance_supervisor.py")
    pyw = resolve_pythonw()
    _log(f"Starting finance_supervisor via {pyw}")
    spawn_detached([str(pyw), str(SUPERVISOR_SCRIPT)], cwd=ROOT)


def _start_watchdog() -> None:
    _clear_dead_lock(WATCHDOG_LOCK, "pipeline_watchdog.py")
    pyw = resolve_pythonw()
    _log(f"Starting pipeline_watchdog via {pyw}")
    spawn_detached(
        [str(pyw), str(WATCHDOG_SCRIPT), "--check-sec", "8"],
        cwd=ROOT,
    )


def _start_worker() -> None:
    _clear_dead_lock(WORKER_LOCK, "etrade_worker.py")
    pyw = resolve_pythonw()
    # Prefer pythonw for service (no console). Use same env as process_guard.
    _log(f"Starting etrade_worker --service via {pyw}")
    env = _venv_env()
    kwargs: dict = {
        "cwd": str(ROOT),
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000 | 0x00000200  # NO_WINDOW | NEW_PROCESS_GROUP
    subprocess.Popen(
        [str(pyw), str(WORKER_SCRIPT), "--service"],
        **kwargs,
    )


def _clear_stuck_pipeline_flag() -> None:
    try:
        if not STATE.exists():
            return
        state = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(state, dict) or not state.get("pipeline_active"):
        return
    try:
        age = time.time() - float(state.get("pipeline_progress_at") or 0)
    except Exception:
        age = 9_999.0
    if age < STUCK_PIPELINE_SEC:
        return
    # Only clear if worker is dead OR progress frozen far too long with no child.
    if _layer_alive(WORKER_LOCK, WORKER_HEARTBEAT) and age < STUCK_PIPELINE_SEC * 2:
        return
    prog = state.get("pipeline_progress") or "?"
    _log(f"Clearing stuck pipeline_active (age={age:.0f}s progress={prog})")
    state.pop("pipeline_active", None)
    state.pop("pipeline_progress", None)
    state.pop("pipeline_progress_at", None)
    try:
        state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:
        pass


def _acquire() -> bool:
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.kernel32.SetLastError(0)
            handle = ctypes.windll.kernel32.CreateMutexW(
                None, False, "Local\\FinanceProcessContinuumWatchdog"
            )
            if int(ctypes.windll.kernel32.GetLastError()) == 183:
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                return False
            global _MUTEX  # noqa: PLW0603
            _MUTEX = int(handle) if handle else None
        except Exception as exc:
            _log(f"mutex note: {exc}")
    try:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        if CONTINUUM_LOCK.exists():
            old = _read_lock_pid(CONTINUUM_LOCK)
            if old and old != os.getpid() and pid_matches_script(
                old, "process_continuum_watchdog.py"
            ):
                return False
            try:
                CONTINUUM_LOCK.unlink(missing_ok=True)
            except OSError:
                pass
        CONTINUUM_LOCK.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except OSError:
        return True


_MUTEX: int | None = None


def main() -> int:
    if not _acquire():
        return 0

    _log(f"Process continuum watchdog UP pid={os.getpid()}")
    # Cooldown map so we do not respawn every CHECK_SEC while a process boots.
    last_spawn: dict[str, float] = {}
    cooldown = 35.0

    while True:
        try:
            write_heartbeat(CONTINUUM_HB, pid=os.getpid(), extra="ok")
            try:
                CONTINUUM_LOCK.write_text(str(os.getpid()), encoding="utf-8")
            except OSError:
                pass

            now = time.time()

            # 1) Supervisor
            if not _layer_alive(
                SUPERVISOR_LOCK, SUPERVISOR_HEARTBEAT, "finance_supervisor.py"
            ):
                if now - last_spawn.get("supervisor", 0) >= cooldown:
                    _log(
                        f"supervisor dead "
                        f"(hb={heartbeat_age_sec(SUPERVISOR_HEARTBEAT):.0f}s) - restart"
                    )
                    _start_supervisor()
                    last_spawn["supervisor"] = now
                    time.sleep(3)

            # 2) Pipeline watchdog (also started by supervisor; we fill gaps)
            if not _layer_alive(
                WATCHDOG_LOCK, WATCHDOG_HEARTBEAT, "pipeline_watchdog.py"
            ):
                if now - last_spawn.get("watchdog", 0) >= cooldown:
                    _log(
                        f"pipeline_watchdog dead "
                        f"(hb={heartbeat_age_sec(WATCHDOG_HEARTBEAT):.0f}s) - restart"
                    )
                    _start_watchdog()
                    last_spawn["watchdog"] = now
                    time.sleep(3)

            # 3) Worker — most important for UI + trading continuity
            if not _layer_alive(WORKER_LOCK, WORKER_HEARTBEAT, "etrade_worker.py"):
                if now - last_spawn.get("worker", 0) >= cooldown:
                    _log(
                        f"etrade_worker dead "
                        f"(hb={heartbeat_age_sec(WORKER_HEARTBEAT):.0f}s) - restart"
                    )
                    _clear_stuck_pipeline_flag()
                    _start_worker()
                    last_spawn["worker"] = now
                    time.sleep(5)
            else:
                _clear_stuck_pipeline_flag()

        except KeyboardInterrupt:
            _log("KeyboardInterrupt — exiting")
            break
        except BaseException as exc:
            _log(f"loop error: {exc}")
            time.sleep(5)
            continue

        time.sleep(CHECK_SEC)

    try:
        if _read_lock_pid(CONTINUUM_LOCK) == os.getpid():
            CONTINUUM_LOCK.unlink(missing_ok=True)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    # Outer immortal shell — OS task re-launches us if this dies completely.
    while True:
        try:
            code = main()
            if code == 0:
                # Clean exit (another instance holds mutex)
                raise SystemExit(0)
        except SystemExit:
            raise
        except BaseException as exc:
            try:
                _log(f"continuum crashed hard: {exc} — respawn in 5s")
            except Exception:
                pass
            time.sleep(5)
