# Team rules — Finance phone bus

**Applies to:** AI-CODING (main) · BOXONE (helper) · PHONE-OXYGEN (human mobile) · unattended agents in this repo

This repo is a **GitStatus phone bus** plus trading code. Phone writes `STATUS.md`; PC watchers wake headless Grok when assigned.

---

## 1. Roles

| Role | Machine | Authority |
|------|---------|-----------|
| **Main** | **AI-CODING** | Default home for Finance agent work. Plans; may assign light work to BOXONE. |
| **Helper** | **BOXONE** | Executes only assigned work. Does not invent tasks for main. |
| **Mobile** | **PHONE-OXYGEN** | Human via GitStatus / GitHub. Never `Act on: PHONE`. |

Human overrides everything.

---

## 2. STATUS protocol

### When work completes

1. Move task → `tasks/done/` (short **Result**) when a task file exists.
2. Update `STATUS.md`:
   - **Done** — one clear line
   - **Active owner:** `none`
   - **Act on:** the **other** PC (AI-CODING ↔ BOXONE) when a peer should see the result; else **`none`** if human-only / quiet
   - **`NOTIFY:`** when notifying the other PC
3. Clear completed items from **Next**.
4. No secrets in git (keys, tokens, account numbers, bridge tokens).

### When you receive a peer NOTIFY

1. Ack once under **Done**.
2. Set **Act on: none**. Do **not** notify back.

### Idle

If **Act on** is not you and no pending `target:` matches you → **exit without editing STATUS**.

---

## 3. Handoff / anti-thrash

- No heartbeat STATUS edits when idle.
- One owner at a time (`Active owner`).
- Handoff cap default **2**.
- One heavy job at a time.
- No force-push, no disabling watchers, no secrets in commits.

## 4. Commits

All intentional commits need a **subject + Notes body** (why / paths / verify). No secrets.

## 5. Scope

- Prefer report / config / UI-bridge work over live trading actions unless STATUS/Next explicitly asks for a trade action and policy allows it.
- Runtime trading stack may live outside this clone (e.g. `C:\Users\Box One\Finance`); do not commit secrets from runtime into this public repo.

## 6. Live runtime vs Git clone (money path)

| Tree | Role |
|------|------|
| `%USERPROFILE%\Finance` (e.g. `C:\Users\Box One\Finance`) | **Live** — worker, OAuth tokens, orders |
| `Documents\GitHub\Finance` | Bus / code only — **not** the broker host |

- OAuth CLIs **must** write tokens to the live root (`etrade_runtime.resolve_live_root`).
- Agents **must not** claim “logged in” or “trading live” without `check_etrade_live_status.py` OK on the live root + worker log `Connected to E*TRADE (production)`.
- False green on login/live status is a **critical** defect (real money risk).
