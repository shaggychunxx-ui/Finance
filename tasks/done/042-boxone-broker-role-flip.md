# 042 â€” BOXONE becomes broker (role flip B)

**status:** pending  
target: BOXONE  
**kind:** ops  
**handoff_count:** 0  
**max_handoffs:** 2  
**created:** 2026-08-01  
**created_by:** AI-CODING (human chose option B)  
**next_after:** 043 (OXYGEN GitStatus data-connection verify)

## Goal

Make **BOXONE** the E*TRADE **broker** host; **AI-CODING** is already **pipeline**.

## Already done on AI-CODING

- `deployment.json` â†’ `role: pipeline`, `publish_quotes: false`, `consume_shared_quotes: true`
- `etrade_config.json` / `short_etrade_config.json`: `auto_execute`, `live_trading`, `day_trading` = false; `dry_run` = true
- Share handoff: `\\10.10.10.1\HelperDrop\FinanceShare\ROLE_FLIP_B.md`
- Broker template + script: `Apply-Broker-Role-BOXONE.ps1`

## Command (run on BOXONE)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "\\10.10.10.1\HelperDrop\FinanceShare\Apply-Broker-Role-BOXONE.ps1"
```

Or double-click `\\10.10.10.1\HelperDrop\FinanceShare\Apply-Broker-Role-BOXONE.bat`

## BOXONE checklist

1. Run the script above (sets `deployment.json` role=broker; practice/dry_run ON).
2. Keep OAuth tokens **local only**.
3. Restart **headless background worker** only (desktop Unified Trader UIs removed â€” see `ETRADE_HEADLESS.md`). OAuth CLI if needed: `begin_etrade_login.py` / `finish_etrade_login.py`.
4. Confirm share `broker/` files get fresh `pushed_at` / `fetched_at` (**today**, not Jul 30).
5. Confirm `BOXONE_BROKER_APPLY_DONE.txt` exists on the share.
6. **Report complete to AI-CODING (required):**
   - Move this task â†’ `tasks/done/` with **Result** filled.
   - STATUS **Done** line for BOXONE 042.
   - Clear your Next item; keep PHONE **043** Next line.
   - **NOTIFY:** `NOTIFY AI-CODING: 042 complete â€” share broker fresh; please ack.`
   - **Act on: AI-CODING** (so main wakes and acks; then AI-CODING sets Act on: none for phone).
   - **git commit + push** (or auto-sync). Do not go silent after only running the script.
7. Never Act on PHONE. No secrets on share.

## Result

(empty until BOXONE completes and notifies AI-CODING)

## Result

**Partial complete (BOXONE 2026-08-02).** Role flip + headless worker + bus watcher done; live snapshot blocked on OAuth.

| Check | Result |
|-------|--------|
| role=broker | YES on runtime `C:\Users\Box One\Finance\deployment.json` |
| dry_run | ON |
| headless etrade_worker --service | RUNNING (role=broker) |
| SMB UNC HelperDrop | FAIL (error 5/1223); publish via **SFTP** fsbox |
| BOXONE_BROKER_APPLY_DONE.txt | YES on share (via SFTP) |
| broker/broker_status.json | fresh today (SFTP) |
| broker/account_snapshot.json | STALE Jul 30 — token expired past midnight ET (last tokens 2026-07-31) |
| FinanceWorkspaceWatch | Ready (install-watcher.ps1) |
| FinanceBrokerSftpPublish | Ready every 2m |

**Blocker (human on BOXONE):**
```
cd $env:USERPROFILE\Finance
python begin_etrade_login.py
python finish_etrade_login.py <CODE>
```
Then worker publishes fresh snapshot; SFTP task mirrors to AI-CODING share.

Report (gsw): `work/finance-dual-pc/reports/apply-BOXONE-060-latest.md`
