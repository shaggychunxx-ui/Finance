"""Shared process-survival helpers for Finance background services.

Windows process trees and Job Objects can take whole trees down. These flags
and heartbeat paths keep supervisor / watchdog / worker independently restartable.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"

WORKER_LOCK = OUTPUT / "etrade_worker.lock"
WORKER_HEARTBEAT = OUTPUT / "etrade_worker_heartbeat.txt"
WATCHDOG_LOCK = OUTPUT / "pipeline_watchdog.lock"
WATCHDOG_HEARTBEAT = OUTPUT / "pipeline_watchdog_heartbeat.txt"
SUPERVISOR_LOCK = OUTPUT / "finance_supervisor.lock"
SUPERVISOR_HEARTBEAT = OUTPUT / "finance_supervisor_heartbeat.txt"

CREATE_BREAKAWAY_FROM_JOB = 0x01000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000


def detached_creationflags() -> int:
    """No console window. Skip BREAKAWAY_FROM_JOB — can raise Access Denied (WinError 5).

    Do not combine DETACHED_PROCESS with redirected stdio — that combo is unreliable.
    """
    if os.name != "nt":
        return 0
    return CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW


def resolve_pythonw() -> Path:
    """Prefer base pythonw.exe (no venv re-exec stub that doubles processes/flashes)."""
    # sys.base_prefix is the real install even when running under a venv
    for base in (getattr(sys, "base_prefix", None), getattr(sys, "real_prefix", None), sys.prefix):
        if not base:
            continue
        cand = Path(base) / "pythonw.exe"
        if cand.exists():
            return cand
    venv_w = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if venv_w.exists():
        return venv_w
    here = Path(sys.executable).with_name("pythonw.exe")
    if here.exists():
        return here
    return Path(sys.executable)


def venv_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Env so base pythonw still sees the Finance venv packages."""
    env = dict(base or os.environ)
    venv = ROOT / ".venv"
    site = venv / "Lib" / "site-packages"
    scripts = venv / "Scripts"
    if venv.is_dir():
        env["VIRTUAL_ENV"] = str(venv)
        env["PATH"] = str(scripts) + os.pathsep + env.get("PATH", "")
    path_parts = [str(ROOT)]
    if site.is_dir():
        path_parts.append(str(site))
    prev = env.get("PYTHONPATH", "")
    if prev:
        path_parts.append(prev)
    env["PYTHONPATH"] = os.pathsep.join(path_parts)
    # Prevent pythonw from trying to open a console for prints
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _hidden_startupinfo():
    if os.name != "nt":
        return None
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        return si
    except Exception:
        return None


def spawn_detached(argv: list[str], *, cwd: Path | None = None) -> subprocess.Popen:
    """Start a long-lived process with no console window."""
    run_argv = list(argv)
    env = venv_env()
    if os.name == "nt" and run_argv:
        exe = str(run_argv[0]).lower()
        if "python" in Path(exe).name:
            run_argv[0] = str(resolve_pythonw())
    kwargs: dict = {
        "cwd": str(cwd or ROOT),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
        "env": env,
    }
    if os.name == "nt":
        kwargs["creationflags"] = detached_creationflags()
        si = _hidden_startupinfo()
        if si is not None:
            kwargs["startupinfo"] = si
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(run_argv, **kwargs)


def write_heartbeat(path: Path, *, pid: int | None = None, extra: str = "") -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        pid = int(pid or os.getpid())
        line = f"{pid}\n{time.time():.3f}\n{extra}\n"
        path.write_text(line, encoding="utf-8")
        # Nudge mtime for VBS DateLastModified checks
        os.utime(path, None)
    except OSError:
        pass


def read_heartbeat(path: Path) -> tuple[int, float]:
    try:
        if not path.exists():
            return 0, 0.0
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        pid = int(float(lines[0].strip())) if lines else 0
        ts = float(lines[1].strip()) if len(lines) > 1 else 0.0
        return pid, ts
    except Exception:
        return 0, 0.0


def heartbeat_age_sec(path: Path) -> float:
    _, ts = read_heartbeat(path)
    if ts <= 0:
        try:
            if path.exists():
                return max(0.0, time.time() - path.stat().st_mtime)
        except OSError:
            pass
        return 9_999.0
    return max(0.0, time.time() - ts)


def pid_is_python(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
            )
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def kill_tree(pid: int) -> None:
    if pid <= 0 or pid == os.getpid():
        return
    try:
        if os.name == "nt":
            # Use CREATE_NO_WINDOW for taskkill itself so no console flashes
            flags = CREATE_NO_WINDOW
            si = _hidden_startupinfo()
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=25,
                check=False,
                creationflags=flags,
                startupinfo=si,
            )
        else:
            os.kill(pid, 9)
    except Exception:
        pass
