# 062 — Is the PDT 3/5 cap ours? E*TRADE says no more PDT limits

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

Phone Send: "is that rule set by us? e trade says it's no more pdp limits"

Follow-up to task **061** (does PDT still apply).

## Result

**Answer for phone:** **Yes — the 3/5 cap is ours.** E*TRADE is right that FINRA PDT is gone.

| Layer | Status now |
|-------|------------|
| **FINRA PDT** (4 day trades / 5 days + $25k) | **Gone.** Notice **26-10**, effective **2026-06-04**. Replaced by intraday margin (Rule 4210). |
| **E*TRADE** | Implemented **2026-06-09**. No PDT designation, no day-trade count, no $25k PDT min. Margin min is the usual **$2,000**. |
| **Our worker** | **House cap still on:** `trade_guards.py` defaults `pdt_max_day_trades_5d: 3` when equity < $25k. Live config has **no** `trade_guards` override. |
| **This account** | **CASH** (`Individual Brokerage · CASH`). PDT was always a **margin** rule — it never applied to cash at the broker. |

**Still real on cash (unchanged by the PDT repeal):** T+1 settlement, good-faith violations, freeriding. Cash buying power **~$126**. Equity **$3,955**.

Used **3/3** house slots Mon **2026-08-31** (MRNA, SOFI, BRVE). That is our tracker, not an E*TRADE PDT flag.

**Did not lift the house 3/5 from this Send.** Phone asked who set the rule, not to turn it off. Overnight holds are still not day trades. Swing buys still blocked by the bullish-signal gate.

Sources: [FINRA Notice 26-10](https://www.finra.org/rules-guidance/notices/26-10), [E*TRADE PDT rule change](https://us.etrade.com/knowledge/library/margin/pattern-day-trading-rule-change) (dated 06/05/26, CRC# 5551313).

## Cache

- Live root `C:\Users\shagg\Finance`
- Account label: Individual Brokerage · CASH (tail redacted)
- Equity $3,955.34; cash BP $125.86
- `output/pdt_tracker.json` — last day trades 2026-08-31 MRNA/SOFI/BRVE
- Live `etrade_config.json` has no `trade_guards` key → code defaults
- `trade_guards.py` docstring now says house cap, not current FINRA PDT
- Glossary in `tools/send_etrade_trader_summary_email.py` updated

## Do not

- Call the house 3/5 a current E*TRADE or FINRA PDT rule
- Lift or disable the house cap from a why-Send (Send "lift PDT cap" if that is wanted)
- Treat cash as unlimited day-trade buying power (T+1 / GFV / ~$126 BP)
- Place live day trades from this question
- Put tokens / `account_id_key` / bridge token in git or STATUS
