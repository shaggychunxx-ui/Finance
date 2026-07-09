"""Fuse Finance agent outputs into ranked market mover predictions."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.platform_catalog import active_agent_sources

BIAS_SCORES = {"BULLISH": 1.0, "NEUTRAL": 0.15, "BEARISH": -1.0}
HORIZON_RETURN_SCALE = {"24h": 0.35, "1wk": 0.55, "1mo": 1.0, "1yr": 2.5}
TOP_N = 25


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
    ) -> None:
        sym = _normalize_symbol(symbol)
        if not sym:
            return
        try:
            from agent_constraints import agent_preferred_horizon

            fusion_horizon = agent_preferred_horizon(source)
        except Exception:
            fusion_horizon = "24h"
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

    for src in active_agent_sources():
        data = _load_json(output_dir / src["file"])
        if not data:
            continue
        source = src["id"]

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
            for ticker in sig.get("tickers", []):
                bump(
                    ticker,
                    delta,
                    source=source,
                    note=note,
                    confidence=confidence,
                    sector_hint=sector,
                )

        if source == "finance":
            for opp in data.get("trading_opportunities", []):
                score_val = float(opp.get("opportunity_score", 0))
                bump(
                    opp.get("symbol", ""),
                    min(1.2, score_val * 0.5),
                    source=source,
                    note=opp.get("rationale", opp.get("strategy", "")),
                    confidence=min(0.9, 0.45 + score_val * 0.2),
                    price=opp.get("price"),
                )

        if source == "datascience":
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

        if source == "sales-analytics":
            for retailer in data.get("retail_leaders", []):
                bump(
                    retailer.get("symbol", ""),
                    0.3,
                    source=source,
                    note=retailer.get("category", "Retail leader"),
                    confidence=0.5,
                    sector_hint="retail",
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
            bump(
                row["symbol"],
                row["composite"] * 0.2,
                source="history",
                note=f"Persistent bullish ({row['bullish_hits']} cycles)",
                confidence=min(0.85, 0.45 + row["avg_score"] * 0.2),
            )
    except Exception:
        pass

    apply_cluster_caps(scores)
    return scores


def _build_horizon_rows(
    ranked: list[tuple[str, dict[str, Any]]],
    horizon: str,
) -> list[dict[str, Any]]:
    scale = HORIZON_RETURN_SCALE[horizon]
    rows: list[dict[str, Any]] = []
    horizon_ranked = sorted(
        ranked,
        key=lambda item: _horizon_adjusted_score(item[0], item[1], horizon),
        reverse=True,
    )
    for rank, (symbol, row) in enumerate(horizon_ranked[:TOP_N], start=1):
        score = _horizon_adjusted_score(symbol, row, horizon)
        direction = _direction(score)
        base_return = min(12.0, max(0.4, abs(score) * 4.5)) * scale
        if direction == "down":
            predicted_return = -base_return
        elif direction == "up":
            predicted_return = base_return
        else:
            predicted_return = 0.0

        confidence = min(0.95, max(0.35, float(row["confidence"] or 0.45) + min(0.25, abs(score) * 0.15)))
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
    ranked = sorted(scores.items(), key=lambda item: item[1]["score"], reverse=True)
    positive = [(sym, row) for sym, row in ranked if row["score"] > 0]
    negative = [(sym, row) for sym, row in reversed(ranked) if row["score"] < 0]
    movers = positive[:TOP_N]
    if len(movers) < 8 and negative:
        movers.extend(negative[: max(0, 8 - len(movers))])

    predictions = {
        horizon: _build_horizon_rows(movers, horizon)
        for horizon in ("24h", "1wk", "1mo", "1yr")
    }

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
    result = {
        "meta": {
            "agent": "Market Predictor",
            "analyzed_at": stamp,
            "generated_at": stamp,
            "source_files": sources_used,
            "tickers_scored": len(scores),
            "horizons": list(predictions.keys()),
            "fusion": fusion_meta,
            "pipeline_memory": pipeline_memory,
        },
        "predictions": predictions,
        "recommendations": [
            f"Fused {len(sources_used)} agent report(s) into ranked mover predictions.",
            "Accuracy-weighted fusion with per-horizon, regime, domain, and cluster caps applied.",
        ],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result