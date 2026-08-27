# 052 — Re-entering OAuth should be automatic

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

Phone Send: "Re enteing Oath sould be autmatic"

## Result

Midnight ET re-login is automatic on GROMIT. Watchdog + keepalive call `complete_etrade_oauth.py`, which drives taskbar Chrome Default (never Playwright / blank profile): Log on → left Accept → harvest verifier → `finish_etrade_login.py`.

**Tonight (2026-08-26 ~21:29 PT):** after midnight expiry, auto-OAuth completed. `check_etrade_live_status.py` → **LIVE STATUS: OK** (production). Worker log: `Connected to E*TRADE (production)`.

**Why it was not finishing before:** BitBlt screenshots captured an overlay HUD instead of Chrome (Log on/Accept looked missing). PrintWindow `PW_RENDERFULLCONTENT` captures the HWND. Stale login tab + logon-delay banner needed a fresh request token in the same tab. Overlay stole SendInput until Chrome was raised topmost.

Manual fallback still exists: `begin_etrade_login.py` / `finish_etrade_login.py <CODE>`. 2FA still needs the human/device if E*TRADE prompts it.

## Cache

- Live root: `C:\Users\shagg\Finance`
- Scripts: `complete_etrade_oauth.py`, `chrome_oauth_ui.py`
- Tests: `tests/test_chrome_oauth_ui.py` ALL_OK
- Verify: `python check_etrade_live_status.py` LIVE STATUS: OK
- Log: `output/oauth_auto.log` (no secrets)

## Do not

- Claim live without `check_etrade_live_status.py` OK
- Playwright / `--user-data-dir` blank Chrome profile
- Put tokens, verifier, or passwords in git/STATUS
- Open a new authorize tab while one is already on Accept/code
