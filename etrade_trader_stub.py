"""Frozen launcher entry — runs the GUI in-process so the taskbar shows ETrade Trader.exe."""

from __future__ import annotations

import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent

os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["ETRADE_TRADER_VENV"] = "1"

from win_app_identity import apply_windows_app_identity

apply_windows_app_identity()

from etrade_trader_gui import main

if __name__ == "__main__":
    raise SystemExit(main())