"""
Prediction Tracking & Learning
==============================
Shared JSONL prediction logging for all Finance agents, plus a simple
accuracy backtester and confidence-learning helper.

Every agent run can append a compact record of what it predicted (its
recommendations/signals and a directional bias) to a JSONL log. Later,
``evaluate_accuracy`` replays that log against live reference-ticker
prices to measure how often each agent's directional bias was right.
``learning_adjustment`` turns that track record into a small confidence
multiplier agents can apply to their own scoring, so agents with a good
track record are trusted a bit more and agents with a poor one are
dampened -- a lightweight "learn from past predictions" feedback loop.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Finance-Tracking/1.0 (shaggychunxx@gmail.com)"}

DEFAULT_LOG_PATH = Path("output/prediction_log.jsonl")

BULLISH_KEYWORDS = (
    "buy",
    "bullish",
    "long",
    "upside",
    "overweight",
    "accumulate",
    "rally",
    "outperform",
)
BEARISH_KEYWORDS = (
    "sell",
    "bearish",
    "short",
    "downside",
    "underweight",
    "reduce",
    "sell-off",
    "selloff",
    "underperform",
)


def _fetch_reference_price(ticker: str) -> float | None:
    """Best-effort current price fetch. Returns None on any failure."""
    try:
        resp = requests.get(
            CHART_API.format(symbol=ticker),
            params={"interval": "1d", "range": "1d"},
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        result = data["chart"]["result"][0]
        price = result["meta"].get("regularMarketPrice")
        return float(price) if price is not None else None
    except Exception:
        return None


def _extract_text_blob(result: dict[str, Any]) -> str:
    """Pull recommendation/signal text out of an agent's result dict."""
    parts: list[str] = []
    for key in ("recommendations", "market_signals", "signals"):
        value = result.get(key)
        if isinstance(value, list):
            parts.extend(str(v) for v in value)
        elif isinstance(value, dict):
            parts.extend(f"{k}: {v}" for k, v in value.items())
        elif isinstance(value, str):
            parts.append(value)
    return " | ".join(parts).lower()


def _infer_direction(text_blob: str) -> str:
    bullish_hits = sum(1 for kw in BULLISH_KEYWORDS if kw in text_blob)
    bearish_hits = sum(1 for kw in BEARISH_KEYWORDS if kw in text_blob)
    if bullish_hits == 0 and bearish_hits == 0:
        return "neutral"
    return "bullish" if bullish_hits >= bearish_hits else "bearish"


def _resolve_log_path(output: Path | None, log_path: Path | None) -> Path:
    if log_path is not None:
        return log_path
    if output is not None:
        return output.parent / "prediction_log.jsonl"
    return DEFAULT_LOG_PATH


def log_prediction(
    agent: str,
    result: dict[str, Any],
    output: Path | None = None,
    reference_ticker: str = "SPY",
    log_path: Path | None = None,
) -> dict[str, Any]:
    """Append a JSONL record of this run's predictions for future backtesting.

    Best-effort: if the reference price can't be fetched, the entry is still
    logged (with ``reference_price: null``) so no run is ever blocked on
    tracking.
    """
    path = _resolve_log_path(output, log_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    text_blob = _extract_text_blob(result)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "reference_ticker": reference_ticker,
        "reference_price": _fetch_reference_price(reference_ticker),
        "predicted_direction": _infer_direction(text_blob),
        "recommendations": result.get("recommendations"),
        "market_signals": result.get("market_signals") or result.get("signals"),
    }

    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    return entry


def _read_log(log_path: Path) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def evaluate_accuracy(
    log_path: Path = DEFAULT_LOG_PATH,
    agent: str | None = None,
    horizon_days: int = 7,
) -> dict[str, Any]:
    """Backtest logged predictions that are at least ``horizon_days`` old.

    Compares each entry's ``predicted_direction`` against the reference
    ticker's actual move since the prediction was logged.
    """
    entries = _read_log(log_path)
    now = time.time()
    horizon_seconds = horizon_days * 86400

    eligible: list[dict[str, Any]] = []
    for entry in entries:
        if agent is not None and entry.get("agent") != agent:
            continue
        if entry.get("predicted_direction") == "neutral":
            continue
        if entry.get("reference_price") is None:
            continue
        try:
            logged_at = datetime.fromisoformat(entry["timestamp"]).timestamp()
        except (KeyError, ValueError):
            continue
        if now - logged_at < horizon_seconds:
            continue
        eligible.append(entry)

    price_cache: dict[str, float | None] = {}
    by_agent: dict[str, dict[str, int]] = {}
    total_hits = 0
    total_scored = 0

    for entry in eligible:
        ticker = entry["reference_ticker"]
        if ticker not in price_cache:
            price_cache[ticker] = _fetch_reference_price(ticker)
        current_price = price_cache[ticker]
        if current_price is None:
            continue

        reference_price = entry["reference_price"]
        actual_return = (current_price - reference_price) / reference_price
        actual_direction = "bullish" if actual_return > 0 else "bearish"
        hit = entry["predicted_direction"] == actual_direction

        stats = by_agent.setdefault(entry["agent"], {"scored": 0, "hits": 0})
        stats["scored"] += 1
        stats["hits"] += int(hit)
        total_scored += 1
        total_hits += int(hit)

    result: dict[str, Any] = {
        "horizon_days": horizon_days,
        "evaluated": total_scored,
        "overall_hit_rate": (total_hits / total_scored) if total_scored else None,
        "by_agent": {
            name: {
                **stats,
                "hit_rate": (stats["hits"] / stats["scored"]) if stats["scored"] else None,
            }
            for name, stats in by_agent.items()
        },
    }
    return result


def learning_adjustment(
    agent: str,
    log_path: Path = DEFAULT_LOG_PATH,
    horizon_days: int = 7,
    min_samples: int = 5,
) -> float:
    """Confidence multiplier learned from an agent's own track record.

    Returns 1.0 (no adjustment) until at least ``min_samples`` predictions
    have been scored. Otherwise nudges confidence up for agents that have
    historically been right more than half the time, and down for agents
    that haven't, clipped to a modest [0.85, 1.15] band so a small sample
    can't wildly distort output.
    """
    stats = evaluate_accuracy(log_path=log_path, agent=agent, horizon_days=horizon_days)
    agent_stats = stats["by_agent"].get(agent)
    if not agent_stats or agent_stats["scored"] < min_samples:
        return 1.0

    hit_rate = agent_stats["hit_rate"]
    adjustment = 1.0 + (hit_rate - 0.5) * 0.4
    return max(0.85, min(1.15, adjustment))
