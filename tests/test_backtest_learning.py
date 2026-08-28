"""Tests for walk-forward trial journal + learning rebuild + session brief."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def trial_paths(tmp_path, monkeypatch):
    import backtest_trial_store as store
    import agent_learning as learning

    trials_dir = tmp_path / "backtest_trials"
    monkeypatch.setattr(store, "TRIALS_DIR", trials_dir)
    monkeypatch.setattr(store, "LATEST_FILE", trials_dir / "latest_cycle.json")
    monkeypatch.setattr(store, "INDEX_FILE", trials_dir / "index.json")
    monkeypatch.setattr(store, "JSONL_FILE", trials_dir / "trials.jsonl")
    monkeypatch.setattr(learning, "LEARNING_FILE", tmp_path / "agent_learning.json")
    monkeypatch.setattr(learning, "BRIEF_FILE", tmp_path / "next_session_brief.json")
    monkeypatch.setattr(learning, "LEARNING_POLICY_FILE", tmp_path / "learning_policy.json")
    monkeypatch.setattr(learning, "ACCURACY_FILE", tmp_path / "prediction_accuracy.json")
    monkeypatch.setattr(learning, "BENCHMARK_FILE", tmp_path / "accuracy_benchmark.json")
    monkeypatch.setattr(learning, "SIM_FILE", tmp_path / "historical_simulation.json")
    monkeypatch.setattr(learning, "PENALTIES_FILE", tmp_path / "balance_penalties.json")
    return store, learning, tmp_path


def test_append_and_load_trials(trial_paths):
    store, _learning, _tmp = trial_paths
    trials = [
        {
            "agent_id": "grid",
            "symbol": "SPY",
            "horizon": "1wk",
            "predicted_direction": "up",
            "actual_direction": "up",
            "hit": True,
            "confidence": 0.6,
            "source": "bar_walk_forward",
            "simulated_at": "2025-06-01T13:30:00+00:00",
        },
        {
            "agent_id": "grid",
            "symbol": "QQQ",
            "horizon": "1wk",
            "predicted_direction": "up",
            "actual_direction": "down",
            "hit": False,
            "confidence": 0.55,
            "source": "bar_walk_forward",
            "simulated_at": "2025-06-08T13:30:00+00:00",
        },
    ]
    out = store.append_trials(trials, cycle_id="bt_test_1", meta={"full": True})
    assert out["trial_count"] == 2
    assert store.LATEST_FILE.exists()
    assert store.JSONL_FILE.exists()
    loaded = store.load_recent_trials(max_rows=100)
    assert len(loaded) >= 2
    assert any(r.get("symbol") == "SPY" for r in loaded)


def test_rebuild_learning_and_brief(trial_paths):
    store, learning, tmp = trial_paths
    # seed benchmark agents
    bench = {
        "meta": {"expert_summary": "test bench"},
        "agents": {
            "grid": {
                "agent_id": "grid",
                "accuracy_pct": 40.0,
                "total_trials": 40,
                "hits": 16,
                "by_horizon": {
                    "1wk": {"total": 20, "hits": 10, "accuracy_pct": 50.0},
                    "24h": {"total": 20, "hits": 6, "accuracy_pct": 30.0},
                },
            },
            "bear-thesis": {
                "agent_id": "bear-thesis",
                "accuracy_pct": 20.0,
                "total_trials": 40,
                "hits": 8,
                "by_horizon": {"24h": {"total": 40, "hits": 8, "accuracy_pct": 20.0}},
            },
        },
        "leaderboard": [
            {"agent_id": "grid", "accuracy_pct": 40.0, "total_trials": 40},
            {"agent_id": "bear-thesis", "accuracy_pct": 20.0, "total_trials": 40},
        ],
    }
    (tmp / "accuracy_benchmark.json").write_text(json.dumps(bench), encoding="utf-8")
    (tmp / "prediction_accuracy.json").write_text(json.dumps({"agents": {}, "scored": []}), encoding="utf-8")

    rows = []
    for i in range(12):
        rows.append(
            {
                "agent_id": "grid",
                "symbol": "XLU" if i % 2 == 0 else "SPY",
                "horizon": "1wk",
                "predicted_direction": "up",
                "actual_direction": "up" if i < 7 else "down",
                "hit": i < 7,
                "source": "bar_walk_forward",
                "simulated_at": f"2025-05-{i+1:02d}T13:30:00+00:00",
            }
        )
    store.append_trials(rows, cycle_id="bt_test_2")

    # Avoid depending on full platform catalog — call _build_learning path via partial rebuild
    # by monkeypatching active sources.
    class _Src(dict):
        pass

    def fake_sources(check_remote=False):
        return [{"id": "grid"}, {"id": "bear-thesis"}]

    import agents.platform_catalog as catalog

    # patch via monkeypatch is not available here; simple assign
    original = catalog.active_agent_sources
    catalog.active_agent_sources = fake_sources  # type: ignore
    try:
        # fusion import may pull agent_uses_directional_accuracy
        payload = learning.rebuild_agent_learning()
    finally:
        catalog.active_agent_sources = original  # type: ignore

    assert "grid" in payload["agents"]
    grid = payload["agents"]["grid"]
    assert grid.get("preferred_horizon") in {"1wk", "24h"}
    assert "edge_score" in grid
    assert learning.LEARNING_FILE.exists()
    assert learning.LEARNING_POLICY_FILE.exists()

    brief = learning.write_next_session_brief(benchmark=bench)
    assert brief.get("top_agents")
    assert learning.BRIEF_FILE.exists()
    loaded = learning.load_next_session_brief()
    assert loaded.get("for_session") == "next_RTH"


def test_policy_fusion_multiplier(trial_paths):
    _store, learning, tmp = trial_paths
    policy = {
        "boost_agents": ["grid"],
        "cut_agents": ["bear-thesis"],
        "agents": {
            "grid": {"edge_score": 0.3},
            "bear-thesis": {"edge_score": -0.4},
        },
    }
    learning.LEARNING_POLICY_FILE.write_text(json.dumps(policy), encoding="utf-8")
    assert learning.policy_fusion_multiplier("grid") > 1.0
    assert learning.policy_fusion_multiplier("bear-thesis", for_trading=True) < 0.5
    assert learning.policy_fusion_multiplier("unknown") == 1.0


def test_sticky_live_pct_not_reset_by_proxy(trial_paths):
    """Proxy bar-walk must not overwrite a stored live accuracy_pct."""
    store, learning, tmp = trial_paths
    (tmp / "accuracy_benchmark.json").write_text(json.dumps({"agents": {}}), encoding="utf-8")
    (tmp / "prediction_accuracy.json").write_text(
        json.dumps({"agents": {}, "live_agents": {}, "scored": []}),
        encoding="utf-8",
    )
    learning.LEARNING_FILE.write_text(
        json.dumps(
            {
                "agents": {
                    "grid": {
                        "agent_id": "grid",
                        "accuracy_pct": 44.9,
                        "sample_trials": 136,
                        "edge_score": 0.5,
                        "lessons": [],
                        "avoid_symbols": [],
                        "trust_symbols": [],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    rows = []
    for i in range(12):
        rows.append(
            {
                "agent_id": "grid",
                "symbol": "SPY",
                "horizon": "24h",
                "predicted_direction": "up",
                "actual_direction": "down",
                "hit": False,
                "source": "bar_walk_forward",
                "simulated_at": f"2025-06-{i+1:02d}T13:30:00+00:00",
            }
        )
    store.append_trials(rows, cycle_id="bt_sticky")

    import agents.platform_catalog as catalog

    original = catalog.active_agent_sources
    catalog.active_agent_sources = lambda check_remote=False: [{"id": "grid"}]  # type: ignore
    try:
        payload = learning.rebuild_agent_learning()
    finally:
        catalog.active_agent_sources = original  # type: ignore

    grid = payload["agents"]["grid"]
    assert grid["accuracy_pct"] == 44.9
    assert grid["sample_trials"] == 136
    assert grid.get("proxy_accuracy_pct") is not None
    assert grid["proxy_accuracy_pct"] < 40


def test_sticky_ignores_tiny_zero_live_slice(trial_paths):
    store, learning, tmp = trial_paths
    (tmp / "accuracy_benchmark.json").write_text(json.dumps({"agents": {}}), encoding="utf-8")
    live_rows = []
    for i in range(7):
        live_rows.append(
            {
                "agent_id": "grid",
                "symbol": "SPY",
                "horizon": "24h",
                "predicted_direction": "up",
                "actual_direction": "down",
                "hit": False,
            }
        )
    (tmp / "prediction_accuracy.json").write_text(
        json.dumps(
            {
                "live_agents": {
                    "grid": {
                        "accuracy_pct": 0.0,
                        "combined_accuracy_pct": 0.0,
                        "total_scored": 7,
                    }
                },
                "agents": {
                    "grid": {
                        "accuracy_pct": 44.9,
                        "combined_accuracy_pct": 44.9,
                        "total_scored": 136,
                    }
                },
                "scored": live_rows,
            }
        ),
        encoding="utf-8",
    )
    learning.LEARNING_FILE.write_text(
        json.dumps(
            {
                "agents": {
                    "grid": {"agent_id": "grid", "accuracy_pct": 0.0, "sample_trials": 7}
                }
            }
        ),
        encoding="utf-8",
    )
    store.append_trials(
        [
            {
                "agent_id": "grid",
                "symbol": "SPY",
                "horizon": "24h",
                "predicted_direction": "up",
                "actual_direction": "down",
                "hit": False,
                "source": "bar_walk_forward",
            }
        ]
        * 8,
        cycle_id="bt_zero",
    )
    import agents.platform_catalog as catalog

    original = catalog.active_agent_sources
    catalog.active_agent_sources = lambda check_remote=False: [{"id": "grid"}]  # type: ignore
    try:
        payload = learning.rebuild_agent_learning()
    finally:
        catalog.active_agent_sources = original  # type: ignore
    assert payload["agents"]["grid"]["accuracy_pct"] == 44.9
    assert payload["agents"]["grid"]["sample_trials"] == 136


def test_labels_net_and_purge():
    from backtest_labels import net_return_pct, purged_keep, round_trip_cost_pct, source_bucket

    assert round_trip_cost_pct("SPY") < round_trip_cost_pct("FAKE")
    net = net_return_pct("up", 1.0, symbol="SPY")
    assert net < 1.0
    assert net_return_pct("flat", 5.0, symbol="SPY") == 0.0
    assert purged_keep(25, 25, "24h", 5) is True
    assert purged_keep(26, 25, "1yr", 5) is False
    assert purged_keep(25, 25, "1yr", 5) is True
    assert source_bucket("bar_walk_forward") == "proxy"
    assert source_bucket("snapshot_replay") == "replay"
    assert source_bucket("live") == "live"


def test_night_window_skip_ignores_full_day(trial_paths):
    store, _learning, _tmp = trial_paths
    store.append_trials(
        [
            {
                "agent_id": "grid",
                "symbol": "SPY",
                "horizon": "24h",
                "predicted_direction": "up",
                "actual_direction": "up",
                "hit": True,
                "source": "full_day_walk_forward",
            }
        ],
        cycle_id="bt_full",
        meta={"source": "full_day_walk_forward", "window_end": "2026-08-27"},
    )
    assert store.night_window_already_journaled("2026-08-27") is False
    store.append_trials(
        [
            {
                "agent_id": "grid",
                "symbol": "SPY",
                "horizon": "24h",
                "predicted_direction": "up",
                "actual_direction": "up",
                "hit": True,
                "source": "bar_walk_forward",
            }
        ],
        cycle_id="bt_night",
        meta={"source": "bar_walk_forward", "window_end": "2026-08-27"},
    )
    assert store.night_window_already_journaled("2026-08-27") is True
    assert store.night_window_already_journaled("2026-08-28") is False


def test_base_expert_apply_learning(trial_paths, monkeypatch):
    _store, learning, tmp = trial_paths
    # minimal learning file
    learning_payload = {
        "agents": {
            "grid": {
                "agent_id": "grid",
                "accuracy_pct": 42.0,
                "bias_drift": -0.1,
                "confidence_scale": 0.9,
                "fusion_multiplier": 1.1,
                "preferred_horizon": "1wk",
                "posture": "calibrated",
                "lessons": ["test lesson"],
                "avoid_symbols": ["BAD"],
                "trust_symbols": ["GOOD"],
                "bullish_miss_rate": 0.6,
                "bearish_miss_rate": 0.3,
                "blame_score": 0.0,
                "edge_score": 0.2,
                "sample_trials": 40,
                "horizon_weights": {"1wk": 1.1},
                "min_confidence_to_emit": 0.4,
                "source": "walk_forward",
                "updated_at": "2026-08-01T00:00:00+00:00",
            }
        }
    }
    learning.LEARNING_FILE.write_text(json.dumps(learning_payload), encoding="utf-8")

    from agents.base import BaseExpert

    expert = BaseExpert(agent_id="grid")
    out = expert.apply_learning_to_signal(direction="up", confidence=0.5, symbol="GOOD")
    assert out["learning_applied"] is True
    assert out["confidence"] > 0
    assert out["preferred_horizon"] == "1wk"
    weak = expert.apply_learning_to_signal(direction="up", confidence=0.2, symbol="BAD")
    assert weak["suppressed"] is True or weak["direction"] == "flat"
