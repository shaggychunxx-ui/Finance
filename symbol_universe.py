"""Curated liquid symbol universe for accuracy scoring and historical simulation."""

from __future__ import annotations

from typing import Any

from agent_fusion import AGENT_DOMAINS

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


def collect_liquid_universe(
    *,
    portfolio: dict[str, Any] | None = None,
    predictions: dict[str, Any] | None = None,
    max_symbols: int = 40,
    extra: list[str] | None = None,
) -> list[str]:
    """Build an ordered liquid symbol list from portfolio, predictions, and defaults."""
    symbols: list[str] = []
    seen: set[str] = set()

    def add(sym: str) -> None:
        s = normalize_symbol(sym)
        if not s or s in seen or not is_liquid_symbol(s):
            return
        seen.add(s)
        symbols.append(s)

    if isinstance(portfolio, dict):
        for row in portfolio.get("holdings") or portfolio.get("positions") or []:
            if isinstance(row, dict):
                add(row.get("symbol", ""))

    if isinstance(predictions, dict):
        for rows in (predictions.get("predictions") or {}).values():
            for row in rows or []:
                if isinstance(row, dict):
                    add(row.get("symbol", ""))

    for sym in sorted(CURATED_LIQUID):
        add(sym)
        if len(symbols) >= max_symbols:
            return symbols[:max_symbols]

    for sym in extra or []:
        add(sym)
        if len(symbols) >= max_symbols:
            break

    return symbols[:max_symbols]