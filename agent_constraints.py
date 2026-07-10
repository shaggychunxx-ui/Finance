"""Domain and horizon constraints — keep specialist agents in their lane."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app_paths import ROOT

DEFAULT_DOMAIN_CONSTRAINTS = {
    "enabled": True,
    "filter_out_of_domain_signals": True,
    "strict_domain_for_trading": True,
    "horizon_alignment": True,
    "non_preferred_horizon_factor": 0.35,
    "distant_horizon_factor": 0.12,
    "strict_horizon_for_specialists": False,
}

HORIZON_ORDER = ("24h", "1wk", "1mo", "1yr")
ADJACENT_HORIZONS: dict[str, frozenset[str]] = {
    "24h": frozenset({"1wk"}),
    "1wk": frozenset({"24h", "1mo"}),
    "1mo": frozenset({"1wk", "1yr"}),
    "1yr": frozenset({"1mo"}),
}


def load_domain_constraint_settings(config_path: Path | None = None) -> dict[str, Any]:
    settings = dict(DEFAULT_DOMAIN_CONSTRAINTS)
    path = config_path or (ROOT / "etrade_config.json")
    if not path.exists():
        return settings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        strategy = raw.get("strategy", {})
        if isinstance(strategy, dict):
            nested = strategy.get("domain_constraints", {})
            if isinstance(nested, dict):
                settings.update({k: nested[k] for k in settings if k in nested})
        top = raw.get("domain_constraints", {})
        if isinstance(top, dict):
            settings.update({k: top[k] for k in settings if k in top})
    except (json.JSONDecodeError, OSError):
        pass
    return settings


def normalize_agent_id(agent_id: str) -> str:
    return str(agent_id or "").replace("_", "-")


def is_domain_specialist(agent_id: str) -> bool:
    from agent_fusion import AGENT_DOMAINS, GENERALIST_AGENTS

    aid = normalize_agent_id(agent_id)
    return aid not in GENERALIST_AGENTS and aid in AGENT_DOMAINS


def agent_preferred_horizon(agent_id: str) -> str:
    """Learning profile horizon, then catalog default, then personality."""
    aid = normalize_agent_id(agent_id)
    try:
        from agent_learning import get_agent_learning

        learning = get_agent_learning(aid)
        if learning is not None and learning.preferred_horizon in HORIZON_ORDER:
            return learning.preferred_horizon
    except Exception:
        pass
    try:
        from agent_fusion import agent_default_horizon

        horizon = agent_default_horizon(aid)
        if horizon in HORIZON_ORDER:
            return horizon
    except Exception:
        pass
    return "24h"


def domain_allows_symbol(
    agent_id: str,
    symbol: str,
    *,
    sector_hint: str = "",
    settings: dict[str, Any] | None = None,
) -> bool:
    gate = settings or load_domain_constraint_settings()
    if not gate.get("enabled", True):
        return True
    if not gate.get("filter_out_of_domain_signals", True):
        return True

    from agent_fusion import AGENT_DOMAINS, GENERALIST_AGENTS, agent_in_domain

    aid = normalize_agent_id(agent_id)
    sym = str(symbol or "").strip().upper()
    if aid in GENERALIST_AGENTS:
        return agent_in_domain(aid, sym, sector_hint=sector_hint)

    domain = AGENT_DOMAINS.get(aid)
    if domain and sym:
        # Specialists with a mapped universe must name explicit tickers in-domain.
        return sym in domain.get("tickers", frozenset())

    return agent_in_domain(aid, sym, sector_hint=sector_hint)


def strict_domain_for_trading(settings: dict[str, Any] | None = None) -> bool:
    gate = settings or load_domain_constraint_settings()
    return bool(gate.get("enabled", True) and gate.get("strict_domain_for_trading", True))


def horizon_match_multiplier(
    agent_id: str,
    horizon: str,
    *,
    settings: dict[str, Any] | None = None,
) -> float:
    gate = settings or load_domain_constraint_settings()
    if not gate.get("enabled", True) or not gate.get("horizon_alignment", True):
        return 1.0

    aid = normalize_agent_id(agent_id)
    preferred = agent_preferred_horizon(aid)
    h = horizon if horizon in HORIZON_ORDER else "24h"
    if h == preferred:
        return 1.0

    near = float(gate.get("non_preferred_horizon_factor", DEFAULT_DOMAIN_CONSTRAINTS["non_preferred_horizon_factor"]))
    distant = float(gate.get("distant_horizon_factor", DEFAULT_DOMAIN_CONSTRAINTS["distant_horizon_factor"]))

    if is_domain_specialist(aid) and gate.get("strict_horizon_for_specialists", False):
        return 0.0

    if h in ADJACENT_HORIZONS.get(preferred, frozenset()):
        return near
    return distant


def _filter_tickers(
    tickers: list[Any],
    *,
    agent_id: str,
    sector_hint: str,
    settings: dict[str, Any],
    impact_scope: str = "",
) -> list[str]:
    if str(impact_scope or "") == "market":
        try:
            from agent_signal_logic import MARKET_IMPACT_TICKERS

            return [
                str(ticker or "").strip().upper()
                for ticker in tickers or []
                if str(ticker or "").strip().upper() in MARKET_IMPACT_TICKERS
            ]
        except Exception:
            pass

    kept: list[str] = []
    for ticker in tickers or []:
        sym = str(ticker or "").strip().upper()
        if not sym:
            continue
        if domain_allows_symbol(agent_id, sym, sector_hint=sector_hint, settings=settings):
            kept.append(sym)
    return kept


def _constrain_market_signals(
    signals: list[dict[str, Any]],
    *,
    agent_id: str,
    settings: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    aid = normalize_agent_id(agent_id)
    preferred = agent_preferred_horizon(aid)
    removed = 0
    out: list[dict[str, Any]] = []
    for sig in signals or []:
        if not isinstance(sig, dict):
            continue
        sector = str(sig.get("sector", ""))
        tickers = _filter_tickers(
            sig.get("tickers") or [],
            agent_id=aid,
            sector_hint=sector,
            settings=settings,
            impact_scope=str(sig.get("impact_scope") or ""),
        )
        removed += max(0, len(sig.get("tickers") or []) - len(tickers))
        if not tickers:
            removed += 1
            continue
        row = dict(sig)
        row["tickers"] = tickers
        row["preferred_horizon"] = preferred
        out.append(row)
    return out, removed


def _constrain_predictions(
    predictions: dict[str, Any],
    *,
    agent_id: str,
    settings: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    aid = normalize_agent_id(agent_id)
    preferred = agent_preferred_horizon(aid)
    removed = 0
    out: dict[str, Any] = {}
    strict_horizon = bool(
        settings.get("strict_horizon_for_specialists", False) and is_domain_specialist(aid)
    )

    for horizon, rows in (predictions or {}).items():
        if horizon not in HORIZON_ORDER:
            continue
        if strict_horizon and horizon != preferred:
            removed += len(rows or [])
            continue
        kept_rows: list[dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").upper()
            if sym and not domain_allows_symbol(aid, sym, settings=settings):
                removed += 1
                continue
            kept = dict(row)
            kept["preferred_horizon"] = preferred
            kept_rows.append(kept)
        if kept_rows:
            out[horizon] = kept_rows
    return out, removed


def apply_agent_constraints_to_result(
    data: dict[str, Any],
    agent_id: str,
    *,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Filter specialist signals to in-domain tickers and stamp preferred horizons."""
    if not isinstance(data, dict):
        return data

    gate = settings or load_domain_constraint_settings()
    if not gate.get("enabled", True):
        return data

    aid = normalize_agent_id(agent_id)
    preferred = agent_preferred_horizon(aid)
    removed_signals = 0
    removed_opps = 0
    removed_predictions = 0

    signals, removed_signals = _constrain_market_signals(
        list(data.get("market_signals") or []),
        agent_id=aid,
        settings=gate,
    )
    data["market_signals"] = signals

    opps_out: list[dict[str, Any]] = []
    for opp in data.get("trading_opportunities") or []:
        if not isinstance(opp, dict):
            continue
        sym = str(opp.get("symbol") or "").upper()
        if sym and not domain_allows_symbol(aid, sym, settings=gate):
            removed_opps += 1
            continue
        row = dict(opp)
        row["preferred_horizon"] = preferred
        opps_out.append(row)
    if "trading_opportunities" in data:
        data["trading_opportunities"] = opps_out

    preds = data.get("predictions")
    if isinstance(preds, dict):
        filtered_preds, removed_predictions = _constrain_predictions(preds, agent_id=aid, settings=gate)
        data["predictions"] = filtered_preds

    meta = data.setdefault("meta", {})
    if not isinstance(meta, dict):
        meta = {}
        data["meta"] = meta
    meta["preferred_horizon"] = preferred
    meta["domain_constraints"] = {
        "specialist": is_domain_specialist(aid),
        "removed_out_of_domain_signals": removed_signals,
        "removed_out_of_domain_opportunities": removed_opps,
        "removed_out_of_domain_predictions": removed_predictions,
    }
    return data