# Status / Handoff — Finance

**Last updated:** 2026-08-02
**Updated by:** BOXONE
**Active owner:** none
**Act on:** none

## NOTIFY

(none)

---

## >>> ROLE FLIP B LIVE — 042 ACKED <<<

| Machine | Role | Status |
|---------|------|--------|
| **BOXONE** | **broker** | Live: headless worker + SFTP publish `broker/` (tokens local only) |
| **AI-CODING** | **pipeline** | Live: consume_shared_quotes; agents/fusion; publish `pipeline/` |

### AI-CODING ack (2026-08-02) — share re-verified

| Check | Result |
|-------|--------|
| `BOXONE_BROKER_APPLY_DONE.txt` | Present — host=BOXONE role=broker dry_run=on snapshot_today=True etrade_connected=True share_transport=sftp |
| `broker/account_snapshot.json` | **Fresh** fetched_at **2026-08-02T12:32:15Z** (14 positions) |
| `broker/broker_status.json` | **Pushed today** 2026-08-02 |
| Task 042 | `tasks/done/042-boxone-broker-role-flip.md` Result filled |
| dry_run | ON |

**Next for human:** PHONE **043** GitStatus data-connection verify (never Act on PHONE). Docs: `DUAL_PC_PIPELINE.md` · `BUS-COMMS.md` · `ROLE_FLIP_B.md`.

---

## Current goal

Finance phone bus live: GitStatus Send → STATUS.md → watchers → agents. **Dropshipping** canonical under `dropshipping/`. **Primary trading goal:** raise daily and total average P/L; groups earn role-scaled points per full 1.0% total P/L.

**Role flip B:** BOXONE = **broker** · AI-CODING = **pipeline**. Tokens only on BOXONE.

**AI workstation hardware (gsw):** ABS tower + UPS ordered. Finance goals/rules and E*TRADE P0 always win over workstation cutover. See Notes + gsw `PAYOFF-ROADMAP.md`.

## Done

- [x] **BOXONE:** ack AI-CODING **NOTIFY 046 complete** — Massive API key on AI-CODING runtime only; SPY prev-bar verified; secrets scrubbed. No BOXONE action. NOTIFY cleared. **Act on: none**. Quiet.
- [x] **AI-CODING (PHONE: key minus the spaces):** Joined phone chunks (whitespace removed) → Massive API key installed **runtime-only** (`C:\Users\Box One\Finance\etrade_config.json` → `data_apis.massive_api_key`). Live verify: SPY prev bar ok (close 747.03, +0.316%). `massive-market` has_api_key; full watchlist can hit rate_limited on free/low tier. Scrubbed raw key fragments from STATUS Next/Notes. Task: `tasks/done/046-massive-api-key-install.md`. Gmail OAuth still human-only.
- [x] **BOXONE:** ack AI-CODING **NOTIFY 045 complete** — Massive.com agent shipped; Gmail OAuth + Massive key remain human on AI-CODING. No BOXONE action. NOTIFY cleared. **Act on: none**. Quiet.
- [x] **AI-CODING (PHONE: Gmail attn AI-CODING / massive.com API):** Gmail poll **blocked** — `~\.gmail-link` has client credentials but **no `token.json`** (need one-time `Invoke-GmailOAuthSetup.ps1`). No Massive key in env/config. **New agent shipped:** `massive-market` (`agents/massive_market/`) → prev-day bars via `api.massive.com`; group markets_core; fail-open without key; registered in main RUNNERS + data steward. Runtime deployed. Empty `data_apis.massive_api_key` slot added (no secret). Task: `tasks/done/045-massive-com-api-gmail-agents.md`. Summary for human: (1) run Gmail OAuth once on AI-CODING, (2) put key in env `MASSIVE_API_KEY` or runtime etrade_config only — never STATUS/git.
- [x] **AI-CODING:** ack BOXONE **NOTIFY 042 complete** — share re-verified: `account_snapshot` fetched_at **2026-08-02T12:32:15Z** (14 pos); done marker host=BOXONE dry_run=on etrade_connected=True SFTP; task 042 in `tasks/done/`. NOTIFY cleared. **Act on: none**. Leave PHONE **043** for human GitStatus. No notify-back.
- [x] **AI-CODING (human: repair connection):** Verified share account_snapshot FRESH; host SMB repair + pipeline pull/push OK. Dual-PC data path live.
- [x] **BOXONE 042 complete:** role=broker; worker Connected production; account_snapshot today; 48 quotes; SFTP + done marker; FinanceWorkspaceWatch Running. Tokens local only. dry_run ON.
- [x] **AI-CODING (human: E*TRADE account connected):** Earlier check — snapshot was Jul-30; re-armed BOXONE (since resolved).
- [x] **AI-CODING:** ack BOXONE 042 **partial** (earlier) — snapshot was stale past midnight ET; resolved after OAuth re-login on BOXONE.
- [x] **BOXONE 042 broker role (partial earlier):** role=broker + headless worker + SFTP; snapshot blocked until token sync — **resolved**.
- [x] **AI-CODING (human: dual-PC pipeline with BOXONE):** Pipeline host locked; BOXONE broker publish path live.
- [x] **AI-CODING (human: BOXONE logged into E*TRADE):** Ack — login belongs on BOXONE (Role flip B). AI-CODING stays pipeline.
- [x] **AI-CODING (human: repair pipeline):** Force-ran pipeline lanes critical+quant+flow on runtime. Cycle `20260802T115842Z`: **51/51 agents ok**. Worker role=pipeline.
- [x] **AI-CODING (human: repair repo communication with BOXONE):** Fixed dead dual-PC bus (`watch-and-act.ps1` targets, BUS-COMMS, inbox archive).
- [x] **AI-CODING (human: "box one says its done"):** Earlier verify fail; 042 later completed for real (see above).
- [x] **AI-CODING (human: repair agent pipeline):** Fixed split-pipeline false 0/0 history bug (`strategy_engine.py` + tests). Deployed to runtime.
- [x] **LAPTOP/gsw (human):** AI workstation payoff roadmap is Finance-first — gsw `work/ai-workstation/PAYOFF-ROADMAP.md`. Does not flip live/dry_run.
- [x] **AI-CODING:** Headless E*TRADE — removed desktop Trader/Unified/Short GUIs. Docs: `ETRADE_HEADLESS.md`.
- [x] **AI-CODING:** Full accuracy/ops plan shipped. APK rebuild assigned Oxygen-OS task **062**.
- [x] **AI-CODING (PHONE):** slow constant full backtest from 2000-01-01 — **done / running**. Task: `tasks/done/041-full-day-backtest-from-2000.md`.
- [x] **AI-CODING (PHONE):** goal increase daily and total average P/L; group PL points — **done**. Task: `tasks/done/040-group-pl-points-daily-total.md`.
- [x] **AI-CODING (PHONE via gsw):** all dropshipping info in Finance — **done**. Canonical: `dropshipping/`.
- [x] **AI-CODING (PHONE):** agent groups scoring systems — **done**. Task: `tasks/done/038-agent-group-scoring.md`.
- [x] **AI-CODING (PHONE):** "Prior pipeline cycle 0/0" explained (empty roster / later fixed recording bug).
- [x] **AI-CODING (PHONE):** transferred positions = deposits; zero P/L at book-in — **done**. Task: `tasks/done/037-transfer-positions-as-deposits.md`.
- [x] **AI-CODING (PHONE):** stop sending info to etrader UI — **done**. Task: `tasks/done/036-stop-etrader-ui-info.md`.
- [x] **AI-CODING:** Scaffolded Finance phone bus + FinanceWorkspaceWatch.
- [x] **AI-CODING:** Received HUMAN GitStatus **test** — RECEIPT OK (2026-07-31).
- [x] **AI-CODING:** GitStatus remote probe — RECEIPT OK.

## Next

- [x] **BOXONE (P0):** 042 complete — broker live; snapshot fresh today; SFTP published.
- [x] **AI-CODING:** Ack 042 once; confirm share freshness; clear NOTIFY; Act on none; leave PHONE 043.
- [ ] **PHONE (GitStatus / OXYGEN):** Verify Finance **data connection** in GitStatus: open Finance, refresh STATUS, Send `gitstatus-data-probe-verify-role-B`, then Send `data connection OK` or `FAIL`. Checklist: task **043** + share `OXYGEN_GITSTATUS_VERIFY.md`. Never Act on PHONE.
- [ ] **Human (later, off-RTH / non-live):** When ABS tower + UPS arrive — follow gsw `PAYOFF-ROADMAP.md` **Finance-first** only. Do **not** stop BOXONE broker / workers for cutover during RTH. Do **not** change Role flip B without a new human decision.
- [ ] **Human (AI-CODING desktop, once):** Complete Gmail OAuth so unattended mail works: `powershell -ExecutionPolicy Bypass -File ~\Documents\GitHub\grok-shared-workspace\work\gmail-api\Invoke-GmailOAuthSetup.ps1` (sign in shaggychunxx@gmail.com). Then AI-CODING can re-read "attn AI-CODING" / Massive mail.
- [x] **Human (key, secrets off-git):** Massive API key set on AI-CODING runtime (task **046**). Prefer not to re-paste keys into STATUS/git.
- [x] **AI-CODING** Check Gmail for email "attn AI-CODING" api for massive.com. make new agents if needed. answer back with summary of actions taken — **done (partial)**; see Done 045.
- [x] **AI-CODING** Phone key "minus the spaces" → installed runtime-only + live SPY verify — **done**. Task **046**.

## Blockers

- **Gmail OAuth token missing** on AI-CODING (`token.json`) — cannot read "attn AI-CODING" email body until human completes browser consent once.

## Notes

- **AI workstation + UPS (2026-08-02):** Hardware order on gsw. Binding: Finance primary goal and Role flip B outrank workstation cutover. No RTH reboot that kills broker/pipeline. No live_trading / dry_run flips for hardware payoff. Secrets off-git.
- **Role flip B (2026-08-01):** BOXONE=broker, AI-CODING=pipeline. Tokens stay on BOXONE only. See ROLE_FLIP_B.md / DUAL_PC_DEPLOYMENT.md.
- **After BOXONE done — OXYGEN verify:** Human uses **GitStatus** (Finance window) for task **043**. Never `Act on: PHONE`. Probe: `gitstatus-data-probe-verify-role-B`.
- **Full day backtest:** Continuous walk-forward from 2000-01-01 on AI-CODING. `python run_full_day_backtest.py` or `Start Full Day Backtest.bat`.
- **PL points:** Groups earn points per full 1.0% total trading P/L. See `agent_groups.ROLE_PL_POINTS_PER_PCT` and task **040**.
- **Dropshipping:** Canonical path `dropshipping/README.md`. ShopifyDS keeps automation.
- **Phone bus:** FinanceWorkspaceWatch every ~2 min. See `RULES.md` / `AGENTS.md`.
- Runtime trading stack may be `C:\Users\Box One\Finance` (local); this clone is `Documents\GitHub\Finance` (git + phone bus). Do not commit secrets from runtime.
- Standing commit rules: subject + body; no secrets.
- **Etrader UI info OFF:** set `phone_ui_info_enabled: true` in runtime `phone_bridge_config.json` to re-enable.
- Armed for HUMAN GitStatus: Send any message from phone on Finance window → AI-CODING should claim and respond.
- **Pipeline 0/0 hint (updated 2026-08-02):** historical 0/0 rows were a recording bug in split post-fusion; fixed. New cycles show real ok/total.
- **Group scoring:** each agent group graded by function. Source: `agent_groups.py` `scoring`.
- **Massive.com (2026-08-02):** Agent `massive-market` live with key on AI-CODING runtime (task **046**). Auth: `MASSIVE_API_KEY` or runtime `data_apis.massive_api_key`. Docs: https://massive.com/docs/rest/quickstart. Do not paste keys into STATUS/git.

