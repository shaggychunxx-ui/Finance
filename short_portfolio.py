#!/usr/bin/env python3
"""Build a short-interest portfolio from Finance agent outputs (bearish side)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app_paths import OUTPUT
from portfolio_generator import (
    DEFAULT_HOLDINGS,
    TickerScore,
    _add_score,
    _backfill_etrade_prices,
    _detect_regime,
    _ingest_datascience,
    _ingest_finance_opportunities,
    _ingest_predictions,
    _ingest_sales_retailers,
    _ingest_signals,
    _load_json,
    AGENT_OUTPUTS,
)
from short_paths import SHORT_OUTPUT, SHORT_PORTFOLIO_FILE, ensure_short_dirs

DEFAULT_SHORT_HOLDINGS = 8
MAX_SHORT_WEIGHT_PCT = 12.0
MIN_SHORT_WEIGHT_PCT = 3.0


def load_short_strategy_settings(config_path: Path | None = None) -> dict[str, Any]:
    from short_paths import SHORT_CONFIG

    path = config_path or SHORT_CONFIG
    defaults = {
        "enabled": True,
        "cash_buffer_pct": 20.0,
        "max_short_book_pct": 40.0,
        "max_positions": DEFAULT_SHORT_HOLDINGS,
        "max_position_pct": 8.0,
        "min_drift_pct": 2.0,
        "min_trade_usd": 75.0,
        "min_bearish_score": 0.15,
        "min_confidence": 0.45,
        # strict = absolute bearish only; relative = weakest names when market is bullish
        "selection_mode": "relative",
        "require_cluster_agreement": False,
        "min_agreeing_clusters": 2,
        "stop_loss_pct": 6.0,
        "take_profit_pct": 10.0,
        "use_stop_orders": True,
        "place_protective_orders": True,
        "hard_to_borrow_skip": True,
        "min_price": 5.0,
        "exclude_symbols": [],
        "prefer_liquid": True,
    }
    if not path.exists():
        # Fall back to long config short_strategy block if present
        long_cfg = path.parent / "etrade_config.json"
        if long_cfg.exists():
            try:
                raw = json.loads(long_cfg.read_text(encoding="utf-8"))
                user = raw.get("short_strategy", {})
                if isinstance(user, dict):
                    defaults.update({k: user[k] for k in user})
            except (json.JSONDecodeError, OSError):
                pass
        return defaults
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        user = raw.get("short_strategy", {})
        if isinstance(user, dict):
            defaults.update({k: user[k] for k in user})
    except (json.JSONDecodeError, OSError):
        pass
    return defaults


def _collect_scores(output_dir: Path) -> tuple[dict[str, TickerScore], list[str]]:
    scores: dict[str, TickerScore] = {}
    sources_used: list[str] = []

    predictions = _load_json(output_dir / "market_predictions.json")
    if predictions:
        _ingest_predictions(predictions, scores)
        sources_used.append("market_predictions.json")

    for filename in AGENT_OUTPUTS:
        if filename == "market_predictions.json":
            continue
        data = _load_json(output_dir / filename)
        if not data:
            continue
        sources_used.append(filename)
        _ingest_signals(data, scores, filename.replace(".json", ""))
        if filename == "finance.json":
            _ingest_finance_opportunities(data, scores)
        elif filename == "datascience.json":
            _ingest_datascience(data, scores)
        elif filename == "sales_analytics.json":
            _ingest_sales_retailers(data, scores)

    return scores, sources_used


def _bearish_strength(ticker: TickerScore) -> float:
    """Higher = better short candidate. Inverted long score + down-projection bonus."""
    raw = float(ticker.score)
    # Negative agent scores are short-friendly; invert so ranking is descending.
    base = -raw
    conf = float(ticker.confidence or 0.5)
    proj = ticker.projected_return_pct
    if proj is not None and proj < 0:
        base += min(2.0, abs(proj) / 8.0)
    elif proj is not None and proj > 0:
        # Soft penalty so relative weakest can still rank, but pure bulls sink.
        base -= min(0.8, proj / 40.0)
    clusters = ticker.by_cluster or {}
    bearish_clusters = sum(1 for v in clusters.values() if v < 0)
    bullish_clusters = sum(1 for v in clusters.values() if v > 0)
    base += 0.12 * bearish_clusters
    base -= 0.04 * bullish_clusters
    return base * (0.55 + 0.45 * conf)


def _passes_short_gates(
    ticker: TickerScore,
    settings: dict[str, Any],
    *,
    relative_mode: bool = False,
    strength_floor: float | None = None,
) -> tuple[bool, str]:
    if ticker.symbol in {s.upper() for s in (settings.get("exclude_symbols") or [])}:
        return False, "excluded"
    min_price = float(settings.get("min_price", 5.0))
    if ticker.price is not None and ticker.price < min_price:
        return False, f"price < ${min_price}"

    strength = _bearish_strength(ticker)
    min_score = float(settings.get("min_bearish_score", 0.15))
    if relative_mode:
        # In bull regimes, take the weakest names among the agent universe.
        if strength_floor is not None and strength < strength_floor:
            return False, f"below relative floor {strength_floor:.2f}"
    else:
        if strength < min_score:
            return False, f"bearish strength {strength:.2f} < {min_score}"
        if ticker.projected_return_pct is not None and ticker.projected_return_pct > 0.5:
            return False, "projected return still positive"
        if settings.get("require_cluster_agreement", False):
            clusters = ticker.by_cluster or {}
            bearish = [k for k, v in clusters.items() if v < 0]
            need = int(settings.get("min_agreeing_clusters", 2))
            if len(clusters) >= need and len(bearish) < need:
                return False, f"only {len(bearish)} bearish clusters"

    min_conf = float(settings.get("min_confidence", 0.45))
    if ticker.confidence is not None and ticker.confidence < min_conf and not relative_mode:
        return False, f"confidence {ticker.confidence:.2f} < {min_conf}"
    return True, "ok"


def generate_short_portfolio(
    output_dir: Path | None = None,
    *,
    holdings: int | None = None,
    notional_usd: float | None = 100_000.0,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select a short book from the most bearish agent-scored names."""
    ensure_short_dirs()
    agent_dir = output_dir or OUTPUT
    settings = settings or load_short_strategy_settings()
    max_positions = int(holdings or settings.get("max_positions") or DEFAULT_SHORT_HOLDINGS)
    max_weight = min(MAX_SHORT_WEIGHT_PCT, float(settings.get("max_position_pct", 8.0)))
    max_book = float(settings.get("max_short_book_pct", 40.0))

    scores, sources_used = _collect_scores(agent_dir)
    tickers = list(scores.values())
    try:
        _backfill_etrade_prices(agent_dir, tickers)
    except Exception:
        pass

    # Joint sleeve coordination: prefer short-assigned names for this book
    try:
        from sleeve_coordinator import coordinate_sleeves, preferred_sleeve_for_symbol

        coordinate_sleeves(total_account_value=float(notional_usd or 0) or None)
        for t in tickers:
            side = preferred_sleeve_for_symbol(t.symbol)
            if side == "short":
                t.score -= 0.25  # more negative = more short-friendly after invert
                t.sources.add("sleeve-coord-short")
                t.notes.append("Joint sleeve: assigned short for profit max")
            elif side == "long":
                t.score += 0.40  # push away from short book
                t.sources.add("sleeve-coord-long")
                t.notes.append("Joint sleeve: reserved for long book")
        sources_used.append("sleeve_coordination.json")
    except Exception:
        pass

    regime = _detect_regime(agent_dir)
    mode = str(settings.get("selection_mode") or "relative").lower()
    relative_mode = mode in {"relative", "weakest", "auto"}

    ranked = [(_bearish_strength(t), t) for t in tickers]
    ranked.sort(key=lambda row: row[0], reverse=True)

    # Relative mode: keep top half by bearish strength (i.e. weakest longs / best shorts).
    strength_floor = None
    if relative_mode and ranked:
        strengths = [s for s, _ in ranked]
        # Floor at median of strengths so we only take the weaker half.
        mid = strengths[len(strengths) // 2]
        strength_floor = mid

    candidates: list[tuple[float, TickerScore, str]] = []
    rejected = 0
    for strength, t in ranked:
        ok, reason = _passes_short_gates(
            t,
            settings,
            relative_mode=relative_mode,
            strength_floor=strength_floor,
        )
        if not ok:
            rejected += 1
            continue
        tag = reason if not relative_mode else f"relative short ({reason})"
        candidates.append((strength, t, tag))

    # If strict mode yields nothing, fall back once to relative weakest names.
    if not candidates and not relative_mode and ranked:
        for strength, t in ranked[: max_positions * 2]:
            ok, reason = _passes_short_gates(
                t, settings, relative_mode=True, strength_floor=None
            )
            if not ok:
                continue
            candidates.append((strength, t, f"fallback relative ({reason})"))

    candidates.sort(key=lambda row: row[0], reverse=True)
    selected = candidates[:max_positions]

    # Equal-ish weights capped by max_weight, total capped by max_book
    n = len(selected)
    if n == 0:
        holdings_out: list[dict[str, Any]] = []
    else:
        equal = min(max_weight, max_book / n)
        equal = max(MIN_SHORT_WEIGHT_PCT, equal) if equal >= MIN_SHORT_WEIGHT_PCT else equal
        raw_weights = [equal] * n
        total_w = sum(raw_weights)
        if total_w > max_book and total_w > 0:
            scale = max_book / total_w
            raw_weights = [w * scale for w in raw_weights]

        holdings_out = []
        for weight, (strength, ticker, _) in zip(raw_weights, selected):
            rationale_bits = [
                f"Bearish strength {strength:.2f}",
                f"agent score {ticker.score:.2f}",
            ]
            if ticker.projected_return_pct is not None:
                rationale_bits.append(f"proj {ticker.projected_return_pct:+.2f}%")
            if ticker.sources:
                rationale_bits.append("sources: " + ",".join(sorted(ticker.sources)[:5]))
            alloc = None
            if notional_usd:
                alloc = round(float(notional_usd) * weight / 100.0, 2)
            holdings_out.append(
                {
                    "symbol": ticker.symbol,
                    "side": "SHORT",
                    "weight_pct": round(weight, 2),
                    "score": round(ticker.score, 4),
                    "bearish_strength": round(strength, 4),
                    "confidence": ticker.confidence,
                    "projected_return_pct": ticker.projected_return_pct,
                    "price": ticker.price,
                    "allocation_usd": alloc,
                    "role": "short",
                    "sources": sorted(ticker.sources),
                    "rationale": " | ".join(rationale_bits),
                }
            )

    portfolio = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "short",
            "holdings_count": len(holdings_out),
            "notional_usd": notional_usd,
            "sources_used": sources_used,
            "candidates_considered": len(tickers),
            "candidates_rejected": rejected,
            "max_short_book_pct": max_book,
        },
        "regime": regime,
        "holdings": holdings_out,
        "allocation_summary": {
            "short_book_pct": round(sum(h["weight_pct"] for h in holdings_out), 2),
            "cash_buffer_pct": float(settings.get("cash_buffer_pct", 20.0)),
        },
        "recommendations": [
            "Short book is built from inverted / bearish agent scores only.",
            "Covers use BUY_TO_COVER; entries use SELL_SHORT.",
            "Keep dry_run true until borrow/margin behavior is verified in sandbox.",
        ],
    }
    return portfolio


def save_short_portfolio(portfolio: dict[str, Any], path: Path | None = None) -> Path:
    ensure_short_dirs()
    path = path or SHORT_PORTFOLIO_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(portfolio, indent=2), encoding="utf-8")
    return path
