"""Market API client for E*TRADE: quotes, options chains, and symbol lookup."""

from __future__ import annotations

from typing import Any

import requests
from requests_oauthlib import OAuth1

from .config import ETradeConfig
from .oauth import (
    ETradeTokens,
    is_expired_for_day,
    load_tokens,
    needs_renewal,
    renew_access_token,
    touch_tokens,
)


class ETradeClient:
    def __init__(self, config: ETradeConfig, tokens: ETradeTokens | None = None) -> None:
        self.config = config
        self.tokens = tokens or load_tokens(config.token_path, config.sandbox)
        if not self.tokens:
            raise RuntimeError(
                "No E*TRADE access token found. Run: python -m etrade_api auth"
            )

    def _session(self) -> requests.Session:
        session = requests.Session()
        session.auth = OAuth1(
            client_key=self.config.consumer_key,
            client_secret=self.config.consumer_secret,
            resource_owner_key=self.tokens.oauth_token,
            resource_owner_secret=self.tokens.oauth_token_secret,
            signature_method="HMAC-SHA1",
        )
        session.headers.update({"Accept": "application/json"})
        return session

    def _ensure_fresh_token(self) -> None:
        """Refresh the access token proactively, as soon as it expires.

        E*TRADE access tokens go inactive after ~2 hours without use and die
        outright at midnight US/Eastern. Rather than waiting for a 401 from
        the API, check both conditions before every request and renew
        immediately so agents polling E*TRADE never hit a stale token.
        """

        if is_expired_for_day(self.tokens):
            raise RuntimeError(
                "E*TRADE access token expired (past midnight US/Eastern). "
                "Run: python -m etrade_api auth"
            )
        if needs_renewal(self.tokens):
            self.tokens = renew_access_token(self.config, self.tokens)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        self._ensure_fresh_token()
        url = f"{self.config.api_base}{path}"
        response = self._session().request(method, url, timeout=30, **kwargs)
        if response.status_code == 401:
            self.tokens = renew_access_token(self.config, self.tokens)
            response = self._session().request(method, url, timeout=30, **kwargs)
        response.raise_for_status()
        self.tokens = touch_tokens(self.config, self.tokens)
        if not response.text:
            return {}
        return response.json()

    def get_quotes(
        self,
        symbols: list[str] | str,
        detail_flag: str = "ALL",
        require_earnings_date: bool = False,
        skip_mini_options_check: bool = False,
    ) -> dict[str, Any]:
        if isinstance(symbols, (list, tuple)):
            symbol_str = ",".join(symbols)
        else:
            symbol_str = symbols
        params = {
            "detailFlag": detail_flag,
            "requireEarningsDate": str(require_earnings_date).lower(),
            "skipMiniOptionsCheck": str(skip_mini_options_check).lower(),
        }
        return self._request("GET", f"/v1/market/quote/{symbol_str}.json", params=params)

    def lookup(self, search: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/market/lookup/{search}.json")

    def get_option_expire_dates(
        self, symbol: str, expiry_type: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"symbol": symbol}
        if expiry_type:
            params["expiryType"] = expiry_type
        return self._request("GET", "/v1/market/optionexpiredate.json", params=params)

    def get_option_chains(
        self,
        symbol: str,
        *,
        expiry_year: int | None = None,
        expiry_month: int | None = None,
        expiry_day: int | None = None,
        strike_price_near: float | None = None,
        no_of_strikes: int | None = None,
        option_category: str | None = None,
        chain_type: str | None = None,
        price_type: str | None = None,
        skip_adjusted: bool | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"symbol": symbol}
        if expiry_year is not None:
            params["expiryYear"] = expiry_year
        if expiry_month is not None:
            params["expiryMonth"] = expiry_month
        if expiry_day is not None:
            params["expiryDay"] = expiry_day
        if strike_price_near is not None:
            params["strikePriceNear"] = strike_price_near
        if no_of_strikes is not None:
            params["noOfStrikes"] = no_of_strikes
        if option_category is not None:
            params["optionCategory"] = option_category
        if chain_type is not None:
            params["chainType"] = chain_type
        if price_type is not None:
            params["priceType"] = price_type
        if skip_adjusted is not None:
            params["skipAdjusted"] = str(skip_adjusted).lower()
        return self._request("GET", "/v1/market/optionchains.json", params=params)
