#!/usr/bin/env python3
"""Run the full Finance agent pipeline repeatedly with checkpointing."""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from app_paths import OUTPUT, ensure_app_path

ensure_app_path()

STATE_FILE = OUTPUT / "history" / "pipeline_loop_state.json"
LOG_FILE = OUTPUT / "history" / "pipeline_loop.log"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {"completed": 0, "target": 0, "runs": [], "started_at": None, "updated_at": None}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"completed": 0, "target": 0, "runs": []}
    except (OSError, json.JSONDecodeError):
        return {"completed": 0, "target": 0, "runs": []}


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


def run_loop(*, target: int, start_from: int | None = None) -> int:
    from finance_runners import load_finance_runners
    from strategy_engine import run_agent_pipeline

    state = _load_state()
    if state.get("target") != target:
        state = {
            "completed": 0,
            "target": target,
            "runs": [],
            "started_at": _now_iso(),
            "updated_at": None,
        }
        _save_state(state)

    runners = load_finance_runners()
    begin = max(1, int(start_from or state.get("completed", 0) + 1))
    failures = 0

    _log(f"Pipeline loop starting — runs {begin}..{target} of {target}")

    for run_index in range(begin, target + 1):
        started = time.perf_counter()
        _log(f"Run {run_index}/{target} — starting full pipeline")
        try:
            ok = run_agent_pipeline(runners, on_progress=lambda msg: _log(f"  {msg}"), check_remote=False)
            elapsed = time.perf_counter() - started
            entry = {
                "run": run_index,
                "agents_ok": ok,
                "elapsed_sec": round(elapsed, 1),
                "finished_at": _now_iso(),
                "status": "ok",
            }
            _log(f"Run {run_index}/{target} complete — {ok} agents, {elapsed / 60:.1f} min")
        except Exception as exc:
            elapsed = time.perf_counter() - started
            failures += 1
            entry = {
                "run": run_index,
                "elapsed_sec": round(elapsed, 1),
                "finished_at": _now_iso(),
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-2000:],
            }
            _log(f"Run {run_index}/{target} FAILED — {exc}")

        state = _load_state()
        state["target"] = target
        state.setdefault("runs", []).append(entry)
        state["runs"] = state["runs"][-200:]
        state["completed"] = run_index
        state.setdefault("started_at", _now_iso())
        _save_state(state)

    _log(f"Pipeline loop finished — {target - failures}/{target} succeeded, {failures} failed")
    return 0 if failures == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run full agent pipeline in a loop")
    parser.add_argument("--count", type=int, default=1000, help="Number of pipeline runs")
    parser.add_argument(
        "--start",
        type=int,
        default=None,
        help="Resume from this run number (default: continue from checkpoint)",
    )
    args = parser.parse_args()
    if args.count < 1:
        print("count must be >= 1", file=sys.stderr)
        return 2
    return run_loop(target=args.count, start_from=args.start)


if __name__ == "__main__":
    raise SystemExit(main())