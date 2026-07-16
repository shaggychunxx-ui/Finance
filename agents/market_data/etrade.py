"""E*TRADE live quote helpers for agent probability and statistics."""

from __future__ import annotations

from typing import Any

from agents.enhancement import normalize_tradeable_symbol


def tradeable_symbol(symbol: str) -> str | None:
    return normalize_tradeable_symbol(symbol)


def session_return_from_quote(quote: dict[str, Any]) -> float | None:
    """Estimate today's session return from an E*TRADE quote payload."""
    prev = quote.get("previous_close")
    last = quote.get("last_trade")
    try:
        if prev is not None and last is not None and float(prev) > 0:
            return (float(last) - float(prev)) / float(prev)
    except (TypeError, ValueError):
        pass
    change_pct = quote.get("change_pct")
    try:
        if change_pct is not None:
            return float(change_pct) / 100.0
    except (TypeError, ValueError):
        pass
    return None


def bid_ask_spread_pct(quote: dict[str, Any]) -> float | None:
    bid = quote.get("bid")
    ask = quote.get("ask")
    last = quote.get("last_trade")
    try:
        if bid is None or ask is None:
            return None
        bid_f, ask_f = float(bid), float(ask)
        if bid_f <= 0 or ask_f <= 0 or ask_f < bid_f:
            return None
        mid = float(last) if last is not None else (bid_f + ask_f) / 2.0
        if mid <= 0:
            return None
        return round((ask_f - bid_f) / mid * 100.0, 4)
    except (TypeError, ValueError):
        return None


def quote_snapshot(symbol: str, quote: dict[str, Any], *, session_return: float | None = None) -> dict[str, Any]:
    ret = session_return if session_return is not None else session_return_from_quote(quote)
    spread = bid_ask_spread_pct(quote)
    trade_sym = tradeable_symbol(symbol) or str(quote.get("symbol") or symbol).upper()
    snap: dict[str, Any] = {
        "symbol": str(symbol).upper(),
        "tradeable_symbol": trade_sym,
        "data_source": "etrade",
        "last_trade": quote.get("last_trade"),
        "bid": quote.get("bid"),
        "ask": quote.get("ask"),
        "change_pct": quote.get("change_pct"),
        "previous_close": quote.get("previous_close"),
        "volume": quote.get("volume"),
        "session_return": round(ret, 6) if ret is not None else None,
        "bid_ask_spread_pct": spread,
        "fetched_at": quote.get("fetched_at"),
    }
    return snap


def merge_live_return_into_series(
    returns: list[float],
    quote: dict[str, Any],
    *,
    symbol: str,
) -> tuple[list[float], dict[str, Any]]:
    """Prefer E*TRADE for the latest daily return when a live quote is cached."""
    session_ret = session_return_from_quote(quote)
    snap = quote_snapshot(symbol, quote, session_return=session_ret)
    if session_ret is None or not returns:
        return returns, snap

    merged = list(returns)
    yahoo_last = merged[-1]
    snap["yahoo_last_return"] = round(yahoo_last, 6)
    snap["return_delta"] = round(session_ret - yahoo_last, 6)
    snap["live_return_applied"] = True
    merged[-1] = session_ret
    return merged, snap