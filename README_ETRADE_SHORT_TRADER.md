# E*TRADE Short Trader (sister app)

Short-selling counterpart to **E*TRADE Trader**. Same machine, same agent research, **separate** config, worker, plans, and trade log.

## UI

**Same desktop UI as E*TRADE Trader** (theme, Home / Agents / Trades / Settings / Activity,
connection bar, trees, automation chips, color palettes). The sister app subclasses the long
GUI shell and rewires the backend for short selling.

| Tab | Short-app behavior |
|-----|--------------------|
| **Home** | Swing shorting + day shorting toggles, dry-run, Stop all |
| **Agents** | Same embedded Finance agents panel |
| **Trades** | Overview · **Short book** · Orders (Swing short / Day short) · Performance |
| **Settings** | Same 4-step connect wizard (writes `short_etrade_config.json`) |
| **Activity** | App / worker log |

## What it does

| Piece | Behavior |
|-------|----------|
| **Short book** | Picks **bearish** names from Finance agent scores (inverted long bias) |
| **Swing** | `SELL_SHORT` toward targets · `BUY_TO_COVER` to trim/exit |
| **Stops** | Optional protective cover orders (stop when price rises, limit target when price falls) |
| **Day shorts** | Intraday shorts from 24h **down** signals; flatten before close |
| **Isolation** | `output/short/*`, mutex `FinanceETradeShortWorkerService`, AppID `Finance.ETrade.ShortTrader.1` |

It does **not** replace the long app. Run both if you want long + short sleeves, but watch **margin, PDT, and opposing positions**.

## Quick start

1. Run **`Install ETrade Short Trader.bat`**
2. Confirm **`short_etrade_config.json`** (created from example)
   - Inherits API keys / selected account from `etrade_config.json` when placeholders are left empty
   - Shares `etrade_tokens.json` by default
3. Launch **ETrade Short Trader** (desktop shortcut or bat)
4. Keep **`sandbox: true`** and **`dry_run: true`** until previews succeed
5. **Build short plan** → **Preview orders**
6. Optional: **`Install ETrade Short Background.bat`** for headless loops

## Safety defaults

```json
"background_worker": {
  "auto_execute": false,
  "live_trading": false,
  "dry_run": true,
  "paused": false
}
```

Short selling requires a **margin-enabled** E*TRADE account, hard-to-borrow awareness, and higher risk of unlimited upside loss. This software does not locate shares or guarantee borrow.

## Files

| Path | Role |
|------|------|
| `short_trader_gui.py` | Desktop UI |
| `short_worker.py` | Background plan / day loops |
| `short_portfolio.py` | Bearish portfolio builder |
| `short_strategy_engine.py` | Swing short rebalance + execute |
| `short_day_trader.py` | Intraday short layer |
| `short_etrade_config.json` | Sister config |
| `output/short/` | Plans, state, logs, history |

## CLI

```bat
.venv\Scripts\python.exe short_worker.py --plan
.venv\Scripts\python.exe short_worker.py --day
.venv\Scripts\python.exe short_worker.py --service
```

## Relation to long trader

- **Agents**: reuses `output/*.json` from the long pipeline (`reuse_long_agent_pipeline`)
- **OAuth**: same tokens file by default
- **Orders**: long uses `BUY`/`SELL`; short uses `SELL_SHORT`/`BUY_TO_COVER`
- **Do not** enable live auto-execute on both apps blindly against the same symbols without a portfolio policy

## Requirements

- Windows 10/11
- Python 3.10+ (project `.venv`)
- E*TRADE developer API keys
- Margin / shorting privileges on the brokerage account
