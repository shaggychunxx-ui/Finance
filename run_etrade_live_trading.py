#!/usr/bin/env python3
"""Scheduled live trading task — submit orders from the saved strategy plan."""

from __future__ import annotations

import etrade_worker

if __name__ == "__main__":
    raise SystemExit(etrade_worker.run_live_trading_cycle())