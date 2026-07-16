#!/usr/bin/env python3
"""Scheduled live trading task — submit orders from the saved strategy plan."""

from __future__ import annotations

import etrade_worker

if __name__ == "__main__":
    if etrade_worker.service_already_running():
        raise SystemExit(0)
    raise SystemExit(etrade_worker.run_live_trading_cycle())