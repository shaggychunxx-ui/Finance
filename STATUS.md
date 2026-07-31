# Status / Handoff — Finance

**Last updated:** 2026-07-31
**Updated by:** PHONE-OXYGEN
**Active owner:** none
**Act on:** AI-CODING

## Current goal

Finance phone bus live: GitStatus Send → STATUS.md → FinanceWorkspaceWatch → headless Grok on AI-CODING.

## NOTIFY

- (none)

## Done

- [x] **AI-CODING:** Scaffolded Finance phone bus (RULES, AGENTS, tasks/, watch-and-act, install-watcher). Scheduled task **FinanceWorkspaceWatch** on AI-CODING. Phone Send path now has a watcher (was missing).
- [x] **AI-CODING:** Received HUMAN GitStatus **test** — **RECEIPT OK** on **Finance** (AI-CODING, 2026-07-31 04:28).
- [x] **AI-CODING:** GitStatus remote probe `gitstatus-remote-probe-20260731-042147` — **RECEIPT OK**. Public STATUS phone bus fields OK (Act on/Next/Notes).

## Next

- [ ] **AI-CODING** make sure all transfered positions count as deposits. zero out profit and p/l at time of deposti
- [ ] **AI-CODING** stop sending info to etrader desktop UI

## Blockers

- (none)

## Notes

- **Phone bus (2026-07-31):** Finance previously accepted GitStatus writes but had **no watcher** — agents never woke on `Act on: AI-CODING`. Fixed: install `FinanceWorkspaceWatch` (every ~2 min). See `RULES.md` / `AGENTS.md`.
- PHONE: make sure all transfered positions count as deposits. zero out profit and p/l at time of deposti → Act on AI-CODING
- PHONE: stop sending info to etrader UI → Act on AI-CODING (re-armed after bus scaffold).
- Standing commit rules (mandatory): subject + body; no secrets. Prefer multi-line `git commit -m subject -m body`.
- Runtime trading stack may be `C:\Users\Box One\Finance` (local); this clone is `Documents\GitHub\Finance` (git + phone bus). Do not commit secrets from runtime.
- Armed for HUMAN GitStatus: Send any message from phone on Finance window → AI-CODING should claim and respond.
- PHONE: gitstatus-remote-probe-20260731-042147 -> Act on AI-CODING
- PHONE: test → Act on AI-CODING
