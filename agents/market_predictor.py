"""Fuse Finance agent outputs into ranked market mover predictions."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.platform_catalog import active_agent_sources

BIAS_SCORES = {"BULLISH": 1.0, "NEUTRAL": 0.15, "BEARISH": -1.0}
HORIZON_RETURN_SCALE = {
    "1m": 0.015,
    "1h": 0.08,
    "24h": 0.35,
    "1wk": 0.55,
    "1mo": 1.0,
    "1yr": 2.5,
}
TOP_N = 25
INTRADAY_TOP_N = 12
PREDICTION_HORIZONS = ("1m", "1h", "24h", "1wk", "1mo", "1yr")
SYMBOL_RETURN_HINT_WEIGHT = 0.58
# Keep enrich small so post-fusion finishes under pipeline stall/timeouts.
ENRICH_PRICE_RETURNS_LIMIT = 25
# Actionable predictions must clear this confidence (else abstain → flat).
DEFAULT_ABSTAIN_MIN_CONFIDENCE = 0.52
DEFAULT_ABSTAIN_MIN_ABS_SCORE = 0.08


def _abstain_thresholds() -> tuple[float, float]:
    """(min_confidence, min_abs_composite) for actionable directional calls."""
    min_conf = DEFAULT_ABSTAIN_MIN_CONFIDENCE
    min_score = DEFAULT_ABSTAIN_MIN_ABS_SCORE
    try:
        from app_paths import ROOT
        import json

        raw = json.loads((ROOT / "etrade_config.json").read_text(encoding="utf-8"))
        strat = raw.get("strategy") if isinstance(raw.get("strategy"), dict) else {}
        block = strat.get("prediction_abstain") if isinstance(strat.get("prediction_abstain"), dict) else {}
        if "min_confidence" in block:
            min_conf = float(block["min_confidence"])
        if "min_abs_score" in block:
            min_score = float(block["min_abs_score"])
    except Exception:
        pass
    # Adaptive thresholds from meta-calibrator (night/live trial buckets)
    try:
        from prediction_meta import load_adaptive_abstain, rebuild_prediction_meta

        try:
            rebuild_prediction_meta()
        except Exception:
            pass
        a_conf, a_score = load_adaptive_abstain()
        min_conf = max(min_conf, a_conf)
        min_score = max(min_score, a_score)
    except Exception:
        pass
    try:
        from agent_learning import get_agent_learning

        learn = get_agent_learning("market-predictor")
        if learn is not None and learn.min_confidence_to_emit:
            min_conf = max(min_conf, float(learn.min_confidence_to_emit))
    except Exception:
        pass
    # Tighten on high-impact event days
    try:
        from event_calendar import event_flags

        if event_flags().get("high_impact"):
            min_conf = min(0.75, min_conf + 0.06)
            min_score = min(0.2, min_score + 0.02)
    except Exception:
        pass
    return max(0.35, min(0.85, min_conf)), max(0.02, min(0.25, min_score))


def _enrich_day_book_intraday(actionable: dict[str, list[dict[str, Any]]]) -> None:
    """Pull short-horizon momentum from Yahoo for day-book symbols (best effort)."""
    import urllib.request

    day_horizons = ("1m", "1h", "24h")
    symbols: list[str] = []
    for h in day_horizons:
        for row in actionable.get(h) or []:
            if isinstance(row, dict) and row.get("symbol"):
                symbols.append(str(row["symbol"]).upper())
    symbols = list(dict.fromkeys(symbols))[:12]
    mom: dict[str, float] = {}
    for sym in symbols:
        try:
            url = (
                f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
                f"?range=5d&interval=1h"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "FinanceDayBook/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = json.loads(resp.read().decode())
            result = ((payload.get("chart") or {}).get("result") or [None])[0]
            if not result:
                continue
            closes = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
            vals = [float(c) for c in closes if c is not None]
            if len(vals) < 4:
                continue
            ret = (vals[-1] / vals[-4] - 1.0) * 100.0
            mom[sym] = ret
        except Exception:
            continue
    if not mom:
        return
    for h in day_horizons:
        for row in actionable.get(h) or []:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").upper()
            if sym not in mom:
                continue
            r = mom[sym]
            row["intraday_momentum_3h_pct"] = round(r, 3)
            direction = str(row.get("predicted_direction") or "").lower()
            # Soft veto: strong adverse 3h momentum knocks day calls out
            if direction == "up" and r < -1.25:
                row["actionable"] = False
                row["predicted_direction"] = "flat"
                row["abstain_reason"] = "adverse_intraday_momentum"
            elif direction == "down" and r > 1.25:
                row["actionable"] = False
                row["predicted_direction"] = "flat"
                row["abstain_reason"] = "adverse_intraday_momentum"


def _apply_prediction_abstain(
    predictions: dict[str, list[dict[str, Any]]],
    *,
    min_confidence: float,
    min_abs_score: float,
) -> dict[str, Any]:
    """Mark low-confidence rows non-actionable and force flat direction for trading."""
    stats = {
        "min_confidence": min_confidence,
        "min_abs_score": min_abs_score,
        "total": 0,
        "actionable": 0,
        "abstained": 0,
    }
    actionable: dict[str, list[dict[str, Any]]] = {}
    for horizon, rows in predictions.items():
        kept: list[dict[str, Any]] = []
        if not isinstance(rows, list):
            actionable[horizon] = []
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            stats["total"] += 1
            conf = float(row.get("confidence") or 0.0)
            score = abs(float(row.get("composite_score") or 0.0))
            direction = str(row.get("predicted_direction") or "flat").lower()
            ok = (
                direction in {"up", "down"}
                and conf >= min_confidence
                and score >= min_abs_score
            )
            row["actionable"] = bool(ok)
            if not ok:
                stats["abstained"] += 1
                row["abstain_reason"] = (
                    "low_confidence"
                    if conf < min_confidence
                    else "weak_score"
                    if score < min_abs_score
                    else "flat_or_neutral"
                )
                # Preserve original for analysis; trading paths should use actionable only.
                row["raw_predicted_direction"] = direction
                row["predicted_direction"] = "flat"
            else:
                stats["actionable"] += 1
                kept.append(row)
        # Re-rank actionable book
        for i, row in enumerate(kept, start=1):
            row["rank"] = i
        actionable[horizon] = kept
    stats["actionable_rate"] = (
        round(stats["actionable"] / stats["total"], 3) if stats["total"] else 0.0
    )
    return {"actionable_predictions": actionable, "abstain_stats": stats}


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _normalize_symbol(symbol: str) -> str:
    sym = (symbol or "").strip().upper()
    if sym.startswith("^") and sym not in {"^GSPC"}:
        return ""
    if len(sym) > 6 and not sym.endswith("-USD"):
        return ""
    return sym.replace(".", "-")


def _direction(score: float) -> str:
    if score > 0.08:
        return "up"
    if score < -0.08:
        return "down"
    return "flat"


def _return_over_closes(closes: list[float], days_back: int) -> float | None:
    if len(closes) <= days_back:
        return None
    old = closes[-1 - days_back]
    if old <= 0:
        return None
    return (closes[-1] - old) / old * 100.0


def _enrich_symbol_price_returns(
    scores: dict[str, dict[str, Any]],
    symbols: list[str],
    *,
    fetch_missing: bool = True,
) -> None:
    """Attach per-symbol recent price returns from cached or Yahoo daily bars."""
    from price_history import bar_closes, fetch_daily_bars, load_daily_bars

    for sym in symbols:
        row = scores.get(sym)
        if not isinstance(row, dict):
            continue
        if row.get("return_5d_pct") is not None and row.get("return_20d_pct") is not None:
            continue
        bars = load_daily_bars(sym)
        if fetch_missing and len(bars) < 6:
            bars = fetch_daily_bars(sym, days=90, use_cache=True)
        closes = bar_closes(bars)
        if len(closes) < 2:
            continue
        for key, days in (("return_1d_pct", 1), ("return_5d_pct", 5), ("return_20d_pct", 20)):
            if row.get(key) is None:
                value = _return_over_closes(closes, days)
                if value is not None:
                    row[key] = round(value, 3)


def _symbol_return_hint(row: dict[str, Any], horizon: str) -> float | None:
    """Symbol-specific forward return hint (%) for the requested horizon."""
    hints: list[tuple[float, float]] = []

    def _add(value: Any, weight: float) -> None:
        if value is None:
            return
        try:
            hints.append((float(value), weight))
        except (TypeError, ValueError):
            return

    day = row.get("day_change_pct")
    week = row.get("week_change_pct")
    r1 = row.get("return_1d_pct")
    r5 = row.get("return_5d_pct")
    r20 = row.get("return_20d_pct")
    mom = row.get("momentum_score")
    hist_mom = row.get("history_momentum")
    hist_avg = row.get("history_avg_score")
    opp = row.get("opportunity_score")

    if horizon in {"1m", "1h"}:
        _add(r1, 0.45)
        _add(day, 0.35)
        if r5 is not None:
            _add(float(r5) / 5.0, 0.20)
    elif horizon == "24h":
        _add(r1, 0.40)
        _add(day, 0.30)
        if r5 is not None:
            _add(float(r5) / 5.0, 0.20)
        if mom is not None:
            _add((float(mom) - 0.5) * 2.0, 0.10)
    elif horizon == "1wk":
        _add(r5, 0.50)
        _add(week, 0.20)
        if r1 is not None:
            _add(float(r1) * 3.0, 0.15)
        if r20 is not None:
            _add(float(r20) / 4.0, 0.15)
    elif horizon == "1mo":
        _add(r20, 0.55)
        if r5 is not None:
            _add(float(r5) * 3.5, 0.25)
        if hist_avg is not None:
            _add(float(hist_avg) * 0.12, 0.10)
    elif horizon == "1yr":
        if r20 is not None:
            _add(float(r20) * 6.0, 0.55)
        if r5 is not None:
            _add(float(r5) * 14.0, 0.20)
        if hist_avg is not None:
            _add(float(hist_avg) * 0.35, 0.15)
        if hist_mom is not None:
            _add(float(hist_mom), 0.10)
    if opp is not None:
        _add(float(opp) * 4.0, 0.08)

    if not hints:
        return None
    total_w = sum(weight for _, weight in hints)
    if total_w <= 0:
        return None
    return sum(value * weight for value, weight in hints) / total_w


def _predicted_return_pct(
    row: dict[str, Any],
    *,
    score: float,
    direction: str,
    horizon: str,
    rank: int,
    limit: int,
) -> float:
    scale = HORIZON_RETURN_SCALE.get(horizon, HORIZON_RETURN_SCALE["24h"])
    base = min(12.0, max(0.4, abs(score) * 4.5)) * scale
    hint = _symbol_return_hint(row, horizon)
    if hint is not None:
        hint_mag = min(12.0, max(0.05, abs(hint)))
        blended = (1.0 - SYMBOL_RETURN_HINT_WEIGHT) * base + SYMBOL_RETURN_HINT_WEIGHT * hint_mag
        if direction == "down" and hint < 0:
            blended = (1.0 - SYMBOL_RETURN_HINT_WEIGHT) * base + SYMBOL_RETURN_HINT_WEIGHT * hint_mag
        elif direction == "up" and hint < 0:
            blended = max(0.15, base * 0.65 + hint_mag * 0.35)
    else:
        blended = base
    blended += max(0, limit - rank) * 0.01
    if direction == "down":
        return -round(blended, 2)
    if direction == "flat":
        return 0.0
    return round(max(0.05, blended), 2)


def _horizon_adjusted_score(symbol: str, row: dict[str, Any], horizon: str) -> float:
    from agent_fusion import fusion_weight

    base = float(row.get("score", 0))
    posture = row.get("_regime_posture", "neutral")
    adjustment = 0.0
    for source in row.get("sources", set()):
        w_h = fusion_weight(source, horizon=horizon, symbol=symbol, regime_posture=posture)
        w_24 = fusion_weight(source, horizon="24h", symbol=symbol, regime_posture=posture)
        adjustment += (w_h - w_24) * 0.2
    return base * (1.0 + adjustment)


def _collect_ticker_scores(output_dir: Path) -> dict[str, dict[str, Any]]:
    from agent_disagreement import collect_agent_bias_votes, disagreement_fusion_multiplier
    from agent_fusion import agent_cluster, apply_cluster_caps, current_regime, fusion_weight

    regime = current_regime()
    posture = str(regime.get("posture", "neutral"))
    bias_votes = collect_agent_bias_votes(output_dir)

    scores: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "score": 0.0,
            "confidence": 0.0,
            "sources": set(),
            "notes": [],
            "price": None,
            "by_cluster": defaultdict(float),
            "_regime_posture": posture,
        }
    )

    def bump(
        symbol: str,
        delta: float,
        *,
        source: str,
        note: str = "",
        confidence: float | None = None,
        price: float | None = None,
        sector_hint: str = "",
        ignore_accuracy_floor: bool = False,
    ) -> None:
        sym = _normalize_symbol(symbol)
        if not sym:
            return
        # Account-aware filter: skip names too expensive for this account's slot size.
        if price is not None and float(price) > 0:
            try:
                from agent_fusion import affordable_max_share_price

                cap = affordable_max_share_price()
                if cap is not None and float(price) > float(cap) * 1.02:
                    return
            except Exception:
                pass
        try:
            from agent_constraints import agent_preferred_horizon

            fusion_horizon = agent_preferred_horizon(source)
        except Exception:
            fusion_horizon = "24h"
        if ignore_accuracy_floor:
            # Patent-holder (and similar) research must still vote in fusion even
            # when the specialist's directional accuracy is below the exclude floor.
            # Do not use this path for live accuracy labels.
            weight = 0.28
        else:
            weight = fusion_weight(
                source,
                horizon=fusion_horizon,
                symbol=sym,
                sector_hint=sector_hint,
                regime_posture=posture,
                for_trading=True,
            )
            if weight <= 0:
                return
        try:
            from agent_learning import get_agent_learning

            learning = get_agent_learning(source)
            if learning is not None:
                if sym in learning.avoid_symbols:
                    weight *= 0.82
                elif sym in learning.trust_symbols:
                    weight *= 1.08
        except Exception:
            pass
        disagree_mult = disagreement_fusion_multiplier(sym, delta, bias_votes)
        weighted = delta * weight * disagree_mult
        row = scores[sym]
        cluster = agent_cluster(source)
        row["by_cluster"][cluster] += weighted
        row["score"] += weighted
        row["sources"].add(source)
        if note and note not in row["notes"]:
            row["notes"].append(note)
        if confidence is not None:
            row["confidence"] = max(row["confidence"], confidence * weight)
        if price is not None:
            row["price"] = price

    enhanced = _load_json(output_dir / "etrade_enhanced_quotes.json")
    if enhanced:
        for sym, quote in (enhanced.get("quotes") or {}).items():
            if not isinstance(quote, dict):
                continue
            last = quote.get("last_trade")
            change = quote.get("change_pct")
            note = "E*TRADE live quote"
            if change is not None:
                note = f"E*TRADE {change:+.2f}%"
            bump(
                sym,
                0.15,
                source="etrade",
                note=note,
                confidence=0.65,
                price=float(last) if last is not None else None,
            )
            norm = _normalize_symbol(sym)
            if norm and change is not None:
                try:
                    scores[norm]["day_change_pct"] = float(change)
                except (TypeError, ValueError):
                    pass

    # Domain context agents (power, weather, ag, freight, etc.) tilt the *market*
    # outlook — they must not nominate single-name equity picks into fusion.
    market_context_votes: list[dict[str, Any]] = []
    try:
        from agent_groups import is_market_context_agent
    except Exception:
        def is_market_context_agent(_aid: str) -> bool:  # type: ignore[misc]
            return False

    for src in active_agent_sources():
        data = _load_json(output_dir / src["file"])
        if not data:
            continue
        source = src["id"]
        context_only = is_market_context_agent(source)

        for sig in data.get("market_signals", []):
            bias = str(sig.get("bias", "NEUTRAL")).upper()
            delta = BIAS_SCORES.get(bias, 0.0) * 0.35
            sector = str(sig.get("sector", ""))
            reason = sig.get("reason", "")
            note = f"{sector}: {reason}" if sector else reason
            try:
                confidence = float(sig.get("confidence"))
            except (TypeError, ValueError):
                confidence = 0.55 if bias == "BULLISH" else 0.45 if bias == "BEARISH" else 0.35
            if context_only:
                # Market-context vote only — ignore any tickers listed on the signal.
                market_context_votes.append(
                    {
                        "source": source,
                        "bias": bias,
                        "confidence": confidence,
                        "delta": delta,
                        "sector": sector,
                        "reason": reason,
                    }
                )
                continue
            for ticker in sig.get("tickers", []):
                bump(
                    ticker,
                    delta,
                    source=source,
                    note=note,
                    confidence=confidence,
                    sector_hint=sector,
                )

        landscape = data.get("landscape")
        if isinstance(landscape, list):
            for card in landscape:
                if not isinstance(card, dict):
                    continue
                tick = str(card.get("holder_ticker") or card.get("symbol") or "").upper()
                if not tick:
                    continue
                held = str(card.get("source") or "").startswith("held-lot")
                terms = [str(t) for t in (card.get("impact_terms") or [])]
                # Short vs long is an input to fusion, not a patents price call.
                if "short" in terms and "long" in terms:
                    delta = 0.26
                    window = "short+long"
                elif "short" in terms:
                    delta = 0.16
                    window = "short"
                else:
                    delta = 0.20
                    window = "long"
                if held:
                    delta += 0.06
                company = card.get("company") or tick
                intended = str(card.get("intended_use") or "")[:90]
                bump(
                    tick,
                    delta,
                    source=source,
                    note=f"Innovation input {window} | {company} ({tick}): {intended}",
                    confidence=0.52 if held else 0.48,
                    sector_hint=str(card.get("industry") or card.get("sector") or "patent"),
                    ignore_accuracy_floor=True,
                )

        if source == "finance":
            for opp in data.get("trading_opportunities", []):
                score_val = float(opp.get("opportunity_score", 0))
                sym = _normalize_symbol(str(opp.get("symbol", "")))
                bump(
                    sym,
                    min(1.2, score_val * 0.5),
                    source=source,
                    note=opp.get("rationale", opp.get("strategy", "")),
                    confidence=min(0.9, 0.45 + score_val * 0.2),
                    price=opp.get("price"),
                )
                if sym:
                    row = scores[sym]
                    row["opportunity_score"] = score_val
                    for key, field in (("day_change_pct", "day_chg_pct"), ("week_change_pct", "week_chg_pct")):
                        if opp.get(field) is not None:
                            try:
                                row[key] = float(opp[field])
                            except (TypeError, ValueError):
                                pass

        if source == "datascience":
            for ticker_row in data.get("tickers", []) or []:
                sym = _normalize_symbol(str(ticker_row.get("symbol", "")))
                if not sym:
                    continue
                row = scores[sym]
                for key in (
                    "return_1d_pct",
                    "return_5d_pct",
                    "return_20d_pct",
                    "momentum_score",
                ):
                    if ticker_row.get(key) is not None:
                        try:
                            row[key] = float(ticker_row[key])
                        except (TypeError, ValueError):
                            pass
            for pick in data.get("top_picks", []):
                bump(
                    pick.get("symbol", ""),
                    float(pick.get("score", 0.5)) * 0.6,
                    source=source,
                    note=pick.get("rationale", "Data science pick"),
                    confidence=float(pick.get("confidence", 0.55)),
                    price=pick.get("price"),
                )
            for factor in data.get("factor_leaders", []):
                bump(
                    factor.get("symbol", ""),
                    0.25,
                    source=source,
                    note=factor.get("factor", "Factor leader"),
                    confidence=0.5,
                )

        metrics = data.get("metrics", {})
        if source == "markets":
            risk_on = float(metrics.get("risk_on_score", 0.5))
            if risk_on >= 0.6:
                bump("QQQ", 0.2, source=source, note="Risk-on regime", confidence=0.55)
                bump("SPY", 0.15, source=source, note="Risk-on regime", confidence=0.5)
            elif risk_on <= 0.4:
                bump("GLD", 0.2, source=source, note="Risk-off regime", confidence=0.55)
                bump("TLT", 0.15, source=source, note="Risk-off regime", confidence=0.5)

    try:
        from analysis_history import get_persistent_bullish_tickers

        for row in get_persistent_bullish_tickers(top_n=25):
            sym = _normalize_symbol(str(row.get("symbol", "")))
            bump(
                sym,
                row["composite"] * 0.2,
                source="history",
                note=f"Persistent bullish ({row['bullish_hits']} cycles)",
                confidence=min(0.85, 0.45 + row["avg_score"] * 0.2),
            )
            if sym:
                hist = scores[sym]
                hist["history_composite"] = float(row.get("composite") or 0.0)
                hist["history_avg_score"] = float(row.get("avg_score") or 0.0)
                hist["history_momentum"] = float(row.get("momentum") or 0.0)
    except Exception:
        pass

    apply_cluster_caps(scores)
    return scores


def _build_horizon_rows(
    ranked: list[tuple[str, dict[str, Any]]],
    horizon: str,
    *,
    limit: int = TOP_N,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    horizon_ranked = sorted(
        ranked,
        key=lambda item: _horizon_adjusted_score(item[0], item[1], horizon),
        reverse=True,
    )
    for rank, (symbol, row) in enumerate(horizon_ranked[:limit], start=1):
        score = _horizon_adjusted_score(symbol, row, horizon)
        direction = _direction(score)
        predicted_return = _predicted_return_pct(
            row,
            score=score,
            direction=direction,
            horizon=horizon,
            rank=rank,
            limit=limit,
        )

        confidence = min(0.95, max(0.35, float(row["confidence"] or 0.45) + min(0.25, abs(score) * 0.15)))
        try:
            from prediction_meta import calibrate_confidence

            confidence = calibrate_confidence(
                confidence,
                horizon=horizon,
                composite_score=score,
            )
        except Exception:
            pass
        entry: dict[str, Any] = {
            "rank": rank,
            "symbol": symbol,
            "predicted_direction": direction,
            "predicted_return_pct": round(predicted_return, 2),
            "confidence": round(confidence, 3),
            "composite_score": round(score, 3),
            "sources": sorted(row["sources"]),
            "rationale": "; ".join(row["notes"][:2]) or "Composite agent signal",
        }
        if row.get("price") is not None:
            entry["price_at_prediction"] = row["price"]
        entry["preferred_horizon"] = horizon
        rows.append(entry)
    return rows


def run_market_predictor_analysis(
    *,
    output: Path | None = None,
    pipeline_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(__file__).resolve().parent.parent
    output_dir = root / "output"
    output_path = output or (output_dir / "market_predictions.json")
    output_dir.mkdir(parents=True, exist_ok=True)

    scores = _collect_ticker_scores(output_dir)

    # Market-context agents (power, weather, ag, freight, etc.) tilt market outlook
    # without nominating single-name equity picks (tickers on their signals ignored).
    market_context: dict[str, Any] = {"votes": [], "net_tilt": 0.0, "label": "neutral", "vote_count": 0}
    try:
        from agent_groups import is_market_context_agent as _is_ctx
    except Exception:
        def _is_ctx(_a: str) -> bool:  # type: ignore[misc]
            return False

    ctx_votes: list[dict[str, Any]] = []
    net = 0.0
    for src in active_agent_sources():
        aid = str(src.get("id") or "")
        if not _is_ctx(aid):
            continue
        data = _load_json(output_dir / src["file"])
        if not data:
            continue
        for sig in data.get("market_signals") or []:
            if not isinstance(sig, dict):
                continue
            bias = str(sig.get("bias", "NEUTRAL")).upper()
            try:
                conf = float(sig.get("confidence") or 0.5)
            except (TypeError, ValueError):
                conf = 0.5
            net += BIAS_SCORES.get(bias, 0.0) * conf
            ctx_votes.append(
                {
                    "source": aid,
                    "bias": bias,
                    "confidence": round(conf, 3),
                    "sector": sig.get("sector"),
                    "reason": (sig.get("reason") or "")[:160],
                }
            )
    if ctx_votes:
        tilt = max(-0.35, min(0.35, net / max(len(ctx_votes), 1) * 0.45))
        market_context = {
            "votes": ctx_votes[:24],
            "vote_count": len(ctx_votes),
            "net_tilt": round(tilt, 4),
            "label": "risk-on" if tilt > 0.05 else "risk-off" if tilt < -0.05 else "neutral",
        }
        for _sym, row in scores.items():
            if not isinstance(row, dict):
                continue
            row["score"] = float(row.get("score") or 0) + tilt
            note = f"market-context {market_context['label']} ({tilt:+.2f})"
            notes = row.setdefault("notes", [])
            if isinstance(notes, list) and note not in notes:
                notes.append(note)

    ranked = sorted(scores.items(), key=lambda item: item[1]["score"], reverse=True)
    positive = [(sym, row) for sym, row in ranked if row["score"] > 0]
    negative = [(sym, row) for sym, row in reversed(ranked) if row["score"] < 0]
    movers = positive[:TOP_N]
    if len(movers) < 8 and negative:
        movers.extend(negative[: max(0, 8 - len(movers))])

    enrich_symbols: list[str] = []
    seen: set[str] = set()
    for sym, _row in movers + positive[:ENRICH_PRICE_RETURNS_LIMIT]:
        if sym and sym not in seen:
            seen.add(sym)
            enrich_symbols.append(sym)
    # Cache-only enrich by default (FINANCE_PREDICTOR_FETCH_PRICES=1 enables Yahoo).
    fetch_missing = str(os.environ.get("FINANCE_PREDICTOR_FETCH_PRICES", "0")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    _enrich_symbol_price_returns(scores, enrich_symbols, fetch_missing=fetch_missing)

    predictions = {
        horizon: _build_horizon_rows(
            movers,
            horizon,
            limit=INTRADAY_TOP_N if horizon in {"1m", "1h"} else TOP_N,
        )
        for horizon in PREDICTION_HORIZONS
    }
    min_conf, min_abs = _abstain_thresholds()
    abstain_pack = _apply_prediction_abstain(
        predictions,
        min_confidence=min_conf,
        min_abs_score=min_abs,
    )

    # Regime / disagreement / event gate — may wipe actionable book (no-trade)
    regime_gate: dict[str, Any] = {}
    try:
        from regime_trade_gate import evaluate_regime_trade_gate

        regime_gate = evaluate_regime_trade_gate()
        block_syms = set(regime_gate.get("block_symbols") or [])
        if regime_gate.get("block_new_entries"):
            for h, rows in (abstain_pack.get("actionable_predictions") or {}).items():
                for row in rows or []:
                    if isinstance(row, dict):
                        if not row.get("raw_predicted_direction"):
                            row["raw_predicted_direction"] = row.get("predicted_direction")
                        row["actionable"] = False
                        row["predicted_direction"] = "flat"
                        row["abstain_reason"] = "regime_no_trade"
                abstain_pack["actionable_predictions"][h] = []
            stats = abstain_pack.setdefault("abstain_stats", {})
            stats["regime_no_trade"] = True
            stats["regime_reasons"] = list(regime_gate.get("reasons") or [])
            stats["actionable"] = 0
            stats["actionable_rate"] = 0.0
        elif block_syms:
            for h, rows in list((abstain_pack.get("actionable_predictions") or {}).items()):
                kept = []
                for row in rows or []:
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("symbol") or "").upper() in block_syms:
                        if not row.get("raw_predicted_direction"):
                            row["raw_predicted_direction"] = row.get("predicted_direction")
                        row["actionable"] = False
                        row["predicted_direction"] = "flat"
                        row["abstain_reason"] = "contested_symbol"
                        continue
                    kept.append(row)
                for i, row in enumerate(kept, start=1):
                    row["rank"] = i
                abstain_pack["actionable_predictions"][h] = kept
    except Exception:
        regime_gate = {}

    # Light intraday enrichment for day horizons (1m/1h/24h) on top actionable names
    try:
        _enrich_day_book_intraday(abstain_pack.get("actionable_predictions") or {})
        # Drop rows killed by intraday veto
        for h, rows in list((abstain_pack.get("actionable_predictions") or {}).items()):
            kept = [r for r in (rows or []) if isinstance(r, dict) and r.get("actionable") is not False]
            for i, row in enumerate(kept, start=1):
                row["rank"] = i
            abstain_pack["actionable_predictions"][h] = kept
    except Exception:
        pass

    sources_used = [src["file"] for src in active_agent_sources() if (output_dir / src["file"]).exists()]
    fusion_meta: dict[str, Any] = {}
    try:
        from agent_fusion import current_regime, export_walk_forward_weights

        fusion_meta = export_walk_forward_weights()
    except Exception:
        try:
            from agent_fusion import current_regime

            fusion_meta = {"regime": current_regime()}
        except Exception:
            fusion_meta = {}

    pipeline_memory: dict[str, Any] = {}
    try:
        if pipeline_context:
            pipeline_memory = dict(pipeline_context)
        else:
            from agents.pipeline_memory import memory_bundle_for_agent

            pipeline_memory = memory_bundle_for_agent("market-predictor")
    except Exception:
        pass

    stamp = datetime.now(timezone.utc).isoformat()
    abs_stats = abstain_pack.get("abstain_stats") or {}
    result = {
        "meta": {
            "agent": "Market Predictor",
            "analyzed_at": stamp,
            "generated_at": stamp,
            "source_files": sources_used,
            "tickers_scored": len(scores),
            "horizons": list(predictions.keys()),
            "fusion": fusion_meta,
            "market_context": market_context,
            "pipeline_memory": pipeline_memory,
            "abstain": abs_stats,
            "regime_trade_gate": {
                "block_new_entries": bool(regime_gate.get("block_new_entries")),
                "reasons": list(regime_gate.get("reasons") or []),
                "event_day": bool(regime_gate.get("event_day")),
                "regime": regime_gate.get("regime") or {},
            },
            "trading_uses_actionable_only": True,
        },
        # Full book (includes abstained→flat) for analysis / accuracy recording
        "predictions": predictions,
        # Clean book for portfolio / trading (directional only, conf gated)
        "actionable_predictions": abstain_pack.get("actionable_predictions") or {},
        "recommendations": [
            f"Fused {len(sources_used)} agent report(s) into ranked mover predictions.",
            "Accuracy-weighted fusion with per-horizon, regime, domain, and cluster caps applied.",
            (
                f"Abstain gate: conf≥{min_conf:.2f}, |score|≥{min_abs:.2f} → "
                f"{abs_stats.get('actionable', 0)}/{abs_stats.get('total', 0)} actionable "
                f"({float(abs_stats.get('actionable_rate') or 0):.0%})."
            ),
            (
                f"Market-context tilt: {market_context.get('label')} "
                f"({market_context.get('net_tilt', 0):+.2f}) from "
                f"{market_context.get('vote_count', 0)} non-picker agent signal(s)."
                if market_context.get("vote_count")
                else "No market-context agent votes this cycle."
            ),
        ],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result