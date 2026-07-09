"""Collect symbols agents want enhanced via E*TRADE and merge quote data into outputs."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.platform_catalog import active_agent_sources

OUTPUT = Path(__file__).resolve().parent.parent / "output"
ENHANCED_QUOTES_FILE = "etrade_enhanced_quotes.json"

# Index / Google-style symbols → liquid E*TRADE tickers
ETF_PROXY: dict[str, str] = {
    "^GSPC": "SPY",
    "^IXIC": "QQQ",
    "^DJI": "DIA",
    "^RUT": "IWM",
    "^VIX": "VXX",
    ".INX": "SPY",
    ".IXIC": "QQQ",
    ".DJI": "DIA",
    "RUT": "IWM",
    "VIX": "VXX",
}

SYMBOL_KEYS = ("symbol", "yahoo_symbol", "google_symbol", "ticker", "underlying")


def normalize_tradeable_symbol(symbol: str) -> str | None:
    sym = (symbol or "").strip().upper()
    if not sym:
        return None
    if sym in ETF_PROXY:
        return ETF_PROXY[sym]
    if sym.startswith("^"):
        return ETF_PROXY.get(sym)
    if sym.startswith("."):
        return ETF_PROXY.get(sym)
    if ":" in sym:
        return None
    if sym.endswith("=F") or sym.endswith("-USD"):
        return None
    if len(sym) > 6:
        return None
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,5}", sym):
        return None
    return sym.replace(".", "-")


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _add_candidate(
    bucket: dict[str, dict[str, Any]],
    symbol: str,
    *,
    priority: float,
    reason: str,
    source: str,
) -> None:
    trade = normalize_tradeable_symbol(symbol)
    if not trade:
        return
    row = bucket.setdefault(
        trade,
        {"symbol": trade, "priority": 0.0, "reasons": [], "sources": set()},
    )
    row["priority"] = max(row["priority"], priority)
    if reason and reason not in row["reasons"]:
        row["reasons"].append(reason)
    row["sources"].add(source)


def load_enhanced_quotes(output_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return symbol → quote map from the latest E*TRADE enhancement file."""
    out = output_dir or OUTPUT
    data = _load_json(out / ENHANCED_QUOTES_FILE)
    if not isinstance(data, dict):
        return {}
    quotes = data.get("quotes")
    return quotes if isinstance(quotes, dict) else {}


def collect_proactive_enhancement_candidates(
    output_dir: Path | None = None,
    *,
    fused_horizons: tuple[str, ...] = ("24h", "1wk"),
    fused_limit: int = 15,
    portfolio_limit: int = 12,
    persistent_limit: int = 10,
) -> list[dict[str, Any]]:
    """Symbols from prior-cycle fused picks, portfolio holdings, and persistent bullish tickers."""
    out = output_dir or OUTPUT
    bucket: dict[str, dict[str, Any]] = {}

    fused = _load_json(out / "market_predictions.json")
    if fused:
        predictions = fused.get("predictions") if isinstance(fused.get("predictions"), dict) else {}
        seen_fused: set[str] = set()
        for horizon in fused_horizons:
            rows = predictions.get(horizon)
            if not isinstance(rows, list):
                continue
            for row in rows[:fused_limit]:
                if not isinstance(row, dict):
                    continue
                sym = str(row.get("symbol", "")).upper()
                if not sym or sym in seen_fused:
                    continue
                seen_fused.add(sym)
                rank = int(row.get("rank") or len(seen_fused))
                conf = float(row.get("confidence", 0.55) or 0.55)
                _add_candidate(
                    bucket,
                    sym,
                    priority=min(0.94, 0.9 - (rank - 1) * 0.025 + conf * 0.04),
                    reason=f"Fused pick #{rank} ({horizon})",
                    source="market_predictions",
                )

    portfolio = _load_json(out / "portfolio.json")
    if portfolio:
        holdings = portfolio.get("holdings") if isinstance(portfolio.get("holdings"), list) else []
        for index, row in enumerate(holdings[:portfolio_limit], start=1):
            if not isinstance(row, dict):
                continue
            conf = float(row.get("confidence", 0.6) or 0.6)
            _add_candidate(
                bucket,
                str(row.get("symbol", "")),
                priority=min(0.96, 0.9 + conf * 0.05 - (index - 1) * 0.01),
                reason=row.get("rationale", "Portfolio holding"),
                source="portfolio",
            )

    try:
        from analysis_history import get_persistent_bullish_tickers

        for row in get_persistent_bullish_tickers(top_n=persistent_limit):
            if not isinstance(row, dict):
                continue
            composite = float(row.get("composite", 0.0) or 0.0)
            _add_candidate(
                bucket,
                str(row.get("symbol", "")),
                priority=min(0.86, 0.68 + composite * 0.12),
                reason=f"Persistent bullish ({int(row.get('bullish_hits', 0))} cycles)",
                source="history",
            )
    except Exception:
        pass

    ctx = _load_json(out / "pipeline_run_context.json")
    if ctx:
        for item in (ctx.get("persistent_bullish_tickers") or [])[:persistent_limit]:
            if isinstance(item, dict):
                sym = str(item.get("symbol", ""))
                composite = float(item.get("composite", 0.0) or 0.0)
                priority = min(0.84, 0.66 + composite * 0.12)
                reason = "Pipeline memory bullish"
            else:
                sym = str(item)
                priority = 0.72
                reason = "Pipeline memory bullish"
            _add_candidate(bucket, sym, priority=priority, reason=reason, source="pipeline_memory")

    ranked = sorted(bucket.values(), key=lambda r: r["priority"], reverse=True)
    for row in ranked:
        row["sources"] = sorted(row["sources"])
    return ranked


def collect_enhancement_candidates(
    output_dir: Path | None = None,
    *,
    include_proactive: bool = True,
) -> list[dict[str, Any]]:
    """Read agent outputs and build a ranked list of symbols for E*TRADE quotes."""
    out = output_dir or OUTPUT
    bucket: dict[str, dict[str, Any]] = {}

    if include_proactive:
        for row in collect_proactive_enhancement_candidates(out):
            _add_candidate(
                bucket,
                row["symbol"],
                priority=float(row.get("priority", 0.7)),
                reason=", ".join(row.get("reasons", [])[:2]) or "Proactive",
                source=", ".join(row.get("sources", ["proactive"])),
            )

    for src in active_agent_sources(check_remote=False):
        data = _load_json(out / src["file"])
        if not data:
            continue
        agent_id = src["id"]
        source = src.get("label", agent_id)

        for req in data.get("enhance_symbols", []) or []:
            if isinstance(req, str):
                _add_candidate(bucket, req, priority=0.75, reason="Agent requested", source=source)
                continue
            if isinstance(req, dict):
                _add_candidate(
                    bucket,
                    str(req.get("symbol", "")),
                    priority=float(req.get("priority", 0.75)),
                    reason=str(req.get("reason", "Agent requested")),
                    source=source,
                )

        for opp in data.get("trading_opportunities", []) or []:
            score = float(opp.get("opportunity_score", 0.5))
            sym = opp.get("yahoo_symbol") or opp.get("symbol", "")
            _add_candidate(
                bucket,
                sym,
                priority=min(0.95, 0.45 + score * 0.4),
                reason=opp.get("rationale", "Trading opportunity"),
                source=source,
            )

        for pick in data.get("top_picks", []) or []:
            conf = float(pick.get("confidence", 0.55))
            _add_candidate(
                bucket,
                pick.get("symbol", ""),
                priority=min(0.9, 0.4 + conf * 0.45),
                reason=pick.get("rationale", "Top pick"),
                source=source,
            )

        for row in (data.get("top_gainers", []) or []) + (data.get("most_active", []) or []):
            pct = abs(float(row.get("day_chg_pct", 0) or 0))
            sym = row.get("symbol") or row.get("yahoo_symbol") or row.get("google_symbol", "")
            _add_candidate(
                bucket,
                sym,
                priority=min(0.85, 0.35 + pct * 0.04),
                reason="Active mover",
                source=source,
            )

        for sig in data.get("market_signals", []) or []:
            bias = str(sig.get("bias", "NEUTRAL")).upper()
            boost = 0.55 if bias == "BULLISH" else 0.45 if bias == "BEARISH" else 0.35
            for ticker in sig.get("tickers", []) or []:
                _add_candidate(
                    bucket,
                    ticker,
                    priority=boost,
                    reason=sig.get("reason", sig.get("sector", "Market signal")),
                    source=source,
                )

    plan = _load_json(out / "strategy_plan.json")
    if plan:
        for order in plan.get("orders", []) or []:
            _add_candidate(
                bucket,
                order.get("symbol", ""),
                priority=0.8,
                reason="Pending strategy order",
                source="strategy_plan",
            )

    day_plan = _load_json(out / "day_trade_plan.json")
    if day_plan:
        for order in day_plan.get("orders", []) or []:
            _add_candidate(
                bucket,
                order.get("symbol", ""),
                priority=0.85,
                reason="Day trade candidate",
                source="day_trade_plan",
            )

    ranked = sorted(bucket.values(), key=lambda r: r["priority"], reverse=True)
    for row in ranked:
        row["sources"] = sorted(row["sources"])
    return ranked


BIAS_ENHANCE_PRIORITY = {"BULLISH": 0.75, "BEARISH": 0.7, "NEUTRAL": 0.45}


def enhance_symbols_from_report(
    *,
    market_signals: list[dict[str, Any]] | None = None,
    trading_opportunities: list[dict[str, Any]] | None = None,
    top_picks: list[dict[str, Any]] | None = None,
    top_gainers: list[Any] | None = None,
    most_active: list[Any] | None = None,
    trending: list[str] | None = None,
    extra_items: list[tuple[str, float, str]] | None = None,
    agent_requests: list[dict[str, Any]] | None = None,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Build enhance_symbols from standard agent report fields."""
    items: list[tuple[str, float, str]] = []

    for req in agent_requests or []:
        if isinstance(req, dict):
            items.append(
                (
                    str(req.get("symbol", "")),
                    float(req.get("priority", 0.75)),
                    str(req.get("reason", "Agent requested")),
                )
            )

    for sig in market_signals or []:
        bias = str(sig.get("bias", "NEUTRAL")).upper()
        priority = BIAS_ENHANCE_PRIORITY.get(bias, 0.45)
        reason = sig.get("reason") or sig.get("sector") or "Market signal"
        for ticker in sig.get("tickers", []) or []:
            items.append((str(ticker), priority, str(reason)))

    for opp in trading_opportunities or []:
        score = float(opp.get("opportunity_score", 0.5))
        sym = opp.get("yahoo_symbol") or opp.get("symbol", "")
        items.append(
            (
                sym,
                min(0.95, 0.45 + score * 0.4),
                str(opp.get("rationale", "Trading opportunity")),
            )
        )

    for pick in top_picks or []:
        conf = float(pick.get("confidence", 0.55))
        items.append(
            (
                str(pick.get("symbol", "")),
                min(0.9, 0.4 + conf * 0.45),
                str(pick.get("rationale", "Top pick")),
            )
        )

    for row in (top_gainers or []) + (most_active or []):
        if isinstance(row, dict):
            pct = abs(float(row.get("day_chg_pct", 0) or 0))
            sym = row.get("symbol") or row.get("yahoo_symbol") or row.get("google_symbol", "")
            items.append((str(sym), min(0.85, 0.35 + pct * 0.04), "Active mover"))
        else:
            sym = getattr(row, "yahoo_symbol", None) or getattr(row, "symbol", "")
            pct = abs(float(getattr(row, "day_chg_pct", 0) or 0))
            items.append((str(sym), min(0.85, 0.35 + pct * 0.04), "Active mover"))

    for sym in trending or []:
        items.append((str(sym), 0.55, "Trending"))

    for symbol, priority, reason in extra_items or []:
        items.append((symbol, priority, reason))

    return build_enhance_symbols(items, limit=limit)


def derive_enhance_symbols_from_output(data: dict[str, Any], *, limit: int = 12) -> list[dict[str, Any]]:
    """Infer enhance_symbols from any agent JSON output (survives GitHub agent updates)."""
    extra: list[tuple[str, float, str]] = []

    for o in data.get("outliers", [])[:8]:
        if isinstance(o, dict):
            z = abs(float(o.get("z_score_mover", 0) or 0))
            extra.append(
                (
                    str(o.get("symbol", "")),
                    min(0.9, 0.5 + z * 0.08),
                    f"Statistical outlier ({o.get('direction', 'mover')})",
                )
            )

    for s in data.get("sectors", [])[:3]:
        if isinstance(s, dict):
            sym = s.get("etf") or s.get("yahoo_symbol") or s.get("symbol", "")
            label = s.get("sector") or s.get("name") or "Sector"
            extra.append((str(sym), 0.6, f"Sector leader — {label}"))

    retailers = data.get("retailers", []) or []
    for r in sorted(retailers, key=lambda x: -float(x.get("momentum_score", 0) or 0))[:6]:
        if not isinstance(r, dict) or r.get("category") == "sector_etf":
            continue
        mom = float(r.get("momentum_score", 0) or 0)
        extra.append(
            (
                str(r.get("symbol", "")),
                min(0.85, 0.4 + mom / 200),
                f"Retail momentum — {r.get('name', r.get('symbol', ''))}",
            )
        )

    for l in data.get("top_losers", [])[:3]:
        if isinstance(l, dict):
            pct = abs(float(l.get("day_chg_pct", 0) or 0))
            sym = l.get("symbol") or l.get("yahoo_symbol") or l.get("google_symbol", "")
            extra.append((str(sym), min(0.75, 0.45 + pct * 0.04), "Oversold loser"))

    return enhance_symbols_from_report(
        market_signals=data.get("market_signals"),
        trading_opportunities=data.get("trading_opportunities"),
        top_picks=data.get("top_picks"),
        top_gainers=data.get("top_gainers"),
        most_active=data.get("most_active"),
        trending=data.get("trending"),
        extra_items=extra,
        agent_requests=data.get("enhance_symbols"),
        limit=limit,
    )


def patch_agent_output_enhance_symbols(path: Path, *, limit: int = 12) -> bool:
    """Ensure agent output declares symbols for E*TRADE quote enhancement."""
    data = _load_json(path)
    if not data:
        return False
    existing = data.get("enhance_symbols")
    if isinstance(existing, list) and existing:
        return False
    derived = derive_enhance_symbols_from_output(data, limit=limit)
    if not derived:
        return False
    data["enhance_symbols"] = derived
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True


def build_enhance_symbols(
    items: list[tuple[str, float, str]],
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Build enhance_symbols payload from (symbol, priority, reason) tuples."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for symbol, priority, reason in sorted(items, key=lambda x: x[1], reverse=True):
        trade = normalize_tradeable_symbol(symbol)
        if not trade or trade in seen:
            continue
        seen.add(trade)
        out.append({"symbol": trade, "priority": round(priority, 3), "reason": reason})
        if len(out) >= limit:
            break
    return out


def select_symbols(
    candidates: list[dict[str, Any]],
    *,
    max_symbols: int = 50,
    min_priority: float = 0.4,
) -> list[str]:
    symbols: list[str] = []
    for row in candidates:
        if float(row.get("priority", 0)) < min_priority:
            continue
        sym = row.get("symbol")
        if sym and sym not in symbols:
            symbols.append(sym)
        if len(symbols) >= max_symbols:
            break
    return symbols


SKIP_ENHANCE_WALK_KEYS = frozenset({"etrade_enhanced", "enhance_symbols", "quotes", "candidates"})


def _walk_and_enhance(node: Any, quotes: dict[str, dict[str, Any]]) -> bool:
    changed = False
    if isinstance(node, dict):
        sym = None
        for key in SYMBOL_KEYS:
            if key in node and isinstance(node[key], str):
                trade = normalize_tradeable_symbol(node[key])
                if trade:
                    sym = trade
                    break
        if sym and sym in quotes and "etrade_enhanced" not in node:
            node["etrade_enhanced"] = quotes[sym]
            if quotes[sym].get("last_trade") is not None:
                node["price"] = quotes[sym]["last_trade"]
            changed = True
        for key, value in node.items():
            if key in SKIP_ENHANCE_WALK_KEYS:
                continue
            if _walk_and_enhance(value, quotes):
                changed = True
    elif isinstance(node, list):
        for item in node:
            if _walk_and_enhance(item, quotes):
                changed = True
    return changed


def apply_enhancements_to_agent_files(
    quotes: dict[str, dict[str, Any]],
    output_dir: Path | None = None,
) -> int:
    """Merge E*TRADE quote fields into agent JSON outputs."""
    if not quotes:
        return 0
    out = output_dir or OUTPUT
    updated = 0
    for src in active_agent_sources(check_remote=False):
        path = out / src["file"]
        data = _load_json(path)
        if not data:
            continue
        if _walk_and_enhance(data, quotes):
            meta = data.setdefault("meta", {})
            meta["etrade_enhancement_applied_at"] = datetime.now(timezone.utc).isoformat()
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            updated += 1
    return updated