#!/usr/bin/env python3
"""Continuously run walk-forward backtests so agents keep learning from the past.

Runs ``historical_simulation.run_accuracy_benchmark`` on a repeating timer,
scoring every agent's historical predictions against realized returns and
rebuilding ``output/history/agent_learning.json`` after every cycle. Designed
to run alongside or independently of ``run_pipeline_loop.py`` /
``run_market_predictor_loop.py`` without clobbering their state files.

Usage::

    python run_backtest_loop.py --interval-minutes 60
    python run_backtest_loop.py --interval-minutes 15 --once
    python run_backtest_loop.py --target-trials 2000 --max-symbols 60

Press Ctrl+C (or send SIGTERM) to stop cleanly after the current cycle.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from app_paths import OUTPUT, ensure_app_path

ensure_app_path()

STATE_FILE = OUTPUT / "history" / "backtest_loop_state.json"
LOG_FILE = OUTPUT / "history" / "backtest_loop.log"

_shutdown_requested = False


def _request_shutdown(signum: int, frame: object) -> None:  # noqa: ARG001
    global _shutdown_requested
    _shutdown_requested = True
    _log("Shutdown signal received — will stop after current cycle completes.")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {"cycles": 0, "runs": [], "started_at": None, "updated_at": None}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"cycles": 0, "runs": []}
    except (OSError, json.JSONDecodeError):
        return {"cycles": 0, "runs": []}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _now_iso()
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _log(message: str) -> None:
    line = f"[{_now_iso()}] {message}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def run_backtest_cycle(*, target_trials: int, max_symbols: int, full: bool) -> dict:
    """Run one walk-forward backtest and rebuild agent learning. Returns a status dict."""
    from historical_simulation import run_accuracy_benchmark

    started = time.perf_counter()
    _log(
        f"  Running walk-forward backtest — target {target_trials:,} trials, "
        f"{max_symbols} symbols, full={full} …"
    )
    ok = False
    trials = 0
    leader = None
    try:
        report = run_accuracy_benchmark(
            target_trials=target_trials,
            max_symbols=max_symbols,
            full=full,
            rebuild_learning=True,
        )
        metrics = report.get("metrics") or {}
        board = report.get("leaderboard") or []
        trials = int(metrics.get("total_trials", 0) or 0)
        leader = board[0].get("agent_id") if board else None
        ok = True
    except Exception as exc:
        _log(f"  Backtest failed: {type(exc).__name__}: {exc}")
        _log(traceback.format_exc()[-2000:])

    elapsed = time.perf_counter() - started
    return {
        "finished_at": _now_iso(),
        "elapsed_sec": round(elapsed, 1),
        "trials": trials,
        "top_agent": leader,
        "backtest_ok": ok,
        "status": "ok" if ok else "error",
    }


def run_loop(
    *,
    interval_minutes: float,
    target_trials: int,
    max_symbols: int,
    full: bool,
    once: bool = False,
) -> int:
    """Main loop: run cycles separated by *interval_minutes*.

    If *once* is True, run exactly one cycle and exit.
    """
    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)

    state = _load_state()
    if not state.get("started_at"):
        state["started_at"] = _now_iso()
    _save_state(state)

    mode = "once" if once else f"every {interval_minutes} minutes"
    _log(f"Backtest loop starting — {mode}")
    _log(f"  Benchmark   → {OUTPUT / 'history' / 'accuracy_benchmark.json'}")
    _log(f"  Learning    → {OUTPUT / 'history' / 'agent_learning.json'}")
    _log(f"  State       → {STATE_FILE}")
    _log(f"  Log         → {LOG_FILE}")

    cycle_num = state.get("cycles", 0)
    failures = 0

    while True:
        if _shutdown_requested:
            _log("Shutdown requested before starting cycle — exiting cleanly.")
            break

        cycle_num += 1
        _log(f"Cycle {cycle_num} — starting")
        try:
            entry = run_backtest_cycle(
                target_trials=target_trials,
                max_symbols=max_symbols,
                full=full,
            )
            entry["cycle"] = cycle_num
            if not entry["backtest_ok"]:
                failures += 1
            _log(
                f"Cycle {cycle_num} complete — backtest {'OK' if entry['backtest_ok'] else 'FAILED'}"
                f", {entry['trials']:,} trials, {entry['elapsed_sec']}s"
            )
        except Exception as exc:
            failures += 1
            entry = {
                "cycle": cycle_num,
                "finished_at": _now_iso(),
                "elapsed_sec": 0.0,
                "trials": 0,
                "top_agent": None,
                "backtest_ok": False,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-2000:],
            }
            _log(f"Cycle {cycle_num} FAILED — {exc}")

        state = _load_state()
        state.setdefault("runs", []).append(entry)
        state["runs"] = state["runs"][-200:]
        state["cycles"] = cycle_num
        state.setdefault("started_at", _now_iso())
        _save_state(state)

        if once or _shutdown_requested:
            break

        _log(f"  Sleeping {interval_minutes} minutes until next cycle …")
        sleep_end = time.monotonic() + interval_minutes * 60
        while time.monotonic() < sleep_end:
            if _shutdown_requested:
                break
            time.sleep(1)

    _log(f"Backtest loop finished — {cycle_num - failures}/{cycle_num} cycles succeeded")
    return 0 if failures == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Continuously run walk-forward backtests for agent learning"
    )
    parser.add_argument(
        "--interval-minutes",
        type=float,
        default=60.0,
        metavar="N",
        help="Minutes between backtest cycles (default: 60)",
    )
    parser.add_argument(
        "--target-trials",
        type=int,
        default=1000,
        metavar="N",
        help="Target walk-forward trials per cycle (default: 1000)",
    )
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=40,
        metavar="N",
        help="Symbol universe size per cycle (default: 40)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Use the reduced (quick) horizon/lookback set instead of the full backtest",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single cycle then exit (useful for testing)",
    )
    args = parser.parse_args()
    if args.interval_minutes <= 0:
        print("--interval-minutes must be > 0", file=sys.stderr)
        return 2
    if args.target_trials < 1:
        print("--target-trials must be >= 1", file=sys.stderr)
        return 2
    if args.max_symbols < 1:
        print("--max-symbols must be >= 1", file=sys.stderr)
        return 2
    return run_loop(
        interval_minutes=args.interval_minutes,
        target_trials=args.target_trials,
        max_symbols=args.max_symbols,
        full=not args.quick,
        once=args.once,
    )


if __name__ == "__main__":
    raise SystemExit(main())
