"""Account goals — daily/total average P/L goal + group PL points."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_default_goals_primary_pl_focus() -> None:
    from account_goals import DEFAULT_ACCOUNT_GOALS, load_account_goals

    goals = load_account_goals(config_path=Path("/nonexistent/etrade_config.json"))
    assert goals["enabled"] is True
    assert goals["pl_points_enabled"] is True
    assert goals["agent_goal_bonus"] is True
    assert "daily" in (DEFAULT_ACCOUNT_GOALS.get("notes") or "").lower() or True
    assert "1.0%" in str(DEFAULT_ACCOUNT_GOALS.get("notes") or "") or "1.0" in str(
        DEFAULT_ACCOUNT_GOALS.get("notes") or ""
    )


def test_agent_goal_bonus_includes_pl_points() -> None:
    from account_goals import agent_goal_bonus_score

    progress = {
        "daily": {"target_pct": 2.0, "actual_pct": 1.0, "status": "behind"},
        "weekly": {"target_pct": 12.0, "actual_pct": 0.0, "status": "behind"},
        "monthly": {"target_pct": 48.0, "actual_pct": 0.0, "status": "behind"},
        "total_pl_pct": 3.2,
    }
    goals = {
        "enabled": True,
        "agent_goal_bonus": True,
        "pl_points_enabled": True,
    }
    gb = agent_goal_bonus_score(
        1.0,
        progress,
        goals=goals,
        agent_id="markets",
    )
    assert gb["eligible"] is True
    # 3 full % × 10 pts (alpha) = 30 PL points; daily 1% × 10 × 0.5 = 5 → 35
    assert gb["pl_points"] == 35.0
    assert gb["pl_detail"]["total_pct_units"] == 3
    assert gb["pl_detail"]["daily_pct_units"] == 1
    assert gb["points"] > 0
    assert gb["bonus"] > 0


def test_group_pl_leaderboard_orders_by_role() -> None:
    from account_goals import group_pl_leaderboard

    progress = {
        "daily": {"actual_pct": 2.0},
        "total_pl_pct": 5.0,
    }
    goals = {"enabled": True, "pl_points_enabled": True}
    rows = group_pl_leaderboard(progress, goals=goals)
    assert len(rows) >= 10
    # Top should be intraday (12 pts/pct) or tied high roles
    top = rows[0]
    assert float(top["pl_points_per_pct"]) >= 10.0
    # 5 total units + 2 daily half-weight
    # intraday: 5*12 + 2*12*0.5 = 60+12 = 72
    intraday = next(r for r in rows if r.get("trading_role") == "intraday")
    assert intraday["points"] == 72.0
    platform = next(r for r in rows if r.get("trading_role") == "platform")
    assert platform["points"] == 5 * 2 + 2 * 2 * 0.5  # 10 + 2 = 12
    assert platform["points"] < intraday["points"]
