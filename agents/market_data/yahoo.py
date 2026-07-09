"""Cached Yahoo Finance chart client shared across agents."""

from __future__ import annotations

import time
from typing import Any

import requests

CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
DEFAULT_HEADERS = {"User-Agent": "Finance-Agents/1.0 (shaggychunxx@gmail.com)"}

_session_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
_last_request_at = 0.0


def clear_yahoo_session_cache() -> None:
    """Drop cached chart responses (call at pipeline session start/end)."""
    global _last_request_at
    _session_cache.clear()
    _last_request_at = 0.0


def _throttle(delay_seconds: float) -> None:
    global _last_request_at
    if delay_seconds <= 0:
        return
    elapsed = time.monotonic() - _last_request_at
    if elapsed < delay_seconds:
        time.sleep(delay_seconds - elapsed)
    _last_request_at = time.monotonic()


def _chart_payload(
    symbol: str,
    *,
    range_: str = "6mo",
    interval: str = "1d",
    delay_seconds: float = 0.0,
    client_tag: str = "agent",
    timeout: int = 25,
) -> dict[str, Any] | None:
    key = (symbol.upper(), range_, interval)
    if key in _session_cache:
        return _session_cache[key]

    headers = {**DEFAULT_HEADERS, "User-Agent": f"Finance-{client_tag}/1.0"}
    params = {"interval": interval, "range": range_}
    _throttle(delay_seconds)
    try:
        resp = requests.get(
            CHART_API.format(symbol=symbol),
            params=params,
            headers=headers,
            timeout=timeout,
        )
        if resp.status_code == 429:
            time.sleep(3)
            _throttle(delay_seconds)
            resp = requests.get(
                CHART_API.format(symbol=symbol),
                params=params,
                headers=headers,
                timeout=timeout,
            )
        resp.raise_for_status()
        result = resp.json()["chart"]["result"][0]
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError):
        return None

    _session_cache[key] = result
    return result


def fetch_closes(
    symbol: str,
    *,
    range_: str = "6mo",
    interval: str = "1d",
    delay_seconds: float = 0.0,
    client_tag: str = "agent",
) -> list[float]:
    payload = _chart_payload(
        symbol,
        range_=range_,
        interval=interval,
        delay_seconds=delay_seconds,
        client_tag=client_tag,
    )
    if not payload:
        return []
    closes = payload.get("indicators", {}).get("quote", [{}])[0].get("close", [])
    return [float(c) for c in closes if c is not None]


def fetch_ohlcv(
    symbol: str,
    *,
    range_: str = "3mo",
    interval: str = "1d",
    delay_seconds: float = 0.0,
    client_tag: str = "agent",
) -> dict[str, list[float]]:
    payload = _chart_payload(
        symbol,
        range_=range_,
        interval=interval,
        delay_seconds=delay_seconds,
        client_tag=client_tag,
    )
    if not payload:
        return {"open": [], "high": [], "low": [], "close": [], "volume": []}
    quote = payload.get("indicators", {}).get("quote", [{}])[0]
    rows = zip(
        quote.get("open", []),
        quote.get("high", []),
        quote.get("low", []),
        quote.get("close", []),
        quote.get("volume", []),
    )
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    volumes: list[float] = []
    for o, h, l, c, v in rows:
        if o is None or h is None or l is None or c is None:
            continue
        opens.append(float(o))
        highs.append(float(h))
        lows.append(float(l))
        closes.append(float(c))
        volumes.append(float(v) if v is not None else 0.0)
    return {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes}


def fetch_chart_meta(
    symbol: str,
    *,
    range_: str = "1mo",
    interval: str = "1d",
    delay_seconds: float = 0.0,
    client_tag: str = "agent",
) -> dict[str, Any] | None:
    """Return last price and day/week change pct from a chart response."""
    payload = _chart_payload(
        symbol,
        range_=range_,
        interval=interval,
        delay_seconds=delay_seconds,
        client_tag=client_tag,
    )
    if not payload:
        return None
    meta = payload.get("meta") or {}
    quote = payload.get("indicators", {}).get("quote", [{}])[0]
    closes = [float(c) for c in quote.get("close", []) if c is not None]
    if not closes:
        return None
    price = float(meta.get("regularMarketPrice") or closes[-1])
    prev = float(meta.get("chartPreviousClose") or closes[-2] if len(closes) >= 2 else closes[-1])
    day_chg = ((price - prev) / prev * 100.0) if prev else 0.0
    week_chg = None
    if len(closes) >= 6 and closes[-6]:
        week_chg = (price - closes[-6]) / closes[-6] * 100.0
    volume = meta.get("regularMarketVolume")
    return {
        "symbol": symbol,
        "price": price,
        "day_chg_pct": round(day_chg, 3),
        "week_chg_pct": round(week_chg, 3) if week_chg is not None else None,
        "volume": int(volume) if volume is not None else None,
    }