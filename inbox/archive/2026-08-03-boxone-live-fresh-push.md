# Inbox → BOXONE

**from:** AI-CODING  
**at:** 2026-08-03  
**priority:** P0  

Human: **make trading live** + **push fresh data to the phone**.

You are the only host that can (1) re-auth E*TRADE, (2) pull live positions/quotes, (3) place orders.

**Task:** `tasks/pending/047-boxone-live-and-fresh-broker-push.md`  
**STATUS:** Act on BOXONE + NOTIFY set.

**One-liner:**

```powershell
powershell -ExecutionPolicy Bypass -File "\\10.10.10.1\HelperDrop\FinanceShare\Apply-Live-Trading-BOXONE.ps1"
```

Then re-auth if needed, confirm today’s `broker/account_snapshot.json` `fetched_at`, write `BOXONE_LIVE_TRADING_ON.txt`, NOTIFY AI-CODING.
