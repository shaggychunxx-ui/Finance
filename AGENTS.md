# Finance — Agent Rules

You are an **unattended worker** on the Finance phone bus. Follow **`RULES.md`** and this checklist.

## Leadership

| Machine | Role |
|---------|------|
| **AI-CODING** | Main. Plans; heavy work; decides BOXONE sends. |
| **BOXONE** | Helper only. |
| **PHONE-OXYGEN** | Human mobile. `origin: PHONE` = human request. Never Act on phone. |

## Always do first

1. Read `RULES.md` (if not known this session).
2. Read `STATUS.md` (Act on, Active owner, Blockers, Next).
3. Read `tasks/pending/` (respect `target`, `handoff_count`, `max_handoffs`, `kind`).
4. Check `inbox/` if relevant.
5. If this machine is **not** the assignee → **exit without editing STATUS**.

## Assignment

- **`Act on:`** must match this `COMPUTERNAME` (or pending `target:`) to start.
- **`Act on: none`** → do nothing; no “checked, no work” STATUS spam.
- **`Act on: ALL` / `either`** → only **AI-CODING** may claim. BOXONE ignores.

## Completing work

1. Claim: **Active owner** = this machine, stamp **Last updated** / **Updated by**.
2. Do the work. Process **all** open **Next** lines for this machine before going idle.
3. Task file → `tasks/done/` + **Result** when applicable.
4. Update **Done**; clear finished **Next** items.
5. Notify other PC when peer needs to know: **Act on:** other + **NOTIFY:**.
6. **Active owner:** `none` when you stop.
7. No secrets in git.

## Phone (GitStatus)

Phone **Send** sets **Act on: AI-CODING** and appends `- [ ] **AI-CODING** <message>` under **Next**. Treat those as human requests.

## Anti-thrash

- No idle STATUS heartbeats.
- One NOTIFY per completion; receiver acks once then quiet.
- Handoff cap enforced.
- Stay in-repo unless the task requires the runtime Finance path (document path; never commit secrets).

## LIVE TRADING / OAuth — money path (mandatory)

Mistakes here cost money. **False “logged in / live” is a critical failure.**

| | Path |
|--|------|
| **Live runtime (worker + tokens)** | `%USERPROFILE%\Finance` → on this PC: `C:\Users\Box One\Finance` |
| **Override** | env `FINANCE_RUNTIME` |
| **Git clone (bus / code only)** | `Documents\GitHub\Finance` — **never** treat as broker host |

### Hard rules

1. **OAuth** only via live root: `begin_etrade_login.py` / `finish_etrade_login.py` (they redirect tokens to live runtime).
2. **Never** say login is good, trading is live, or orders will work from a GitHub-clone-only success.
3. **Only** report live status after:  
   `python check_etrade_live_status.py` → exit 0 / `LIVE STATUS: OK`  
   against **`C:\Users\Box One\Finance`** (or `FINANCE_RUNTIME`), **and** worker log shows `Connected to E*TRADE (production)` when claiming the worker is live.
4. Tokens expire **midnight US/Eastern** daily — re-login is expected; restarts do not wipe same-day tokens.
5. No secrets in git (`etrade_config.json`, `etrade_tokens.json`).

### After any OAuth

Run `check_etrade_live_status.py` on the live tree. If it fails, say **not live** with the blocker — never soft-pass.

## Idle

If assigned nothing: **exit cleanly. Zero STATUS changes.**
