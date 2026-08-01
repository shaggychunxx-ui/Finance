# 043 — OXYGEN GitStatus verify data connection (after role flip B)

**status:** pending  
**target:** PHONE (human OXYGEN via GitStatus)  
**kind:** verify  
**depends_on:** 042 (BOXONE broker apply)  
**handoff_count:** 0  
**max_handoffs:** 1  
**created:** 2026-08-01  
**created_by:** AI-CODING  

## Goal

After BOXONE finishes broker role flip, **PHONE-OXYGEN** confirms the Finance **data connection** through **GitStatus** (STATUS phone bus), not by `Act on: PHONE` (forbidden).

## When to run

Only after task **042** is Done (BOXONE broker applied, share `broker/` fresh).

## Checklist (GitStatus app)

1. Open **GitStatus** → **Finance** repo.
2. Refresh STATUS — read Act on / Next / Notes / role flip B.
3. Confirm BOXONE Done line for **042** is visible.
4. **Send** probe message: `gitstatus-data-probe-verify-role-B`
5. Wait for AI-CODING **RECEIPT** under Done (watcher).
6. Send result: `data connection OK` or `data connection FAIL: <reason>`

## Pass criteria

| Check | Required |
|-------|----------|
| Finance STATUS readable in GitStatus | Yes |
| Role flip B / 042 completion visible | Yes |
| Probe gets AI-CODING RECEIPT | Yes |
| No secrets leaked into STATUS | Yes |

## Share copy

`\\10.10.10.1\HelperDrop\FinanceShare\OXYGEN_GITSTATUS_VERIFY.md`

## Result

(empty until PHONE reports)
