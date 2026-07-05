#!/usr/bin/env python3
"""Step 2: Paste E*TRADE verification code to complete login."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from requests_oauthlib import OAuth1Session

from etrade_api.config import ETradeConfig, build_config
from etrade_api.oauth import OAuthPending, finish_authorization, normalize_verifier

ROOT = Path(__file__).resolve().parent
PENDING_FILE = ROOT / "output" / "oauth_pending.json"


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("Usage: finish_etrade_login.py <verification_code>")
        return 1
    if not PENDING_FILE.exists():
        print("No pending login. Run begin_etrade_login.py first.")
        return 1

    raw = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    verifier = normalize_verifier(args[0])
    if not verifier:
        print("Verification code is empty.")
        return 1

    cfg = build_config(
        raw["consumer_key"],
        raw["consumer_secret"],
        sandbox=bool(raw.get("sandbox", True)),
        callback_url=raw.get("callback_url", ETradeConfig.callback_url),
        use_oob=bool(raw.get("use_oob", True)),
        token_path=Path(raw.get("token_path", "etrade_tokens.json")),
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
    PENDING_FILE.unlink(missing_ok=True)
    print(f"Logged in to E*TRADE ({'sandbox' if tokens.sandbox else 'production'}).")
    print(f"Tokens saved to {cfg.token_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())