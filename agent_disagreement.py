"""Cross-agent disagreement signals for fusion and per-agent confidence."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from app_paths import OUTPUT

BIAS_SCORES = {"BULLISH": 1.0, "NEUTRAL": 0.0, "BEARISH": -1.0}


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _normalize_symbol(symbol: str) -> str:
    sym = str(symbol or "").strip().upper()
    if not sym or sym.startswith("^") or len(sym) > 6:
        return ""
    return sym.replace(".", "-")


def _vote_from_signal(sig: dict[str, Any], *, source: str, votes: dict[str, dict[str, Any]]) -> None:
    bias = str(sig.get("bias", "NEUTRAL")).upper()
    if bias not in BIAS_SCORES or bias == "NEUTRAL":
        return
    try:
        confidence = float(sig.get("confidence", 0.55))
    except (TypeError, ValueError):
        confidence = 0.55
    weight = max(0.2, min(1.0, confidence))
    for ticker in sig.get("tickers") or []:
        sym = _normalize_symbol(str(ticker))
        if not sym:
            continue
        row = votes.setdefault(
            sym,
            {
                "bullish_weight": 0.0,
                "bearish_weight": 0.0,
                "bullish_agents": [],
                "bearish_agents": [],
                "neutral_agents": [],
            },
        )
        if bias == "BULLISH":
            row["bullish_weight"] += weight
            if source not in row["bullish_agents"]:
                row["bullish_agents"].append(source)
        elif bias == "BEARISH":
            row["bearish_weight"] += weight
            if source not in row["bearish_agents"]:
                row["bearish_agents"].append(source)


def collect_agent_bias_votes(
    output_dir: Path | None = None,
    *,
    agent_outputs: dict[str, dict[str, Any]] | None = None,
    exclude_agent: str = "",
) -> dict[str, dict[str, Any]]:
    """Aggregate directional votes per symbol from agent reports."""
    votes: dict[str, dict[str, Any]] = {}
    exclude = str(exclude_agent or "").replace("_", "-")

    if agent_outputs:
        for agent_id, data in agent_outputs.items():
            if not isinstance(data, dict) or agent_id == exclude:
                continue
            for sig in data.get("market_signals") or []:
                if isinstance(sig, dict):
                    _vote_from_signal(sig, source=agent_id, votes=votes)
        return votes

    try:
        from agents.platform_catalog import active_agent_sources

        sources = active_agent_sources(check_remote=False)
    except Exception:
        sources = []

    root = output_dir or OUTPUT
    for src in sources:
        agent_id = src["id"]
        if agent_id == exclude:
            continue
        data = _load_json(root / src["file"])
        if not isinstance(data, dict):
            continue
        for sig in data.get("market_signals") or []:
            if isinstance(sig, dict):
                _vote_from_signal(sig, source=agent_id, votes=votes)
    return votes


def disagreement_metrics(votes: dict[str, dict[str, Any]], symbol: str) -> dict[str, Any]:
    sym = _normalize_symbol(symbol)
    row = votes.get(sym) or {}
    bull = float(row.get("bullish_weight") or 0.0)
    bear = float(row.get("bearish_weight") or 0.0)
    total = bull + bear
    if total <= 0:
        return {
            "symbol": sym,
            "contested": False,
            "agreement_ratio": 1.0,
            "minority_weight": 0.0,
            "bullish_agents": [],
            "bearish_agents": [],
        }
    majority = max(bull, bear)
    minority = min(bull, bear)
    agreement = majority / total if total else 1.0
    return {
        "symbol": sym,
        "contested": minority > 0.35,
        "agreement_ratio": round(agreement, 3),
        "minority_weight": round(minority / total, 3) if total else 0.0,
        "bullish_agents": list(row.get("bullish_agents") or []),
        "bearish_agents": list(row.get("bearish_agents") or []),
    }


def disagreement_confidence_factor(symbol: str, bias: str, votes: dict[str, dict[str, Any]]) -> float:
    """Scale confidence down when agents disagree on the same symbol."""
    metrics = disagreement_metrics(votes, symbol)
    if not metrics.get("contested"):
        if metrics.get("agreement_ratio", 0) >= 0.85:
            return 1.05
        return 1.0
    minority = float(metrics.get("minority_weight") or 0.0)
    b = str(bias or "").upper()
    bull = float((votes.get(_normalize_symbol(symbol)) or {}).get("bullish_weight") or 0.0)
    bear = float((votes.get(_normalize_symbol(symbol)) or {}).get("bearish_weight") or 0.0)
    adding_majority = (b == "BULLISH" and bull >= bear) or (b == "BEARISH" and bear > bull)
    if adding_majority:
        return max(0.88, 1.0 - minority * 0.35)
    return max(0.55, 1.0 - minority * 0.85)


def disagreement_fusion_multiplier(symbol: str, delta: float, votes: dict[str, dict[str, Any]]) -> float:
    """Reduce fused score when directional agents split on a ticker."""
    if delta == 0:
        return 1.0
    metrics = disagreement_metrics(votes, symbol)
    if not metrics.get("contested"):
        return 1.0
    minority = float(metrics.get("minority_weight") or 0.0)
    return max(0.45, 1.0 - minority * 0.75)


def top_contested_symbols(votes: dict[str, dict[str, Any]], *, limit: int = 12) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sym, row in votes.items():
        bull = float(row.get("bullish_weight") or 0.0)
        bear = float(row.get("bearish_weight") or 0.0)
        total = bull + bear
        if total < 0.8:
            continue
        minority = min(bull, bear) / total
        if minority < 0.25:
            continue
        rows.append(
            {
                "symbol": sym,
                "bullish_agents": list(row.get("bullish_agents") or []),
                "bearish_agents": list(row.get("bearish_agents") or []),
                "disagreement": round(minority, 3),
            }
        )
    rows.sort(key=lambda item: item["disagreement"], reverse=True)
    return rows[:limit]