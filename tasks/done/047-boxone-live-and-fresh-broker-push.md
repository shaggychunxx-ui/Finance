# 047 — BOXONE live trading + fresh broker data for phone

**status:** partial  
**target:** BOXONE  
**kind:** broker-ops  
**depends_on:** 042  
**handoff_count:** 1  
**max_handoffs:** 2  
**created:** 2026-08-03  
**created_by:** AI-CODING  
**origin:** PHONE / human on AI-CODING  
**completed:** 2026-08-03 (partial)  
**completed_by:** BOXONE  

## Goal

1. Turn **LIVE trading** on the **broker** host (BOXONE only).  
2. Pull **fresh** E*TRADE account_snapshot + quotes.  
3. Publish to FinanceShare `broker/` so AI-CODING can push a real-time phone pack.

## Result (partial — 2026-08-03 BOXONE)

| Pass criteria | Result |
|---------------|--------|
| background_worker dry_run=false auto/live/day on | **YES** (runtime local apply; SMB UNC apply script unreachable) |
| deployment role=broker prefer_dry_run=false | **YES** |
| E*TRADE Connected production | **NO** — session expired (401 renew); human OAuth required |
| account_snapshot.fetched_at today | **NO** — still 2026-08-02 |
| Share broker/ + LIVE marker | **Partial** — SFTP OK; wrote `BOXONE_LIVE_FLAGS_APPLIED.txt`; did **not** write `BOXONE_LIVE_TRADING_ON.txt` |
| STATUS NOTIFY AI-CODING | **YES** |

**Notes:** Worker role=broker running. Tokens local only (never git). Human must re-login on BOXONE (`begin_etrade_login.py` / `finish_etrade_login.py <CODE>` or Unified Trader). After Connected, publish fresh snapshot, write LIVE_ON marker, complete remainder.

**Blocker:** human E*TRADE OAuth on BOXONE.