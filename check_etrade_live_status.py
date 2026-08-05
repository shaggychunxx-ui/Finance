#!/usr/bin/env python3
"""Report whether LIVE trading path is actually connected.

ONLY inspects the canonical live runtime (%USERPROFILE%\\Finance or
FINANCE_RUNTIME). Never greets a GitHub clone as "good to go".

Exit codes:
  0 = production connected (API ok + not day-expired token)
  1 = not live / blocked (expired, dry_run, paused, missing token, etc.)
  2 = usage / hard error
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from etrade_runtime import (
    assert_live_for_broker_action,
    ensure_sys_path,
    print_live_banner,
    resolve_live_root,
    worker_log_connection_state,
)


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def main() -> int:
    try:
        decision = resolve_live_root(allow_non_live=False)
    except FileNotFoundError as exc:
        print(f"LIVE STATUS: FAIL — {exc}")
        return 1

    print_live_banner(decision)
    try:
        assert_live_for_broker_action(decision)
    except RuntimeError as exc:
        print(f"LIVE STATUS: FAIL — {exc}")
        return 1

    ensure_sys_path(decision.root)
    # Import API helpers from the live tree when possible.
    sys.path.insert(0, str(decision.root))
    from etrade_api.config import load_config  # noqa: WPS433
    from etrade_api.oauth import (  # noqa: WPS433
        is_expired_for_day,
        load_tokens,
        needs_renewal,
        renew_access_token,
    )
    from etrade_api.client import ETradeClient  # noqa: WPS433

    cfg_path = decision.config_path
    if not cfg_path.exists():
        print(f"LIVE STATUS: FAIL — missing config {cfg_path}")
        return 1

    raw = _load_json(cfg_path)
    bg = raw.get("background_worker") if isinstance(raw.get("background_worker"), dict) else {}
    flags = {
        "sandbox": bool(raw.get("sandbox", True)),
        "dry_run": bool(bg.get("dry_run", True)),
        "prefer_dry_run": bool(bg.get("prefer_dry_run", False)),
        "auto_execute": bool(bg.get("auto_execute", False)),
        "live_trading": bool(bg.get("live_trading", False)),
        "day_trading": bool(bg.get("day_trading", False)),
        "paused": bool(bg.get("paused", False)),
    }
    sel = raw.get("selected_account") if isinstance(raw.get("selected_account"), dict) else {}
    print("flags:", json.dumps(flags, sort_keys=True))
    print("account:", sel.get("display_label") or "(none selected)")

    try:
        config = load_config(cfg_path)
    except Exception as exc:
        print(f"LIVE STATUS: FAIL — config error: {exc}")
        return 1

    # Force token path under live root even if config has a relative path.
    token_path = Path(config.token_path)
    if not token_path.is_absolute():
        token_path = (decision.root / token_path).resolve()
    # Prefer canonical live token file.
    if token_path.parent != decision.root:
        print(f"NOTE: config token_path={token_path}; checking live {decision.token_path} too")

    tokens = load_tokens(token_path, config.sandbox)
    if tokens is None and decision.token_path != token_path:
        tokens = load_tokens(decision.token_path, config.sandbox)
        token_path = decision.token_path

    if tokens is None:
        print(f"LIVE STATUS: FAIL — no tokens at {token_path}")
        print("  Run OAuth against the LIVE runtime only:")
        print(f"    python {decision.root / 'begin_etrade_login.py'}")
        return 1

    if is_expired_for_day(tokens):
        print("LIVE STATUS: FAIL — token past midnight ET (full re-login required)")
        return 1

    if needs_renewal(tokens):
        try:
            tokens = renew_access_token(config, tokens)
            print("token: renewed (idle timer)")
        except Exception as exc:
            print(f"LIVE STATUS: FAIL — token needs renewal but renew failed: {exc}")
            return 1

    try:
        client = ETradeClient(config, tokens)
        accounts = client.list_accounts()
        print(f"api: CONNECTED ({'sandbox' if config.sandbox else 'production'}) accounts={len(accounts)}")
    except Exception as exc:
        print(f"LIVE STATUS: FAIL — API connect error: {exc}")
        return 1

    log_state, log_detail = worker_log_connection_state(decision.worker_log_path)
    print(f"worker_log: {log_state}")
    print(f"  last: {log_detail[:200]}")

    blockers: list[str] = []
    if flags["sandbox"]:
        blockers.append("sandbox=true (not production)")
    if flags["paused"]:
        blockers.append("paused=true")
    if flags["dry_run"] or flags["prefer_dry_run"]:
        blockers.append("dry_run enabled")
    if not flags["auto_execute"]:
        blockers.append("auto_execute=false")
    if not flags["live_trading"] and not flags["day_trading"]:
        blockers.append("live_trading and day_trading both false")
    if log_state in {"expired", "waiting"}:
        blockers.append(f"worker_log={log_state} (worker may not have picked up tokens yet)")
    if log_state == "connected_sandbox" and not flags["sandbox"]:
        blockers.append("worker connected to sandbox but config is production")

    # Money path: production API + not day-expired is required for exit 0.
    # Worker log lag is a WARNING but if API works after token fix, exit 0 only when
    # flags allow live and not sandbox — still warn on log lag.
    if blockers and any(
        b.startswith("sandbox") or b.startswith("paused") or b.startswith("dry_run") or b.startswith("auto_execute")
        for b in blockers
    ):
        print("LIVE STATUS: NOT LIVE — " + "; ".join(blockers))
        return 1

    if blockers:
        print("LIVE STATUS: API OK but WARN — " + "; ".join(blockers))
        # Still 0 if production API works and flags are live; worker will catch up.
        if flags["sandbox"] or flags["paused"] or flags["dry_run"]:
            return 1

    print("LIVE STATUS: OK — production API connected; tokens on live runtime")
    print(f"  tokens: {token_path}")
    print(f"  checked_at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    if not flags["sandbox"] and not flags["dry_run"] and flags["auto_execute"] and not flags["paused"]:
        print("  config: live execution enabled (orders still require market hours / plan)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
