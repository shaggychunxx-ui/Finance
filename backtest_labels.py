"""Shared backtest labels: costs, regime, families, purged sampling.

Does not overwrite live agent accuracy percentages. Proxy/replay metrics
live in separate fields consumed by learning rebuild.
"""

from __future__ import annotations

from typing import Any

# Round-trip cost in percent (not bps). E*TRADE equity commission is 0;
# this is a spread + slippage stand-in so "hit" is not free money.
LIQUID_COST_PCT = 0.04  # 4 bps
DEFAULT_COST_PCT = 0.08  # 8 bps
LIQUID_SYMBOLS = frozenset(
    {
        "SPY",
        "QQQ",
        "DIA",
        "IWM",
        "VOO",
        "VTI",
        "IVV",
        "XLK",
        "XLF",
        "XLE",
        "XLV",
        "XLI",
        "XLY",
        "XLP",
        "XLU",
        "XLB",
        "XLRE",
        "XLC",
        "AAPL",
        "MSFT",
        "AMZN",
        "NVDA",
        "GOOGL",
        "GOOG",
        "META",
        "TSLA",
        "JPM",
        "BRK.B",
        "BRK-B",
        "UNH",
        "V",
        "MA",
        "WMT",
        "KO",
        "XOM",
    }
)

PROXY_SOURCES = frozenset(
    {"bar_walk_forward", "full_day_walk_forward", "proxy"}
)
REPLAY_SOURCES = frozenset({"snapshot_replay", "expert_replay", "replay"})
FAMILY_MOMENTUM = "momentum"
FAMILY_REVERSION = "mean_reversion"
FAMILY_RISK_OFF = "risk_off"
FAMILY_REPLAY = "expert_replay"
FAMILY_PROXY = "proxy_momentum"

# 3-way (up/down/flat) coin prior — proxy edge only, never live %.
PROXY_ACCURACY_PRIOR = 33.0
PROXY_EDGE_FLOOR = 33.0

HORIZON_BARS = {"24h": 1, "1wk": 5, "1mo": 21, "1yr": 252}


def round_trip_cost_pct(symbol: str) -> float:
    return LIQUID_COST_PCT if str(symbol or "").upper() in LIQUID_SYMBOLS else DEFAULT_COST_PCT


def signed_forward_pct(predicted_direction: str, actual_return_pct: float) -> float:
    pred = str(predicted_direction or "flat").lower()
    if pred == "up":
        return float(actual_return_pct)
    if pred == "down":
        return -float(actual_return_pct)
    return 0.0


def net_return_pct(
    predicted_direction: str,
    actual_return_pct: float,
    *,
    symbol: str = "",
) -> float:
    """Signed forward return minus round-trip cost. Flat takes no position."""
    pred = str(predicted_direction or "flat").lower()
    if pred not in {"up", "down"}:
        return 0.0
    return round(signed_forward_pct(pred, actual_return_pct) - round_trip_cost_pct(symbol), 4)


def binary_brier(predicted_direction: str, hit: bool, confidence: float | None) -> float | None:
    pred = str(predicted_direction or "flat").lower()
    if pred not in {"up", "down"}:
        return None
    try:
        conf = float(confidence if confidence is not None else 0.5)
    except (TypeError, ValueError):
        conf = 0.5
    conf = max(0.01, min(0.99, conf))
    y = 1.0 if hit else 0.0
    return round((conf - y) ** 2, 4)


def regime_from_closes(closes: list[float], idx: int, *, window: int = 200) -> str:
    """risk-on if last close is above SMA(window), else risk-off. Neutral if short history."""
    if idx < 20 or not closes:
        return "neutral"
    i = min(idx, len(closes) - 1)
    w = min(window, i + 1)
    if w < 20:
        return "neutral"
    sma = sum(closes[i - w + 1 : i + 1]) / w
    if sma <= 0:
        return "neutral"
    px = closes[i]
    if px > sma * 1.005:
        return "risk-on"
    if px < sma * 0.995:
        return "risk-off"
    return "neutral"


def purged_keep(idx: int, min_start: int, horizon: str, base_step: int) -> bool:
    """Drop overlapping 1yr (and 1mo when step is small) evaluation points."""
    fwd = HORIZON_BARS.get(str(horizon or ""), 1)
    if fwd < 21:
        return True
    stride = max(int(base_step or 1), int(fwd))
    return ((idx - min_start) % stride) == 0


def family_for_agent(agent_id: str) -> str:
    aid = str(agent_id or "")
    if aid in {"momentum-reversion"}:
        return FAMILY_REPLAY
    if aid in {
        "markets",
        "finance",
        "financial-data",
        "datascience",
        "sales-analytics",
        "research-statistics",
    }:
        return FAMILY_MOMENTUM
    if aid in {
        "empirical-probability",
        "theoretical-probability",
        "combined-conditional",
    }:
        return FAMILY_REVERSION
    if aid in {"geopolitics", "events"}:
        return FAMILY_RISK_OFF
    return FAMILY_PROXY


def source_bucket(source: str | None) -> str:
    src = str(source or "").strip().lower()
    if src in REPLAY_SOURCES:
        return "replay"
    if src in PROXY_SOURCES or src.startswith("bar_"):
        return "proxy"
    if src in {"live", "live_scored", ""}:
        return "live"
    return "live"


def row_accuracy_pct(rows: list[dict[str, Any]]) -> tuple[float | None, int]:
    if not rows:
        return None, 0
    total = 0
    hits = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        total += 1
        if row.get("hit"):
            hits += 1
    if total <= 0:
        return None, 0
    return round(hits / total * 100, 1), total


def mean_net_return(rows: list[dict[str, Any]]) -> float | None:
    vals: list[float] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("net_return_pct")
        if raw is None:
            continue
        try:
            vals.append(float(raw))
        except (TypeError, ValueError):
            continue
    if not vals:
        return None
    return round(sum(vals) / len(vals), 4)


def mean_brier(rows: list[dict[str, Any]]) -> float | None:
    vals: list[float] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("brier")
        if raw is None:
            continue
        try:
            vals.append(float(raw))
        except (TypeError, ValueError):
            continue
    if not vals:
        return None
    return round(sum(vals) / len(vals), 4)


def proxy_edge_score(accuracy_pct: float | None, samples: int) -> float:
    """Shrink proxy accuracy toward a 33% 3-way prior. Never used as live %."""
    if accuracy_pct is None or samples < 8:
        return 0.0
    n = min(200, max(0, samples))
    shrink = n / (n + 40.0)
    blended = PROXY_ACCURACY_PRIOR * (1.0 - shrink) + float(accuracy_pct) * shrink
    return round((blended - PROXY_EDGE_FLOOR) / 20.0, 4)


def by_regime_accuracy(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    buckets: dict[str, dict[str, int]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("regime") or "neutral")
        bucket = buckets.setdefault(key, {"total": 0, "hits": 0})
        bucket["total"] += 1
        bucket["hits"] += 1 if row.get("hit") else 0
    out: dict[str, dict[str, Any]] = {}
    for key, bucket in buckets.items():
        total = bucket["total"]
        if total < 4:
            continue
        out[key] = {
            "total": total,
            "hits": bucket["hits"],
            "accuracy_pct": round(bucket["hits"] / total * 100, 1),
        }
    return out
