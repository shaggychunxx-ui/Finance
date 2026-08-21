# Dollar-cost averaging sleeve

**Agent:** `dca-strategy` (`run.bat dca-strategy`)  
**Engine:** `dca_engine.py`  
**Lane:** research (`agent_pipelines.RESEARCH_AGENTS`)  
**Group:** `dca_invest` (not directional; 1yr horizon)  
**Worker:** `etrade_worker` after long rebalance, before day trading

This is the scheduled **invest** sleeve. It is not the signal rebalance plan and not the day-trader.

## What it does

On a calendar (weekly default Friday after 10:30 ET, or monthly), buy a fixed dollar amount of a core ETF mix with **whole shares**. Leftover cash rolls. Lots are **protected** from `strategy_engine` SELL/trim. Due-period cash is **reserved** so long/short sleeves do not spend it.

## Live + use score

`dca_strategy.enabled = true` lets the worker place tickets. A **0-100 use score**
decides whether this period deploys:

| Score | Action | Size |
|------|--------|------|
| below 40 | skip (period stays open, retry later) | 0 |
| 40-59 | half | 0.5x |
| 60-84 | full | 1.0x |
| 85+ | lean-in | 1.5x |

Factors: cash slack 25, index dip 25, VIX 20, fusion regime 20, breadth 10.
Risk-off / a down day **raises** the score (buy cheaper core). Melt-up still
invests unless cash is tight. Leftover below 1 whole share rolls to the next period.

In live `etrade_config.json` (never commit secrets):

```json
"dca_strategy": {
  "enabled": true,
  "amount_usd": 100.0,
  "cadence": "weekly",
  "weekday": "Friday",
  "month_day": 1,
  "execute_after_et": "10:30",
  "min_trade_usd": 50.0,
  "protect_lots": true,
  "vix_overlay": "off",
  "vix_high": 30.0,
  "skip_if_cash_below_usd": 200.0,
  "use_score": true,
  "min_score_full": 60.0,
  "min_score_half": 40.0,
  "min_score_lean": 85.0,
  "lean_multiplier": 1.5,
  "universe": [
    {"symbol": "VTI", "weight_pct": 70.0, "name": "US total market"},
    {"symbol": "VXUS", "weight_pct": 20.0, "name": "International ex-US"},
    {"symbol": "BND", "weight_pct": 10.0, "name": "US aggregate bonds"}
  ]
}
```

Group grading: `dca_invest` uses allocation scoring (schedule fidelity, use-decision,
core funding, isolation) and allocator P/L points (9 per full 1% account gain).

## Knowledge (short)

- DCA = fixed dollars on a calendar, not a forecast.
- Lump-sum usually beats DCA when cash is already idle (cash sits in market longer). DCA is for cash that **arrives over time** and for path/regret.
- Core vehicles: broad low-cost ETFs. Avoid single-name, leveraged, inverse.
- BUY only. Not a day trade. Do not flatten.
- Protect lots from rebalance. Wash-sale: do not sell the same symbol in another sleeve around a buy.
- Optional VIX overlay: `off` (default), `skip_high`, or `lean_in`.

## Outputs

| File | Role |
|------|------|
| `output/dca_strategy.json` | Agent report + knowledge |
| `output/dca_methodology.json` | Sidecar playbook |
| `output/dca_plan.json` | Proposed BUY tickets |
| `output/dca_state.json` | Filled periods + protected qty |

## Pipeline vs other sleeves

| Sleeve | Module | Job |
|--------|--------|-----|
| Long rebalance | `strategy_engine.py` | Target weights from agent fusion |
| Short | `short_strategy_engine.py` | Isolated shorts |
| Day | `day_trader.py` | Intraday, flatten near close |
| **DCA** | `dca_engine.py` | Calendar core BUYs, hold |
