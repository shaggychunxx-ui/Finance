"""Cached Yahoo Finance chart + options client shared across agents."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import requests

CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
OPTIONS_API = "https://query1.finance.yahoo.com/v7/finance/options/{symbol}"
CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"
COOKIE_BOOTSTRAP_URL = "https://fc.yahoo.com"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}

_session_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
_options_cache: dict[str, dict[str, Any]] = {}
_last_request_at = 0.0
_http_session: requests.Session | None = None
_yahoo_crumb: str | None = None


def clear_yahoo_session_cache() -> None:
    """Drop cached chart/options responses (call at pipeline session start/end)."""
    global _last_request_at, _http_session, _yahoo_crumb
    _session_cache.clear()
    _options_cache.clear()
    _last_request_at = 0.0
    _http_session = None
    _yahoo_crumb = None


def _throttle(delay_seconds: float) -> None:
    global _last_request_at
    if delay_seconds <= 0:
        return
    elapsed = time.monotonic() - _last_request_at
    if elapsed < delay_seconds:
        time.sleep(delay_seconds - elapsed)
    _last_request_at = time.monotonic()


def _yahoo_session() -> requests.Session:
    """Shared session with crumb cookie for Yahoo endpoints that require auth."""
    global _http_session, _yahoo_crumb
    if _http_session is not None and _yahoo_crumb:
        return _http_session
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    try:
        session.get(COOKIE_BOOTSTRAP_URL, timeout=12, allow_redirects=True)
        crumb_resp = session.get(CRUMB_URL, timeout=12)
        crumb_resp.raise_for_status()
        crumb = crumb_resp.text.strip()
        if crumb and "html" not in crumb.lower() and len(crumb) < 80:
            _yahoo_crumb = crumb
            _http_session = session
            return session
    except requests.RequestException:
        pass
    # Fallback unauthenticated session (chart API often still works)
    _http_session = session
    _yahoo_crumb = None
    return session


def _request_get(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    delay_seconds: float = 0.0,
    client_tag: str = "agent",
    timeout: int = 25,
    use_crumb: bool = False,
) -> requests.Response | None:
    global _http_session, _yahoo_crumb
    session = _yahoo_session()
    headers = {**DEFAULT_HEADERS, "User-Agent": f"{DEFAULT_HEADERS['User-Agent']} Finance-{client_tag}/1.0"}
    req_params = dict(params or {})
    if use_crumb and _yahoo_crumb:
        req_params.setdefault("crumb", _yahoo_crumb)
    _throttle(delay_seconds)
    try:
        resp = session.get(url, params=req_params or None, headers=headers, timeout=timeout)
        if resp.status_code in {401, 403} and use_crumb:
            # Refresh crumb once and retry
            _http_session = None
            _yahoo_crumb = None
            session = _yahoo_session()
            if _yahoo_crumb:
                req_params["crumb"] = _yahoo_crumb
            _throttle(delay_seconds)
            resp = session.get(url, params=req_params or None, headers=headers, timeout=timeout)
        if resp.status_code == 429:
            time.sleep(3)
            _throttle(delay_seconds)
            resp = session.get(url, params=req_params or None, headers=headers, timeout=timeout)
        return resp
    except requests.RequestException:
        return None


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

    params = {"interval": interval, "range": range_}
    try:
        resp = _request_get(
            CHART_API.format(symbol=symbol),
            params=params,
            delay_seconds=delay_seconds,
            client_tag=client_tag,
            timeout=timeout,
            use_crumb=False,
        )
        if resp is None:
            return None
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


def _normalize_option_leg(raw: dict[str, Any]) -> dict[str, Any] | None:
    try:
        strike = float(raw.get("strike") or 0)
    except (TypeError, ValueError):
        return None
    if strike <= 0:
        return None
    def _num(key: str, default: float = 0.0) -> float:
        try:
            val = raw.get(key)
            return float(val) if val is not None else default
        except (TypeError, ValueError):
            return default

    def _int(key: str) -> int:
        try:
            val = raw.get(key)
            return int(val) if val is not None else 0
        except (TypeError, ValueError):
            return 0

    return {
        "strike": strike,
        "volume": _int("volume"),
        "open_interest": _int("openInterest"),
        "last_price": _num("lastPrice"),
        "bid": _num("bid"),
        "ask": _num("ask"),
        "implied_volatility": _num("impliedVolatility"),
        "in_the_money": bool(raw.get("inTheMoney")),
        "contract_symbol": str(raw.get("contractSymbol") or ""),
    }


def fetch_option_chain(
    symbol: str,
    *,
    delay_seconds: float = 0.0,
    client_tag: str = "agent",
    timeout: int = 30,
) -> dict[str, Any] | None:
    """Nearest-expiration option chain (calls + puts) for smart-money flow agents.

    Returns::
        {
          "symbol": "SPY",
          "spot_price": 500.0,
          "expiration": unix_ts,
          "days_to_expiration": 3.2,
          "calls": [{strike, volume, open_interest, last_price, ask, bid, ...}],
          "puts":  [...],
        }
    """
    sym = str(symbol or "").strip().upper()
    if not sym:
        return None
    if sym in _options_cache:
        return _options_cache[sym]

    try:
        resp = _request_get(
            OPTIONS_API.format(symbol=sym),
            delay_seconds=delay_seconds,
            client_tag=client_tag,
            timeout=timeout,
            use_crumb=True,
        )
        if resp is None:
            return None
        resp.raise_for_status()
        payload = resp.json()
        result = (payload.get("optionChain") or {}).get("result") or []
        if not result:
            return None
        block = result[0]
        quote = block.get("quote") or {}
        options = block.get("options") or []
        if not options:
            return None
        nearest = options[0]
        exp_ts = nearest.get("expirationDate")
        dte: float | None = None
        if exp_ts is not None:
            try:
                exp_dt = datetime.fromtimestamp(int(exp_ts), tz=timezone.utc)
                dte = max(0.0, (exp_dt - datetime.now(timezone.utc)).total_seconds() / 86400.0)
            except (TypeError, ValueError, OSError):
                dte = None
        spot = quote.get("regularMarketPrice") or quote.get("postMarketPrice") or quote.get("preMarketPrice")
        try:
            spot_f = float(spot) if spot is not None else 0.0
        except (TypeError, ValueError):
            spot_f = 0.0
        if spot_f <= 0:
            meta = fetch_chart_meta(sym, range_="5d", interval="1d", delay_seconds=0, client_tag=client_tag)
            if meta and meta.get("price"):
                spot_f = float(meta["price"])
        calls = [
            leg
            for raw in (nearest.get("calls") or [])
            if isinstance(raw, dict) and (leg := _normalize_option_leg(raw)) is not None
        ]
        puts = [
            leg
            for raw in (nearest.get("puts") or [])
            if isinstance(raw, dict) and (leg := _normalize_option_leg(raw)) is not None
        ]
        if not calls and not puts:
            return None
        out = {
            "symbol": sym,
            "spot_price": spot_f,
            "expiration": exp_ts,
            "days_to_expiration": round(dte, 2) if dte is not None else None,
            "calls": calls,
            "puts": puts,
        }
        _options_cache[sym] = out
        return out
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError):
        return None