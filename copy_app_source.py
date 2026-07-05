#!/usr/bin/env python3
"""Bundle app source (no secrets) and copy to the Windows clipboard."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKIP_DIRS = {".venv", "__pycache__", "output", "build", "dist", ".git"}
SKIP_FILES = {"etrade_config.json", "etrade_tokens.json", "config.json", "copy_app_source.py"}
EXTENSIONS = {
    ".py", ".ps1", ".bat", ".vbs", ".txt", ".json", ".html", ".css", ".js", ".md"
}
SKIP_SUFFIXES = {".ico", ".jpg", ".png", ".exe", ".zip", ".lock", ".log", ".pyc"}


def should_include(path: Path) -> bool:
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    if path.name in SKIP_FILES:
        return False
    if path.suffix.lower() in SKIP_SUFFIXES:
        return False
    return path.suffix.lower() in EXTENSIONS


def build_bundle() -> str:
    files = sorted(p for p in ROOT.rglob("*") if p.is_file() and should_include(p))
    chunks = [
        "# E*TRADE Trader - Finance App Source Bundle",
        f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"# Files: {len(files)}",
        "",
    ]
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        chunks.append(f"===== FILE: {rel} =====")
        try:
            chunks.append(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
        chunks.append("")
    return "\n".join(chunks)


def copy_to_clipboard(text: str) -> bool:
    if sys.platform != "win32":
        return False
    try:
        process = subprocess.run(
            ["clip"],
            input=text,
            text=True,
            encoding="utf-8",
            check=True,
            capture_output=True,
        )
        return process.returncode == 0
    except Exception:
        return False


def main() -> int:
    bundle = build_bundle()
    lines = bundle.count("\n") + 1
    size_mb = len(bundle.encode("utf-8")) / (1024 * 1024)
    print(f"Bundle: {lines:,} lines, {size_mb:.2f} MB")

    if copy_to_clipboard(bundle):
        print("Copied full app source to clipboard.")
        return 0

    fallback = Path.home() / "Desktop" / "ETrade-Trader-Source.txt"
    fallback.write_text(bundle, encoding="utf-8")
    print(f"Clipboard copy failed or unsupported. Saved to: {fallback}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())