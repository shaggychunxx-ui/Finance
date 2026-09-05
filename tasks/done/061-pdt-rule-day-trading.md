# 061 — Does the PDT rule still apply, or can we start day trading?

**status:** done  
**target:** GROMIT  
**kind:** investigate  
**handoff_count:** 0  
**max_handoffs:** 2  
**created:** 2026-09-05  
**updated:** 2026-09-05  
**created_by:** PHONE  
**updated_by:** GROMIT  

## Goal

Phone Send: "does the pdp rule still apply? or can we start day trading?"

## Result

**Answer for phone:** **PDT still applies. Do not start unlimited day trading.**

Phone wrote **pdp** — that is **PDT** (FINRA Pattern Day Trader, 4+ round-trips in 5 business days, $25k equity). The worker caps at **3/5** so we never take the 4th.

**Now (Sat 2026-09-05 ET):**

- Equity **$3,955.34** (well under $25,000) → software PDT guard **on**.
- Window **Mon 8/31–Fri 9/4:** **3/3 used**, all on **Mon 8/31** (MRNA, SOFI, BRVE). Tue–Fri this week: 0 day trades.
- Remaining slots **0**. Day-trade sleeve stays blocked through the weekend.
- Next RTH is **Tue 2026-09-08** (Labor Day Mon 9/7 closed). Those three roll off → **0/3**, so **up to 3** day-trade names that session — still not unlimited.
- Overnight swing holds are **not** day trades. Swing buys are still blocked separately by the bullish-signal gate (stale plan 2026-08-20).
- Live flags: `day_trading` / `live_trading` / `auto_execute` **on**, `dry_run` off. LIVE STATUS OK. Market closed. Cash buying power **~$126**.

**Cash vs FINRA:** account label is **CASH**, so broker PDT designation is margin-oriented. Cash still needs **settled funds** (good-faith). We **did not** lift the 3/5 software cap from this Send.

## Cache

- Live root `C:\Users\shagg\Finance`
- `output/pdt_tracker.json` — 8/31 MRNA/SOFI/BRVE; no later day_trades
- `trade_guards.py` — `pdt_applies` when equity < $25k; max 3 in 5 weekdays
- Snapshot equity $3,955.34; cash BP $125.86
- Worker pid 104132 role=all; Connected production

## Do not

- Lift or disable the PDT 3/5 guard from a why-Send
- Claim unlimited day trading on a sub-$25k account
- Treat a cash label as permission to ignore settled-cash / GFV
- Place live day trades from this question
- Put tokens / `account_id_key` / bridge token in git or STATUS
