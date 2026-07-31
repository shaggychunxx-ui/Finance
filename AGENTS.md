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

## Idle

If assigned nothing: **exit cleanly. Zero STATUS changes.**
