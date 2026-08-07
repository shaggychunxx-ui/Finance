"""Open a URL in the user's normal Google Chrome profile (taskbar session).

CRITICAL:
  - Never use --user-data-dir (that is a blank profile with no logins).
  - Never use --new-window (spawns extra windows).
  - If Chrome is already running, chrome.exe <url> hands off to that process
    and opens a tab in the same profile the user is logged into.
  - Open at most once per call.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def chrome_exe() -> Path | None:
    for p in (
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Google/Chrome/Application/chrome.exe",
    ):
        if p.is_file():
            return p
    return None


def chrome_running() -> bool:
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/FO", "CSV", "/NH"],
            text=True,
            errors="ignore",
            timeout=10,
        )
        return "chrome.exe" in out.lower() and "no tasks" not in out.lower()
    except Exception:
        return False


def open_url_chrome(url: str, **_ignored) -> dict:
    """Open url in DEFAULT Chrome profile only. profile_dir kwargs are ignored on purpose."""
    chrome = chrome_exe()
    if not chrome:
        return {"ok": False, "error": "chrome.exe not found", "url": url}

    before_running = chrome_running()

    # Default profile only — same as double-clicking a link / yesterday's webbrowser path.
    # No --user-data-dir, no --new-window, no --start-maximized profile fork.
    cmd = f'"{chrome}" "{url}"'
    method = "wscript.default_profile.once"
    try:
        vbs = Path(os.environ.get("TEMP", str(Path.home()))) / "finance_open_chrome_once.vbs"
        esc = cmd.replace('"', '""')
        vbs.write_text(
            'Set sh = CreateObject("WScript.Shell")\r\n'
            f'sh.Run "{esc}", 1, False\r\n',
            encoding="utf-8",
        )
        subprocess.run(
            ["wscript.exe", "//Nologo", str(vbs)],
            check=False,
            timeout=20,
        )
    except Exception as exc:
        try:
            # Fallback: same default profile via cmd start
            subprocess.Popen(["cmd.exe", "/c", "start", "", str(chrome), url])
            method = f"cmd.start_fallback_after:{exc}"
        except Exception as exc2:
            return {"ok": False, "error": str(exc2), "method": method, "url": url}

    # Brief settle — existing Chrome reuses process quickly
    time.sleep(2.0)
    running = chrome_running()
    return {
        "ok": running,
        "method": method,
        "chrome": str(chrome),
        "url": url,
        "default_profile": True,
        "new_window": False,
        "user_data_dir": None,
        "chrome_was_running_before": before_running,
        "chrome_running_after": running,
        "launched": True,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: open_chrome_url.py <url>")
        raise SystemExit(2)
    # Ignore any legacy profile_dir arg so callers don't fork a blank profile.
    result = open_url_chrome(sys.argv[1])
    print(result)
    raise SystemExit(0 if result.get("ok") else 1)
