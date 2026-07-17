"""Accuracy-driven agent fusion: domains, regimes, clusters, calibration, floors."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app_paths import OUTPUT

FUSION_WEIGHTS_FILE = OUTPUT / "history" / "fusion_weights.json"

ACCURACY_FLOOR_PCT = 42.0
ACCURACY_EXCLUDE_PCT = 38.0
TRADING_ACCURACY_FLOOR_PCT = 45.0
TRADING_ACCURACY_EXCLUDE_PCT = 40.0
ACCURACY_FLOOR_WEIGHT = 0.25
MIN_SAMPLES_FLOOR = 20
MIN_SAMPLES_HORIZON = 4
MIN_SAMPLES_REGIME = 4

AGENT_DEFAULT_HORIZON: dict[str, str] = {
    "markets": "24h",
    "finance": "24h",
    "financial-data": "24h",
    "datascience": "24h",
    "order-execution": "24h",
    "sales-analytics": "1wk",
    "geopolitics": "1wk",
    "events": "1wk",
    "patents": "1mo",
    "electricity": "1wk",
    "grid": "1wk",
    "meteorology": "1wk",
    "transportation": "1wk",
    "logistics": "1wk",
    "theoretical-probability": "1wk",
    "empirical-probability": "1wk",
    "combined-conditional": "1wk",
    "research-statistics": "1mo",
    "trading-economics": "1wk",
    "fed-policy": "1wk",
}
CLUSTER_WEIGHT_CAP = 0.45
OUT_OF_DOMAIN_FACTOR = 0.3
HISTORICAL_BLEND = 0.35

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
    "sec-filings": "intelligence",
    "migration": "intelligence",
    "census": "macro",
    "agriculture": "energy_grid",
    "trading-economics": "macro",
    "fed-policy": "macro",
    "sales-analytics": "consumer",
    "order-execution": "execution",
    "data-steward": "data_platform",
    "records-management": "data_platform",
    "market-predictor": "fusion",
    "history": "intelligence",
    "etrade": "market_data",
}

# Agents that emit execution/platform signals — not directional price forecasts.
DIRECTIONAL_SCORING_SKIP = frozenset({
    "etrade",
    "history",
    "market-predictor",
    "order-execution",
    "data-steward",
    "records-management",
})


def agent_uses_directional_accuracy(agent_id: str) -> bool:
    """True when live directional hit-rate scoring applies to this agent."""
    aid = str(agent_id or "").replace("_", "-")
    return aid not in DIRECTIONAL_SCORING_SKIP


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
    "agriculture": {
        "tickers": frozenset({"DBA", "WEAT", "CORN", "SOYB", "MOO", "DE", "ADM", "BG"}),
        "sectors": frozenset({"agriculture", "farming", "commodity", "crop", "grain"}),
    },
    "census": {
        "tickers": frozenset({"XRT", "ITB", "XHB", "HD", "LOW", "WMT", "TGT"}),
        "sectors": frozenset({"retail", "housing", "consumer", "construction", "census"}),
    },
    "sec-filings": {
        "tickers": frozenset({"SPY", "QQQ", "XLF", "XLK", "XLE"}),
        "sectors": frozenset({"sec", "filing", "regulatory", "corporate", "disclosure"}),
    },
    "migration": {
        "tickers": frozenset({"EWW", "EWZ", "INDA", "FXI", "EEM"}),
        "sectors": frozenset({"remittance", "migration", "emerging", "demographic"}),
    },
    "trading-economics": {
        "tickers": frozenset({"SPY", "TLT", "GLD", "UUP", "EEM"}),
        "sectors": frozenset({"macro", "rates", "inflation", "gdp", "economics"}),
    },
    "fed-policy": {
        "tickers": frozenset({"TLT", "IEF", "SHY", "XLF", "KRE", "IWM", "HYG", "STPP"}),
        "sectors": frozenset({"rates", "fed", "fomc", "sofr", "treasury", "swap", "duration", "credit"}),
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
    if not sym:
        return True
    try:
        from agent_signal_logic import MARKET_IMPACT_TICKERS

        if sym in MARKET_IMPACT_TICKERS:
            return True
    except Exception:
        pass
    if aid in GENERALIST_AGENTS:
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
    score = 0.5
    posture = "neutral"
    if markets:
        metrics = markets.get("metrics", {}) or {}
        score = float(metrics.get("risk_on_score", 0.5) or 0.5)
        assessment = markets.get("assessment") or {}
        regime_label = str(assessment.get("regime", "") or markets.get("trend_label", "")).lower()
        if any(token in regime_label for token in ("risk-on", "risk on", "bull", "expansion")):
            posture = "risk-on"
        elif any(token in regime_label for token in ("risk-off", "risk off", "bear", "contraction", "defensive")):
            posture = "risk-off"
        else:
            posture = "risk-on" if score >= 0.58 else "risk-off" if score <= 0.42 else "neutral"
    return {"label": posture.title(), "posture": posture, "risk_on_score": score}


def agent_default_horizon(agent_id: str) -> str:
    aid = str(agent_id or "")
    if aid in AGENT_DEFAULT_HORIZON:
        return AGENT_DEFAULT_HORIZON[aid]
    try:
        from agent_personality import personality_horizon_preference

        return personality_horizon_preference(aid)
    except Exception:
        return "24h"


def is_event_day(*, recorded_at: str | None = None) -> bool:
    """True when high-impact macro/earnings-style events are active today."""
    when = recorded_at or datetime.now(timezone.utc).isoformat()
    day = when[:10]

    def _scan_event_rows(rows: list[Any] | None) -> bool:
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            impact = str(row.get("impact", row.get("severity", row.get("risk_level", "")))).lower()
            if impact not in {"high", "critical", "major", "elevated"}:
                continue
            event_day = str(row.get("date", row.get("event_date", "")))[:10]
            if event_day == day:
                return True
            if row.get("active") is True:
                return True
        return False

    for filename in ("world_events.json", "geopolitics.json", "events.json"):
        data = _load_json(OUTPUT / filename)
        if not isinstance(data, dict):
            continue
        if _scan_event_rows(data.get("active_events")):
            return True
        if _scan_event_rows(data.get("events")):
            return True
        if _scan_event_rows(data.get("risk_events")):
            return True

    markets = _load_json(OUTPUT / "markets.json")
    if isinstance(markets, dict):
        metrics = markets.get("metrics", {}) or {}
        try:
            vix = float(metrics.get("vix_level", metrics.get("^VIX", 0)) or 0)
            if vix >= 28:
                return True
        except (TypeError, ValueError):
            pass
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
    """Limit accuracy scoring to liquid, tradeable tickers."""
    try:
        from symbol_universe import is_liquid_symbol

        if not is_liquid_symbol(symbol, price):
            return False
    except Exception:
        pass
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
    for_trading: bool = False,
) -> float:
    """Combined walk-forward fusion weight for an agent contribution."""
    from prediction_accuracy import MIN_SAMPLES_FOR_WEIGHT, get_agent_accuracy

    aid = str(agent_id or "")
    if not aid:
        return 0.0

    if not agent_in_domain(aid, symbol, sector_hint=sector_hint):
        if for_trading:
            try:
                from agent_constraints import strict_domain_for_trading

                if strict_domain_for_trading():
                    return 0.0
            except Exception:
                pass
        return OUT_OF_DOMAIN_FACTOR

    if for_trading:
        try:
            from trading_gate import agent_trading_eligibility

            if not agent_trading_eligibility(aid).get("eligible"):
                return 0.0
        except Exception:
            pass

    exclude_pct = TRADING_ACCURACY_EXCLUDE_PCT if for_trading else ACCURACY_EXCLUDE_PCT
    floor_pct = TRADING_ACCURACY_FLOOR_PCT if for_trading else ACCURACY_FLOOR_PCT

    entry = get_agent_accuracy(aid)
    base = 1.0
    if entry:
        total = int(entry.get("total_scored") or entry.get("total") or 0)
        live_scored = int(entry.get("live_scored") or 0)
        source = str(entry.get("accuracy_source") or "")
        sample_total = live_scored if source in {"live_scored", "live_benchmark_blend"} else total
        combined = entry.get("fusion_accuracy_pct") or entry.get("combined_accuracy_pct")
        if sample_total >= MIN_SAMPLES_FLOOR and combined is not None:
            if float(combined) < exclude_pct:
                return 0.0
            if float(combined) < floor_pct:
                base = ACCURACY_FLOOR_WEIGHT
            else:
                base = float(entry.get("weight_multiplier") or 1.0)
        elif sample_total >= MIN_SAMPLES_FOR_WEIGHT or (
            source == "walk_forward_benchmark"
            and total >= MIN_SAMPLES_FOR_WEIGHT
        ):
            base = float(entry.get("weight_multiplier") or 1.0)

        fusion_horizon = horizon
        if entry.get("prefer_preferred_horizon_for_fusion") and entry.get("preferred_horizon"):
            fusion_horizon = str(entry.get("preferred_horizon"))
        by_horizon = entry.get("by_horizon") or {}
        hb = by_horizon.get(fusion_horizon) if isinstance(by_horizon, dict) else None
        if isinstance(hb, dict) and int(hb.get("total", 0)) >= MIN_SAMPLES_HORIZON:
            hacc = float(hb.get("accuracy_pct") or 50.0)
            base *= 0.55 + hacc / 200.0

        posture = regime_posture or current_regime().get("posture", "neutral")
        by_regime_bucket = entry.get("by_regime_bucket") or {}
        try:
            from accuracy_measurement import load_accuracy_measurement_settings, regime_bucket

            min_regime = int(
                load_accuracy_measurement_settings().get("min_regime_bucket_samples", MIN_SAMPLES_REGIME)
            )
            bucket_key = regime_bucket(posture, event_day=is_event_day())
            rb = by_regime_bucket.get(bucket_key) if isinstance(by_regime_bucket, dict) else None
        except Exception:
            min_regime = MIN_SAMPLES_REGIME
            rb = None
        if not isinstance(rb, dict) or int(rb.get("total", 0)) < min_regime:
            by_regime = entry.get("by_regime") or {}
            rb = by_regime.get(posture) if isinstance(by_regime, dict) else None
            min_regime = MIN_SAMPLES_REGIME
        if isinstance(rb, dict) and int(rb.get("total", 0)) >= min_regime:
            racc = float(rb.get("accuracy_pct") or 50.0)
            base *= 0.55 + racc / 200.0

    base *= calibration_factor(aid)

    try:
        from historical_simulation import historical_weight_multiplier

        hist_mult = historical_weight_multiplier(aid, horizon=horizon)
        if hist_mult is not None:
            base = base * (1.0 - HISTORICAL_BLEND) + hist_mult * HISTORICAL_BLEND
    except Exception:
        pass

    try:
        from account_balance_penalty import agent_balance_penalty_multiplier

        base *= agent_balance_penalty_multiplier(aid)
    except Exception:
        pass

    try:
        from agent_personality import personality_fusion_factor

        base *= personality_fusion_factor(aid, regime_posture=regime_posture or current_regime().get("posture", "neutral"))
    except Exception:
        pass

    try:
        from agent_learning import learning_fusion_factor

        base *= learning_fusion_factor(aid)
    except Exception:
        pass

    if for_trading:
        try:
            from agent_constraints import horizon_match_multiplier

            base *= horizon_match_multiplier(aid, horizon)
        except Exception:
            pass

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

    balance_penalties: dict[str, Any] = {}
    try:
        from account_balance_penalty import rebuild_balance_penalties

        balance_penalties = rebuild_balance_penalties()
    except Exception:
        pass

    regime = current_regime()
    posture = str(regime.get("posture", "neutral"))
    agents: dict[str, Any] = {}
    for src in active_agent_sources(check_remote=False):
        aid = src["id"]
        bal_mult = 1.0
        bal_blame = 0.0
        bal_credit = 0.0
        bal_benchmark = 0.0
        bal_entry = (balance_penalties.get("agents") or {}).get(aid)
        if isinstance(bal_entry, dict):
            bal_mult = float(bal_entry.get("multiplier") or 1.0)
            bal_blame = float(bal_entry.get("blame_score") or 0.0)
            bal_credit = float(bal_entry.get("reward_score") or 0.0)
            bal_benchmark = float(bal_entry.get("benchmark_reward_score") or 0.0)
        personality_label = ""
        personality_fit = 1.0
        personality_tuned = False
        learning_label = ""
        learning_fit = 1.0
        try:
            from agent_personality import (
                get_agent_personality,
                personality_fusion_factor,
                personality_is_tuned,
            )

            personality_label = get_agent_personality(aid).label
            personality_fit = personality_fusion_factor(aid, regime_posture=posture)
            personality_tuned = personality_is_tuned(aid)
        except Exception:
            pass
        try:
            from agent_learning import learning_fusion_factor, learning_label as _learning_label

            learning_label = _learning_label(aid)
            learning_fit = learning_fusion_factor(aid)
        except Exception:
            pass
        accuracy_meta: dict[str, Any] = {}
        try:
            from prediction_accuracy import get_agent_accuracy

            acc_row = get_agent_accuracy(aid)
            if isinstance(acc_row, dict):
                accuracy_meta = {
                    "accuracy_source": acc_row.get("accuracy_source"),
                    "combined_accuracy_pct": acc_row.get("combined_accuracy_pct"),
                    "live_scored": acc_row.get("live_scored"),
                    "live_weight": acc_row.get("live_weight"),
                }
        except Exception:
            pass
        agents[aid] = {
            "cluster": agent_cluster(aid),
            "weight_24h": round(fusion_weight(aid, horizon="24h", regime_posture=posture), 3),
            "weight_1wk": round(fusion_weight(aid, horizon="1wk", regime_posture=posture), 3),
            "weight_1mo": round(fusion_weight(aid, horizon="1mo", regime_posture=posture), 3),
            "regime": posture,
            "balance_multiplier": round(bal_mult, 3),
            "balance_blame": round(bal_blame, 3),
            "balance_reward": round(bal_credit, 3),
            "daily_benchmark_reward": round(bal_benchmark, 3),
            "personality_label": personality_label,
            "personality_fit": round(personality_fit, 3),
            "personality_tuned": personality_tuned,
            "learning_label": learning_label,
            "learning_fit": round(learning_fit, 3),
            **accuracy_meta,
        }
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "regime": regime,
        "account_balance": balance_penalties.get("account"),
        "daily_growth_pct": balance_penalties.get("daily_growth_pct"),
        "benchmark_tiers_hit": balance_penalties.get("benchmark_tiers_hit", []),
        "daily_benchmarks_pct": balance_penalties.get("daily_benchmarks_pct", []),
        "agents": agents,
        "accuracy_floor_pct": ACCURACY_FLOOR_PCT,
        "accuracy_exclude_pct": ACCURACY_EXCLUDE_PCT,
        "trading_accuracy_floor_pct": TRADING_ACCURACY_FLOOR_PCT,
        "trading_accuracy_exclude_pct": TRADING_ACCURACY_EXCLUDE_PCT,
    }
    _write_json(FUSION_WEIGHTS_FILE, payload)
    return payload


def estimate_return_from_bias(direction: str, *, confidence: float = 0.5) -> float:
    sign = 1.0 if direction == "up" else -1.0 if direction == "down" else 0.0
    return round(sign * max(0.35, abs(confidence - 0.35) * 4.0), 2)