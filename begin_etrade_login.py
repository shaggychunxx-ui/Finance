#!/usr/bin/env python3
"""Step 1: Open E*TRADE sign-in and save session for finish_etrade_login.py."""

from __future__ import annotations

import json
import webbrowser
from pathlib import Path

from etrade_api.config import load_config
from etrade_api.oauth import start_authorization

ROOT = Path(__file__).resolve().parent
PENDING_FILE = ROOT / "output" / "oauth_pending.json"


def main() -> int:
    cfg = load_config()
    pending = start_authorization(cfg)
    oauth = pending.oauth
    token = getattr(oauth, "resource_owner_key", None) or oauth.token.get("oauth_token", "")
    secret = getattr(oauth, "resource_owner_secret", None) or oauth.token.get("oauth_token_secret", "")

    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(
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
                "token_path": str(cfg.token_path),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(pending.authorize_url)
    webbrowser.open(pending.authorize_url)
    print("Browser opened.")
    print("After you sign in and click Accept, copy the verification code from E*TRADE.")
    print("Then run: finish_etrade_login.py <CODE>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())