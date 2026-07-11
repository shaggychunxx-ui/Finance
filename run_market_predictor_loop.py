#!/usr/bin/env python3
"""Continuously refresh market predictions on a configurable interval.

Runs the core signal-producing agents followed by ``run_market_predictor_analysis``
on a repeating timer.  Designed to run alongside or independently of the full
``run_pipeline_loop.py`` without clobbering its state files.

Usage::

    python run_market_predictor_loop.py --interval-minutes 30
    python run_market_predictor_loop.py --interval-minutes 5 --once

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

STATE_FILE = OUTPUT / "history" / "market_predictor_loop_state.json"
LOG_FILE = OUTPUT / "history" / "market_predictor_loop.log"

# Signal-producing agents to run before fusing predictions.
SIGNAL_AGENTS = [
    "markets",
    "finance",
    "datascience",
    "financial-data",
    "geopolitics",
    "sales-analytics",
]

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


def _run_signal_agent(agent_id: str) -> bool:
    """Import and run one signal-producing agent; return True on success."""
    from main import RUNNERS

    output_map: dict[str, str] = {
        "markets": "markets.json",
        "finance": "finance.json",
        "datascience": "datascience.json",
        "financial-data": "financial_data.json",
        "geopolitics": "geopolitics.json",
        "sales-analytics": "sales_analytics.json",
    }
    runner = RUNNERS.get(agent_id)
    if runner is None:
        _log(f"  Agent '{agent_id}' not found in RUNNERS — skipping")
        return False
    out_file = OUTPUT / output_map.get(agent_id, f"{agent_id}.json")
    try:
        runner(output=out_file)
        return True
    except Exception as exc:
        _log(f"  Agent '{agent_id}' failed: {type(exc).__name__}: {exc}")
        return False


def run_predictor_cycle() -> dict:
    """Run signal agents then fuse predictions.  Returns a status dict."""
    from agents.market_predictor import run_market_predictor_analysis

    started = time.perf_counter()
    agent_results: dict[str, bool] = {}

    _log("  Running signal agents …")
    for agent_id in SIGNAL_AGENTS:
        _log(f"    → {agent_id}")
        agent_results[agent_id] = _run_signal_agent(agent_id)

    _log("  Fusing predictions with market_predictor …")
    predictor_ok = False
    try:
        run_market_predictor_analysis(output=OUTPUT / "market_predictions.json")
        predictor_ok = True
    except Exception as exc:
        _log(f"  market_predictor failed: {type(exc).__name__}: {exc}")
        _log(traceback.format_exc()[-2000:])

    elapsed = time.perf_counter() - started
    return {
        "finished_at": _now_iso(),
        "elapsed_sec": round(elapsed, 1),
        "agents": agent_results,
        "predictor_ok": predictor_ok,
        "status": "ok" if predictor_ok else "error",
    }


def run_loop(*, interval_minutes: float, once: bool = False) -> int:
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
    _log(f"Market predictor loop starting — {mode}")
    _log(f"  Predictions → {OUTPUT / 'market_predictions.json'}")
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
            entry = run_predictor_cycle()
            entry["cycle"] = cycle_num
            if not entry["predictor_ok"]:
                failures += 1
            _log(
                f"Cycle {cycle_num} complete — predictor {'OK' if entry['predictor_ok'] else 'FAILED'}"
                f", {entry['elapsed_sec']}s"
            )
        except Exception as exc:
            failures += 1
            entry = {
                "cycle": cycle_num,
                "finished_at": _now_iso(),
                "elapsed_sec": 0.0,
                "agents": {},
                "predictor_ok": False,
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

    _log(f"Market predictor loop finished — {cycle_num - failures}/{cycle_num} cycles succeeded")
    return 0 if failures == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Continuously refresh market predictions at a set interval"
    )
    parser.add_argument(
        "--interval-minutes",
        type=float,
        default=30.0,
        metavar="N",
        help="Minutes between prediction refresh cycles (default: 30)",
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
    return run_loop(interval_minutes=args.interval_minutes, once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
