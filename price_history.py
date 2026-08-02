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
# File-mtime ceiling used only as a soft secondary check for very old files.
BAR_CACHE_MAX_AGE_HOURS = 24
# Last bar may lag several calendar days (weekends / holidays) and still be "current".
BAR_CACHE_TIP_MAX_AGE_DAYS = 3
# When history is good but the tip is stale, re-download only this recent window and merge.
BAR_CACHE_INCREMENTAL_LOOKBACK_DAYS = 14
_yahoo_cache: dict[tuple[str, str], float | None] = {}
# Last fetch_daily_bars source: "cache" | "incremental" | "network" | "cache_fallback"
_last_bar_fetch_source: str = "cache"


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


def last_bar_fetch_source() -> str:
    """Source of the most recent fetch_daily_bars call (for throttle decisions)."""
    return _last_bar_fetch_source


def _bar_cache_fresh(path: Path, *, max_age_hours: int = BAR_CACHE_MAX_AGE_HOURS) -> bool:
    """Legacy file-mtime freshness (kept for callers / tests). Prefer tip-based checks."""
    if not path.exists():
        return False
    try:
        age_h = (
            datetime.now(timezone.utc)
            - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        ).total_seconds() / 3600
        return age_h <= max_age_hours
    except OSError:
        return False


def _write_bar_cache(path: Path, symbol: str, bars: list[dict[str, Any]]) -> None:
    """Compact JSON write — multi-decade series are large; indent slows load/save."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "symbol": symbol,
        "bars": bars,
        "interval": "1d",
        "fetched_at": _now_iso(),
        "bar_count": len(bars),
    }
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def load_daily_bars(symbol: str) -> list[dict[str, Any]]:
    """Load cached daily OHLCV bars for a symbol (empty if missing)."""
    path = BAR_CACHE_DIR / f"{symbol.upper()}.json"
    data = _load_json(path)
    if not isinstance(data, dict):
        return []
    bars = data.get("bars") or []
    return [row for row in bars if isinstance(row, dict)]


def _bar_day_key(row: dict[str, Any]) -> str | None:
    at = _parse_iso(row.get("at"))
    if at is None:
        return None
    return at.date().isoformat()


def merge_daily_bars(
    existing: list[dict[str, Any]],
    newer: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge bar lists by calendar day; *newer* overwrites same-day closes."""
    by_day: dict[str, dict[str, Any]] = {}
    for row in existing:
        key = _bar_day_key(row)
        if key is not None:
            by_day[key] = row
    for row in newer:
        key = _bar_day_key(row)
        if key is not None:
            by_day[key] = row
    return [by_day[k] for k in sorted(by_day)]


def _last_bar_datetime(bars: list[dict[str, Any]]) -> datetime | None:
    for row in reversed(bars):
        at = _parse_iso(row.get("at"))
        if at is not None:
            return at
    return None


def _first_bar_datetime(bars: list[dict[str, Any]]) -> datetime | None:
    for row in bars:
        at = _parse_iso(row.get("at"))
        if at is not None:
            return at
    return None


def bar_tip_is_fresh(
    bars: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    max_age_days: int = BAR_CACHE_TIP_MAX_AGE_DAYS,
) -> bool:
    """True when the last cached bar is recent enough (covers weekends/holidays)."""
    last = _last_bar_datetime(bars)
    if last is None:
        return False
    now = now or datetime.now(timezone.utc)
    # Compare on UTC calendar dates so "Friday bar on Monday" is age 3, not hours.
    age_days = (now.date() - last.date()).days
    return 0 <= age_days <= max(0, int(max_age_days))


def _min_cached_bars(*, days: int, start: datetime | None) -> int:
    # Enough bars for the request: ~trading days ≈ calendar * 0.7; keep a floor.
    if start is None:
        return max(40, min(days // 2, 2500))
    return max(40, min(days // 3, 4000))


def _cache_covers_request(
    cached: list[dict[str, Any]],
    *,
    days: int,
    start: datetime | None,
    min_cached: int,
) -> bool:
    if len(cached) < min_cached:
        return False
    if start is None:
        return True
    first = _first_bar_datetime(cached)
    if first is None:
        return False
    # Allow listing delay / IPO lag; reject caches that start far after requested history.
    return first <= start + timedelta(days=400)


def _yahoo_daily_bars(symbol: str, period1: int, period2: int) -> list[dict[str, Any]]:
    """Download daily closes from Yahoo for [period1, period2] unix range."""
    bars: list[dict[str, Any]] = []
    resp = requests.get(
        CHART_API.format(symbol=symbol),
        params={"period1": period1, "period2": period2, "interval": "1d"},
        headers=HEADERS,
        timeout=45,
    )
    if resp.status_code == 429:
        time.sleep(3)
        resp = requests.get(
            CHART_API.format(symbol=symbol),
            params={"period1": period1, "period2": period2, "interval": "1d"},
            headers=HEADERS,
            timeout=45,
        )
    resp.raise_for_status()
    result = (resp.json().get("chart") or {}).get("result") or []
    if not result:
        return bars
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
    return bars


def _period1_for_request(*, days: int, start: datetime | None) -> int:
    if start is not None:
        if start.tzinfo is None:
            return int(start.replace(tzinfo=timezone.utc).timestamp())
        return int(start.timestamp())
    return int((datetime.now(timezone.utc) - timedelta(days=days + 30)).timestamp())


def fetch_daily_bars(
    symbol: str,
    *,
    days: int = 400,
    use_cache: bool = True,
    start: datetime | None = None,
) -> list[dict[str, Any]]:
    """Fetch daily close bars from Yahoo and cache under output/history/bars/.

    *days* is the lookback window ending now. When *start* is set, *period1*
    uses that calendar date instead (for full history from e.g. 2000-01-01).

    Cache strategy (walk-forward-safe — only bars change, not signal logic):
      1. Pure disk hit when history coverage is enough and last bar is recent.
      2. Incremental tip refresh: keep long history, re-download ~2 weeks and merge.
      3. Full network download only when cache is missing/too short/starts too late.
    """
    global _last_bar_fetch_source

    sym = str(symbol or "").strip().upper()
    if not sym:
        _last_bar_fetch_source = "cache"
        return []

    days = max(1, int(days))
    min_cached = _min_cached_bars(days=days, start=start)
    cache_path = BAR_CACHE_DIR / f"{sym}.json"
    cached = load_daily_bars(sym) if use_cache else []

    if use_cache and _cache_covers_request(
        cached, days=days, start=start, min_cached=min_cached
    ):
        if bar_tip_is_fresh(cached):
            _last_bar_fetch_source = "cache"
            return cached

        # History is good; only the tip is stale — append recent bars.
        last = _last_bar_datetime(cached)
        if last is not None:
            tip_start = last - timedelta(days=BAR_CACHE_INCREMENTAL_LOOKBACK_DAYS)
            if start is not None and tip_start < start:
                tip_start = start
            period1 = int(tip_start.timestamp()) if tip_start.tzinfo else int(
                tip_start.replace(tzinfo=timezone.utc).timestamp()
            )
            period2 = int(datetime.now(timezone.utc).timestamp())
            try:
                tip = _yahoo_daily_bars(sym, period1, period2)
                if tip:
                    merged = merge_daily_bars(cached, tip)
                    _write_bar_cache(cache_path, sym, merged)
                    _last_bar_fetch_source = "incremental"
                    return merged
            except Exception:
                # Prefer serving slightly stale history over failing the whole run.
                if cached:
                    _last_bar_fetch_source = "cache_fallback"
                    return cached

    period1 = _period1_for_request(days=days, start=start)
    period2 = int(datetime.now(timezone.utc).timestamp())
    try:
        bars = _yahoo_daily_bars(sym, period1, period2)
    except Exception:
        if cached:
            _last_bar_fetch_source = "cache_fallback"
            return cached
        _last_bar_fetch_source = "network"
        return []

    if not bars:
        if cached:
            _last_bar_fetch_source = "cache_fallback"
            return cached
        _last_bar_fetch_source = "network"
        return []

    # If we had partial history that covers *start* better than a short full fetch
    # (rare), merge so we never shrink long-history cache accidentally.
    if cached and len(cached) > len(bars):
        bars = merge_daily_bars(cached, bars)

    _write_bar_cache(cache_path, sym, bars)
    _last_bar_fetch_source = "network"
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