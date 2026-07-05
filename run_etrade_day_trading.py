#!/usr/bin/env python3
"""Scheduled day-trading task entry point."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from etrade_worker import run_day_trading_cycle

if __name__ == "__main__":
    raise SystemExit(run_day_trading_cycle())