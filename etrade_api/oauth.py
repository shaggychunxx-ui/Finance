"""OAuth 1.0a flow for E*TRADE: request token -> browser authorize -> access token."""

from __future__ import annotations

import json
import re
import time
import webbrowser
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse
from zoneinfo import ZoneInfo

import requests
from requests_oauthlib import OAuth1Session

from .config import AUTHORIZE_URL, ETradeConfig, credential_hint

# E*TRADE access tokens die at midnight US Eastern time regardless of use, and
# go "inactive" (renewable, but unusable until renewed) after this many
# minutes without a request. Renewal is attempted a little before the
# official 2-hour inactivity limit to avoid ever hitting a 401 in practice.
INACTIVITY_LIMIT_MINUTES = 120
RENEW_BEFORE_MINUTES = 10
OAUTH_HTTP_TIMEOUT = 20
_ETRADE_TIMEZONE: ZoneInfo | None = None


def etrade_timezone() -> ZoneInfo:
    """US/Eastern for E*TRADE token midnight expiry (lazy load; needs tzdata on Windows)."""

    global _ETRADE_TIMEZONE
    if _ETRADE_TIMEZONE is not None:
        return _ETRADE_TIMEZONE
    try:
        _ETRADE_TIMEZONE = ZoneInfo("America/New_York")
    except Exception:
        try:
            import tzdata  # noqa: F401

            _ETRADE_TIMEZONE = ZoneInfo("America/New_York")
        except Exception as exc:
            raise RuntimeError(
                "tzdata is required for E*TRADE timezone handling. "
                "Run: pip install tzdata (or launch via .venv\\Scripts\\pythonw.exe)."
            ) from exc
    return _ETRADE_TIMEZONE


@dataclass
class OAuthPending:
    config: ETradeConfig
    oauth: OAuth1Session
    authorize_url: str


@dataclass
class ETradeTokens:
    oauth_token: str
    oauth_token_secret: str
    sandbox: bool = True
    created_at: float = 0.0
    last_used_at: float = 0.0


def is_expired_for_day(tokens: ETradeTokens, now: float | None = None) -> bool:
    """E*TRADE access tokens die at midnight US/Eastern no matter what.

    Once the calendar day (Eastern time) the token was issued/renewed on has
    passed, the token cannot be renewed anymore and a full re-authentication
    (browser OAuth flow) is required.
    """

    if not tokens.created_at:
        return True
    now = time.time() if now is None else now
    tz = etrade_timezone()
    issued_day = datetime.fromtimestamp(tokens.created_at, tz=tz).date()
    current_day = datetime.fromtimestamp(now, tz=tz).date()
    return current_day > issued_day


def needs_renewal(tokens: ETradeTokens, now: float | None = None) -> bool:
    """True once the token is close to E*TRADE's 2-hour inactivity limit."""

    now = time.time() if now is None else now
    last_used = tokens.last_used_at or tokens.created_at
    if not last_used:
        return True
    idle_minutes = (now - last_used) / 60
    return idle_minutes >= (INACTIVITY_LIMIT_MINUTES - RENEW_BEFORE_MINUTES)


def _oauth_session(config: ETradeConfig, **kwargs: Any) -> OAuth1Session:
    return OAuth1Session(
        client_key=config.consumer_key,
        client_secret=config.consumer_secret,
        callback_uri=config.callback_url if not config.use_oob else "oob",
        signature_method="HMAC-SHA1",
        **kwargs,
    )


def build_authorize_url(config: ETradeConfig, request_token: str) -> str:
    return (
        f"{AUTHORIZE_URL}?key={config.consumer_key}"
        f"&token={requests.utils.quote(request_token, safe='')}"
    )


def format_oauth_error(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    body = ""
    if response is not None:
        try:
            body = response.text or ""
        except Exception:
            body = ""

    problem_match = re.search(r"oauth_problem=([^<\s]+)", body)
    problem = problem_match.group(1) if problem_match else ""

    if "consumer_key_rejected" in problem or "consumer_key_rejected" in body:
        return (
            "E*TRADE rejected your API credentials (consumer_key_rejected).\n\n"
            "This usually means the Consumer Key and Secret do not match, or they\n"
            "were regenerated on developer.etrade.com and the old secret no longer works.\n\n"
            "Fix:\n"
            "  1. Sign in at https://developer.etrade.com\n"
            "  2. Open your app (or create a new one)\n"
            "  3. Copy the Consumer Key AND Consumer Secret together (secret is shown once)\n"
            "  4. In Setup, paste both, pick Sandbox or Production to match the app, save\n"
            "  5. Keep “Use verification code (OOB)” checked if your app uses OOB\n"
            "  6. Click Connect again"
        )
    if "consumer_key_unknown" in problem or "consumer_key_unknown" in body:
        return (
            "E*TRADE rejected your Consumer Key (consumer_key_unknown).\n\n"
            "Check that you copied the key exactly from developer.etrade.com\n"
            "and that Sandbox/Production matches your developer app."
        )
    if "callback_rejected" in problem or "callback_rejected" in body:
        acceptable = re.search(r"oauth_acceptable_callback=([^<\s]+)", body)
        hint = acceptable.group(1) if acceptable else "oob"
        if hint == "oob":
            return (
                "E*TRADE rejected the callback URL (callback_rejected).\n\n"
                "Your developer app is set to Out-of-Band (OOB) mode.\n"
                "In Setup, enable “Use verification code (OOB)”, save, and connect again."
            )
        return (
            "E*TRADE rejected the callback URL (callback_rejected).\n\n"
            f"Set your developer app callback URL to:\n{hint}"
        )
    if "token_rejected" in problem or "token_rejected" in body:
        return (
            "E*TRADE rejected the verification code (token_rejected).\n\n"
            "The code may have expired or was already used. Click Connect again,\n"
            "complete sign-in in the browser, and paste the new code immediately."
        )
    if "permission_denied" in problem or "permission_denied" in body:
        return "E*TRADE authorization was declined. Approve access on the E*TRADE page and try again."
    if isinstance(exc, requests.exceptions.Timeout):
        return (
            f"E*TRADE did not respond within {OAUTH_HTTP_TIMEOUT} seconds.\n\n"
            "Check your internet connection and try again."
        )
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "Could not reach E*TRADE. Check your internet connection and try again."
    if problem:
        return f"E*TRADE authorization failed: {problem.replace(',', ', ')}"
    return str(exc)


def normalize_verifier(raw: str) -> str:
    text = (raw or "").strip().strip('"').strip("'")
    if not text:
        return ""

    if "oauth_verifier=" in text:
        query = parse_qs(urlparse(text).query)
        values = query.get("oauth_verifier") or []
        if values and values[0].strip():
            return values[0].strip()

    if text.lower().startswith("verification code"):
        _, _, rest = text.partition(":")
        text = rest.strip() or text

    match = re.search(r"\b([A-Za-z0-9]{4,16})\b", text)
    if match and len(text) <= 24:
        return match.group(1)
    return text


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

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, A003
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


def _probe_request_token(config: ETradeConfig) -> None:
    """Lightweight key check — request token only, no browser step."""

    oauth = _oauth_session(config)
    oauth.fetch_request_token(
        f"{config.api_base}/oauth/request_token",
        timeout=OAUTH_HTTP_TIMEOUT,
    )


def test_api_credentials(config: ETradeConfig) -> tuple[bool, str]:
    """Verify consumer key/secret with E*TRADE before opening the browser."""

    key_hint = credential_hint(config.consumer_key)
    env = "sandbox" if config.sandbox else "production"
    try:
        _probe_request_token(config)
        return True, (
            f"API keys accepted by E*TRADE ({env}, key {key_hint}). "
            "Click Connect to open the browser and finish sign-in."
        )
    except Exception as exc:
        msg = format_oauth_error(exc)
        problem = msg.lower()
        if "consumer_key_rejected" in problem:
            return False, (
                f"E*TRADE rejected these credentials (key {key_hint}).\n\n"
                "The Consumer Key and Secret must be copied together from "
                "developer.etrade.com — the secret is only shown once.\n\n"
                "Regenerate a new key+secret pair, paste both into Setup, "
                "click Save Settings, then Test API Keys."
            )
        if "consumer_key_unknown" in problem:
            other = ETradeConfig(
                consumer_key=config.consumer_key,
                consumer_secret=config.consumer_secret,
                sandbox=not config.sandbox,
                callback_url=config.callback_url,
                use_oob=config.use_oob,
                config_path=config.config_path,
                token_path=config.token_path,
            )
            other_env = "sandbox" if other.sandbox else "production"
            try:
                _probe_request_token(other)
                return False, (
                    f"Keys work in {other_env} but not {env} (key {key_hint}).\n\n"
                    f"In Setup, switch Environment to {other_env.title()}, "
                    "click Save Settings, then Connect again."
                )
            except Exception:
                pass
        return False, f"{msg}\n\n(Using key {key_hint} in {env}.)"


def start_authorization(config: ETradeConfig) -> OAuthPending:
    oauth = _oauth_session(config)
    request_token_url = f"{config.api_base}/oauth/request_token"
    try:
        fetch_response = oauth.fetch_request_token(
            request_token_url,
            timeout=OAUTH_HTTP_TIMEOUT,
        )
    except Exception as exc:
        raise RuntimeError(format_oauth_error(exc)) from exc

    request_token = fetch_response.get("oauth_token")
    if not request_token:
        raise RuntimeError(f"Request token missing from response: {fetch_response}")

    return OAuthPending(
        config=config,
        oauth=oauth,
        authorize_url=build_authorize_url(config, request_token),
    )


def finish_authorization(pending: OAuthPending, verifier: str) -> ETradeTokens:
    cleaned = normalize_verifier(verifier)
    if not cleaned:
        raise ValueError("Authorization cancelled — no verification code entered.")

    access_token_url = f"{pending.config.api_base}/oauth/access_token"
    try:
        access_tokens = pending.oauth.fetch_access_token(
            access_token_url,
            verifier=cleaned,
            timeout=OAUTH_HTTP_TIMEOUT,
        )
    except Exception as exc:
        raise RuntimeError(format_oauth_error(exc)) from exc

    issued_at = time.time()
    tokens = ETradeTokens(
        oauth_token=access_tokens["oauth_token"],
        oauth_token_secret=access_tokens["oauth_token_secret"],
        sandbox=pending.config.sandbox,
        created_at=issued_at,
        last_used_at=issued_at,
    )
    _save_tokens(pending.config.token_path, tokens)
    return tokens


def authenticate(
    config: ETradeConfig,
    verifier: str | None = None,
    open_browser: bool = True,
    verifier_prompt: Callable[[str], str] | None = None,
) -> ETradeTokens:
    if config.use_oob:
        pending = start_authorization(config)
        print("Open this URL, sign in, accept access, then paste the verifier code:")
        print(pending.authorize_url)
        if open_browser:
            webbrowser.open(pending.authorize_url)
        if not verifier:
            if verifier_prompt:
                verifier = verifier_prompt(pending.authorize_url)
            else:
                verifier = input("Enter oauth_verifier: ").strip()
        return finish_authorization(pending, verifier or "")

    pending = start_authorization(config)
    print(f"Listening for callback at {config.callback_url}")
    print("Opening browser for E*TRADE authorization...")
    if open_browser:
        webbrowser.open(pending.authorize_url)
    else:
        print(pending.authorize_url)
    if not verifier:
        verifier = wait_for_callback_verifier(config.callback_url)
    return finish_authorization(pending, verifier or "")


def renew_access_token(config: ETradeConfig, tokens: ETradeTokens) -> ETradeTokens:
    """Renew an inactive access token.

    Renewal resets E*TRADE's 2-hour inactivity timer, but it does *not* push
    back the midnight US/Eastern expiration of the token, so `created_at` is
    left untouched here.
    """

    oauth = OAuth1Session(
        client_key=config.consumer_key,
        client_secret=config.consumer_secret,
        resource_owner_key=tokens.oauth_token,
        resource_owner_secret=tokens.oauth_token_secret,
        signature_method="HMAC-SHA1",
    )
    renew_url = f"{config.api_base}/oauth/renew_access_token"
    response = oauth.get(renew_url, timeout=OAUTH_HTTP_TIMEOUT)
    response.raise_for_status()
    tokens.last_used_at = time.time()
    _save_tokens(config.token_path, tokens)
    return tokens


def touch_tokens(config: ETradeConfig, tokens: ETradeTokens) -> ETradeTokens:
    """Record that the token was just used successfully, resetting its idle clock."""

    tokens.last_used_at = time.time()
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
    response = oauth.get(revoke_url, timeout=OAUTH_HTTP_TIMEOUT)
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
        last_used_at=float(raw.get("last_used_at", raw.get("created_at", 0.0))),
    )
    if sandbox is not None and tokens.sandbox != sandbox:
        return None
    if not tokens.oauth_token or not tokens.oauth_token_secret:
        return None
    return tokens
