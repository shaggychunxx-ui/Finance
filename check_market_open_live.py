#!/usr/bin/env python3
"""Market-open live gate: fail loudly if session is dead during US RTH.

Run from Task Scheduler around 9:25 / 9:35 / 10:00 ET (or every 15 min RTH).
Exit codes:
  0 = LIVE STATUS OK (or market closed — nothing to do)
  1 = market open but NOT live / session dead
  2 = config/runtime error
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent


def _is_rth(now: datetime | None = None) -> bool:
    try:
        et = now or datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        et = datetime.utcnow()
    if et.weekday() >= 5:
        return False
    mins = et.hour * 60 + et.minute
    return (9 * 60 + 30) <= mins < (16 * 60)


def main() -> int:
    if not _is_rth():
        print("Market closed (or outside RTH) — no open-gate action.")
        return 0

    check = ROOT / "check_etrade_live_status.py"
    py = sys.executable
    proc = subprocess.run([py, str(check)], cwd=str(ROOT), capture_output=True, text=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    print(out)
    blocker = ROOT / "output" / "LIVE_BLOCKER.txt"
    if proc.returncode != 0 or "LIVE STATUS: OK" not in out:
        # Ensure blocker file exists for watchers / human
        if not blocker.exists():
            blocker.parent.mkdir(parents=True, exist_ok=True)
            blocker.write_text(
                "LIVE BLOCKER\n"
                f"time: {datetime.now().isoformat()}\n"
                "reason: market open but check_etrade_live_status did not return OK\n"
                "fix: python begin_etrade_login.py then finish_etrade_login.py <CODE>\n",
                encoding="utf-8",
            )
        print("OPEN GATE FAIL — live trading cannot function until OAuth is fixed.")
        return 1
    if blocker.exists():
        try:
            blocker.unlink()
        except OSError:
            pass
    print("OPEN GATE OK — live session healthy during RTH.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
