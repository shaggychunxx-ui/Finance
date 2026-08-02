# Inbox — PUSH instructions to BOXONE (task 042)

**From:** AI-CODING  
**To:** BOXONE  
**Priority:** do now  
**Task:** 042  
**Date:** 2026-08-02  

## Why

Human: "push instructions to boxone". Prior RE-SEND still not applied (no `BOXONE_BROKER_APPLY_DONE.txt`).

## Share (refreshed this push)

| File | Purpose |
|------|---------|
| `\\10.10.10.1\HelperDrop\FinanceShare\BOXONE_RUN_THIS.txt` | Full checklist |
| `\\10.10.10.1\HelperDrop\FinanceShare\ATTENTION_BOXONE.txt` | Short urgent note |
| `\\10.10.10.1\HelperDrop\FinanceShare\Apply-Broker-Role-BOXONE.ps1` | Apply role=broker (headless wording) |
| `\\10.10.10.1\HelperDrop\FinanceShare\ROLE_FLIP_B.md` | Role flip B |
| `\\10.10.10.1\HelperDrop\FinanceShare\ETRADE_HEADLESS.md` | No desktop trader UI |

## Run on BOXONE

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "\\10.10.10.1\HelperDrop\FinanceShare\Apply-Broker-Role-BOXONE.ps1"
```

Then: **headless background worker only** (no Unified Trader). Fresh `broker/` on share. STATUS Done **042** → arm **043**; **Act on: none**.

Practice/dry_run ON. Tokens stay local.
