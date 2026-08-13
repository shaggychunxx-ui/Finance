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

# Worker-placed orders use this clientOrderId prefix (see _client_order_id).
WORKER_CLIENT_ORDER_PREFIX = "FIN"
# Only unlock shares by canceling worker protective exits — never MARKET/human tickets.
DEFAULT_CANCEL_PRICE_TYPES = frozenset(
    {"STOP", "STOP_LIMIT", "TRAILING_STOP_CNST", "TRAILING_STOP_PRCT", "LIMIT"}
)


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return value
    return []


def iter_open_order_legs(order: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten an E*TRADE Order into one dict per instrument leg."""
    oid = order.get("orderId")
    client_id = str(order.get("clientOrderId") or order.get("clientOrderID") or "")
    details = _as_list(order.get("OrderDetail"))
    detail = details[0] if details else {}
    price_type = str(detail.get("priceType") or order.get("priceType") or "").upper()
    legs: list[dict[str, Any]] = []
    instruments = detail.get("Instrument") if detail else None
    if not instruments:
        instruments = order.get("Instrument")
    for inst in _as_list(instruments):
        prod = inst.get("Product") or {}
        legs.append(
            {
                "order_id": oid,
                "client_order_id": client_id,
                "symbol": str(prod.get("symbol") or "").upper(),
                "action": str(inst.get("orderAction") or "").upper(),
                "price_type": price_type,
                "security_type": str(prod.get("securityType") or "").upper(),
            }
        )
    return legs


def skip_cancel_reason(
    leg: dict[str, Any],
    symbols: set[str],
    *,
    actions: set[str] | None = None,
    only_worker: bool = True,
    price_types: set[str] | frozenset[str] | None = DEFAULT_CANCEL_PRICE_TYPES,
) -> str | None:
    """Why this open-order leg must not be canceled, or None if cancel is allowed.

    Human UI sells (no FIN clientOrderId) and mutual funds are never canceled.
    """
    sym = str(leg.get("symbol") or "").upper()
    if not sym or (symbols and sym not in symbols):
        return "symbol_not_requested"
    action = str(leg.get("action") or "").upper()
    if actions is not None and action not in {a.upper() for a in actions}:
        return "action_filtered"
    sec = str(leg.get("security_type") or "").upper()
    if sec in {"MF", "MUTUAL_FUND"}:
        return "mutual_fund"
    try:
        from symbol_universe import is_mutual_fund_symbol

        if is_mutual_fund_symbol(sym):
            return "mutual_fund"
    except Exception:
        pass
    client_id = str(leg.get("client_order_id") or "")
    if only_worker and not client_id.upper().startswith(WORKER_CLIENT_ORDER_PREFIX):
        return "human_or_external"
    pt = str(leg.get("price_type") or "").upper()
    allowed_pts = {p.upper() for p in price_types} if price_types is not None else None
    if allowed_pts is not None and pt not in allowed_pts:
        return "price_type_filtered"
    return None


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

    def _reload_tokens_from_disk(self) -> None:
        """Always prefer the on-disk token — phone/worker/bridge share one file."""
        fresh = load_tokens(self.config.token_path, sandbox=None)
        if fresh:
            self.tokens = fresh

    def _ensure_fresh_token(self) -> None:
        """Reload disk tokens, then renew only if idle (inactive), not if still active.

        E*TRADE: renew is for *inactive* tokens (2h idle). Calling renew on a still-
        active token can yield oauth_problem=token_rejected and kill the session.
        """
        self._reload_tokens_from_disk()
        if not self.tokens:
            raise RuntimeError(
                "No E*TRADE access token found. Run: python begin_etrade_login.py"
            )
        if is_expired_for_day(self.tokens):
            raise RuntimeError(
                "E*TRADE access token expired (past midnight US/Eastern). "
                "Run: python begin_etrade_login.py"
            )
        if needs_renewal(self.tokens):
            try:
                self.tokens = renew_access_token(self.config, self.tokens)
            except Exception:
                # Still try the request — token may remain active until true reject.
                pass

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        self._ensure_fresh_token()
        url = f"{self.config.api_base}{path}"
        response = self._session().request(method, url, timeout=30, **kwargs)
        if response.status_code == 401:
            # 1) Another process may have written newer tokens (phone OAuth finish).
            self._reload_tokens_from_disk()
            response = self._session().request(method, url, timeout=30, **kwargs)
        if response.status_code == 401:
            # 2) Inactive token — renew once (do not renew on every 401 blindly first).
            try:
                self.tokens = renew_access_token(self.config, self.tokens)
                response = self._session().request(method, url, timeout=30, **kwargs)
            except Exception as exc:
                body = ""
                try:
                    body = (response.text or "")[:200]
                except Exception:
                    pass
                raise RuntimeError(
                    "E*TRADE session expired. Disconnect and click Connect to sign in again."
                    + (f" ({body})" if body else "")
                ) from exc
        if response.status_code == 401:
            raise RuntimeError(
                "E*TRADE session expired. Disconnect and click Connect to sign in again."
            )
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
        stop_price: float | None = None,
    ) -> dict[str, Any]:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        action = action.upper()
        if action not in {"BUY", "SELL", "SELL_SHORT", "BUY_TO_COVER"}:
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
        if price_type in {"LIMIT", "STOP_LIMIT"} and limit_price is not None:
            order["limitPrice"] = limit_price
        if price_type in {"STOP", "STOP_LIMIT"} and stop_price is not None:
            order["stopPrice"] = stop_price

        return {
            "orderType": "EQ",
            "clientOrderId": self._client_order_id(),
            "Order": [order],
        }

    def list_orders(
        self,
        account_id_key: str,
        *,
        status: str = "OPEN",
        count: int = 100,
    ) -> list[dict[str, Any]]:
        """List orders (default OPEN). Returns flattened order dicts."""
        params: dict[str, Any] = {"count": int(count)}
        if status:
            params["status"] = status
        payload = self._request(
            "GET",
            f"/v1/accounts/{account_id_key}/orders.json",
            params=params,
        )
        wrap = payload.get("OrdersResponse", payload)
        raw = wrap.get("Order") or wrap.get("Orders") or []
        if isinstance(raw, dict):
            raw = [raw]
        return list(raw)

    def cancel_order(self, account_id_key: str, order_id: int | str) -> dict[str, Any]:
        """Cancel an open order by id."""
        payload = {"CancelOrderRequest": {"orderId": int(order_id)}}
        return self._request(
            "PUT",
            f"/v1/accounts/{account_id_key}/orders/cancel",
            json=payload,
        )

    def cancel_open_orders_for_symbols(
        self,
        account_id_key: str,
        symbols: set[str] | list[str],
        *,
        actions: set[str] | None = None,
        only_worker: bool = True,
        price_types: set[str] | frozenset[str] | None = DEFAULT_CANCEL_PRICE_TYPES,
    ) -> list[dict[str, Any]]:
        """Cancel OPEN worker protective orders that lock shares for a planned SELL.

        Never cancels human UI tickets (no FIN clientOrderId) or mutual funds.
        """
        want = {str(s).upper() for s in symbols}
        results: list[dict[str, Any]] = []
        seen: set[Any] = set()
        for order in self.list_orders(account_id_key, status="OPEN", count=100):
            for leg in iter_open_order_legs(order):
                reason = skip_cancel_reason(
                    leg,
                    want,
                    actions=actions,
                    only_worker=only_worker,
                    price_types=price_types,
                )
                if reason is not None:
                    continue
                oid = leg.get("order_id")
                if oid is None or oid in seen:
                    continue
                seen.add(oid)
                try:
                    resp = self.cancel_order(account_id_key, oid)
                    results.append(
                        {
                            "order_id": oid,
                            "symbol": leg.get("symbol"),
                            "action": leg.get("action"),
                            "ok": True,
                            "response": resp,
                        }
                    )
                except Exception as exc:
                    results.append(
                        {
                            "order_id": oid,
                            "symbol": leg.get("symbol"),
                            "action": leg.get("action"),
                            "ok": False,
                            "error": str(exc),
                        }
                    )
                break
        return results

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
        price_type: str = "MARKET",
        limit_price: float | None = None,
    ) -> dict[str, Any]:
        order_body = self.build_equity_order(
            symbol,
            quantity,
            action,
            price_type=price_type,
            limit_price=limit_price,
        )
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
