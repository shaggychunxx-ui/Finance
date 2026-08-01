# Shared E*TRADE API + phone app feature feed

target: AI-CODING
origin: human
kind: work
handoff_count: 0
max_handoffs: 2
parent: none
status: done
completed: 2026-08-01
completed_by: AI-CODING

## Goal

Long and short trading operate on the **same E\*TRADE API**, with **independent practice mode** per sleeve. Keep the **E\*TRADE Trader phone app** (not GitStatus) up to date with features and data.

## Result

### Shared API
- New `shared_etrade_api.py`: single source of truth = `etrade_config.json` (keys, sandbox, tokens, account).
- Short sleeve mirrors API fields; never runs a separate brokerage environment.
- Practice mode stays independent: `background_worker.dry_run` on long vs short configs.
- Wired through: `short_config.py`, `short_worker.py`, `short_trader_gui.py` (`api_config` path), `etrade_trader_gui.py` (`API_CONFIG_PATH`), `unified_trader_gui.py`.

### Phone app (E\*TRADE Trader)
- Runtime + git `phone_bridge.py` **v1.5.0**:
  - `GET /api/features` — feature catalog + `shared_api` snapshot
  - `GET /api/dashboard` — includes `shared_api`, single `api_environment`, independent `long`/`short` `dry_run`
  - `GET /health` — advertises `shared_api`, `practice_independent`, `features_path`
  - Account select writes shared account (long + mirror short)
- Oxygen-OS `etrade-app`: `BridgeApi.features()`, dashboard metrics show shared API + independent practice.

### Docs / tests
- `SLEEVE_POLICY.md`, README trader/short, `short_etrade_config.example.json`
- `tests/test_shared_etrade_api.py`

### Runtime
- Synced modules into `C:\Users\Box One\Finance\` (including `phone_bridge.py`). **Restart phone bridge** to pick up v1.5.0.

## Do not
- Commit API keys / bridge tokens / `etrade_tokens.json`
- Treat GitStatus as the etrader phone app update path
