# 044 — Headless E*TRADE (remove desktop trader UIs)

**status:** done  
**target:** AI-CODING  
**kind:** code  
**created:** 2026-08-01  
**completed:** 2026-08-02  
**completed_by:** AI-CODING  

## Goal

Remove desktop ETrade Trader / Unified / Short GUIs. Keep agents, API, headless workers, OAuth CLI, phone bridge, Finance Agents report UI.

## Result

- Deleted: `etrade_trader_gui.py`, `unified_trader_gui.py`, `short_trader_gui.py`, launchers, install/package scripts, desktop icon refreshers, related bats/vbs/READMEs.
- `finance_agents_gui.py` runs standalone (no redirect to unified GUI).
- `install_etrade_background.ps1` installs worker only; strips obsolete GUI shortcuts.
- Import/Export user-data scripts resolve Finance root via `etrade_worker.py` / `etrade_api`.
- `phone_bridge.py` 1.5.3: load best of local + share broker snapshots; refuse thinner live overwrite; heal thin local; `/health` data_quality; atomic oxygen dashboard publish.
- Docs: `ETRADE_HEADLESS.md`, `DUAL_PC_DEPLOYMENT.md`, `ROLE_FLIP_B.md`, STATUS NOTIFY for **042**.
