# 049 — Human UI sells are not API sells

**status:** done  
**target:** GROMIT  
**kind:** fix  
**handoff_count:** 0  
**max_handoffs:** 2  
**created:** 2026-08-13  
**updated:** 2026-08-13  
**created_by:** PHONE  
**updated_by:** GROMIT  

## Goal

Honor phone: "I put them for sale, not the api" — do not cancel or replace human E*TRADE UI sell tickets.

## Result

**Answer for phone:** Those sells are yours (UI), not the worker. The API will **not** cancel them and will **not** place replacement equity sells for the mutual funds.

**What happened 2026-08-12:** Worker proposed fund SELLs, then canceled open SELL tickets (including your UI fund sells) to free shares, then skipped placing API replacements. Task 048 stopped proposing/canceling **fund** symbols first.

**What this follow-up locked in:** Cancel path is `only_worker=True` — only worker `FIN*` protective STOP/LIMIT orders may be canceled. Human UI tickets (no FIN clientOrderId) and mutual funds are never canceled. Leftover-position trim and stop-inject also skip funds.

**How to sell the funds:** Re-place any canceled tickets in the E*TRADE **mutual fund** ticket (not stock market). Fill is end-of-day NAV.

## Cache

- Live root: `C:\Users\shagg\Finance`
- Worker: pythonw `etrade_worker.py --service` pid 15712 started 2026-08-13 04:22:25 (after live patch 04:20)
- Tests: `tests/test_human_ui_orders.py` ALL_OK via live venv (no pytest module)
- Last human-fund cancel in log: 2026-08-12 07:35; later cycles skip only
- LIVE_BLOCKER now: token past midnight ET (OAuth remains human Next item)

## Verify

- `skip_cancel_reason` returns `human_or_external` without FIN prefix
- `skip_cancel_reason` returns `mutual_fund` for PRBLX / securityType MF
- `preview_orders` skips fund SELL and does not call cancel
- Live `strategy_engine.preview_orders` uses `only_worker=True`

## Do not

- OAuth / flip dry_run (human)
- Assign BOXONE
