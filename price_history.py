"""Local and remote historical prices for prediction scoring."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from app_paths import OUTPUT

HISTORY_ROOT = OUTPUT / "history"
PRICE_DIR = HISTORY_ROOT / "prices"
BAR_CACHE_DIR = HISTORY_ROOT / "bars"
CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Finance/1.0)"}
MAX_PRICE_POINTS = 2000
BAR_CACHE_MAX_AGE_HOURS = 24
_yahoo_cache: dict[tuple[str, str], float | None] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def record_prices(quotes: dict[str, float], *, recorded_at: str | None = None) -> int:
    """Append latest quote prices to per-symbol local history."""
    stamp = recorded_at or _now_iso()
    saved = 0
    for sym, price in quotes.items():
        symbol = str(sym or "").strip().upper()
        if not symbol:
            continue
        try:
            px = float(price)
        except (TypeError, ValueError):
            continue
        if px <= 0:
            continue
        path = PRICE_DIR / f"{symbol}.json"
        series = _load_json(path) or {"symbol": symbol, "points": []}
        points: list[dict[str, Any]] = list(series.get("points") or [])
        if points and points[-1].get("at", "")[:16] == stamp[:16]:
            points[-1]["price"] = round(px, 6)
        else:
            points.append({"at": stamp, "price": round(px, 6)})
        series["points"] = points[-MAX_PRICE_POINTS:]
        series["updated_at"] = _now_iso()
        _write_json(path, series)
        saved += 1
    return saved


def _local_price_at(symbol: str, target: datetime) -> float | None:
    path = PRICE_DIR / f"{symbol.upper()}.json"
    series = _load_json(path)
    if not series:
        return None
    points = series.get("points") or []
    if not points:
        return None

    best_after: tuple[float, datetime] | None = None
    best_any: tuple[float, datetime] | None = None
    for row in points:
        at = _parse_iso(row.get("at"))
        if at is None:
            continue
        try:
            price = float(row.get("price"))
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        delta = abs((at - target).total_seconds())
        if best_any is None or delta < abs((best_any[1] - target).total_seconds()):
            best_any = (price, at)
        if at >= target - timedelta(hours=1):
            if best_after is None or at < best_after[1]:
                best_after = (price, at)

    if best_after is not None:
        return best_after[0]
    if best_any is not None and abs((best_any[1] - target).total_seconds()) <= 36 * 3600:
        return best_any[0]
    return None


def _yahoo_price_near(symbol: str, target: datetime) -> float | None:
    cache_key = (symbol.upper(), target.strftime("%Y-%m-%dT%H"))
    if cache_key in _yahoo_cache:
        return _yahoo_cache[cache_key]

    age_days = max(0.0, (datetime.now(timezone.utc) - target).total_seconds() / 86400)
    interval = "1h" if age_days <= 10 else "1d"
    period1 = int((target - timedelta(days=5)).timestamp())
    period2 = int((target + timedelta(days=2)).timestamp())
    price: float | None = None
    try:
        resp = requests.get(
            CHART_API.format(symbol=symbol.upper()),
            params={"period1": period1, "period2": period2, "interval": interval},
            headers=HEADERS,
            timeout=20,
        )
        if resp.status_code == 429:
            time.sleep(2)
            resp = requests.get(
                CHART_API.format(symbol=symbol.upper()),
                params={"period1": period1, "period2": period2, "interval": interval},
                headers=HEADERS,
                timeout=20,
            )
        resp.raise_for_status()
        result = (resp.json().get("chart") or {}).get("result") or []
        if not result:
            _yahoo_cache[cache_key] = None
            return None
        timestamps = result[0].get("timestamp") or []
        closes = ((result[0].get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        target_ts = target.timestamp()
        best: tuple[float, float] | None = None
        for ts, close in zip(timestamps, closes):
            if close is None or ts is None:
                continue
            try:
                px = float(close)
            except (TypeError, ValueError):
                continue
            if px <= 0:
                continue
            delta = abs(float(ts) - target_ts)
            if best is None or delta < best[1]:
                best = (px, delta)
        if best is not None:
            price = best[0]
    except Exception:
        price = None

    _yahoo_cache[cache_key] = price
    return price


def resolve_price_at(
    symbol: str,
    target: datetime,
    *,
    latest_quote: float | None = None,
) -> tuple[float | None, str]:
    """Return price at horizon time: local history, then Yahoo, then latest quote."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return None, "missing"

    local = _local_price_at(sym, target)
    if local is not None:
        return local, "local_history"

    remote = _yahoo_price_near(sym, target)
    if remote is not None:
        record_prices({sym: remote}, recorded_at=target.isoformat())
        return remote, "yahoo_history"

    if latest_quote is not None and latest_quote > 0:
        return float(latest_quote), "latest_quote"
    return None, "unavailable"


def clear_yahoo_cache() -> None:
    _yahoo_cache.clear()


def _bar_cache_fresh(path: Path, *, max_age_hours: int = BAR_CACHE_MAX_AGE_HOURS) -> bool:
    if not path.exists():
        return False
    try:
        age_h = (datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)).total_seconds() / 3600
        return age_h <= max_age_hours
    except OSError:
        return False


def load_daily_bars(symbol: str) -> list[dict[str, Any]]:
    """Load cached daily OHLCV bars for a symbol (empty if missing)."""
    path = BAR_CACHE_DIR / f"{symbol.upper()}.json"
    data = _load_json(path)
    if not isinstance(data, dict):
        return []
    bars = data.get("bars") or []
    return [row for row in bars if isinstance(row, dict)]


def fetch_daily_bars(
    symbol: str,
    *,
    days: int = 400,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """Fetch daily close bars from Yahoo and cache under output/history/bars/."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return []

    cache_path = BAR_CACHE_DIR / f"{sym}.json"
    if use_cache and _bar_cache_fresh(cache_path):
        cached = load_daily_bars(sym)
        if len(cached) >= min(days // 2, 60):
            return cached

    period1 = int((datetime.now(timezone.utc) - timedelta(days=days + 30)).timestamp())
    period2 = int(datetime.now(timezone.utc).timestamp())
    bars: list[dict[str, Any]] = []
    try:
        resp = requests.get(
            CHART_API.format(symbol=sym),
            params={"period1": period1, "period2": period2, "interval": "1d"},
            headers=HEADERS,
            timeout=25,
        )
        if resp.status_code == 429:
            time.sleep(2)
            resp = requests.get(
                CHART_API.format(symbol=sym),
                params={"period1": period1, "period2": period2, "interval": "1d"},
                headers=HEADERS,
                timeout=25,
            )
        resp.raise_for_status()
        result = (resp.json().get("chart") or {}).get("result") or []
        if not result:
            return load_daily_bars(sym)
        timestamps = result[0].get("timestamp") or []
        closes = ((result[0].get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        for ts, close in zip(timestamps, closes):
            if close is None or ts is None:
                continue
            try:
                px = float(close)
            except (TypeError, ValueError):
                continue
            if px <= 0:
                continue
            at = datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
            bars.append({"at": at, "close": round(px, 6)})
    except Exception:
        return load_daily_bars(sym)

    if bars:
        _write_json(
            cache_path,
            {
                "symbol": sym,
                "bars": bars,
                "interval": "1d",
                "fetched_at": _now_iso(),
            },
        )
    return bars


def bar_closes(bars: list[dict[str, Any]]) -> list[float]:
    out: list[float] = []
    for row in bars:
        try:
            px = float(row.get("close"))
        except (TypeError, ValueError):
            continue
        if px > 0:
            out.append(px)
    return out


def bar_datetimes(bars: list[dict[str, Any]]) -> list[datetime]:
    out: list[datetime] = []
    for row in bars:
        at = _parse_iso(row.get("at"))
        if at is not None:
            out.append(at)
    return out


def bar_index_at_or_before(dates: list[datetime], target: datetime) -> int | None:
    best: int | None = None
    for i, at in enumerate(dates):
        if at <= target + timedelta(hours=18):
            best = i
    return best


def forward_return_pct(closes: list[float], start_idx: int, bars_forward: int) -> float | None:
    end_idx = start_idx + bars_forward
    if start_idx < 0 or end_idx >= len(closes):
        return None
    start = closes[start_idx]
    end = closes[end_idx]
    if start <= 0:
        return None
    return (end - start) / start * 100.0