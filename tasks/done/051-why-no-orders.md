# 051 — Why are there no orders?

**status:** done  
**target:** GROMIT  
**kind:** investigate  
**handoff_count:** 0  
**max_handoffs:** 2  
**created:** 2026-08-26  
**updated:** 2026-08-26  
**created_by:** PHONE  
**updated_by:** GROMIT  

## Goal

Phone Send: "why are there no orders?"

## Result

**Answer for phone:** The worker is live on GROMIT and flags are ON (`live_trading` / `auto_execute` / `dry_run` off). It still **submitted 0 orders today**. Empty ETrader Orders is real, not a disconnected phone.

**Three stacked reasons (today 2026-08-26 PT):**

1. **Swing plan cannot rebuild.** Last good `strategy_plan.json` is **2026-08-20** (~157h stale, risk-off). Rebuild fails: *Not enough bullish signals to build a portfolio.* Worker then keeps previewing the leftover **CISS SELL qty 0** → `No orders passed E*TRADE preview (1 skipped for available qty)` (CISS is no longer in the book). Count today: 920 bullish skips (199 in RTH), 187 qty-skips.

2. **Day-trade PDT guard.** `Day trade guards blocked 3/3` **51 times** — `6/3 day trades in 5d` (buying power was ~$3,305). Intraday plan at 12:57 PT had **0 orders** (flatten-before-close, 2.6 min to close). FINRA-style round-trip cap, not a broker outage.

3. **Session clock.** RTH ended 1pm PT / 4pm ET (`US market closed`). At **9:00pm PT / midnight ET** the access token expired again — worker: *Broker waiting for E*TRADE connection (GUI OAuth once).* Re-login is human on GROMIT (`begin_etrade_login.py` on live root).

**Book now (snapshot 2026-08-27T03:51Z, still connected then):** BRVE 9 + SOFI 13 only (~$495 MV); cash BP ~$3,373; total ~$3,867. Older plan still lists 12 names (sold down during the PDT window).

**Not the cause:** phone bridge, git clone, BOXONE, or dry_run. `check_etrade_live_status.py` was OK at 20:59 PT; keepalive failed at 21:00 PT.

**Human next:** OAuth once after midnight ET so tomorrow’s worker can talk to the API. Day trades stay blocked until the 5-day count drops under 3. Swing buys stay off until the portfolio generator gets enough bullish/affordable names (do not lower the gate from this Send).

## Cache

- Live root: `C:\Users\shagg\Finance`
- Worker pid 7012 role=all; log `output/etrade_worker.log`
- `last_plan_error`: Not enough bullish signals…
- `last_execute_at`: 2026-08-26T19:59:06Z (close); submitted lines today: 0
- Snapshot positions: BRVE, SOFI
- Market: closed (checked `check_market_open_live.py`)

## Do not

- Claim live/logged-in after midnight ET without a fresh `check_etrade_live_status.py` OK
- Place or preview live orders from this why-Send
- Lower the bullish holdings floor or override PDT
- Put tokens / bridge token in git or STATUS
