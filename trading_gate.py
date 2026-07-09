"""Stricter trading gates — sample minimums, accuracy floors, and cluster agreement."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app_paths import OUTPUT, ROOT

DEFAULT_TRADING_GATE = {
    "enabled": True,
    "min_live_samples": 25,
    "min_benchmark_samples": 8,
    "min_accuracy_pct": 40.0,
    "require_cluster_agreement": True,
    "min_agreeing_clusters": 2,
    "min_cluster_contribution": 0.08,
    "min_net_score": 0.12,
}

TRADING_EXEMPT_AGENTS = frozenset({
    "etrade",
    "history",
    "regime",
    "profit-optimizer",
    "market-predictor",
    "data-steward",
    "records-management",
})

IGNORE_CLUSTERS = frozenset({"other", "data_platform", "execution"})


def load_trading_gate_settings(config_path: Path | None = None) -> dict[str, Any]:
    settings = dict(DEFAULT_TRADING_GATE)
    path = config_path or (ROOT / "etrade_config.json")
    if not path.exists():
        return settings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        strategy = raw.get("strategy", {})
        if isinstance(strategy, dict):
            nested = strategy.get("trading_gate", {})
            if isinstance(nested, dict):
                settings.update({k: nested[k] for k in settings if k in nested})
        top = raw.get("trading_gate", {})
        if isinstance(top, dict):
            settings.update({k: top[k] for k in settings if k in top})
    except (json.JSONDecodeError, OSError):
        pass
    return settings


def _source_agent_id(source: str) -> str:
    return str(source or "").replace("_", "-")


def agent_trading_eligibility(agent_id: str, *, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return whether an agent may influence live trading (orders/portfolio)."""
    from agent_fusion import TRADING_ACCURACY_EXCLUDE_PCT
    from prediction_accuracy import BENCHMARK_SOURCE, get_agent_accuracy

    aid = _source_agent_id(agent_id)
    gate = settings or load_trading_gate_settings()
    if not gate.get("enabled", True):
        return {"eligible": True, "agent_id": aid, "reason": "gate_disabled"}

    if aid in TRADING_EXEMPT_AGENTS:
        return {"eligible": True, "agent_id": aid, "reason": "exempt_source"}

    entry = get_agent_accuracy(aid)
    if not entry:
        return {"eligible": False, "agent_id": aid, "reason": "no_accuracy_data", "total_samples": 0}

    total = int(entry.get("total_scored") or entry.get("total") or 0)
    live_scored = int(entry.get("live_scored") or 0)
    source = str(entry.get("accuracy_source") or "")
    min_live = int(gate.get("min_live_samples", DEFAULT_TRADING_GATE["min_live_samples"]))
    min_bench = int(gate.get("min_benchmark_samples", DEFAULT_TRADING_GATE["min_benchmark_samples"]))
    if source in {"live_scored", "live_benchmark_blend"}:
        min_required = min_live
        total = max(total, live_scored)
    else:
        min_required = min_bench

    combined = (
        entry.get("combined_accuracy_pct")
        or entry.get("weighted_accuracy_pct")
        or entry.get("accuracy_pct")
    )
    min_acc = float(gate.get("min_accuracy_pct", DEFAULT_TRADING_GATE["min_accuracy_pct"]))

    if total < min_required:
        return {
            "eligible": False,
            "agent_id": aid,
            "reason": f"insufficient_samples ({total}<{min_required})",
            "total_samples": total,
            "accuracy_pct": combined,
        }

    if combined is not None and float(combined) < min_acc:
        return {
            "eligible": False,
            "agent_id": aid,
            "reason": f"accuracy_below_floor ({float(combined):.1f}%<{min_acc:.1f}%)",
            "total_samples": total,
            "accuracy_pct": combined,
        }

    return {
        "eligible": True,
        "agent_id": aid,
        "reason": "ok",
        "total_samples": total,
        "accuracy_pct": combined,
        "accuracy_source": source or "live",
    }


def evaluate_cluster_agreement(
    by_cluster: dict[str, float] | None,
    *,
    net_score: float,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Require multiple independent agent clusters to lean the same way."""
    gate = settings or load_trading_gate_settings()
    clusters = dict(by_cluster or {})
    min_clusters = int(gate.get("min_agreeing_clusters", DEFAULT_TRADING_GATE["min_agreeing_clusters"]))
    min_contrib = float(gate.get("min_cluster_contribution", DEFAULT_TRADING_GATE["min_cluster_contribution"]))
    min_net = float(gate.get("min_net_score", DEFAULT_TRADING_GATE["min_net_score"]))

    if not gate.get("require_cluster_agreement", True):
        return {
            "passes": abs(net_score) >= min_net,
            "agreeing_clusters": sorted(clusters),
            "required_clusters": min_clusters,
            "reason": "cluster_agreement_disabled",
        }

    if net_score >= min_net:
        agreeing = [
            name
            for name, value in clusters.items()
            if name not in IGNORE_CLUSTERS and float(value) >= min_contrib
        ]
        direction = "bullish"
    elif net_score <= -min_net:
        agreeing = [
            name
            for name, value in clusters.items()
            if name not in IGNORE_CLUSTERS and float(value) <= -min_contrib
        ]
        direction = "bearish"
    else:
        return {
            "passes": False,
            "agreeing_clusters": [],
            "required_clusters": min_clusters,
            "direction": "flat",
            "reason": f"net_score_below_threshold ({net_score:.3f}<{min_net:.3f})",
        }

    passes = len(agreeing) >= min_clusters
    return {
        "passes": passes,
        "agreeing_clusters": sorted(agreeing),
        "required_clusters": min_clusters,
        "direction": direction,
        "reason": "ok" if passes else f"need_{min_clusters}_clusters_got_{len(agreeing)}",
    }


def ticker_trading_gate(
    *,
    symbol: str,
    score: float,
    by_cluster: dict[str, float] | None,
    sources: set[str] | list[str] | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full gate evaluation for a scored ticker."""
    gate = settings or load_trading_gate_settings()
    sym = str(symbol or "").upper()
    source_set = {_source_agent_id(s) for s in (sources or [])}
    eligible_sources = []
    blocked_sources = []
    for src in sorted(source_set):
        row = agent_trading_eligibility(src, settings=gate)
        if row.get("eligible"):
            eligible_sources.append(src)
        elif src not in TRADING_EXEMPT_AGENTS:
            blocked_sources.append({"agent_id": src, "reason": row.get("reason")})

    cluster = evaluate_cluster_agreement(by_cluster, net_score=score, settings=gate)
    has_eligible_agent = bool(eligible_sources)
    passes = (
        gate.get("enabled", True)
        and has_eligible_agent
        and cluster.get("passes", False)
    )
    if not gate.get("enabled", True):
        passes = score > 0

    return {
        "symbol": sym,
        "passes": passes,
        "score": round(float(score), 4),
        "eligible_agent_sources": eligible_sources,
        "blocked_agent_sources": blocked_sources,
        "cluster_agreement": cluster,
    }


def filter_tickers_for_trading(
    tickers: list[Any],
    *,
    settings: dict[str, Any] | None = None,
) -> list[Any]:
    """Keep only tickers that pass trading gates (portfolio selection)."""
    gate = settings or load_trading_gate_settings()
    if not gate.get("enabled", True):
        return tickers

    kept: list[Any] = []
    for ticker in tickers:
        by_cluster = getattr(ticker, "by_cluster", None) or {}
        row = ticker_trading_gate(
            symbol=getattr(ticker, "symbol", ""),
            score=float(getattr(ticker, "score", 0) or 0),
            by_cluster=dict(by_cluster),
            sources=getattr(ticker, "sources", set()),
            settings=gate,
        )
        ticker.trading_gate = row  # type: ignore[attr-defined]
        if row.get("passes"):
            kept.append(ticker)
    return kept


def apply_trading_gates_to_plan(
    plan: Any,
    *,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Block BUY orders that fail accuracy/cluster gates."""
    gate = settings or load_trading_gate_settings()
    if not gate.get("enabled", True):
        return {"enabled": False}

    holdings_by_symbol = {
        str(row.get("symbol", "")).upper(): row
        for row in (plan.target_holdings or [])
        if isinstance(row, dict)
    }
    blocked_buys = 0
    allowed_buys = 0

    for order in plan.orders:
        if order.action != "BUY" or order.quantity <= 0:
            continue
        sym = str(order.symbol).upper()
        holding = holdings_by_symbol.get(sym, {})
        gate_row = holding.get("trading_gate")
        if not isinstance(gate_row, dict):
            gate_row = ticker_trading_gate(
                symbol=sym,
                score=float(holding.get("score") or 0),
                by_cluster=holding.get("by_cluster") or {},
                sources=holding.get("sources") or [],
                settings=gate,
            )

        if gate_row.get("passes"):
            allowed_buys += 1
            continue

        order.status = "blocked"
        cluster = gate_row.get("cluster_agreement") or {}
        reason = cluster.get("reason") or "trading_gate"
        blocked = gate_row.get("blocked_agent_sources") or []
        if blocked:
            preview = blocked[0].get("reason", "")
            order.message = f"Blocked — trading gate ({reason}; {preview})"
        else:
            order.message = f"Blocked — trading gate ({reason})"
        blocked_buys += 1

    summary = {
        "enabled": True,
        "allowed_buys": allowed_buys,
        "blocked_buys": blocked_buys,
        "min_accuracy_pct": gate.get("min_accuracy_pct"),
        "min_agreeing_clusters": gate.get("min_agreeing_clusters"),
        "require_cluster_agreement": gate.get("require_cluster_agreement"),
    }
    plan.meta.setdefault("trading_gate", summary)
    return summary


def trading_gate_summary_for_portfolio(tickers: list[Any]) -> dict[str, Any]:
    passed = sum(1 for t in tickers if getattr(t, "trading_gate", {}).get("passes"))
    return {
        "enabled": True,
        "candidates": len(tickers),
        "passed": passed,
    }