"""Stale / all-1037 plans must trigger rebuild; age alone does not hot-loop."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from etrade_worker import _plan_should_rebuild  # noqa: E402


def test_missing_plan() -> None:
    assert _plan_should_rebuild(None) == "missing_plan"
    assert _plan_should_rebuild({}) == "missing_plan"


def test_old_generated_at() -> None:
    old = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    why = _plan_should_rebuild({"generated_at": old, "orders": []})
    assert why and why.startswith("plan_age_")


def test_fresh_plan_ok() -> None:
    now = datetime.now(timezone.utc).isoformat()
    assert _plan_should_rebuild({"generated_at": now, "orders": []}) is None


def test_all_sells_1037() -> None:
    now = datetime.now(timezone.utc).isoformat()
    data = {
        "generated_at": now,
        "orders": [
            {"action": "SELL", "symbol": "NVDA", "message": "E*TRADE error 1037: not enough"},
            {"action": "SELL", "symbol": "GME", "message": "E*TRADE error 1037: not enough"},
        ],
    }
    assert _plan_should_rebuild(data) == "all_sells_1037"


if __name__ == "__main__":
    test_missing_plan()
    test_old_generated_at()
    test_fresh_plan_ok()
    test_all_sells_1037()
    print("ALL_OK")
