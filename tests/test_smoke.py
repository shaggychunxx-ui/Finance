"""Lightweight smoke tests — no network, no full pipeline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_app_paths_consistent() -> None:
    from app_paths import OUTPUT, ROOT as APP_ROOT
    from analysis_history import HISTORY_ROOT, OUTPUT as HIST_OUTPUT

    assert HIST_OUTPUT == OUTPUT
    assert HISTORY_ROOT == OUTPUT / "history"
    assert APP_ROOT.exists()


def test_new_pipeline_cycle_id_format() -> None:
    from analysis_history import new_pipeline_cycle_id

    cycle_id = new_pipeline_cycle_id()
    assert len(cycle_id) == 16
    assert cycle_id.endswith("Z")
    assert "T" in cycle_id


def test_record_pipeline_run_upsert() -> None:
    from analysis_history import PIPELINE_RUNS_FILE, record_pipeline_run

    backup = PIPELINE_RUNS_FILE.read_text(encoding="utf-8") if PIPELINE_RUNS_FILE.exists() else None
    try:
        cycle_id = "test00000000T000000Z"
        first = record_pipeline_run(cycle_id, agents_ok=3, agents_total=5)
        second = record_pipeline_run(cycle_id, agents_ok=4, agents_total=5)
        assert first["cycle_id"] == cycle_id
        assert second["agents_ok"] == 4
        store = json.loads(PIPELINE_RUNS_FILE.read_text(encoding="utf-8"))
        matches = [row for row in store["runs"] if row.get("cycle_id") == cycle_id]
        assert len(matches) == 1
    finally:
        if backup is None:
            PIPELINE_RUNS_FILE.unlink(missing_ok=True)
        else:
            PIPELINE_RUNS_FILE.write_text(backup, encoding="utf-8")


def test_prediction_hit_logic() -> None:
    from prediction_accuracy import _prediction_hit

    assert _prediction_hit("up", "up") is True
    assert _prediction_hit("up", "down") is False
    assert _prediction_hit("flat", "flat") is True


def test_import_core_modules() -> None:
    import agent_learning  # noqa: F401
    import analysis_history  # noqa: F401
    import prediction_accuracy  # noqa: F401
    import strategy_engine  # noqa: F401


def test_agent_signal_logic_thresholds() -> None:
    from agent_signal_logic import (
        breadth_risk_signal_confidence,
        conditional_prob_confidence,
        cross_section_confidence,
        event_recency_weight,
        freight_logistics_confidence,
        grid_power_confidence,
        hypothesis_test_confidence,
        quant_signal_confidence,
        retail_signal_confidence,
        sector_rotation_confidence,
        weighted_event_score,
        wilson_edge_valid,
    )

    assert wilson_edge_valid(0.58, ci_low=0.52, ci_high=0.64, samples=50) is True
    assert wilson_edge_valid(0.58, ci_low=0.48, ci_high=0.64, samples=50) is False
    assert event_recency_weight("2020-01-01T00:00:00+00:00") < 0.2
    assert weighted_event_score(
        [{"impact": "critical", "date": "2099-01-01T00:00:00+00:00"}]
    ) > 0.9
    conf = retail_signal_confidence(
        momentum=0.65,
        return_20d_pct=3.5,
        breadth_pct=62.0,
        consumer_strength=0.64,
    )
    assert conf >= 0.55
    assert breadth_risk_signal_confidence(0.45, 0.72) > retail_signal_confidence(
        momentum=0.5,
        return_20d_pct=None,
        breadth_pct=50.0,
        consumer_strength=0.5,
    )
    assert quant_signal_confidence(momentum=0.7, mc_prob_up=0.58, z_score=-1.5) >= 0.55
    assert sector_rotation_confidence(1.2, week_chg_pct=2.5, risk_reward=0.65) >= 0.6
    assert grid_power_confidence(renewable_pct=42.0, gas_pct=48.0, lmp=62.0) >= 0.55
    assert freight_logistics_confidence(0.72, congestion=0.68, stress=0.55) >= 0.58
    assert hypothesis_test_confidence(p_value=0.01, significant=True, statistic=2.4) >= 0.7
    assert hypothesis_test_confidence(p_value=0.12, significant=False) <= 0.5
    assert cross_section_confidence(0.62, breadth_pct=68.0, z_score=1.8) >= 0.58
    assert conditional_prob_confidence(0.72, sample_size=252) >= 0.55


def test_live_accuracy_merge_prefers_live_samples() -> None:
    from live_accuracy import (
        BLENDED_ACCURACY_SOURCE,
        LIVE_ACCURACY_SOURCE,
        merge_live_and_benchmark,
        refresh_merged_agent_accuracy,
    )
    from prediction_accuracy import BENCHMARK_SOURCE

    settings = {
        "enabled": True,
        "min_live_samples_full": 25,
        "min_live_samples_blend": 8,
    }
    bench = {
        "agent_id": "markets",
        "total_scored": 300,
        "combined_accuracy_pct": 41.0,
        "accuracy_source": BENCHMARK_SOURCE,
    }
    live = {
        "agent_id": "markets",
        "total_scored": 30,
        "combined_accuracy_pct": 48.0,
        "weight_multiplier": 0.98,
    }

    full_live = merge_live_and_benchmark(live, bench, settings=settings)
    assert full_live is not None
    assert full_live["accuracy_source"] == LIVE_ACCURACY_SOURCE
    assert full_live["combined_accuracy_pct"] == 48.0

    partial_live = merge_live_and_benchmark(
        {**live, "total_scored": 12, "combined_accuracy_pct": 50.0},
        bench,
        settings=settings,
    )
    assert partial_live is not None
    assert partial_live["accuracy_source"] == BLENDED_ACCURACY_SOURCE
    assert partial_live["live_weight"] > 0.0
    assert partial_live["live_weight"] < 1.0

    store = refresh_merged_agent_accuracy(
        {
            "live_agents": {"markets": live},
            "benchmark_agents": {"markets": bench},
            "scored": [],
        },
        settings=settings,
    )
    assert store["agents"]["markets"]["accuracy_source"] == LIVE_ACCURACY_SOURCE
    assert store["live_accuracy"]["live_primary_agents"] == 1


def test_temperature_stabilized_by_posture_and_accuracy() -> None:
    from agent_temperature import apply_temperature_to_result, resolve_agent_temperature
    from agents.pipeline_memory import activate_pipeline_memory, clear_pipeline_memory

    settings = {
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
    activate_pipeline_memory({"agent_learning": {}})
    try:
        cautious = resolve_agent_temperature(
            "markets",
            pipeline_context={"posture": "cautious", "accuracy_pct": 36.0},
            settings=settings,
        )
        assert cautious["temperature"] == 2
        assert cautious["mode"] == "pipeline_stabilized"

        confident = resolve_agent_temperature(
            "markets",
            pipeline_context={"posture": "confident", "accuracy_pct": 52.0},
            settings=settings,
        )
        assert 3 <= confident["temperature"] <= 4

        stamped = apply_temperature_to_result({"meta": {}}, "markets", settings=settings)
        assert 2 <= stamped["meta"]["temperature"] <= 4
        assert stamped["meta"]["temperature_control"]["mode"] == "pipeline_stabilized"
    finally:
        clear_pipeline_memory()


def test_agent_domain_and_horizon_constraints() -> None:
    from agent_constraints import (
        apply_agent_constraints_to_result,
        agent_preferred_horizon,
        domain_allows_symbol,
        horizon_match_multiplier,
        load_domain_constraint_settings,
    )

    settings = load_domain_constraint_settings()
    assert domain_allows_symbol("sales-analytics", "WMT", settings=settings) is True
    assert domain_allows_symbol("sales-analytics", "UNG", settings=settings) is False
    assert horizon_match_multiplier("sales-analytics", "1wk") >= horizon_match_multiplier(
        "sales-analytics", "1yr"
    )

    steered = apply_agent_constraints_to_result(
        {
            "meta": {},
            "market_signals": [
                {
                    "sector": "retail",
                    "bias": "BULLISH",
                    "tickers": ["WMT", "UNG"],
                }
            ],
        },
        "sales-analytics",
        settings=settings,
    )
    assert steered["market_signals"][0]["tickers"] == ["WMT"]
    assert "domain_constraints" in steered["meta"]
    assert steered["meta"]["domain_constraints"]["removed_out_of_domain_signals"] >= 1

    assert agent_preferred_horizon("markets") in {"24h", "1wk", "1mo", "1yr"}


def test_proactive_enhancement_candidates() -> None:
    import json
    import tempfile
    from pathlib import Path

    from agents.enhancement import collect_proactive_enhancement_candidates, collect_enhancement_candidates

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        (out / "market_predictions.json").write_text(
            json.dumps(
                {
                    "predictions": {
                        "24h": [
                            {"rank": 1, "symbol": "NVDA", "confidence": 0.9},
                            {"rank": 2, "symbol": "SPY", "confidence": 0.8},
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        (out / "portfolio.json").write_text(
            json.dumps({"holdings": [{"symbol": "UNG", "confidence": 0.95, "rationale": "Agent pick"}]}),
            encoding="utf-8",
        )
        proactive = collect_proactive_enhancement_candidates(out)
        symbols = {row["symbol"] for row in proactive}
        assert "NVDA" in symbols
        assert "UNG" in symbols
        assert proactive[0]["priority"] >= proactive[-1]["priority"]

        full = collect_enhancement_candidates(out, include_proactive=True)
        full_symbols = {row["symbol"] for row in full}
        assert "NVDA" in full_symbols
        assert "UNG" in full_symbols


def test_accuracy_measurement_horizon_and_regime() -> None:
    from accuracy_measurement import (
        build_accuracy_leaderboards,
        effective_accuracy_metrics,
        enrich_agent_accuracy_entry,
        format_accuracy_label,
        regime_bucket,
    )

    assert regime_bucket("risk-on", event_day=True) == "risk-on:event"
    assert regime_bucket("cautious", event_day=False) == "neutral:normal"

    entry = {
        "agent_id": "sales-analytics",
        "preferred_horizon": "1wk",
        "total_scored": 30,
        "hits": 14,
        "accuracy_pct": 46.7,
        "weighted_accuracy_pct": 48.0,
        "combined_accuracy_pct": 47.5,
        "by_horizon": {
            "1wk": {
                "total": 12,
                "hits": 7,
                "accuracy_pct": 58.3,
                "magnitude_total": 0,
                "magnitude_hits": 0,
            },
            "24h": {"total": 18, "hits": 7, "accuracy_pct": 38.9, "magnitude_total": 0, "magnitude_hits": 0},
        },
        "by_regime_bucket": {
            "risk-on:normal": {"total": 5, "hits": 3, "accuracy_pct": 60.0},
        },
    }
    metrics = effective_accuracy_metrics(entry, "sales-analytics")
    assert metrics["measurement_kind"] == "preferred_horizon"
    assert metrics["preferred_horizon"] == "1wk"
    assert float(metrics["measurement_primary_pct"]) >= 58.0

    enriched = enrich_agent_accuracy_entry(entry, "sales-analytics")
    assert enriched["prefer_preferred_horizon_for_fusion"] is True
    label = format_accuracy_label(enriched, min_samples=8)
    assert "@" in label or "%" in label

    boards = build_accuracy_leaderboards(
        {"sales-analytics": enriched, "markets": {"agent_id": "markets", "total_scored": 3, "combined_accuracy_pct": 40.0}},
        min_samples=8,
    )
    assert len(boards["combined"]) == 1
    assert boards["combined"][0]["agent_id"] == "sales-analytics"


def test_validate_agent_output_freshness() -> None:
    from datetime import datetime, timedelta, timezone

    from app_paths import OUTPUT
    from strategy_engine import validate_agent_output

    started = datetime(2026, 7, 9, 16, 0, 0, tzinfo=timezone.utc)
    fresh = {
        "meta": {"analyzed_at": (started + timedelta(seconds=30)).isoformat()},
        "market_signals": [],
    }
    stale = {
        "meta": {"analyzed_at": (started - timedelta(hours=1)).isoformat()},
        "market_signals": [],
    }
    path = OUTPUT / "_smoke_agent_output.json"
    try:
        path.write_text(json.dumps(fresh), encoding="utf-8")
        assert validate_agent_output(path, started_at=started) is None

        path.write_text(json.dumps(stale), encoding="utf-8")
        assert validate_agent_output(path, started_at=started) is not None

        predictor_fresh = {
            "meta": {"generated_at": (started + timedelta(seconds=30)).isoformat()},
            "predictions": {},
        }
        path.write_text(json.dumps(predictor_fresh), encoding="utf-8")
        assert validate_agent_output(path, started_at=started) is None

        path.write_text("{not json", encoding="utf-8")
        assert validate_agent_output(path, started_at=started) is not None
    finally:
        path.unlink(missing_ok=True)


def test_record_pipeline_agent_errors_roundtrip() -> None:
    from analysis_history import PIPELINE_ERRORS_FILE, record_pipeline_agent_errors

    backup = PIPELINE_ERRORS_FILE.read_text(encoding="utf-8") if PIPELINE_ERRORS_FILE.exists() else None
    cycle_id = "test00000000T000001Z"
    try:
        entry = record_pipeline_agent_errors(
            cycle_id,
            failures=[{"agent_id": "order-execution", "label": "Order Execution", "error": "boom"}],
            degraded=[{"agent_id": "markets", "label": "Markets", "error": "fallback"}],
            predictor_failure={"agent_id": "market-predictor", "error": "fuse failed"},
        )
        assert entry["cycle_id"] == cycle_id
        assert len(entry["failures"]) == 1
        store = json.loads(PIPELINE_ERRORS_FILE.read_text(encoding="utf-8"))
        saved = next(row for row in store["cycles"] if row.get("cycle_id") == cycle_id)
        assert saved["predictor_failure"]["error"] == "fuse failed"
    finally:
        if backup is None:
            PIPELINE_ERRORS_FILE.unlink(missing_ok=True)
        else:
            PIPELINE_ERRORS_FILE.write_text(backup, encoding="utf-8")


def test_trading_gate_cluster_and_eligibility() -> None:
    from trading_gate import (
        agent_trading_eligibility,
        evaluate_cluster_agreement,
        ticker_trading_gate,
    )

    gate = {
        "enabled": True,
        "min_live_samples": 25,
        "min_benchmark_samples": 8,
        "min_accuracy_pct": 40.0,
        "require_cluster_agreement": True,
        "min_agreeing_clusters": 2,
        "min_cluster_contribution": 0.08,
        "min_net_score": 0.12,
    }
    cluster = evaluate_cluster_agreement(
        {"macro": 0.15, "quant": 0.11, "consumer": 0.02},
        net_score=0.35,
        settings=gate,
    )
    assert cluster["passes"] is True
    assert len(cluster["agreeing_clusters"]) >= 2

    weak = evaluate_cluster_agreement(
        {"macro": 0.15},
        net_score=0.35,
        settings=gate,
    )
    assert weak["passes"] is False

    blocked = agent_trading_eligibility("nonexistent-agent-xyz", settings=gate)
    assert blocked["eligible"] is False

    row = ticker_trading_gate(
        symbol="SPY",
        score=0.4,
        by_cluster={"macro": 0.2, "quant": 0.15},
        sources={"markets", "datascience"},
        settings=gate,
    )
    assert "cluster_agreement" in row


def test_pipeline_memory_bundle_and_steering() -> None:
    from agents.pipeline_memory import (
        activate_pipeline_memory,
        apply_pipeline_memory_to_result,
        clear_pipeline_memory,
        memory_bundle_for_agent,
    )

    activate_pipeline_memory(
        {
            "total_pipeline_runs": 3,
            "agent_learning": {
                "markets": {
                    "posture": "cautious",
                    "lessons": ["Too bullish on momentum."],
                    "avoid_symbols": ["GME"],
                    "trust_symbols": ["SPY"],
                    "preferred_horizon": "1wk",
                }
            },
            "accuracy_leaderboard": [{"agent_id": "markets", "combined_accuracy_pct": 44.0}],
            "prior_pipeline_runs": [{"cycle_id": "abc", "agents_ok": 18, "agents_total": 20}],
        }
    )
    try:
        bundle = memory_bundle_for_agent("markets")
        assert bundle["posture"] == "cautious"
        assert "GME" in bundle["avoid_symbols"]
        assert bundle["accuracy_rank"] == 1

        steered = apply_pipeline_memory_to_result(
            {
                "meta": {"expert_summary": "Risk-on tape."},
                "market_signals": [
                    {"tickers": ["GME"], "bias": "BULLISH", "confidence": 0.7},
                    {"tickers": ["SPY"], "bias": "BULLISH", "confidence": 0.7},
                ],
                "recommendations": ["Watch breadth."],
            },
            "markets",
            bundle,
        )
        assert len(steered["market_signals"]) == 1
        assert steered["market_signals"][0]["tickers"] == ["SPY"]
        assert steered["market_signals"][0]["confidence"] > 0.7
        assert any(str(r).startswith("[Memory]") for r in steered["recommendations"])
        assert "pipeline_memory" in steered["meta"]
    finally:
        clear_pipeline_memory()


def _run_all() -> None:
    tests = [
        test_app_paths_consistent,
        test_new_pipeline_cycle_id_format,
        test_record_pipeline_run_upsert,
        test_prediction_hit_logic,
        test_import_core_modules,
        test_pipeline_memory_bundle_and_steering,
        test_agent_signal_logic_thresholds,
        test_live_accuracy_merge_prefers_live_samples,
        test_temperature_stabilized_by_posture_and_accuracy,
        test_agent_domain_and_horizon_constraints,
        test_accuracy_measurement_horizon_and_regime,
        test_proactive_enhancement_candidates,
        test_validate_agent_output_freshness,
        test_record_pipeline_agent_errors_roundtrip,
        test_trading_gate_cluster_and_eligibility,
    ]
    for test in tests:
        test()
        print(f"ok {test.__name__}")
    print(f"passed {len(tests)} tests")


if __name__ == "__main__":
    _run_all()