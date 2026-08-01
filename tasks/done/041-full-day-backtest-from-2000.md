# Full day walk-forward backtest from 2000-01-01

target: AI-CODING
origin: PHONE
kind: work
handoff_count: 0
max_handoffs: 2
parent: none

## Goal

Run a slow but constant full backtest: start Jan 1 2000, no look-ahead, predict vs actual day-by-day to current date, loop forever, conserve CPU/GPU/memory, open review window before start.

## Instructions

1. Day-by-day walk-forward from 2000-01-01.
2. Signals only use bars on/before sim date; score vs realized forward returns.
3. When current date reached, restart from 2000-01-01.
4. Low process priority; capped symbols/agents; sleep between days.
5. Open review summary window on AI-CODING before starting.

## Done means

- Engine + launcher committed
- Review window opened
- Continuous process running on AI-CODING
- State/report paths documented

## Result

**Done (AI-CODING 2026-08-01).**

- Added `run_full_day_backtest.py` — day-by-day walk-forward from **2000-01-01**, no look-ahead for signals, predict vs actual for 24h/1wk/1mo, loops when reaching today.
- Resource conservation: `BELOW_NORMAL` priority, default **1.25s/day**, **16** long-history symbols, **20** agents, incremental JSON state (no giant trial lists), gentle Yahoo bar fetch.
- Pre-start review: tkinter summary window + `output/history/full_day_backtest_review.txt`; launcher `Start Full Day Backtest.bat`.
- Extended `price_history.fetch_daily_bars(..., start=)` for multi-decade history.
- Smoke verified: SPY/etc bars from 2000-01-03 (~6684 days); after warm-up, trials accumulate (e.g. ~71k trials by 2000-04 with higher agent count in smoke).
- Production process launched on AI-CODING (visible cmd + review window; continuous loop).

Paths:
- State: `output/history/full_day_backtest_state.json`
- Report: `output/history/full_day_backtest.json`
- Log: `output/history/full_day_backtest.log`
- PID: `output/history/full_day_backtest.pid`

## Cache

-

## Do not

- Reassign unless blocked
- Put secrets in Cache
