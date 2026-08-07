#!/usr/bin/env python3
"""Step 1: Open E*TRADE sign-in — always against the LIVE runtime root.

Tokens are written where the headless worker reads them
(%USERPROFILE%\\Finance or FINANCE_RUNTIME), never only into a GitHub clone.
"""

from __future__ import annotations

import json
import sys
import webbrowser
from pathlib import Path

from etrade_runtime import (
    assert_live_for_broker_action,
    ensure_sys_path,
    print_live_banner,
    resolve_live_root,
)


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    allow_non_live = "--allow-non-live" in args
    if allow_non_live:
        args = [a for a in args if a != "--allow-non-live"]
        print("WARNING: --allow-non-live set. Do NOT use for production money path.")

    try:
        decision = resolve_live_root(allow_non_live=allow_non_live)
    except FileNotFoundError as exc:
        print(exc)
        return 1

    print_live_banner(decision)
    if not allow_non_live:
        try:
            assert_live_for_broker_action(decision)
        except RuntimeError as exc:
            print(exc)
            return 1

    ensure_sys_path(decision.root)
    # Prefer live tree's etrade_api after path insert.
    if str(decision.root) not in sys.path:
        sys.path.insert(0, str(decision.root))

    from etrade_api.config import load_config
    from etrade_api.oauth import start_authorization

    config_path = decision.config_path
    if not config_path.exists():
        print(f"Missing E*TRADE config at {config_path}")
        print("Copy etrade_config.example.json → etrade_config.json on the LIVE runtime and add keys.")
        return 1

    cfg = load_config(config_path)
    # Force token file onto the live root (absolute) so finish + worker agree.
    live_token = decision.token_path
    cfg.token_path = live_token

    force = "--force" in args
    no_browser = "--no-browser" in args
    if force:
        args = [a for a in args if a != "--force"]
    if no_browser:
        args = [a for a in args if a != "--no-browser"]

    # CRITICAL: starting a new OAuth Accept can invalidate the current access token
    # (phone + PC share one consumer key). Never begin while session is still live.
    if not force:
        try:
            from etrade_api.oauth import session_is_live

            live_ok, detail = session_is_live(cfg)
            if live_ok:
                print("E*TRADE session is already LIVE — not starting a new OAuth.")
                print(f"  detail: {detail}")
                print("  Starting a new login can invalidate the working token (phone + PC).")
                print("  Use --force only if you intentionally want to re-auth.")
                print(f"  Verify: python \"{decision.root / 'check_etrade_live_status.py'}\"")
                return 0
            print(f"Session not live ({detail}) — starting OAuth...")
        except Exception as exc:
            print(f"Live probe failed ({exc}) — starting OAuth...")

    pending = start_authorization(cfg)
    oauth = pending.oauth
    token = getattr(oauth, "resource_owner_key", None) or oauth.token.get("oauth_token", "")
    secret = getattr(oauth, "resource_owner_secret", None) or oauth.token.get("oauth_token_secret", "")

    pending_file = decision.pending_oauth_path
    pending_file.parent.mkdir(parents=True, exist_ok=True)
    pending_file.write_text(
        json.dumps(
            {
                "request_token": token,
                "request_token_secret": secret,
                "authorize_url": pending.authorize_url,
                "sandbox": cfg.sandbox,
                "use_oob": cfg.use_oob,
                "consumer_key": cfg.consumer_key,
                "consumer_secret": cfg.consumer_secret,
                "callback_url": cfg.callback_url,
                "token_path": str(live_token),
                "live_root": str(decision.root),
                "config_path": str(config_path),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(pending.authorize_url)
    if no_browser:
        print("Browser NOT opened (--no-browser). Caller controls single open.")
    else:
        webbrowser.open(pending.authorize_url, new=0, autoraise=True)
        print("Browser opened (once).")
    print(f"Pending session: {pending_file}")
    print(f"Tokens will be saved to: {live_token}")
    print("After you sign in and click Accept, copy the verification code from E*TRADE.")
    print(f"Then run (from any dir):")
    print(f"  python \"{decision.root / 'finish_etrade_login.py'}\" <CODE>")
    print("Or from this clone (it will redirect to live root):")
    print("  python finish_etrade_login.py <CODE>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
