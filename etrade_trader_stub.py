"""Frozen launcher entry — opens Unified Trader (standalone long app removed)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.chdir(ROOT)
from unified_trader_gui import main

if __name__ == "__main__":
    raise SystemExit(main())
