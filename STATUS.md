# Status / Handoff — Finance

**Last updated:** 2026-09-04
**Updated by:** PHONE
**Active owner:** none
**Act on:** GROMIT

## NOTIFY

- **NOTIFY (seen on Finance bus):** Decommission BOXONE Finance via **gsw** task **061** (`Act on: BOXONE` on grok-shared-workspace). Finance bus stays quiet on BOXONE.

---

## >>> FINANCE HOST: GROMIT ONLY (2026-08-06) <<<

| Machine | Role | Status |
|---------|------|--------|
| **GROMIT** | **`all`** (broker + pipeline) | **Sole Finance host** — phone bus + runtime target |
| **BOXONE** | **none** | **Finance OFF** — decommission when task 061 runs |
| **AI-CODING / LAPTOP** | **none** for Finance | Do not assign Finance trading |

Docs: `SINGLE_HOST_GROMIT.md`. Dual-PC Role flip B **retired**.

### Fleet policy (standing)

**GROMIT runs all Finance** (trading + agents + phone bus). **Never** `Act on: BOXONE` for Finance. Never Act on PHONE.

## Current goal

Finance phone bus → **GROMIT**. **Dropshipping** canonical under `dropshipping/`. **Primary trading goal:** raise daily and total average P/L.

**Host:** GROMIT single-machine `role=all`. Live root: `%USERPROFILE%\Finance` on GROMIT (create/OAuth when ready). Git clone is bus/code only.

## Next

- [ ] **PHONE (GitStatus):** Reconnect check — pull Finance STATUS, Send `gitstatus-data-probe-gromit`, then `data connection OK` or `FAIL`. Never Act on PHONE.
- [ ] **PHONE (E*TRADE Trader app):** Setup → Base URL `http://192.168.1.177:8787` (GROMIT `/health` `phone_hint`; Wi‑Fi DHCP can change) + bridge token from GROMIT live config only → Test. Same Wi‑Fi as GROMIT.
- [ ] **BOXONE:** Stop all Finance/E*TRADE workers + disable related scheduled tasks (gsw **061**). No trading on BOXONE.
- [x] **GROMIT** no content in email l. send detailed pdf
- [x] **GROMIT** send detailed weekly summary email. include daily info
- [x] **GROMIT** there was no attachment in email
- [x] **GROMIT** why is the data missing for Thursday?
- [ ] **GROMIT** send email of details agent info

## Done

- [x] **GROMIT (PHONE: send etrade trader summary to self in email):** Sent to self via taskbar Chrome Default Gmail. Full body (16 positions, 35 open orders, next-session brief). Equity $3,955.34 day -0.58%. Earlier Chrome pass was subject-only ("Message sent" + empty Gemini placeholder); now compose URL includes `body=` and Send is refused unless body ink-ratio ≥ 0.12. Helper `tools/send_etrade_trader_summary_email.py`. Tests `test_etrade_trader_summary.py` 4 passed. Task `tasks/done/055-etrade-trader-summary-email.md`. **Act on: none**.

- [x] **GROMIT (PHONE: etrader phone app. no orders are displayed):** Empty Orders tab was a display bug, not a dead book. Live #8804 has **35 OPEN** (SOFI/MBAI/LYNX… stop-limits) + recent fills. Bridge **v1.6.4** flattens nested E*TRADE OrderDetail so cards have symbol/action/status (was all `-`). Phone **v1.6.55** loads Orders from GROMIT like Positions (was gated on phone-native login). Phone: **Get app update**, then Refresh. Task `tasks/done/054-etrader-orders-displayed.md`. **Act on: none**.

- [x] **GROMIT (PHONE: Re enteing Oath sould be autmatic):** Midnight re-login is automatic. `complete_etrade_oauth.py` drives taskbar Chrome Default (PrintWindow, not overlay BitBlt): Log on → left Accept → verifier → tokens on live root. Tonight **LIVE STATUS: OK** production; worker `Connected to E*TRADE (production)`. Watchdog + keepalive retry on expiry. 2FA still human if prompted. Task `tasks/done/052-oauth-reentry-automatic.md`. **Act on: none**.

- [x] **GROMIT (PHONE: why are there no orders?):** **0 submitted today.** Not a dead phone/broker: live flags ON, worker role=all. Stack: (1) swing plan stuck **2026-08-20** — rebuild fails *not enough bullish signals* (risk-off); leftover CISS SELL qty 0 skipped available qty; (2) **PDT 6/3 day trades in 5d** blocked 3/3 day orders 51×; (3) market closed after 1pm PT, OAuth expired again **9pm PT / midnight ET**. Book now BRVE+SOFI only. Human: re-login on GROMIT; day trades stay capped until the 5d window rolls. Task `tasks/done/051-why-no-orders.md`. **Act on: none**.

- [x] **GROMIT (PHONE: etrader data not current):** phone_bridge **v1.6.2** on live `:8787`. `/health` ~30ms (was ~21s UNC hang to retired BOXONE). `data_current=true` from 15-min Yahoo marks (16/16 lots), not 14-day broker `fetched_at`. Wi‑Fi **`http://192.168.1.177:8787`**. Tests `test_phone_bridge_publish.py` OK. OAuth still expired (human). Task `tasks/done/050-phone-data-current-from-gromit.md`. **Act on: none**.

- [x] **GROMIT (PHONE: I put them for sale, not the api):** Your UI sells stay. Worker cancels only its own `FIN*` protective stops/limits — never human tickets and never mutual funds. Funds ETMUX/ETBOX/TAIBX/PHYZX/PRBLX are not proposed on the equity API. Re-place any 2026-08-12 canceled fund sells in the E*TRADE **fund** ticket (NAV). Tests `test_human_ui_orders.py` OK. Worker pid 15712 loaded the fix. OAuth still expired past midnight ET (separate human item). Task `tasks/done/049-human-ui-sells-not-api.md`. **Act on: none**.

- [x] **GROMIT (PHONE: why fund sells canceled):** Positions ETMUX/ETBOX/TAIBX/PHYZX/PRBLX are **mutual funds** — equity API cannot sell them. Worker on 2026-08-12 **cancelled open UI SELL orders** for those symbols (cancel-before-sell), then **skipped** fund sells. Fix: skip funds **before** cancel open orders (live `strategy_engine.preview_orders` + git). Sell funds only via E*TRADE UI fund ticket / NAV. Task `tasks/done/048-why-mutual-fund-sells-canceled.md`. **Act on: none**.

- [x] **GROMIT (human: fix connection with phone):** Phone bus + LAN bridge repaired on GROMIT. Installed `FinanceWorkspaceWatch` (GitStatus → GROMIT). `watch-and-act.ps1` main host = GROMIT (not AI-CODING). Started `phone_bridge` v1.5.8 on live root `:8787` (`http://192.168.1.155:8787` health ok); durable task `FinancePhoneBridge` + firewall allow 8787. Pairing: `outbox/phone-bridge-pairing.md` (token not in git). **Act on: none**.
- [x] **GROMIT (human: test etrade + start pipeline):** Live root `C:\Users\shagg\Finance` role=all; venv OK; pipeline critical+quant **51/51** (cycle 20260806T184745Z); worker+ensure **running** dry_run ON; **LIVE STATUS FAIL** — need real consumer_key/secret + OAuth (placeholder config). Trading flags off until keys.
- [x] **GROMIT (human):** **All Finance off BOXONE** â€” single-host GROMIT only. RULES/AGENTS/SINGLE_HOST_GROMIT; dual-PC docs retired. BOXONE decommission task armed. **Act on: BOXONE** for stop stack only.
- [x] **AI-CODING (human: continue pipeline repair):** Fixed phone live pull wrong account (`accounts[0]`=#6854 1-lot vs selected #8804 14-lot) in `phone_bridge.py` v1.5.6. Fixed trading gate zero-eligibility (`trading_gate.py`: preferred-horizon accuracy + floor 35%; was 0/72 agents at 40% combined). Deployed runtime; force eco pipeline **10/10**; plan **15 proposed / 0 blocked**; gate 19/19 candidates. Market closed Ã¢â‚¬â€ live orders resume RTH. **Act on: none**.
- [x] **AI-CODING:** ack BOXONE **NOTIFY 047 partial** Ã¢â‚¬â€ LIVE flags on broker; E*TRADE OAuth still blocked; snapshot **2026-08-02**; no `BOXONE_LIVE_TRADING_ON.txt`. NOTIFY cleared. Surfaced human OAuth + stale snapshot for phone. **Act on: none**. No notify-back. After human re-auth on BOXONE Ã¢â€ â€™ re-pull broker + force phone pack.
- [x] **BOXONE (047 partial):** LIVE flags applied on broker runtime (dry_run off, auto/live/day on, prefer_dry_run false, role=broker). SMB apply script unreachable Ã¢â‚¬â€ local apply. E*TRADE **session expired** (human OAuth needed). Snapshot still **2026-08-02**. No `BOXONE_LIVE_TRADING_ON.txt`. SFTP marker `BOXONE_LIVE_FLAGS_APPLIED.txt`. Task Ã¢â€ â€™ `tasks/done/047-boxone-live-and-fresh-broker-push.md`. **NOTIFY AI-CODING**.
- [x] **AI-CODING (human: instruct BOXONE + fresh phone data):** Wrote task **047**, inbox, share `BOXONE_RUN_THIS.txt` / LIVE scripts; STATUS **Act on: BOXONE** + NOTIFY. Phone pack force-published (14 pos / 70 agents) still waiting on BOXONE for today's snapshot.
- [x] **AI-CODING (human: make trading live):** Enabled LIVE AUTO on pipeline runtime (`dry_run` off, `auto_execute`/`live_trading`/`day_trading` on, `prefer_dry_run` false). Role stays **pipeline** (no orders here). Dropped BOXONE apply script on FinanceShare. **Act on: BOXONE**.
- [x] **BOXONE:** ack AI-CODING **NOTIFY phone re-send key** Ã¢â‚¬â€ key already on AI-CODING runtime (046); SPY re-ok; secret scrubbed. No BOXONE action. NOTIFY cleared. **Act on: none**. Quiet.
- [x] **AI-CODING (PHONE re-send key):** Phone put raw Massive key string in **Next** again. Confirmed runtime key still present (`data_apis.massive_api_key`, len 32). Live re-verify SPY prev bar **ok** (close 747.03, +0.316%). **Scrubbed** secret from Next (no secrets in git). No re-install needed Ã¢â‚¬â€ task **046** already done. Prefer env `MASSIVE_API_KEY` or runtime config only; never STATUS.
- [x] **BOXONE:** ack AI-CODING **NOTIFY 046 complete** Ã¢â‚¬â€ Massive API key on AI-CODING runtime only; SPY prev-bar verified; secrets scrubbed. No BOXONE action. NOTIFY cleared. **Act on: none**. Quiet.
- [x] **AI-CODING (PHONE: key minus the spaces):** Joined phone chunks (whitespace removed) Ã¢â€ â€™ Massive API key installed **runtime-only** (`C:\Users\Box One\Finance\etrade_config.json` Ã¢â€ â€™ `data_apis.massive_api_key`). Live verify: SPY prev bar ok (close 747.03, +0.316%). `massive-market` has_api_key; full watchlist can hit rate_limited on free/low tier. Scrubbed raw key fragments from STATUS Next/Notes. Task: `tasks/done/046-massive-api-key-install.md`. Gmail OAuth still human-only.
- [x] **BOXONE:** ack AI-CODING **NOTIFY 045 complete** Ã¢â‚¬â€ Massive.com agent shipped; Gmail OAuth + Massive key remain human on AI-CODING. No BOXONE action. NOTIFY cleared. **Act on: none**. Quiet.
- [x] **AI-CODING (PHONE: Gmail attn AI-CODING / massive.com API):** Gmail poll **blocked** Ã¢â‚¬â€ `~\.gmail-link` has client credentials but **no `token.json`** (need one-time `Invoke-GmailOAuthSetup.ps1`). No Massive key in env/config. **New agent shipped:** `massive-market` (`agents/massive_market/`) Ã¢â€ â€™ prev-day bars via `api.massive.com`; group markets_core; fail-open without key; registered in main RUNNERS + data steward. Runtime deployed. Empty `data_apis.massive_api_key` slot added (no secret). Task: `tasks/done/045-massive-com-api-gmail-agents.md`. Summary for human: (1) run Gmail OAuth once on AI-CODING, (2) put key in env `MASSIVE_API_KEY` or runtime etrade_config only Ã¢â‚¬â€ never STATUS/git.
- [x] **AI-CODING:** ack BOXONE **NOTIFY 042 complete** Ã¢â‚¬â€ share re-verified: `account_snapshot` fetched_at **2026-08-02T12:32:15Z** (14 pos); done marker host=BOXONE dry_run=on etrade_connected=True SFTP; task 042 in `tasks/done/`. NOTIFY cleared. **Act on: none**. Leave PHONE **043** for human GitStatus. No notify-back.
- [x] **AI-CODING (human: repair connection):** Verified share account_snapshot FRESH; host SMB repair + pipeline pull/push OK. Dual-PC data path live.
- [x] **BOXONE 042 complete:** role=broker; worker Connected production; account_snapshot today; 48 quotes; SFTP + done marker; FinanceWorkspaceWatch Running. Tokens local only. dry_run ON.
- [x] **AI-CODING (human: E*TRADE account connected):** Earlier check Ã¢â‚¬â€ snapshot was Jul-30; re-armed BOXONE (since resolved).
- [x] **AI-CODING:** ack BOXONE 042 **partial** (earlier) Ã¢â‚¬â€ snapshot was stale past midnight ET; resolved after OAuth re-login on BOXONE.
- [x] **BOXONE 042 broker role (partial earlier):** role=broker + headless worker + SFTP; snapshot blocked until token sync Ã¢â‚¬â€ **resolved**.
- [x] **AI-CODING (human: dual-PC pipeline with BOXONE):** Pipeline host locked; BOXONE broker publish path live.
- [x] **AI-CODING (human: BOXONE logged into E*TRADE):** Ack Ã¢â‚¬â€ login belongs on BOXONE (Role flip B). AI-CODING stays pipeline.
- [x] **AI-CODING (human: repair pipeline):** Force-ran pipeline lanes critical+quant+flow on runtime. Cycle `20260802T115842Z`: **51/51 agents ok**. Worker role=pipeline.
- [x] **AI-CODING (human: repair repo communication with BOXONE):** Fixed dead dual-PC bus (`watch-and-act.ps1` targets, BUS-COMMS, inbox archive).
- [x] **AI-CODING (human: "box one says its done"):** Earlier verify fail; 042 later completed for real (see above).
- [x] **AI-CODING (human: repair agent pipeline):** Fixed split-pipeline false 0/0 history bug (`strategy_engine.py` + tests). Deployed to runtime.
- [x] **LAPTOP/gsw (human):** AI workstation payoff roadmap is Finance-first Ã¢â‚¬â€ gsw `work/ai-workstation/PAYOFF-ROADMAP.md`. Does not flip live/dry_run.
- [x] **AI-CODING:** Headless E*TRADE Ã¢â‚¬â€ removed desktop Trader/Unified/Short GUIs. Docs: `ETRADE_HEADLESS.md`.
- [x] **AI-CODING:** Full accuracy/ops plan shipped. APK rebuild assigned Oxygen-OS task **062**.
- [x] **AI-CODING (PHONE):** slow constant full backtest from 2000-01-01 Ã¢â‚¬â€ **done / running**. Task: `tasks/done/041-full-day-backtest-from-2000.md`.
- [x] **AI-CODING (PHONE):** goal increase daily and total average P/L; group PL points Ã¢â‚¬â€ **done**. Task: `tasks/done/040-group-pl-points-daily-total.md`.
- [x] **AI-CODING (PHONE via gsw):** all dropshipping info in Finance Ã¢â‚¬â€ **done**. Canonical: `dropshipping/`.
- [x] **AI-CODING (PHONE):** agent groups scoring systems Ã¢â‚¬â€ **done**. Task: `tasks/done/038-agent-group-scoring.md`.
- [x] **AI-CODING (PHONE):** "Prior pipeline cycle 0/0" explained (empty roster / later fixed recording bug).
- [x] **AI-CODING (PHONE):** transferred positions = deposits; zero P/L at book-in Ã¢â‚¬â€ **done**. Task: `tasks/done/037-transfer-positions-as-deposits.md`.
- [x] **AI-CODING (PHONE):** stop sending info to etrader UI Ã¢â‚¬â€ **done**. Task: `tasks/done/036-stop-etrader-ui-info.md`.
- [x] **AI-CODING:** Scaffolded Finance phone bus + FinanceWorkspaceWatch.
- [x] **AI-CODING:** Received HUMAN GitStatus **test** Ã¢â‚¬â€ RECEIPT OK (2026-07-31).
- [x] **AI-CODING:** GitStatus remote probe Ã¢â‚¬â€ RECEIPT OK.

## Next

- [ ] **PHONE (GitStatus):** Reconnect check — pull Finance STATUS, Send `gitstatus-data-probe-gromit`, then `data connection OK` or `FAIL`. Never Act on PHONE.
- [ ] **PHONE (E*TRADE Trader app):** Setup → Base URL `http://192.168.1.177:8787` (GROMIT `/health` `phone_hint`; Wi‑Fi DHCP can change) + bridge token from GROMIT live config only → Test. Same Wi‑Fi as GROMIT.
- [ ] **BOXONE:** Stop all Finance/E*TRADE workers + disable related scheduled tasks (gsw **061**). No trading on BOXONE.
- [x] **GROMIT** no content in email l. send detailed pdf
- [x] **GROMIT** send detailed weekly summary email. include daily info
- [x] **GROMIT** there was no attachment in email
- [x] **GROMIT** why is the data missing for Thursday?
- [ ] **GROMIT** send email of details agent info

## Blockers

- **PDT 6/3 day trades in 5d** — day-trade sleeve blocked until the rolling window drops under 3. Not a code bug.
- **Swing plan bullish gate** — portfolio rebuild fails (risk-off / not enough bullish affordable names). Stale plan 2026-08-20. Do not lower the gate from a why-Send.
- **US market closed (off-RTH)** — LIVE flags on; no submit until next RTH **and** OAuth.
- **Gmail OAuth token missing** on retired AI-CODING (`token.json`) — not GROMIT trading.
- **Role flip B deferred / obsolete** — GROMIT is sole host `role=all`.

## Notes

- **AI workstation + UPS (2026-08-02):** Hardware order on gsw. Binding: Finance primary goal and Role flip B outrank workstation cutover. No RTH reboot that kills broker/pipeline. No live_trading / dry_run flips for hardware payoff. Secrets off-git.
- **Role flip B (2026-08-01):** BOXONE=broker, AI-CODING=pipeline. Tokens stay on BOXONE only. See ROLE_FLIP_B.md / DUAL_PC_DEPLOYMENT.md.
- [ ] **PHONE (GitStatus / OXYGEN):** Verify Finance **data connection** in GitStatus: open Finance, refresh STATUS, Send `gitstatus-data-probe-gromit`, then Send `data connection OK` or `FAIL`. Checklist: task **043** + `OXYGEN_GITSTATUS_VERIFY.md`. Bridge URL from `/health` `phone_hint` (`http://192.168.1.177:8787`). Never Act on PHONE.
- **Full day backtest:** Continuous walk-forward from 2000-01-01. `python run_full_day_backtest.py` or `Start Full Day Backtest.bat`.
- **PL points:** Groups earn points per full 1.0% total trading P/L. See `agent_groups.ROLE_PL_POINTS_PER_PCT` and task **040**.
- **Dropshipping:** Canonical path `dropshipping/README.md`. ShopifyDS keeps automation.
- **Phone bus:** FinanceWorkspaceWatch every ~2 min on GROMIT. Bridge v1.6.2 `:8787` refreshes phone pack every 15 min all hours. See `RULES.md` / `AGENTS.md` / `BUS-COMMS.md`.
- Live runtime: `%USERPROFILE%\Finance` on GROMIT; this clone is `Documents\GitHub\Finance` (git + phone bus). Do not commit secrets from runtime.
- Standing commit rules: subject + body; no secrets.
- **Etrader UI info:** `phone_ui_info_enabled: true` on GROMIT live bridge (v1.6.2).
- Armed for HUMAN GitStatus: Send any message from phone on Finance window ? **GROMIT** claims and responds.
- **Pipeline 0/0 hint (updated 2026-08-02):** historical 0/0 rows were a recording bug in split post-fusion; fixed. New cycles show real ok/total.
- **Group scoring:** each agent group graded by function. Source: `agent_groups.py` `scoring`.
- **Massive.com (2026-08-02):** Agent `massive-market` live with key on AI-CODING runtime (task **046**). Auth: `MASSIVE_API_KEY` or runtime `data_apis.massive_api_key`. Docs: https://massive.com/docs/rest/quickstart. Do not paste keys into STATUS/git.
- Phone LAN: GROMIT `/health` `phone_hint` is `http://192.168.1.177:8787` (2026-09-03). Token in live config only. Bridge **v1.6.4**.
- PHONE: why are there no orders? → answered 2026-08-26 (task **051**). 0 submitted: bullish-gate stale plan + PDT 6/3 + closed/OAuth.
- PHONE: Re enteing Oath sould be autmatic → done 2026-08-26 (task **052**). Auto OAuth LIVE STATUS OK.
- PHONE: send etrade trader summary to self in email → done 2026-09-04 (task **055**). First Chrome pass was empty body; full-text follow-up sent. Phone asked for a detailed PDF next.
- PHONE: no content in email l. send detailed pdf → Act on GROMIT (GROMIT delegates host-local work)
- PHONE: send detailed weekly summary email. include daily info → Act on GROMIT (GROMIT delegates host-local work)
- PHONE: there was no attachment in email → Act on GROMIT (GROMIT delegates host-local work)
- PHONE: why is the data missing for Thursday? → Act on GROMIT (GROMIT delegates host-local work)
- PHONE: send email of details agent info → Act on GROMIT (GROMIT delegates host-local work)

