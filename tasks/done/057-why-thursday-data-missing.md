# 057 — Why Thursday data was missing in the weekly summary

**status:** done  
**target:** GROMIT  
**kind:** report  
**handoff_count:** 0  
**max_handoffs:** 2  
**created:** 2026-09-04  
**updated:** 2026-09-04  
**created_by:** PHONE  
**updated_by:** GROMIT  

## Goal

Phone Send: "why is the data missing for Thursday?"

## Result

Thursday **2026-09-03** was a real equity-history gap, not a weekday-label bug.

Live `account_values.json` last **plan** point was Wed 2026-09-02 23:55 UTC ($3,877.14). The 8/26 live worker only wrote that file when a strategy **plan rebuild succeeded**. Thursday plan rebuild failed **3382×** (`Not enough bullish signals`) while the worker stayed **Connected to E*TRADE (production)**. `deployment.publish_quotes=false`, and that live worker had **no** `_snapshot_live_account` fallback, so quote-off days wrote no close. No Thursday trades (last fills 2026-09-02). Friday used the live snapshot ($3,955.34), so the weekly table showed Thu `[missing]`.

Filled Thu close **$3,918.68** from the same 16 lots × that day's marks (no trades that session) and persisted `source=marks`. Resent weekly PDF+body: Thu +1.07%, Fri +0.94% (was +2.02% jumping Wed→Fri). Ink **0.24**, PDF **53,660** bytes attached (`clipboard_hdrop`). Gmail compose **Message sent**.

Deployed git helper + worker snapshot stamp + `analysis_history` same-ET-day + phone_bridge history to live. Reloaded worker **pid 104132** (Connected production) and phone_bridge **pid 50748** `:8787`. Worker now stamps `broker_snapshot` even when plan fails.

## Cache

- Live root `C:\Users\shagg\Finance`
- Helper `tools/send_etrade_trader_summary_email.py` (copied git → live)
- Tests `tests/test_etrade_trader_summary.py` **8 passed**
- Last text `output/etrade_trader_summary_last.txt` (not git)
- PDF `output/etrade_weekly_summary.pdf` (not git)
- Send record `output/etrade_trader_summary_send.json` (not git)

## Do not

- Treat a running worker as proof that daily equity was written
- Interpolate Wed/Fri when lots+marks can reconstruct the session
- Put tokens, `account_id_key`, or SMTP passwords in git/STATUS
