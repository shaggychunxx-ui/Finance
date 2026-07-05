"""Fetch E*TRADE quotes for agent-selected symbols and enhance research outputs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agents.enhancement import (
    ENHANCED_QUOTES_FILE,
    apply_enhancements_to_agent_files,
    collect_enhancement_candidates,
    select_symbols,
)

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
CONFIG_PATH = ROOT / "etrade_config.json"

DEFAULT_SETTINGS = {
    "enabled": True,
    "max_symbols": 50,
    "min_priority": 0.4,
    "detail_flag": "ALL",
    "require_production": True,
}


def enhancement_settings(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    if not config_path.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_SETTINGS)
    merged = dict(DEFAULT_SETTINGS)
    section = raw.get("market_data_enhancement", {})
    if isinstance(section, dict):
        merged.update(section)
    return merged


def _parse_quote_entry(raw: dict[str, Any], *, fetched_at: str) -> dict[str, Any] | None:
    product = raw.get("Product", {}) or {}
    sym = (product.get("symbol") or raw.get("symbol") or "").strip().upper()
    if not sym:
        return None
    all_data = raw.get("All", {}) or {}
    fundamental = raw.get("Fundamental", {}) or {}
    last = all_data.get("lastTrade") or raw.get("lastTrade")
    bid = all_data.get("bid")
    ask = all_data.get("ask")
    change_pct = all_data.get("changeClosePercentage")
    change = all_data.get("changeClose")
    return {
        "symbol": sym,
        "last_trade": float(last) if last is not None else None,
        "bid": float(bid) if bid is not None else None,
        "ask": float(ask) if ask is not None else None,
        "change_pct": float(change_pct) if change_pct is not None else None,
        "change": float(change) if change is not None else None,
        "open": float(all_data.get("open")) if all_data.get("open") is not None else None,
        "high": float(all_data.get("high")) if all_data.get("high") is not None else None,
        "low": float(all_data.get("low")) if all_data.get("low") is not None else None,
        "volume": int(all_data.get("totalVolume")) if all_data.get("totalVolume") is not None else None,
        "previous_close": float(all_data.get("previousClose"))
        if all_data.get("previousClose") is not None
        else None,
        "company_name": all_data.get("companyName") or product.get("companyName"),
        "pe": float(fundamental.get("pe")) if fundamental.get("pe") is not None else None,
        "market_cap": float(all_data.get("marketCap")) if all_data.get("marketCap") is not None else None,
        "data_source": "etrade",
        "fetched_at": fetched_at,
    }


def fetch_etrade_quotes(
    client: Any,
    symbols: list[str],
    *,
    detail_flag: str = "ALL",
) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    fetched_at = datetime.now(timezone.utc).isoformat()
    quotes: dict[str, dict[str, Any]] = {}
    chunk_size = 25
    for i in range(0, len(symbols), chunk_size):
        batch = symbols[i : i + chunk_size]
        try:
            payload = client.get_quotes(
                batch,
                detail_flag=detail_flag,
                skip_mini_options_check=True,
            )
        except Exception:
            continue
        response = payload.get("QuoteResponse", payload)
        data = response.get("QuoteData")
        rows = data if isinstance(data, list) else [data] if data else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            parsed = _parse_quote_entry(row, fetched_at=fetched_at)
            if parsed:
                quotes[parsed["symbol"]] = parsed
    return quotes


def run_etrade_enhancement(
    *,
    config_path: Path = CONFIG_PATH,
    output_dir: Path | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    settings = enhancement_settings(config_path)
    out = output_dir or OUTPUT
    out.mkdir(parents=True, exist_ok=True)

    def say(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    if not settings.get("enabled", True):
        return {"skipped": True, "reason": "disabled"}

    candidates = collect_enhancement_candidates(out)
    symbols = select_symbols(
        candidates,
        max_symbols=int(settings.get("max_symbols", 50)),
        min_priority=float(settings.get("min_priority", 0.4)),
    )
    if not symbols:
        say("E*TRADE enhancement: no symbols selected by agents.")
        return {"skipped": True, "reason": "no_symbols", "candidates": len(candidates)}

    say(f"E*TRADE enhancement: {len(symbols)} symbol(s) requested by agents…")

    try:
        from etrade_worker import _connect_client
    except ImportError:
        say("E*TRADE enhancement skipped — worker module unavailable.")
        return {"skipped": True, "reason": "import_error"}

    client = _connect_client(config_path)
    if client is None:
        say("E*TRADE enhancement skipped — connect in the app first.")
        return {"skipped": True, "reason": "not_connected", "symbols_requested": symbols}

    if settings.get("require_production", True) and client.config.sandbox:
        say("E*TRADE enhancement skipped — production account required for subscribed market data.")
        return {"skipped": True, "reason": "sandbox", "symbols_requested": symbols}

    quotes = fetch_etrade_quotes(
        client,
        symbols,
        detail_flag=str(settings.get("detail_flag", "ALL")),
    )
    if not quotes:
        say("E*TRADE enhancement: quote fetch returned no data.")
        return {"skipped": True, "reason": "no_quotes", "symbols_requested": symbols}

    payload = {
        "meta": {
            "source": "etrade",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "symbol_count": len(quotes),
            "requested": symbols,
            "candidates": [
                {
                    "symbol": c["symbol"],
                    "priority": c["priority"],
                    "reasons": c.get("reasons", [])[:3],
                    "sources": c.get("sources", []),
                }
                for c in candidates[: min(30, len(candidates))]
            ],
        },
        "quotes": quotes,
    }
    (out / ENHANCED_QUOTES_FILE).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    updated = apply_enhancements_to_agent_files(quotes, out)
    say(f"E*TRADE enhancement: updated {len(quotes)} quotes, {updated} agent file(s).")
    return {
        "skipped": False,
        "symbols_requested": len(symbols),
        "quotes": len(quotes),
        "agent_files_updated": updated,
    }