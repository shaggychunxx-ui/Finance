#!/usr/bin/env python3
"""Keep E*TRADE access token active all day (until midnight ET).

E*TRADE rules:
  - Token dies at midnight US/Eastern → full browser OAuth
  - Token goes inactive after ~2h with no API calls → renew_access_token
  - Calling renew on a still-ACTIVE token can token_rejected (kill session)

This script only probes list-accounts (or renew if truly idle). Run every 10 min
via Task Scheduler so worker/phone never go 2h without a request.

Exit: 0 live OK, 1 dead session, 2 config error
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from etrade_runtime import resolve_live_root, ensure_sys_path  # noqa: E402


def main() -> int:
    try:
        decision = resolve_live_root()
    except Exception as exc:
        print(f"KEEPALIVE FAIL runtime: {exc}")
        return 2
    ensure_sys_path(decision.root)
    if str(decision.root) not in sys.path:
        sys.path.insert(0, str(decision.root))

    from etrade_api.config import load_config
    from etrade_api.oauth import session_is_live

    try:
        cfg = load_config(decision.config_path)
        cfg.token_path = decision.token_path
    except Exception as exc:
        print(f"KEEPALIVE FAIL config: {exc}")
        return 2

    ok, detail = session_is_live(cfg)
    blocker = decision.root / "output" / "LIVE_BLOCKER.txt"
    if ok:
        if blocker.exists():
            try:
                blocker.unlink()
            except OSError:
                pass
        print(f"KEEPALIVE OK {detail}")
        return 0

    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_text(
        "LIVE BLOCKER\n"
        f"reason: keepalive failed: {detail}\n"
        "fix: On GROMIT run begin_etrade_login.py ONLY if session is dead,\n"
        "      then finish_etrade_login.py <CODE>. Do NOT re-login on phone if PC is live.\n"
        "verify: python check_etrade_live_status.py\n",
        encoding="utf-8",
    )
    print(f"KEEPALIVE FAIL {detail}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
