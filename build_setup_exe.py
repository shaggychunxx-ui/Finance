#!/usr/bin/env python3
"""Build a lean ETrade Unified Trader Setup.exe for another PC.

Payload is app source only (no secrets, no .venv, no history). Target PC needs
Python 3.10+ — Grok (or the user) can install Python, then run Setup.

Output (Desktop):
  ETradeUnifiedTrader-Setup.exe
  ETrade Trader Install.zip  (same payload, unzip-only option)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DESKTOP = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"

EXCLUDE_DIRS = {
    ".venv",
    "__pycache__",
    "output",
    "build",
    "dist",
    ".git",
    "node_modules",
    ".pytest_cache",
    "_restored",
}
EXCLUDE_FILES = {
    "etrade_config.json",
    "etrade_tokens.json",
    "short_etrade_config.json",
    "config.json",
    "oauth_pending.json",
    "ui_prefs.json",
    "ETrade Trader.exe",
    "ETrade Trader.new.exe",
    "package_etrade_install.ps1",
    "build_setup_exe.py",
    "build_etrade_launcher.py",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log", ".lock", ".db", ".spec"}


def should_skip(rel: Path, is_dir: bool) -> bool:
    parts = set(rel.parts)
    if parts & EXCLUDE_DIRS:
        return True
    if is_dir:
        return False
    name = rel.name
    if name in EXCLUDE_FILES:
        return True
    if rel.suffix.lower() in EXCLUDE_SUFFIXES:
        return True
    return False


def copy_tree(src: Path, dst: Path) -> int:
    count = 0
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        rel = Path(item.name)
        if should_skip(rel, item.is_dir()):
            continue
        target = dst / item.name
        if item.is_dir():
            count += copy_tree_recursive(item, target, Path(item.name))
        else:
            shutil.copy2(item, target)
            count += 1
    return count


def copy_tree_recursive(src: Path, dst: Path, rel: Path) -> int:
    count = 0
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        child_rel = rel / item.name
        if should_skip(child_rel, item.is_dir()):
            continue
        target = dst / item.name
        if item.is_dir():
            count += copy_tree_recursive(item, target, child_rel)
        else:
            shutil.copy2(item, target)
            count += 1
    return count


def write_install_readme(stage: Path) -> None:
    text = f"""E*TRADE Unified Trader — Install Package
========================================

This package does NOT include API keys, tokens, or trade history.

REQUIREMENTS (other PC)
-----------------------
- Windows 10/11
- Python 3.10+ (https://www.python.org/downloads/)
  During install, check "Add python.exe to PATH" and include tcl/tk (default).

INSTALL
-------
Option A — Setup.exe
  1. Run ETradeUnifiedTrader-Setup.exe
  2. Choose install folder (default: %LOCALAPPDATA%\\Programs\\ETrade Unified Trader)
  3. Setup creates a local .venv, installs deps, desktop shortcut

Option B — ZIP
  1. Unzip ETrade-Trader folder anywhere
  2. Run Install ETrade Trader.bat
  3. Launch "ETrade Unified Trader" from the desktop

AFTER INSTALL
-------------
1. Edit etrade_config.json (and optional short_etrade_config.json) with your
   E*TRADE developer consumer key/secret (https://developer.etrade.com)
2. Open the app → Settings → Connect → pick account
3. Start in Sandbox / practice (dry run) before live trading
4. Optional: Install ETrade Background.bat for headless worker

Packaged: {date.today().isoformat()}
"""
    (stage / "INSTALL.txt").write_text(text, encoding="utf-8")


def stage_payload(stage_root: Path) -> int:
    if stage_root.exists():
        shutil.rmtree(stage_root, ignore_errors=True)
    n = copy_tree(ROOT, stage_root)
    write_install_readme(stage_root)
    # Ensure example configs exist for first-run copy
    for example, target in (
        ("etrade_config.example.json", "etrade_config.json"),
        ("short_etrade_config.example.json", "short_etrade_config.json"),
    ):
        src = stage_root / example
        dst = stage_root / target
        if src.exists() and not dst.exists():
            # Do not pre-create secrets file in package; install script copies
            pass
    # Ship robust installer scripts
    installer_ps1 = ROOT / "Install-ETrade-Unified-Trader.ps1"
    if installer_ps1.exists():
        shutil.copy2(installer_ps1, stage_root / installer_ps1.name)
    return n


def zip_payload(stage_root: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in stage_root.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(stage_root.parent).as_posix())


def write_installer_entry(build_dir: Path, payload_zip: Path) -> Path:
    """Small setup UI: extract payload, run install script, make shortcuts."""
    entry = build_dir / "setup_entry.py"
    # Embed path relative to frozen exe later via --add-data
    entry.write_text(
        r'''#!/usr/bin/env python3
"""ETrade Unified Trader Setup — extract payload and run install."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import tkinter as tk
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


def resource_path(name: str) -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / name
    return Path(__file__).resolve().parent / name


def default_install_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "Programs" / "ETrade Unified Trader"


def find_payload() -> Path:
    for candidate in (
        resource_path("payload.zip"),
        Path(sys.executable).resolve().parent / "payload.zip",
        Path(__file__).resolve().parent / "payload.zip",
    ):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("payload.zip not found next to Setup or inside the bundle")


def extract_payload(zip_path: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest)
    # Payload root is ETrade-Trader/
    nested = dest / "ETrade-Trader"
    if nested.is_dir():
        return nested
    return dest


def run_install(app_root: Path) -> int:
    ps1 = app_root / "Install-ETrade-Unified-Trader.ps1"
    bat = app_root / "Install ETrade Trader.bat"
    if ps1.is_file():
        cmd = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ps1),
            "-InstallDir",
            str(app_root),
            "-InPlace",
        ]
        return subprocess.call(cmd, cwd=str(app_root))
    if bat.is_file():
        return subprocess.call(["cmd", "/c", str(bat)], cwd=str(app_root))
    raise FileNotFoundError("No install script found in package")


class SetupApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ETrade Unified Trader Setup")
        self.geometry("560x320")
        self.resizable(False, False)
        self.install_var = tk.StringVar(value=str(default_install_dir()))
        self.status_var = tk.StringVar(value="Ready. Python 3.10+ must be installed on this PC.")

        pad = {"padx": 16, "pady": 8}
        ttk.Label(
            self,
            text="Install E*TRADE Unified Trader",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w", **pad)
        ttk.Label(
            self,
            text="Lean install: app files only. Creates a local .venv and desktop shortcut.\n"
            "Does not copy API keys or trading history.",
            justify="left",
        ).pack(anchor="w", padx=16)

        row = ttk.Frame(self)
        row.pack(fill="x", padx=16, pady=12)
        ttk.Label(row, text="Install folder:").pack(side="left")
        ttk.Entry(row, textvariable=self.install_var, width=48).pack(side="left", padx=8)
        ttk.Button(row, text="Browse…", command=self.browse).pack(side="left")

        ttk.Label(self, textvariable=self.status_var, wraplength=520).pack(anchor="w", padx=16, pady=8)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=16, pady=16)
        ttk.Button(btns, text="Install", command=self.install).pack(side="right", padx=4)
        ttk.Button(btns, text="Close", command=self.destroy).pack(side="right", padx=4)

    def browse(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.install_var.get() or str(Path.home()))
        if chosen:
            self.install_var.set(chosen)

    def install(self) -> None:
        dest = Path(self.install_var.get().strip())
        if not dest.parts:
            messagebox.showerror("Setup", "Choose an install folder.")
            return
        try:
            self.status_var.set("Extracting…")
            self.update_idletasks()
            payload = find_payload()
            staging = Path(tempfile.mkdtemp(prefix="etrade-setup-"))
            try:
                app_root = extract_payload(payload, staging)
                dest.mkdir(parents=True, exist_ok=True)
                # Copy extracted app into destination (merge)
                for item in app_root.iterdir():
                    target = dest / item.name
                    if item.is_dir():
                        if target.exists():
                            shutil.rmtree(target)
                        shutil.copytree(item, target)
                    else:
                        shutil.copy2(item, target)
                self.status_var.set("Running install (venv + shortcuts)…")
                self.update_idletasks()
                code = run_install(dest)
            finally:
                shutil.rmtree(staging, ignore_errors=True)
            if code != 0:
                self.status_var.set(f"Install finished with exit code {code}. See console or INSTALL.txt.")
                messagebox.showwarning(
                    "Setup",
                    f"Install returned code {code}.\n\n"
                    "If Python is missing, install Python 3.10+ from python.org\n"
                    "(Add to PATH, include tcl/tk), then run Setup again\n"
                    f"or run Install ETrade Trader.bat in:\n{dest}",
                )
                return
            self.status_var.set(f"Installed to {dest}")
            messagebox.showinfo(
                "Setup",
                "Install complete.\n\n"
                "Next:\n"
                "1. Edit etrade_config.json with your E*TRADE API keys\n"
                "2. Launch ETrade Unified Trader from the desktop\n"
                "3. Settings → Connect (start in Sandbox / practice)",
            )
        except Exception as exc:
            self.status_var.set(str(exc))
            messagebox.showerror("Setup failed", str(exc))


def main() -> int:
    # Unattended: ETradeUnifiedTrader-Setup.exe /S [dir]
    if len(sys.argv) >= 2 and sys.argv[1] in {"/S", "/silent", "--silent"}:
        dest = Path(sys.argv[2]) if len(sys.argv) >= 3 else default_install_dir()
        payload = find_payload()
        staging = Path(tempfile.mkdtemp(prefix="etrade-setup-"))
        try:
            app_root = extract_payload(payload, staging)
            dest.mkdir(parents=True, exist_ok=True)
            for item in app_root.iterdir():
                target = dest / item.name
                if item.is_dir():
                    if target.exists():
                        shutil.rmtree(target)
                    shutil.copytree(item, target)
                else:
                    shutil.copy2(item, target)
            return run_install(dest)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    app = SetupApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
        encoding="utf-8",
    )
    return entry


def build_setup_exe(entry: Path, payload_zip: Path, out_exe: Path) -> None:
    py = VENV_PY if VENV_PY.is_file() else Path(sys.executable)
    subprocess.check_call([str(py), "-m", "pip", "install", "pyinstaller", "-q"])
    work = ROOT / "build" / "setup_work"
    dist = ROOT / "build" / "setup_dist"
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    if dist.exists():
        shutil.rmtree(dist, ignore_errors=True)

    icon = ROOT / "etrade_trader.ico"
    if not icon.is_file():
        icon = ROOT / "etrade_short_trader.ico"
    if not icon.is_file():
        icon = ROOT / "app_icon.ico"

    # PyInstaller --add-data: Windows uses semicolon
    add_data = f"{payload_zip}{os.pathsep}."
    cmd = [
        str(py),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name",
        "ETradeUnifiedTrader-Setup",
        "--distpath",
        str(dist),
        "--workpath",
        str(work),
        "--specpath",
        str(ROOT / "build"),
        "--add-data",
        add_data,
    ]
    if icon.is_file():
        cmd.extend(["--icon", str(icon)])
    cmd.append(str(entry))
    subprocess.check_call(cmd, cwd=str(ROOT))

    built = dist / "ETradeUnifiedTrader-Setup.exe"
    if not built.is_file():
        raise FileNotFoundError(f"PyInstaller did not produce {built}")
    DESKTOP.mkdir(parents=True, exist_ok=True)
    if out_exe.exists():
        out_exe.unlink()
    shutil.copy2(built, out_exe)


def main() -> int:
    print("Staging clean payload (no secrets / no .venv)…")
    with tempfile.TemporaryDirectory(prefix="etrade-stage-") as tmp:
        tmp_path = Path(tmp)
        stage_root = tmp_path / "ETrade-Trader"
        n = stage_payload(stage_root)
        print(f"  staged {n} files")

        zip_path = DESKTOP / "ETrade Trader Install.zip"
        print(f"Writing {zip_path}…")
        zip_payload(stage_root, zip_path)
        zip_mb = zip_path.stat().st_size / (1024 * 1024)
        print(f"  zip {zip_mb:.2f} MB")

        # Payload for embedded setup: same zip
        payload_for_exe = tmp_path / "payload.zip"
        shutil.copy2(zip_path, payload_for_exe)

        build_dir = ROOT / "build" / "setup_src"
        build_dir.mkdir(parents=True, exist_ok=True)
        entry = write_installer_entry(build_dir, payload_for_exe)
        # Copy payload next to entry for non-frozen tests and for --add-data source
        shutil.copy2(payload_for_exe, build_dir / "payload.zip")

        out_exe = DESKTOP / "ETradeUnifiedTrader-Setup.exe"
        print(f"Building {out_exe.name} with PyInstaller…")
        build_setup_exe(entry, build_dir / "payload.zip", out_exe)
        exe_mb = out_exe.stat().st_size / (1024 * 1024)
        print(f"  exe {exe_mb:.2f} MB")

    print()
    print("Done.")
    print(f"  Setup EXE : {DESKTOP / 'ETradeUnifiedTrader-Setup.exe'}")
    print(f"  ZIP       : {DESKTOP / 'ETrade Trader Install.zip'}")
    print("On the other PC: install Python 3.10+ (Add to PATH), then run Setup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
