"""Per-group scoring systems — function-specific grades for each agent group."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_every_group_has_scoring_system() -> None:
    from agent_groups import AGENT_GROUPS, group_scoring_for

    assert len(AGENT_GROUPS) >= 10
    for gid, meta in AGENT_GROUPS.items():
        scoring = meta.get("scoring")
        assert isinstance(scoring, dict), f"{gid} missing scoring"
        assert scoring.get("mode"), f"{gid} missing mode"
        assert scoring.get("primary_metric"), f"{gid} missing primary_metric"
        assert scoring.get("summary"), f"{gid} missing summary"
        metrics = scoring.get("metrics") or []
        assert len(metrics) >= 2, f"{gid} needs multiple KPI metrics"
        weight_sum = sum(float(m.get("weight") or 0) for m in metrics)
        assert abs(weight_sum - 1.0) < 0.02, f"{gid} metric weights sum to {weight_sum}"
        # API returns enriched copy
        api = group_scoring_for(gid)
        assert api["group_id"] == gid
        assert api["mode"] == scoring["mode"]
        assert api["directional"] == bool(meta.get("directional", True))


def test_scoring_modes_match_group_function() -> None:
    from agent_groups import agent_scoring_mode, agent_scoring_system

    # Function → mode expectations
    expected = {
        "markets": "directional_alpha",
        "datascience": "calibration",
        "fred": "regime_timing",
        "events": "risk_overlay",
        "electricity": "domain_specialist",
        "transportation": "domain_specialist",
        "sales-analytics": "domain_specialist",
        "day-trading-microstructure": "intraday",
        "bear-thesis": "short_alpha",
        "risk-protection": "risk_gate",
        "fundamental-analyst": "multi_horizon",
        "portfolio-frameworks": "allocation",
        "data-steward": "platform_quality",
        "order-execution": "execution_quality",
        "market-predictor": "ensemble",
    }
    for aid, mode in expected.items():
        assert agent_scoring_mode(aid) == mode, f"{aid} expected {mode}"
        system = agent_scoring_system(aid)
        assert system["agent_id"] == aid
        assert system.get("metrics")


def test_non_directional_groups_zero_direction_weight() -> None:
    from agent_groups import group_accuracy_weights, uses_directional_scoring

    # Platform + execution: pure quality KPIs, no price-direction weight
    for aid in ("data-steward", "order-execution"):
        assert uses_directional_scoring(aid) is False
        dw, mw = group_accuracy_weights(aid)
        assert dw == 0.0, aid
        assert mw == 1.0, aid

    # Fusion skips live directional agent accuracy, but still grades blend consensus
    assert uses_directional_scoring("market-predictor") is False
    dw, mw = group_accuracy_weights("market-predictor")
    assert dw > 0.0 and mw > 0.0


def test_composite_group_score_renormalizes() -> None:
    from agent_groups import composite_group_score

    # Only supply one of three markets_core metrics → still produces a score
    result = composite_group_score(
        "markets",
        {"direction_hit": 80.0},
    )
    assert result["score"] == 80.0
    assert result["coverage"] < 1.0
    assert result["mode"] == "directional_alpha"

    full = composite_group_score(
        "markets",
        {
            "direction_hit": 80.0,
            "magnitude_capture": 60.0,
            "liquid_coverage": 100.0,
        },
    )
    assert full["score"] is not None
    assert 0 <= full["score"] <= 100
    assert full["coverage"] == 1.0
    # 0.55*80 + 0.25*60 + 0.20*100 = 44 + 15 + 20 = 79
    assert abs(full["score"] - 79.0) < 0.5


def test_all_scoring_systems_export() -> None:
    from agent_groups import AGENT_GROUPS, all_scoring_systems

    rows = all_scoring_systems()
    assert len(rows) == len(AGENT_GROUPS)
    modes = {r["mode"] for r in rows}
    # Distinct function-based modes present
    assert "directional_alpha" in modes
    assert "calibration" in modes
    assert "platform_quality" in modes
    assert "risk_gate" in modes


def test_report_meta_stamps_scoring() -> None:
    from agent_groups import apply_group_conduct_to_report

    data = apply_group_conduct_to_report({"market_signals": []}, "risk-protection")
    meta = data["meta"]
    assert meta["scoring_mode"] == "risk_gate"
    assert meta["primary_metric"] == "capital_protection"
    assert meta["score_horizon"] == "24h"


def test_accuracy_measurement_uses_group_weights() -> None:
    from accuracy_measurement import _group_blend_weights, enrich_agent_accuracy_entry

    # Risk gate favors magnitude/protection over pure direction
    dw, mw = _group_blend_weights("risk-protection")
    assert mw > dw

    # Day trading favors direction
    dwd, mwd = _group_blend_weights("day-trading-microstructure")
    assert dwd > mwd

    entry = enrich_agent_accuracy_entry(
        {
            "agent_id": "datascience",
            "accuracy_pct": 55.0,
            "combined_accuracy_pct": 55.0,
            "total_scored": 10,
            "hits": 5,
        },
        "datascience",
    )
    assert entry.get("scoring_mode") == "calibration"
    assert entry.get("primary_metric") == "probability_calibration"
