"""Persist agent analysis over time for future runs and growth-oriented trading."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
HISTORY_ROOT = OUTPUT / "history"
SNAPSHOTS_DIR = HISTORY_ROOT / "snapshots"
TICKER_DIR = HISTORY_ROOT / "tickers"
INDEX_FILE = HISTORY_ROOT / "index.json"
ACCOUNT_VALUES_FILE = HISTORY_ROOT / "account_values.json"
AGENT_CONTEXT_FILE = OUTPUT / "agent_context.json"

MAX_SNAPSHOTS = 240
MAX_TICKER_POINTS = 120
MAX_ACCOUNT_POINTS = 500
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


def archive_pipeline_cycle(*, cycle_id: str | None = None) -> str:
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

    build_agent_context(lookback_cycles=DEFAULT_LOOKBACK_CYCLES)
    return cycle_id


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
    points.append(
        {
            "at": _now_iso(),
            "total_account_value": round(total_value, 2),
            "cash_buying_power": round(cash_buying_power, 2) if cash_buying_power is not None else None,
            "account_id_key": account_id_key,
            "source": source,
        }
    )
    data["points"] = points[-MAX_ACCOUNT_POINTS:]
    if data.get("baseline_value") is None:
        data["baseline_value"] = round(total_value, 2)
    data["latest_value"] = round(total_value, 2)
    data["growth_pct"] = _growth_pct(data)
    data["updated_at"] = _now_iso()
    _write_json(ACCOUNT_VALUES_FILE, data)
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
        return {"baseline_value": None, "latest_value": None, "growth_pct": None, "points": []}
    return data


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

    context = {
        "generated_at": _now_iso(),
        "objective": "maximize_multi_horizon_profit",
        "lookback_cycles": lookback_cycles,
        "account_growth": {
            "baseline_value": growth.get("baseline_value"),
            "latest_value": growth.get("latest_value"),
            "growth_pct": growth.get("growth_pct"),
        },
        "persistent_bullish_tickers": persistent,
        "regime_history": regime_history[-lookback_cycles:],
        "agent_run_counts": index.get("agents", {}),
        "snapshot_count": len(index.get("snapshots", [])),
        "usage": (
            "Agents and portfolio logic read this file to weight tickers with sustained bullish "
            "signals and favor trades that grow total account value."
        ),
    }
    _write_json(AGENT_CONTEXT_FILE, context)
    return context


def record_day_trade_session(state: dict[str, Any]) -> None:
    """Persist intraday P&L for future agent weighting."""
    _ensure_dirs()
    path = HISTORY_DIR / "day_trade_summary.json"
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