"""E*TRADE API helper package: OAuth 1.0a authentication + market data client."""

from __future__ import annotations

from typing import Any

__all__ = [
    "ETradeClient",
    "ETradeConfig",
    "load_config",
    "ETradeTokens",
    "authenticate",
    "load_tokens",
    "renew_access_token",
    "revoke_access_token",
    "touch_tokens",
    "is_expired_for_day",
    "needs_renewal",
]


def __getattr__(name: str) -> Any:
    if name == "ETradeClient":
        from .client import ETradeClient

        return ETradeClient
    if name in {"ETradeConfig", "load_config"}:
        from .config import ETradeConfig, load_config

        return ETradeConfig if name == "ETradeConfig" else load_config
    if name in {
        "ETradeTokens",
        "authenticate",
        "load_tokens",
        "renew_access_token",
        "revoke_access_token",
        "touch_tokens",
        "is_expired_for_day",
        "needs_renewal",
    }:
        from . import oauth as oauth_mod

        return getattr(oauth_mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")