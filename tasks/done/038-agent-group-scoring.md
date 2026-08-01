# Agent groups — per-group scoring systems

target: AI-CODING
origin: PHONE
kind: work
handoff_count: 0
max_handoffs: 2
parent: none
status: done
completed: 2026-07-31
completed_by: AI-CODING

## Goal

Give each agent group a scoring system based on the function of the group.

## Result

**Done.** Every entry in `AGENT_GROUPS` now has a function-specific `scoring` block (mode, primary metric, weighted KPIs, direction/magnitude blend, score horizon, success criteria).

### Scoring modes (by function)

| Group | Mode | Primary metric |
|-------|------|----------------|
| markets_core | directional_alpha | opportunity_hit_rate |
| quant_stats | calibration | probability_calibration |
| macro_index | regime_timing | regime_alignment |
| intelligence | risk_overlay | early_warning_quality |
| infrastructure / transport / consumer | domain_specialist | domain_hit_rate |
| day_trading | intraday | session_hit_rate |
| short_mechanics | short_alpha | short_candidate_quality |
| risk_protection | risk_gate | capital_protection |
| fundamental_tech | multi_horizon | thesis_accuracy |
| portfolio_alloc | allocation | portfolio_quality |
| data_platform | platform_quality | data_health |
| execution | execution_quality | fill_quality |
| fusion | ensemble | blend_calibration |

### API (`agent_groups.py`)

- `agent_scoring_system(agent_id)` / `group_scoring_for(group_id)`
- `agent_scoring_mode` / `agent_primary_metric` / `score_horizon_for_agent`
- `group_accuracy_weights` → direction/magnitude blend for combined accuracy
- `composite_group_score` → weighted 0–100 grade from metric values
- `all_scoring_systems()` catalog export
- Report meta stamps: `scoring_mode`, `primary_metric`, `score_horizon`

### Wiring

- `accuracy_measurement.py` uses group direction/magnitude weights and attaches scoring mode/primary metric on accuracy rows
- Platform/execution: direction weight 0 (not graded on price direction)

### Verify

- `tests/test_agent_group_scoring.py` — 7 tests, all pass
- Smoke tests pass

## Do not

- Commit tokens/keys
- Disable FinanceWorkspaceWatch
