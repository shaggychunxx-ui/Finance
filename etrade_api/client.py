"""Market API client for E*TRADE: quotes, options chains, and symbol lookup."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import requests
from requests_oauthlib import OAuth1

from .accounts import parse_accounts, parse_balance, parse_portfolio
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
            try:
                self.tokens = renew_access_token(self.config, self.tokens)
            except Exception:
                # Token may still be active; proceed and let the API request decide.
                pass

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        self._ensure_fresh_token()
        url = f"{self.config.api_base}{path}"
        response = self._session().request(method, url, timeout=30, **kwargs)
        if response.status_code == 401:
            try:
                self.tokens = renew_access_token(self.config, self.tokens)
                response = self._session().request(method, url, timeout=30, **kwargs)
            except Exception as exc:
                raise RuntimeError(
                    "E*TRADE session expired. Disconnect and click Connect to sign in again."
                ) from exc
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

    def dump_json(self, payload: dict[str, Any]) -> str:
        return json.dumps(payload, indent=2, sort_keys=True)

    def list_accounts(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/v1/accounts/list.json")
        return parse_accounts(payload)

    def get_balance(self, account_id_key: str) -> dict[str, Any]:
        params = {"instType": "BROKERAGE", "realTimeNAV": "true"}
        payload = self._request("GET", f"/v1/accounts/{account_id_key}/balance", params=params)
        return parse_balance(payload)

    def get_portfolio(self, account_id_key: str) -> list[dict[str, Any]]:
        payload = self._request("GET", f"/v1/accounts/{account_id_key}/portfolio")
        return parse_portfolio(payload)

    @staticmethod
    def _client_order_id() -> str:
        return f"FIN{int(time.time())}{uuid.uuid4().hex[:6].upper()}"

    def build_equity_order(
        self,
        symbol: str,
        quantity: int,
        action: str,
        *,
        price_type: str = "MARKET",
        order_term: str = "GOOD_FOR_DAY",
        limit_price: float | None = None,
    ) -> dict[str, Any]:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        action = action.upper()
        if action not in {"BUY", "SELL", "SELL_SHORT"}:
            raise ValueError(f"unsupported action: {action}")

        instrument: dict[str, Any] = {
            "Product": {"securityType": "EQ", "symbol": symbol.upper()},
            "orderAction": action,
            "quantityType": "QUANTITY",
            "quantity": quantity,
        }
        order: dict[str, Any] = {
            "allOrNone": False,
            "priceType": price_type,
            "orderTerm": order_term,
            "marketSession": "REGULAR",
            "Instrument": [instrument],
        }
        if price_type == "LIMIT" and limit_price is not None:
            order["limitPrice"] = limit_price

        return {
            "orderType": "EQ",
            "clientOrderId": self._client_order_id(),
            "Order": [order],
        }

    def preview_equity_order(self, account_id_key: str, order_body: dict[str, Any]) -> dict[str, Any]:
        payload = {"PreviewOrderRequest": order_body}
        return self._request(
            "POST",
            f"/v1/accounts/{account_id_key}/orders/preview",
            json=payload,
        )

    def place_equity_order(
        self,
        account_id_key: str,
        order_body: dict[str, Any],
        preview_id: int,
    ) -> dict[str, Any]:
        payload = {
            "PlaceOrderRequest": {
                **order_body,
                "PreviewIds": [{"previewId": preview_id}],
            }
        }
        return self._request(
            "POST",
            f"/v1/accounts/{account_id_key}/orders/place",
            json=payload,
        )

    def preview_and_place_equity_order(
        self,
        account_id_key: str,
        symbol: str,
        quantity: int,
        action: str,
        *,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        order_body = self.build_equity_order(symbol, quantity, action)
        preview = self.preview_equity_order(account_id_key, order_body)
        preview_response = preview.get("PreviewOrderResponse", preview)
        preview_ids = preview_response.get("PreviewIds", [])
        preview_id = None
        if isinstance(preview_ids, list) and preview_ids:
            preview_id = preview_ids[0].get("previewId")
        elif isinstance(preview_ids, dict):
            preview_id = preview_ids.get("previewId")

        result: dict[str, Any] = {
            "symbol": symbol.upper(),
            "action": action.upper(),
            "quantity": quantity,
            "preview": preview,
            "preview_id": preview_id,
            "placed": None,
        }
        if dry_run or preview_id is None:
            return result

        placed = self.place_equity_order(account_id_key, order_body, int(preview_id))
        result["placed"] = placed
        return result
