"""OAuth 1.0a flow for E*TRADE: request token -> browser authorize -> access token."""

from __future__ import annotations

import json
import time
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from requests_oauthlib import OAuth1Session

from .config import AUTHORIZE_URL, ETradeConfig


@dataclass
class ETradeTokens:
    oauth_token: str
    oauth_token_secret: str
    sandbox: bool = True
    created_at: float = 0.0


def _oauth_session(config: ETradeConfig, **kwargs: Any) -> OAuth1Session:
    return OAuth1Session(
        client_key=config.consumer_key,
        client_secret=config.consumer_secret,
        callback_uri=config.callback_url if not config.use_oob else "oob",
        signature_method="HMAC-SHA1",
        **kwargs,
    )


def build_authorize_url(config: ETradeConfig, request_token: str) -> str:
    params = {"key": config.consumer_key, "token": request_token}
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def wait_for_callback_verifier(callback_url: str, timeout_seconds: int = 300) -> str:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from threading import Event, Thread

    parsed = urlparse(callback_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8765
    expected_path = parsed.path or "/callback"

    verifier_event = Event()
    verifier_holder: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path.split("?", 1)[0] != expected_path:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
                return

            query = parse_qs(urlparse(self.path).query)
            verifier = (query.get("oauth_verifier") or [""])[0]
            if not verifier:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing oauth_verifier")
                return

            verifier_holder["value"] = verifier
            verifier_event.set()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<h2>E*TRADE authorization complete.</h2>"
                b"<p>You can close this tab and return to the terminal.</p>"
            )

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    server = HTTPServer((host, port), CallbackHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if not verifier_event.wait(timeout_seconds):
            raise TimeoutError(f"Timed out waiting for OAuth callback at {callback_url}")
    finally:
        server.shutdown()

    return verifier_holder["value"]


def authenticate(
    config: ETradeConfig, verifier: str | None = None, open_browser: bool = True
) -> ETradeTokens:
    oauth = _oauth_session(config)
    request_token_url = f"{config.api_base}/oauth/request_token"
    fetch_response = oauth.fetch_request_token(request_token_url)
    request_token = fetch_response.get("oauth_token")
    if not request_token:
        raise RuntimeError(f"Request token missing from response: {fetch_response}")

    authorize_url = build_authorize_url(config, request_token)
    if config.use_oob:
        print("Open this URL, sign in, accept access, then paste the verifier code:")
        print(authorize_url)
        if open_browser:
            webbrowser.open(authorize_url)
        if not verifier:
            verifier = input("Enter oauth_verifier: ").strip()
    else:
        print(f"Listening for callback at {config.callback_url}")
        print("Opening browser for E*TRADE authorization...")
        if open_browser:
            webbrowser.open(authorize_url)
        else:
            print(authorize_url)
        if not verifier:
            verifier = wait_for_callback_verifier(config.callback_url)

    if not verifier:
        raise ValueError("oauth_verifier is required")

    access_token_url = f"{config.api_base}/oauth/access_token"
    access_tokens = oauth.fetch_access_token(access_token_url, verifier=verifier)
    tokens = ETradeTokens(
        oauth_token=access_tokens["oauth_token"],
        oauth_token_secret=access_tokens["oauth_token_secret"],
        sandbox=config.sandbox,
        created_at=time.time(),
    )
    _save_tokens(config.token_path, tokens)
    return tokens


def renew_access_token(config: ETradeConfig, tokens: ETradeTokens) -> ETradeTokens:
    oauth = OAuth1Session(
        client_key=config.consumer_key,
        client_secret=config.consumer_secret,
        resource_owner_key=tokens.oauth_token,
        resource_owner_secret=tokens.oauth_token_secret,
        signature_method="HMAC-SHA1",
    )
    renew_url = f"{config.api_base}/oauth/renew_access_token"
    response = oauth.get(renew_url)
    response.raise_for_status()
    tokens.created_at = time.time()
    _save_tokens(config.token_path, tokens)
    return tokens


def revoke_access_token(config: ETradeConfig, tokens: ETradeTokens) -> None:
    oauth = OAuth1Session(
        client_key=config.consumer_key,
        client_secret=config.consumer_secret,
        resource_owner_key=tokens.oauth_token,
        resource_owner_secret=tokens.oauth_token_secret,
        signature_method="HMAC-SHA1",
    )
    revoke_url = f"{config.api_base}/oauth/revoke_access_token"
    response = oauth.get(revoke_url)
    response.raise_for_status()
    token_path = Path(config.token_path)
    if token_path.exists():
        token_path.unlink()


def _save_tokens(token_path: str | Path, tokens: ETradeTokens) -> None:
    path = Path(token_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(asdict(tokens), handle, indent=2)


def load_tokens(token_path: str | Path, sandbox: bool | None = None) -> ETradeTokens | None:
    path = Path(token_path)
    if not path.exists():
        return None

    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)

    tokens = ETradeTokens(
        oauth_token=raw.get("oauth_token", ""),
        oauth_token_secret=raw.get("oauth_token_secret", ""),
        sandbox=bool(raw.get("sandbox", True)),
        created_at=float(raw.get("created_at", 0.0)),
    )
    if sandbox is not None and tokens.sandbox != sandbox:
        return None
    if not tokens.oauth_token or not tokens.oauth_token_secret:
        return None
    return tokens
