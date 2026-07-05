#!/usr/bin/env python3
"""Run one E*TRADE background cycle and exit (for Task Scheduler)."""

from __future__ import annotations

import etrade_worker

if __name__ == "__main__":
    raise SystemExit(etrade_worker.main())