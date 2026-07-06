"""Accuracy-driven agent fusion: domains, regimes, clusters, calibration, floors."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app_paths import OUTPUT

FUSION_WEIGHTS_FILE = OUTPUT / "history" / "fusion_weights.json"

ACCURACY_FLOOR_PCT = 40.0
ACCURACY_EXCLUDE_PCT = 35.0
ACCURACY_FLOOR_WEIGHT = 0.25
MIN_SAMPLES_FLOOR = 8
MIN_SAMPLES_HORIZON = 4
MIN_SAMPLES_REGIME = 4
CLUSTER_WEIGHT_CAP = 0.45
OUT_OF_DOMAIN_FACTOR = 0.3

GENERALIST_AGENTS = frozenset({
    "finance",
    "markets",
    "datascience",
    "financial-data",
    "google-finance",
    "yahoo-finance",
    "geopolitics",
    "events",
    "theoretical-probability",
    "empirical-probability",
    "combined-conditional",
    "research-statistics",
    "market-predictor",
    "order-execution",
    "data-steward",
    "records-management",
})

AGENT_CLUSTERS: dict[str, str] = {
    "electricity": "energy_grid",
    "grid": "energy_grid",
    "meteorology": "energy_grid",
    "transportation": "transport_logistics",
    "logistics": "transport_logistics",
    "markets": "macro",
    "finance": "macro",
    "financial-data": "macro",
    "google-finance": "macro",
    "yahoo-finance": "macro",
    "geopolitics": "macro",
    "datascience": "quant",
    "theoretical-probability": "quant",
    "empirical-probability": "quant",
    "combined-conditional": "quant",
    "research-statistics": "quant",
    "events": "intelligence",
    "patents": "intelligence",
    "sales-analytics": "consumer",
    "order-execution": "execution",
    "data-steward": "data_platform",
    "records-management": "data_platform",
}

AGENT_DOMAINS: dict[str, dict[str, frozenset[str]]] = {
    "electricity": {
        "tickers": frozenset({"UNG", "USO", "XLE", "XLU", "VST", "NG", "D", "SO", "NEE", "AES", "ETR"}),
        "sectors": frozenset({"utilities", "energy", "power", "gas", "electric", "grid"}),
    },
    "grid": {
        "tickers": frozenset({"XLU", "VST", "NEE", "D", "SO", "AES", "ETR", "PEG", "EXC"}),
        "sectors": frozenset({"utilities", "grid", "power", "electric"}),
    },
    "meteorology": {
        "tickers": frozenset({"UNG", "USO", "XLE", "WEAT", "DBA", "CORZ", "WULF"}),
        "sectors": frozenset({"energy", "agriculture", "weather", "gas", "oil"}),
    },
    "transportation": {
        "tickers": frozenset({"UPS", "FDX", "UNP", "CSX", "NSC", "UBER", "DAL", "UAL", "JETS"}),
        "sectors": frozenset({"transport", "transportation", "rail", "airline", "freight"}),
    },
    "logistics": {
        "tickers": frozenset({"UPS", "FDX", "ZIM", "MATX", "XRT", "UNP", "CSX"}),
        "sectors": frozenset({"logistics", "shipping", "freight", "supply chain"}),
    },
    "patents": {
        "tickers": frozenset({"XBI", "IBB", "ARKK", "QQQ", "XLK", "ABCL", "MRNA"}),
        "sectors": frozenset({"biotech", "patent", "innovation", "technology", "pharma"}),
    },
    "sales-analytics": {
        "tickers": frozenset({"XRT", "WMT", "TGT", "COST", "HD", "LOW", "AMZN", "MCD"}),
        "sectors": frozenset({"retail", "consumer", "sales", "staples", "discretionary"}),
    },
}


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def agent_cluster(agent_id: str) -> str:
    return AGENT_CLUSTERS.get(str(agent_id or ""), "other")


def agent_in_domain(agent_id: str, symbol: str, *, sector_hint: str = "") -> bool:
    aid = str(agent_id or "")
    sym = str(symbol or "").strip().upper()
    if aid in GENERALIST_AGENTS or not sym:
        return True
    domain = AGENT_DOMAINS.get(aid)
    if not domain:
        return True
    if sym in domain.get("tickers", frozenset()):
        return True
    hint = str(sector_hint or "").lower()
    if hint:
        for keyword in domain.get("sectors", frozenset()):
            if keyword in hint:
                return True
    return False


def current_regime() -> dict[str, Any]:
    portfolio = _load_json(OUTPUT / "portfolio.json")
    if portfolio and isinstance(portfolio.get("regime"), dict):
        return portfolio["regime"]
    markets = _load_json(OUTPUT / "markets.json")
    if markets and isinstance(markets.get("regime"), dict):
        return markets["regime"]
    metrics = (markets or {}).get("metrics", {}) if markets else {}
    score = float(metrics.get("risk_on_score", 0.5) or 0.5)
    posture = "risk-on" if score >= 0.58 else "risk-off" if score <= 0.42 else "neutral"
    return {"label": posture.title(), "posture": posture, "risk_on_score": score}


def is_event_day(*, recorded_at: str | None = None) -> bool:
    """True when high-impact macro/earnings-style events are active today."""
    when = recorded_at or datetime.now(timezone.utc).isoformat()
    day = when[:10]
    events = _load_json(OUTPUT / "world_events.json")
    if not events:
        return False
    for row in events.get("active_events", []) or events.get("events", []) or []:
        if not isinstance(row, dict):
            continue
        impact = str(row.get("impact", row.get("severity", ""))).lower()
        if impact not in {"high", "critical", "major"}:
            continue
        event_day = str(row.get("date", row.get("event_date", "")))[:10]
        if event_day == day:
            return True
        if row.get("active") is True:
            return True
    return False


def affordable_max_share_price() -> float | None:
    portfolio = _load_json(OUTPUT / "portfolio.json")
    if portfolio:
        small = (portfolio.get("meta") or {}).get("small_account", {})
        if isinstance(small, dict) and small.get("max_share_price"):
            try:
                return float(small["max_share_price"])
            except (TypeError, ValueError):
                pass
    try:
        raw = _load_json(Path(__file__).resolve().parent / "etrade_config.json")
        if raw:
            strat = raw.get("strategy", {})
            threshold = float(strat.get("small_account_threshold_usd", 500))
            notional = float((portfolio or {}).get("meta", {}).get("notional_usd", 0) or 0)
            if notional and notional < threshold:
                investable = notional * 0.95
                max_holdings = int(strat.get("small_account_max_holdings", 6))
                slot = investable / max(max_holdings, 1)
                return max(float(strat.get("min_trade_usd", 5)), slot * 0.98)
    except Exception:
        pass
    return None


def score_symbol_allowed(symbol: str, price: float | None = None) -> bool:
    """For small accounts, limit accuracy scoring to affordable tradeable tickers."""
    cap = affordable_max_share_price()
    if cap is None:
        return True
    if price is None or price <= 0:
        return True
    return float(price) <= cap * 1.05


def calibration_factor(agent_id: str) -> float:
    """Scale confidence from Brier calibration (1.0 = well calibrated)."""
    from prediction_accuracy import get_agent_accuracy

    entry = get_agent_accuracy(agent_id)
    if not entry:
        return 1.0
    brier = entry.get("brier_score")
    if brier is None:
        return 1.0
    # Lower Brier is better; 0.25 random -> 1.0, 0.10 excellent -> 1.15
    return max(0.75, min(1.15, 1.0 + (0.25 - float(brier)) * 0.6))


def fusion_weight(
    agent_id: str,
    *,
    horizon: str = "24h",
    symbol: str = "",
    sector_hint: str = "",
    regime_posture: str | None = None,
) -> float:
    """Combined walk-forward fusion weight for an agent contribution."""
    from prediction_accuracy import MIN_SAMPLES_FOR_WEIGHT, get_agent_accuracy

    aid = str(agent_id or "")
    if not aid:
        return 0.0

    if not agent_in_domain(aid, symbol, sector_hint=sector_hint):
        return OUT_OF_DOMAIN_FACTOR

    entry = get_agent_accuracy(aid)
    base = 1.0
    if entry:
        total = int(entry.get("total_scored") or entry.get("total") or 0)
        combined = entry.get("combined_accuracy_pct")
        if total >= MIN_SAMPLES_FLOOR and combined is not None:
            if float(combined) < ACCURACY_EXCLUDE_PCT:
                return 0.0
            if float(combined) < ACCURACY_FLOOR_PCT:
                base = ACCURACY_FLOOR_WEIGHT
            else:
                base = float(entry.get("weight_multiplier") or 1.0)
        elif total >= MIN_SAMPLES_FOR_WEIGHT:
            base = float(entry.get("weight_multiplier") or 1.0)

        by_horizon = entry.get("by_horizon") or {}
        hb = by_horizon.get(horizon) if isinstance(by_horizon, dict) else None
        if isinstance(hb, dict) and int(hb.get("total", 0)) >= MIN_SAMPLES_HORIZON:
            hacc = float(hb.get("accuracy_pct") or 50.0)
            base *= 0.55 + hacc / 200.0

        posture = regime_posture or current_regime().get("posture", "neutral")
        by_regime = entry.get("by_regime") or {}
        rb = by_regime.get(posture) if isinstance(by_regime, dict) else None
        if isinstance(rb, dict) and int(rb.get("total", 0)) >= MIN_SAMPLES_REGIME:
            racc = float(rb.get("accuracy_pct") or 50.0)
            base *= 0.55 + racc / 200.0

    base *= calibration_factor(aid)
    return max(0.0, min(1.5, base))


def apply_cluster_caps(scores: dict[str, dict[str, Any]]) -> None:
    """Cap correlated agent clusters so one theme cannot dominate a ticker."""
    for row in scores.values():
        clusters: dict[str, float] = dict(row.get("by_cluster") or {})
        if not clusters:
            continue
        total_abs = sum(abs(v) for v in clusters.values())
        if total_abs <= 0:
            continue
        cap = total_abs * CLUSTER_WEIGHT_CAP
        adjusted: dict[str, float] = {}
        for cluster, value in clusters.items():
            if abs(value) > cap:
                adjusted[cluster] = cap if value > 0 else -cap
            else:
                adjusted[cluster] = value
        row["by_cluster"] = adjusted
        row["score"] = sum(adjusted.values())


def export_walk_forward_weights() -> dict[str, Any]:
    """Persist latest fusion weights for inspection and downstream use."""
    from agents.platform_catalog import active_agent_sources

    regime = current_regime()
    posture = str(regime.get("posture", "neutral"))
    agents: dict[str, Any] = {}
    for src in active_agent_sources(check_remote=False):
        aid = src["id"]
        agents[aid] = {
            "cluster": agent_cluster(aid),
            "weight_24h": round(fusion_weight(aid, horizon="24h", regime_posture=posture), 3),
            "weight_1wk": round(fusion_weight(aid, horizon="1wk", regime_posture=posture), 3),
            "weight_1mo": round(fusion_weight(aid, horizon="1mo", regime_posture=posture), 3),
            "regime": posture,
        }
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "regime": regime,
        "agents": agents,
        "accuracy_floor_pct": ACCURACY_FLOOR_PCT,
        "accuracy_exclude_pct": ACCURACY_EXCLUDE_PCT,
    }
    _write_json(FUSION_WEIGHTS_FILE, payload)
    return payload


def estimate_return_from_bias(direction: str, *, confidence: float = 0.5) -> float:
    sign = 1.0 if direction == "up" else -1.0 if direction == "down" else 0.0
    return round(sign * max(0.35, abs(confidence - 0.35) * 4.0), 2)