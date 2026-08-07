# E*TRADE phone bridge — pairing (no secrets)

**Updated:** 2026-08-06  
**Service:** Finance `phone_bridge.py` (finance-phone-bridge **v1.5.8**)

## Active host

**GROMIT** runs the bridge (sole Finance host). Live root: `%USERPROFILE%\Finance`.

| Field | Value |
|-------|--------|
| **Base URL (phone Wi‑Fi)** | `http://192.168.1.155:8787` |
| **Port** | `8787` |
| **Health** | `GET /health` (no auth) → `ok: true` |

**Bridge token:** only in live `C:\Users\shagg\Finance\phone_bridge_config.json` (`bridge_token`).  
Do **not** put the token in git / STATUS / this file.

**Durable:** scheduled task `FinancePhoneBridge` (logon + every 5 min ensure).

## Start on GROMIT

```text
Finance\Start Phone Bridge.bat
```

Or:

```powershell
cd $env:USERPROFILE\Documents\GitHub\Finance
powershell -ExecutionPolicy Bypass -File .\install-phone-bridge.ps1
```

## Phone Setup (E*TRADE Trader)

1. Same Wi‑Fi as GROMIT (`192.168.1.x`)
2. **Setup** tab → Base URL `http://192.168.1.155:8787` + token from PC config → Save → Test
3. **Login** → Connect opens E\*TRADE browser OAuth on the PC path (needs real consumer key/secret first)
4. **Dashboard / Portfolio** Refresh over LAN

If Wi‑Fi IP changes, re-check `GET http://127.0.0.1:8787/health` → `phone_hint` on GROMIT.

## GitStatus bus (separate from LAN bridge)

Phone **Send** on Finance window → STATUS Next + **Act on: GROMIT**.  
Watcher: `FinanceWorkspaceWatch` every ~2 min.
