"""Stabilized agent temperature — posture and accuracy drive run variance."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from app_paths import ROOT

DEFAULT_TEMPERATURE_CONTROL = {
    "enabled": True,
    "stabilize_in_pipeline": True,
    "pipeline_min": 2,
    "pipeline_max": 4,
    "exploratory_min": 1,
    "exploratory_max": 8,
    "posture_ranges": {
        "cautious": [2, 3],
        "learning": [2, 4],
        "calibrated": [3, 4],
        "confident": [3, 5],
    },
    "max_below_45_pct": 3,
    "max_below_40_pct": 2,
    "force_low_below_38_pct": 2,
    "exploratory_mode": False,
}

POSTURE_FALLBACK_RANGE = [2, 4]


def load_temperature_settings(config_path: Path | None = None) -> dict[str, Any]:
    settings = dict(DEFAULT_TEMPERATURE_CONTROL)
    path = config_path or (ROOT / "etrade_config.json")
    if not path.exists():
        return settings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        strategy = raw.get("strategy", {})
        if isinstance(strategy, dict):
            nested = strategy.get("temperature_control", {})
            if isinstance(nested, dict):
                settings.update({k: nested[k] for k in settings if k in nested})
        top = raw.get("temperature_control", {})
        if isinstance(top, dict):
            settings.update({k: top[k] for k in settings if k in top})
    except (json.JSONDecodeError, OSError):
        pass
    return settings


def _normalize_agent_id(agent_id: str) -> str:
    return str(agent_id or "").replace("_", "-")


def _pipeline_session_active() -> bool:
    try:
        from agents.pipeline_memory import get_active_pipeline_context

        return bool(get_active_pipeline_context())
    except Exception:
        return False


def _agent_context(agent_id: str, pipeline_context: dict[str, Any] | None = None) -> dict[str, Any]:
    ctx = dict(pipeline_context or {})
    aid = _normalize_agent_id(agent_id)
    if not ctx and aid:
        try:
            from agents.pipeline_memory import memory_bundle_for_agent

            ctx = memory_bundle_for_agent(aid)
        except Exception:
            ctx = {}

    posture = str(ctx.get("posture") or "")
    accuracy = ctx.get("accuracy_pct")
    if not posture or accuracy is None:
        try:
            from agent_learning import get_agent_learning

            learning = get_agent_learning(aid)
            if learning is not None:
                posture = posture or learning.posture
                if accuracy is None and learning.accuracy_pct is not None:
                    accuracy = learning.accuracy_pct
        except Exception:
            pass
    if accuracy is None:
        try:
            from prediction_accuracy import get_agent_accuracy

            entry = get_agent_accuracy(aid)
            if isinstance(entry, dict):
                accuracy = (
                    entry.get("combined_accuracy_pct")
                    or entry.get("weighted_accuracy_pct")
                    or entry.get("accuracy_pct")
                )
        except Exception:
            pass

    return {
        "posture": posture or "learning",
        "accuracy_pct": float(accuracy) if accuracy is not None else None,
    }


def _range_bounds(raw: Any, *, fallback: list[int]) -> tuple[int, int]:
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        lo = int(raw[0])
        hi = int(raw[1])
        return min(lo, hi), max(lo, hi)
    return fallback[0], fallback[1]


def resolve_agent_temperature(
    agent_id: str,
    *,
    pipeline_context: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pick a stabilized temperature for this agent run."""
    gate = settings or load_temperature_settings()
    if not gate.get("enabled", True):
        temp = random.randint(
            int(gate.get("exploratory_min", 1)),
            int(gate.get("exploratory_max", 8)),
        )
        return {
            "temperature": temp,
            "mode": "legacy_random",
            "posture": None,
            "accuracy_pct": None,
            "range": [temp, temp],
        }

    ctx = _agent_context(agent_id, pipeline_context)
    posture = str(ctx.get("posture") or "learning")
    accuracy = ctx.get("accuracy_pct")

    exploratory = bool(gate.get("exploratory_mode", False))
    stabilize = bool(gate.get("stabilize_in_pipeline", True)) and _pipeline_session_active()
    if exploratory or not stabilize:
        lo = int(gate.get("exploratory_min", 1))
        hi = int(gate.get("exploratory_max", 8))
        mode = "exploratory"
    else:
        pipeline_lo = int(gate.get("pipeline_min", 2))
        pipeline_hi = int(gate.get("pipeline_max", 4))
        posture_ranges = gate.get("posture_ranges") or {}
        lo, hi = _range_bounds(posture_ranges.get(posture), fallback=POSTURE_FALLBACK_RANGE)
        lo = max(lo, pipeline_lo)
        hi = min(hi, pipeline_hi)
        mode = "pipeline_stabilized"

    if accuracy is not None:
        acc = float(accuracy)
        if acc < 38.0:
            cap = int(gate.get("force_low_below_38_pct", 2))
            hi = min(hi, cap)
            lo = min(lo, cap)
        elif acc < 40.0:
            hi = min(hi, int(gate.get("max_below_40_pct", 2)))
        elif acc < 45.0:
            hi = min(hi, int(gate.get("max_below_45_pct", 3)))
        if lo > hi:
            lo = hi

    temperature = random.randint(lo, hi)
    return {
        "temperature": temperature,
        "mode": mode,
        "posture": posture,
        "accuracy_pct": accuracy,
        "range": [lo, hi],
    }


def apply_temperature_to_result(
    data: dict[str, Any],
    agent_id: str,
    *,
    pipeline_context: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stamp stabilized temperature into agent output meta."""
    if not isinstance(data, dict):
        return data

    gate = settings or load_temperature_settings()
    if not gate.get("enabled", True):
        return data

    resolved = resolve_agent_temperature(
        agent_id,
        pipeline_context=pipeline_context,
        settings=gate,
    )
    meta = data.setdefault("meta", {})
    if not isinstance(meta, dict):
        meta = {}
        data["meta"] = meta

    meta["temperature"] = int(resolved["temperature"])
    meta["temperature_control"] = {
        "mode": resolved.get("mode"),
        "posture": resolved.get("posture"),
        "accuracy_pct": resolved.get("accuracy_pct"),
        "range": resolved.get("range"),
    }
    return data