"""
E*TRADE Account API client
==========================
A minimal OAuth 1.0a signed REST client for the E*TRADE Accounts API, used by
the Portfolio & Fund Manager agent to base trading decisions on a real
E*TRADE account's actual cash balance and holdings — instead of the agent's
own paper-trading ledger or a manually supplied ``--balance``.

E*TRADE's OAuth 1.0a login flow is interactive (it requires a browser
redirect and a verification code) and must be completed once, out of band,
to obtain a long-lived access token/secret pair. This client does not perform
that flow — it only signs and sends requests using credentials that have
already been obtained. Configure it via environment variables:

    ETRADE_CONSUMER_KEY
    ETRADE_CONSUMER_SECRET
    ETRADE_ACCESS_TOKEN
    ETRADE_ACCESS_TOKEN_SECRET
    ETRADE_ACCOUNT_ID_KEY  (optional; auto-discovered from /accounts/list if omitted)
    ETRADE_ENV             "sandbox" (default) or "live"

This client only reads account balance/position data. It does not place
orders — the portfolio agent treats its output as decisions/recommendations
based on the account's real assets, not as executed trades.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
import uuid
from base64 import b64encode
from typing import Any
from urllib.parse import quote

import requests

LIVE_BASE_URL = "https://api.etrade.com"
SANDBOX_BASE_URL = "https://apisb.etrade.com"


class ETradeConfigError(RuntimeError):
    """Raised when required E*TRADE API credentials are missing."""


class ETradeAPIError(RuntimeError):
    """Raised when the E*TRADE API request fails or returns an unexpected payload."""


def _percent_encode(value: Any) -> str:
    return quote(str(value), safe="~")


class ETradeClient:
    """Minimal OAuth 1.0a signed client for the E*TRADE Accounts API."""

    def __init__(
        self,
        consumer_key: str | None = None,
        consumer_secret: str | None = None,
        access_token: str | None = None,
        access_token_secret: str | None = None,
        account_id_key: str | None = None,
        sandbox: bool | None = None,
    ) -> None:
        self.consumer_key = consumer_key or os.environ.get("ETRADE_CONSUMER_KEY")
        self.consumer_secret = consumer_secret or os.environ.get("ETRADE_CONSUMER_SECRET")
        self.access_token = access_token or os.environ.get("ETRADE_ACCESS_TOKEN")
        self.access_token_secret = access_token_secret or os.environ.get("ETRADE_ACCESS_TOKEN_SECRET")
        self.account_id_key = account_id_key or os.environ.get("ETRADE_ACCOUNT_ID_KEY")
        env = os.environ.get("ETRADE_ENV", "sandbox").strip().lower()
        self.sandbox = sandbox if sandbox is not None else env != "live"
        self.base_url = SANDBOX_BASE_URL if self.sandbox else LIVE_BASE_URL

    @property
    def is_configured(self) -> bool:
        return bool(
            self.consumer_key and self.consumer_secret
            and self.access_token and self.access_token_secret
        )

    # ------------------------------------------------------------ OAuth 1.0a
    def _oauth_signature(self, method: str, url: str, params: dict[str, str]) -> dict[str, str]:
        oauth_params = {
            "oauth_consumer_key": self.consumer_key,
            "oauth_token": self.access_token,
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(int(time.time())),
            "oauth_nonce": uuid.uuid4().hex,
            "oauth_version": "1.0",
        }
        all_params = {**params, **oauth_params}
        param_str = "&".join(
            f"{_percent_encode(k)}={_percent_encode(all_params[k])}" for k in sorted(all_params)
        )
        base_str = "&".join([method.upper(), _percent_encode(url), _percent_encode(param_str)])
        signing_key = f"{_percent_encode(self.consumer_secret)}&{_percent_encode(self.access_token_secret)}"
        # HMAC-SHA1 is mandated by the OAuth 1.0a spec and is the only signature
        # method E*TRADE's API accepts — this is not a locally chosen weak hash
        # for secrets, but the required MAC algorithm for request signing. It is
        # used here purely to sign requests (proving possession of the consumer
        # secret / access token secret), not to hash or store sensitive data.
        signature = b64encode(
            hmac.new(
                signing_key.encode("utf-8"), base_str.encode("utf-8"), hashlib.sha1
            ).digest()
        ).decode("utf-8")
        oauth_params["oauth_signature"] = signature
        return oauth_params

    def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        if not self.is_configured:
            raise ETradeConfigError(
                "E*TRADE API credentials are not configured. Set ETRADE_CONSUMER_KEY, "
                "ETRADE_CONSUMER_SECRET, ETRADE_ACCESS_TOKEN, and ETRADE_ACCESS_TOKEN_SECRET."
            )
        params = params or {}
        url = f"{self.base_url}{path}"
        oauth_params = self._oauth_signature("GET", url, params)
        auth_header = "OAuth " + ", ".join(
            f'{k}="{_percent_encode(v)}"' for k, v in oauth_params.items()
        )
        try:
            resp = requests.get(
                url, params=params, headers={"Authorization": auth_header}, timeout=20,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            raise ETradeAPIError(f"E*TRADE API request failed for {path}: {exc}") from exc
        except ValueError as exc:
            raise ETradeAPIError(f"E*TRADE API returned a non-JSON response for {path}: {exc}") from exc

    # ------------------------------------------------------------ account data
    def _resolve_account_id_key(self) -> str:
        if self.account_id_key:
            return self.account_id_key
        data = self._get("/v1/accounts/list.json")
        try:
            accounts = data["AccountListResponse"]["Accounts"]["Account"]
        except (KeyError, TypeError) as exc:
            raise ETradeAPIError("Unexpected /accounts/list response — no accounts found.") from exc
        if isinstance(accounts, dict):
            accounts = [accounts]
        if not accounts:
            raise ETradeAPIError("E*TRADE account list is empty.")
        active = [a for a in accounts if str(a.get("accountStatus", "ACTIVE")).upper() == "ACTIVE"]
        chosen = (active or accounts)[0]
        self.account_id_key = chosen["accountIdKey"]
        return self.account_id_key

    def get_account_assets(self) -> dict[str, Any]:
        """Fetch the account's current cash balance and holdings.

        Returns:
            {
                "account_id_key": str,
                "cash": float,
                "positions": {symbol: {"quantity": float, "avg_cost": float}, ...},
            }
        """
        account_id_key = self._resolve_account_id_key()

        balance_data = self._get(
            f"/v1/accounts/{account_id_key}/balance.json",
            params={"instType": "BROKERAGE", "realTimeNAV": "true"},
        )
        try:
            computed = balance_data["BalanceResponse"]["Computed"]
        except (KeyError, TypeError) as exc:
            raise ETradeAPIError("Unexpected /accounts/balance response — missing balance data.") from exc
        cash = computed.get("cashAvailableForInvestment")
        if cash is None:
            cash = computed.get("cashBuyingPower")
        if cash is None:
            cash = computed.get("netCash", 0.0)
        cash = float(cash)

        positions: dict[str, dict[str, float]] = {}
        try:
            portfolio_data = self._get(f"/v1/accounts/{account_id_key}/portfolio.json")
        except ETradeAPIError:
            portfolio_data = {}
        account_portfolio = portfolio_data.get("PortfolioResponse", {}).get("AccountPortfolio", [])
        if isinstance(account_portfolio, dict):
            account_portfolio = [account_portfolio]
        for acct in account_portfolio:
            positions_list = acct.get("Position", [])
            if isinstance(positions_list, dict):
                positions_list = [positions_list]
            for pos in positions_list:
                symbol = (pos.get("Product") or {}).get("symbol") or pos.get("symbolDescription")
                # E*TRADE can return an explicit null for quantity; `or 0.0`
                # guards against that in addition to the missing-key default.
                quantity = float(pos.get("quantity") or 0.0)
                if not symbol or quantity <= 0:
                    continue
                avg_cost = float(pos.get("pricePaid", 0.0) or 0.0)
                positions[symbol] = {"quantity": quantity, "avg_cost": avg_cost}

        return {"account_id_key": account_id_key, "cash": cash, "positions": positions}
