# Finance — Agent Rules

You are an **unattended worker** on the Finance phone bus. Follow **`RULES.md`** and this checklist.

## Leadership

| Machine | Role |
|---------|------|
| **GROMIT** | **Main.** **Runs all background / unattended tasks** by default. Plans; heavy agent work; assigns BOXONE only for host-local broker/runtime. |
| **BOXONE** | Helper / broker host only when assigned. |
| **AI-CODING** | Helper spare only when explicitly assigned. |
| **PHONE-OXYGEN** | Human mobile. `origin: PHONE` = human request → default **`Act on: GROMIT`**. Never Act on phone. |

## Always do first

1. Read `RULES.md` (if not known this session).
2. Read `STATUS.md` (Act on, Active owner, Blockers, Next).
3. Read `tasks/pending/` (respect `target`, `handoff_count`, `max_handoffs`, `kind`).
4. Check `inbox/` if relevant.
5. If this machine is **not** the assignee → **exit without editing STATUS**.

## Assignment

- **`Act on:`** must match this `COMPUTERNAME` (or pending `target:`) to start.
- **`Act on: none`** → do nothing; no “checked, no work” STATUS spam.
- **`Act on: ALL` / `either`** → only **GROMIT** may claim. Helpers ignore.
- Default background work is **GROMIT** — helpers do not claim it.

## Completing work

1. Claim: **Active owner** = this machine, stamp **Last updated** / **Updated by**.
2. Do the work. Process **all** open **Next** lines for this machine before going idle.
3. Task file → `tasks/done/` + **Result** when applicable.
4. Update **Done**; clear finished **Next** items.
5. Notify peer when needed: helper done → **`Act on: GROMIT`** + **NOTIFY:**; GROMIT done → assign host-local helper or **none**.
6. **Active owner:** `none` when you stop.
7. No secrets in git.

## Phone (GitStatus)

Phone **Send** should set **Act on: GROMIT** and append `- [ ] **GROMIT** <message>` under **Next**. Treat those as human requests.

## Anti-thrash

- No idle STATUS heartbeats.
- One NOTIFY per completion; receiver acks once then quiet.
- Handoff cap enforced.
- Stay in-repo unless the task requires the runtime Finance path (document path; never commit secrets).

## LIVE TRADING / OAuth — money path (mandatory)

Mistakes here cost money. **False “logged in / live” is a critical failure.**

| | Path |
|--|------|
| **Live runtime (worker + tokens)** | `%USERPROFILE%\Finance` → on BOXONE typically `C:\Users\Box One\Finance` |
| **Override** | env `FINANCE_RUNTIME` |
| **Git clone (bus / code only)** | `Documents\GitHub\Finance` — **never** treat as broker host |

### Hard rules

1. **OAuth** only via live root: `begin_etrade_login.py` / `finish_etrade_login.py` (they redirect tokens to live runtime).
2. Broker host-local work stays on **BOXONE** when assigned; pipeline/agent defaults stay on **GROMIT**.
