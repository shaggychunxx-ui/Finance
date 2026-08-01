"""Tests for live pending drain, abstain gate, and trading preferred-horizon fusion."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_prediction_abstain_marks_non_actionable() -> None:
    from agents.market_predictor import _apply_prediction_abstain

    preds = {
        "24h": [
            {
                "symbol": "AAA",
                "predicted_direction": "up",
                "confidence": 0.7,
                "composite_score": 0.3,
                "rank": 1,
            },
            {
                "symbol": "BBB",
                "predicted_direction": "up",
                "confidence": 0.4,
                "composite_score": 0.3,
                "rank": 2,
            },
        ]
    }
    pack = _apply_prediction_abstain(preds, min_confidence=0.52, min_abs_score=0.08)
    assert pack["abstain_stats"]["actionable"] == 1
    assert pack["actionable_predictions"]["24h"][0]["symbol"] == "AAA"
    assert preds["24h"][1]["predicted_direction"] == "flat"
    assert preds["24h"][1]["actionable"] is False


def test_cap_pending_by_horizon() -> None:
    from prediction_accuracy import _cap_pending_by_horizon, MAX_PENDING_BY_HORIZON

    rows = []
    for i in range(500):
        rows.append(
            {
                "agent_id": "markets",
                "symbol": f"S{i}",
                "horizon": "1mo",
                "predicted_direction": "up",
                "recorded_at": f"2026-08-01T{i%20:02d}:00:00+00:00",
            }
        )
    for i in range(50):
        rows.append(
            {
                "agent_id": "markets",
                "symbol": f"D{i}",
                "horizon": "24h",
                "predicted_direction": "up",
                "recorded_at": f"2026-08-01T{i%20:02d}:30:00+00:00",
            }
        )
    capped = _cap_pending_by_horizon(rows)
    n_1mo = sum(1 for r in capped if r.get("horizon") == "1mo")
    n_24 = sum(1 for r in capped if r.get("horizon") == "24h")
    assert n_1mo <= MAX_PENDING_BY_HORIZON["1mo"]
    assert n_24 == 50


def test_trading_fusion_prefers_horizon(monkeypatch) -> None:
    import agent_fusion as af
    import prediction_accuracy as pa

    entry = {
        "total_scored": 40,
        "live_scored": 40,
        "accuracy_source": "live_scored",
        "combined_accuracy_pct": 50.0,
        "fusion_accuracy_pct": 50.0,
        "weight_multiplier": 1.0,
        "preferred_horizon": "1wk",
        "prefer_preferred_horizon_for_fusion": True,
        "by_horizon": {
            "1wk": {"total": 30, "hits": 18, "accuracy_pct": 60.0},
            "24h": {"total": 30, "hits": 9, "accuracy_pct": 30.0},
        },
    }

    monkeypatch.setattr(pa, "get_agent_accuracy", lambda aid: entry)
    monkeypatch.setattr(af, "agent_in_domain", lambda *a, **k: True)
    monkeypatch.setattr(af, "calibration_factor", lambda aid: 1.0)
    monkeypatch.setattr(af, "current_regime", lambda: {"posture": "neutral"})
    monkeypatch.setattr(af, "is_event_day", lambda: False)

    # Off-horizon trading vote should be discounted vs preferred-horizon vote
    w_pref = af.fusion_weight("markets", horizon="1wk", for_trading=True)
    w_off = af.fusion_weight("markets", horizon="24h", for_trading=True)
    assert w_pref > w_off
