"""Shared signal-quality helpers — statistical thresholds, decay, and confidence."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app_paths import OUTPUT


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def bias_from_edge(
    edge: float,
    *,
    bullish_threshold: float = 0.55,
    bearish_threshold: float = 0.45,
) -> str:
    if edge >= bullish_threshold:
        return "BULLISH"
    if edge <= bearish_threshold:
        return "BEARISH"
    return "NEUTRAL"


def confidence_from_edge(
    edge: float,
    *,
    samples: int = 0,
    min_samples: int = 20,
    neutral: float = 0.5,
) -> float:
    """Map probability edge + sample depth to signal confidence."""
    sample_factor = _clamp(samples / max(min_samples, 1), 0.35, 1.0)
    edge_strength = _clamp(abs(edge - neutral) * 2.0, 0.0, 1.0)
    return round(_clamp(0.42 + edge_strength * 0.45 * sample_factor, 0.35, 0.92), 3)


def wilson_edge_valid(
    prob: float,
    *,
    ci_low: float,
    ci_high: float,
    samples: int,
    min_samples: int = 30,
    min_edge: float = 0.05,
) -> bool:
    """True when Wilson interval clears 50% with enough samples."""
    if samples < min_samples:
        return False
    if prob >= 0.5 + min_edge:
        return ci_low > 0.5
    if prob <= 0.5 - min_edge:
        return ci_high < 0.5
    return False


def event_recency_weight(
    timestamp: str | None,
    *,
    half_life_hours: float = 48.0,
) -> float:
    """Exponential decay for dated headlines/events (1.0 = fresh)."""
    if not timestamp:
        return 0.55
    try:
        when = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        age_hours = max(0.0, (datetime.now(timezone.utc) - when).total_seconds() / 3600.0)
    except ValueError:
        return 0.55
    if half_life_hours <= 0:
        return 1.0
    return round(math.exp(-0.693147 * age_hours / half_life_hours), 3)


def weighted_event_score(events: list[dict[str, Any]], *, impact_weights: dict[str, float] | None = None) -> float:
    weights = impact_weights or {
        "critical": 1.0,
        "high": 0.72,
        "medium": 0.4,
        "low": 0.2,
    }
    total = 0.0
    for event in events:
        impact = str(event.get("impact") or "medium").lower()
        base = weights.get(impact, 0.3)
        recency = event_recency_weight(
            str(event.get("date") or event.get("pub_date") or event.get("recorded_at") or ""),
        )
        total += base * recency
    return round(total, 3)


def build_market_signal(
    *,
    sector: str,
    tickers: list[str],
    bias: str,
    reason: str,
    confidence: float | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "sector": sector,
        "tickers": [str(t).upper() for t in tickers if t],
        "bias": str(bias or "NEUTRAL").upper(),
        "reason": reason,
    }
    if confidence is not None:
        row["confidence"] = round(_clamp(confidence, 0.05, 0.99), 3)
    if evidence:
        row["evidence"] = evidence
    return row


def load_peer_agent_output(filename: str) -> dict[str, Any] | None:
    path = OUTPUT / filename
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def meteorology_energy_score() -> float | None:
    """Read prior-cycle meteorology stress for energy-grid alignment."""
    data = load_peer_agent_output("meteorology.json")
    if not data:
        return None
    metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
    for key in ("energy_demand_score", "weather_energy_score", "energy_stress_score", "energy_score"):
        if metrics.get(key) is not None:
            try:
                return float(metrics[key])
            except (TypeError, ValueError):
                continue
    assessment = data.get("assessment") if isinstance(data.get("assessment"), dict) else {}
    text = " ".join(str(v) for v in assessment.values()).lower()
    if "elevated" in text or "high demand" in text:
        return 0.72
    if "moderate" in text:
        return 0.55
    return 0.4


def retail_signal_confidence(
    *,
    momentum: float,
    return_20d_pct: float | None,
    breadth_pct: float,
    consumer_strength: float,
) -> float:
    momentum_factor = _clamp((momentum - 0.45) / 0.35, 0.0, 1.0)
    return_factor = _clamp((float(return_20d_pct or 0.0)) / 8.0, 0.0, 1.0) if return_20d_pct else 0.35
    breadth_factor = _clamp(breadth_pct / 100.0, 0.0, 1.0)
    strength_factor = _clamp((consumer_strength - 0.4) / 0.35, 0.0, 1.0)
    return round(
        _clamp(0.38 + 0.22 * momentum_factor + 0.18 * return_factor + 0.12 * breadth_factor + 0.1 * strength_factor),
        3,
    )


def breadth_risk_signal_confidence(
    breadth: float | None,
    risk_on: float,
    *,
    momentum: float | None = None,
) -> float:
    """Tape breadth + risk posture for macro market agents."""
    breadth_factor = _clamp(abs(float(breadth or 0.0)) / 0.8, 0.0, 1.0)
    risk_factor = _clamp(abs(risk_on - 0.5) * 2.0, 0.0, 1.0)
    mom_factor = _clamp((float(momentum or 0.5) - 0.45) / 0.35, 0.0, 1.0) if momentum is not None else 0.4
    return round(_clamp(0.38 + 0.28 * breadth_factor + 0.22 * risk_factor + 0.12 * mom_factor), 3)


def quant_signal_confidence(
    *,
    momentum: float,
    mc_prob_up: float | None = None,
    z_score: float | None = None,
    stress: float | None = None,
) -> float:
    """Monte Carlo / z-score confidence for quant cluster agents."""
    mom_factor = _clamp((momentum - 0.45) / 0.35, 0.0, 1.0)
    mc_factor = _clamp((float(mc_prob_up or 0.5) - 0.48) / 0.12, 0.0, 1.0) if mc_prob_up is not None else 0.35
    z_factor = _clamp(abs(float(z_score or 0.0)) / 2.0, 0.0, 1.0) if z_score is not None else 0.3
    stress_factor = _clamp(float(stress or 0.0) / 0.6, 0.0, 1.0) if stress is not None else 0.25
    return round(
        _clamp(0.36 + 0.24 * mom_factor + 0.2 * mc_factor + 0.12 * z_factor + 0.08 * stress_factor),
        3,
    )


def sector_rotation_confidence(
    day_chg_pct: float | None,
    *,
    week_chg_pct: float | None = None,
    risk_reward: float | None = None,
) -> float:
    """Sector rotation move strength from live quote deltas."""
    day_factor = _clamp(abs(float(day_chg_pct or 0.0)) / 1.5, 0.0, 1.0)
    week_factor = _clamp(abs(float(week_chg_pct or 0.0)) / 3.0, 0.0, 1.0) if week_chg_pct is not None else 0.35
    rr_factor = _clamp((float(risk_reward or 0.5) - 0.45) / 0.25, 0.0, 1.0) if risk_reward is not None else 0.35
    return round(_clamp(0.4 + 0.32 * day_factor + 0.16 * week_factor + 0.12 * rr_factor), 3)


def grid_power_confidence(
    *,
    renewable_pct: float | None = None,
    gas_pct: float | None = None,
    lmp: float | None = None,
    grid_stress: float | None = None,
) -> float:
    """ISO fuel mix / wholesale price signal strength."""
    ren_factor = _clamp((float(renewable_pct or 0.0) - 25.0) / 25.0, 0.0, 1.0) if renewable_pct is not None else 0.35
    gas_factor = _clamp((float(gas_pct or 0.0) - 30.0) / 25.0, 0.0, 1.0) if gas_pct is not None else 0.3
    lmp_factor = _clamp(abs(float(lmp or 35.0) - 35.0) / 25.0, 0.0, 1.0) if lmp is not None else 0.35
    stress_factor = _clamp(float(grid_stress or 0.0) / 70.0, 0.0, 1.0) if grid_stress is not None else 0.25
    return round(
        _clamp(0.38 + 0.22 * ren_factor + 0.18 * gas_factor + 0.14 * lmp_factor + 0.08 * stress_factor),
        3,
    )


def freight_logistics_confidence(
    freight: float,
    *,
    congestion: float | None = None,
    stress: float | None = None,
    lane_density: float | None = None,
) -> float:
    """Shipping corridor / freight momentum confidence."""
    freight_factor = _clamp((freight - 0.4) / 0.35, 0.0, 1.0)
    cong_factor = _clamp(abs(float(congestion or 0.0) - 0.5) * 2.0, 0.0, 1.0) if congestion is not None else 0.3
    stress_factor = _clamp(float(stress or 0.0) / 0.65, 0.0, 1.0) if stress is not None else 0.25
    density_factor = _clamp((float(lane_density or 0.0) - 0.5) / 0.3, 0.0, 1.0) if lane_density is not None else 0.3
    return round(
        _clamp(0.38 + 0.28 * freight_factor + 0.16 * cong_factor + 0.1 * stress_factor + 0.08 * density_factor),
        3,
    )


def hypothesis_test_confidence(
    *,
    p_value: float,
    significant: bool,
    statistic: float | None = None,
    alpha: float = 0.05,
) -> float:
    """Statistical inference — low confidence unless test clears alpha."""
    if not significant or p_value >= alpha:
        return round(_clamp(0.38 + (alpha - min(p_value, alpha)) / alpha * 0.12, 0.35, 0.5), 3)
    sig_strength = _clamp((alpha - p_value) / alpha, 0.0, 1.0)
    stat_strength = _clamp(abs(float(statistic or 0.0)) / 2.5, 0.0, 1.0) if statistic is not None else 0.4
    return round(_clamp(0.52 + 0.28 * sig_strength + 0.12 * stat_strength, 0.45, 0.9), 3)


def cross_section_confidence(
    statistical_score: float,
    *,
    breadth_pct: float | None = None,
    z_score: float | None = None,
) -> float:
    """Cross-sectional breadth / z-score confidence for statistical agents."""
    score_factor = _clamp(abs(statistical_score - 0.5) * 2.0, 0.0, 1.0)
    breadth_factor = _clamp(abs(float(breadth_pct or 50.0) - 50.0) / 30.0, 0.0, 1.0) if breadth_pct is not None else 0.35
    z_factor = _clamp(abs(float(z_score or 0.0)) / 2.0, 0.0, 1.0) if z_score is not None else 0.3
    return round(_clamp(0.4 + 0.3 * score_factor + 0.18 * breadth_factor + 0.12 * z_factor), 3)


def conditional_prob_confidence(
    prob: float,
    *,
    sample_size: int = 0,
    min_samples: int = 60,
) -> float:
    """Empirical conditional probability confidence."""
    return confidence_from_edge(prob, samples=sample_size, min_samples=min_samples)