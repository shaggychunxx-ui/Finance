# Status / Handoff â€” Finance

**Last updated:** 2026-08-02 (human: E*TRADE connected; snapshot still stale — BOXONE re-push)
**Updated by:** AI-CODING
**Last updated:** 2026-08-02 (BOXONE ran finish; OAuth re-login still needed)
**Updated by:** AI-CODING
**Active owner:** none
**Act on:** BOXONE

## NOTIFY

- **NOTIFY AI-CODING: 042 partial** — broker role applied on BOXONE; headless worker running; FinanceWorkspaceWatch Ready; share via SFTP (SMB still broken). **account_snapshot still stale** — E*TRADE token expired past midnight ET; human must re-auth on BOXONE (`begin_etrade_login.py` / `finish_etrade_login.py <CODE>`). dry_run ON. gsw task 060 same handoff.

---

## >>> BOXONE — SCRIPT RAN — NEED FRESH E*TRADE TOKEN <<<

**Verified on share (AI-CODING):** BOXONE **did** execute the dual-PC finish path.

| Check | Result |
|-------|--------|
| `BOXONE_BROKER_APPLY_DONE.txt` | **Present** host=BOXONE worker_pid=13536 dry_run=on role=broker |
| `broker_status.json` | **Pushed today** 2026-08-02 |
| `account_snapshot.json` | Still **Jul 30** |
| `etrade_connected` | **False** — marker: token expired past midnight ET |

**LAN note:** AI-CODING can **ping** BOXONE (10.10.10.2) and share is open for BOXONE writes, but **admin WinRM/SSH/SMB admin shares still Access Denied** without a working remote password (stored labctrl has no password blob). BOXONE **did** act via **repo bus + SFTP**.

### Last step on BOXONE (OAuth — human/browser)

```powershell
cd "C:\Users\Box One\Finance"
python begin_etrade_login.py
python finish_etrade_login.py
# restart headless worker, then:
powershell -NoProfile -ExecutionPolicy Bypass -File "\\10.10.10.1\HelperDrop\FinanceShare\BOXONE_FINISH_042_NOW.ps1"
```

Prove `broker\account_snapshot.json` is **today**, then finish tasks 042/060 → **Act on: AI-CODING**.

### Target architecture (Role flip B)

| Machine | Role | Job |
|---------|------|-----|
| **BOXONE** | **broker** | E\*TRADE login (done) + headless worker + publish share `broker/` |
| **AI-CODING** | **pipeline** | Agents/fusion (running; 51/51 repair OK) + pull share broker + publish `pipeline/` |

### AI-CODING already done (this side)

- `deployment.json` **role=pipeline**, consume_shared_quotes on  
- Worker/supervisor/watchdog **up**  
- Pipeline force repair cycle **51/51** agents  
- Pull-broker wired (waiting for **fresh** BOXONE publish)  
- Doc: `DUAL_PC_PIPELINE.md` Â· bus: `BUS-COMMS.md`

### BOXONE â€” one command (preferred)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "\\10.10.10.1\HelperDrop\FinanceShare\BOXONE_FINISH_042_NOW.ps1"
```

Or double-click `BOXONE_FINISH_042_NOW.bat` on the share.

Also assigned on **grok-shared-workspace** (your live watcher): task **060** + **Act on: BOXONE**.

### After script: Finance watcher + handoff

```powershell
cd $env:USERPROFILE\Documents\GitHub\Finance
git pull
powershell -NoProfile -ExecutionPolicy Bypass -File .\install-watcher.ps1
```

Then: 042 â†’ `tasks/done/` + Done line + **NOTIFY AI-CODING** + **Act on: AI-CODING** + push.

### BOXONE publish path ready (SFTP); snapshot waits on OAuth

| Check | Status |
|-------|--------|
| Login on BOXONE | Tokens **expired** past midnight ET (need re-auth) |
| `broker/account_snapshot.json` | Still **Jul 30** |
| Done marker | **Present** (SFTP) |
| **BOXONE** | **broker** | E*TRADE + headless worker + publish `broker/` |
| **AI-CODING** | **pipeline** | Agents/fusion (51/51 OK) + pull broker + publish `pipeline/` |

dry_run ON. Tokens local only.

---

## (earlier) REPO BUS + 042 context

**Human (earlier):** repair communication through repo with box one.

### Bus diagnosis (AI-CODING)

| Issue | Evidence | Fix |
|-------|----------|-----|
| BOXONE never speaks on git | **Zero** commits `auto-sync: â€¦ from BOXONE` in history | BOXONE must `git pull` + `install-watcher.ps1` â†’ task **FinanceWorkspaceWatch** |
| AI-CODING thrashed every 2 min | 145+ idle headless wakes today; log: `Pending task target matches: ALL` | Fixed `watch-and-act.ps1` (markdown `**target:**` parse; inbox address filter; ALL=main only) |
| Inbox noise | Old boxone mails woke every PC | Archived to `inbox/archive/`; one ping left: `inbox/2026-08-02-boxone-bus-comms-repair.md` |
| 042 still open | See verify table below | Still your ops work after bus is alive |

**Read:** `BUS-COMMS.md` (protocol + install).

### BOXONE â€” restore git bus (do first, once)

```powershell
cd $env:USERPROFILE\Documents\GitHub\Finance
git pull
powershell -NoProfile -ExecutionPolicy Bypass -File .\install-watcher.ps1
Get-ScheduledTask -TaskName FinanceWorkspaceWatch | Format-List TaskName, State
```

Proof of life: after a few minutes, GitHub should show activity from BOXONE **or** headless Grok on BOXONE acting on this STATUS (Act on: BOXONE). If watcher missing, AI-CODING can push forever and BOXONE never hears it.

### Then finish 042 (still required)

**Human earlier:** â€œbox one says its done.â€ **AI-CODING verified: NOT DONE** until checks pass.

### Verification (AI-CODING, 2026-08-02 after human report)

| Check | Required | Observed | Pass? |
|-------|----------|----------|-------|
| `BOXONE_BROKER_APPLY_DONE.txt` on share | exists | **MISSING** | NO |
| `broker/account_snapshot.json` | fresh **today** | mtime **2026-07-30**, `fetched_at` Jul 31 UTC | NO |
| `broker/broker_status.json` | fresh **today**, host=BOXONE | `pushed_at` **2026-08-01**, host path `C:\Users\Box One\Finance` (not a BOXONE push today) | NO |
| Task `042` | in `tasks/done/` + Result | still **`tasks/pending/`**, Result empty | NO |
| STATUS Done line from BOXONE | present | **absent** | NO |
| STATUS **Act on: AI-CODING** after report | set by BOXONE | still **Act on: BOXONE** (you never handed off) | NO |
| git push from BOXONE | STATUS/task commit | `git pull` on AI-CODING already up to date â€” **no BOXONE commit** | NO |

**Saying â€œdoneâ€ without these is incomplete.** Finish the real work, then report.

**You are BOXONE. COMPUTERNAME must be BOXONE. Claim: Active owner: BOXONE, then execute. Do not exit idle.**

### Step 1 â€” git pull (this repo)

```
cd %USERPROFILE%\Documents\GitHub\Finance
git pull
```

(or whatever path is the Finance git clone on BOXONE)

### Step 2 â€” apply broker role (on BOXONE machine)

Run **exactly**:

```
powershell -NoProfile -ExecutionPolicy Bypass -File "\\10.10.10.1\HelperDrop\FinanceShare\Apply-Broker-Role-BOXONE.ps1"
```

Backup if share path differs: same script under `C:\Users\Public\HelperDrop\FinanceShare\` if that is your local share mount.

Or double-click: `\\10.10.10.1\HelperDrop\FinanceShare\Apply-Broker-Role-BOXONE.bat`

What the script must do: set local runtime `deployment.json` **role=broker**, shared_root to FinanceShare, practice / **dry_run ON**. **Tokens stay local on BOXONE only** â€” never copy tokens to share or git.

### Step 3 â€” start headless worker only

On BOXONE Finance **runtime** (often `C:\Users\â€¦\Finance` or similar â€” not only the git clone):

1. Start/restart: `Start ETrade Background Service.vbs` **or** `Install ETrade Background.bat`
2. **No** desktop Unified Trader / Short GUI (removed â€” see `ETRADE_HEADLESS.md`)
3. If OAuth expired: `python begin_etrade_login.py` then `python finish_etrade_login.py` (tokens local only)

Confirm a worker process is alive (`etrade_worker.py --service` / heartbeat file updating).

### Step 4 â€” prove share is fresh (todayâ€™s date)

After worker runs a few minutes, these must have **todayâ€™s** timestamps (not Jul 26 / Jul 30 / Aug 1 only):

| Must be FRESH today | Path |
|---------------------|------|
| account snapshot | `\\10.10.10.1\HelperDrop\FinanceShare\broker\account_snapshot.json` |
| broker status | `\\10.10.10.1\HelperDrop\FinanceShare\broker\broker_status.json` |
| done marker | `\\10.10.10.1\HelperDrop\FinanceShare\BOXONE_BROKER_APPLY_DONE.txt` |

If the done marker is missing, create it after apply succeeds (script may write it; if not, write a one-line text file: host + UTC time + dry_run=on). **Do not put secrets in that file.**

### Step 5 â€” report to AI-CODING (required â€” do not skip)

In the **git** Finance repo:

1. Move `tasks/pending/042-boxone-broker-role-flip.md` â†’ `tasks/done/` and fill **Result** (host=BOXONE, dry_run on, share files fresh today).
2. Under **Done** add:
   `- [x] **BOXONE:** task 042 broker role applied; headless worker up; share broker/ fresh.`
3. **Clear** the BOXONE line under **Next**. Leave PHONE **043** under Next.
4. Set **NOTIFY** to:
   `NOTIFY AI-CODING: 042 complete â€” share broker fresh; please ack and leave PHONE 043 for human GitStatus.`
5. Set header:
   - **Active owner:** `none`
   - **Act on:** `AI-CODING`
6. `git add` STATUS + task; `git commit` (subject + Notes body); `git push`

**Incomplete** if you only run the script and go silent. Human requires report-back.

### Do not

- Act on PHONE  
- Put tokens / consumer secrets on the share or in git  
- Start desktop trader UIs  
- Flip live trading / turn dry_run off  
- Exit because â€œAct on was already BOXONEâ€ â€” that means **you** must work  

### More detail on share

- `\\10.10.10.1\HelperDrop\FinanceShare\BOXONE_RUN_THIS.txt`
- `\\10.10.10.1\HelperDrop\FinanceShare\ATTENTION_BOXONE.txt`
- `\\10.10.10.1\HelperDrop\FinanceShare\ROLE_FLIP_B.md`
- Task file: `tasks/pending/042-boxone-broker-role-flip.md`

---

## Current goal

Finance phone bus live: GitStatus Send â†’ STATUS.md â†’ watchers â†’ agents. **Dropshipping** canonical under `dropshipping/`. **Primary trading goal:** raise daily and total average P/L; groups earn role-scaled points per full 1.0% total P/L.

**Role flip B:** BOXONE = **broker** Â· AI-CODING = **pipeline**. Tokens only on BOXONE.

**AI workstation hardware (gsw):** ABS tower + UPS ordered. Finance goals/rules and E\*TRADE P0 always win over workstation cutover. See Notes + gsw `PAYOFF-ROADMAP.md`.

## NOTIFY

- **NOTIFY BOXONE (DUAL-PC PIPELINE GO):** Human wants full dual-PC pipeline. AI-CODING pipeline side ready. **You:** run `BOXONE_FINISH_042_NOW.ps1` + Finance watcher + handoff. Also gsw task **060**. Share still stale until you publish.



## Done

- [x] **AI-CODING (human: E*TRADE account connected):** Checked share — **account_snapshot still Jul-30**; broker_status pushes today. Connection may be local on BOXONE but worker has not refreshed snapshot. Re-armed **Act on: BOXONE** to force cycle + re-push.


- [x] **AI-CODING:** ack BOXONE 042 **partial** — worker/role/marker/SFTP push OK; **account_snapshot still stale** (E*TRADE token expired past midnight ET). Re-arm **Act on: BOXONE** for OAuth re-login only.


- [x] **BOXONE 042 broker role** — role=broker + headless worker + FinanceWorkspaceWatch Ready + SFTP publish path; **snapshot blocked** on E*TRADE midnight token expiry (need human re-login). Report gsw `work/finance-dual-pc/reports/apply-BOXONE-060-latest.md`.

- [x] **AI-CODING (human: dual-PC pipeline with BOXONE):** Armed BOXONE on **Finance** + **gsw** (task 060 â€” BOXONE watcher live there). Pipeline host locked; finish script on share; inbox ping. Waiting BOXONE publish fresh broker/.
- [x] **AI-CODING (human: BOXONE logged into E\*TRADE):** Ack â€” login belongs on BOXONE (Role flip B). Verified share still not refreshed after login (snapshot Jul-30, no done-marker). Re-armed BOXONE with **publish steps** only. AI-CODING stays pipeline (no local OAuth required).
- [x] **AI-CODING (human: repair pipeline):** Force-ran pipeline lanes **critical+quant+flow** on runtime (off-hours; market_hours_only was deferring schedule). Result cycle `20260802T115842Z`: **51/51 agents ok**, 0 failed, predictor ok, ~219s. History no longer stuck on false 0/0 for new runs. Lane stamps refreshed critical/quant/flow; research still next-due. Worker heartbeats healthy (role=pipeline). E\*TRADE OAuth expired on AI-CODING (expected pipeline role) â€” used 281 shared broker quotes. `pipeline_status.json` pushed to share.
- [x] **AI-CODING (human: repair repo communication with BOXONE):** Diagnosed dead dual-PC bus. **Root causes:** (1) zero `from BOXONE` auto-sync ever â†’ BOXONE watcher missing/not on this repo; (2) `**target:**` not parsed â†’ false ALL â†’ AI-CODING headless thrash (100+ idle acts); (3) unaddressed inbox woke everyone. **Fixes:** `watch-and-act.ps1` assignment rules; `BUS-COMMS.md`; inbox archive + one BOXONE ping; task frontmatter plain `target:`; **Act on: BOXONE**. 042 ops still incomplete until share proof + handoff.
- [x] **AI-CODING (human: â€œbox one says its doneâ€):** Verified **042 NOT complete.** Share missing `BOXONE_BROKER_APPLY_DONE.txt`; `broker/account_snapshot.json` still 2026-07-30; no BOXONE Done line / no task move / no git handoff. Re-armed **Act on: BOXONE** with fail table + steps. Do **not** arm PHONE 043 until 042 truly done.
- [x] **AI-CODING (human: repair agent pipeline):** Fixed split-pipeline **false 0/0** history bug. Root cause: post-fusion called `only_agents=[]`, which emptied the agent roster and finalized every cycle as `0/0` (all 500 history rows). Fix: `skip_agent_runs` + lane totals stamped into `finalize_pipeline_cycle`; empty `only_agents` treated as post-steps-only with full catalog kept for memory. Deployed to runtime `C:\Users\Box One\Finance`. Smoke: critical lane **5/5** ok, cycle `20260802T114101Z`, predictor ok. Worker role=pipeline heartbeats healthy; off-hours still defers full multi-lane (market-hours-only) until pre-open/RTH. Code: `strategy_engine.py` + regression in `tests/test_smoke.py`.
- [x] **LAPTOP/gsw (human):** AI workstation **payoff roadmap is Finance-first** â€” recorded on Finance bus. Workstation cutover/payoff must **not** interfere with Finance current goals, rules, Role flip B, or E\*TRADE. Canonical policy: grok-shared-workspace `work/ai-workstation/PAYOFF-ROADMAP.md` (N0 Finance non-interference; RTH hard bans; staged cutover). Hardware order log: gsw `work/ai-workstation/ORDER-2026-08-02.md` (ABS i7-14700F + RTX 5060 + 32GB DDR5; APC BR1500G UPS). **Does not change Act on BOXONE 042.** Does not flip live/dry_run/sandbox.
- [x] **AI-CODING:** Headless E*TRADE â€” removed desktop Trader/Unified/Short GUIs; Finance Agents + background worker only. `phone_bridge` prefers fuller dual-PC share snapshots (quality gate). Docs: `ETRADE_HEADLESS.md`. BOXONE **042** steps updated (worker only, no Unified Trader).
- [x] **AI-CODING:** Full accuracy/ops plan shipped (night backtest, RTH pipeline, learning, abstain, fusion horizon, regime gate, meta-calibrator, pre-open burst, plan rebuild). APK rebuild assigned Oxygen-OS task **062**.

- [x] **AI-CODING (PHONE):** slow constant full backtest from 2000-01-01 Ã¢â‚¬â€ **done / running**.
  - Day-by-day walk-forward; signals only use bars Ã¢â€°Â¤ sim date; predict vs actual (24h/1wk/1mo); restarts at today.
  - Conserves CPU/GPU/mem: BELOW_NORMAL, 1.25s/day, 16 symbols, 20 agents, incremental disk state.
  - Review summary window + `output/history/full_day_backtest_review.txt` before start; live status window.
  - Continuous process on AI-CODING. Task: `tasks/done/041-full-day-backtest-from-2000.md`.
- [x] **AI-CODING (PHONE):** goal increase daily and total average P/L; give group appropriate points for each 1.0% increase in total P/L Ã¢â‚¬â€ **done**.
  - Primary goal flag + `total_pl_pct` / `total_avg_pl_pct` on goal progress.
  - Role-scaled `pl_points_per_pct` on every group; `pl_points_for_total_gain` (full 1% units; daily at 0.5Ãƒâ€”).
  - Agent bonuses + balance_penalties carry `pl_points`; group leaderboard export.
  - Task: `tasks/done/040-group-pl-points-daily-total.md`.
- [x] **AI-CODING (PHONE via gsw):** all dropshipping info in Finance Ã¢â‚¬â€ **done**. Canonical tree `dropshipping/` (README, STORE-STATUS, MISSION, product-research, marketing-plan, shopify-setup-plan, DROPSHIP-STACK, margins/, reports/, notes/). Ops code remains ShopifyDS. See task on grok-shared-workspace `tasks/done/058-dropshipping-info-to-finance-AI-CODING.md`.
- [x] **AI-CODING (PHONE):** agent groups Ã¢â‚¬â€ each group gets a scoring system based on function Ã¢â‚¬â€ **done**.
  - 15 groups each have `scoring` (mode, primary_metric, weighted KPIs, dir/mag blend, score_horizon).
  - Helpers: `agent_scoring_system`, `composite_group_score`, `all_scoring_systems`, report meta stamps.
  - Accuracy blend uses per-group direction/magnitude weights.
  - Task: `tasks/done/038-agent-group-scoring.md`.
- [x] **AI-CODING (PHONE):** what does "Prior pipeline cycle 20260726T180307Z: 0/0 agents succeeded." mean? Ã¢â‚¬â€ **answered**.
  - **Where it comes from:** `agents/pipeline_memory.py` builds `prior_cycle_hint` from the last entry in pipeline-run history and injects it as a `[Memory]` note so later agents know how the previous full cycle went.
  - **Cycle id:** `20260726T180307Z` = one pipeline run stamped **2026-07-26 18:03:07 UTC** (not a clock error).
  - **0/0:** `agents_ok` / `agents_total`. **0 succeeded out of 0 total** means **no agents were in that cycle** (empty roster / not run / recorded with zero count) Ã¢â‚¬â€ **not** Ã¢â‚¬Å“all agents crashed.Ã¢â‚¬Â A real failure run would look like `0/20` or `18/20`.
  - **Why you see it:** harmless context for the next pipeline; only worth investigating if cycles keep logging `0/0` when you expect a full agent batch.
- [x] **AI-CODING (PHONE):** transferred positions = deposits; zero P/L at book-in Ã¢â‚¬â€ **done**. `account_profit.py` ACATS/capital-event detection in git+runtime; bridge zeros open P/L on transfer lots (SPCX+SAGMF + learned). Live: net_flows ~$3.7k, total_pl ~Ã¢Ë†â€™$17.55. See `tasks/done/037-transfer-positions-as-deposits.md`.
- [x] **AI-CODING (PHONE):** stop sending info to etrader UI Ã¢â‚¬â€ **done**. Gated `/api/agents` + idea rows via `phone_ui_info_enabled=false`; emptied `etrade-agents.json` publish path; OAuth/controls/balances still available. Re-enable documented in task Result. See `tasks/done/036-stop-etrader-ui-info.md`.
- [x] **AI-CODING:** Scaffolded Finance phone bus (RULES, AGENTS, tasks/, watch-and-act, install-watcher). Scheduled task **FinanceWorkspaceWatch** on AI-CODING. Phone Send path now has a watcher (was missing).
- [x] **AI-CODING:** Received HUMAN GitStatus **test** Ã¢â‚¬â€ **RECEIPT OK** on **Finance** (AI-CODING, 2026-07-31 04:28).
- [x] **AI-CODING:** GitStatus remote probe `gitstatus-remote-probe-20260731-042147` Ã¢â‚¬â€ **RECEIPT OK**. Public STATUS phone bus fields OK (Act on/Next/Notes).

## Next

- [~] **BOXONE (P0):** 042 applied (role+worker+watcher+SFTP); **blocked** on human E*TRADE re-login for fresh snapshot.
- [ ] **AI-CODING (after BOXONE reports):** Ack **042** once under Done; confirm share freshness; clear NOTIFY; set **Act on: none**; leave PHONE **043** for human GitStatus (never Act on PHONE).
- [ ] **PHONE (GitStatus / OXYGEN):** After **042** Done â€” verify Finance **data connection** in GitStatus: open Finance, refresh STATUS, Send `gitstatus-data-probe-verify-role-B`, then Send `data connection OK` or `FAIL`. Checklist: task **043** + share `OXYGEN_GITSTATUS_VERIFY.md`.
- [ ] **Human (later, off-RTH / non-live):** When ABS tower + UPS arrive â€” follow gsw `PAYOFF-ROADMAP.md` **Finance-first** only. Do **not** stop BOXONE broker / workers for cutover during RTH. Do **not** change Role flip B without a new human decision. Optional: stage new tower as pipeline/bus first; broker stays BOXONE until human says otherwise.



## Blockers

- (none)

## Notes

- **AI workstation + UPS (2026-08-02, gsw â†’ Finance STATUS):** Human ordered ABS Cyclone Aqua (i7-14700F / RTX 5060 / 32GB DDR5) + APC BR1500G. Full payoff/cutover lives in **grok-shared-workspace** `work/ai-workstation/PAYOFF-ROADMAP.md` and `FLEET-INCORPORATE.md`. **Binding here:** (1) Finance primary goal (raise daily/total avg P/L) and all Finance rules **outrank** workstation setup. (2) E\*TRADE / headless worker priority and dual-PC roles stand â€” currently **Role flip B: BOXONE=broker, AI-CODING=pipeline**. (3) No RTH reboot/rename/migrate that kills broker or pipeline for a checklist. (4) No live_trading / dry_run / sandbox flips as part of hardware payoff. (5) UPS unplug tests only when **non-live** / off-RTH. (6) Secrets stay off-git. BOXONE **042** and PHONE **043** remain the active Finance Next path; this note does **not** reassign them.
- **Role flip B (2026-08-01):** BOXONE=broker, AI-CODING=pipeline. Tokens stay on BOXONE only. AI-CODING trading flags off. See ROLE_FLIP_B.md / DUAL_PC_DEPLOYMENT.md.
- **After BOXONE done â€” OXYGEN verify (2026-08-01):** Human uses **GitStatus** (Finance window) to confirm bus/data connection (task **043**). Never `Act on: PHONE`. Probe string: `gitstatus-data-probe-verify-role-B`.
- **Full day backtest (2026-08-01):** Continuous walk-forward from 2000-01-01 on AI-CODING. `python run_full_day_backtest.py` or `Start Full Day Backtest.bat`. Check `output/history/full_day_backtest_state.json` / `.log`. Resumes mid-pass unless `--fresh`.
- **PL points (2026-08-01):** Groups earn points per full 1.0% total trading P/L (deposit-aware). Intraday 12, alpha 10, platform 2. Daily half-weight. See `agent_groups.ROLE_PL_POINTS_PER_PCT` and task **040**.
- **Dropshipping (2026-08-01):** PHONE asked that all dropshipping info live in Finance. Canonical path: `dropshipping/README.md`. ShopifyDS keeps automation/scripts; gsw `work/dropshipping-store/` is a legacy mirror only.
- **Phone bus (2026-07-31):** Finance previously accepted GitStatus writes but had **no watcher** Ã¢â‚¬â€ agents never woke on `Act on: AI-CODING`. Fixed: install `FinanceWorkspaceWatch` (every ~2 min). See `RULES.md` / `AGENTS.md`.
- Runtime trading stack may be `C:\Users\Box One\Finance` (local); this clone is `Documents\GitHub\Finance` (git + phone bus). Do not commit secrets from runtime.
- Standing commit rules (mandatory): subject + body; no secrets. Prefer multi-line `git commit -m subject -m body`.
- **Etrader UI info OFF:** set `phone_ui_info_enabled: true` in runtime `phone_bridge_config.json`, delete `output/phone_ui_info_disabled.flag`, restart bridge to re-enable agents feed.
- Armed for HUMAN GitStatus: Send any message from phone on Finance window Ã¢â€ â€™ AI-CODING should claim and respond.
- Phone reword during rebase said Ã¢â‚¬Å“desktop UIÃ¢â‚¬Â; task **036** was phone etrader UI info gate (agents/analysis). PC trading workers left running.
- **Pipeline 0/0 hint (updated 2026-08-02):** historical 0/0 rows were a **recording bug** in split post-fusion (`only_agents=[]`), not empty rosters. Fixed â€” new cycles should show real `ok/total` (e.g. critical smoke 5/5). Old 0/0 rows remain in history.
- **Group scoring:** each agent group graded by function (alpha vs calibration vs risk vs platform/execution, etc.). Source: `agent_groups.py` `scoring` + `all_scoring_systems()`.

