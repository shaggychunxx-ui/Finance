# 042 — BOXONE becomes broker (role flip B)

**status:** pending
**target:** BOXONE
**kind:** ops
**handoff_count:** 0
**max_handoffs:** 2
**created:** 2026-08-01
**created_by:** AI-CODING (human chose option B)

## Goal

Make **BOXONE** the E*TRADE **broker** host; **AI-CODING** is already **pipeline**.

## Already done on AI-CODING

- `deployment.json` → `role: pipeline`, `publish_quotes: false`, `consume_shared_quotes: true`
- `etrade_config.json` / `short_etrade_config.json`: `auto_execute`, `live_trading`, `day_trading` = false; `dry_run` = true
- Share handoff: `\\10.10.10.1\HelperDrop\FinanceShare\ROLE_FLIP_B.md`
- Broker template: `FinanceShare\_deploy\deployment.json.broker-for-BOXONE.json`

## BOXONE checklist

1. Copy `_deploy/deployment.json.broker-for-BOXONE.json` → runtime `deployment.json` (role=broker).
2. Keep OAuth tokens **local only** (user reported already connected).
3. Leave `prefer_dry_run` / practice on until human says live.
4. Restart Unified Trader + etrade worker so role reloads.
5. Confirm share `broker/` files get fresh `pushed_at` / `fetched_at`.
6. Ack STATUS: set Act on none after one NOTIFY ack.

## Result

(empty until BOXONE completes)

## Command (run on BOXONE)

`powershell
powershell -NoProfile -ExecutionPolicy Bypass -File \\10.10.10.1\HelperDrop\FinanceShare\Apply-Broker-Role-BOXONE.ps1
`

Or double-click \\10.10.10.1\HelperDrop\FinanceShare\Apply-Broker-Role-BOXONE.bat

