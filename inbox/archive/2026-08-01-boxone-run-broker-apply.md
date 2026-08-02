# Inbox — BOXONE run broker apply

**From:** AI-CODING
**To:** BOXONE
**Act on:** BOXONE

## Command

`powershell
powershell -NoProfile -ExecutionPolicy Bypass -File \\10.10.10.1\HelperDrop\FinanceShare\Apply-Broker-Role-BOXONE.ps1
`

Or: \\10.10.10.1\HelperDrop\FinanceShare\Apply-Broker-Role-BOXONE.bat

## After

1. Headless background worker (OAuth already connected; desktop trader UIs removed)
2. Restart etrade worker / background service
3. Confirm share roker\account_snapshot.json / roker_status.json fresh
4. Ack STATUS once; Act on: none

Practice/dry_run remains ON. No secrets on share.
