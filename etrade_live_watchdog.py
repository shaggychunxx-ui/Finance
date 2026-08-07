#!/usr/bin/env python3
"""E*TRADE RTH live watchdog — MUST NOT silently stay down during market hours.

Every run (schedule every 1 min):
  1) If outside US RTH → exit 0 (quiet)
  2) Probe session (list-accounts / keepalive)
  3) If OK → clear blockers, exit 0
  4) If FAIL → diagnose + auto-repair:
       - ensure worker process running
       - ensure phone_bridge listening :8787
       - re-probe
  5) If still FAIL → write LIVE_BLOCKER + NEED_HUMAN_OAUTH, open Chrome authorize URL
     (only when dead — never start OAuth while live)

Exit: 0 ok/closed, 1 down needs human OAuth, 2 hard error
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# Always see Finance .venv packages (requests/oauthlib) even when launched via
# base pythonw without PYTHONPATH — otherwise probes false-fail as API down.
try:
    from process_guard import ensure_finance_packages

    ensure_finance_packages()
except Exception:
    site = ROOT / ".venv" / "Lib" / "site-packages"
    if site.is_dir() and str(site) not in sys.path:
        sys.path.insert(0, str(site))

LOG = ROOT / "output" / "live_watchdog.log"
BLOCKER = ROOT / "output" / "LIVE_BLOCKER.txt"
NEED_OAUTH = ROOT / "output" / "NEED_HUMAN_OAUTH.txt"
PENDING_OAUTH = ROOT / "output" / "oauth_pending.json"
# Marker: last time we opened a browser for OAuth. Prevents spam every 1 min.
OAUTH_OPENED_MARK = ROOT / "output" / "oauth_browser_opened.txt"
# Reuse pending request token this long (do not --force a new one / re-open browser).
PENDING_REUSE_SEC = 20 * 60
# Hard floor: never open browser more often than this even if pending missing.
BROWSER_OPEN_COOLDOWN_SEC = 15 * 60


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _is_rth() -> bool:
    try:
        from zoneinfo import ZoneInfo

        et = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        # Fallback: treat local as rough; prefer ET when tzdata present
        et = datetime.now()
    if et.weekday() >= 5:
        return False
    mins = et.hour * 60 + et.minute
    # Pre-open 9:00 ET through close 16:00 — catch death before the open too
    return (9 * 60) <= mins < (16 * 60)


def _py() -> str:
    """Base install python (not venv launcher) — still prefer quiet helpers."""
    try:
        from process_guard import resolve_pythonw

        # resolve_pythonw returns pythonw; for rare cases that need python.exe:
        p = resolve_pythonw()
        pe = p.with_name("python.exe")
        return str(pe if pe.exists() else p)
    except Exception:
        venv = ROOT / ".venv" / "Scripts" / "python.exe"
        return str(venv) if venv.exists() else sys.executable


def _pyw() -> str:
    try:
        from process_guard import resolve_pythonw

        return str(resolve_pythonw())
    except Exception:
        venv = ROOT / ".venv" / "Scripts" / "pythonw.exe"
        return str(venv) if venv.exists() else _py()


def _process_running(needle: str) -> bool:
    """True if any process command line contains needle (no PowerShell — no console flash)."""
    try:
        from process_guard import pid_command_line, pid_is_alive
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        TH32CS_SNAPPROCESS = 0x00000002

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        CreateToolhelp32Snapshot = kernel32.CreateToolhelp32Snapshot
        CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        Process32FirstW = kernel32.Process32FirstW
        Process32NextW = kernel32.Process32NextW
        CloseHandle = kernel32.CloseHandle

        snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snap or snap == wintypes.HANDLE(-1).value:
            return False
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            needle_l = needle.lower()
            ok = Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                name = (entry.szExeFile or "").lower()
                if "python" in name and pid_is_alive(int(entry.th32ProcessID)):
                    cmd = pid_command_line(int(entry.th32ProcessID)).lower()
                    if needle_l in cmd:
                        return True
                ok = Process32NextW(snap, ctypes.byref(entry))
        finally:
            CloseHandle(snap)
        return False
    except Exception:
        return False


def _port_listen(port: int) -> bool:
    """True if something accepts TCP on 127.0.0.1:port (no PowerShell)."""
    try:
        import socket

        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def _ensure_worker() -> None:
    if _process_running("etrade_worker.py"):
        return
    _log("REPAIR: starting etrade_worker.py --service")
    try:
        from process_guard import spawn_detached

        spawn_detached([_pyw(), str(ROOT / "etrade_worker.py"), "--service"], cwd=ROOT)
    except Exception:
        subprocess.Popen(
            [_pyw(), str(ROOT / "etrade_worker.py"), "--service"],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )


def _ensure_bridge() -> None:
    if _port_listen(8787) or _process_running("phone_bridge.py"):
        if _port_listen(8787):
            return
    _log("REPAIR: starting phone_bridge.py")
    try:
        from process_guard import spawn_detached

        spawn_detached([_pyw(), str(ROOT / "phone_bridge.py")], cwd=ROOT)
    except Exception:
        subprocess.Popen(
            [_pyw(), str(ROOT / "phone_bridge.py")],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )


def _probe() -> tuple[bool, str]:
    from etrade_runtime import ensure_sys_path, resolve_live_root
    from etrade_api.config import load_config
    from etrade_api.oauth import session_is_live

    decision = resolve_live_root()
    ensure_sys_path(decision.root)
    cfg = load_config(decision.config_path)
    cfg.token_path = decision.token_path
    return session_is_live(cfg)


def _check_live_status_script() -> tuple[bool, str]:
    # MUST use pythonw + CREATE_NO_WINDOW. venv python.exe re-exec flashes
    # Windows Terminal (title becomes ...\python.exe) every minute during RTH.
    try:
        from process_guard import run_python_quiet

        proc = run_python_quiet(ROOT / "check_etrade_live_status.py", timeout=90)
    except Exception:
        from process_guard import quiet_subprocess_kwargs

        kwargs = quiet_subprocess_kwargs(capture=True)
        kwargs["timeout"] = 90
        proc = subprocess.run(
            [_pyw(), str(ROOT / "check_etrade_live_status.py")],
            **kwargs,
        )
    out = (proc.stdout or "") + (proc.stderr or "")
    ok = proc.returncode == 0 and "LIVE STATUS: OK" in out
    return ok, out[-1500:]


def _write_blocker(reason: str) -> None:
    BLOCKER.parent.mkdir(parents=True, exist_ok=True)
    text = (
        "LIVE BLOCKER — E*TRADE MUST NOT BE DOWN DURING MARKET HOURS\n"
        f"time: {datetime.now().isoformat()}\n"
        f"machine: {os.environ.get('COMPUTERNAME', '')}\n"
        f"reason: {reason}\n"
        "auto: worker/bridge restart attempted; OAuth URL opened if needed\n"
        "human: finish_etrade_login.py <CODE> then verify check_etrade_live_status.py\n"
        "phone: do NOT start a second OAuth while PC is re-authing\n"
    )
    BLOCKER.write_text(text, encoding="utf-8")
    NEED_OAUTH.write_text(text, encoding="utf-8")


def _clear_blocker() -> None:
    for p in (BLOCKER, NEED_OAUTH, OAUTH_OPENED_MARK):
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass


def _pending_age_sec() -> float | None:
    try:
        if not PENDING_OAUTH.exists():
            return None
        return max(0.0, time.time() - PENDING_OAUTH.stat().st_mtime)
    except OSError:
        return None


def _browser_opened_age_sec() -> float | None:
    try:
        if not OAUTH_OPENED_MARK.exists():
            return None
        return max(0.0, time.time() - OAUTH_OPENED_MARK.stat().st_mtime)
    except OSError:
        return None


def _read_pending_url() -> str | None:
    try:
        if not PENDING_OAUTH.exists():
            return None
        import json

        return json.loads(PENDING_OAUTH.read_text(encoding="utf-8")).get("authorize_url")
    except Exception:
        return None


def _mark_browser_opened() -> None:
    try:
        OAUTH_OPENED_MARK.parent.mkdir(parents=True, exist_ok=True)
        OAUTH_OPENED_MARK.write_text(
            f"{time.time():.3f}\n{datetime.now().isoformat()}\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def _chrome_path() -> Path | None:
    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Google/Chrome/Application/chrome.exe",
    ]
    for p in candidates:
        if p and p.is_file():
            return p
    return None


def _open_browser_once(url: str) -> None:
    """Open authorize URL at most once per cooldown — Chrome only (user preference)."""
    age = _browser_opened_age_sec()
    if age is not None and age < BROWSER_OPEN_COOLDOWN_SEC:
        _log(
            f"OAUTH browser suppressed (opened {age:.0f}s ago; "
            f"cooldown {BROWSER_OPEN_COOLDOWN_SEC}s) — reuse pending code"
        )
        return
    opened = False
    chrome = _chrome_path()
    if chrome is not None:
        try:
            # Single new Chrome window — do not also call webbrowser (that opens Edge).
            subprocess.Popen(
                [str(chrome), "--new-window", "--start-maximized", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                # Do NOT use CREATE_NO_WINDOW — browser must be visible to human.
            )
            opened = True
            _log(f"OAUTH BROWSER CHROME: {url[:80]}...")
        except Exception as exc:
            _log(f"Chrome open failed: {exc}")
    if not opened:
        # Last resort: default handler (often Edge on this machine).
        try:
            webbrowser.open(url, new=1, autoraise=True)
            opened = True
            _log(f"OAUTH BROWSER FALLBACK webbrowser: {url[:80]}...")
        except Exception as exc:
            _log(f"webbrowser.open failed: {exc}")
    if opened:
        _mark_browser_opened()
        # Persist URL for manual open / Open-EtradeAuthorize-Chrome.bat
        try:
            (ROOT / "output" / "last_authorize_url.txt").write_text(url + "\n", encoding="utf-8")
        except OSError:
            pass
    else:
        _log("OAUTH browser open failed — human must open authorize_url from pending json")


def _open_oauth() -> str | None:
    """Ensure a single pending OAuth exists; open browser at most once.

    Critical: do NOT call begin_etrade_login --force every minute — that mints a
    new request token (invalidates the human's current verification code) and
    spams browser windows.
    """
    try:
        age = _pending_age_sec()
        url = _read_pending_url()
        if url and age is not None and age < PENDING_REUSE_SEC:
            _log(
                f"OAUTH pending reuse age={age:.0f}s (<{PENDING_REUSE_SEC}s) — no new token"
            )
            _open_browser_once(url)
            return url

        # Need a new request token (missing or stale pending).
        # --no-browser: we control the single browser open ourselves.
        try:
            from process_guard import run_python_quiet

            proc = run_python_quiet(
                ROOT / "begin_etrade_login.py",
                "--force",
                "--no-browser",
                timeout=60,
            )
        except Exception:
            from process_guard import quiet_subprocess_kwargs

            kwargs = quiet_subprocess_kwargs(capture=True)
            kwargs["timeout"] = 60
            proc = subprocess.run(
                [
                    _pyw(),
                    str(ROOT / "begin_etrade_login.py"),
                    "--force",
                    "--no-browser",
                ],
                **kwargs,
            )
        out = (proc.stdout or "") + (proc.stderr or "")
        url = _read_pending_url()
        if url:
            _open_browser_once(url)
            return url
        _log(f"OAUTH begin output: {out[-400:]}")
    except Exception as exc:
        _log(f"OAUTH open failed: {exc}")
    return None


def main() -> int:
    if not _is_rth():
        print("Watchdog: outside RTH window (09:00–16:00 ET) — idle.")
        return 0

    _log("RTH watchdog tick")
    try:
        ok, detail = _probe()
    except Exception as exc:
        ok, detail = False, f"probe_error: {exc}"

    if ok:
        # Double-check flags via full status script periodically
        status_ok, status_out = _check_live_status_script()
        if status_ok:
            _clear_blocker()
            _log(f"LIVE OK {detail}")
            print("WATCHDOG OK — live")
            return 0
        # Probe ok but status script unhappy (e.g. worker log stale) — still repair processes
        _log(f"Probe ok but status script not OK — repairing processes. {status_out[-200:]}")
    else:
        _log(f"LIVE FAIL: {detail}")

    # --- AUTO REPAIR ---
    _ensure_worker()
    _ensure_bridge()
    time.sleep(4)

    try:
        ok2, detail2 = _probe()
    except Exception as exc:
        ok2, detail2 = False, str(exc)

    if ok2:
        status_ok, _ = _check_live_status_script()
        if status_ok or ok2:
            _clear_blocker()
            _log(f"RECOVERED after process repair: {detail2}")
            print("WATCHDOG RECOVERED")
            return 0

    # Hard failure — human OAuth required (browser at most once; never spam)
    _write_blocker(detail2 if not ok2 else detail)
    url = _open_oauth()
    _log(f"NEEDS HUMAN OAUTH url_set={bool(url)} reason={detail2 if not ok2 else detail}")
    print(
        "WATCHDOG FAIL — need human verification code "
        "(browser opens once only; finish_etrade_login.py <CODE>)"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
