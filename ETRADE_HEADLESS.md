# E*TRADE — headless (no desktop trader UI)

Desktop **ETrade Trader** / **ETrade Unified Trader** GUIs have been **removed**.  
**Kept:** agent pipeline, `etrade_api/`, workers, OAuth CLI, phone bridge, Finance Agents report UI.

## What to use instead

| Need | How |
|------|-----|
| Agent research UI | `Finance Agents.bat` / `finance_agents_gui.py` |
| Connect OAuth | `begin_etrade_login.py` then `finish_etrade_login.py <CODE>` — **always targets live runtime** (`%USERPROFILE%\Finance`), even if you run the script from a GitHub clone |
| Verify live (required) | `python check_etrade_live_status.py` → must print `LIVE STATUS: OK` |
| Headless trading worker | `Install ETrade Background.bat` or `Start ETrade Background Service.vbs` |
| Quiet pipeline/worker | `Start Silent Worker Only.vbs` |
| Phone monitor | `phone_bridge.py` (LAN) |

### Live runtime (do not confuse with git clone)

- **Live (tokens + worker):** `%USERPROFILE%\Finance` (this PC: `C:\Users\Box One\Finance`), or `FINANCE_RUNTIME`
- **Git clone:** `Documents\GitHub\Finance` — code/bus only; logging in *only* there does **not** feed the worker
- Tokens die at **midnight US/Eastern**; full browser OAuth again next day

## Standalone short worker — retired

Do **not** run `short_worker.py --service` as a second background process.  
It duplicated the main stack (venv stub pairs) and error-looped on the pipeline host when tokens live only on BOXONE.

| Was | Now |
|-----|-----|
| `Start ETrade Short Background Service.vbs` | **No-op** (safe if old Startup lnk remains) |
| `install_short_background.ps1` | **Retire/uninstall only** (removes autostart) |
| Task `Finance ETrade Short Dry-Run` | Disable on hosts that ran it |
| Manual CLI | Still OK: `short_worker.py --plan` / `--day` / `--force-dry-run` |

Use the main immortal stack: `finance_supervisor` → `pipeline_watchdog` → `etrade_worker` (+ continuum).

## Config

- Long/shared API: `etrade_config.json` (from `etrade_config.example.json`)
- Short sleeve config: `short_etrade_config.json` (optional; shares API via `shared_etrade_api.py` — not a second daemon)
- Dual-PC roles: `deployment.json` — see `DUAL_PC_DEPLOYMENT.md` / `ROLE_FLIP_B.md`

## Not removed

- `etrade_worker.py`, `ensure_silent_worker.py`
- `short_worker.py` (manual one-shots only; not an autostart service)
- `etrade_api/`, day/swing strategy engines, pipeline agents
- Install/run scripts for the **main** background stack (not desktop GUI)
