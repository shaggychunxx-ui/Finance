# 042 — BOXONE becomes broker (role flip B)

**status:** pending  
**target:** BOXONE  
**kind:** ops  
**handoff_count:** 0  
**max_handoffs:** 2  
**created:** 2026-08-01  
**created_by:** AI-CODING (human chose option B)  
**next_after:** 043 (OXYGEN GitStatus data-connection verify)

## Goal

Make **BOXONE** the E*TRADE **broker** host; **AI-CODING** is already **pipeline**.

## Already done on AI-CODING

- `deployment.json` → `role: pipeline`, `publish_quotes: false`, `consume_shared_quotes: true`
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
3. Restart Unified Trader + etrade worker.
4. Confirm share `broker/` files get fresh `pushed_at` / `fetched_at`.
5. Update STATUS: Done line for 042; clear your Next item; **do not leave Act on: BOXONE**.
6. **When done — arm OXYGEN verify (task 043):** under Next add:

```
- [ ] **PHONE (GitStatus):** Verify Finance data connection — open Finance in GitStatus, refresh STATUS, Send `gitstatus-data-probe-verify-role-B`, then Send `data connection OK` or FAIL. See task **043** / share `OXYGEN_GITSTATUS_VERIFY.md`.
```

   Set **Act on: none** (human phone uses GitStatus Send; never Act on PHONE).  
   One NOTIFY ack only — no ping-pong.

## Result

(empty until BOXONE completes)
