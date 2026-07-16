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


def test_market_predictor_symbol_returns_differ() -> None:
    from agents.market_predictor import _build_horizon_rows, _enrich_symbol_price_returns

    rows = {
        "AAA": {
            "score": 0.774,
            "confidence": 0.8,
            "sources": {"history"},
            "notes": ["test"],
            "return_5d_pct": 4.65,
            "return_20d_pct": -17.59,
        },
        "BBB": {
            "score": 0.774,
            "confidence": 0.8,
            "sources": {"history"},
            "notes": ["test"],
            "return_5d_pct": 6.12,
            "return_20d_pct": 4.42,
        },
    }
    ranked = [("AAA", rows["AAA"]), ("BBB", rows["BBB"])]
    built = _build_horizon_rows(ranked, "1wk", limit=2)
    returns = {row["symbol"]: row["predicted_return_pct"] for row in built}
    assert returns["AAA"] != returns["BBB"]


def test_projected_return_shows_horizon() -> None:
    from position_analysis import _projected_return_line, merge_portfolio_projection, projected_return_compact

    assert projected_return_compact(
        {"projected_return_pct": 3.7, "projected_return_horizon": "1wk"}
    ) == "+3.70% over 1 week"
    assert (
        _projected_return_line({"projected_return_pct": 1.92, "projected_return_horizon": "1wk"})
        == "Projected return (1 week): +1.92%"
    )
    assert (
        _projected_return_line({"projected_return_pct": 2.5, "projected_return_horizon": "today"})
        == "Projected return (today): +2.50%"
    )
    assert (
        _projected_return_line({"projected_return_pct": 4.0})
        == "Projected return: +4.00%"
    )
    merged = merge_portfolio_projection(
        {"symbol": "ENPH", "projected_return_pct": 1.92},
        {"symbol": "ENPH", "projected_return_pct": 3.7, "projected_return_horizon": "1wk"},
    )
    assert merged is not None
    assert merged.get("projected_return_horizon") == "1wk"
    assert merged.get("projected_return_pct") == 3.7


def test_external_deposits_excluded_from_profit() -> None:
    from account_profit import detect_external_flow_events, profit_metrics_for_account

    growth = {
        "baseline_value": 78.0,
        "latest_value": 320.65,
        "accounts": {
            "acct1": {"opening_balance": 78.0, "opened_at": "2026-07-06"},
        },
        "points": [
            {
                "at": "2026-07-08T21:29:05+00:00",
                "total_account_value": 76.29,
                "cash_buying_power": 30.17,
                "account_id_key": "acct1",
            },
            {
                "at": "2026-07-10T03:47:15+00:00",
                "total_account_value": 73.05,
                "cash_buying_power": 50.08,
                "account_id_key": "acct1",
            },
            {
                "at": "2026-07-10T10:02:54+00:00",
                "total_account_value": 323.06,
                "cash_buying_power": 300.09,
                "account_id_key": "acct1",
            },
            {
                "at": "2026-07-16T13:56:07+00:00",
                "total_account_value": 320.65,
                "cash_buying_power": 23.73,
                "account_id_key": "acct1",
            },
        ],
    }
    events = detect_external_flow_events(growth["points"], "acct1")
    assert len(events) == 1
    assert events[0]["kind"] == "deposit"
    assert events[0]["amount"] == 250.01

    metrics = profit_metrics_for_account(growth, "acct1")
    assert metrics["net_external_flows"] == 250.01
    assert metrics["invested_capital"] == 328.01
    assert metrics["profit_amount"] == -7.36
    assert metrics["profit_pct"] == -2.24

    no_deposit_growth = {
        "accounts": {"acct1": {"opening_balance": 100.0}},
        "points": [
            {"at": "2026-07-08T10:00:00+00:00", "total_account_value": 100.0, "cash_buying_power": 20.0, "account_id_key": "acct1"},
            {"at": "2026-07-09T10:00:00+00:00", "total_account_value": 105.0, "cash_buying_power": 18.0, "account_id_key": "acct1"},
        ],
    }
    assert detect_external_flow_events(no_deposit_growth["points"], "acct1") == []
    steady = profit_metrics_for_account(no_deposit_growth, "acct1")
    assert steady["profit_amount"] == 5.0
    assert steady["profit_pct"] == 5.0


def test_order_execution_skips_directional_scoring() -> None:
    from agent_fusion import agent_uses_directional_accuracy
    from agent_learning import rebuild_agent_learning
    from live_accuracy import merge_live_and_benchmark
    from prediction_accuracy import _append_prediction

    assert agent_uses_directional_accuracy("markets") is True
    assert agent_uses_directional_accuracy("order-execution") is False

    pending: list[dict] = []
    _append_prediction(
        pending,
        agent_id="order-execution",
        symbol="AAPL",
        horizon="24h",
        predicted_direction="flat",
        confidence=0.5,
        predicted_return_pct=None,
        price_at_prediction=100.0,
        cycle_id="test-cycle",
        recorded_at="2026-07-16T12:00:00+00:00",
    )
    assert pending == []

    merged = merge_live_and_benchmark(
        {"agent_id": "order-execution", "total_scored": 101, "combined_accuracy_pct": 100.0},
        {"agent_id": "order-execution", "total_scored": 65, "combined_accuracy_pct": 30.8, "accuracy_pct": 30.8},
        agent_id="order-execution",
    )
    assert merged is not None
    assert merged.get("combined_accuracy_pct") == 30.8
    assert merged.get("accuracy_source") == "walk_forward_benchmark"
    assert merged.get("live_weight") == 0.0

    learning = rebuild_agent_learning()
    row = (learning.get("agents") or {}).get("order-execution") or {}
    assert row.get("accuracy_pct") == 30.8
    assert row.get("posture") == "cautious"


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
        weather_disruption_confidence,
        innovation_velocity_confidence,
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
    assert weather_disruption_confidence(disruption=0.8, heat=0.7, severe=0.45) >= 0.55
    assert innovation_velocity_confidence(innovation_score=72.0, filing_count=12, high_impact_count=3) >= 0.55
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


def test_transportation_and_meteorology_market_impact_signals() -> None:
    from agent_constraints import apply_agent_constraints_to_result, load_domain_constraint_settings
    from agent_signal_logic import (
        MARKET_IMPACT_TICKERS,
        meteorology_market_impact_signals,
        transportation_market_impact_signals,
    )

    freight_up = transportation_market_impact_signals(
        infrastructure_stress=32.0,
        stress_label="Stable infrastructure conditions",
        freight_score=78.0,
        truck_chg_avg_pct=4.2,
        passenger_chg_avg_pct=1.1,
        unknown_bridge_design_pct=8.0,
    )
    assert freight_up
    assert all(sig.get("impact_scope") == "market" for sig in freight_up)
    transport_tickers = {t for sig in freight_up for t in sig.get("tickers", [])}
    assert "SPY" in transport_tickers
    assert "XLI" in transport_tickers
    assert not any(t in {"UNP", "CSX", "JBHT", "ODFL"} for t in transport_tickers)

    weather_shock = meteorology_market_impact_signals(
        heat_stress=0.74,
        cold_stress=0.2,
        severe_stress=0.48,
        flood_stress=0.3,
        energy_stress=0.78,
        disruption_score=0.81,
        disruption_label="Critical",
        tropical_activity="Active tropical systems in Gulf",
        agricultural_risk="Heat/drought stress on Plains crops",
        heat_alerts=18,
        cold_alerts=2,
        severe_alerts=11,
    )
    assert weather_shock
    assert all(sig.get("impact_scope") == "market" for sig in weather_shock)
    weather_tickers = {t for sig in weather_shock for t in sig.get("tickers", [])}
    assert "SPY" in weather_tickers
    assert all(t in MARKET_IMPACT_TICKERS for t in weather_tickers)
    assert not any(t in {"CEG", "VST", "ALL", "TRV", "DBA", "CORN"} for t in weather_tickers)

    for agent_id, payload in (
        ("transportation", freight_up),
        ("meteorology", weather_shock),
    ):
        steered = apply_agent_constraints_to_result(
            {"meta": {}, "market_signals": payload},
            agent_id,
            settings=load_domain_constraint_settings(),
        )
        assert steered["market_signals"]
        assert "SPY" in steered["market_signals"][0]["tickers"]


def test_remaining_specialist_market_impact_signals() -> None:
    from agent_constraints import apply_agent_constraints_to_result, load_domain_constraint_settings
    from agent_signal_logic import (
        MARKET_IMPACT_TICKERS,
        logistics_market_impact_signals,
        patents_market_impact_signals,
        sales_consumer_market_impact_signals,
    )

    logistics_stress = logistics_market_impact_signals(
        supply_chain_stress=0.78,
        stress_label="Critical",
        freight_momentum=0.62,
        congestion_score=0.71,
        us_west_coast_congestion=0.74,
        tanker_flow_active=True,
        retail_lead_time_stressed=True,
    )
    assert logistics_stress and all(sig.get("impact_scope") == "market" for sig in logistics_stress)
    logistics_tickers = {t for sig in logistics_stress for t in sig.get("tickers", [])}
    assert "SPY" in logistics_tickers
    assert not any(t in {"ZIM", "BDRY", "CHRW", "AMZN"} for t in logistics_tickers)

    patent_burst = patents_market_impact_signals(
        innovation_score=76.0,
        landscape_label="High innovation velocity",
        by_sector={"artificial-intelligence": 5, "semiconductor": 3},
        high_impact_count=3,
        top_sector="artificial-intelligence",
    )
    assert patent_burst and all(sig.get("impact_scope") == "market" for sig in patent_burst)
    patent_tickers = {t for sig in patent_burst for t in sig.get("tickers", [])}
    assert "QQQ" in patent_tickers
    assert not any(t in {"NVDA", "MRNA", "ABCL", "ARKK"} for t in patent_tickers)

    consumer_risk_on = sales_consumer_market_impact_signals(
        consumer_strength=0.68,
        breadth_pct=62.0,
        momentum_index=0.71,
        discretionary_premium_pct=1.2,
        strength_label="Strong consumer demand",
        leading_category="Big Box Retail",
        category_momentum=0.64,
        e_commerce_weak=False,
    )
    assert consumer_risk_on and all(sig.get("impact_scope") == "market" for sig in consumer_risk_on)
    retail_tickers = {t for sig in consumer_risk_on for t in sig.get("tickers", [])}
    assert "SPY" in retail_tickers
    assert "XLY" in retail_tickers
    assert not any(t in {"WMT", "COST", "AMZN", "TGT"} for t in retail_tickers)
    assert all(t in MARKET_IMPACT_TICKERS for t in retail_tickers)

    for agent_id, payload in (
        ("logistics", logistics_stress),
        ("patents", patent_burst),
        ("sales-analytics", consumer_risk_on),
    ):
        steered = apply_agent_constraints_to_result(
            {"meta": {}, "market_signals": payload},
            agent_id,
            settings=load_domain_constraint_settings(),
        )
        assert steered["market_signals"]
        assert "SPY" in steered["market_signals"][0]["tickers"]


def test_power_grid_market_impact_signals() -> None:
    from agent_constraints import apply_agent_constraints_to_result, load_domain_constraint_settings
    from agent_signal_logic import MARKET_IMPACT_TICKERS, power_grid_market_impact_signals

    stressed = power_grid_market_impact_signals(
        grid_stress=72.0,
        stress_label="Elevated grid stress",
        renewable_pct=22.0,
        gas_pct=52.0,
        avg_lmp=61.0,
        weather_energy=0.68,
        peak_load_mw=82_000.0,
        source="grid",
    )
    assert stressed
    assert all(sig.get("impact_scope") == "market" for sig in stressed)
    tickers = {t for sig in stressed for t in sig.get("tickers", [])}
    assert "SPY" in tickers
    assert "XLI" in tickers
    assert all(t in MARKET_IMPACT_TICKERS for t in tickers)
    assert not any(t in {"XLU", "VST", "NEE", "TAN"} for t in tickers)

    steered = apply_agent_constraints_to_result(
        {"meta": {}, "market_signals": stressed},
        "grid",
        settings=load_domain_constraint_settings(),
    )
    assert steered["market_signals"]
    assert "SPY" in steered["market_signals"][0]["tickers"]


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


def test_yahoo_session_cache_and_shared_fetch() -> None:
    from agents.market_data.yahoo import clear_yahoo_session_cache, fetch_closes

    clear_yahoo_session_cache()
    # Cache should not raise; network may fail in CI — accept empty or data
    first = fetch_closes("SPY", range_="1mo", delay_seconds=0, client_tag="smoke")
    second = fetch_closes("SPY", range_="1mo", delay_seconds=0, client_tag="smoke")
    assert second == first


def test_agent_disagreement_contested_symbol() -> None:
    from agent_disagreement import (
        collect_agent_bias_votes,
        disagreement_confidence_factor,
        disagreement_fusion_multiplier,
        top_contested_symbols,
    )

    outputs = {
        "markets": {
            "market_signals": [
                {"tickers": ["NVDA"], "bias": "BULLISH", "confidence": 0.8},
            ]
        },
        "finance": {
            "market_signals": [
                {"tickers": ["NVDA"], "bias": "BEARISH", "confidence": 0.75},
            ]
        },
    }
    votes = collect_agent_bias_votes(agent_outputs=outputs)
    contested = top_contested_symbols(votes)
    assert any(row["symbol"] == "NVDA" for row in contested)
    bull_factor = disagreement_confidence_factor("NVDA", "BULLISH", votes)
    bear_factor = disagreement_confidence_factor("NVDA", "BEARISH", votes)
    assert bull_factor < 1.0 or bear_factor < 1.0
    assert disagreement_fusion_multiplier("NVDA", 0.5, votes) < 1.0


def test_base_expert_watchlist_and_memory() -> None:
    from agents.base import BaseExpert

    expert = BaseExpert(
        agent_id="datascience",
        pipeline_context={
            "live_quote_symbols": ["SPY", "AAPL"],
            "trust_symbols": ["MSFT"],
            "avoid_symbols": ["GME"],
            "lessons": ["Reduce weak calls."],
        },
    )
    wl = expert.pipeline_watchlist_symbols(["QQQ"], limit=10)
    assert "SPY" in wl
    assert "GME" not in wl
    recs = expert.append_memory_recommendations(["Quant scan complete."])
    assert any(str(r).startswith("[Memory]") for r in recs)


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


def test_intraday_prediction_horizons() -> None:
    from agents.market_predictor import HORIZON_RETURN_SCALE, PREDICTION_HORIZONS
    from prediction_accuracy import HORIZON_HOURS, horizon_timedelta

    assert "1m" in PREDICTION_HORIZONS
    assert "1h" in PREDICTION_HORIZONS
    assert HORIZON_RETURN_SCALE["1m"] < HORIZON_RETURN_SCALE["1h"]
    assert horizon_timedelta("1m").total_seconds() == 60
    assert horizon_timedelta("1h").total_seconds() == 3600
    assert HORIZON_HOURS["1h"] == 1


def test_resolve_pipeline_benchmark_profiles() -> None:
    from historical_simulation import resolve_pipeline_benchmark

    skip = resolve_pipeline_benchmark("skip")
    assert skip.get("enabled") is False
    daily = resolve_pipeline_benchmark("daily")
    assert daily.get("profile") == "daily"
    assert int(daily.get("target_trials", 0)) >= 1000


def test_merge_agent_output_for_restore_prefers_memory_impact() -> None:
    from agents.pipeline_memory import merge_agent_output_for_restore

    memory = {
        "market_signals": [
            {"sector": "Broad Market", "tickers": ["SPY"], "impact_scope": "market"},
        ],
    }
    legacy = {
        "market_signals": [
            {"sector": "Dry Bulk Shipping", "tickers": ["BDRY"], "bias": "NEUTRAL"},
        ],
        "meta": {"learning": {"accuracy_pct": 58.1}},
    }
    merged = merge_agent_output_for_restore(memory, legacy)
    assert merged["market_signals"][0]["impact_scope"] == "market"
    assert merged["meta"]["learning"]["accuracy_pct"] == 58.1


def test_restore_same_cycle_agent_outputs() -> None:
    import tempfile

    import app_paths
    from agents import pipeline_memory as pm

    out_dir = Path(tempfile.mkdtemp()) / "output"
    out_dir.mkdir()
    original_output = app_paths.OUTPUT
    app_paths.OUTPUT = out_dir
    payload = {
        "meta": {"analyzed_at": "2026-01-01T00:00:00+00:00"},
        "market_signals": [
            {"sector": "Broad Market", "tickers": ["SPY"], "impact_scope": "market"},
        ],
        "recommendations": ["ok"],
    }
    pm.begin_pipeline_memory_session()
    try:
        pm.register_same_cycle_agent_output("logistics", payload)
        restored = pm.restore_same_cycle_agent_outputs(
            [{"id": "logistics", "file": "logistics.json"}],
        )
        assert restored == 1
        written = json.loads((out_dir / "logistics.json").read_text(encoding="utf-8"))
        assert written["market_signals"][0]["impact_scope"] == "market"
    finally:
        pm.end_pipeline_memory_session()
        app_paths.OUTPUT = original_output


def test_market_predictor_cli_registered() -> None:
    """market-predictor must appear in RUNNERS and PRINTERS and round-trip without error."""
    import tempfile

    import app_paths
    from main import PRINTERS, RUNNERS

    assert "market-predictor" in RUNNERS, "market-predictor missing from RUNNERS"
    assert "market-predictor" in PRINTERS, "market-predictor missing from PRINTERS"

    out_dir = Path(tempfile.mkdtemp()) / "output"
    out_dir.mkdir()
    original_output = app_paths.OUTPUT
    app_paths.OUTPUT = out_dir
    try:
        out_file = out_dir / "market_predictions.json"
        result = RUNNERS["market-predictor"](output=out_file)
        assert isinstance(result, dict), "run_market_predictor_analysis must return a dict"
        assert "predictions" in result, "result must contain 'predictions'"
        assert "meta" in result, "result must contain 'meta'"
        # Printer must not raise on empty/no-data result
        PRINTERS["market-predictor"](result)
    finally:
        app_paths.OUTPUT = original_output


def test_market_predictor_loop_cycle_no_crash() -> None:
    """run_predictor_cycle must complete without raising even with no agent data."""
    import tempfile
    import unittest.mock as mock

    import app_paths

    out_dir = Path(tempfile.mkdtemp()) / "output"
    out_dir.mkdir()
    original_output = app_paths.OUTPUT
    app_paths.OUTPUT = out_dir
    try:
        import run_market_predictor_loop as loop_mod

        original_log = loop_mod.OUTPUT
        loop_mod.OUTPUT = out_dir
        try:
            # Patch _run_signal_agent to skip network calls
            with mock.patch.object(loop_mod, "_run_signal_agent", return_value=True):
                entry = loop_mod.run_predictor_cycle()
            assert isinstance(entry, dict), "run_predictor_cycle must return a dict"
            assert "predictor_ok" in entry
            assert "finished_at" in entry
        finally:
            loop_mod.OUTPUT = original_log
    finally:
        app_paths.OUTPUT = original_output


def test_backtest_loop_cycle_no_crash() -> None:
    """run_backtest_cycle must complete without raising, even if the benchmark fails."""
    import unittest.mock as mock

    import run_backtest_loop as loop_mod

    with mock.patch(
        "historical_simulation.run_accuracy_benchmark",
        return_value={
            "metrics": {"total_trials": 42},
            "leaderboard": [{"agent_id": "markets", "accuracy_pct": 55.0}],
        },
    ):
        entry = loop_mod.run_backtest_cycle(target_trials=10, max_symbols=5, full=False)
    assert isinstance(entry, dict), "run_backtest_cycle must return a dict"
    assert entry["backtest_ok"] is True
    assert entry["trials"] == 42
    assert entry["top_agent"] == "markets"
    assert "finished_at" in entry

    with mock.patch(
        "historical_simulation.run_accuracy_benchmark",
        side_effect=RuntimeError("boom"),
    ):
        failed_entry = loop_mod.run_backtest_cycle(target_trials=10, max_symbols=5, full=False)
    assert failed_entry["backtest_ok"] is False
    assert failed_entry["status"] == "error"


def test_backtest_loop_cli_argument_validation() -> None:
    """CLI rejects non-positive interval/target-trials/max-symbols values."""
    import unittest.mock as mock

    import run_backtest_loop as loop_mod

    with mock.patch.object(sys, "argv", ["run_backtest_loop.py", "--interval-minutes", "0"]):
        assert loop_mod.main() == 2
    with mock.patch.object(sys, "argv", ["run_backtest_loop.py", "--target-trials", "0"]):
        assert loop_mod.main() == 2
    with mock.patch.object(sys, "argv", ["run_backtest_loop.py", "--max-symbols", "0"]):
        assert loop_mod.main() == 2


def _run_all() -> None:
    tests = [
        test_app_paths_consistent,
        test_new_pipeline_cycle_id_format,
        test_record_pipeline_run_upsert,
        test_prediction_hit_logic,
        test_external_deposits_excluded_from_profit,
        test_import_core_modules,
        test_pipeline_memory_bundle_and_steering,
        test_intraday_prediction_horizons,
        test_resolve_pipeline_benchmark_profiles,
        test_merge_agent_output_for_restore_prefers_memory_impact,
        test_restore_same_cycle_agent_outputs,
        test_agent_signal_logic_thresholds,
        test_live_accuracy_merge_prefers_live_samples,
        test_temperature_stabilized_by_posture_and_accuracy,
        test_transportation_and_meteorology_market_impact_signals,
        test_remaining_specialist_market_impact_signals,
        test_power_grid_market_impact_signals,
        test_agent_domain_and_horizon_constraints,
        test_accuracy_measurement_horizon_and_regime,
        test_proactive_enhancement_candidates,
        test_validate_agent_output_freshness,
        test_record_pipeline_agent_errors_roundtrip,
        test_yahoo_session_cache_and_shared_fetch,
        test_agent_disagreement_contested_symbol,
        test_base_expert_watchlist_and_memory,
        test_trading_gate_cluster_and_eligibility,
        test_market_predictor_cli_registered,
        test_market_predictor_loop_cycle_no_crash,
        test_backtest_loop_cycle_no_crash,
        test_backtest_loop_cli_argument_validation,
    ]
    for test in tests:
        test()
        print(f"ok {test.__name__}")
    print(f"passed {len(tests)} tests")


if __name__ == "__main__":
    _run_all()