"""Persist agent analysis over time for future runs and growth-oriented trading."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app_paths import OUTPUT, ROOT

HISTORY_ROOT = OUTPUT / "history"
SNAPSHOTS_DIR = HISTORY_ROOT / "snapshots"
TICKER_DIR = HISTORY_ROOT / "tickers"
INDEX_FILE = HISTORY_ROOT / "index.json"
ACCOUNT_VALUES_FILE = HISTORY_ROOT / "account_values.json"
PIPELINE_RUNS_FILE = HISTORY_ROOT / "pipeline_runs.json"
RUN_CONTEXT_FILE = OUTPUT / "pipeline_run_context.json"
AGENT_CONTEXT_FILE = OUTPUT / "agent_context.json"

MAX_SNAPSHOTS = 240
MAX_TICKER_POINTS = 120
MAX_ACCOUNT_POINTS = 500
MAX_PIPELINE_RUNS = 500
DEFAULT_LOOKBACK_CYCLES = 12

BIAS_SCORES = {"BULLISH": 1.0, "NEUTRAL": 0.0, "BEARISH": -1.0}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _ensure_dirs() -> None:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    TICKER_DIR.mkdir(parents=True, exist_ok=True)


def _load_index() -> dict[str, Any]:
    data = _load_json(INDEX_FILE)
    if isinstance(data, dict):
        data.setdefault("snapshots", [])
        data.setdefault("agents", {})
        return data
    return {"snapshots": [], "agents": {}, "updated_at": _now_iso()}


def _save_index(index: dict[str, Any]) -> None:
    index["updated_at"] = _now_iso()
    _write_json(INDEX_FILE, index)


def _extract_ticker_signals(data: dict[str, Any], source: str) -> dict[str, float]:
    """Map symbol -> directional score from one agent report."""
    scores: dict[str, float] = {}
    for sig in data.get("market_signals", []):
        bias = str(sig.get("bias", "NEUTRAL")).upper()
        delta = BIAS_SCORES.get(bias, 0.0)
        for ticker in sig.get("tickers", []):
            sym = str(ticker).strip().upper()
            if sym:
                scores[sym] = scores.get(sym, 0.0) + delta
    if source == "finance":
        for opp in data.get("trading_opportunities", []):
            sym = str(opp.get("symbol", "")).strip().upper()
            if sym:
                scores[sym] = scores.get(sym, 0.0) + min(1.0, float(opp.get("opportunity_score", 0)) * 0.5)
    preds = data.get("predictions", {})
    for horizon_rows in preds.values() if isinstance(preds, dict) else []:
        for row in horizon_rows or []:
            sym = str(row.get("symbol", "")).strip().upper()
            if not sym:
                continue
            direction = str(row.get("predicted_direction", "")).lower()
            conf = float(row.get("confidence", 0.5))
            sign = 1.0 if direction == "up" else -1.0 if direction == "down" else 0.0
            scores[sym] = scores.get(sym, 0.0) + sign * conf
    return scores


def archive_agent_output(agent_id: str, output_path: Path, *, cycle_id: str | None = None) -> None:
    """Store one agent report and update per-ticker history."""
    if not output_path.exists():
        return
    data = _load_json(output_path)
    if not isinstance(data, dict):
        return

    _ensure_dirs()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    cycle_id = cycle_id or stamp
    agent_dir = SNAPSHOTS_DIR / cycle_id / "agents"
    agent_dir.mkdir(parents=True, exist_ok=True)

    dest = agent_dir / f"{agent_id}.json"
    shutil.copy2(output_path, dest)

    index = _load_index()
    index["agents"].setdefault(agent_id, {"runs": 0, "last_at": None, "last_file": str(output_path.name)})
    index["agents"][agent_id]["runs"] = int(index["agents"][agent_id].get("runs", 0)) + 1
    index["agents"][agent_id]["last_at"] = _now_iso()
    index["agents"][agent_id]["last_file"] = output_path.name
    _save_index(index)

    ticker_scores = _extract_ticker_signals(data, agent_id)
    point = {"at": _now_iso(), "agent": agent_id, "scores": ticker_scores}
    for sym, score in ticker_scores.items():
        path = TICKER_DIR / f"{sym}.json"
        series = _load_json(path)
        if not isinstance(series, dict):
            series = {"symbol": sym, "points": []}
        series.setdefault("points", []).append({"at": point["at"], "agent": agent_id, "score": score})
        series["points"] = series["points"][-MAX_TICKER_POINTS:]
        series["updated_at"] = _now_iso()
        _write_json(path, series)


def archive_pipeline_cycle(
    *,
    cycle_id: str | None = None,
    refresh_context: bool = True,
) -> str:
    """Snapshot current output artifacts after a full agent pipeline run."""
    from agents.platform_catalog import active_agent_sources

    _ensure_dirs()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    cycle_id = cycle_id or stamp
    cycle_dir = SNAPSHOTS_DIR / cycle_id
    cycle_dir.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    for src in active_agent_sources(check_remote=False):
        path = OUTPUT / src["file"]
        if path.exists():
            shutil.copy2(path, cycle_dir / path.name)
            copied.append(path.name)

    for extra in ("market_predictions.json", "portfolio.json", "strategy_plan.json"):
        path = OUTPUT / extra
        if path.exists():
            shutil.copy2(path, cycle_dir / extra)
            copied.append(extra)

    index = _load_index()
    snapshots = index.setdefault("snapshots", [])
    snapshots.append(
        {
            "cycle_id": cycle_id,
            "at": _now_iso(),
            "files": copied,
            "file_count": len(copied),
        }
    )
    index["snapshots"] = snapshots[-MAX_SNAPSHOTS:]
    _save_index(index)

    if refresh_context:
        build_agent_context(lookback_cycles=DEFAULT_LOOKBACK_CYCLES)
    return cycle_id


def new_pipeline_cycle_id() -> str:
    """Stable id shared by every artifact in one pipeline run."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_pipeline_runs_store() -> dict[str, Any]:
    data = _load_json(PIPELINE_RUNS_FILE)
    if isinstance(data, dict):
        data.setdefault("runs", [])
        return data
    return {"runs": [], "total_runs": 0, "updated_at": _now_iso()}


def _save_pipeline_runs_store(store: dict[str, Any]) -> None:
    store["updated_at"] = _now_iso()
    store["total_runs"] = len(store.get("runs") or [])
    _write_json(PIPELINE_RUNS_FILE, store)


def record_pipeline_run(
    cycle_id: str,
    *,
    agents_ok: int = 0,
    agents_total: int = 0,
    accuracy_stats: dict[str, int] | None = None,
    benchmark: dict[str, Any] | None = None,
    file_count: int = 0,
) -> dict[str, Any]:
    """Append one completed pipeline run to durable history."""
    _ensure_dirs()
    stats = accuracy_stats or {}
    bench_board = (benchmark or {}).get("leaderboard") or []
    bench_top = bench_board[0] if bench_board else {}
    bench_metrics = (benchmark or {}).get("metrics") or {}
    entry = {
        "cycle_id": cycle_id,
        "at": _now_iso(),
        "agents_ok": int(agents_ok),
        "agents_total": int(agents_total),
        "predictions_recorded": int(stats.get("recorded") or 0),
        "predictions_scored": int(stats.get("scored") or 0),
        "benchmark_trials": int(bench_metrics.get("total_trials") or 0),
        "benchmark_top_agent": bench_top.get("agent_id"),
        "benchmark_top_pct": bench_top.get("accuracy_pct"),
        "snapshot_files": int(file_count),
    }
    store = _load_pipeline_runs_store()
    runs: list[dict[str, Any]] = list(store.setdefault("runs", []))
    if not any(row.get("cycle_id") == cycle_id for row in runs):
        runs.append(entry)
    else:
        for index, row in enumerate(runs):
            if row.get("cycle_id") == cycle_id:
                runs[index] = {**row, **entry}
                break
    store["runs"] = runs[-MAX_PIPELINE_RUNS:]
    _save_pipeline_runs_store(store)
    return entry


def load_pipeline_run_context() -> dict[str, Any]:
    data = _load_json(RUN_CONTEXT_FILE)
    return data if isinstance(data, dict) else {}


def write_pipeline_run_context(*, cycle_id: str | None = None) -> dict[str, Any]:
    """Publish prior pipeline memory for the next agent cycle."""
    from agent_learning import get_agent_learning

    index = _load_index()
    runs_store = _load_pipeline_runs_store()
    prior_runs = list(runs_store.get("runs") or [])[-8:]

    learning_by_agent: dict[str, Any] = {}
    try:
        from agents.platform_catalog import active_agent_sources

        for src in active_agent_sources(check_remote=False):
            aid = src["id"]
            row = get_agent_learning(aid)
            if row is None:
                continue
            learning_by_agent[aid] = {
                "posture": row.posture,
                "lessons": list(row.lessons),
                "avoid_symbols": sorted(row.avoid_symbols)[:10],
                "trust_symbols": sorted(row.trust_symbols)[:10],
                "bias_drift": row.bias_drift,
                "fusion_multiplier": row.fusion_multiplier,
                "preferred_horizon": row.preferred_horizon,
            }
    except Exception:
        pass

    accuracy_board: list[dict[str, Any]] = []
    accuracy_board_direction: list[dict[str, Any]] = []
    try:
        from prediction_accuracy import accuracy_leaderboard

        accuracy_board = accuracy_leaderboard(top_n=12, kind="combined")
        accuracy_board_direction = accuracy_leaderboard(top_n=12, kind="direction")
    except Exception:
        pass

    regime_history: list[dict[str, Any]] = []
    for snap in reversed(index.get("snapshots", [])[-DEFAULT_LOOKBACK_CYCLES:]):
        snap_cycle = snap.get("cycle_id")
        if not snap_cycle:
            continue
        markets_path = SNAPSHOTS_DIR / str(snap_cycle) / "markets.json"
        markets = _load_json(markets_path)
        if isinstance(markets, dict):
            metrics = markets.get("metrics", {})
            regime_history.append(
                {
                    "at": snap.get("at"),
                    "cycle_id": snap_cycle,
                    "risk_on_score": metrics.get("risk_on_score"),
                    "trend_label": metrics.get("trend_label"),
                }
            )

    context = {
        "cycle_id": cycle_id,
        "generated_at": _now_iso(),
        "total_pipeline_runs": int(runs_store.get("total_runs") or len(runs_store.get("runs") or [])),
        "prior_pipeline_runs": prior_runs,
        "agent_learning": learning_by_agent,
        "persistent_bullish_tickers": get_persistent_bullish_tickers(top_n=15),
        "accuracy_leaderboard": accuracy_board,
        "accuracy_leaderboard_direction": accuracy_board_direction,
        "regime_history": list(reversed(regime_history))[-DEFAULT_LOOKBACK_CYCLES:],
        "usage": (
            "Loaded at the start of each pipeline run. Agents and fusion use lessons, "
            "symbol trust/avoid lists, and prior cycle outcomes to steer future decisions."
        ),
    }
    _write_json(RUN_CONTEXT_FILE, context)
    return context


def finalize_pipeline_cycle(
    cycle_id: str,
    *,
    agents_ok: int = 0,
    agents_total: int = 0,
    accuracy_stats: dict[str, int] | None = None,
    benchmark: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a completed pipeline run and refresh learning/context for the next cycle."""
    index = _load_index()
    snap = next(
        (row for row in reversed(index.get("snapshots", [])) if row.get("cycle_id") == cycle_id),
        {},
    )
    entry = record_pipeline_run(
        cycle_id,
        agents_ok=agents_ok,
        agents_total=agents_total,
        accuracy_stats=accuracy_stats,
        benchmark=benchmark,
        file_count=int(snap.get("file_count") or 0),
    )
    try:
        from agent_learning import rebuild_agent_learning

        rebuild_agent_learning()
    except Exception:
        pass
    build_agent_context(lookback_cycles=DEFAULT_LOOKBACK_CYCLES)
    write_pipeline_run_context(cycle_id=cycle_id)
    return entry


def record_account_value(
    total_value: float,
    *,
    account_id_key: str = "",
    cash_buying_power: float | None = None,
    source: str = "plan",
) -> None:
    """Track account value over time to measure growth."""
    if total_value <= 0:
        return
    _ensure_dirs()
    data = _load_json(ACCOUNT_VALUES_FILE)
    if not isinstance(data, dict):
        data = {"points": [], "baseline_value": None, "objective": "grow_account_value"}
    points: list[dict[str, Any]] = data.setdefault("points", [])
    stamp = _now_iso()
    rounded_total = round(total_value, 2)
    rounded_cash = round(cash_buying_power, 2) if cash_buying_power is not None else None

    if points:
        last = points[-1]
        try:
            last_total = float(last.get("total_account_value", 0) or 0)
        except (TypeError, ValueError):
            last_total = 0.0
        last_cash = last.get("cash_buying_power")
        last_at = str(last.get("at") or "")
        try:
            last_ts = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
            age_sec = (datetime.now(timezone.utc) - last_ts).total_seconds()
        except ValueError:
            age_sec = 999999.0
        same_account = not account_id_key or str(last.get("account_id_key") or "") == str(account_id_key)
        value_unchanged = abs(last_total - rounded_total) < 0.01
        cash_unchanged = (
            rounded_cash is None
            or last_cash is None
            or abs(float(last_cash) - float(rounded_cash)) < 0.01
        )
        if same_account and value_unchanged and cash_unchanged and age_sec < 900:
            if rounded_cash is not None:
                last["cash_buying_power"] = rounded_cash
            last["source"] = source
            data["latest_value"] = rounded_total
            data["growth_pct"] = _growth_pct(data)
            data["updated_at"] = stamp
            _write_json(ACCOUNT_VALUES_FILE, data)
            return

    points.append(
        {
            "at": stamp,
            "total_account_value": rounded_total,
            "cash_buying_power": rounded_cash,
            "account_id_key": account_id_key,
            "source": source,
        }
    )
    data["points"] = points[-MAX_ACCOUNT_POINTS:]
    if data.get("baseline_value") is None:
        data["baseline_value"] = rounded_total
    data["latest_value"] = rounded_total
    data["growth_pct"] = _growth_pct(data)
    data["updated_at"] = stamp
    _write_json(ACCOUNT_VALUES_FILE, data)
    try:
        from account_balance_penalty import rebuild_balance_penalties

        rebuild_balance_penalties()
    except Exception:
        pass
    build_agent_context()


def _growth_pct(account_data: dict[str, Any]) -> float | None:
    baseline = account_data.get("baseline_value")
    latest = account_data.get("latest_value")
    if not baseline or not latest:
        return None
    try:
        return round((float(latest) - float(baseline)) / float(baseline) * 100, 2)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def get_account_growth() -> dict[str, Any]:
    data = _load_json(ACCOUNT_VALUES_FILE)
    if not isinstance(data, dict):
        return {
            "baseline_value": None,
            "latest_value": None,
            "growth_pct": None,
            "points": [],
            "accounts": {},
        }
    data.setdefault("accounts", {})
    return data


def set_account_opened_at(
    account_id_key: str,
    opened_at: str,
    *,
    opening_balance: float | None = None,
) -> None:
    """Persist the brokerage account open date for equity-curve anchoring."""
    key = str(account_id_key or "").strip()
    opened = str(opened_at or "").strip()
    if not key or not opened:
        return
    _ensure_dirs()
    data = get_account_growth()
    accounts = data.setdefault("accounts", {})
    if not isinstance(accounts, dict):
        accounts = {}
        data["accounts"] = accounts
    entry: dict[str, Any] = {"opened_at": opened}
    if opening_balance is not None:
        entry["opening_balance"] = round(float(opening_balance), 2)
    accounts[key] = {**accounts.get(key, {}), **entry}
    data["updated_at"] = _now_iso()
    _write_json(ACCOUNT_VALUES_FILE, data)


def get_ticker_momentum(symbol: str, *, lookback_points: int = 8) -> float:
    """Positive = increasingly bullish across recent agent cycles."""
    path = TICKER_DIR / f"{symbol.upper()}.json"
    series = _load_json(path)
    if not isinstance(series, dict):
        return 0.0
    points = series.get("points", [])[-lookback_points:]
    if len(points) < 2:
        return float(points[-1].get("score", 0)) if points else 0.0
    scores = [float(p.get("score", 0)) for p in points]
    half = max(1, len(scores) // 2)
    recent = sum(scores[-half:]) / half
    prior = sum(scores[:-half]) / max(1, len(scores) - half)
    return recent - prior


def get_persistent_bullish_tickers(*, top_n: int = 24, min_cycles: int = 2) -> list[dict[str, Any]]:
    """Tickers with repeated bullish agent signals across history."""
    if not TICKER_DIR.exists():
        return []
    ranked: list[dict[str, Any]] = []
    for path in TICKER_DIR.glob("*.json"):
        series = _load_json(path)
        if not isinstance(series, dict):
            continue
        points = series.get("points", [])
        if len(points) < min_cycles:
            continue
        recent = points[-DEFAULT_LOOKBACK_CYCLES:]
        bullish_hits = sum(1 for p in recent if float(p.get("score", 0)) > 0.15)
        avg_score = sum(float(p.get("score", 0)) for p in recent) / max(1, len(recent))
        momentum = get_ticker_momentum(path.stem, lookback_points=min(8, len(recent)))
        if bullish_hits < min_cycles and avg_score <= 0:
            continue
        ranked.append(
            {
                "symbol": path.stem,
                "bullish_hits": bullish_hits,
                "avg_score": round(avg_score, 3),
                "momentum": round(momentum, 3),
                "composite": round(avg_score + momentum * 0.6 + bullish_hits * 0.05, 3),
            }
        )
    ranked.sort(key=lambda row: row["composite"], reverse=True)
    return ranked[:top_n]


def load_recent_agent_report(agent_id: str, *, max_age_cycles: int = 5) -> dict[str, Any] | None:
    """Return the most recent archived report for an agent (for future analysis)."""
    index = _load_index()
    snapshots = list(reversed(index.get("snapshots", [])))
    checked = 0
    for snap in snapshots:
        if checked >= max_age_cycles:
            break
        checked += 1
        cycle_id = snap.get("cycle_id")
        if not cycle_id:
            continue
        path = SNAPSHOTS_DIR / str(cycle_id) / "agents" / f"{agent_id}.json"
        if not path.exists():
            path = SNAPSHOTS_DIR / str(cycle_id) / f"{agent_id.replace('-', '_')}.json"
        data = _load_json(path)
        if isinstance(data, dict):
            return data
    return None


def build_agent_context(*, lookback_cycles: int = DEFAULT_LOOKBACK_CYCLES) -> dict[str, Any]:
    """Condensed history file agents and portfolio logic can read on the next run."""
    index = _load_index()
    growth = get_account_growth()
    persistent = get_persistent_bullish_tickers(top_n=20)

    regime_history: list[dict[str, Any]] = []
    for snap in reversed(index.get("snapshots", [])[-lookback_cycles:]):
        cycle_id = snap.get("cycle_id")
        if not cycle_id:
            continue
        markets_path = SNAPSHOTS_DIR / str(cycle_id) / "markets.json"
        markets = _load_json(markets_path)
        if isinstance(markets, dict):
            metrics = markets.get("metrics", {})
            regime_history.append(
                {
                    "at": snap.get("at"),
                    "risk_on_score": metrics.get("risk_on_score"),
                    "trend_label": metrics.get("trend_label"),
                }
            )

    accuracy_board: list[dict[str, Any]] = []
    try:
        from prediction_accuracy import accuracy_leaderboard

        accuracy_board = accuracy_leaderboard(top_n=12)
    except Exception:
        pass

    pipeline_runs_store = _load_pipeline_runs_store()
    learning_store = _load_json(HISTORY_ROOT / "agent_learning.json") or {}

    balance_penalties: dict[str, Any] = {}
    try:
        from account_balance_penalty import rebuild_balance_penalties

        balance_penalties = rebuild_balance_penalties()
    except Exception:
        pass

    context = {
        "generated_at": _now_iso(),
        "objective": "maximize_multi_horizon_profit",
        "accuracy_objective": "maximize_prediction_accuracy",
        "accuracy_leaderboard": accuracy_board,
        "lookback_cycles": lookback_cycles,
        "account_growth": {
            "baseline_value": growth.get("baseline_value"),
            "latest_value": growth.get("latest_value"),
            "growth_pct": growth.get("growth_pct"),
            "is_declining": balance_penalties.get("is_declining"),
            "is_rising": balance_penalties.get("is_rising"),
            "trend": balance_penalties.get("trend"),
            "penalty_strength": (balance_penalties.get("account") or {}).get("penalty_strength"),
            "reward_strength": (balance_penalties.get("account") or {}).get("reward_strength"),
            "daily_growth_pct": balance_penalties.get("daily_growth_pct"),
            "benchmark_tiers_hit": balance_penalties.get("benchmark_tiers_hit", []),
            "benchmark_peak_pct": balance_penalties.get("benchmark_peak_pct", 0),
        },
        "balance_penalties": {
            "updated_at": balance_penalties.get("updated_at"),
            "held_symbols": balance_penalties.get("held_symbols", []),
            "agents": balance_penalties.get("agents", {}),
        },
        "persistent_bullish_tickers": persistent,
        "regime_history": regime_history[-lookback_cycles:],
        "agent_run_counts": index.get("agents", {}),
        "snapshot_count": len(index.get("snapshots", [])),
        "pipeline_runs": {
            "total": int(pipeline_runs_store.get("total_runs") or len(pipeline_runs_store.get("runs") or [])),
            "recent": list(pipeline_runs_store.get("runs") or [])[-lookback_cycles:],
        },
        "agent_learning": learning_store.get("agents") if isinstance(learning_store, dict) else {},
        "usage": (
            "Agents and portfolio logic read this file to weight tickers with sustained bullish "
            "signals, favor high-accuracy agents, apply lessons from prior pipeline runs, "
            "and grow total account value."
        ),
    }
    _write_json(AGENT_CONTEXT_FILE, context)
    return context


def record_day_trade_session(state: dict[str, Any]) -> None:
    """Persist intraday P&L for future agent weighting."""
    _ensure_dirs()
    path = HISTORY_ROOT / "day_trade_summary.json"
    data = _load_json(path)
    if not isinstance(data, dict):
        data = {"sessions": [], "objective": "grow_account_value"}
    sessions: list[dict[str, Any]] = data.setdefault("sessions", [])
    entry = {
        "session_date": state.get("session_date"),
        "stats": state.get("stats", {}),
        "closed_trades": state.get("closed_trades", [])[-20:],
        "open_positions": len(state.get("positions", [])),
        "recorded_at": _now_iso(),
    }
    sessions.append(entry)
    data["sessions"] = sessions[-60:]
    data["latest"] = entry
    _write_json(path, data)
    build_agent_context()


def history_boost_for_portfolio(scores: dict[str, Any], *, scale: float = 0.25) -> None:
    """Apply historical momentum boosts to portfolio ticker scores (mutates score objects)."""
    for row in get_persistent_bullish_tickers(top_n=30):
        sym = row["symbol"]
        entry = scores.get(sym)
        if entry is None:
            continue
        boost = row["composite"] * scale
        entry.score += boost
        entry.sources.add("history")
        if f"History: {row['bullish_hits']} bullish cycles" not in entry.notes:
            entry.notes.append(f"History: {row['bullish_hits']} bullish cycles, momentum {row['momentum']:+.2f}")