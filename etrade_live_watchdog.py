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

LOG = ROOT / "output" / "live_watchdog.log"
BLOCKER = ROOT / "output" / "LIVE_BLOCKER.txt"
NEED_OAUTH = ROOT / "output" / "NEED_HUMAN_OAUTH.txt"


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
    venv = ROOT / ".venv" / "Scripts" / "python.exe"
    return str(venv) if venv.exists() else sys.executable


def _pyw() -> str:
    venv = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    return str(venv) if venv.exists() else _py()


def _process_running(needle: str) -> bool:
    try:
        import subprocess as sp

        out = sp.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' OR Name='python.exe'\" "
                "| Select-Object -ExpandProperty CommandLine",
            ],
            text=True,
            timeout=30,
            stderr=sp.DEVNULL,
        )
        return needle.lower() in (out or "").lower()
    except Exception:
        return False


def _port_listen(port: int) -> bool:
    try:
        import socket

        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        # create_connection succeeds if something accepts — for LISTEN we probe differently
        pass
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-NetTCPConnection -LocalPort {port} -State Listen -EA SilentlyContinue) -ne $null",
            ],
            text=True,
            timeout=20,
            stderr=subprocess.DEVNULL,
        )
        return "True" in (out or "")
    except Exception:
        return False


def _ensure_worker() -> None:
    if _process_running("etrade_worker.py"):
        return
    _log("REPAIR: starting etrade_worker.py --service")
    subprocess.Popen(
        [_pyw(), str(ROOT / "etrade_worker.py"), "--service"],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _ensure_bridge() -> None:
    if _port_listen(8787) or _process_running("phone_bridge.py"):
        if _port_listen(8787):
            return
    _log("REPAIR: starting phone_bridge.py")
    subprocess.Popen(
        [_pyw(), str(ROOT / "phone_bridge.py")],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
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
    proc = subprocess.run(
        [_py(), str(ROOT / "check_etrade_live_status.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=90,
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
    for p in (BLOCKER, NEED_OAUTH):
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass


def _open_oauth() -> str | None:
    """Start OAuth only because session is dead. Returns authorize URL."""
    try:
        proc = subprocess.run(
            [_py(), str(ROOT / "begin_etrade_login.py"), "--force"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        pending = ROOT / "output" / "oauth_pending.json"
        if pending.exists():
            import json

            url = json.loads(pending.read_text(encoding="utf-8")).get("authorize_url")
            if url:
                try:
                    webbrowser.open(url)
                except Exception:
                    pass
                # Also try Chrome explicitly on Windows
                chrome = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe"
                if chrome.exists():
                    subprocess.Popen(
                        [str(chrome), "--new-window", "--start-maximized", url],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                _log(f"OAUTH OPENED: {url[:80]}...")
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

    # Hard failure — human OAuth required
    _write_blocker(detail2 if not ok2 else detail)
    url = _open_oauth()
    _log(f"NEEDS HUMAN OAUTH url_set={bool(url)} reason={detail2 if not ok2 else detail}")
    print("WATCHDOG FAIL — OAuth opened; paste code to finish_etrade_login.py")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
