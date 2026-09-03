# 054 — ETrader phone app: no orders displayed

**status:** done  
**target:** GROMIT  
**kind:** fix  
**handoff_count:** 0  
**max_handoffs:** 2  
**created:** 2026-09-03  
**updated:** 2026-09-03  
**created_by:** PHONE / TUI  
**updated_by:** GROMIT  

## Goal

Phone / TUI: "etrader phone app. no orders are displayed"

## Result

**Not an empty broker book.** Live #8804 during RTH 2026-09-03: **35 OPEN** stop-limits (SOFI, MBAI, LYNX, MRNA, SMCI, XLE, …) plus recent EXECUTED buys/sells. Worker LIVE STATUS OK.

Two display bugs:

1. **Bridge `build_orders_for_phone`** mapped top-level `symbol`/`action`/`status`. E*TRADE List Orders keeps those under `OrderDetail` / `Instrument` / `Product`, so the pack was 35 rows of `-`. Now **v1.6.4** flattens OPEN + recent history (count 100).
2. **Orders tab** required phone-native E*TRADE login (`isEtradeLoggedIn()`). After v1.6.54, lots/orders come from GROMIT only — skip login — so Refresh never ran. **v1.6.55** uses the same GROMIT LAN/GitHub gate as Positions.

Phone: Settings → **Get app update**, then Orders → Refresh. Same Wi‑Fi `http://192.168.1.177:8787`.

## Cache

- Live root `C:\Users\shagg\Finance`; bridge `:8787` v1.6.4
- Flattened pack: 100 orders, 35 open; first SOFI SELL OPEN STOP_LIMIT 15.61/15.69
- Tests: `tests/test_phone_bridge_orders.py` + publish/same-account **15 passed**
- App: Oxygen-OS `etrade-app` v1.6.55 / code 67

## Do not

- Claim no tickets at the broker when List Orders returns nested OPEN rows
- Gate Orders refresh on phone OAuth
- Put bridge token / account id key in git
