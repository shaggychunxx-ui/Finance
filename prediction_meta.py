#!/usr/bin/env python3
"""Meta-calibration of prediction confidence from walk-forward + live trials.

Learns a simple P(hit | confidence, horizon, abs_score, regime, event) model
from the trial journal and live scored rows, then:
  - recalibrates confidence
  - suggests adaptive abstain thresholds
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app_paths import OUTPUT

HISTORY = OUTPUT / "history"
META_FILE = HISTORY / "prediction_meta.json"
MIN_BUCKET = 12


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _conf_bucket(conf: float) -> str:
    if conf < 0.45:
        return "c_low"
    if conf < 0.55:
        return "c_mid"
    if conf < 0.70:
        return "c_high"
    return "c_vhigh"


def _score_bucket(score: float) -> str:
    a = abs(float(score or 0))
    if a < 0.08:
        return "s_weak"
    if a < 0.20:
        return "s_mod"
    return "s_strong"


def _collect_labeled_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    acc = _load_json(HISTORY / "prediction_accuracy.json") or {}
    for row in acc.get("scored") or []:
        if isinstance(row, dict) and row.get("predicted_direction") not in (None, "flat"):
            rows.append(row)
    try:
        from backtest_trial_store import load_recent_trials

        for row in load_recent_trials(max_rows=15_000):
            if isinstance(row, dict) and row.get("predicted_direction") not in (None, "flat"):
                rows.append(row)
    except Exception:
        pass
    return rows


def rebuild_prediction_meta() -> dict[str, Any]:
    """Fit bucket hit-rates and write adaptive abstain suggestion."""
    labeled = _collect_labeled_rows()
    buckets: dict[str, dict[str, float]] = defaultdict(lambda: {"n": 0.0, "hits": 0.0})
    by_horizon: dict[str, dict[str, float]] = defaultdict(lambda: {"n": 0.0, "hits": 0.0})

    for row in labeled:
        conf = float(row.get("confidence") or 0.5)
        # composite_score may be absent on scored rows — use |predicted_return| proxy
        score = row.get("composite_score")
        if score is None:
            try:
                score = abs(float(row.get("predicted_return_pct") or 0)) / 10.0
            except (TypeError, ValueError):
                score = 0.1
        h = str(row.get("horizon") or "24h")
        hit = 1.0 if row.get("hit") else 0.0
        key = f"{h}|{_conf_bucket(conf)}|{_score_bucket(float(score))}"
        buckets[key]["n"] += 1
        buckets[key]["hits"] += hit
        by_horizon[h]["n"] += 1
        by_horizon[h]["hits"] += hit

    rates: dict[str, dict[str, Any]] = {}
    for key, b in buckets.items():
        n = int(b["n"])
        if n < MIN_BUCKET:
            continue
        rates[key] = {
            "n": n,
            "hit_rate": round(b["hits"] / b["n"], 4),
        }

    horizon_rates = {
        h: {
            "n": int(b["n"]),
            "hit_rate": round(b["hits"] / b["n"], 4) if b["n"] else None,
        }
        for h, b in by_horizon.items()
        if b["n"] >= MIN_BUCKET
    }

    # Adaptive abstain: raise min confidence until bucket hit_rate >= target
    target = 0.48
    suggested_min_conf = 0.52
    # Find lowest conf bucket that still clears target on 24h if available
    candidates = []
    for key, info in rates.items():
        if not key.startswith("24h|") and not key.startswith("1wk|"):
            continue
        if info["hit_rate"] >= target:
            if "c_mid" in key:
                candidates.append(0.50)
            elif "c_high" in key:
                candidates.append(0.55)
            elif "c_vhigh" in key:
                candidates.append(0.65)
            elif "c_low" in key:
                candidates.append(0.45)
    if candidates:
        suggested_min_conf = max(0.48, min(0.70, sum(candidates) / len(candidates)))

    # If overall is very high, relax slightly; if very low, tighten
    overall_n = sum(int(v["n"]) for v in rates.values())
    overall_hits = sum(float(v["hit_rate"]) * v["n"] for v in rates.values())
    overall = (overall_hits / overall_n) if overall_n else None
    if overall is not None:
        if overall < 0.30:
            suggested_min_conf = min(0.70, suggested_min_conf + 0.05)
        elif overall > 0.45:
            suggested_min_conf = max(0.48, suggested_min_conf - 0.03)

    payload = {
        "updated_at": _now_iso(),
        "labeled_rows": len(labeled),
        "bucket_rates": rates,
        "horizon_rates": horizon_rates,
        "overall_hit_rate": round(overall, 4) if overall is not None else None,
        "suggested_abstain": {
            "min_confidence": round(suggested_min_conf, 3),
            "min_abs_score": 0.08,
            "target_hit_rate": target,
        },
        "description": "Bucketed empirical P(hit) for confidence calibration and abstain tuning.",
    }
    _write_json(META_FILE, payload)
    # Optionally write suggestion into a sidecar for market_predictor thresholds
    try:
        sidec = HISTORY / "adaptive_abstain.json"
        _write_json(
            sidec,
            {
                "updated_at": _now_iso(),
                "min_confidence": payload["suggested_abstain"]["min_confidence"],
                "min_abs_score": payload["suggested_abstain"]["min_abs_score"],
                "source": "prediction_meta",
            },
        )
    except Exception:
        pass
    return payload


def calibrate_confidence(
    confidence: float,
    *,
    horizon: str = "24h",
    composite_score: float = 0.0,
    default: float | None = None,
) -> float:
    """Map raw confidence to empirical hit-rate when bucket has enough data."""
    meta = _load_json(META_FILE) or {}
    rates = meta.get("bucket_rates") if isinstance(meta, dict) else {}
    if not isinstance(rates, dict) or not rates:
        return float(default if default is not None else confidence)
    key = f"{horizon}|{_conf_bucket(float(confidence))}|{_score_bucket(composite_score)}"
    row = rates.get(key)
    if not isinstance(row, dict) or int(row.get("n") or 0) < MIN_BUCKET:
        # fallback: same conf bucket any score
        for k, v in rates.items():
            if k.startswith(f"{horizon}|{_conf_bucket(float(confidence))}|") and int(v.get("n") or 0) >= MIN_BUCKET:
                row = v
                break
    if not isinstance(row, dict):
        return float(default if default is not None else confidence)
    # Blend raw conf with empirical hit rate
    emp = float(row.get("hit_rate") or 0.5)
    raw = float(confidence)
    return max(0.05, min(0.95, 0.45 * raw + 0.55 * emp))


def load_adaptive_abstain() -> tuple[float, float]:
    data = _load_json(HISTORY / "adaptive_abstain.json") or {}
    try:
        return float(data.get("min_confidence") or 0.52), float(data.get("min_abs_score") or 0.08)
    except (TypeError, ValueError):
        return 0.52, 0.08
