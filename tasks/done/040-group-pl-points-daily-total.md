# Goal: increase daily & total average P/L — group points per 1% total P/L

target: AI-CODING
origin: PHONE
kind: work
handoff_count: 0
max_handoffs: 2
parent: none
status: done
completed: 2026-08-01
completed_by: AI-CODING

## Goal

Increase daily and total average P/L. Give each agent group **appropriate points for each 1.0% increase in total P/L**.

## Result

**Done.** Primary account goal is now daily + total average P/L. Groups earn role-scaled points for each full 1.0% of total (and daily) trading P/L.

### Points per full 1.0% total P/L (by trading_role)

| Role | Pts / 1% | Rationale |
|------|----------|-----------|
| intraday | 12 | Daily P/L focus |
| alpha / short_alpha | 10 | Direct edge drivers |
| sector_specialist / allocator | 9 | Sector & portfolio quality |
| regime / fusion | 8 | Timing & ensemble |
| risk_overlay | 6 | Overlay protection |
| risk_gate | 5 | Capital protection |
| execution | 4 | Fill quality support |
| platform | 2 | Data support only |

Daily P/L uses the same schedule at **0.5×** weight (avoids double-counting with total).

### API / wiring

- `agent_groups.py`: `ROLE_PL_POINTS_PER_PCT`, `group_pl_points_per_pct`, `agent_pl_points_per_pct`, `pl_points_for_total_gain`, `all_group_pl_point_rates`; scoring export + report meta stamp `pl_points_per_pct`
- `account_goals.py`: `primary_goal=increase_daily_and_total_average_pl`, `total_pl_pct` / `total_avg_pl_pct` on progress; horizon bonus tilt daily 50%; `agent_goal_bonus_score(..., agent_id=)` returns `pl_points`; `group_pl_leaderboard()`
- `account_balance_penalty.py`: agents get `pl_points` + detail; payload `group_pl_points` leaderboard; UI label `PL +Npts`

### Verify

- `tests/test_agent_group_scoring.py` — PL points tests pass
- `tests/test_account_goals_pl_points.py` — goals + leaderboard pass
- Prior scoring tests still pass

## Do not

- Commit tokens/keys
- Disable FinanceWorkspaceWatch
