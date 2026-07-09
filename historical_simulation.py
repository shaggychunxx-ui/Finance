"""Historical walk-forward simulation for Finance agents.

Replays agent signal strategies on daily price bars and scores archived
pipeline snapshots against realized returns. Complements live walk-forward
accuracy tracking in prediction_accuracy.py.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app_paths import OUTPUT
from price_history import (
    BAR_CACHE_DIR,
    bar_closes,
    bar_datetimes,
    bar_index_at_or_before,
    fetch_daily_bars,
    forward_return_pct,
    load_daily_bars,
)

HISTORY_ROOT = OUTPUT / "history"
SNAPSHOTS_DIR = HISTORY_ROOT / "snapshots"
SIM_FILE = HISTORY_ROOT / "historical_simulation.json"
BENCHMARK_FILE = HISTORY_ROOT / "accuracy_benchmark.json"
INDEX_FILE = HISTORY_ROOT / "index.json"

DEFAULT_LOOKBACK_DAYS = 365
DEFAULT_MAX_SYMBOLS = 32
DEFAULT_BENCHMARK_TRIALS = 1000
SIGNAL_STEP_BARS = 5
MIN_SIM_SAMPLES = 8
HISTORICAL_BLEND = 0.35
SKIP_AGENTS = frozenset({"data-steward", "records-management", "market-predictor", "etrade", "history"})

HORIZON_BARS = {"24h": 1, "1wk": 5, "1mo": 21, "1yr": 252}
HORIZON_HOURS = {"24h": 24, "1wk": 168, "1mo": 720, "1yr": 8760}
HORIZON_MOVE_PCT = {"24h": 0.5, "1wk": 1.5, "1mo": 3.0, "1yr": 8.0}

AGENT_PROXY_ETF: dict[str, str] = {
    "electricity": "XLU",
    "grid": "XLU",
    "meteorology": "XLE",
    "transportation": "IYT",
    "logistics": "ZIM",
    "patents": "XLK",
    "sales-analytics": "XRT",
    "geopolitics": "SPY",
    "events": "SPY",
    "order-execution": "SPY",
}

MOMENTUM_AGENTS = frozenset({
    "markets", "finance", "financial-data", "datascience",
    "sales-analytics", "research-statistics",
})
MEAN_REVERSION_AGENTS = frozenset({
    "empirical-probability", "theoretical-probability", "combined-conditional",
})
RISK_OFF_AGENTS = frozenset({"geopolitics", "events"})


@dataclass
class SimTrial:
    agent_id: str
    symbol: str
    horizon: str
    predicted_direction: str
    actual_direction: str
    predicted_return_pct: float | None
    actual_return_pct: float
    hit: bool
    confidence: float
    source: str
    simulated_at: str


@dataclass
class HistoricalSimReport:
    trials: list[SimTrial]
    agents: dict[str, dict[str, Any]]
    leaderboard: list[dict[str, Any]]
    universe: list[str]
    bar_walk_trials: int
    snapshot_trials: int
    expert_summary: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


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


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


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


def _return_pct(closes: list[float], idx: int, lookback: int) -> float | None:
    if idx < lookback:
        return None
    start = closes[idx - lookback]
    if start <= 0:
        return None
    return (closes[idx] / start - 1.0) * 100.0


def _rolling_vol_pct(closes: list[float], idx: int, window: int = 20) -> float | None:
    if idx < window:
        return None
    rets = []
    for j in range(idx - window + 1, idx + 1):
        if closes[j - 1] <= 0:
            continue
        rets.append((closes[j] / closes[j - 1] - 1.0) * 100.0)
    if len(rets) < window // 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    return var ** 0.5


def _estimate_return(direction: str, confidence: float) -> float:
    from agent_fusion import estimate_return_from_bias

    return estimate_return_from_bias(direction, confidence=confidence)


def _sim_momentum(closes: list[float], idx: int) -> tuple[str, float]:
    r5 = _return_pct(closes, idx, 5)
    r20 = _return_pct(closes, idx, 20)
    if r5 is None or r20 is None:
        return "flat", 0.35
    if r5 > 0.4 and r20 > 0:
        return "up", min(0.88, 0.52 + (r5 + r20) / 25.0)
    if r5 < -0.4 and r20 < 0:
        return "down", min(0.88, 0.52 + abs(r5 + r20) / 25.0)
    return "flat", 0.35


def _sim_mean_reversion(closes: list[float], idx: int) -> tuple[str, float]:
    if idx < 2:
        return "flat", 0.35
    d1 = closes[idx] / closes[idx - 1] - 1.0
    d2 = closes[idx - 1] / closes[idx - 2] - 1.0
    if d1 < 0 and d2 < 0:
        return "up", 0.58
    if d1 > 0 and d2 > 0:
        return "down", 0.54
    return "flat", 0.35


def _sim_risk_off(closes: list[float], idx: int, proxy_closes: list[float] | None) -> tuple[str, float]:
    ref = proxy_closes if proxy_closes and len(proxy_closes) > idx else closes
    vol = _rolling_vol_pct(ref, idx, 20)
    r5 = _return_pct(ref, idx, 5)
    if vol is not None and vol >= 2.5:
        return "down", min(0.82, 0.5 + vol / 10.0)
    if r5 is not None and r5 < -2.0:
        return "down", 0.62
    if r5 is not None and r5 > 1.5:
        return "up", 0.55
    return "flat", 0.38


def _sim_zscore(closes: list[float], idx: int) -> tuple[str, float]:
    window = 20
    if idx < window:
        return "flat", 0.35
    segment = closes[idx - window + 1 : idx + 1]
    mean = sum(segment) / len(segment)
    var = sum((x - mean) ** 2 for x in segment) / len(segment)
    if var <= 0:
        return "flat", 0.35
    z = (closes[idx] - mean) / (var ** 0.5)
    if z <= -1.2:
        return "up", min(0.85, 0.55 + abs(z) * 0.08)
    if z >= 1.2:
        return "down", min(0.85, 0.55 + abs(z) * 0.08)
    return "flat", 0.35


def _agent_signal(
    agent_id: str,
    closes: list[float],
    idx: int,
    *,
    proxy_closes: list[float] | None,
) -> tuple[str, float]:
    if agent_id in MOMENTUM_AGENTS:
        return _sim_momentum(closes, idx)
    if agent_id in MEAN_REVERSION_AGENTS:
        return _sim_mean_reversion(closes, idx)
    if agent_id in RISK_OFF_AGENTS:
        return _sim_risk_off(closes, idx, proxy_closes)
    if agent_id in {"theoretical-probability", "research-statistics", "combined-conditional"}:
        return _sim_zscore(closes, idx)
    proxy = proxy_closes
    if proxy and len(proxy) > idx:
        return _sim_momentum(proxy, idx)
    return _sim_momentum(closes, idx)


def _collect_universe(*, max_symbols: int) -> list[str]:
    from symbol_universe import collect_liquid_universe

    portfolio = _load_json(OUTPUT / "portfolio.json")
    fused = _load_json(OUTPUT / "market_predictions.json")
    return collect_liquid_universe(
        portfolio=portfolio if isinstance(portfolio, dict) else None,
        predictions=fused if isinstance(fused, dict) else None,
        max_symbols=max_symbols,
        output_dir=OUTPUT,
        expand_remote=max_symbols > 80,
    )


def _universe_agent_cap(universe: list[str], *, default: int) -> int:
    if len(universe) <= 40:
        return default
    return min(64, max(default, len(universe) // 6))


def _agent_symbols(agent_id: str, universe: list[str]) -> list[str]:
    from agent_fusion import agent_in_domain

    if agent_id in SKIP_AGENTS:
        return []
    domain_cap = _universe_agent_cap(universe, default=12)
    broad_cap = _universe_agent_cap(universe, default=8)
    narrow_cap = _universe_agent_cap(universe, default=4)
    matched = [sym for sym in universe if agent_in_domain(agent_id, sym)]
    if matched:
        return matched[:domain_cap]
    if agent_id in MOMENTUM_AGENTS or agent_id in MEAN_REVERSION_AGENTS:
        return universe[:broad_cap]
    proxy = AGENT_PROXY_ETF.get(agent_id)
    if proxy:
        proxy_matches = [sym for sym in universe if agent_in_domain(agent_id, sym)]
        mid_cap = _universe_agent_cap(universe, default=6)
        return proxy_matches[:mid_cap] or universe[:narrow_cap]
    return universe[:narrow_cap]


def _ensure_proxy_bars(
    proxy_symbols: set[str],
    *,
    lookback_days: int,
    bar_cache: dict[str, list[dict[str, Any]]],
) -> None:
    for sym in sorted(proxy_symbols):
        if sym not in bar_cache:
            bar_cache[sym] = fetch_daily_bars(sym, days=lookback_days)


def _bar_walk_forward(
    agent_id: str,
    symbols: list[str],
    *,
    lookback_days: int,
    bar_cache: dict[str, list[dict[str, Any]]],
    horizons: tuple[str, ...] = ("24h", "1wk", "1mo"),
    signal_step_bars: int = SIGNAL_STEP_BARS,
    max_trials: int | None = None,
) -> list[SimTrial]:
    trials: list[SimTrial] = []
    proxy_sym = AGENT_PROXY_ETF.get(agent_id, "SPY")
    proxy_closes = bar_closes(bar_cache.get(proxy_sym, []))

    for symbol in symbols:
        bars = bar_cache.get(symbol)
        if not bars:
            continue
        closes = bar_closes(bars)
        dates = bar_datetimes(bars)
        if len(closes) < 40:
            continue
        min_start = 25
        fwd_max = max(HORIZON_BARS.get(h, 1) for h in horizons)
        max_start = len(closes) - fwd_max - 1
        if max_start <= min_start:
            continue

        step = max(1, int(signal_step_bars))
        for idx in range(min_start, max_start, step):
            if max_trials is not None and len(trials) >= max_trials:
                return trials
            direction, confidence = _agent_signal(
                agent_id, closes, idx, proxy_closes=proxy_closes or None
            )
            predicted_return = _estimate_return(direction, confidence)
            simulated_at = dates[idx].isoformat() if idx < len(dates) else _now_iso()

            for horizon in horizons:
                if max_trials is not None and len(trials) >= max_trials:
                    return trials
                fwd = HORIZON_BARS.get(horizon, 1)
                actual_ret = forward_return_pct(closes, idx, fwd)
                if actual_ret is None:
                    continue
                actual_dir = _actual_direction(actual_ret, horizon=horizon)
                hit = _prediction_hit(direction, actual_dir)
                trials.append(
                    SimTrial(
                        agent_id=agent_id,
                        symbol=symbol,
                        horizon=horizon,
                        predicted_direction=direction,
                        actual_direction=actual_dir,
                        predicted_return_pct=round(predicted_return, 3),
                        actual_return_pct=round(actual_ret, 3),
                        hit=hit,
                        confidence=round(confidence, 3),
                        source="bar_walk_forward",
                        simulated_at=simulated_at,
                    )
                )
    return trials


def _bias_direction(bias: str) -> str:
    b = str(bias or "").upper()
    if b == "BULLISH":
        return "up"
    if b == "BEARISH":
        return "down"
    return "flat"


def _extract_snapshot_predictions(
    agent_id: str,
    data: dict[str, Any],
    *,
    recorded_at: str,
    quotes: dict[str, float],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    preds = data.get("predictions", {})
    if isinstance(preds, dict):
        for horizon, items in preds.items():
            if horizon not in HORIZON_BARS:
                continue
            for row in items or []:
                if not isinstance(row, dict):
                    continue
                sym = str(row.get("symbol", "")).upper()
                if not sym:
                    continue
                rows.append(
                    {
                        "agent_id": agent_id,
                        "symbol": sym,
                        "horizon": horizon,
                        "predicted_direction": str(row.get("predicted_direction", "flat")).lower(),
                        "confidence": float(row.get("confidence", 0.5)),
                        "predicted_return_pct": row.get("predicted_return_pct"),
                        "price_at_prediction": row.get("price_at_prediction") or quotes.get(sym),
                        "recorded_at": recorded_at,
                    }
                )

    for sig in data.get("market_signals", []):
        if not isinstance(sig, dict):
            continue
        direction = _bias_direction(sig.get("bias", "NEUTRAL"))
        conf = 0.55 if direction == "up" else 0.45 if direction == "down" else 0.35
        for ticker in sig.get("tickers", []):
            sym = str(ticker).upper()
            rows.append(
                {
                    "agent_id": agent_id,
                    "symbol": sym,
                    "horizon": "24h",
                    "predicted_direction": direction,
                    "confidence": conf,
                    "predicted_return_pct": _estimate_return(direction, conf),
                    "price_at_prediction": quotes.get(sym),
                    "recorded_at": recorded_at,
                }
            )
    return rows


def _resolve_snapshot_agent_file(cycle_dir: Path, agent_id: str, filename: str) -> Path | None:
    candidates = [
        cycle_dir / "agents" / f"{agent_id}.json",
        cycle_dir / filename,
        cycle_dir / f"{agent_id.replace('-', '_')}.json",
        cycle_dir / "agents" / filename,
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _snapshot_replay(
    *,
    bar_cache: dict[str, list[dict[str, Any]]],
    max_cycles: int = 40,
) -> list[SimTrial]:
    from agents.platform_catalog import active_agent_sources
    from symbol_universe import is_liquid_symbol

    index = _load_json(INDEX_FILE)
    if not isinstance(index, dict):
        return []
    now = datetime.now(timezone.utc)
    snapshots = list(index.get("snapshots") or [])
    snapshots.sort(key=lambda row: str(row.get("at") or ""))
    trials: list[SimTrial] = []
    processed_cycles = 0

    for snap in snapshots:
        if processed_cycles >= max_cycles:
            break
        cycle_id = snap.get("cycle_id")
        recorded_at = str(snap.get("at") or "")
        if not cycle_id or not recorded_at:
            continue
        recorded_dt = _parse_iso(recorded_at)
        if recorded_dt is None:
            continue
        if (now - recorded_dt) < timedelta(hours=HORIZON_HOURS["24h"]):
            continue

        cycle_dir = SNAPSHOTS_DIR / str(cycle_id)
        if not cycle_dir.exists():
            continue
        processed_cycles += 1

        quotes: dict[str, float] = {}
        for src in active_agent_sources(check_remote=False):
            agent_id = src["id"]
            if agent_id in SKIP_AGENTS:
                continue
            path = _resolve_snapshot_agent_file(cycle_dir, agent_id, src["file"])
            if path is None:
                continue
            data = _load_json(path)
            if not isinstance(data, dict):
                continue
            for pred in _extract_snapshot_predictions(agent_id, data, recorded_at=recorded_at, quotes=quotes):
                sym = pred["symbol"]
                if not is_liquid_symbol(sym):
                    continue
                horizon = pred["horizon"]
                hours = HORIZON_HOURS.get(horizon, 24)
                if (now - recorded_dt) < timedelta(hours=hours):
                    continue
                bars = bar_cache.get(sym)
                if not bars:
                    bars = fetch_daily_bars(sym, days=DEFAULT_LOOKBACK_DAYS + 120)
                    bar_cache[sym] = bars
                closes = bar_closes(bars)
                dates = bar_datetimes(bars)
                if len(closes) < 5:
                    continue
                start_idx = bar_index_at_or_before(dates, recorded_dt)
                if start_idx is None:
                    continue
                fwd = HORIZON_BARS.get(horizon, 1)
                actual_ret = forward_return_pct(closes, start_idx, fwd)
                if actual_ret is None:
                    continue
                predicted = str(pred.get("predicted_direction", "flat")).lower()
                actual_dir = _actual_direction(actual_ret, horizon=horizon)
                trials.append(
                    SimTrial(
                        agent_id=agent_id,
                        symbol=sym,
                        horizon=horizon,
                        predicted_direction=predicted,
                        actual_direction=actual_dir,
                        predicted_return_pct=(
                            float(pred["predicted_return_pct"])
                            if pred.get("predicted_return_pct") is not None
                            else None
                        ),
                        actual_return_pct=round(actual_ret, 3),
                        hit=_prediction_hit(predicted, actual_dir),
                        confidence=float(pred.get("confidence", 0.5)),
                        source="snapshot_replay",
                        simulated_at=recorded_at,
                    )
                )
    return trials


def _aggregate_trials(trials: list[SimTrial]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    agents: dict[str, dict[str, Any]] = {}
    for trial in trials:
        bucket = agents.setdefault(
            trial.agent_id,
            {
                "total": 0,
                "hits": 0,
                "by_horizon": {},
                "by_source": {},
                "avg_return_when_hit": [],
            },
        )
        bucket["total"] += 1
        bucket["hits"] += 1 if trial.hit else 0
        hb = bucket["by_horizon"].setdefault(trial.horizon, {"total": 0, "hits": 0})
        hb["total"] += 1
        hb["hits"] += 1 if trial.hit else 0
        sb = bucket["by_source"].setdefault(trial.source, {"total": 0, "hits": 0})
        sb["total"] += 1
        sb["hits"] += 1 if trial.hit else 0
        if trial.hit:
            bucket["avg_return_when_hit"].append(trial.actual_return_pct)

    leaderboard: list[dict[str, Any]] = []
    for aid, bucket in agents.items():
        total = int(bucket["total"])
        hits = int(bucket["hits"])
        accuracy_pct = round(hits / total * 100, 1) if total else None
        hit_returns = bucket.get("avg_return_when_hit") or []
        avg_hit_return = round(sum(hit_returns) / len(hit_returns), 3) if hit_returns else None
        weight_multiplier = (
            round(max(0.5, min(1.5, 0.5 + float(accuracy_pct) / 100.0)), 3)
            if total >= MIN_SIM_SAMPLES and accuracy_pct is not None
            else 1.0
        )
        entry = {
            "agent_id": aid,
            "total_trials": total,
            "hits": hits,
            "accuracy_pct": accuracy_pct,
            "avg_return_when_hit_pct": avg_hit_return,
            "weight_multiplier": weight_multiplier,
            "by_horizon": {
                h: {
                    "total": v["total"],
                    "hits": v["hits"],
                    "accuracy_pct": round(v["hits"] / v["total"] * 100, 1) if v["total"] else None,
                }
                for h, v in bucket.get("by_horizon", {}).items()
            },
            "by_source": {
                s: {
                    "total": v["total"],
                    "hits": v["hits"],
                    "accuracy_pct": round(v["hits"] / v["total"] * 100, 1) if v["total"] else None,
                }
                for s, v in bucket.get("by_source", {}).items()
            },
        }
        bucket.clear()
        bucket.update(entry)
        agents[aid] = bucket
        if total >= MIN_SIM_SAMPLES and accuracy_pct is not None:
            leaderboard.append(entry)

    leaderboard.sort(
        key=lambda row: (row.get("accuracy_pct") or 0, row.get("total_trials") or 0),
        reverse=True,
    )
    return agents, leaderboard


def _estimate_walk_forward_trials(
    *,
    agent_count: int,
    symbol_count: int,
    lookback_days: int,
    signal_step_bars: int,
    horizons: tuple[str, ...],
) -> int:
    trading_bars = max(40, int(lookback_days * 0.68))
    fwd_max = max(HORIZON_BARS.get(h, 1) for h in horizons)
    min_start = 25
    max_start = max(min_start + 1, trading_bars - fwd_max - 1)
    steps = max(1, (max_start - min_start) // max(1, signal_step_bars))
    symbols_per_agent = min(12, max(4, symbol_count // 2))
    return max(1, agent_count * symbols_per_agent * steps * len(horizons))


def run_historical_simulation(
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    max_symbols: int = DEFAULT_MAX_SYMBOLS,
    quick: bool = False,
    output: Path | None = None,
    horizons: tuple[str, ...] | None = None,
    signal_step_bars: int = SIGNAL_STEP_BARS,
    max_trials: int | None = None,
    trial_cap: int | None = None,
    include_snapshots: bool = True,
    write_output: bool = True,
) -> dict[str, Any]:
    """Run bar walk-forward and snapshot replay historical simulations."""
    from agents.platform_catalog import active_agent_sources

    BAR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    universe = _collect_universe(max_symbols=max_symbols if not quick else min(max_symbols, 20))
    bar_cache: dict[str, list[dict[str, Any]]] = {}

    proxy_syms = set(AGENT_PROXY_ETF.values()) | {"SPY", "QQQ"}
    fetch_list = list(dict.fromkeys(universe + sorted(proxy_syms)))
    throttle = 0.15 if quick else 0.08 if len(fetch_list) > 120 else 0.0
    for i, sym in enumerate(fetch_list):
        if throttle and i > 0 and i % 4 == 0:
            time.sleep(throttle)
        bar_cache[sym] = fetch_daily_bars(sym, days=lookback_days, use_cache=True)

    _ensure_proxy_bars(proxy_syms, lookback_days=lookback_days, bar_cache=bar_cache)

    all_trials: list[SimTrial] = []
    if horizons is None:
        horizons = ("24h", "1wk") if quick else ("24h", "1wk", "1mo")

    for src in active_agent_sources(check_remote=False):
        if max_trials is not None and len(all_trials) >= max_trials:
            break
        agent_id = src["id"]
        if agent_id in SKIP_AGENTS:
            continue
        symbols = _agent_symbols(agent_id, universe)
        if not symbols:
            continue
        remaining = None if max_trials is None else max(0, max_trials - len(all_trials))
        all_trials.extend(
            _bar_walk_forward(
                agent_id,
                symbols,
                lookback_days=lookback_days,
                bar_cache=bar_cache,
                horizons=horizons,
                signal_step_bars=signal_step_bars,
                max_trials=remaining,
            )
        )

    snapshot_trials: list[SimTrial] = []
    if include_snapshots and (max_trials is None or len(all_trials) < max_trials):
        snapshot_trials = _snapshot_replay(bar_cache=bar_cache, max_cycles=20 if quick else 50)
        if max_trials is not None:
            snapshot_trials = snapshot_trials[: max(0, max_trials - len(all_trials))]
    all_trials.extend(snapshot_trials)

    if trial_cap is not None and len(all_trials) > trial_cap:
        all_trials = _subsample_trials(all_trials, trial_cap)

    agents, leaderboard = _aggregate_trials(all_trials)
    bar_count = sum(1 for t in all_trials if t.source == "bar_walk_forward")
    snap_count = sum(1 for t in all_trials if t.source == "snapshot_replay")

    if leaderboard:
        top = leaderboard[0]
        summary = (
            f"Historical simulation: {len(all_trials)} trials across {len(universe)} symbols "
            f"({bar_count} bar walk-forward, {snap_count} snapshot replay). "
            f"Top agent {top['agent_id']} at {top['accuracy_pct']}% accuracy "
            f"({top['total_trials']} trials)."
        )
    else:
        summary = (
            f"Historical simulation: {len(all_trials)} trials recorded; "
            f"need {MIN_SIM_SAMPLES}+ trials per agent for ranked accuracy."
        )

    total_trials = len(all_trials)
    report = HistoricalSimReport(
        trials=all_trials[-500:],
        agents=agents,
        leaderboard=leaderboard[:20],
        universe=universe,
        bar_walk_trials=bar_count,
        snapshot_trials=snap_count,
        expert_summary=summary,
    )
    payload = to_dict(report, total_trials=total_trials)
    payload["meta"]["lookback_days"] = lookback_days
    payload["meta"]["signal_step_bars"] = signal_step_bars
    payload["meta"]["horizons"] = list(horizons)
    if write_output:
        out_path = output or SIM_FILE
        _write_json(out_path, payload)
    return payload


def to_dict(report: HistoricalSimReport, *, total_trials: int | None = None) -> dict[str, Any]:
    trial_total = total_trials if total_trials is not None else len(report.trials)
    return {
        "meta": {
            "agent": "Historical Simulation Engine",
            "analyzed_at": report.analyzed_at,
            "data_source": "Yahoo daily bars + archived pipeline snapshots",
            "expert_summary": report.expert_summary,
            "lookback_days": DEFAULT_LOOKBACK_DAYS,
            "universe_size": len(report.universe),
        },
        "metrics": {
            "total_trials": trial_total,
            "bar_walk_trials": report.bar_walk_trials,
            "snapshot_trials": report.snapshot_trials,
            "agents_simulated": len(report.agents),
            "leaderboard_size": len(report.leaderboard),
        },
        "universe": report.universe,
        "agents": report.agents,
        "leaderboard": report.leaderboard,
        "recent_trials": [
            {
                "agent_id": t.agent_id,
                "symbol": t.symbol,
                "horizon": t.horizon,
                "predicted_direction": t.predicted_direction,
                "actual_direction": t.actual_direction,
                "actual_return_pct": t.actual_return_pct,
                "hit": t.hit,
                "confidence": t.confidence,
                "source": t.source,
                "simulated_at": t.simulated_at,
            }
            for t in report.trials[-40:]
        ],
        "market_signals": [
            {
                "sector": "Historical Simulation",
                "tickers": ["SPY"],
                "bias": "BULLISH" if report.leaderboard else "NEUTRAL",
                "reason": report.expert_summary[:200],
            }
        ],
        "recommendations": [
            report.expert_summary,
            f"Bar walk-forward trials: {report.bar_walk_trials}",
            f"Snapshot replay trials: {report.snapshot_trials}",
        ]
        + [
            f"{row['agent_id']}: {row['accuracy_pct']}% ({row['total_trials']} trials)"
            for row in report.leaderboard[:8]
        ],
    }


def get_agent_historical_accuracy(agent_id: str) -> dict[str, Any] | None:
    data = _load_json(SIM_FILE)
    if not isinstance(data, dict):
        return None
    entry = (data.get("agents") or {}).get(agent_id)
    return entry if isinstance(entry, dict) else None


def historical_weight_multiplier(agent_id: str, *, horizon: str = "24h") -> float | None:
    entry = get_agent_historical_accuracy(agent_id)
    if not entry:
        return None
    total = int(entry.get("total_trials") or 0)
    if total < MIN_SIM_SAMPLES:
        return None
    by_horizon = entry.get("by_horizon") or {}
    hb = by_horizon.get(horizon) if isinstance(by_horizon, dict) else None
    if isinstance(hb, dict) and int(hb.get("total", 0)) >= 4:
        acc = float(hb.get("accuracy_pct") or 50.0)
        return max(0.5, min(1.5, 0.5 + acc / 100.0))
    acc = entry.get("accuracy_pct")
    if acc is None:
        return None
    return float(entry.get("weight_multiplier") or max(0.5, min(1.5, 0.5 + float(acc) / 100.0)))


def run_historical_simulation_cli(output: Path | None = None) -> dict[str, Any]:
    return run_historical_simulation(quick=False, output=output or SIM_FILE)


def _subsample_trials(trials: list[SimTrial], target: int) -> list[SimTrial]:
    if len(trials) <= target:
        return trials
    by_agent: dict[str, list[SimTrial]] = {}
    for trial in trials:
        by_agent.setdefault(trial.agent_id, []).append(trial)
    agent_ids = sorted(by_agent)
    if not agent_ids:
        return trials[:target]
    per_agent = max(1, target // len(agent_ids))
    sampled: list[SimTrial] = []
    for agent_id in agent_ids:
        rows = by_agent[agent_id]
        stride = max(1, len(rows) // per_agent)
        sampled.extend(rows[::stride][:per_agent])
    if len(sampled) > target:
        stride = max(1, len(sampled) // target)
        sampled = sampled[::stride][:target]
    elif len(sampled) < target:
        remaining = [t for t in trials if t not in sampled]
        sampled.extend(remaining[: target - len(sampled)])
    return sampled[:target]


def run_accuracy_benchmark(
    *,
    target_trials: int = DEFAULT_BENCHMARK_TRIALS,
    max_symbols: int = 40,
    full: bool = True,
    output: Path | None = None,
) -> dict[str, Any]:
    """Run a sized walk-forward backtest for agent accuracy benchmarking."""
    from agents.platform_catalog import active_agent_sources

    target = max(100, int(target_trials))
    agent_count = sum(
        1
        for src in active_agent_sources(check_remote=False)
        if src["id"] not in SKIP_AGENTS
    )
    lookback_days = 504 if full else DEFAULT_LOOKBACK_DAYS
    max_symbols = max(20, int(max_symbols))
    horizons: tuple[str, ...] = ("24h", "1wk", "1mo", "1yr") if full else ("24h", "1wk", "1mo")

    estimated = _estimate_walk_forward_trials(
        agent_count=agent_count,
        symbol_count=max_symbols,
        lookback_days=lookback_days,
        signal_step_bars=SIGNAL_STEP_BARS,
        horizons=horizons,
    )
    first_step = SIGNAL_STEP_BARS
    if estimated > target * 1.15:
        first_step = max(1, int(round(SIGNAL_STEP_BARS * (estimated / target))))

    step_candidates = list(dict.fromkeys([first_step, 5, 3, 2, 1]))
    report: dict[str, Any] = {}
    signal_step = first_step
    total = 0

    def _run_pass(
        *,
        step: int,
        days: int,
        symbols: int,
        cap: int | None,
    ) -> dict[str, Any]:
        return run_historical_simulation(
            lookback_days=days,
            max_symbols=symbols,
            quick=not full,
            horizons=horizons,
            signal_step_bars=step,
            trial_cap=cap,
            include_snapshots=full,
            write_output=False,
        )

    for step in step_candidates:
        signal_step = step
        report = _run_pass(step=signal_step, days=lookback_days, symbols=max_symbols, cap=None)
        total = int((report.get("metrics") or {}).get("total_trials") or 0)
        if total >= target:
            if total > target:
                report = _run_pass(
                    step=signal_step,
                    days=lookback_days,
                    symbols=max_symbols,
                    cap=target,
                )
                total = target
            break

    if total < target:
        lookback_days = min(1260, lookback_days + 252)
        boosted_symbols = min(max(max_symbols, 64), max_symbols + 16)
        report = _run_pass(step=1, days=lookback_days, symbols=boosted_symbols, cap=None)
        max_symbols = boosted_symbols
        signal_step = 1
        total = int((report.get("metrics") or {}).get("total_trials") or 0)
        if total > target:
            report = _run_pass(step=1, days=lookback_days, symbols=max_symbols, cap=target)
            total = target
    board = report.get("leaderboard") or []
    if board:
        top = board[0]
        summary = (
            f"Accuracy benchmark: {total}/{target} walk-forward trials across "
            f"{report.get('meta', {}).get('universe_size', 0)} symbols "
            f"({report.get('metrics', {}).get('bar_walk_trials', 0)} bar, "
            f"{report.get('metrics', {}).get('snapshot_trials', 0)} snapshot). "
            f"Top agent {top['agent_id']} at {top['accuracy_pct']}% "
            f"({top['total_trials']} trials)."
        )
    else:
        summary = (
            f"Accuracy benchmark: {total}/{target} trials recorded; "
            f"need {MIN_SIM_SAMPLES}+ trials per agent for ranked accuracy."
        )

    report.setdefault("meta", {})["benchmark"] = {
        "target_trials": target,
        "max_symbols": max_symbols,
        "full_mode": full,
        "signal_step_bars": signal_step,
        "lookback_days": lookback_days,
        "horizons": list(horizons),
    }
    report["meta"]["expert_summary"] = summary
    report["meta"]["agent"] = "Agent Accuracy Benchmark"

    out_path = output or BENCHMARK_FILE
    _write_json(out_path, report)
    _write_json(SIM_FILE, report)

    try:
        from agent_fusion import export_walk_forward_weights

        export_walk_forward_weights()
    except Exception:
        pass

    return report


def run_accuracy_benchmark_cli(
    output: Path | None = None,
    *,
    target_trials: int = DEFAULT_BENCHMARK_TRIALS,
    max_symbols: int = 40,
    full: bool = True,
) -> dict[str, Any]:
    return run_accuracy_benchmark(
        target_trials=target_trials,
        max_symbols=max_symbols,
        full=full,
        output=output or BENCHMARK_FILE,
    )