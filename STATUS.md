# Status / Handoff â€” Finance

**Last updated:** 2026-08-02 (pipeline repair + BOXONE 042 still open)
**Updated by:** AI-CODING
**Active owner:** none
**Act on:** BOXONE

## Current goal

Finance phone bus live: GitStatus Send → STATUS.md → FinanceWorkspaceWatch → headless Grok on AI-CODING. **Dropshipping business info** is canonical under `dropshipping/`. **Primary trading goal:** increase daily and total average P/L; groups earn role-scaled points per full 1.0% total P/L.

**AI workstation hardware (gsw bus — does not override Finance):** New ABS tower + UPS ordered (gsw `work/ai-workstation/`). **Finance goals/rules and E\*TRADE P0 always win** over workstation payoff/cutover. See Notes + gsw `PAYOFF-ROADMAP.md`.

## NOTIFY

- **NOTIFY BOXONE (FINISH 042 — then report to AI-CODING):** Human: work as a team. AI-CODING verified **042 incomplete** — no `BOXONE_BROKER_APPLY_DONE.txt`, share `broker/account_snapshot` still ~Jul 30, STATUS never closed by BOXONE. **BOXONE: finish the job end-to-end, then inform AI-CODING.**

  **A) Do the work (on BOXONE runtime):**
  ```
  powershell -NoProfile -ExecutionPolicy Bypass -File "\\10.10.10.1\HelperDrop\FinanceShare\Apply-Broker-Role-BOXONE.ps1"
  ```
  Or: `\\10.10.10.1\HelperDrop\FinanceShare\Apply-Broker-Role-BOXONE.bat`  
  Then start/restart **headless background worker only** (`Start ETrade Background Service.vbs` / `Install ETrade Background.bat`). No desktop Unified Trader. practice/dry_run **ON**. Tokens stay **local** on BOXONE.  
  Confirm share files are **fresh** (new timestamps today):
  - `\\10.10.10.1\HelperDrop\FinanceShare\broker\account_snapshot.json`
  - `\\10.10.10.1\HelperDrop\FinanceShare\broker\broker_status.json`  
  Done marker should exist: `\\10.10.10.1\HelperDrop\FinanceShare\BOXONE_BROKER_APPLY_DONE.txt`

  **B) Report complete to AI-CODING (required — this is the handoff):**
  1. Move task **042** → `tasks/done/` with a short **Result** (host, dry_run on, share fresh).
  2. STATUS **Done** line: `- [x] **BOXONE:** task 042 broker role applied; headless worker up; share broker/ fresh.`
  3. Clear the BOXONE **Next** item. Keep PHONE **043** under Next.
  4. Set **NOTIFY:** `NOTIFY AI-CODING: 042 complete — share broker fresh; please ack and leave PHONE 043 for human GitStatus.`
  5. Set **Act on: AI-CODING** (so AI-CODING wakes, acks once, then sets Act on: none for phone verify).
  6. **git commit + push** STATUS/task (or auto-sync). Do **not** go silent after only running the script.
  7. Do **not** Act on PHONE. Do **not** put tokens on the share.

  Full checklist on share: `\\10.10.10.1\HelperDrop\FinanceShare\BOXONE_RUN_THIS.txt` · `ATTENTION_BOXONE.txt`



## Done

- [x] **AI-CODING (human: repair agent pipeline):** Fixed split-pipeline **false 0/0** history bug. Root cause: post-fusion called `only_agents=[]`, which emptied the agent roster and finalized every cycle as `0/0` (all 500 history rows). Fix: `skip_agent_runs` + lane totals stamped into `finalize_pipeline_cycle`; empty `only_agents` treated as post-steps-only with full catalog kept for memory. Deployed to runtime `C:\Users\Box One\Finance`. Smoke: critical lane **5/5** ok, cycle `20260802T114101Z`, predictor ok. Worker role=pipeline heartbeats healthy; off-hours still defers full multi-lane (market-hours-only) until pre-open/RTH. Code: `strategy_engine.py` + regression in `tests/test_smoke.py`.
- [x] **LAPTOP/gsw (human):** AI workstation **payoff roadmap is Finance-first** — recorded on Finance bus. Workstation cutover/payoff must **not** interfere with Finance current goals, rules, Role flip B, or E\*TRADE. Canonical policy: grok-shared-workspace `work/ai-workstation/PAYOFF-ROADMAP.md` (N0 Finance non-interference; RTH hard bans; staged cutover). Hardware order log: gsw `work/ai-workstation/ORDER-2026-08-02.md` (ABS i7-14700F + RTX 5060 + 32GB DDR5; APC BR1500G UPS). **Does not change Act on BOXONE 042.** Does not flip live/dry_run/sandbox.
- [x] **AI-CODING:** Headless E*TRADE — removed desktop Trader/Unified/Short GUIs; Finance Agents + background worker only. `phone_bridge` prefers fuller dual-PC share snapshots (quality gate). Docs: `ETRADE_HEADLESS.md`. BOXONE **042** steps updated (worker only, no Unified Trader).
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

- [ ] **BOXONE:** **Finish task 042 completely** (apply + headless worker + fresh share `broker/`), then **report to AI-CODING** via STATUS Done + `NOTIFY AI-CODING` + **Act on: AI-CODING** + git push. See NOTIFY above. Incomplete = missing done-marker or stale Jul-30 snapshot.
- [ ] **AI-CODING (after BOXONE reports):** Ack **042** once under Done; confirm share freshness; clear NOTIFY; set **Act on: none**; leave PHONE **043** for human GitStatus (never Act on PHONE).
- [ ] **PHONE (GitStatus / OXYGEN):** After **042** Done — verify Finance **data connection** in GitStatus: open Finance, refresh STATUS, Send `gitstatus-data-probe-verify-role-B`, then Send `data connection OK` or `FAIL`. Checklist: task **043** + share `OXYGEN_GITSTATUS_VERIFY.md`.
- [ ] **Human (later, off-RTH / non-live):** When ABS tower + UPS arrive — follow gsw `PAYOFF-ROADMAP.md` **Finance-first** only. Do **not** stop BOXONE broker / workers for cutover during RTH. Do **not** change Role flip B without a new human decision. Optional: stage new tower as pipeline/bus first; broker stays BOXONE until human says otherwise.



## Blockers

- (none)

## Notes

- **AI workstation + UPS (2026-08-02, gsw → Finance STATUS):** Human ordered ABS Cyclone Aqua (i7-14700F / RTX 5060 / 32GB DDR5) + APC BR1500G. Full payoff/cutover lives in **grok-shared-workspace** `work/ai-workstation/PAYOFF-ROADMAP.md` and `FLEET-INCORPORATE.md`. **Binding here:** (1) Finance primary goal (raise daily/total avg P/L) and all Finance rules **outrank** workstation setup. (2) E\*TRADE / headless worker priority and dual-PC roles stand — currently **Role flip B: BOXONE=broker, AI-CODING=pipeline**. (3) No RTH reboot/rename/migrate that kills broker or pipeline for a checklist. (4) No live_trading / dry_run / sandbox flips as part of hardware payoff. (5) UPS unplug tests only when **non-live** / off-RTH. (6) Secrets stay off-git. BOXONE **042** and PHONE **043** remain the active Finance Next path; this note does **not** reassign them.
- **Role flip B (2026-08-01):** BOXONE=broker, AI-CODING=pipeline. Tokens stay on BOXONE only. AI-CODING trading flags off. See ROLE_FLIP_B.md / DUAL_PC_DEPLOYMENT.md.
- **After BOXONE done — OXYGEN verify (2026-08-01):** Human uses **GitStatus** (Finance window) to confirm bus/data connection (task **043**). Never `Act on: PHONE`. Probe string: `gitstatus-data-probe-verify-role-B`.
- **Full day backtest (2026-08-01):** Continuous walk-forward from 2000-01-01 on AI-CODING. `python run_full_day_backtest.py` or `Start Full Day Backtest.bat`. Check `output/history/full_day_backtest_state.json` / `.log`. Resumes mid-pass unless `--fresh`.
- **PL points (2026-08-01):** Groups earn points per full 1.0% total trading P/L (deposit-aware). Intraday 12, alpha 10, platform 2. Daily half-weight. See `agent_groups.ROLE_PL_POINTS_PER_PCT` and task **040**.
- **Dropshipping (2026-08-01):** PHONE asked that all dropshipping info live in Finance. Canonical path: `dropshipping/README.md`. ShopifyDS keeps automation/scripts; gsw `work/dropshipping-store/` is a legacy mirror only.
- **Phone bus (2026-07-31):** Finance previously accepted GitStatus writes but had **no watcher** â€” agents never woke on `Act on: AI-CODING`. Fixed: install `FinanceWorkspaceWatch` (every ~2 min). See `RULES.md` / `AGENTS.md`.
- Runtime trading stack may be `C:\Users\Box One\Finance` (local); this clone is `Documents\GitHub\Finance` (git + phone bus). Do not commit secrets from runtime.
- Standing commit rules (mandatory): subject + body; no secrets. Prefer multi-line `git commit -m subject -m body`.
- **Etrader UI info OFF:** set `phone_ui_info_enabled: true` in runtime `phone_bridge_config.json`, delete `output/phone_ui_info_disabled.flag`, restart bridge to re-enable agents feed.
- Armed for HUMAN GitStatus: Send any message from phone on Finance window â†’ AI-CODING should claim and respond.
- Phone reword during rebase said â€œdesktop UIâ€; task **036** was phone etrader UI info gate (agents/analysis). PC trading workers left running.
- **Pipeline 0/0 hint (updated 2026-08-02):** historical 0/0 rows were a **recording bug** in split post-fusion (`only_agents=[]`), not empty rosters. Fixed — new cycles should show real `ok/total` (e.g. critical smoke 5/5). Old 0/0 rows remain in history.
- **Group scoring:** each agent group graded by function (alpha vs calibration vs risk vs platform/execution, etc.). Source: `agent_groups.py` `scoring` + `all_scoring_systems()`.

