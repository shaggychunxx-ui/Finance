# E*TRADE — headless (no desktop trader UI)

Desktop **ETrade Trader** / **ETrade Unified Trader** GUIs have been **removed**.  
**Kept:** agent pipeline, `etrade_api/`, workers, OAuth CLI, phone bridge, Finance Agents report UI.

## What to use instead

| Need | How |
|------|-----|
| Agent research UI | `Finance Agents.bat` / `finance_agents_gui.py` |
| Connect OAuth | `begin_etrade_login.py` then `finish_etrade_login.py <CODE>` |
| Headless trading worker | `Install ETrade Background.bat` or `Start ETrade Background Service.vbs` |
| Quiet pipeline/worker | `Start Silent Worker Only.vbs` |
| Phone monitor | `phone_bridge.py` (LAN) |

## Config

- Long/shared API: `etrade_config.json` (from `etrade_config.example.json`)
- Short sleeve: `short_etrade_config.json` (optional; shares API via `shared_etrade_api.py`)
- Dual-PC roles: `deployment.json` — see `DUAL_PC_DEPLOYMENT.md` / `ROLE_FLIP_B.md`

## Not removed

- `etrade_worker.py`, `short_worker.py`, `ensure_silent_worker.py`
- `etrade_api/`, day/swing strategy engines, pipeline agents
- Install/run scripts for **background** services (not the old desktop GUI)
