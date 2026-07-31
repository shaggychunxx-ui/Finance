# Status / Handoff — Finance

**Last updated:** 2026-07-31
**Updated by:** AI-CODING
**Active owner:** none
**Act on:** BOXONE

## Current goal

Finance phone bus live: GitStatus Send → STATUS.md → FinanceWorkspaceWatch → headless Grok on AI-CODING.

## NOTIFY

- **NOTIFY → BOXONE:** AI-CODING finished Finance PHONE batch (037 transfer=deposits + 036 stop etrader UI info). Runtime bridge **v1.3.6**; `phone_ui_info_enabled=false` (re-enable in `phone_bridge_config.json` + restart bridge). Account P/L excludes ACATS book-in (live total_pl ≈ −$17.55). Ack once → Act on: none.

## Done

- [x] **AI-CODING (PHONE):** transferred positions = deposits; zero P/L at book-in — **done**. `account_profit.py` ACATS/capital-event detection in git+runtime; bridge zeros open P/L on transfer lots (SPCX+SAGMF + learned). Live: net_flows ~$3.7k, total_pl ~−$17.55. See `tasks/done/037-transfer-positions-as-deposits.md`.
- [x] **AI-CODING (PHONE):** stop sending info to etrader UI — **done**. Gated `/api/agents` + idea rows via `phone_ui_info_enabled=false`; emptied `etrade-agents.json` publish path; OAuth/controls/balances still available. Re-enable documented in task Result. See `tasks/done/036-stop-etrader-ui-info.md`.
- [x] **AI-CODING:** Scaffolded Finance phone bus (RULES, AGENTS, tasks/, watch-and-act, install-watcher). Scheduled task **FinanceWorkspaceWatch** on AI-CODING. Phone Send path now has a watcher (was missing).
- [x] **AI-CODING:** Received HUMAN GitStatus **test** — **RECEIPT OK** on **Finance** (AI-CODING, 2026-07-31 04:28).
- [x] **AI-CODING:** GitStatus remote probe `gitstatus-remote-probe-20260731-042147` — **RECEIPT OK**. Public STATUS phone bus fields OK (Act on/Next/Notes).

## Next

- (none)

## Blockers

- (none)

## Notes

- **Phone bus (2026-07-31):** Finance previously accepted GitStatus writes but had **no watcher** — agents never woke on `Act on: AI-CODING`. Fixed: install `FinanceWorkspaceWatch` (every ~2 min). See `RULES.md` / `AGENTS.md`.
- Runtime trading stack may be `C:\Users\Box One\Finance` (local); this clone is `Documents\GitHub\Finance` (git + phone bus). Do not commit secrets from runtime.
- Standing commit rules (mandatory): subject + body; no secrets. Prefer multi-line `git commit -m subject -m body`.
- **Etrader UI info OFF:** set `phone_ui_info_enabled: true` in runtime `phone_bridge_config.json`, delete `output/phone_ui_info_disabled.flag`, restart bridge to re-enable agents feed.
- Armed for HUMAN GitStatus: Send any message from phone on Finance window → AI-CODING should claim and respond.
- Phone reword during rebase said “desktop UI”; task **036** was phone etrader UI info gate (agents/analysis). PC trading workers left running.
