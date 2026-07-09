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


def _run_all() -> None:
    tests = [
        test_app_paths_consistent,
        test_new_pipeline_cycle_id_format,
        test_record_pipeline_run_upsert,
        test_prediction_hit_logic,
        test_import_core_modules,
    ]
    for test in tests:
        test()
        print(f"ok {test.__name__}")
    print(f"passed {len(tests)} tests")


if __name__ == "__main__":
    _run_all()