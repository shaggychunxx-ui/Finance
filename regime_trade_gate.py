#!/usr/bin/env python3
"""Regime / disagreement / event gates — when to refuse new risk.

Used by market predictor (abstain all) and trading paths (block new entries).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app_paths import OUTPUT, ROOT

DEFAULT_GATE = {
    "enabled": True,
    "max_minority_weight": 0.42,
    "min_agreement_ratio": 0.58,
    "block_on_event_day": True,
    "block_extreme_risk_off": True,
    "risk_off_score_max": 0.28,
    "block_extreme_risk_on_chase": False,
    "risk_on_score_min_for_chase_block": 0.92,
}


def _load_settings() -> dict[str, Any]:
    settings = dict(DEFAULT_GATE)
    path = ROOT / "etrade_config.json"
    if not path.exists():
        return settings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        strat = raw.get("strategy") if isinstance(raw.get("strategy"), dict) else {}
        block = strat.get("regime_trade_gate") if isinstance(strat.get("regime_trade_gate"), dict) else {}
        settings.update({k: block[k] for k in settings if k in block})
    except (OSError, json.JSONDecodeError):
        pass
    return settings


def evaluate_regime_trade_gate(
    *,
    symbols: list[str] | None = None,
    votes: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return whether new risk should be blocked globally or per-symbol."""
    gate = _load_settings()
    if not gate.get("enabled", True):
        return {
            "block_new_entries": False,
            "reasons": [],
            "contested_symbols": [],
            "event_day": False,
            "regime": {},
        }

    reasons: list[str] = []
    regime: dict[str, Any] = {}
    event_day = False
    try:
        from agent_fusion import current_regime, is_event_day

        regime = current_regime() or {}
        event_day = bool(is_event_day())
    except Exception:
        pass

    if gate.get("block_on_event_day") and event_day:
        reasons.append("high_impact_event_day")

    score = float(regime.get("risk_on_score") or 0.5)
    posture = str(regime.get("posture") or "neutral")
    if gate.get("block_extreme_risk_off") and (
        posture == "risk-off" and score <= float(gate.get("risk_off_score_max", 0.28))
    ):
        reasons.append(f"extreme_risk_off score={score:.2f}")

    if gate.get("block_extreme_risk_on_chase") and score >= float(
        gate.get("risk_on_score_min_for_chase_block", 0.92)
    ):
        reasons.append(f"extreme_risk_on_chase score={score:.2f}")

    contested: list[dict[str, Any]] = []
    if votes is None:
        try:
            from agent_disagreement import collect_agent_bias_votes, top_contested_symbols

            votes = collect_agent_bias_votes()
            contested = top_contested_symbols(votes, limit=20)
        except Exception:
            votes = {}
            contested = []
    else:
        try:
            from agent_disagreement import top_contested_symbols

            contested = top_contested_symbols(votes, limit=20)
        except Exception:
            contested = []

    max_minority = float(gate.get("max_minority_weight", 0.42))
    hard_contested = [c for c in contested if float(c.get("disagreement") or 0) >= max_minority]
    if hard_contested and len(hard_contested) >= 5:
        reasons.append(f"broad_cluster_disagreement n={len(hard_contested)}")

    # Global block only for event / extreme regime / broad war; per-symbol still listed
    global_block = any(
        r.startswith("high_impact") or r.startswith("extreme_") or r.startswith("broad_cluster")
        for r in reasons
    )

    block_symbols = {str(c.get("symbol") or "").upper() for c in hard_contested}
    if symbols:
        block_symbols &= {str(s).upper() for s in symbols}

    result = {
        "block_new_entries": global_block,
        "reasons": reasons,
        "contested_symbols": contested[:12],
        "block_symbols": sorted(block_symbols),
        "event_day": event_day,
        "regime": {
            "posture": posture,
            "risk_on_score": score,
            "label": regime.get("label"),
        },
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        path = OUTPUT / "regime_trade_gate.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except OSError:
        pass
    return result


def symbol_blocked_for_new_entry(symbol: str, gate: dict[str, Any] | None = None) -> bool:
    g = gate or evaluate_regime_trade_gate()
    if g.get("block_new_entries"):
        return True
    sym = str(symbol or "").upper()
    return sym in set(g.get("block_symbols") or [])
