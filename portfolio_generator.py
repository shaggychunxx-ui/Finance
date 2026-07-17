#!/usr/bin/env python3
"""Generate an investment portfolio from Finance agent outputs and predictions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_HOLDINGS = 12
MAX_WEIGHT_PCT = 15.0
MIN_WEIGHT_PCT = 3.0
HORIZON_WEIGHTS = {"24h": 0.4, "1wk": 0.65, "1mo": 1.0, "1yr": 0.8}
BIAS_SCORES = {"BULLISH": 1.0, "NEUTRAL": 0.15, "BEARISH": -1.0}

# Core outputs always ingested (order is stable for logging).
AGENT_OUTPUTS = [
    "markets.json",
    "finance.json",
    "financial_data.json",
    "datascience.json",
    "sales_analytics.json",
    "geopolitics.json",
    "market_predictions.json",
    # Short / microstructure specialists (GitHub copilot branches)
    "bear_thesis.json",
    "htb_dynamics.json",
    "squeeze_mechanics.json",
    "ftd_regsho.json",
    "risk_mitigation.json",
    "day_trading_microstructure.json",
    "long_squeeze_synergy.json",
    "portfolio_frameworks.json",
    "risk_protection.json",
    # Fundamental / technical / regime suite
    "fundamental_analyst.json",
    "technical_pattern.json",
    "adversarial_debate.json",
    "risk_guardrail.json",
    "market_regime.json",
    "sentiment_alt_data.json",
    # Macro / index / alt-data
    "fred.json",
    "cpi.json",
    "economy.json",
    "consumer_sentiment.json",
    "ftse100.json",
    "nikkei.json",
    "earthdata.json",
]

AGENT_SOURCE_IDS = {
    "markets",
    "finance",
    "financial_data",
    "datascience",
    "sales-analytics",
    "sales_analytics",
    "geopolitics",
    "market-predictor",
    "bear-thesis",
    "htb-dynamics",
    "squeeze-mechanics",
    "ftd-regsho",
    "risk-mitigation",
    "day-trading-microstructure",
    "long-squeeze-synergy",
    "portfolio-frameworks",
    "risk-protection",
    "fundamental-analyst",
    "technical-pattern",
    "adversarial-debate",
    "risk-guardrail",
    "market-regime",
    "sentiment-alt-data",
    "fred",
    "cpi",
    "economy",
    "consumer-sentiment",
    "ftse100",
    "nikkei",
    "earthdata",
}
NON_AGENT_SOURCES = frozenset({"regime", "etrade", "history", "profit-optimizer"})


@dataclass
class TickerScore:
    symbol: str
    score: float = 0.0
    sources: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)
    price: float | None = None
    projected_return_pct: float | None = None
    projected_return_horizon: str | None = None
    confidence: float | None = None
    role: str = "equity"
    by_cluster: dict[str, float] = field(default_factory=dict)
    trading_gate: dict[str, Any] = field(default_factory=dict)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _normalize_symbol(symbol: str) -> str:
    sym = symbol.strip().upper()
    if sym.startswith("^"):
        return sym
    return sym.replace(".", "-")


def _add_score(
    scores: dict[str, TickerScore],
    symbol: str,
    delta: float,
    source: str,
    note: str = "",
    *,
    price: float | None = None,
    projected_return_pct: float | None = None,
    projected_return_horizon: str | None = None,
    confidence: float | None = None,
    role: str = "equity",
    horizon: str | None = None,
    sector_hint: str = "",
) -> None:
    sym = _normalize_symbol(symbol)
    if not sym or sym.startswith("^") and sym not in {"^GSPC"}:
        if sym.startswith("^"):
            return
    if len(sym) > 6 and not sym.endswith("-USD"):
        return
    agent_id = str(source or "").replace("_", "-")
    try:
        from agent_constraints import domain_allows_symbol, horizon_match_multiplier, load_domain_constraint_settings

        gate = load_domain_constraint_settings()
        if not domain_allows_symbol(agent_id, sym, sector_hint=sector_hint, settings=gate):
            return
    except Exception:
        pass

    weighted_delta = delta
    try:
        from prediction_accuracy import agent_accuracy_weight

        weight = agent_accuracy_weight(
            source, symbol=sym, horizon=horizon or "24h", for_trading=True
        )
        if weight <= 0:
            return
        weighted_delta = delta * weight
        try:
            from agent_constraints import horizon_match_multiplier, load_domain_constraint_settings

            weighted_delta *= horizon_match_multiplier(
                agent_id,
                horizon or "24h",
                settings=load_domain_constraint_settings(),
            )
        except Exception:
            pass
    except Exception:
        pass
    entry = scores.setdefault(sym, TickerScore(symbol=sym))
    entry.score += weighted_delta
    entry.sources.add(source)
    try:
        from agent_fusion import agent_cluster
        from trading_gate import _source_agent_id

        cluster = agent_cluster(_source_agent_id(source))
        entry.by_cluster[cluster] = entry.by_cluster.get(cluster, 0.0) + weighted_delta
    except Exception:
        pass
    if note and note not in entry.notes:
        entry.notes.append(note)
    if price is not None:
        entry.price = price
    if projected_return_pct is not None:
        entry.projected_return_pct = projected_return_pct
        if projected_return_horizon:
            entry.projected_return_horizon = projected_return_horizon
        elif horizon:
            entry.projected_return_horizon = horizon
    if confidence is not None:
        entry.confidence = max(entry.confidence or 0, confidence)
    if role:
        entry.role = role


def _ingest_predictions(data: dict[str, Any], scores: dict[str, TickerScore]) -> None:
    preds = data.get("predictions", {})
    for horizon, weight in HORIZON_WEIGHTS.items():
        for row in preds.get(horizon, []):
            symbol = row.get("symbol", "")
            direction = row.get("predicted_direction", "")
            confidence = float(row.get("confidence", 0.5))
            ret = float(row.get("predicted_return_pct", 0))
            sign = 1.0 if direction == "up" else -1.0 if direction == "down" else 0.0
            rank_bonus = max(0, (51 - int(row.get("rank", 50))) / 50)
            delta = sign * confidence * weight * (0.6 + 0.4 * rank_bonus)
            note = f"{horizon} {direction} {ret:+.1f}% (conf {confidence:.0%})"
            _add_score(
                scores,
                symbol,
                delta,
                "market-predictor",
                note,
                price=row.get("price_at_prediction"),
                projected_return_pct=ret if direction == "up" else None,
                confidence=confidence,
                horizon=horizon,
            )


def _ingest_signals(data: dict[str, Any], scores: dict[str, TickerScore], source: str) -> None:
    for sig in data.get("market_signals", []):
        bias = str(sig.get("bias", "NEUTRAL")).upper()
        delta = BIAS_SCORES.get(bias, 0.0) * 0.35
        sector = sig.get("sector", "")
        reason = sig.get("reason", "")
        note = f"{sector}: {reason}" if sector else reason
        role = "sector_etf" if any(
            t in {"SPY", "QQQ", "IWM", "GLD", "TLT", "HYG", "XLE", "XLK", "XLV", "XLF", "XLU", "XLP", "XLY"}
            for t in sig.get("tickers", [])
        ) else "equity"
        signal_horizon = str(sig.get("preferred_horizon") or "")
        if signal_horizon not in HORIZON_WEIGHTS:
            try:
                from agent_constraints import agent_preferred_horizon

                signal_horizon = agent_preferred_horizon(source)
            except Exception:
                signal_horizon = "24h"
        for ticker in sig.get("tickers", []):
            _add_score(
                scores,
                ticker,
                delta,
                source,
                note,
                role=role,
                horizon=signal_horizon,
                sector_hint=str(sector),
            )


def _ingest_finance_opportunities(data: dict[str, Any], scores: dict[str, TickerScore]) -> None:
    for opp in data.get("trading_opportunities", []):
        score_val = float(opp.get("opportunity_score", 0))
        _add_score(
            scores,
            opp.get("symbol", ""),
            min(1.2, score_val * 0.5),
            "finance",
            opp.get("rationale", opp.get("strategy", "")),
            projected_return_pct=opp.get("day_chg_pct"),
            projected_return_horizon="today",
        )


def _ingest_datascience(data: dict[str, Any], scores: dict[str, TickerScore]) -> None:
    for row in data.get("tickers", []):
        mom = float(row.get("momentum_score", 0))
        if mom <= 0:
            continue
        _add_score(
            scores,
            row.get("symbol", ""),
            min(1.0, mom / 100),
            "datascience",
            f"momentum {mom:.0f}, 20d {row.get('return_20d_pct', 0):+.1f}%",
            role="sector_etf",
        )


def _apply_etrade_prices(
    output_dir: Path,
    scores: dict[str, TickerScore],
    *,
    small: dict[str, Any] | None = None,
) -> None:
    """Prefer E*TRADE subscribed quotes for portfolio sizing when available."""
    enhanced = _load_json(output_dir / "etrade_enhanced_quotes.json")
    if not enhanced:
        return
    max_px = float(small["max_share_price"]) if small else None
    for sym, quote in (enhanced.get("quotes") or {}).items():
        if not isinstance(quote, dict):
            continue
        last = quote.get("last_trade")
        if last is None:
            continue
        px = float(last)
        entry = scores.setdefault(sym, TickerScore(symbol=sym))
        entry.price = px
        entry.sources.add("etrade")
        change = quote.get("change_pct")
        if change is not None:
            note = f"E*TRADE {float(change):+.2f}%"
            if note not in entry.notes:
                entry.notes.append(note)
        if max_px and 0 < px <= max_px:
            entry.score += 0.45
            affordable_note = f"Live affordable quote ${px:.2f}/sh"
            if affordable_note not in entry.notes:
                entry.notes.insert(0, affordable_note)


def _backfill_etrade_prices(output_dir: Path, tickers: list[TickerScore]) -> None:
    enhanced = _load_json(output_dir / "etrade_enhanced_quotes.json")
    if not enhanced:
        return
    quotes = enhanced.get("quotes") or {}
    for ticker in tickers:
        if _ticker_price(ticker) > 0:
            continue
        quote = quotes.get(ticker.symbol)
        if not isinstance(quote, dict):
            continue
        last = quote.get("last_trade")
        if last is not None:
            ticker.price = float(last)


def _ingest_sales_retailers(data: dict[str, Any], scores: dict[str, TickerScore]) -> None:
    for row in data.get("retailers", []):
        if row.get("category") == "sector_etf":
            continue
        mom = float(row.get("momentum_score", 0))
        if mom <= 0:
            continue
        _add_score(
            scores,
            row.get("symbol", ""),
            min(0.8, mom / 120),
            "sales-analytics",
            f"{row.get('name', '')} momentum {mom:.0f}",
        )


def _detect_regime(output_dir: Path) -> dict[str, Any]:
    markets = _load_json(output_dir / "markets.json") or {}
    metrics = markets.get("metrics", {})
    risk_on = float(metrics.get("risk_on_score", 0.5))
    label = metrics.get("trend_label", "Neutral")
    if risk_on >= 0.6:
        posture = "risk-on"
    elif risk_on <= 0.4:
        posture = "risk-off"
    else:
        posture = "neutral"
    return {
        "label": label,
        "posture": posture,
        "risk_on_score": round(risk_on, 4),
        "summary": markets.get("meta", {}).get("expert_summary", ""),
    }


def _apply_regime_sleeve(scores: dict[str, TickerScore], regime: dict[str, Any]) -> None:
    posture = regime.get("posture", "neutral")
    if posture == "risk-off":
        for sym, delta, note in [
            ("GLD", 0.6, "Defensive sleeve — risk-off regime"),
            ("TLT", 0.5, "Defensive sleeve — risk-off regime"),
            ("XLP", 0.35, "Staples tilt — risk-off regime"),
        ]:
            _add_score(scores, sym, delta, "regime", note, role="defensive")
    elif posture == "risk-on":
        for sym, delta, note in [
            ("QQQ", 0.45, "Growth sleeve — risk-on regime"),
            ("IWM", 0.35, "Small-cap tilt — risk-on regime"),
        ]:
            _add_score(scores, sym, delta, "regime", note, role="sector_etf")
    else:
        _add_score(scores, "SPY", 0.4, "regime", "Core beta — neutral regime", role="sector_etf")


def _is_agent_pick(ticker: TickerScore, *, small: dict[str, Any] | None = None) -> bool:
    """True when at least one real agent (not regime/system layers) picked this symbol."""
    agent_sources = {s for s in ticker.sources if s not in NON_AGENT_SOURCES}
    if agent_sources & AGENT_SOURCE_IDS or bool(
        agent_sources - NON_AGENT_SOURCES - AGENT_SOURCE_IDS
    ):
        return True
    if small and "etrade" in ticker.sources:
        px = _ticker_price(ticker)
        if px > 0 and px <= float(small["max_share_price"]) and ticker.score >= 0.35:
            return True
    return False


def _ticker_price(ticker: TickerScore) -> float:
    try:
        return float(ticker.price or 0)
    except (TypeError, ValueError):
        return 0.0


def _small_account_profile(
    notional: float,
    settings: dict[str, Any],
    *,
    default_holdings: int,
) -> dict[str, Any] | None:
    if not settings.get("prefer_affordable_tickers", True):
        return None
    threshold = float(settings.get("small_account_threshold_usd", 500))
    if notional <= 0 or notional >= threshold:
        return None

    buffer = float(settings.get("cash_buffer_pct", 5)) / 100
    investable = notional * (1 - buffer)
    min_trade = float(settings.get("min_trade_usd", 5))
    max_holdings = int(settings.get("small_account_max_holdings", 6))
    min_holdings = int(settings.get("small_account_min_holdings", 3))
    by_slots = max(min_holdings, int(investable / min_trade))
    target_holdings = max(min_holdings, min(max_holdings, default_holdings, by_slots))
    slot_usd = investable / target_holdings if target_holdings else investable
    max_share_price = max(min_trade, slot_usd * 0.98)
    return {
        "investable_usd": round(investable, 2),
        "target_holdings": target_holdings,
        "min_holdings": min_holdings,
        "max_share_price": round(max_share_price, 2),
        "min_trade_usd": min_trade,
    }


def _ingest_affordable_movers(
    data: dict[str, Any],
    scores: dict[str, TickerScore],
    *,
    max_share_price: float,
    notional: float,
    source: str = "finance",
) -> None:
    """Boost lower-priced movers agents already surfaced — sized for the account."""
    for section in ("top_gainers", "most_active"):
        for row in data.get(section, []) or []:
            sym = row.get("google_symbol") or row.get("symbol") or row.get("yahoo_symbol") or ""
            price = row.get("price")
            if price is None:
                continue
            try:
                px = float(price)
            except (TypeError, ValueError):
                continue
            if px <= 0 or px > max_share_price:
                continue
            day_chg = row.get("day_chg_pct")
            boost = 0.55
            if day_chg is not None:
                boost += min(0.45, abs(float(day_chg)) * 0.02)
            note = f"Affordable mover ${px:.2f}/sh ({section.replace('_', ' ')})"
            if day_chg is not None:
                note += f" {float(day_chg):+.1f}% today"
            _add_score(
                scores,
                sym,
                boost,
                source,
                note,
                price=px,
                projected_return_pct=float(day_chg) if day_chg is not None else None,
                projected_return_horizon="today" if day_chg is not None else None,
                role="equity",
            )


def _ingest_affordable_predictions(
    data: dict[str, Any],
    scores: dict[str, TickerScore],
    *,
    max_share_price: float,
) -> None:
    preds = data.get("predictions", {})
    for horizon in ("24h", "1wk"):
        for row in preds.get(horizon, []) or []:
            if str(row.get("predicted_direction", "")).lower() != "up":
                continue
            price = row.get("price_at_prediction")
            if price is None:
                continue
            try:
                px = float(price)
            except (TypeError, ValueError):
                continue
            if px <= 0 or px > max_share_price:
                continue
            conf = float(row.get("confidence", 0.5))
            ret = float(row.get("predicted_return_pct", 0))
            boost = 0.35 + conf * 0.35 + min(0.25, ret * 0.04)
            note = f"Affordable {horizon} pick ${px:.2f}/sh"
            _add_score(
                scores,
                row.get("symbol", ""),
                boost,
                "market-predictor",
                note,
                price=px,
                projected_return_pct=ret,
                projected_return_horizon=horizon,
                confidence=conf,
            )


def _apply_affordable_score_boost(
    scores: dict[str, TickerScore],
    *,
    small: dict[str, Any],
    notional: float,
) -> None:
    max_px = float(small["max_share_price"])
    for ticker in scores.values():
        px = _ticker_price(ticker)
        if px <= 0 or px > max_px:
            continue
        ticker.score += 0.2
        note = f"Fits ${notional:,.0f} account (${px:.2f}/share ≤ ${max_px:.2f})"
        if note not in ticker.notes:
            ticker.notes.insert(0, note)


def _select_holdings(
    positive: list[TickerScore],
    *,
    holdings: int,
    small: dict[str, Any] | None,
) -> list[TickerScore]:
    target = int(small["target_holdings"]) if small else holdings
    if not small:
        return positive[:target]

    max_px = float(small["max_share_price"])
    affordable = [t for t in positive if 0 < _ticker_price(t) <= max_px]
    unknown = [t for t in positive if _ticker_price(t) <= 0]
    expensive = [t for t in positive if _ticker_price(t) > max_px]

    selected = affordable[:target]
    if len(selected) < target:
        for ticker in unknown:
            if len(selected) >= target:
                break
            if ticker not in selected:
                selected.append(ticker)
    min_needed = max(3, target // 2)
    if len(selected) < min_needed and expensive:
        expensive.sort(key=lambda t: (_ticker_price(t), -t.score))
        for ticker in expensive:
            if len(selected) >= target:
                break
            selected.append(ticker)
    return selected[:target]


def _cap_weights(weights: list[float], max_pct: float, min_pct: float) -> list[float]:
    if not weights:
        return weights
    capped = [min(max_pct, max(min_pct, w)) for w in weights]
    total = sum(capped)
    return [round(w / total * 100, 2) for w in capped] if total else capped


def _merge_fusion_clusters(scores: dict[str, TickerScore], output_dir: Path) -> None:
    """Blend Market Predictor fused cluster breakdown into portfolio scores."""
    try:
        from agents.market_predictor import _collect_ticker_scores
    except Exception:
        return

    try:
        fused = _collect_ticker_scores(output_dir)
    except Exception:
        return

    for sym, row in fused.items():
        clusters = row.get("by_cluster") or {}
        if not clusters:
            continue
        entry = scores.setdefault(sym, TickerScore(symbol=sym))
        for cluster, value in clusters.items():
            try:
                entry.by_cluster[cluster] = entry.by_cluster.get(cluster, 0.0) + float(value)
            except (TypeError, ValueError):
                continue
        for src in row.get("sources") or []:
            entry.sources.add(str(src))


def _minimum_holdings_required(
    *,
    holdings: int,
    small: dict[str, Any] | None,
) -> int:
    if small:
        return max(3, int(small.get("min_holdings", 3)))
    return max(6, holdings // 2)


def generate_portfolio(
    output_dir: Path,
    *,
    holdings: int = DEFAULT_HOLDINGS,
    notional_usd: float | None = 100_000.0,
) -> dict[str, Any]:
    """Build a portfolio from agent artifacts in *output_dir*."""
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

    strategy_settings: dict[str, Any] = {}
    try:
        from strategy_engine import load_strategy_settings

        strategy_settings = load_strategy_settings()
    except Exception:
        pass
    agent_controlled = bool(strategy_settings.get("agent_controlled", True))
    small_account = (
        _small_account_profile(float(notional_usd or 0), strategy_settings, default_holdings=holdings)
        if notional_usd
        else None
    )

    _apply_etrade_prices(output_dir, scores, small=small_account)
    if small_account:
        finance = _load_json(output_dir / "finance.json")
        if finance:
            _ingest_affordable_movers(
                finance,
                scores,
                max_share_price=float(small_account["max_share_price"]),
                notional=float(notional_usd or 0),
            )
        if predictions:
            _ingest_affordable_predictions(
                predictions,
                scores,
                max_share_price=float(small_account["max_share_price"]),
            )

    regime = _detect_regime(output_dir)
    if not agent_controlled:
        _apply_regime_sleeve(scores, regime)

    # Joint sleeve coordination: boost long-assigned names, soft-penalize short-only ideas
    try:
        from sleeve_coordinator import coordinate_sleeves, preferred_sleeve_for_symbol

        coordinate_sleeves(total_account_value=float(notional_usd or 0) or None)
        for ticker in scores.values():
            side = preferred_sleeve_for_symbol(ticker.symbol)
            if side == "long":
                ticker.score += 0.22
                ticker.sources.add("sleeve-coord-long")
                ticker.notes.append("Joint sleeve: assigned long for profit max")
            elif side == "short":
                ticker.score -= 0.35
                ticker.sources.add("sleeve-coord-short")
                ticker.notes.append("Joint sleeve: reserved for short book")
        sources_used.append("sleeve_coordination.json")
    except Exception:
        pass

    context: dict[str, Any] = {}
    try:
        from analysis_history import build_agent_context, history_boost_for_portfolio

        history_boost_for_portfolio(scores)
        context = build_agent_context()
        sources_used.append("agent_context.json")
    except Exception:
        pass

    profit_profiles: dict[str, Any] = {}
    if not agent_controlled:
        try:
            from profit_optimizer import build_profit_profiles

            profit_profiles = build_profit_profiles(output_dir)
            for ticker in scores.values():
                profile = profit_profiles.get(ticker.symbol)
                if not profile:
                    continue
                boost = max(0.0, profile.composite_score) * 0.12
                ticker.score += boost
                ticker.sources.add("profit-optimizer")
                if profile.composite_return_pct > 0:
                    ticker.projected_return_pct = profile.composite_return_pct
                    ticker.projected_return_horizon = "composite"
                ticker.notes.append(
                    f"Profit d/w/m/y: {profile.horizon_returns.get('daily', 0):+.1f}%/"
                    f"{profile.horizon_returns.get('weekly', 0):+.1f}%/"
                    f"{profile.horizon_returns.get('monthly', 0):+.1f}%/"
                    f"{profile.horizon_returns.get('yearly', 0):+.1f}%"
                )
        except Exception:
            pass

    if small_account:
        _apply_affordable_score_boost(scores, small=small_account, notional=float(notional_usd or 0))

    _merge_fusion_clusters(scores, output_dir)

    ranked = sorted(scores.values(), key=lambda t: t.score, reverse=True)
    gate_meta: dict[str, Any] = {"enabled": False}
    if agent_controlled:
        positive = [t for t in ranked if t.score > 0 and _is_agent_pick(t, small=small_account)]
        pre_gate = list(positive)
        try:
            from trading_gate import (
                filter_tickers_for_trading,
                load_trading_gate_settings,
                trading_gate_summary_for_portfolio,
            )

            gate_settings = load_trading_gate_settings()
            gated = filter_tickers_for_trading(positive, settings=gate_settings)
            gate_meta = trading_gate_summary_for_portfolio(gated)
            gate_meta["pre_gate_candidates"] = len(pre_gate)
            if gated:
                positive = gated
            elif pre_gate:
                positive = pre_gate
                gate_meta["fallback"] = "used_pre_gate_candidates"
        except Exception:
            pass
    else:
        positive = [t for t in ranked if t.score > 0]
    selected = _select_holdings(positive, holdings=holdings, small=small_account)
    _backfill_etrade_prices(output_dir, selected)

    min_required = _minimum_holdings_required(holdings=holdings, small=small_account)
    if len(selected) < min_required:
        raise ValueError(
            "Not enough bullish signals to build a portfolio. "
            "Run Market Predictor and key agents (markets, finance, datascience) first."
        )

    raw_weights = [max(0.01, t.score) for t in selected]
    weight_pcts = _cap_weights(raw_weights, MAX_WEIGHT_PCT, MIN_WEIGHT_PCT)

    holdings_out: list[dict[str, Any]] = []
    for ticker, weight in zip(selected, weight_pcts):
        row: dict[str, Any] = {
            "symbol": ticker.symbol,
            "weight_pct": weight,
            "score": round(ticker.score, 3),
            "role": ticker.role,
            "sources": sorted(ticker.sources),
            "rationale": "; ".join(ticker.notes[:3]) or "Composite agent signal",
        }
        if ticker.price is not None:
            row["price"] = ticker.price
        if ticker.projected_return_pct is not None:
            row["projected_return_pct"] = round(ticker.projected_return_pct, 2)
        if ticker.projected_return_horizon:
            row["projected_return_horizon"] = ticker.projected_return_horizon
        if ticker.confidence is not None:
            row["confidence"] = round(ticker.confidence, 3)
        if ticker.by_cluster:
            row["by_cluster"] = {k: round(v, 4) for k, v in ticker.by_cluster.items()}
        if getattr(ticker, "trading_gate", None):
            row["trading_gate"] = ticker.trading_gate
        if notional_usd:
            row["allocation_usd"] = round(notional_usd * weight / 100, 2)
        try:
            from order_type_selector import resolve_order_type

            px = float(ticker.price or row.get("price") or 0)
            decision = resolve_order_type(
                ticker.symbol,
                "BUY",
                price=px,
                output_dir=output_dir,
                rationale=row.get("rationale", ""),
                horizon="1wk",
                confidence=float(ticker.confidence or 0.55),
            )
            row["order_type"] = decision.price_type
            if decision.limit_price is not None:
                row["limit_price"] = decision.limit_price
            row["order_type_reason"] = decision.reason
            if decision.sources:
                row["order_type_sources"] = decision.sources
        except Exception:
            row["order_type"] = "LIMIT"
        holdings_out.append(row)

    if not agent_controlled:
        try:
            from profit_optimizer import apply_profit_weights_to_holdings

            apply_profit_weights_to_holdings(holdings_out, profit_profiles)
            total_w = sum(float(h["weight_pct"]) for h in holdings_out) or 1.0
            for h in holdings_out:
                h["weight_pct"] = round(float(h["weight_pct"]) / total_w * 100, 2)
        except Exception:
            pass

    equity_pct = round(sum(h["weight_pct"] for h in holdings_out if h["role"] == "equity"), 2)
    defensive_pct = round(sum(h["weight_pct"] for h in holdings_out if h["role"] == "defensive"), 2)
    etf_pct = round(sum(h["weight_pct"] for h in holdings_out if h["role"] == "sector_etf"), 2)

    growth = (context or {}).get("account_growth", {}) if isinstance(context, dict) else {}
    if agent_controlled:
        recommendations = [
            "Objective: agent-controlled stock selection",
            f"{len(holdings_out)} agent-picked holdings, max position {MAX_WEIGHT_PCT:.0f}%",
            f"Regime context: {regime['label']} ({regime['posture']}) — informational only",
        ]
        if small_account:
            recommendations.insert(
                1,
                (
                    f"Small-account mode: ≤${small_account['max_share_price']:.2f}/share "
                    f"({small_account['target_holdings']} names, ${notional_usd:,.0f} account)"
                ),
            )
    else:
        recommendations = [
            "Objective: maximize daily, weekly, monthly, and yearly profit",
            f"Regime: {regime['label']} ({regime['posture']}) — risk-on {regime['risk_on_score']:.2f}",
            f"{len(holdings_out)} holdings, max position {MAX_WEIGHT_PCT:.0f}%",
        ]
    profit_pct = growth.get("profit_pct") if growth.get("profit_pct") is not None else growth.get("growth_pct")
    if profit_pct is not None:
        note = f"Account profit since open: {profit_pct:+.2f}%"
        if growth.get("net_external_flows"):
            note += f" (excludes ${float(growth['net_external_flows']):,.0f} transfers)"
        recommendations.append(note)
    if regime["posture"] == "risk-off":
        recommendations.append("Elevated defensive allocation — favor quality and hedges")
    elif regime["posture"] == "risk-on":
        recommendations.append("Risk-on tilt — growth and momentum sleeves overweighted")

    trading_gate_meta: dict[str, Any] = dict(gate_meta) if agent_controlled else {}
    if agent_controlled:
        try:
            from trading_gate import load_trading_gate_settings

            trading_gate_meta.update(load_trading_gate_settings())
            trading_gate_meta["holdings_passed"] = sum(
                1 for h in holdings_out if (h.get("trading_gate") or {}).get("passes")
            )
        except Exception:
            pass

    return {
        "meta": {
            "generator": "Finance Portfolio Generator",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_files": sources_used,
            "holdings_count": len(holdings_out),
            "notional_usd": notional_usd,
            "horizon_focus": "daily, weekly, monthly, yearly profit",
            "objective": "agent_controlled_selection" if agent_controlled else "maximize_multi_horizon_profit",
            "agent_controlled": agent_controlled,
            "small_account": small_account,
            "account_growth": growth,
            "trading_gate": trading_gate_meta,
        },
        "regime": regime,
        "allocation_summary": {
            "equity_pct": equity_pct,
            "defensive_pct": defensive_pct,
            "sector_etf_pct": etf_pct,
        },
        "holdings": holdings_out,
        "recommendations": recommendations,
    }


def save_portfolio(portfolio: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(portfolio, indent=2), encoding="utf-8")
    return path


def format_portfolio_text(portfolio: dict[str, Any]) -> str:
    meta = portfolio.get("meta", {})
    regime = portfolio.get("regime", {})
    summary = portfolio.get("allocation_summary", {})
    lines = [
        "FINANCE AGENT PORTFOLIO",
        "=" * 56,
        "",
        f"Generated: {meta.get('generated_at', '')[:19].replace('T', ' ')} UTC",
        f"Holdings: {meta.get('holdings_count', 0)}  |  "
        f"Notional: ${meta.get('notional_usd', 0):,.0f}" if meta.get("notional_usd") else "",
        f"Regime: {regime.get('label', '?')} ({regime.get('posture', '?')})  "
        f"risk-on {regime.get('risk_on_score', 0):.2f}",
        "",
        f"Allocation — Equity {summary.get('equity_pct', 0):.1f}%  |  "
        f"ETFs {summary.get('sector_etf_pct', 0):.1f}%  |  "
        f"Defensive {summary.get('defensive_pct', 0):.1f}%",
        "",
        f"{'Symbol':<8} {'Weight':>7}  {'Score':>6}  {'Role':<12}  Rationale",
        "-" * 56,
    ]
    for h in portfolio.get("holdings", []):
        rationale = (h.get("rationale") or "")[:42]
        lines.append(
            f"{h['symbol']:<8} {h['weight_pct']:>6.1f}%  "
            f"{h.get('score', 0):>6.2f}  {h.get('role', ''):<12}  {rationale}"
        )
        if h.get("allocation_usd"):
            price_note = f" @ ${h['price']:.2f}" if h.get("price") else ""
            lines.append(f"         ${h['allocation_usd']:,.0f}{price_note}")
    lines.append("")
    recs = portfolio.get("recommendations", [])
    if recs:
        lines.append("Recommendations:")
        for rec in recs:
            lines.append(f"  • {rec}")
    sources = meta.get("source_files", [])
    if sources:
        lines.append("")
        lines.append(f"Sources: {', '.join(sources)}")
    return "\n".join(lines).strip()