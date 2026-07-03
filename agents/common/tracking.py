"""Prediction catalog and accuracy back-testing utilities.

Every Finance agent produces sector/ticker market signals with a directional
``bias`` (BULLISH / BEARISH / NEUTRAL). This module lets any agent — or
``main.py`` on its behalf — catalogue the vital, backtestable information from
a run (signals, key metrics, recommendations, and a reference price snapshot
for each mentioned ticker) into an append-only JSONL log.

Once enough time has passed, :func:`evaluate_accuracy` replays the catalog
against live prices to score whether each directional call was correct,
producing a simple hit-rate accuracy report per agent.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Finance-Prediction-Tracker/1.0 (shaggychunxx@gmail.com)"}

DEFAULT_LOG_PATH = Path("output/prediction_log.jsonl")

#: Directional biases that make a directional (backtestable) call.
_DIRECTIONAL_BIAS = {"BULLISH": 1, "BEARISH": -1}

#: Cap on distinct tickers priced per logged snapshot, to keep run time bounded.
_MAX_PRICED_TICKERS = 25


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fetch_price(symbol: str) -> float | None:
    """Fetch the latest regular-market price for ``symbol``, or ``None`` on failure."""
    try:
        resp = requests.get(
            CHART_API.format(symbol=symbol),
            params={"interval": "1d", "range": "5d"},
            headers=HEADERS,
            timeout=25,
        )
        if resp.status_code == 429:
            time.sleep(2)
            resp = requests.get(
                CHART_API.format(symbol=symbol),
                params={"interval": "1d", "range": "5d"},
                headers=HEADERS,
                timeout=25,
            )
        resp.raise_for_status()
        result = resp.json()["chart"]["result"][0]
        price = result["meta"].get("regularMarketPrice")
        return float(price) if price is not None else None
    except Exception:
        return None


def _unique_tickers(market_signals: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for sig in market_signals:
        for ticker in sig.get("tickers", []) or []:
            if ticker not in seen:
                seen.add(ticker)
                ordered.append(ticker)
    return ordered[:_MAX_PRICED_TICKERS]


def build_snapshot(
    agent: str,
    result: dict[str, Any],
    price_fetcher: Callable[[str], float | None] = fetch_price,
) -> dict[str, Any]:
    """Extract the vital, backtestable information from an agent's report.

    Captures the market signals (sector/bias/tickers/reason), key metrics,
    recommendations, and a reference price for every ticker mentioned in a
    signal so accuracy can be scored later without re-running the agent.
    """
    meta = result.get("meta", {})
    market_signals = result.get("market_signals", []) or []
    reference_prices: dict[str, float] = {}
    for ticker in _unique_tickers(market_signals):
        price = price_fetcher(ticker)
        if price is not None:
            reference_prices[ticker] = price

    return {
        "agent": agent,
        "recorded_at": _utc_now().isoformat(),
        "expert_summary": meta.get("expert_summary"),
        "metrics": result.get("metrics", {}),
        "market_signals": market_signals,
        "recommendations": result.get("recommendations", []),
        "reference_prices": reference_prices,
    }


def log_prediction(
    agent: str,
    result: dict[str, Any],
    log_path: Path | str = DEFAULT_LOG_PATH,
    price_fetcher: Callable[[str], float | None] = fetch_price,
) -> dict[str, Any]:
    """Catalog ``result`` for ``agent`` by appending a snapshot to the JSONL log."""
    snapshot = build_snapshot(agent, result, price_fetcher=price_fetcher)
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(snapshot) + "\n")
    return snapshot


def load_predictions(
    log_path: Path | str = DEFAULT_LOG_PATH,
    agent: str | None = None,
) -> list[dict[str, Any]]:
    """Load catalogued prediction snapshots, optionally filtered by agent name."""
    log_path = Path(log_path)
    if not log_path.exists():
        return []
    records: list[dict[str, Any]] = []
    with log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if agent is None or entry.get("agent") == agent:
                records.append(entry)
    return records


@dataclass
class AccuracyReport:
    """Back-tested accuracy of one agent's catalogued directional calls."""

    agent: str
    signals_evaluated: int = 0
    correct: int = 0
    incorrect: int = 0
    skipped: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)

    @property
    def accuracy_pct(self) -> float | None:
        scored = self.correct + self.incorrect
        if scored == 0:
            return None
        return round(100.0 * self.correct / scored, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "signals_evaluated": self.signals_evaluated,
            "correct": self.correct,
            "incorrect": self.incorrect,
            "skipped": self.skipped,
            "accuracy_pct": self.accuracy_pct,
            "details": self.details,
        }


def evaluate_accuracy(
    log_path: Path | str = DEFAULT_LOG_PATH,
    agent: str | None = None,
    horizon_days: float = 1.0,
    price_fetcher: Callable[[str], float | None] = fetch_price,
) -> list[AccuracyReport]:
    """Score catalogued predictions against current live prices.

    Only entries recorded at least ``horizon_days`` ago are scored, so the
    market has had time to move. For each directional (BULLISH/BEARISH)
    signal with a reference price, the ticker's current price is compared to
    the reference price: the call is "correct" if the sign of the move
    matches the bias direction.
    """
    records = load_predictions(log_path, agent=agent)
    now = _utc_now()
    reports: dict[str, AccuracyReport] = {}
    price_cache: dict[str, float | None] = {}

    def cached_price(symbol: str) -> float | None:
        if symbol not in price_cache:
            price_cache[symbol] = price_fetcher(symbol)
        return price_cache[symbol]

    for entry in records:
        entry_agent = entry.get("agent", "unknown")
        recorded_at_raw = entry.get("recorded_at")
        try:
            recorded_at = datetime.fromisoformat(recorded_at_raw) if recorded_at_raw else None
        except ValueError:
            recorded_at = None
        if recorded_at is None:
            continue
        age_days = (now - recorded_at).total_seconds() / 86400
        if age_days < horizon_days:
            continue

        report = reports.setdefault(entry_agent, AccuracyReport(agent=entry_agent))
        reference_prices = entry.get("reference_prices", {}) or {}

        for sig in entry.get("market_signals", []) or []:
            bias = sig.get("bias")
            direction = _DIRECTIONAL_BIAS.get(bias)
            if direction is None:
                report.skipped += 1
                continue
            tickers = sig.get("tickers") or []
            if not tickers:
                report.skipped += 1
                continue

            evaluated = False
            for ticker in tickers:
                ref_price = reference_prices.get(ticker)
                if ref_price is None:
                    continue
                current_price = cached_price(ticker)
                if current_price is None:
                    continue
                if ref_price == 0:
                    continue
                pct_change = (current_price - ref_price) / ref_price * 100
                if pct_change == 0:
                    # No movement — not enough signal to call correct or incorrect.
                    continue
                is_correct = (pct_change > 0 and direction > 0) or (pct_change < 0 and direction < 0)
                report.signals_evaluated += 1
                if is_correct:
                    report.correct += 1
                else:
                    report.incorrect += 1
                report.details.append({
                    "sector": sig.get("sector"),
                    "ticker": ticker,
                    "bias": bias,
                    "recorded_at": recorded_at_raw,
                    "reference_price": ref_price,
                    "current_price": current_price,
                    "pct_change": round(pct_change, 2),
                    "correct": is_correct,
                })
                evaluated = True
                break

            if not evaluated:
                report.skipped += 1

    return sorted(reports.values(), key=lambda r: r.agent)
