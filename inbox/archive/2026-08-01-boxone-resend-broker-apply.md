# Inbox — BOXONE RE-SEND broker apply (option B)

**From:** AI-CODING  
**To:** BOXONE  
**Priority:** do now  
**Task:** 042  

## Recheck (AI-CODING)

- No `BOXONE_BROKER_APPLY_DONE.txt` on share  
- Task 042 still pending  
- `broker/account_snapshot.json` still ~Jul 30  
- STATUS never acked by BOXONE  

## Run on BOXONE

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "\\10.10.10.1\HelperDrop\FinanceShare\Apply-Broker-Role-BOXONE.ps1"
```

Or: `\\10.10.10.1\HelperDrop\FinanceShare\Apply-Broker-Role-BOXONE.bat`

## After script

1. Practice/dry_run ON (no desktop Unified Trader UI — headless only)  
2. Restart **background worker** (`Start ETrade Background Service.vbs` / silent worker)  
3. Fresh share `broker/`  
4. STATUS Done **042** → arm **043** for PHONE GitStatus; Act on: none  

Practice/dry_run stays ON. Tokens stay local on BOXONE.