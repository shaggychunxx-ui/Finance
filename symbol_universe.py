"""Curated liquid symbol universe for accuracy scoring and historical simulation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

from agent_fusion import AGENT_DOMAINS

SCREENER_API = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
TRENDING_API = "https://query1.finance.yahoo.com/v1/finance/trending/US"
HEADERS = {"User-Agent": "Mozilla/5.0 (Finance/1.0)"}

BENCHMARK_SCREENERS = (
    "most_actives",
    "day_gainers",
    "day_losers",
    "growth_technology_stocks",
    "undervalued_large_caps",
    "portfolio_anchors",
    "solid_large_growth_stocks",
    "solid_midcap_growth_stocks",
)

LIQUID_ETFS = frozenset({
    "SPY", "QQQ", "IWM", "DIA", "VOO", "VTI",
    "XLK", "XLE", "XLU", "XLF", "XLI", "XLY", "XLP", "XLRE", "XLV", "XLB", "XLC", "XRT", "XBI", "IBB",
    "ARKK", "GLD", "SLV", "TLT", "HYG", "UNG", "USO", "WEAT", "DBA", "JETS", "IYT",
    "VIXY", "XOM", "CVX",
})

LIQUID_EQUITIES = frozenset({
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "GOOG", "META", "TSLA", "AMD", "INTC",
    "JPM", "BAC", "WFC", "GS", "V", "MA", "UNH", "JNJ", "PG", "KO", "PEP",
    "WMT", "COST", "TGT", "HD", "LOW", "MCD", "NKE", "DIS", "NFLX", "CRM",
    "UPS", "FDX", "UNP", "CSX", "NSC", "DAL", "UAL", "AAL", "UBER",
    "NEE", "D", "SO", "EXC", "PEG", "VST", "AES", "ETR",
    "ZIM", "MATX", "BDRY",
    "MRNA", "PFE", "ABBV", "LLY",
    "BA", "LMT", "RTX", "NOC", "GD", "CAT",
    "BABA", "PDD",
})

LIQUID_INDICES = frozenset({"^GSPC", "^VIX", "^IXIC", "^DJI", "^RUT"})

MIN_LIQUID_PRICE_USD = 4.0
MAX_SYMBOL_LEN = 5


def _domain_tickers() -> frozenset[str]:
    tickers: set[str] = set()
    for domain in AGENT_DOMAINS.values():
        tickers.update(str(t) for t in domain.get("tickers", ()))
    return frozenset(tickers)


CURATED_LIQUID = LIQUID_ETFS | LIQUID_EQUITIES | LIQUID_INDICES | _domain_tickers()


def normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper().replace(".", "-")


def is_liquid_symbol(symbol: str, price: float | None = None) -> bool:
    """True when a symbol is in the curated liquid universe."""
    sym = normalize_symbol(symbol)
    if not sym:
        return False
    if sym.startswith("^"):
        return sym in LIQUID_INDICES
    if sym.endswith("-USD"):
        return True
    if sym in CURATED_LIQUID:
        return True
    if len(sym) > MAX_SYMBOL_LEN:
        return False
    if price is not None and price < MIN_LIQUID_PRICE_USD:
        return False
    return False


def is_benchmark_symbol(symbol: str, price: float | None = None) -> bool:
    """Broader eligibility for large historical backtests."""
    sym = normalize_symbol(symbol)
    if not sym or sym.startswith("^"):
        return sym in LIQUID_INDICES
    if is_liquid_symbol(sym, price=price):
        return True
    if len(sym) > 6 or not sym.replace("-", "").isalnum():
        return False
    if price is not None and price < MIN_LIQUID_PRICE_USD:
        return False
    return True


def _fetch_screener_symbols(scr_id: str, *, count: int = 250) -> list[str]:
    try:
        resp = requests.get(
            SCREENER_API,
            params={"scrIds": scr_id, "count": count},
            headers=HEADERS,
            timeout=25,
        )
        resp.raise_for_status()
        rows = resp.json()["finance"]["result"][0].get("quotes", [])
    except Exception:
        return []
    symbols: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = normalize_symbol(row.get("symbol", ""))
        price = row.get("regularMarketPrice")
        try:
            px = float(price) if price is not None else None
        except (TypeError, ValueError):
            px = None
        if is_benchmark_symbol(sym, price=px):
            symbols.append(sym)
    return symbols


def _fetch_trending_symbols() -> list[str]:
    try:
        resp = requests.get(TRENDING_API, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        rows = resp.json()["finance"]["result"][0].get("quotes", [])
    except Exception:
        return []
    return [
        normalize_symbol(row.get("symbol", ""))
        for row in rows
        if isinstance(row, dict) and is_benchmark_symbol(normalize_symbol(row.get("symbol", "")))
    ]


def _symbols_from_json_blob(data: Any, found: set[str]) -> None:
    if isinstance(data, dict):
        for key, value in data.items():
            if key in {"symbol", "ticker"} and isinstance(value, str):
                sym = normalize_symbol(value)
                if is_benchmark_symbol(sym):
                    found.add(sym)
            elif key == "tickers" and isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and is_benchmark_symbol(normalize_symbol(item)):
                        found.add(normalize_symbol(item))
            else:
                _symbols_from_json_blob(value, found)
    elif isinstance(data, list):
        for item in data:
            _symbols_from_json_blob(item, found)


def _collect_output_symbols(output_dir: Path, *, limit: int = 500) -> list[str]:
    if not output_dir.exists():
        return []
    found: set[str] = set()
    for path in sorted(output_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        _symbols_from_json_blob(data, found)
        if len(found) >= limit:
            break
    return sorted(found)[:limit]


def fetch_expanded_universe_symbols(*, max_symbols: int) -> list[str]:
    """Pull additional liquid US symbols from Yahoo screeners and trending."""
    symbols: list[str] = []
    seen: set[str] = set()

    def add(sym: str) -> None:
        s = normalize_symbol(sym)
        if not s or s in seen or not is_benchmark_symbol(s):
            return
        seen.add(s)
        symbols.append(s)

    per_screener = max(40, min(250, max_symbols // max(1, len(BENCHMARK_SCREENERS))))
    for scr_id in BENCHMARK_SCREENERS:
        for sym in _fetch_screener_symbols(scr_id, count=per_screener):
            add(sym)
            if len(symbols) >= max_symbols:
                return symbols[:max_symbols]
    for sym in _fetch_trending_symbols():
        add(sym)
        if len(symbols) >= max_symbols:
            return symbols[:max_symbols]
    return symbols[:max_symbols]


def collect_liquid_universe(
    *,
    portfolio: dict[str, Any] | None = None,
    predictions: dict[str, Any] | None = None,
    max_symbols: int = 40,
    extra: list[str] | None = None,
    output_dir: Path | None = None,
    expand_remote: bool = False,
) -> list[str]:
    """Build an ordered liquid symbol list from portfolio, predictions, and defaults."""
    symbols: list[str] = []
    seen: set[str] = set()
    use_benchmark = expand_remote or max_symbols > len(CURATED_LIQUID)

    def eligible(sym: str, price: float | None = None) -> bool:
        return is_benchmark_symbol(sym, price=price) if use_benchmark else is_liquid_symbol(sym, price=price)

    def add(sym: str, *, price: float | None = None) -> None:
        s = normalize_symbol(sym)
        if not s or s in seen or not eligible(s, price=price):
            return
        seen.add(s)
        symbols.append(s)

    if isinstance(portfolio, dict):
        for row in portfolio.get("holdings") or portfolio.get("positions") or []:
            if isinstance(row, dict):
                px = row.get("price") or row.get("lastPrice")
                try:
                    price = float(px) if px is not None else None
                except (TypeError, ValueError):
                    price = None
                add(row.get("symbol", ""), price=price)

    if isinstance(predictions, dict):
        for rows in (predictions.get("predictions") or {}).values():
            for row in rows or []:
                if isinstance(row, dict):
                    add(row.get("symbol", ""))

    if output_dir is not None:
        for sym in _collect_output_symbols(output_dir, limit=max_symbols):
            add(sym)

    for sym in sorted(CURATED_LIQUID):
        add(sym)
        if len(symbols) >= max_symbols:
            return symbols[:max_symbols]

    for sym in extra or []:
        add(sym)
        if len(symbols) >= max_symbols:
            break

    if use_benchmark and len(symbols) < max_symbols:
        for sym in fetch_expanded_universe_symbols(max_symbols=max_symbols):
            add(sym)
            if len(symbols) >= max_symbols:
                break

    return symbols[:max_symbols]