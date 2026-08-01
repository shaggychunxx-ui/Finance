#!/usr/bin/env python3
"""Continuously run walk-forward backtests so agents keep learning from the past.

Runs ``historical_simulation.run_accuracy_benchmark`` on a repeating timer,
scoring every agent's historical predictions against realized returns and
rebuilding ``output/history/agent_learning.json`` after every cycle.

Night-only continuous mode (recommended with market-hours pipeline)::

    python run_backtest_loop.py --night-only --continuous --full-day
    pythonw run_backtest_loop.py --service

During US regular session the night-only loop sleeps; after the close (and on
weekends) it runs full-day walk-forwards back-to-back.

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
from typing import Any
from zoneinfo import ZoneInfo

from app_paths import OUTPUT, ROOT, ensure_app_path

ensure_app_path()

STATE_FILE = OUTPUT / "history" / "backtest_loop_state.json"
LOG_FILE = OUTPUT / "history" / "backtest_loop.log"
SERVICE_LOCK = OUTPUT / "history" / "backtest_loop.lock"
SERVICE_MUTEX_NAME = "Local\\FinanceFullDayBacktestNightService"
ET_TZ = ZoneInfo("America/New_York")

_shutdown_requested = False
_service_mutex_handle: int | None = None


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


def is_us_regular_session(now: datetime | None = None) -> bool:
    """True Mon–Fri 09:30–16:00 America/New_York (no holiday calendar)."""
    now = now or datetime.now(ET_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET_TZ)
    else:
        now = now.astimezone(ET_TZ)
    if now.weekday() >= 5:
        return False
    open_ = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_ <= now < close


def full_day_defaults() -> dict[str, Any]:
    """Match pipeline daily_calibration (full-day) profile when present."""
    defaults = {"target_trials": 10000, "max_symbols": 400, "full": True}
    try:
        from historical_simulation import resolve_pipeline_benchmark

        cfg = resolve_pipeline_benchmark("daily")
        defaults["target_trials"] = int(cfg.get("target_trials") or 10000)
        defaults["max_symbols"] = int(cfg.get("max_symbols") or 400)
        defaults["full"] = bool(cfg.get("full", True))
    except Exception:
        pass
    return defaults


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
        "session": "night" if not is_us_regular_session() else "market",
    }


def _sleep_interruptible(seconds: float) -> None:
    end = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < end:
        if _shutdown_requested:
            return
        time.sleep(min(1.0, end - time.monotonic()))


def _wait_for_night_session(*, poll_seconds: float = 60.0) -> bool:
    """Sleep until US regular session ends (or shutdown). Return False if shutdown."""
    while not _shutdown_requested and is_us_regular_session():
        now = datetime.now(ET_TZ)
        _log(
            f"  Market open ({now.strftime('%Y-%m-%d %H:%M %Z')}) — "
            "night-only backtest paused; sleeping 60s …"
        )
        _sleep_interruptible(poll_seconds)
    return not _shutdown_requested


def run_loop(
    *,
    interval_minutes: float,
    target_trials: int,
    max_symbols: int,
    full: bool,
    once: bool = False,
    night_only: bool = False,
    continuous: bool = False,
) -> int:
    """Main loop: run cycles separated by *interval_minutes*.

    *continuous*: start the next cycle as soon as the previous finishes
    (interval only used as a tiny settle pause, default 5s).
    *night_only*: skip / wait during US regular market hours.
    *once*: run exactly one eligible cycle and exit.
    """
    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)

    state = _load_state()
    if not state.get("started_at"):
        state["started_at"] = _now_iso()
    state["mode"] = {
        "night_only": night_only,
        "continuous": continuous,
        "interval_minutes": interval_minutes,
        "target_trials": target_trials,
        "max_symbols": max_symbols,
        "full": full,
    }
    _save_state(state)

    if once:
        mode = "once"
    elif night_only and continuous:
        mode = "night-only continuous (full-day when RTH closed)"
    elif night_only:
        mode = f"night-only every {interval_minutes} minutes"
    elif continuous:
        mode = "continuous (back-to-back)"
    else:
        mode = f"every {interval_minutes} minutes"

    _log(f"Backtest loop starting — {mode}")
    _log(f"  Benchmark   → {OUTPUT / 'history' / 'accuracy_benchmark.json'}")
    _log(f"  Learning    → {OUTPUT / 'history' / 'agent_learning.json'}")
    _log(f"  State       → {STATE_FILE}")
    _log(f"  Log         → {LOG_FILE}")
    _log(f"  Trials/symbols/full → {target_trials:,} / {max_symbols} / {full}")

    cycle_num = int(state.get("cycles", 0) or 0)
    failures = 0
    settle_sec = 5.0 if continuous else max(0.0, float(interval_minutes) * 60.0)

    while True:
        if _shutdown_requested:
            _log("Shutdown requested before starting cycle — exiting cleanly.")
            break

        if night_only and is_us_regular_session():
            if once:
                _log("Once + night-only: market is open — nothing to run; exit.")
                break
            if not _wait_for_night_session():
                break
            continue

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

        # If market opened mid-cycle, go idle until night again.
        if night_only and is_us_regular_session():
            _log("  Market opened during/after cycle — pausing until night.")
            continue

        if continuous:
            _log(f"  Continuous mode — settle {settle_sec:.0f}s then next cycle …")
        else:
            _log(f"  Sleeping {interval_minutes} minutes until next cycle …")
        _sleep_interruptible(settle_sec)

    _log(f"Backtest loop finished — {cycle_num - failures}/{max(cycle_num, 1)} cycles succeeded")
    return 0 if failures == 0 else 1


def acquire_service_lock() -> bool:
    global _service_mutex_handle
    SERVICE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.CreateMutexW(None, False, SERVICE_MUTEX_NAME)
            last_error = kernel32.GetLastError()
            if not handle:
                return False
            if last_error == 183:  # ERROR_ALREADY_EXISTS
                kernel32.CloseHandle(handle)
                return False
            _service_mutex_handle = handle
        except Exception:
            pass
    if SERVICE_LOCK.exists():
        try:
            age = time.time() - SERVICE_LOCK.stat().st_mtime
            pid_txt = SERVICE_LOCK.read_text(encoding="utf-8").strip()
            pid = int(pid_txt) if pid_txt.isdigit() else 0
            if age < 7200 and pid and pid != __import__("os").getpid():
                try:
                    import os

                    os.kill(pid, 0)
                    return False
                except OSError:
                    pass
        except OSError:
            pass
    SERVICE_LOCK.write_text(str(__import__("os").getpid()), encoding="utf-8")
    return True


def release_service_lock() -> None:
    global _service_mutex_handle
    try:
        if SERVICE_LOCK.exists():
            SERVICE_LOCK.unlink(missing_ok=True)
    except OSError:
        pass
    if _service_mutex_handle and sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.CloseHandle(_service_mutex_handle)  # type: ignore[attr-defined]
        except Exception:
            pass
        _service_mutex_handle = None


def run_service() -> int:
    """Night-only continuous full-day backtest service (single instance)."""
    if not acquire_service_lock():
        _log("Night backtest service already running — exit.")
        return 0
    defaults = full_day_defaults()
    _log(f"Night backtest service started (pid {__import__('os').getpid()}).")
    try:
        return run_loop(
            interval_minutes=0,
            target_trials=int(defaults["target_trials"]),
            max_symbols=int(defaults["max_symbols"]),
            full=bool(defaults["full"]),
            once=False,
            night_only=True,
            continuous=True,
        )
    finally:
        release_service_lock()
        _log("Night backtest service stopped.")


def main() -> int:
    defaults = full_day_defaults()
    parser = argparse.ArgumentParser(
        description="Continuously run walk-forward backtests for agent learning"
    )
    parser.add_argument(
        "--interval-minutes",
        type=float,
        default=60.0,
        metavar="N",
        help="Minutes between backtest cycles when not --continuous (default: 60)",
    )
    parser.add_argument(
        "--target-trials",
        type=int,
        default=None,
        metavar="N",
        help=f"Target walk-forward trials (default: {defaults['target_trials']} with --full-day/--service)",
    )
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=None,
        metavar="N",
        help=f"Symbol universe size (default: {defaults['max_symbols']} with --full-day/--service)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Use the reduced (quick) horizon/lookback set instead of the full backtest",
    )
    parser.add_argument(
        "--full-day",
        action="store_true",
        help="Use daily calibration size (10k trials / 400 symbols / full horizons)",
    )
    parser.add_argument(
        "--night-only",
        action="store_true",
        help="Only run when US regular session is closed (nights + weekends)",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Start next cycle immediately after the previous finishes",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single cycle then exit (useful for testing)",
    )
    parser.add_argument(
        "--service",
        action="store_true",
        help="Single-instance night-only continuous full-day service",
    )
    args = parser.parse_args()

    if args.service:
        return run_service()

    use_full_day = args.full_day or args.night_only or args.continuous
    target = args.target_trials
    symbols = args.max_symbols
    if use_full_day:
        if target is None:
            target = int(defaults["target_trials"])
        if symbols is None:
            symbols = int(defaults["max_symbols"])
        full = not args.quick
    else:
        if target is None:
            target = 1000
        if symbols is None:
            symbols = 40
        full = not args.quick

    if args.interval_minutes < 0:
        print("--interval-minutes must be >= 0", file=sys.stderr)
        return 2
    if target < 1:
        print("--target-trials must be >= 1", file=sys.stderr)
        return 2
    if symbols < 1:
        print("--max-symbols must be >= 1", file=sys.stderr)
        return 2

    return run_loop(
        interval_minutes=float(args.interval_minutes),
        target_trials=int(target),
        max_symbols=int(symbols),
        full=full,
        once=args.once,
        night_only=bool(args.night_only or args.service),
        continuous=bool(args.continuous or args.service),
    )


if __name__ == "__main__":
    raise SystemExit(main())
