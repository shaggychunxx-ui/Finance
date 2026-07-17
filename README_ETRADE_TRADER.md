# E*TRADE Trader

Desktop app that connects Finance agent research to your E*TRADE brokerage account. One window — agents, automation, trades, and reporting.

## Quick start

1. Run **Install ETrade Trader.bat** (creates `.venv` and desktop shortcut).
2. Copy `etrade_config.example.json` → `etrade_config.json` and add your [E*TRADE developer](https://developer.etrade.com) consumer key/secret.
3. Launch **ETrade Unified Trader** (recommended) — Long + Short sleeves in one window — or standalone **ETrade Trader** / **ETrade Short Trader**.
4. **Settings** → Connect → confirm account (each sleeve can use its own account and dry-run flag).
5. Start in **Sandbox** / practice mode before going live.

Optional: **Install ETrade Background.bat** keeps agents and trading running when the GUI is closed.

## Tabs

| Tab | Purpose |
|-----|---------|
| **Home** | Dashboard, automation on/off, dry-run mode, day trading toggle |
| **Agents** | Browse Finance agent research reports |
| **Trades** | Portfolio, orders, P&L, balance, attribution (see below) |
| **Settings** | API keys, OAuth, account selection |
| **Activity** | App and worker log |

### Trades sub-tabs

| Sub-tab | What it shows |
|---------|----------------|
| **Balance & gains** | Account value, buying power, gain $/%, equity curve chart, balance history |
| **History & P&L** | Every logged fill with realized P&L; **Export CSV** for taxes |
| **Attribution** | Realized P&L and trade counts grouped by agent source |
| **Portfolio** | Current vs agent target weights |
| **Swing** | Longer-term rebalance orders |
| **Day trading** | Same-day positions and orders |

## Automation (default)

| Task | Interval |
|------|----------|
| Agent pipeline | 5 minutes |
| Strategy plan rebuild | 30 minutes |
| Swing order execution | 15 minutes (market hours) |
| Day trading scan | 5 minutes (market hours) |

Use **Stop all** on Home to halt everything. **Practice mode (dry run)** simulates orders without sending them to E*TRADE.

## Swing stop / target orders

Configured under `strategy` in `etrade_config.json`:

```json
"strategy": {
  "stop_loss_pct": 8.0,
  "take_profit_pct": 15.0,
  "use_stop_orders": true,
  "place_protective_orders": true
}
```

- **use_stop_orders** — during plan rebuild, inject market sells when price hits stop or target vs tracked entry lots.
- **place_protective_orders** — after each swing BUY fill, submit GTC stop-limit (stop) and limit (target) sells at E*TRADE.

Adjust percentages for your risk tolerance. Sandbox is the right place to test broker acceptance of stop/limit orders.

## Trade history and tax export

Fills are appended to `output/history/trade_history.json` when orders are placed (live or dry run).

**History & P&L** → **Export CSV** writes a tax-friendly log with:

- Date/time, symbol, action, quantity, price, value
- Realized P&L (when a sell closes a lot)
- Mode (swing / day), agent sources, rationale
- Stop/target levels recorded on buys

Review exported data before filing — this is a convenience log, not tax advice.

## Performance attribution

The **Attribution** tab groups logged trades by agent `sources` from the portfolio generator (e.g. `markets`, `finance`, `market-predictor`). Realized P&L is attributed when a sell closes a position that was opened with known agent sources.

## Phone monitor

1. **Start Mobile Server.bat** — LAN access on your Wi-Fi.
2. **Start Mobile Remote Access.bat** — Cloudflare tunnel for away-from-home.
3. Open the URL on your phone (include `?token=` from the console).

## Files

| Path | Contents |
|------|----------|
| `etrade_config.json` | API keys, strategy, day trading, worker settings |
| `output/strategy_plan.json` | Latest swing plan and orders |
| `output/history/trade_history.json` | Trade journal |
| `output/history/account_values.json` | Balance snapshots for growth chart |
| `output/etrade_trader.log` | Desktop app log |
| `output/etrade_worker.log` | Background worker log |

## Requirements

- Windows 10/11
- Python 3.10+
- E*TRADE developer API keys