# Inbox — BOXONE dual-PC pipeline GO

**To:** BOXONE  
**From:** AI-CODING  
**Priority:** P0  
**Date:** 2026-08-02  

Human wants Finance pipeline functioning with BOXONE. Execute end-to-end.

## One command

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "\\10.10.10.1\HelperDrop\FinanceShare\BOXONE_FINISH_042_NOW.ps1"
```

Then install Finance watcher + handoff (see Finance STATUS top + gsw task **060**).

Also assigned on **grok-shared-workspace** (your live watcher): `tasks/pending/060-finance-dual-pc-pipeline-BOXONE.md` with **Act on: BOXONE**.
