# Status / Handoff â€” Finance

**Last updated:** 2026-08-01
**Updated by:** AI-CODING
**Active owner:** none
**Act on:** none

## Current goal

Finance phone bus live: GitStatus Send â†’ STATUS.md â†’ FinanceWorkspaceWatch â†’ headless Grok on AI-CODING. **Dropshipping business info** is canonical under `dropshipping/`. **Primary trading goal:** increase daily and total average P/L; groups earn role-scaled points per full 1.0% total P/L.

## NOTIFY

- **NOTIFY BOXONE:** AI-CODING started PHONE full day walk-forward backtest (from 2000-01-01, no look-ahead, day-by-day, loops). Task `tasks/done/041-full-day-backtest-from-2000.md`. Engine: `run_full_day_backtest.py` + `Start Full Day Backtest.bat`. State/report under `output/history/full_day_backtest_*`. Review window/notepad opened on AI-CODING. Ack once, set Act on: none â€” no ping-pong.

## Done

- [x] **AI-CODING:** Full accuracy/ops plan shipped (night backtest, RTH pipeline, learning, abstain, fusion horizon, regime gate, meta-calibrator, pre-open burst, plan rebuild). APK rebuild assigned Oxygen-OS task **062**.

- [x] **AI-CODING (PHONE):** slow constant full backtest from 2000-01-01 â€” **done / running**.
  - Day-by-day walk-forward; signals only use bars â‰¤ sim date; predict vs actual (24h/1wk/1mo); restarts at today.
  - Conserves CPU/GPU/mem: BELOW_NORMAL, 1.25s/day, 16 symbols, 20 agents, incremental disk state.
  - Review summary window + `output/history/full_day_backtest_review.txt` before start; live status window.
  - Continuous process on AI-CODING. Task: `tasks/done/041-full-day-backtest-from-2000.md`.
- [x] **AI-CODING (PHONE):** goal increase daily and total average P/L; give group appropriate points for each 1.0% increase in total P/L â€” **done**.
  - Primary goal flag + `total_pl_pct` / `total_avg_pl_pct` on goal progress.
  - Role-scaled `pl_points_per_pct` on every group; `pl_points_for_total_gain` (full 1% units; daily at 0.5Ã—).
  - Agent bonuses + balance_penalties carry `pl_points`; group leaderboard export.
  - Task: `tasks/done/040-group-pl-points-daily-total.md`.
- [x] **AI-CODING (PHONE via gsw):** all dropshipping info in Finance â€” **done**. Canonical tree `dropshipping/` (README, STORE-STATUS, MISSION, product-research, marketing-plan, shopify-setup-plan, DROPSHIP-STACK, margins/, reports/, notes/). Ops code remains ShopifyDS. See task on grok-shared-workspace `tasks/done/058-dropshipping-info-to-finance-AI-CODING.md`.
- [x] **AI-CODING (PHONE):** agent groups â€” each group gets a scoring system based on function â€” **done**.
  - 15 groups each have `scoring` (mode, primary_metric, weighted KPIs, dir/mag blend, score_horizon).
  - Helpers: `agent_scoring_system`, `composite_group_score`, `all_scoring_systems`, report meta stamps.
  - Accuracy blend uses per-group direction/magnitude weights.
  - Task: `tasks/done/038-agent-group-scoring.md`.
- [x] **AI-CODING (PHONE):** what does "Prior pipeline cycle 20260726T180307Z: 0/0 agents succeeded." mean? â€” **answered**.
  - **Where it comes from:** `agents/pipeline_memory.py` builds `prior_cycle_hint` from the last entry in pipeline-run history and injects it as a `[Memory]` note so later agents know how the previous full cycle went.
  - **Cycle id:** `20260726T180307Z` = one pipeline run stamped **2026-07-26 18:03:07 UTC** (not a clock error).
  - **0/0:** `agents_ok` / `agents_total`. **0 succeeded out of 0 total** means **no agents were in that cycle** (empty roster / not run / recorded with zero count) â€” **not** â€œall agents crashed.â€ A real failure run would look like `0/20` or `18/20`.
  - **Why you see it:** harmless context for the next pipeline; only worth investigating if cycles keep logging `0/0` when you expect a full agent batch.
- [x] **AI-CODING (PHONE):** transferred positions = deposits; zero P/L at book-in â€” **done**. `account_profit.py` ACATS/capital-event detection in git+runtime; bridge zeros open P/L on transfer lots (SPCX+SAGMF + learned). Live: net_flows ~$3.7k, total_pl ~âˆ’$17.55. See `tasks/done/037-transfer-positions-as-deposits.md`.
- [x] **AI-CODING (PHONE):** stop sending info to etrader UI â€” **done**. Gated `/api/agents` + idea rows via `phone_ui_info_enabled=false`; emptied `etrade-agents.json` publish path; OAuth/controls/balances still available. Re-enable documented in task Result. See `tasks/done/036-stop-etrader-ui-info.md`.
- [x] **AI-CODING:** Scaffolded Finance phone bus (RULES, AGENTS, tasks/, watch-and-act, install-watcher). Scheduled task **FinanceWorkspaceWatch** on AI-CODING. Phone Send path now has a watcher (was missing).
- [x] **AI-CODING:** Received HUMAN GitStatus **test** â€” **RECEIPT OK** on **Finance** (AI-CODING, 2026-07-31 04:28).
- [x] **AI-CODING:** GitStatus remote probe `gitstatus-remote-probe-20260731-042147` â€” **RECEIPT OK**. Public STATUS phone bus fields OK (Act on/Next/Notes).

## Next

- (none)

## Blockers

- (none)

## Notes

- **Full day backtest (2026-08-01):** Continuous walk-forward from 2000-01-01 on AI-CODING. `python run_full_day_backtest.py` or `Start Full Day Backtest.bat`. Check `output/history/full_day_backtest_state.json` / `.log`. Resumes mid-pass unless `--fresh`.
- **PL points (2026-08-01):** Groups earn points per full 1.0% total trading P/L (deposit-aware). Intraday 12, alpha 10, platform 2. Daily half-weight. See `agent_groups.ROLE_PL_POINTS_PER_PCT` and task **040**.
- **Dropshipping (2026-08-01):** PHONE asked that all dropshipping info live in Finance. Canonical path: `dropshipping/README.md`. ShopifyDS keeps automation/scripts; gsw `work/dropshipping-store/` is a legacy mirror only.
- **Phone bus (2026-07-31):** Finance previously accepted GitStatus writes but had **no watcher** â€” agents never woke on `Act on: AI-CODING`. Fixed: install `FinanceWorkspaceWatch` (every ~2 min). See `RULES.md` / `AGENTS.md`.
- Runtime trading stack may be `C:\Users\Box One\Finance` (local); this clone is `Documents\GitHub\Finance` (git + phone bus). Do not commit secrets from runtime.
- Standing commit rules (mandatory): subject + body; no secrets. Prefer multi-line `git commit -m subject -m body`.
- **Etrader UI info OFF:** set `phone_ui_info_enabled: true` in runtime `phone_bridge_config.json`, delete `output/phone_ui_info_disabled.flag`, restart bridge to re-enable agents feed.
- Armed for HUMAN GitStatus: Send any message from phone on Finance window â†’ AI-CODING should claim and respond.
- Phone reword during rebase said â€œdesktop UIâ€; task **036** was phone etrader UI info gate (agents/analysis). PC trading workers left running.
- **Pipeline 0/0 hint:** string from last `record_pipeline_run` / memory bundle; `0/0` = empty agent count that cycle, not mass agent failure.
- **Group scoring:** each agent group graded by function (alpha vs calibration vs risk vs platform/execution, etc.). Source: `agent_groups.py` `scoring` + `all_scoring_systems()`.

