"""Open a URL in Google Chrome on the interactive desktop (Windows).

Uses wscript + WScript.Shell.Run with window style 1 (normal/focused).
Plain subprocess.Popen of chrome.exe from automation often fails to keep a
window the user can see; shell Run matches double-click / Task Scheduler UX.
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


def open_url_chrome(url: str, *, profile_dir: Path | None = None) -> dict:
    chrome = chrome_exe()
    if not chrome:
        return {"ok": False, "error": "chrome.exe not found", "url": url}

    before = _chrome_pids()
    if profile_dir is not None:
        profile_dir.mkdir(parents=True, exist_ok=True)
        cmd = (
            f'"{chrome}" --user-data-dir="{profile_dir}" '
            f"--no-first-run --no-default-browser-check "
            f'--new-window --start-maximized "{url}"'
        )
    else:
        cmd = f'"{chrome}" --new-window --start-maximized "{url}"'

    method = None
    launched = False
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
        launched = True
        method = "wscript.shell.run.style1"
    except Exception as exc:
        method = f"wscript_failed:{exc}"

    if not launched:
        try:
            subprocess.Popen(
                [
                    "cmd.exe",
                    "/c",
                    "start",
                    "",
                    str(chrome),
                    "--new-window",
                    "--start-maximized",
                    url,
                ],
            )
            launched = True
            method = "cmd.start"
        except Exception as exc:
            return {"ok": False, "error": str(exc), "method": method, "url": url}

    visible_titles: list[str] = []
    count = 0
    for _ in range(24):
        time.sleep(0.5)
        count = len(_chrome_pids())
        visible_titles = _visible_chrome_titles()
        if any(
            ("etrade" in t.lower())
            or ("log on" in t.lower())
            or ("authorize" in t.lower())
            for t in visible_titles
        ):
            break

    return {
        "ok": bool(count > 0 or visible_titles),
        "method": method,
        "chrome": str(chrome),
        "url": url,
        "chrome_process_count": count,
        "visible_titles": visible_titles,
        "new_pids": sorted(_chrome_pids() - before),
        "launched": launched,
    }


def _chrome_pids() -> set[int]:
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/FO", "CSV", "/NH"],
            text=True,
            errors="ignore",
            timeout=10,
        )
        pids: set[int] = set()
        for line in out.splitlines():
            parts = [p.strip('"') for p in line.split(",")]
            if len(parts) >= 2 and parts[0].lower() == "chrome.exe":
                try:
                    pids.add(int(parts[1]))
                except ValueError:
                    pass
        return pids
    except Exception:
        return set()


def _visible_chrome_titles() -> list[str]:
    titles: list[str] = []
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        IsWindowVisible = user32.IsWindowVisible
        GetWindowTextW = user32.GetWindowTextW
        GetWindowTextLengthW = user32.GetWindowTextLengthW
        GetWindowThreadProcessId = user32.GetWindowThreadProcessId
        chrome_pids = _chrome_pids()
        if not chrome_pids:
            return []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def _cb(hwnd, _lparam):
            if not IsWindowVisible(hwnd):
                return True
            proc_id = wintypes.DWORD()
            GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
            if int(proc_id.value) not in chrome_pids:
                return True
            n = GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            GetWindowTextW(hwnd, buf, n + 1)
            t = buf.value.strip()
            if t:
                titles.append(t)
            return True

        user32.EnumWindows(_cb, 0)
    except Exception:
        pass
    return titles


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: open_chrome_url.py <url> [profile_dir]")
        raise SystemExit(2)
    u = sys.argv[1]
    prof = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    result = open_url_chrome(u, profile_dir=prof)
    print(result)
    raise SystemExit(0 if result.get("ok") else 1)
