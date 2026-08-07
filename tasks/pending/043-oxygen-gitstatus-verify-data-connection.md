# 043 — OXYGEN GitStatus verify data connection (GROMIT sole host)

**status:** pending  
target: PHONE (human OXYGEN via GitStatus)  
**kind:** verify  
**depends_on:** GROMIT phone bus + bridge up  
**handoff_count:** 0  
**max_handoffs:** 1  
**created:** 2026-08-01  
**updated:** 2026-08-06  
**created_by:** AI-CODING  
**updated_by:** GROMIT  

## Goal

**PHONE-OXYGEN** confirms the Finance **data connection** through **GitStatus** (STATUS phone bus) and optionally the E*TRADE Trader LAN bridge on **GROMIT**. Never `Act on: PHONE`.

## When to run

After GROMIT phone reconnect Done line is visible (watcher + bridge installed).

## Checklist (GitStatus app)

1. Open **GitStatus** → **Finance** repo.
2. Refresh STATUS — read Act on / Next / Notes / GROMIT host policy.
3. Confirm GROMIT Done line for **phone reconnect** is visible.
4. **Send** probe message: `gitstatus-data-probe-gromit`
5. Wait for **GROMIT** RECEIPT under Done (watcher ~2 min).
6. Send result: `data connection OK` or `data connection FAIL: <reason>`
7. Optional: E*TRADE Trader Setup → `http://192.168.1.155:8787` + token from GROMIT config only.

## Pass criteria

| Check | Required |
|-------|----------|
| Finance STATUS readable in GitStatus | Yes |
| GROMIT phone reconnect Done visible | Yes |
| Probe gets GROMIT RECEIPT | Yes |
| No secrets leaked into STATUS | Yes |

## Docs

- `OXYGEN_GITSTATUS_VERIFY.md`
- `outbox/phone-bridge-pairing.md`

## Result

(empty until PHONE reports)
