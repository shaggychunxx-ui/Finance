# 048 — Why mutual-fund sell orders were canceled

**status:** done  
**target:** GROMIT  
**kind:** investigate  
**handoff_count:** 0  
**max_handoffs:** 2  
**created:** 2026-08-13  
**updated:** 2026-08-13  
**created_by:** PHONE  
**updated_by:** GROMIT  

## Goal

Explain why human sell orders for positions the equity API cannot sell were canceled.

## Result

**Answer for phone:** Those positions are **mutual funds** (ETMUX, ETBOX, TAIBX, PHYZX, PRBLX). The E*TRADE **equity order API cannot sell them** (worker skips with "Mutual fund — not tradable via equity order API (sell in E*TRADE UI)").

**Why your UI sells canceled:** On 2026-08-12 the live worker still **proposed SELL** on those funds, then ran **cancel open SELL orders for every planned sell symbol** (to free locked shares) **before** skipping the fund sells. So human E*TRADE UI fund sell orders were canceled by the worker, and the worker then did **not** place replacement fund sells (API cannot). Log examples: 06:31 Cancelled 5/5 open orders + skipped five fund SELLs; same pattern 06:47, 07:04, 07:35.

**How to sell funds correctly:** Use E*TRADE UI/app **mutual fund** ticket (not stock market order), before fund cutoff (typically ~4pm ET); fill is at end-of-day NAV. Do not rely on the API worker.

**Fix applied (live + git):** `preview_orders` now marks mutual funds **skipped first**, then only cancels open orders for remaining equity-orderable SELLs. Live: `C:\Users\shagg\Finance\strategy_engine.py`. Git: `symbol_universe.py` fund helpers + `strategy_engine.py` skip. Worker restarted pid 18664 to load fix.

## Cache

- Live root: `C:\Users\shagg\Finance`
- Funds: ETMUX ETBOX TAIBX PHYZX PRBLX (KNOWN_MUTUAL_FUNDS)
- Worker log: `output/etrade_worker.log` 2026-08-12 06:31 / 06:47 / 07:04 / 07:35
- LIVE_BLOCKER now: token past midnight ET (unrelated OAuth need)
- Task 043 remains PHONE human verify

## Verify

- Import check: `is_mutual_fund_symbol('PRBLX')` True; AAPL False
- `preview_orders` source contains mutual-fund skip before cancel
