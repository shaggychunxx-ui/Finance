#!/usr/bin/env python3
"""Step 2: Complete E*TRADE login — tokens always land on the LIVE runtime."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from requests_oauthlib import OAuth1Session

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

    if not args:
        print("Usage: finish_etrade_login.py <verification_code>")
        return 1

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
    if str(decision.root) not in sys.path:
        sys.path.insert(0, str(decision.root))

    from etrade_api.config import ETradeConfig, build_config
    from etrade_api.oauth import OAuthPending, finish_authorization, normalize_verifier

    pending_file = decision.pending_oauth_path
    if not pending_file.exists():
        # Fallback: legacy pending in script tree (pre-redirect) — still write tokens to live.
        legacy = Path(__file__).resolve().parent / "output" / "oauth_pending.json"
        if legacy.exists() and legacy != pending_file:
            print(f"NOTE: using legacy pending {legacy}; tokens will still save to live root.")
            pending_file = legacy
        else:
            print(f"No pending login at {decision.pending_oauth_path}")
            print("Run begin_etrade_login.py first (it targets the live runtime).")
            return 1

    raw = json.loads(pending_file.read_text(encoding="utf-8"))
    verifier = normalize_verifier(args[0])
    if not verifier:
        print("Verification code is empty.")
        return 1

    live_token = decision.token_path
    # Absolute token path under live root — ignore clone-relative paths from old pending files.
    pending_token = Path(raw.get("token_path") or live_token)
    if not pending_token.is_absolute() or (
        "github" in str(pending_token).lower() and "documents" in str(pending_token).lower()
    ):
        pending_token = live_token

    cfg = build_config(
        raw["consumer_key"],
        raw["consumer_secret"],
        sandbox=bool(raw.get("sandbox", True)),
        callback_url=raw.get("callback_url", ETradeConfig.callback_url),
        use_oob=bool(raw.get("use_oob", True)),
        config_path=decision.config_path,
        token_path=live_token,
    )
    oauth = OAuth1Session(
        client_key=cfg.consumer_key,
        client_secret=cfg.consumer_secret,
        resource_owner_key=raw["request_token"],
        resource_owner_secret=raw["request_token_secret"],
        callback_uri="oob" if cfg.use_oob else cfg.callback_url,
        signature_method="HMAC-SHA1",
    )
    pending = OAuthPending(config=cfg, oauth=oauth, authorize_url=raw.get("authorize_url", ""))
    tokens = finish_authorization(pending, verifier)

    # Clean pending on live root and legacy path if used.
    decision.pending_oauth_path.unlink(missing_ok=True)
    if pending_file != decision.pending_oauth_path:
        pending_file.unlink(missing_ok=True)

    print(f"Logged in to E*TRADE ({'sandbox' if tokens.sandbox else 'production'}).")
    print(f"Tokens saved to LIVE runtime: {live_token}")
    print("Verify with: python check_etrade_live_status.py")
    print("(Only trust LIVE STATUS: OK from that script — not a clone-only login.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
