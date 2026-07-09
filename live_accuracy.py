"""Live vs benchmark accuracy blending — fusion weights follow current markets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app_paths import ROOT

LIVE_ACCURACY_SOURCE = "live_scored"
BLENDED_ACCURACY_SOURCE = "live_benchmark_blend"

DEFAULT_LIVE_ACCURACY = {
    "enabled": True,
    "min_live_samples_full": 25,
    "min_live_samples_blend": 8,
    "prefer_live_for_fusion": True,
    "accuracy_interval_minutes": 15,
}


def load_live_accuracy_settings(config_path: Path | None = None) -> dict[str, Any]:
    settings = dict(DEFAULT_LIVE_ACCURACY)
    path = config_path or (ROOT / "etrade_config.json")
    if not path.exists():
        return settings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        worker = raw.get("background_worker", {})
        if isinstance(worker, dict):
            nested = worker.get("live_accuracy", {})
            if isinstance(nested, dict):
                settings.update({k: nested[k] for k in settings if k in nested})
        strategy = raw.get("strategy", {})
        if isinstance(strategy, dict):
            nested = strategy.get("live_accuracy", {})
            if isinstance(nested, dict):
                settings.update({k: nested[k] for k in settings if k in nested})
        top = raw.get("live_accuracy", {})
        if isinstance(top, dict):
            settings.update({k: top[k] for k in settings if k in top})
    except (json.JSONDecodeError, OSError):
        pass
    return settings


def _pct(entry: dict[str, Any] | None, key: str = "combined_accuracy_pct") -> float | None:
    if not isinstance(entry, dict):
        return None
    value = entry.get(key) or entry.get("weighted_accuracy_pct") or entry.get("accuracy_pct")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _weight_multiplier(accuracy_pct: float | None) -> float:
    if accuracy_pct is None:
        return 1.0
    return round(max(0.5, min(1.5, 0.5 + accuracy_pct / 100.0)), 3)


def merge_live_and_benchmark(
    live_entry: dict[str, Any] | None,
    benchmark_entry: dict[str, Any] | None,
    *,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build the effective accuracy row used by fusion and trading gates."""
    from prediction_accuracy import BENCHMARK_SOURCE, MIN_SAMPLES_BENCHMARK, MIN_SAMPLES_FOR_WEIGHT

    gate = settings or load_live_accuracy_settings()
    if not gate.get("enabled", True):
        if live_entry:
            row = dict(live_entry)
            row.setdefault("accuracy_source", LIVE_ACCURACY_SOURCE)
            return row
        if benchmark_entry:
            row = dict(benchmark_entry)
            row.setdefault("accuracy_source", BENCHMARK_SOURCE)
            return row
        return None

    min_full = int(gate.get("min_live_samples_full", DEFAULT_LIVE_ACCURACY["min_live_samples_full"]))
    min_blend = int(gate.get("min_live_samples_blend", DEFAULT_LIVE_ACCURACY["min_live_samples_blend"]))

    live_total = int((live_entry or {}).get("total_scored") or (live_entry or {}).get("total") or 0)
    bench_total = int(
        (benchmark_entry or {}).get("total_scored") or (benchmark_entry or {}).get("total") or 0
    )

    if live_total < min_blend:
        if benchmark_entry and bench_total >= MIN_SAMPLES_BENCHMARK:
            row = dict(benchmark_entry)
            row["accuracy_source"] = BENCHMARK_SOURCE
            row["live_scored"] = live_total
            row["benchmark_scored"] = bench_total
            row["live_weight"] = 0.0
            return row
        if live_entry and live_total > 0:
            row = dict(live_entry)
            row["accuracy_source"] = LIVE_ACCURACY_SOURCE
            row["live_scored"] = live_total
            row["live_weight"] = 1.0
            return row
        return dict(benchmark_entry) if benchmark_entry else None

    if live_total >= min_full or not benchmark_entry or bench_total < MIN_SAMPLES_BENCHMARK:
        row = dict(live_entry or {})
        row["accuracy_source"] = LIVE_ACCURACY_SOURCE
        row["live_scored"] = live_total
        row["benchmark_scored"] = bench_total
        row["live_weight"] = 1.0
        if benchmark_entry:
            row["benchmark_reference_pct"] = _pct(benchmark_entry)
        if live_total >= MIN_SAMPLES_FOR_WEIGHT:
            combined = _pct(row)
            if combined is not None:
                row["weight_multiplier"] = _weight_multiplier(combined)
        return row

    live_weight = min(1.0, live_total / float(min_full))
    live_pct = _pct(live_entry)
    bench_pct = _pct(benchmark_entry)
    if live_pct is None and bench_pct is None:
        return dict(live_entry or benchmark_entry)

    blended_pct = None
    if live_pct is not None and bench_pct is not None:
        blended_pct = round(live_weight * live_pct + (1.0 - live_weight) * bench_pct, 1)
    elif live_pct is not None:
        blended_pct = live_pct
    else:
        blended_pct = bench_pct

    row = dict(live_entry or {})
    row.update(
        {
            "combined_accuracy_pct": blended_pct,
            "weighted_accuracy_pct": blended_pct,
            "accuracy_pct": blended_pct,
            "accuracy_source": BLENDED_ACCURACY_SOURCE,
            "live_scored": live_total,
            "benchmark_scored": bench_total,
            "live_weight": round(live_weight, 3),
            "live_accuracy_pct": live_pct,
            "benchmark_accuracy_pct": bench_pct,
            "weight_multiplier": _weight_multiplier(blended_pct),
            "benchmark_reference_pct": bench_pct,
        }
    )
    return row


def _benchmark_agents_from_store(accuracy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    stored = accuracy.get("benchmark_agents")
    if isinstance(stored, dict) and stored:
        return {aid: dict(row) for aid, row in stored.items() if isinstance(row, dict)}

    legacy: dict[str, dict[str, Any]] = {}
    from prediction_accuracy import BENCHMARK_SOURCE

    for aid, row in (accuracy.get("agents") or {}).items():
        if isinstance(row, dict) and row.get("accuracy_source") == BENCHMARK_SOURCE:
            legacy[aid] = dict(row)
    return legacy


def refresh_merged_agent_accuracy(
    accuracy: dict[str, Any],
    *,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge live_agents + benchmark_agents into agents used by fusion."""
    gate = settings or load_live_accuracy_settings()
    live_agents = {
        aid: dict(row)
        for aid, row in (accuracy.get("live_agents") or {}).items()
        if isinstance(row, dict)
    }
    benchmark_agents = _benchmark_agents_from_store(accuracy)

    merged: dict[str, Any] = {}
    for aid in sorted(set(live_agents) | set(benchmark_agents)):
        row = merge_live_and_benchmark(live_agents.get(aid), benchmark_agents.get(aid), settings=gate)
        if row:
            merged[aid] = row

    leaderboard: list[dict[str, Any]] = []
    from prediction_accuracy import MIN_SAMPLES_BENCHMARK, MIN_SAMPLES_FOR_WEIGHT

    min_blend = min_blend_threshold(gate)
    for row in merged.values():
        combined = row.get("combined_accuracy_pct")
        if combined is None:
            continue
        source = str(row.get("accuracy_source") or "")
        live_scored = int(row.get("live_scored") or 0)
        total = int(row.get("total_scored") or row.get("total") or 0)
        if source == LIVE_ACCURACY_SOURCE and live_scored >= MIN_SAMPLES_FOR_WEIGHT:
            leaderboard.append(row)
        elif source == BLENDED_ACCURACY_SOURCE and live_scored >= min_blend:
            leaderboard.append(row)
        elif source == BENCHMARK_SOURCE and total >= MIN_SAMPLES_BENCHMARK:
            leaderboard.append(row)

    leaderboard.sort(
        key=lambda row: (
            float(row.get("live_weight") or 0.0),
            row.get("combined_accuracy_pct") or 0,
            row.get("total_scored") or 0,
        ),
        reverse=True,
    )

    try:
        from accuracy_measurement import (
            build_accuracy_leaderboards,
            enrich_agent_accuracy_entry,
            load_accuracy_measurement_settings,
        )
        from prediction_accuracy import MIN_SAMPLES_BENCHMARK, MIN_SAMPLES_FOR_WEIGHT

        measure_settings = load_accuracy_measurement_settings()
        enriched: dict[str, Any] = {}
        for aid, row in merged.items():
            if isinstance(row, dict):
                enriched[aid] = enrich_agent_accuracy_entry(row, aid, settings=measure_settings)
        merged = enriched
        min_board = min(MIN_SAMPLES_BENCHMARK, MIN_SAMPLES_FOR_WEIGHT)
        boards = build_accuracy_leaderboards(merged, top_n=25, min_samples=min_board)
        accuracy["leaderboard"] = boards.get("combined") or leaderboard[:25]
        accuracy["leaderboard_direction"] = boards.get("direction") or []
        accuracy["leaderboard_preferred_horizon"] = boards.get("preferred_horizon") or []
    except Exception:
        accuracy["leaderboard"] = leaderboard[:25]

    accuracy["agents"] = merged
    accuracy["live_accuracy"] = {
        "enabled": gate.get("enabled", True),
        "live_agent_count": len(live_agents),
        "benchmark_agent_count": len(benchmark_agents),
        "merged_agent_count": len(merged),
        "live_primary_agents": sum(
            1 for row in merged.values() if row.get("accuracy_source") == LIVE_ACCURACY_SOURCE
        ),
        "blended_agents": sum(
            1 for row in merged.values() if row.get("accuracy_source") == BLENDED_ACCURACY_SOURCE
        ),
        "benchmark_primary_agents": sum(
            1
            for row in merged.values()
            if row.get("accuracy_source") == "walk_forward_benchmark"
        ),
    }
    return accuracy


def min_blend_threshold(settings: dict[str, Any] | None = None) -> int:
    gate = settings or load_live_accuracy_settings()
    return int(gate.get("min_live_samples_blend", DEFAULT_LIVE_ACCURACY["min_live_samples_blend"]))


def live_scoring_summary(accuracy: dict[str, Any] | None = None) -> dict[str, Any]:
    if accuracy is None:
        from prediction_accuracy import _accuracy_store

        accuracy = _accuracy_store()
    pending = int(accuracy.get("pending_count") or 0)
    scored = len(accuracy.get("scored") or [])
    meta = accuracy.get("live_accuracy") if isinstance(accuracy.get("live_accuracy"), dict) else {}
    return {
        "pending": pending,
        "scored_total": scored,
        "live_primary_agents": int(meta.get("live_primary_agents") or 0),
        "blended_agents": int(meta.get("blended_agents") or 0),
        "benchmark_primary_agents": int(meta.get("benchmark_primary_agents") or 0),
    }