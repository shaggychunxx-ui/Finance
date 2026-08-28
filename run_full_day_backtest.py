#!/usr/bin/env python3
"""Slow continuous day-by-day full walk-forward backtest from 2000-01-01.

PHONE goal: run a constant full backtest that:
  - starts on 2000-01-01
  - never uses future prices for signal generation (true walk-forward)
  - predicts direction, then scores vs realized forward returns
  - advances one trading day at a time until today
  - when current date is reached, restarts from 2000-01-01
  - conserves CPU / GPU / memory (low process priority, small universe,
    sleep between days, incremental disk state)
  - opens a summary window on AI-CODING for review before the run begins

Usage::

    python run_full_day_backtest.py
    python run_full_day_backtest.py --seconds-per-day 1.5 --no-gui
    python run_full_day_backtest.py --review-seconds 45

State: ``output/history/full_day_backtest_state.json``
Report: ``output/history/full_day_backtest.json``
Log:    ``output/history/full_day_backtest.log``
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import signal
import sys
import threading
import time
import traceback
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from app_paths import OUTPUT, ensure_app_path

ensure_app_path()

STATE_FILE = OUTPUT / "history" / "full_day_backtest_state.json"
REPORT_FILE = OUTPUT / "history" / "full_day_backtest.json"
LOG_FILE = OUTPUT / "history" / "full_day_backtest.log"
PID_FILE = OUTPUT / "history" / "full_day_backtest.pid"

# Fixed long-history liquid universe (most have data near/from 2000).
# Kept small to conserve memory and Yahoo rate limits.
LONG_HISTORY_UNIVERSE: tuple[str, ...] = (
    "SPY",
    "QQQ",
    "DIA",
    "IWM",
    "XLK",
    "XLE",
    "XLF",
    "XLI",
    "XLY",
    "XLP",
    "XLU",
    "XLV",
    "AAPL",
    "MSFT",
    "JPM",
    "XOM",
    "WMT",
    "KO",
    "GE",
    "INTC",
)

HORIZON_BARS = {"24h": 1, "1wk": 5, "1mo": 21}
HORIZON_MOVE_PCT = {"24h": 0.5, "1wk": 1.5, "1mo": 3.0}
START_DATE = date(2000, 1, 1)
MIN_HISTORY_BARS = 25
# Max recent day digests kept in report (not full trial log).
MAX_RECENT_DAYS = 40
CHECKPOINT_EVERY_DAYS = 25

_shutdown_requested = False
_status_lock = threading.Lock()
_live_status: dict[str, Any] = {
    "phase": "init",
    "message": "Starting…",
    "sim_date": None,
    "pass_num": 0,
    "days_done": 0,
    "trials": 0,
    "hits": 0,
    "accuracy_pct": None,
    "top_agents": [],
}


def _request_shutdown(signum: int, frame: object) -> None:  # noqa: ARG001
    global _shutdown_requested
    _shutdown_requested = True
    _set_status(phase="stopping", message="Shutdown requested — finishing current day…")
    _log("Shutdown signal received — will stop after current day completes.")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(message: str) -> None:
    line = f"[{_now_iso()}] {message}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def _set_status(**kwargs: Any) -> None:
    with _status_lock:
        _live_status.update(kwargs)


def _get_status() -> dict[str, Any]:
    with _status_lock:
        return dict(_live_status)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _lower_process_priority() -> None:
    """Conserve CPU relative to interactive work (Windows BELOW_NORMAL)."""
    try:
        if sys.platform == "win32":
            import ctypes

            # IDLE_PRIORITY_CLASS = 0x40, BELOW_NORMAL = 0x4000
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.kernel32.SetPriorityClass(handle, 0x4000)
            _log("Process priority set to BELOW_NORMAL")
        else:
            os.nice(10)
            _log("Process nice(+10) applied")
    except Exception as exc:
        _log(f"Could not lower process priority: {exc}")


def _write_pid() -> None:
    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass


def _clear_pid() -> None:
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except OSError:
        pass


def _agent_ids(*, max_agents: int = 0) -> list[str]:
    from historical_simulation import SKIP_AGENTS
    from agents.platform_catalog import active_agent_sources

    ids = [
        src["id"]
        for src in active_agent_sources(check_remote=False)
        if src["id"] not in SKIP_AGENTS
    ]
    # Prefer quant/momentum/risk signal proxies first for resource-friendly full runs.
    priority = {
        "markets",
        "finance",
        "financial-data",
        "datascience",
        "empirical-probability",
        "theoretical-probability",
        "combined-conditional",
        "research-statistics",
        "geopolitics",
        "events",
        "sales-analytics",
        "momentum-reversion",
    }
    preferred = [a for a in ids if a in priority]
    rest = [a for a in ids if a not in priority]
    ordered = preferred + rest
    if max_agents and max_agents > 0:
        return ordered[: max(4, max_agents)]
    return ordered


def _actual_direction(change_pct: float, *, horizon: str) -> str:
    threshold = HORIZON_MOVE_PCT.get(horizon, 0.5)
    if change_pct > threshold:
        return "up"
    if change_pct < -threshold:
        return "down"
    return "flat"


def _prediction_hit(predicted: str, actual: str) -> bool:
    predicted = str(predicted or "flat").lower()
    actual = str(actual or "flat").lower()
    if predicted == "flat":
        return actual == "flat"
    if actual == "flat":
        return False
    return predicted == actual


def _default_state() -> dict[str, Any]:
    return {
        "started_at": _now_iso(),
        "updated_at": _now_iso(),
        "pass": 1,
        "sim_date": START_DATE.isoformat(),
        "days_completed": 0,
        "total_trials": 0,
        "total_hits": 0,
        "by_agent": {},
        "by_horizon": {},
        "recent_days": [],
        "last_checkpoint_at": None,
        "config": {},
        "status": "idle",
    }


def _load_state() -> dict[str, Any]:
    data = _load_json(STATE_FILE)
    if not data:
        return _default_state()
    base = _default_state()
    base.update(data)
    return base


def _save_state(state: dict[str, Any]) -> None:
    state["updated_at"] = _now_iso()
    _write_json(STATE_FILE, state)


def _export_report(state: dict[str, Any], *, universe: list[str], agents: list[str]) -> None:
    by_agent = state.get("by_agent") or {}
    leaderboard: list[dict[str, Any]] = []
    for aid, bucket in by_agent.items():
        total = int(bucket.get("total", 0) or 0)
        hits = int(bucket.get("hits", 0) or 0)
        if total < 1:
            continue
        acc = round(hits / total * 100, 1)
        leaderboard.append(
            {
                "agent_id": aid,
                "total_trials": total,
                "hits": hits,
                "accuracy_pct": acc,
                "weight_multiplier": round(max(0.5, min(1.5, 0.5 + acc / 100.0)), 3),
            }
        )
    leaderboard.sort(key=lambda r: (r["accuracy_pct"], r["total_trials"]), reverse=True)

    total = int(state.get("total_trials", 0) or 0)
    hits = int(state.get("total_hits", 0) or 0)
    acc = round(hits / total * 100, 1) if total else None
    top = leaderboard[0] if leaderboard else None
    summary = (
        f"Full day walk-forward pass {state.get('pass', 1)}: "
        f"sim_date={state.get('sim_date')} days={state.get('days_completed', 0)} "
        f"trials={total} accuracy={acc}%."
        + (
            f" Top agent {top['agent_id']} at {top['accuracy_pct']}%."
            if top
            else " Awaiting ranked agent samples."
        )
    )

    report = {
        "meta": {
            "agent": "Full Day Walk-Forward Backtest",
            "analyzed_at": _now_iso(),
            "start_date": START_DATE.isoformat(),
            "sim_date": state.get("sim_date"),
            "pass": state.get("pass", 1),
            "expert_summary": summary,
            "no_lookahead": True,
            "mode": "day_by_day_from_2000",
            "universe_size": len(universe),
            "agents": agents,
        },
        "metrics": {
            "total_trials": total,
            "total_hits": hits,
            "accuracy_pct": acc,
            "days_completed": state.get("days_completed", 0),
            "pass": state.get("pass", 1),
        },
        "by_horizon": state.get("by_horizon") or {},
        "leaderboard": leaderboard[:25],
        "agents": by_agent,
        "universe": universe,
        "recent_days": state.get("recent_days") or [],
        "recommendations": [
            summary,
            "Signals use only bars on/before sim date; forward returns score later.",
            "Loop restarts at 2000-01-01 after reaching current date.",
        ]
        + [f"{r['agent_id']}: {r['accuracy_pct']}% ({r['total_trials']} trials)" for r in leaderboard[:8]],
    }
    _write_json(REPORT_FILE, report)

    # Optionally blend into agent learning without a heavy full re-benchmark.
    try:
        from prediction_accuracy import sync_benchmark_to_accuracy_store

        # Shape compatible enough: leaderboard + agents + metrics.
        sync_payload = {
            "meta": report["meta"],
            "metrics": {
                "total_trials": total,
                "bar_walk_trials": total,
                "snapshot_trials": 0,
            },
            "leaderboard": leaderboard,
            "agents": {
                aid: {
                    "total_trials": int(b.get("total", 0)),
                    "hits": int(b.get("hits", 0)),
                    "accuracy_pct": (
                        round(int(b.get("hits", 0)) / int(b.get("total", 1)) * 100, 1)
                        if int(b.get("total", 0))
                        else None
                    ),
                    "weight_multiplier": next(
                        (x["weight_multiplier"] for x in leaderboard if x["agent_id"] == aid),
                        1.0,
                    ),
                    "by_horizon": b.get("by_horizon") or {},
                    "by_source": {"full_day_walk_forward": {"total": int(b.get("total", 0)), "hits": int(b.get("hits", 0))}},
                }
                for aid, b in by_agent.items()
            },
            "universe": universe,
            "recent_trials": [],
        }
        sync_benchmark_to_accuracy_store(sync_payload, force=False, rebuild_learning=True)
    except Exception:
        pass


def _load_bar_series(
    symbols: list[str],
    *,
    start: date,
) -> dict[str, dict[str, Any]]:
    """Load full daily series for each symbol from *start* (calendar).

    Uses disk bar cache + incremental tip refresh (price_history). Pure cache
    hits skip Yahoo throttle; network/incremental still pace requests.
    """
    from price_history import (
        bar_closes,
        bar_datetimes,
        fetch_daily_bars,
        last_bar_fetch_source,
    )

    start_dt = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    # Calendar span from start to now + pad.
    days = max(400, (date.today() - start).days + 60)
    series: dict[str, dict[str, Any]] = {}
    cache_hits = 0
    network_calls = 0
    for i, sym in enumerate(symbols):
        if _shutdown_requested:
            break
        bars = fetch_daily_bars(sym, days=days, use_cache=True, start=start_dt)
        source = last_bar_fetch_source()
        if source == "cache":
            cache_hits += 1
        elif source in {"network", "incremental"}:
            network_calls += 1
            # Gentle on Yahoo only when we actually hit the network.
            if i < len(symbols) - 1 and not _shutdown_requested:
                time.sleep(0.35)
        closes = bar_closes(bars)
        dates = bar_datetimes(bars)
        # Align lengths if parse dropped some.
        n = min(len(closes), len(dates))
        series[sym] = {
            "closes": closes[:n],
            "dates": dates[:n],
            "date_to_idx": {d.date(): i for i, d in enumerate(dates[:n])},
        }
        _log(
            f"  Bars {sym}: {n} days (first={dates[0].date() if n else 'n/a'}, "
            f"source={source})"
        )
    _log(f"Bar load summary: cache_hits={cache_hits} network_or_incremental={network_calls}")
    return series


def _build_trading_calendar(series: dict[str, dict[str, Any]], start: date) -> list[date]:
    """Union of all bar dates from start (sorted). Prefer SPY as backbone."""
    if "SPY" in series and series["SPY"]["dates"]:
        cal = [d.date() for d in series["SPY"]["dates"] if d.date() >= start]
        if cal:
            return cal
    seen: set[date] = set()
    for pack in series.values():
        for d in pack["dates"]:
            if d.date() >= start:
                seen.add(d.date())
    return sorted(seen)


def _process_day(
    sim_day: date,
    *,
    series: dict[str, dict[str, Any]],
    agent_ids: list[str],
    horizons: tuple[str, ...],
    state: dict[str, Any],
) -> dict[str, Any]:
    """One trading day: predict with data ≤ sim_day; score vs known forward returns."""
    from backtest_labels import (
        binary_brier,
        family_for_agent,
        net_return_pct,
        purged_keep,
        regime_from_closes,
    )
    from historical_simulation import _agent_signal, _estimate_return, _signal_source
    from price_history import forward_return_pct

    day_trials = 0
    day_hits = 0
    samples: list[dict[str, Any]] = []
    journal_rows: list[dict[str, Any]] = []

    by_agent: dict[str, Any] = state.setdefault("by_agent", {})
    by_horizon: dict[str, Any] = state.setdefault("by_horizon", {})

    for symbol, pack in series.items():
        idx = pack["date_to_idx"].get(sim_day)
        if idx is None or idx < MIN_HISTORY_BARS:
            continue
        closes = pack["closes"]

        # Proxy series only if same index position for this date (signal fn uses same idx).
        proxy_pack = series.get("SPY")
        proxy_closes = None
        if proxy_pack is not None and proxy_pack["date_to_idx"].get(sim_day) == idx:
            proxy_closes = proxy_pack["closes"]

        spy_closes = proxy_closes if proxy_closes else closes
        regime = regime_from_closes(spy_closes, min(idx, len(spy_closes) - 1))

        for agent_id in agent_ids:
            # Signal uses only history through idx (no future closes).
            direction, confidence = _agent_signal(
                agent_id,
                closes,
                idx,
                proxy_closes=proxy_closes,
            )
            predicted_return = _estimate_return(direction, confidence)
            family = family_for_agent(agent_id)
            source = _signal_source(agent_id)
            if source == "bar_walk_forward":
                source = "full_day_walk_forward"

            for horizon in horizons:
                if not purged_keep(idx, MIN_HISTORY_BARS, horizon, 1):
                    continue
                fwd = HORIZON_BARS.get(horizon, 1)
                actual_ret = forward_return_pct(closes, idx, fwd)
                if actual_ret is None:
                    continue  # future not known yet — never invent; skip
                actual_dir = _actual_direction(actual_ret, horizon=horizon)
                hit = _prediction_hit(direction, actual_dir)
                day_trials += 1
                if hit:
                    day_hits += 1
                journal_rows.append(
                    {
                        "agent_id": agent_id,
                        "symbol": symbol,
                        "horizon": horizon,
                        "predicted_direction": direction,
                        "actual_direction": actual_dir,
                        "predicted_return_pct": round(predicted_return, 3),
                        "actual_return_pct": round(actual_ret, 3),
                        "hit": hit,
                        "confidence": round(confidence, 3),
                        "source": source,
                        "simulated_at": sim_day.isoformat(),
                        "net_return_pct": net_return_pct(direction, actual_ret, symbol=symbol),
                        "regime": regime,
                        "family": family,
                        "brier": binary_brier(direction, hit, confidence),
                    }
                )

                bucket = by_agent.setdefault(
                    agent_id,
                    {"total": 0, "hits": 0, "by_horizon": {}},
                )
                bucket["total"] = int(bucket.get("total", 0)) + 1
                bucket["hits"] = int(bucket.get("hits", 0)) + (1 if hit else 0)
                hb = bucket.setdefault("by_horizon", {}).setdefault(
                    horizon, {"total": 0, "hits": 0}
                )
                hb["total"] = int(hb.get("total", 0)) + 1
                hb["hits"] = int(hb.get("hits", 0)) + (1 if hit else 0)

                hglob = by_horizon.setdefault(horizon, {"total": 0, "hits": 0})
                hglob["total"] = int(hglob.get("total", 0)) + 1
                hglob["hits"] = int(hglob.get("hits", 0)) + (1 if hit else 0)

                if len(samples) < 6:
                    samples.append(
                        {
                            "agent_id": agent_id,
                            "symbol": symbol,
                            "horizon": horizon,
                            "predicted": direction,
                            "actual": actual_dir,
                            "actual_return_pct": round(actual_ret, 3),
                            "predicted_return_pct": round(predicted_return, 3),
                            "hit": hit,
                        }
                    )

    state["total_trials"] = int(state.get("total_trials", 0)) + day_trials
    state["total_hits"] = int(state.get("total_hits", 0)) + day_hits
    state["days_completed"] = int(state.get("days_completed", 0)) + 1
    state["sim_date"] = sim_day.isoformat()

    if journal_rows:
        try:
            from backtest_trial_store import append_trials, new_cycle_id

            append_trials(
                journal_rows,
                cycle_id=new_cycle_id(),
                meta={
                    "source": "full_day_walk_forward",
                    "sim_date": sim_day.isoformat(),
                    "window_end": sim_day.isoformat(),
                    "total_trials": len(journal_rows),
                },
            )
        except Exception:
            pass

    digest = {
        "date": sim_day.isoformat(),
        "trials": day_trials,
        "hits": day_hits,
        "accuracy_pct": round(day_hits / day_trials * 100, 1) if day_trials else None,
        "samples": samples,
    }
    recent = list(state.get("recent_days") or [])
    recent.append(digest)
    state["recent_days"] = recent[-MAX_RECENT_DAYS:]
    return digest


def build_review_summary(
    *,
    seconds_per_day: float,
    max_symbols: int,
    max_agents: int,
    review_seconds: float,
    resume: bool,
) -> str:
    state = _load_state() if resume else _default_state()
    agents = _agent_ids(max_agents=max_agents)
    symbols = list(LONG_HISTORY_UNIVERSE[: max(4, max_symbols)])
    today = date.today()
    trading_days_est = int((today - START_DATE).days * 0.69)
    pass_eta_hours = (trading_days_est * seconds_per_day) / 3600.0
    resume_note = (
        f"RESUME from {state.get('sim_date')} (pass {state.get('pass', 1)}, "
        f"{state.get('days_completed', 0)} days already done)"
        if resume and state.get("sim_date")
        else "FRESH start at 2000-01-01"
    )
    lines = [
        "FULL DAY WALK-FORWARD BACKTEST - review before start",
        "=" * 56,
        "",
        f"Machine:     {os.environ.get('COMPUTERNAME', 'AI-CODING')}",
        f"Mode:        {resume_note}",
        f"Start date:  {START_DATE.isoformat()}",
        f"End date:    {today.isoformat()} then LOOP back to start",
        f"Step:        1 trading day at a time",
        f"Look-ahead:  DISABLED (signals use only bars on/before sim date)",
        f"Scoring:     predict direction/return, then compare to actual",
        f"Horizons:    {', '.join(HORIZON_BARS)}",
        "",
        "Resource conservation:",
        f"  - Process priority: BELOW_NORMAL (no GPU)",
        f"  - Sleep between days: {seconds_per_day:.2f}s",
        f"  - Symbols (capped): {len(symbols)} - {', '.join(symbols)}",
        f"  - Agents (capped): {len(agents)} of platform roster",
        f"  - Incremental disk state; no giant in-memory trial lists",
        f"  - Gentle Yahoo throttle when loading bars",
        "",
        f"Estimated ~{trading_days_est:,} trading days/pass ~ {pass_eta_hours:.1f} hours/pass",
        f"  at {seconds_per_day:.2f}s/day (plus signal work).",
        "",
        f"State file:  {STATE_FILE}",
        f"Report file: {REPORT_FILE}",
        f"Log file:    {LOG_FILE}",
        "",
        f"This window stays open for review (~{int(review_seconds)}s) then the run continues.",
        "Close the window or press Ctrl+C in the console to stop after the current day.",
        "",
    ]
    return "\n".join(lines)


def show_review_window(summary: str, *, review_seconds: float) -> None:
    """Open a visible summary window; auto-close after review_seconds (or user close)."""
    try:
        import tkinter as tk
        from tkinter import scrolledtext
    except Exception as exc:
        _log(f"GUI unavailable ({exc}); printing summary only.")
        print(summary)
        if review_seconds > 0:
            time.sleep(min(review_seconds, 15))
        return

    ready = threading.Event()
    root_holder: list[Any] = []

    def _ui() -> None:
        root = tk.Tk()
        root_holder.append(root)
        root.title("Finance — Full Day Backtest (review)")
        root.geometry("720x640")
        try:
            root.attributes("-topmost", True)
            root.after(800, lambda: root.attributes("-topmost", False))
        except Exception:
            pass
        root.configure(bg="#1a1a2e")
        header = tk.Label(
            root,
            text="Full Day Walk-Forward Backtest",
            font=("Segoe UI", 14, "bold"),
            fg="#eaeaea",
            bg="#1a1a2e",
        )
        header.pack(pady=(12, 4))
        sub = tk.Label(
            root,
            text="Review summary — run starts after countdown (or click Start now)",
            font=("Segoe UI", 10),
            fg="#9aa0a6",
            bg="#1a1a2e",
        )
        sub.pack()
        text = scrolledtext.ScrolledText(
            root,
            wrap=tk.WORD,
            font=("Consolas", 9),
            bg="#0f0f1a",
            fg="#d4d4d4",
            insertbackground="#d4d4d4",
        )
        text.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)
        text.insert(tk.END, summary)
        text.configure(state=tk.DISABLED)

        status_var = tk.StringVar(value=f"Starting in {int(review_seconds)}s…")
        status = tk.Label(
            root, textvariable=status_var, font=("Segoe UI", 10), fg="#7ee787", bg="#1a1a2e"
        )
        status.pack(pady=(0, 4))

        btn_frame = tk.Frame(root, bg="#1a1a2e")
        btn_frame.pack(pady=(0, 12))

        def _start_now() -> None:
            ready.set()
            status_var.set("Starting…")

        def _minimize_continue() -> None:
            ready.set()
            try:
                root.iconify()
            except Exception:
                pass

        tk.Button(
            btn_frame,
            text="Start now",
            command=_start_now,
            bg="#238636",
            fg="white",
            font=("Segoe UI", 10, "bold"),
            padx=16,
            pady=4,
        ).pack(side=tk.LEFT, padx=6)
        tk.Button(
            btn_frame,
            text="Minimize & run",
            command=_minimize_continue,
            bg="#30363d",
            fg="white",
            font=("Segoe UI", 10),
            padx=12,
            pady=4,
        ).pack(side=tk.LEFT, padx=6)

        deadline = time.monotonic() + max(0.0, review_seconds)

        def _tick() -> None:
            if ready.is_set():
                return
            left = int(max(0, deadline - time.monotonic()))
            status_var.set(f"Auto-start in {left}s… (or click Start now)")
            if left <= 0:
                ready.set()
                status_var.set("Starting…")
                return
            root.after(250, _tick)

        def _poll_live() -> None:
            st = _get_status()
            if st.get("phase") in {"running", "loading", "stopping", "done"}:
                acc = st.get("accuracy_pct")
                acc_s = f"{acc}%" if acc is not None else "n/a"
                status_var.set(
                    f"[{st.get('phase')}] pass={st.get('pass_num')} date={st.get('sim_date')} "
                    f"days={st.get('days_done')} trials={st.get('trials')} acc={acc_s}"
                )
            if st.get("phase") == "done":
                return
            try:
                root.after(1500, _poll_live)
            except Exception:
                pass

        root.after(200, _tick)
        root.after(1500, _poll_live)

        def _on_close() -> None:
            # Closing window does not stop the backtest unless still in review.
            if not ready.is_set():
                ready.set()
            try:
                root.withdraw()
            except Exception:
                pass

        root.protocol("WM_DELETE_WINDOW", _on_close)
        root.mainloop()

    thread = threading.Thread(target=_ui, name="backtest-review-ui", daemon=True)
    thread.start()
    # Wait for review window countdown / Start.
    ready.wait(timeout=max(5.0, review_seconds + 5))
    _log("Review complete — beginning backtest loop.")


def run_loop(
    *,
    seconds_per_day: float,
    max_symbols: int,
    max_agents: int,
    resume: bool,
    once_pass: bool,
    rebuild_learning_every: int,
) -> int:
    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)
    _lower_process_priority()
    _write_pid()

    horizons = tuple(HORIZON_BARS.keys())
    symbols = list(LONG_HISTORY_UNIVERSE[: max(4, max_symbols)])
    agent_ids = _agent_ids(max_agents=max_agents)

    state = _load_state() if resume else _default_state()
    if not resume:
        state = _default_state()
    state["status"] = "loading"
    state["config"] = {
        "seconds_per_day": seconds_per_day,
        "max_symbols": max_symbols,
        "symbols": symbols,
        "horizons": list(horizons),
        "start_date": START_DATE.isoformat(),
        "agents": agent_ids,
    }
    _save_state(state)
    _set_status(
        phase="loading",
        message="Loading long-history daily bars…",
        pass_num=state.get("pass", 1),
    )

    _log(
        f"Full day backtest — pass={state.get('pass', 1)} resume_date={state.get('sim_date')} "
        f"symbols={len(symbols)} agents={len(agent_ids)} sleep={seconds_per_day}s/day"
    )
    series = _load_bar_series(symbols, start=START_DATE)
    if not series:
        _log("No bar data loaded — aborting.")
        state["status"] = "error"
        _save_state(state)
        _clear_pid()
        return 1

    calendar = _build_trading_calendar(series, START_DATE)
    if not calendar:
        _log("Empty trading calendar — aborting.")
        state["status"] = "error"
        _save_state(state)
        _clear_pid()
        return 1

    # Resume mid-pass if sim_date set.
    resume_date_s = str(state.get("sim_date") or START_DATE.isoformat())
    try:
        resume_d = date.fromisoformat(resume_date_s[:10])
    except ValueError:
        resume_d = START_DATE

    # If resuming, start at the *next* day after last completed (if days_completed>0).
    start_idx = 0
    if resume and state.get("days_completed", 0):
        for i, d in enumerate(calendar):
            if d > resume_d:
                start_idx = i
                break
            if d == resume_d:
                start_idx = i + 1
                break
    else:
        for i, d in enumerate(calendar):
            if d >= resume_d:
                start_idx = i
                break

    _log(f"Calendar: {len(calendar)} trading days ({calendar[0]} → {calendar[-1]}); start_idx={start_idx}")
    state["status"] = "running"
    _save_state(state)

    failures = 0
    days_this_session = 0

    try:
        while not _shutdown_requested:
            pass_num = int(state.get("pass", 1) or 1)
            for i in range(start_idx, len(calendar)):
                if _shutdown_requested:
                    break
                sim_day = calendar[i]
                # Do not process future calendar days beyond "today".
                if sim_day > date.today():
                    break

                try:
                    digest = _process_day(
                        sim_day,
                        series=series,
                        agent_ids=agent_ids,
                        horizons=horizons,
                        state=state,
                    )
                except Exception as exc:
                    failures += 1
                    _log(f"Day {sim_day} failed: {type(exc).__name__}: {exc}")
                    _log(traceback.format_exc()[-1500:])
                    continue

                days_this_session += 1
                total = int(state.get("total_trials", 0))
                hits = int(state.get("total_hits", 0))
                acc = round(hits / total * 100, 1) if total else None

                # Leaderboard snippet for live UI.
                board = []
                for aid, b in (state.get("by_agent") or {}).items():
                    t = int(b.get("total", 0))
                    h = int(b.get("hits", 0))
                    if t >= 8:
                        board.append((aid, round(h / t * 100, 1), t))
                board.sort(key=lambda x: x[1], reverse=True)

                _set_status(
                    phase="running",
                    message=f"Processed {sim_day}",
                    sim_date=sim_day.isoformat(),
                    pass_num=pass_num,
                    days_done=state.get("days_completed", 0),
                    trials=total,
                    hits=hits,
                    accuracy_pct=acc,
                    top_agents=[{"agent_id": a, "accuracy_pct": p, "trials": t} for a, p, t in board[:5]],
                )

                if days_this_session % CHECKPOINT_EVERY_DAYS == 0 or days_this_session == 1:
                    state["last_checkpoint_at"] = _now_iso()
                    _save_state(state)
                    _export_report(state, universe=symbols, agents=agent_ids)
                    _log(
                        f"Checkpoint pass={pass_num} date={sim_day} "
                        f"day_trials={digest.get('trials')} "
                        f"cum_trials={total} acc={acc}% "
                        f"(session_days={days_this_session})"
                    )

                if (
                    rebuild_learning_every > 0
                    and days_this_session % rebuild_learning_every == 0
                ):
                    _export_report(state, universe=symbols, agents=agent_ids)

                # Conserve CPU between days.
                sleep_end = time.monotonic() + max(0.05, seconds_per_day)
                while time.monotonic() < sleep_end:
                    if _shutdown_requested:
                        break
                    time.sleep(0.25)

                if days_this_session % 200 == 0:
                    gc.collect()

            # End of calendar / reached today → save and either loop or exit.
            state["last_checkpoint_at"] = _now_iso()
            _save_state(state)
            _export_report(state, universe=symbols, agents=agent_ids)

            if _shutdown_requested:
                break
            if once_pass:
                _log(f"Single pass complete (pass={pass_num}).")
                break

            # Restart from beginning (fresh accuracy for the new pass).
            pass_num += 1
            _log(f"Reached current date — restarting full pass {pass_num} from {START_DATE}")
            prev_days = int(state.get("days_completed", 0) or 0)
            state["pass"] = pass_num
            state["sim_date"] = START_DATE.isoformat()
            state["total_trials"] = 0
            state["total_hits"] = 0
            state["by_agent"] = {}
            state["by_horizon"] = {}
            state["recent_days"] = []
            state["days_completed"] = prev_days  # lifetime day counter across passes
            start_idx = 0
            _save_state(state)
            # Small pause between passes.
            for _ in range(20):
                if _shutdown_requested:
                    break
                time.sleep(0.5)

    finally:
        state["status"] = "stopped" if _shutdown_requested else "done"
        _save_state(state)
        _export_report(state, universe=symbols, agents=agent_ids)
        _set_status(phase="done", message=state["status"])
        _clear_pid()
        _log(
            f"Full day backtest session end — status={state['status']} "
            f"pass={state.get('pass')} date={state.get('sim_date')} "
            f"trials={state.get('total_trials')} failures={failures}"
        )

    return 0 if failures == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Slow continuous day-by-day full walk-forward backtest from 2000-01-01"
    )
    parser.add_argument(
        "--seconds-per-day",
        type=float,
        default=1.25,
        metavar="S",
        help="Sleep seconds between trading days (default: 1.25) — lower CPU",
    )
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=16,
        metavar="N",
        help="Cap long-history universe size (default: 16)",
    )
    parser.add_argument(
        "--max-agents",
        type=int,
        default=20,
        metavar="N",
        help="Cap agent roster size for CPU/memory (default: 20; 0=all)",
    )
    parser.add_argument(
        "--review-seconds",
        type=float,
        default=45.0,
        metavar="S",
        help="Seconds to show review window before auto-start (default: 45)",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Skip review window (print summary only)",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore saved state and start from 2000-01-01",
    )
    parser.add_argument(
        "--once-pass",
        action="store_true",
        help="Stop after one full pass to current date (no loop)",
    )
    parser.add_argument(
        "--rebuild-learning-every",
        type=int,
        default=100,
        metavar="N",
        help="Export/sync learning every N session days (default: 100; 0=checkpoints only)",
    )
    args = parser.parse_args()
    if args.seconds_per_day < 0.05:
        print("--seconds-per-day must be >= 0.05", file=sys.stderr)
        return 2
    if args.max_symbols < 4:
        print("--max-symbols must be >= 4", file=sys.stderr)
        return 2

    resume = not args.fresh
    summary = build_review_summary(
        seconds_per_day=args.seconds_per_day,
        max_symbols=args.max_symbols,
        max_agents=args.max_agents,
        review_seconds=args.review_seconds,
        resume=resume,
    )
    print(summary, flush=True)
    _log("=== Full day backtest review ===")
    for line in summary.splitlines():
        _log(line)

    # Always write a plain-text review file for humans (and Notepad fallback).
    review_path = OUTPUT / "history" / "full_day_backtest_review.txt"
    try:
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_path.write_text(summary, encoding="utf-8")
    except OSError:
        review_path = None

    if args.no_gui:
        if review_path and sys.platform == "win32":
            try:
                os.startfile(str(review_path))  # type: ignore[attr-defined]
            except OSError:
                pass
        if args.review_seconds > 0:
            _log(f"No-GUI review pause {args.review_seconds:.0f}s…")
            time.sleep(min(args.review_seconds, 60))
    else:
        show_review_window(summary, review_seconds=args.review_seconds)

    return run_loop(
        seconds_per_day=args.seconds_per_day,
        max_symbols=args.max_symbols,
        max_agents=args.max_agents,
        resume=resume,
        once_pass=args.once_pass,
        rebuild_learning_every=args.rebuild_learning_every,
    )


if __name__ == "__main__":
    raise SystemExit(main())
