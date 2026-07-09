"""Horizon-aligned accuracy views, regime buckets, and separate leaderboards."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app_paths import ROOT

DIRECTION_WEIGHT = 0.6
MAGNITUDE_WEIGHT = 0.4
MIN_SAMPLES_FOR_MAGNITUDE = 8

DEFAULT_ACCURACY_MEASUREMENT = {
    "enabled": True,
    "min_preferred_horizon_samples": 8,
    "min_regime_bucket_samples": 3,
    "prefer_preferred_horizon_for_label": True,
    "prefer_preferred_horizon_for_fusion": True,
    "separate_direction_leaderboard": True,
}


def load_accuracy_measurement_settings(config_path: Path | None = None) -> dict[str, Any]:
    settings = dict(DEFAULT_ACCURACY_MEASUREMENT)
    path = config_path or (ROOT / "etrade_config.json")
    if not path.exists():
        return settings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        strategy = raw.get("strategy", {})
        if isinstance(strategy, dict):
            nested = strategy.get("accuracy_measurement", {})
            if isinstance(nested, dict):
                settings.update({k: nested[k] for k in settings if k in nested})
        top = raw.get("accuracy_measurement", {})
        if isinstance(top, dict):
            settings.update({k: top[k] for k in settings if k in top})
    except (json.JSONDecodeError, OSError):
        pass
    return settings


def normalize_posture(posture: str) -> str:
    p = str(posture or "neutral").strip().lower().replace("_", "-")
    if p in {"risk-on", "risk-off", "neutral"}:
        return p
    if p in {"cautious", "learning", "calibrated"}:
        return "neutral"
    if p == "confident":
        return "risk-on"
    return "neutral"


def regime_bucket(posture: str, *, event_day: bool = False) -> str:
    """Composite regime tag: posture + event/normal day."""
    return f"{normalize_posture(posture)}:{'event' if event_day else 'normal'}"


def preferred_horizon_for_agent(agent_id: str) -> str:
    try:
        from agent_constraints import agent_preferred_horizon

        return agent_preferred_horizon(agent_id)
    except Exception:
        return "24h"


def _horizon_slice(by_horizon: dict[str, Any] | None, horizon: str) -> dict[str, Any] | None:
    if not isinstance(by_horizon, dict):
        return None
    row = by_horizon.get(horizon)
    return row if isinstance(row, dict) else None


def _combined_from_slice(
    *,
    weighted_pct: float | None,
    magnitude_pct: float | None,
    magnitude_total: int,
) -> float | None:
    if weighted_pct is None:
        return None
    if magnitude_total >= MIN_SAMPLES_FOR_MAGNITUDE and magnitude_pct is not None:
        return round(DIRECTION_WEIGHT * weighted_pct + MAGNITUDE_WEIGHT * magnitude_pct, 1)
    return weighted_pct


def horizon_accuracy_metrics(
    entry: dict[str, Any],
    horizon: str,
) -> dict[str, Any] | None:
    """Direction + combined metrics for one horizon slice."""
    hb = _horizon_slice(entry.get("by_horizon"), horizon)
    if not hb or int(hb.get("total") or 0) <= 0:
        return None
    total = int(hb.get("total") or 0)
    hits = int(hb.get("hits") or 0)
    direction_pct = float(hb["accuracy_pct"]) if hb.get("accuracy_pct") is not None else round(hits / total * 100, 1)
    mag_total = int(hb.get("magnitude_total") or 0)
    mag_hits = int(hb.get("magnitude_hits") or 0)
    magnitude_pct = (
        float(hb["magnitude_accuracy_pct"])
        if hb.get("magnitude_accuracy_pct") is not None
        else (round(mag_hits / mag_total * 100, 1) if mag_total else None)
    )
    combined = _combined_from_slice(
        weighted_pct=direction_pct,
        magnitude_pct=magnitude_pct,
        magnitude_total=mag_total,
    )
    return {
        "horizon": horizon,
        "total": total,
        "hits": hits,
        "direction_accuracy_pct": direction_pct,
        "magnitude_accuracy_pct": magnitude_pct,
        "magnitude_scored": mag_total,
        "combined_accuracy_pct": combined,
    }


def effective_accuracy_metrics(
    entry: dict[str, Any] | None,
    agent_id: str,
    *,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve primary accuracy numbers — prefer agent's natural horizon when sampled."""
    gate = settings or load_accuracy_measurement_settings()
    if not isinstance(entry, dict):
        return {
            "preferred_horizon": preferred_horizon_for_agent(agent_id),
            "measurement_kind": "none",
            "measurement_primary_pct": None,
        }

    preferred = str(entry.get("preferred_horizon") or preferred_horizon_for_agent(agent_id))
    min_pref = int(gate.get("min_preferred_horizon_samples", DEFAULT_ACCURACY_MEASUREMENT["min_preferred_horizon_samples"]))
    prefer_label = bool(gate.get("prefer_preferred_horizon_for_label", True))
    prefer_fusion = bool(gate.get("prefer_preferred_horizon_for_fusion", True))

    direction_pct = entry.get("accuracy_pct")
    if direction_pct is None and int(entry.get("total_scored") or 0):
        total = int(entry.get("total_scored") or 0)
        hits = int(entry.get("hits") or 0)
        direction_pct = round(hits / total * 100, 1) if total else None

    weighted_pct = entry.get("weighted_accuracy_pct") or direction_pct
    combined_pct = entry.get("combined_accuracy_pct") or weighted_pct
    pref_slice = horizon_accuracy_metrics(entry, preferred)

    use_preferred = (
        pref_slice is not None
        and int(pref_slice.get("total") or 0) >= min_pref
        and (prefer_label or prefer_fusion)
    )

    if use_preferred and pref_slice:
        primary_pct = pref_slice.get("combined_accuracy_pct") or pref_slice.get("direction_accuracy_pct")
        measurement_kind = "preferred_horizon"
        direction_out = pref_slice.get("direction_accuracy_pct")
        combined_out = pref_slice.get("combined_accuracy_pct")
        magnitude_out = pref_slice.get("magnitude_accuracy_pct")
        preferred_samples = int(pref_slice.get("total") or 0)
    else:
        primary_pct = combined_pct
        measurement_kind = "combined"
        direction_out = direction_pct
        combined_out = combined_pct
        magnitude_out = entry.get("magnitude_accuracy_pct")
        preferred_samples = int((pref_slice or {}).get("total") or 0)

    return {
        "preferred_horizon": preferred,
        "preferred_horizon_samples": preferred_samples,
        "preferred_horizon_accuracy_pct": (pref_slice or {}).get("direction_accuracy_pct"),
        "preferred_horizon_combined_pct": (pref_slice or {}).get("combined_accuracy_pct"),
        "direction_accuracy_pct": direction_out,
        "weighted_accuracy_pct": weighted_pct,
        "combined_accuracy_pct": combined_out,
        "magnitude_accuracy_pct": magnitude_out,
        "measurement_kind": measurement_kind,
        "measurement_primary_pct": primary_pct,
        "prefer_preferred_horizon_for_fusion": prefer_fusion and use_preferred,
    }


def enrich_agent_accuracy_entry(
    entry: dict[str, Any],
    agent_id: str,
    *,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach measurement metadata used by labels, fusion, and leaderboards."""
    row = dict(entry)
    metrics = effective_accuracy_metrics(row, agent_id, settings=settings)
    row["preferred_horizon"] = metrics.get("preferred_horizon")
    row["preferred_horizon_samples"] = metrics.get("preferred_horizon_samples")
    row["preferred_horizon_accuracy_pct"] = metrics.get("preferred_horizon_accuracy_pct")
    row["preferred_horizon_combined_pct"] = metrics.get("preferred_horizon_combined_pct")
    row["direction_accuracy_pct"] = metrics.get("direction_accuracy_pct")
    row["measurement_kind"] = metrics.get("measurement_kind")
    row["measurement_primary_pct"] = metrics.get("measurement_primary_pct")
    row["prefer_preferred_horizon_for_fusion"] = metrics.get("prefer_preferred_horizon_for_fusion")

    if metrics.get("prefer_preferred_horizon_for_fusion") and metrics.get("measurement_primary_pct") is not None:
        pct = float(metrics["measurement_primary_pct"])
        row["fusion_accuracy_pct"] = pct
        row["weight_multiplier"] = round(max(0.5, min(1.5, 0.5 + pct / 100.0)), 3)
    else:
        row["fusion_accuracy_pct"] = (
            row.get("combined_accuracy_pct")
            or row.get("weighted_accuracy_pct")
            or row.get("accuracy_pct")
        )
    return row


def _leaderboard_row(row: dict[str, Any], *, metric_key: str) -> dict[str, Any] | None:
    metric = row.get(metric_key) or row.get("measurement_primary_pct") or row.get("combined_accuracy_pct")
    if metric is None:
        return None
    total = int(row.get("total_scored") or row.get("total") or 0)
    if total <= 0:
        return None
    return {
        "agent_id": row.get("agent_id"),
        "total_scored": total,
        "accuracy_pct": metric,
        "direction_accuracy_pct": row.get("direction_accuracy_pct"),
        "combined_accuracy_pct": row.get("combined_accuracy_pct"),
        "preferred_horizon": row.get("preferred_horizon"),
        "preferred_horizon_combined_pct": row.get("preferred_horizon_combined_pct"),
        "measurement_kind": row.get("measurement_kind"),
        "accuracy_source": row.get("accuracy_source"),
        "live_weight": row.get("live_weight"),
    }


def build_accuracy_leaderboards(
    agents: dict[str, dict[str, Any]],
    *,
    top_n: int = 25,
    min_samples: int = 8,
) -> dict[str, list[dict[str, Any]]]:
    """Separate leaderboards for combined, direction-only, and preferred-horizon views."""
    combined_rows: list[dict[str, Any]] = []
    direction_rows: list[dict[str, Any]] = []
    preferred_rows: list[dict[str, Any]] = []

    for aid, raw in agents.items():
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        row.setdefault("agent_id", aid)
        total = int(row.get("total_scored") or row.get("total") or 0)
        if total < min_samples:
            continue

        combined = _leaderboard_row(row, metric_key="combined_accuracy_pct")
        if combined:
            combined_rows.append(combined)

        direction = _leaderboard_row(row, metric_key="direction_accuracy_pct")
        if direction:
            direction_rows.append(direction)

        pref = _leaderboard_row(row, metric_key="preferred_horizon_combined_pct")
        if pref and int(row.get("preferred_horizon_samples") or 0) >= min_samples:
            preferred_rows.append(pref)

    def _sort(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows.sort(
            key=lambda item: (
                float(item.get("live_weight") or 0.0),
                float(item.get("accuracy_pct") or 0.0),
                int(item.get("total_scored") or 0),
            ),
            reverse=True,
        )
        return rows[:top_n]

    return {
        "combined": _sort(combined_rows),
        "direction": _sort(direction_rows),
        "preferred_horizon": _sort(preferred_rows),
    }


def format_accuracy_label(
    entry: dict[str, Any] | None,
    *,
    pending: int = 0,
    min_samples: int = 25,
) -> str:
    """Human-readable accuracy label with horizon context when available."""
    if not entry:
        if pending:
            return f"{pending} tracking"
        return "—"

    total = int(entry.get("total_scored") or entry.get("total") or 0)
    if total < min_samples:
        if pending:
            return f"{pending} tracking"
        if total:
            return f"{total} scored"
        return "—"

    kind = str(entry.get("measurement_kind") or "combined")
    primary = entry.get("measurement_primary_pct") or entry.get("combined_accuracy_pct")
    direction = entry.get("direction_accuracy_pct")
    preferred = entry.get("preferred_horizon")
    if primary is None:
        return "—"

    parts = [f"{float(primary):.0f}%"]
    if kind == "preferred_horizon" and preferred:
        parts.append(f"@{preferred}")
    if direction is not None and abs(float(direction) - float(primary)) >= 1.5:
        parts.append(f"dir {float(direction):.0f}%")
    mag = entry.get("magnitude_accuracy_pct")
    mag_n = int(entry.get("magnitude_scored") or 0)
    if mag is not None and mag_n >= MIN_SAMPLES_FOR_MAGNITUDE:
        parts.append(f"mag {float(mag):.0f}%")
    return " · ".join(parts)