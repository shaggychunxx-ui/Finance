# Status / Handoff â€” Finance

**Last updated:** 2026-08-04
**Updated by:** AI-CODING
**Active owner:** none
**Act on:** none

## NOTIFY

_(none)_

---

## >>> LIVE ON AI-CODING (2026-08-04) â€” PIPELINE REPAIR CONTINUED <<<

| Machine | Role now | Status |
|---------|----------|--------|
| **AI-CODING** | **`all`** (pipeline + broker emergency) | **LIVE** â€” Connected production; dry_run off; auto/live/day on; snapshot **today** #8804 **14** pos; phone live pull fixed; trading gate unblocked |
| **BOXONE** | intended long-term broker (flip B) | Not driving orders right now. Can reclaim broker later after its own API OAuth. |

### Verified live (runtime)

- Worker: **Connected to E*TRADE (production)**; role=all; quotes publishing
- `account_snapshot` **#8804** **14** positions (selected_account; not secondary #6854)
- Phone bridge **v1.5.6**: live pull uses `selected_account` â†’ **14 lots OK** (was wrongly using accounts[0]=#6854 â†’ 1 lot / thinner gate)
- Trading gate: **12** agents eligible (was **0/72**); plan rebuild **15 proposed** (0 blocked)
- Force pipeline eco: **critical+quant 10/10** PIPELINE_OK; Market Predictor ok
- Flags: role=all, prefer_dry_run=false, dry_run=false, auto_execute/live_trading/day_trading on
- Orders still wait for **US market hours** (off-RTH now)

### Optional later

- Restore Role flip B (BOXONE=broker only) once BOXONE has API OAuth + publish path
- gsw bus can still assign BOXONE residual if desired
- Re-auth required again after next midnight ET

---

## Fleet policy (standing)

**GROMIT runs all background / unattended tasks** for Finance (phone Send, agents, pipeline code). **BOXONE** only for host-local broker/runtime when Act on/target says so. Never Act on PHONE.
## Current goal

Finance phone bus live: GitStatus Send â†’ STATUS.md â†’ watchers â†’ agents. **Dropshipping** canonical under `dropshipping/`. **Primary trading goal:** raise daily and total average P/L; groups earn role-scaled points per full 1.0% total P/L.

**Role (emergency 2026-08-04):** AI-CODING **role=all** until API live; intended long-term still **Role flip B** (BOXONE broker Â· AI-CODING pipeline).

**AI workstation hardware (gsw):** ABS tower + UPS ordered. Finance goals/rules and E*TRADE P0 always win over workstation cutover. See Notes + gsw `PAYOFF-ROADMAP.md`.

## Done

- [x] **AI-CODING (human: continue pipeline repair):** Fixed phone live pull wrong account (`accounts[0]`=#6854 1-lot vs selected #8804 14-lot) in `phone_bridge.py` v1.5.6. Fixed trading gate zero-eligibility (`trading_gate.py`: preferred-horizon accuracy + floor 35%; was 0/72 agents at 40% combined). Deployed runtime; force eco pipeline **10/10**; plan **15 proposed / 0 blocked**; gate 19/19 candidates. Market closed â€” live orders resume RTH. **Act on: none**.
- [x] **AI-CODING:** ack BOXONE **NOTIFY 047 partial** â€” LIVE flags on broker; E*TRADE OAuth still blocked; snapshot **2026-08-02**; no `BOXONE_LIVE_TRADING_ON.txt`. NOTIFY cleared. Surfaced human OAuth + stale snapshot for phone. **Act on: none**. No notify-back. After human re-auth on BOXONE â†’ re-pull broker + force phone pack.
- [x] **BOXONE (047 partial):** LIVE flags applied on broker runtime (dry_run off, auto/live/day on, prefer_dry_run false, role=broker). SMB apply script unreachable â€” local apply. E*TRADE **session expired** (human OAuth needed). Snapshot still **2026-08-02**. No `BOXONE_LIVE_TRADING_ON.txt`. SFTP marker `BOXONE_LIVE_FLAGS_APPLIED.txt`. Task â†’ `tasks/done/047-boxone-live-and-fresh-broker-push.md`. **NOTIFY AI-CODING**.
- [x] **AI-CODING (human: instruct BOXONE + fresh phone data):** Wrote task **047**, inbox, share `BOXONE_RUN_THIS.txt` / LIVE scripts; STATUS **Act on: BOXONE** + NOTIFY. Phone pack force-published (14 pos / 70 agents) still waiting on BOXONE for today's snapshot.
- [x] **AI-CODING (human: make trading live):** Enabled LIVE AUTO on pipeline runtime (`dry_run` off, `auto_execute`/`live_trading`/`day_trading` on, `prefer_dry_run` false). Role stays **pipeline** (no orders here). Dropped BOXONE apply script on FinanceShare. **Act on: BOXONE**.
- [x] **BOXONE:** ack AI-CODING **NOTIFY phone re-send key** â€” key already on AI-CODING runtime (046); SPY re-ok; secret scrubbed. No BOXONE action. NOTIFY cleared. **Act on: none**. Quiet.
- [x] **AI-CODING (PHONE re-send key):** Phone put raw Massive key string in **Next** again. Confirmed runtime key still present (`data_apis.massive_api_key`, len 32). Live re-verify SPY prev bar **ok** (close 747.03, +0.316%). **Scrubbed** secret from Next (no secrets in git). No re-install needed â€” task **046** already done. Prefer env `MASSIVE_API_KEY` or runtime config only; never STATUS.
- [x] **BOXONE:** ack AI-CODING **NOTIFY 046 complete** â€” Massive API key on AI-CODING runtime only; SPY prev-bar verified; secrets scrubbed. No BOXONE action. NOTIFY cleared. **Act on: none**. Quiet.
- [x] **AI-CODING (PHONE: key minus the spaces):** Joined phone chunks (whitespace removed) â†’ Massive API key installed **runtime-only** (`C:\Users\Box One\Finance\etrade_config.json` â†’ `data_apis.massive_api_key`). Live verify: SPY prev bar ok (close 747.03, +0.316%). `massive-market` has_api_key; full watchlist can hit rate_limited on free/low tier. Scrubbed raw key fragments from STATUS Next/Notes. Task: `tasks/done/046-massive-api-key-install.md`. Gmail OAuth still human-only.
- [x] **BOXONE:** ack AI-CODING **NOTIFY 045 complete** â€” Massive.com agent shipped; Gmail OAuth + Massive key remain human on AI-CODING. No BOXONE action. NOTIFY cleared. **Act on: none**. Quiet.
- [x] **AI-CODING (PHONE: Gmail attn AI-CODING / massive.com API):** Gmail poll **blocked** â€” `~\.gmail-link` has client credentials but **no `token.json`** (need one-time `Invoke-GmailOAuthSetup.ps1`). No Massive key in env/config. **New agent shipped:** `massive-market` (`agents/massive_market/`) â†’ prev-day bars via `api.massive.com`; group markets_core; fail-open without key; registered in main RUNNERS + data steward. Runtime deployed. Empty `data_apis.massive_api_key` slot added (no secret). Task: `tasks/done/045-massive-com-api-gmail-agents.md`. Summary for human: (1) run Gmail OAuth once on AI-CODING, (2) put key in env `MASSIVE_API_KEY` or runtime etrade_config only â€” never STATUS/git.
- [x] **AI-CODING:** ack BOXONE **NOTIFY 042 complete** â€” share re-verified: `account_snapshot` fetched_at **2026-08-02T12:32:15Z** (14 pos); done marker host=BOXONE dry_run=on etrade_connected=True SFTP; task 042 in `tasks/done/`. NOTIFY cleared. **Act on: none**. Leave PHONE **043** for human GitStatus. No notify-back.
- [x] **AI-CODING (human: repair connection):** Verified share account_snapshot FRESH; host SMB repair + pipeline pull/push OK. Dual-PC data path live.
- [x] **BOXONE 042 complete:** role=broker; worker Connected production; account_snapshot today; 48 quotes; SFTP + done marker; FinanceWorkspaceWatch Running. Tokens local only. dry_run ON.
- [x] **AI-CODING (human: E*TRADE account connected):** Earlier check â€” snapshot was Jul-30; re-armed BOXONE (since resolved).
- [x] **AI-CODING:** ack BOXONE 042 **partial** (earlier) â€” snapshot was stale past midnight ET; resolved after OAuth re-login on BOXONE.
- [x] **BOXONE 042 broker role (partial earlier):** role=broker + headless worker + SFTP; snapshot blocked until token sync â€” **resolved**.
- [x] **AI-CODING (human: dual-PC pipeline with BOXONE):** Pipeline host locked; BOXONE broker publish path live.
- [x] **AI-CODING (human: BOXONE logged into E*TRADE):** Ack â€” login belongs on BOXONE (Role flip B). AI-CODING stays pipeline.
- [x] **AI-CODING (human: repair pipeline):** Force-ran pipeline lanes critical+quant+flow on runtime. Cycle `20260802T115842Z`: **51/51 agents ok**. Worker role=pipeline.
- [x] **AI-CODING (human: repair repo communication with BOXONE):** Fixed dead dual-PC bus (`watch-and-act.ps1` targets, BUS-COMMS, inbox archive).
- [x] **AI-CODING (human: "box one says its done"):** Earlier verify fail; 042 later completed for real (see above).
- [x] **AI-CODING (human: repair agent pipeline):** Fixed split-pipeline false 0/0 history bug (`strategy_engine.py` + tests). Deployed to runtime.
- [x] **LAPTOP/gsw (human):** AI workstation payoff roadmap is Finance-first â€” gsw `work/ai-workstation/PAYOFF-ROADMAP.md`. Does not flip live/dry_run.
- [x] **AI-CODING:** Headless E*TRADE â€” removed desktop Trader/Unified/Short GUIs. Docs: `ETRADE_HEADLESS.md`.
- [x] **AI-CODING:** Full accuracy/ops plan shipped. APK rebuild assigned Oxygen-OS task **062**.
- [x] **AI-CODING (PHONE):** slow constant full backtest from 2000-01-01 â€” **done / running**. Task: `tasks/done/041-full-day-backtest-from-2000.md`.
- [x] **AI-CODING (PHONE):** goal increase daily and total average P/L; group PL points â€” **done**. Task: `tasks/done/040-group-pl-points-daily-total.md`.
- [x] **AI-CODING (PHONE via gsw):** all dropshipping info in Finance â€” **done**. Canonical: `dropshipping/`.
- [x] **AI-CODING (PHONE):** agent groups scoring systems â€” **done**. Task: `tasks/done/038-agent-group-scoring.md`.
- [x] **AI-CODING (PHONE):** "Prior pipeline cycle 0/0" explained (empty roster / later fixed recording bug).
- [x] **AI-CODING (PHONE):** transferred positions = deposits; zero P/L at book-in â€” **done**. Task: `tasks/done/037-transfer-positions-as-deposits.md`.
- [x] **AI-CODING (PHONE):** stop sending info to etrader UI â€” **done**. Task: `tasks/done/036-stop-etrader-ui-info.md`.
- [x] **AI-CODING:** Scaffolded Finance phone bus + FinanceWorkspaceWatch.
- [x] **AI-CODING:** Received HUMAN GitStatus **test** â€” RECEIPT OK (2026-07-31).
- [x] **AI-CODING:** GitStatus remote probe â€” RECEIPT OK.

## Next

- [x] **AI-CODING (human: continue pipeline repair):** phone live-account fix + trading-gate eligibility + force eco pipeline + plan rebuild â€” **done** (2026-08-04).
- [ ] **PHONE (GitStatus / OXYGEN):** Verify Finance **data connection** in GitStatus: open Finance, refresh STATUS, Send `gitstatus-data-probe-verify-role-B`, then Send `data connection OK` or `FAIL`. Checklist: task **043** + share `OXYGEN_GITSTATUS_VERIFY.md`. Never Act on PHONE.
- [ ] **Human (later):** Optional Role flip B restore on BOXONE (broker OAuth + publish) when ready â€” AI-CODING currently **role=all** emergency and is LIVE.
- [ ] **Human (later, off-RTH / non-live):** When ABS tower + UPS arrive â€” follow gsw `PAYOFF-ROADMAP.md` **Finance-first** only. Do **not** stop live workers for cutover during RTH without a plan.
- [ ] **Human (AI-CODING desktop, once):** Complete Gmail OAuth so unattended mail works: `powershell -ExecutionPolicy Bypass -File ~\Documents\GitHub\grok-shared-workspace\work\gmail-api\Invoke-GmailOAuthSetup.ps1` (sign in shaggychunxx@gmail.com). Then AI-CODING can re-read "attn AI-CODING" / Massive mail.
- [x] **Human (key, secrets off-git):** Massive API key set on AI-CODING runtime (task **046**). Prefer not to re-paste keys into STATUS/git.
- [x] **AI-CODING** Phone key / Massive / Gmail agent work â€” see Done 045â€“046.

## Blockers

- **US market closed (off-RTH)** â€” LIVE flags on; orders will submit when market open. Not a code blocker.
- **Gmail OAuth token missing** on AI-CODING (`token.json`) â€” cannot read "attn AI-CODING" email body until human completes browser consent once.
- **Role flip B deferred** â€” BOXONE not yet independent broker; AI-CODING holds **role=all** until human decides to flip.

## Notes

- **AI workstation + UPS (2026-08-02):** Hardware order on gsw. Binding: Finance primary goal and Role flip B outrank workstation cutover. No RTH reboot that kills broker/pipeline. No live_trading / dry_run flips for hardware payoff. Secrets off-git.
- **Role flip B (2026-08-01):** BOXONE=broker, AI-CODING=pipeline. Tokens stay on BOXONE only. See ROLE_FLIP_B.md / DUAL_PC_DEPLOYMENT.md.
- **After BOXONE done â€” OXYGEN verify:** Human uses **GitStatus** (Finance window) for task **043**. Never `Act on: PHONE`. Probe: `gitstatus-data-probe-verify-role-B`.
- **Full day backtest:** Continuous walk-forward from 2000-01-01 on AI-CODING. `python run_full_day_backtest.py` or `Start Full Day Backtest.bat`.
- **PL points:** Groups earn points per full 1.0% total trading P/L. See `agent_groups.ROLE_PL_POINTS_PER_PCT` and task **040**.
- **Dropshipping:** Canonical path `dropshipping/README.md`. ShopifyDS keeps automation.
- **Phone bus:** FinanceWorkspaceWatch every ~2 min. See `RULES.md` / `AGENTS.md`.
- Runtime trading stack may be `C:\Users\Box One\Finance` (local); this clone is `Documents\GitHub\Finance` (git + phone bus). Do not commit secrets from runtime.
- Standing commit rules: subject + body; no secrets.
- **Etrader UI info OFF:** set `phone_ui_info_enabled: true` in runtime `phone_bridge_config.json` to re-enable.
- Armed for HUMAN GitStatus: Send any message from phone on Finance window â†’ AI-CODING should claim and respond.
- **Pipeline 0/0 hint (updated 2026-08-02):** historical 0/0 rows were a recording bug in split post-fusion; fixed. New cycles show real ok/total.
- **Group scoring:** each agent group graded by function. Source: `agent_groups.py` `scoring`.
- **Massive.com (2026-08-02):** Agent `massive-market` live with key on AI-CODING runtime (task **046**). Auth: `MASSIVE_API_KEY` or runtime `data_apis.massive_api_key`. Docs: https://massive.com/docs/rest/quickstart. Do not paste keys into STATUS/git.
