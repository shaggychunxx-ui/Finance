# 050 — Etrader phone data current from GROMIT

**status:** done  
**target:** GROMIT  
**kind:** fix  
**handoff_count:** 0  
**max_handoffs:** 2  
**created:** 2026-08-26  
**updated:** 2026-08-26  
**created_by:** PHONE  
**updated_by:** GROMIT  

## Goal

Phone: "etrader phone app. data is not current. all data should update regularly from gromit."

## Result

Phone pack on GROMIT now reports **data current** from regular GROMIT refresh, not the 14-day frozen broker book.

**Cause:** `/health` probed retired BOXONE UNC shares (`\\10.10.10.1\...`) and hung ~21s. `serving_age_sec` used E*TRADE `fetched_at` 2026-08-12 (~14d) even after Yahoo marks were fresh. Wi‑Fi IP moved `192.168.1.155` → `192.168.1.177`. Duplicate `phone_bridge` starts from venv stub + ensure race.

**Fix (phone_bridge v1.6.2, live root):** skip UNC; `/health` local-only; `data_current` / `serving_age_sec` use last Yahoo marks or 15-min pack; Wi‑Fi IP first in `phone_hint`; Windows mutex so a second start exits.

**Verify (GROMIT live):** `GET http://127.0.0.1:8787/health` ~30ms, `version=1.6.2`, `data_current=true`, `phone_hint=http://192.168.1.177:8787`, marks `yahoo_public`. Tests `test_phone_bridge_publish.py` ALL_OK. Refresh every 15 min all hours; 16/16 lots marked.

**Still human:** E*TRADE OAuth (token expired past midnight ET) — broker book itself stays Aug-12 until login. Phone Setup Base URL must match `/health` `phone_hint` (DHCP). Token stays in live config only.

## Cache

- Live root: `C:\Users\shagg\Finance`
- Bridge: scheduled task `FinancePhoneBridge` :8787
- Tests: `python tests\test_phone_bridge_publish.py` ALL_OK
- Pairing: `outbox/phone-bridge-pairing.md` (no token)

## Do not

- Claim live/logged-in without `check_etrade_live_status.py` OK
- Put bridge token in git/STATUS
