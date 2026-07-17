# Sleeve policy — same account, shared capital, isolated positions

Long **E\*TRADE Trader** and **E\*TRADE Short Trader** may use the **same brokerage account**.

## Rules

### 1. Shared capital (one pool) + joint profit coordination

- Both sleeves size against **total account equity** and **shared buying power**.
- Cash is **not** split into locked buckets.
- Soft ceilings limit how much of equity each side may deploy at once (defaults):
  - Long: up to **75%** of free equity **or** a fixed dollar cap (see below)
  - Short: up to **35%** of free equity  
  - Shared cash buffer: **5%**
- **Buy-app capital cap** (`long_capital_cap_mode`):
  - `"pct"` — use `long_max_deploy_pct` of free equity (default)
  - `"usd"` — hard dollar ceiling via `long_max_capital_usd` (e.g. only $5,000 of a $20k account)
  - `"off"` — no soft long ceiling beyond free equity / buying power
- **`coordinate_for_profit: true`** (default): `sleeve_coordinator.py` tilts those ceilings toward the sleeve with better multi-horizon expected edge, and assigns each symbol to **long or short** (not both) for new entries.
- Output: `output/sleeve_coordination.json` (deploy %, symbol assignment, joint expected profit).

### 2. Position isolation (no crossing books)

| Sleeve | May open | May close | Never does |
|--------|----------|-----------|------------|
| **Long** | `BUY` | `SELL` of **longs only** | Sell shorts, cover shorts, short stock |
| **Short** | `SELL_SHORT` | `BUY_TO_COVER` of **shorts only** | Sell longs, buy longs as investment |

### 3. No opposite-side on the same symbol

- Long will **not** buy a symbol that is already **short**.
- Short will **not** short a symbol that is already **long**.
- Also respects the other sleeve’s day-trade / plan “claims” when configured.

## Config (`sleeve_policy` in both config files)

```json
"sleeve_policy": {
  "enabled": true,
  "shared_capital": true,
  "coordinate_for_profit": true,
  "long_max_deploy_pct": 75.0,
  "long_capital_cap_mode": "pct",
  "long_max_capital_usd": 5000.0,
  "short_max_deploy_pct": 35.0,
  "shared_cash_buffer_pct": 5.0,
  "forbid_opposite_side": true,
  "forbid_same_symbol_both_sleeves": true
}
```

Keep the block **the same** in `etrade_config.json` and `short_etrade_config.json`.

## Implementation

- `sleeve_policy.py` — isolation + shared capital  
- `sleeve_coordinator.py` — joint profit tilt + symbol assignment  
- Snapshots: `output/sleeve_policy_state.json`, `output/sleeve_coordination.json`

## What this does *not* do

- Does not create two E\*TRADE accounts  
- Does not guarantee fills if both hit the market at once with the same BP  
- Does not move cash between virtual wallets — there is only one real cash balance  
