# Finance — Agent Rules

You are an **unattended worker** on the Finance phone bus. Follow **`RULES.md`** and this checklist.

## Leadership

| Machine | Role |
|---------|------|
| **GROMIT** | **Sole Finance host.** Broker + pipeline + phone bus + all background Finance work. |
| **PHONE-OXYGEN** | Human mobile. `origin: PHONE` = human request → **`Act on: GROMIT`**. Never Act on phone. |
| **BOXONE / LAPTOP / AI-CODING** | **No Finance work.** Exit if Act on / target is not you; do not invent Finance tasks. |

## Always do first

1. Read `RULES.md` (if not known this session).
2. Read `STATUS.md` (Act on, Active owner, Blockers, Next).
3. Read `tasks/pending/` (respect `target`, `handoff_count`, `max_handoffs`, `kind`).
4. Check `inbox/` if relevant.
5. If this machine is **not** the assignee → **exit without editing STATUS**.
6. If you are BOXONE (or any non-GROMIT) and task is Finance → **do not run trading** — exit or stop stack if human tasked a decommission only.

## Assignment

- **`Act on:`** must match this `COMPUTERNAME` (or pending `target:`) to start.
- **`Act on: none`** → do nothing; no “checked, no work” STATUS spam.
- **`Act on: ALL` / `either`** → only **GROMIT** may claim.
- **Never** create Finance `target: BOXONE` (or other helpers) unless human explicitly overrides.

## Completing work

1. Claim: **Active owner** = this machine, stamp **Last updated** / **Updated by**.
2. Do the work on **GROMIT**.
3. Task file → `tasks/done/` + **Result** when applicable.
4. Update **Done**; clear finished **Next** items.
5. **Active owner:** `none` when you stop.
6. No secrets in git.

## Phone (GitStatus)

Phone **Send** → **Act on: GROMIT** and `- [ ] **GROMIT** <message>` under **Next**.

## LIVE TRADING / OAuth — money path (mandatory)

Mistakes here cost money. **False “logged in / live” is a critical failure.**

| | Path |
|--|------|
| **Live runtime (worker + tokens)** | `%USERPROFILE%\Finance` on **GROMIT** |
| **Override** | env `FINANCE_RUNTIME` |
| **Git clone (bus / code only)** | `Documents\GitHub\Finance` |

### Hard rules

1. **OAuth** only via live root on GROMIT: `begin_etrade_login.py` / `finish_etrade_login.py`.
2. **BOXONE is not a Finance host** — no broker, no pipeline, no E*TRADE worker there.
3. Prefer `deployment.role = all` on GROMIT (single machine).
