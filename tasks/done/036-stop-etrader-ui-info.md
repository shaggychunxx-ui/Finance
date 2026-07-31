# Stop sending info to etrader UI

target: AI-CODING
origin: PHONE
kind: work
handoff_count: 0
max_handoffs: 2
parent: none
status: done
completed: 2026-07-31
completed_by: AI-CODING

## Goal

Honor phone request: stop sending info to the E*TRADE Trader phone UI (etrader).

## Result

**Done (AI-CODING runtime + git docs).**

### What was stopped
1. **phone_bridge `/api/agents`** — returns empty payload with `disabled: true` when `phone_ui_info_enabled=false`.
2. **Dashboard idea/analysis rows** — Top idea / # ideas / Exp. profit stripped; balances, positions, OAuth, stop/resume **still work**.
3. **`work/phone/etrade-agents.json`** (Oxygen) — written empty/disabled so GitHub/phone path stops showing stale agent catalog.
4. **Oxygen `scripts/build-etrade-agents-json.py`** — early-exits when Finance flag/config says disabled.

### Config (runtime, not committed secrets)
- `C:\Users\Box One\Finance\phone_bridge_config.json` → `"phone_ui_info_enabled": false`
- Flag file: `Finance/output/phone_ui_info_disabled.flag`
- Bridge version: **1.3.6**

### Re-enable
1. Set `phone_ui_info_enabled: true` in `phone_bridge_config.json`
2. Delete `output/phone_ui_info_disabled.flag`
3. Restart `phone_bridge.py`
4. Optionally re-run `Oxygen-OS/scripts/build-etrade-agents-json.py`

### Git
- `phone_bridge_config.example.json` documents the flag (no secrets).
- PC trading workers **not** stopped.

## Do not
- Commit API keys / bridge tokens
- Disable FinanceWorkspaceWatch
