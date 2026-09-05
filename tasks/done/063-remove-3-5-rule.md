# 063 — Remove the house 3/5 day-trade cap

**status:** done  
**target:** GROMIT  
**kind:** fix  
**handoff_count:** 0  
**max_handoffs:** 2  
**created:** 2026-09-05  
**updated:** 2026-09-05  
**created_by:** PHONE  
**updated_by:** GROMIT  

## Goal

Phone Send: "remove 3/5 rule"

Follow-up to tasks **061** / **062** (why-Sends that explained the cap and did not lift it).

## Result

**Answer for phone:** **House 3/5 is off.** The worker will no longer block day trades after 3 round-trips in 5 sessions.

That cap was our software (`trade_guards.py`), not current FINRA/E*TRADE PDT (already gone Jun 2026). Phone asked to remove it, so default is now `pdt_enabled: false` (live config too). Tracker still counts same-day round-trips for reports.

**Still real on this CASH account:** T+1 settlement, good-faith violations, freeriding, and cash buying power **~$126**. Buying-power guard stays on. Day-sleeve `max_positions: 3` is a separate size limit, not the old 3/5 cap. Swing buys are still blocked by the bullish-signal gate (stale plan 2026-08-20). Market closed; next RTH **Tue 2026-09-08** after Labor Day. No tickets placed from this Send.

Live worker **pid 68032** reloaded from `%USERPROFILE%\Finance`; `Connected to E*TRADE (production)`.

## Cache

- Live root `C:\Users\shagg\Finance`
- Git `trade_guards.py` default `pdt_enabled: False`; live `etrade_config.json` `trade_guards.pdt_enabled: false`
- Tests `test_trade_guards.py` + `test_etrade_trader_summary.py` **13 passed**
- Worker pid 104132 → 68032 (pythonw live `--service`)
- Glossary: PDT line is informational; house 3/5 cap off

## Do not

- Treat this as unlimited cash buying power (T+1 / GFV / ~$126 BP remain)
- Place live day trades from this Send (market closed)
- Re-enable the house cap unless the human asks (`pdt_enabled: true`)
- Put tokens / `account_id_key` / bridge token in git or STATUS
