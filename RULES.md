# Team rules — Finance phone bus

**Applies to:** GROMIT (sole Finance host) · PHONE-OXYGEN (human mobile) · unattended agents  
**Does not apply Finance work to:** LAPTOP · retired BOXONE · retired AI-CODING (unless human overrides)

This repo is a **GitStatus phone bus** plus trading code. Phone writes `STATUS.md`; GROMIT watchers wake headless Grok when assigned.

### Host policy (human 2026-08-06)

**All Finance is off BOXONE** (and BOXONE is out of the fleet). Dual-PC broker/pipeline split is **retired**.

| Work | Who |
|------|-----|
| Broker (E*TRADE OAuth, worker, orders, quotes) | **GROMIT only** |
| Pipeline (agents, fusion, backtests) | **GROMIT only** |
| Phone bus / STATUS / tasks | **GROMIT** (`Act on: GROMIT`) |
| BOXONE / LAPTOP / AI-CODING | **No Finance** — do not assign `target: BOXONE` for Finance |

Live runtime root on GROMIT: `%USERPROFILE%\Finance` (or `FINANCE_RUNTIME`).  
Git clone `Documents\GitHub\Finance` = bus/code only.

---

## 1. Roles

| Role | Machine | Authority |
|------|---------|-----------|
| **Sole Finance host** | **GROMIT** | All trading runtime, agents, automation, phone bus execution. |
| **Mobile** | **PHONE-OXYGEN** | Human via GitStatus / GitHub. Never `Act on: PHONE`. Default **`Act on: GROMIT`**. |

Human overrides everything.

---

## 2. STATUS protocol

### When work completes

1. Move task → `tasks/done/` (short **Result**) when a task file exists.
2. Update `STATUS.md`:
   - **Done** — one clear line
   - **Active owner:** `none`
   - **Act on:** **`none`** when quiet; **`GROMIT`** only if more GROMIT work remains
   - **`NOTIFY:`** rare (phone reads STATUS)
3. Clear completed items from **Next**.
4. No secrets in git (keys, tokens, account numbers, bridge tokens).

### Idle

If **Act on** is not you → **exit without editing STATUS**.  
BOXONE / LAPTOP / AI-CODING: if woken on Finance bus by mistake → **exit**; do not claim Finance work.

---

## 3. Handoff / anti-thrash

- No heartbeat STATUS edits when idle.
- One owner at a time (`Active owner`).
- Handoff cap default **2** (should not apply dual-PC Finance anymore).
- One heavy job at a time.
- No force-push, no disabling watchers, no secrets in commits.

## 4. Commits

All intentional commits need a **subject + Notes body** (why / paths / verify). No secrets.

## 5. Scope

- Prefer report / config / UI-bridge work over live trading actions unless STATUS/Next explicitly asks for a trade action and policy allows it.
- Do not commit secrets from runtime into this public repo.

## 6. Live runtime vs Git clone (money path)

| Tree | Role |
|------|------|
| `%USERPROFILE%\Finance` on **GROMIT** | **Live** — worker, OAuth tokens, orders |
| `Documents\GitHub\Finance` | Bus / code only — **not** the broker host |

- OAuth CLIs **must** write tokens to the live root (`etrade_runtime.resolve_live_root`).
- Agents **must not** claim “logged in” or “trading live” without `check_etrade_live_status.py` OK on the live root + worker log `Connected to E*TRADE (production)`.
- False green on login/live status is a **critical** defect (real money risk).

## 7. Dual-PC docs

Historical dual-PC files (`DUAL_PC_*.md`, Role flip B) are **obsolete for ops**. See `SINGLE_HOST_GROMIT.md`.
