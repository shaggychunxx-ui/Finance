"""Single market-regime enum for the whole pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app_paths import OUTPUT

ENUM_PATH = OUTPUT / "market_regime_enum.json"

_LABEL_TO_ID = {
    "Low-Vol Trending": "low_vol_trending",
    "High-Vol Trending": "high_vol_trending",
    "Low-Vol Mean-Reverting": "low_vol_mean_reverting",
    "High-Vol Mean-Reverting": "high_vol_mean_reverting",
}

_PLAYBOOK = {
    "low_vol_trending": "momentum_ok",
    "high_vol_trending": "trend_wide_stops",
    "low_vol_mean_reverting": "fade_range",
    "high_vol_mean_reverting": "no_breakouts_cut_size",
    "unclassified": "conservative",
}


def parse_regime(metrics: dict[str, Any] | None, *, label: str = "") -> dict[str, Any]:
    metrics = metrics if isinstance(metrics, dict) else {}
    raw_label = str(label or metrics.get("regime_label") or "").strip()
    rid = _LABEL_TO_ID.get(raw_label, "unclassified")
    vol = "high" if "High-Vol" in raw_label or str(metrics.get("volatility_state") or "").startswith("High") else (
        "low" if "Low-Vol" in raw_label or str(metrics.get("volatility_state") or "").startswith("Low") else "unknown"
    )
    trend = "trending" if "Trending" in raw_label or metrics.get("trending_state") == "Trending" else (
        "mean_reverting" if "Mean-Reverting" in raw_label or metrics.get("trending_state") == "Mean-Reverting" else "unknown"
    )
    size = 0.5 if rid == "high_vol_mean_reverting" else 0.7 if rid == "high_vol_trending" else 1.0
    allow_breakouts = rid in {"low_vol_trending", "high_vol_trending"}
    return {
        "id": rid,
        "label": raw_label or rid,
        "vol": vol,
        "trend": trend,
        "playbook": _PLAYBOOK.get(rid, "conservative"),
        "allow_breakouts": allow_breakouts,
        "size_multiplier": size,
    }


def save_regime(result: dict[str, Any]) -> dict[str, Any]:
    metrics = result.get("metrics") if isinstance(result, dict) else {}
    enum = parse_regime(metrics if isinstance(metrics, dict) else {})
    ENUM_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENUM_PATH.write_text(json.dumps(enum, indent=2), encoding="utf-8")
    if isinstance(result, dict):
        result["regime"] = enum
        meta = result.setdefault("meta", {})
        if isinstance(meta, dict):
            meta["regime"] = enum
    return enum


def load_regime() -> dict[str, Any]:
    if ENUM_PATH.is_file():
        try:
            data = json.loads(ENUM_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("id"):
                return data
        except Exception:
            pass
    # Fallback: last market_regime.json
    raw = OUTPUT / "market_regime.json"
    if raw.is_file():
        try:
            payload = json.loads(raw.read_text(encoding="utf-8"))
            return parse_regime(payload.get("metrics") if isinstance(payload, dict) else {})
        except Exception:
            pass
    return parse_regime({}, label="")
