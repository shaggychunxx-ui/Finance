#!/usr/bin/env python3
"""Coordinate Long + Short sleeves on one account to maximize expected profit.

Uses shared capital (one pool) while keeping position isolation. Dynamically:
  - Tilts deploy ceilings toward the sleeve with better multi-horizon edge
  - Assigns each symbol to long OR short (never both) based on expected return
  - Surfaces a joint profit score for plans/workers

Does not place orders — plan builders read the coordination file.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app_paths import OUTPUT, ROOT

COORD_FILE = OUTPUT / "sleeve_coordination.json"
MARKET_PRED = OUTPUT / "market_predictions.json"
LONG_PORTFOLIO = OUTPUT / "portfolio.json"
SHORT_PORTFOLIO = OUTPUT / "short" / "short_portfolio.json"

# Bounds so neither sleeve is starved when the other looks slightly better
MIN_LONG_DEPLOY_PCT = 35.0
MAX_LONG_DEPLOY_PCT = 85.0
MIN_SHORT_DEPLOY_PCT = 10.0
MAX_SHORT_DEPLOY_PCT = 50.0
# Floor share of free equity each side keeps available for its book
MIN_SHARE = 0.18


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_coordination() -> dict[str, Any]:
    return _load_json(COORD_FILE)


def _horizon_weights() -> dict[str, float]:
    try:
        from profit_optimizer import load_horizon_weights
        from strategy_engine import load_strategy_settings

        return load_horizon_weights(load_strategy_settings())
    except Exception:
        return {"daily": 0.25, "weekly": 0.25, "monthly": 0.25, "yearly": 0.25}


def _pred_map() -> dict[str, dict[str, Any]]:
    """symbol -> {return_pct, confidence, horizons} from market_predictions."""
    data = _load_json(MARKET_PRED)
    preds = data.get("predictions") or {}
    horizon_map = {"24h": "daily", "1wk": "weekly", "1mo": "monthly", "1yr": "yearly"}
    weights = _horizon_weights()
    out: dict[str, dict[str, Any]] = {}

    for hz_key, rows in preds.items():
        if not isinstance(rows, list):
            continue
        w_key = horizon_map.get(str(hz_key), "")
        w = float(weights.get(w_key, 0.2))
        for row in rows:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").upper()
            if not sym:
                continue
            ret = float(row.get("predicted_return_pct") or 0)
            conf = float(row.get("confidence") or row.get("probability") or 0.5)
            entry = out.setdefault(
                sym,
                {"weighted_return": 0.0, "weight_sum": 0.0, "confidence": 0.0, "n": 0},
            )
            entry["weighted_return"] += ret * w * conf
            entry["weight_sum"] += w * conf
            entry["confidence"] = max(entry["confidence"], conf)
            entry["n"] += 1

    scored: dict[str, dict[str, Any]] = {}
    for sym, entry in out.items():
        ws = float(entry["weight_sum"]) or 1e-6
        expected = float(entry["weighted_return"]) / ws
        scored[sym] = {
            "expected_return_pct": round(expected, 4),
            "confidence": round(float(entry["confidence"]), 4),
            "samples": int(entry["n"]),
            # Positive edge for long; positive edge for short when expected is negative
            "long_edge": round(expected * float(entry["confidence"]), 4),
            "short_edge": round((-expected) * float(entry["confidence"]), 4),
        }
    return scored


def _portfolio_score_bias(path: Path, *, invert: bool = False) -> dict[str, float]:
    data = _load_json(path)
    scores: dict[str, float] = {}
    for h in data.get("holdings") or []:
        if not isinstance(h, dict) or not h.get("symbol"):
            continue
        sym = str(h["symbol"]).upper()
        sc = float(h.get("score") or h.get("bearish_strength") or 0)
        if invert:
            sc = float(h.get("bearish_strength") or -sc)
        scores[sym] = sc
    return scores


def _regime_tilt() -> dict[str, Any]:
    try:
        from portfolio_generator import _detect_regime

        regime = _detect_regime(OUTPUT)
    except Exception:
        regime = {"posture": "neutral", "risk_on_score": 0.5, "label": "unknown"}
    posture = str(regime.get("posture") or "neutral").lower()
    risk_on = float(regime.get("risk_on_score") or 0.5)
    # risk-on → favor long share; risk-off → favor short share
    if posture in {"risk-on", "risk_on"} or risk_on >= 0.58:
        long_share = 0.72
    elif posture in {"risk-off", "risk_off"} or risk_on <= 0.42:
        long_share = 0.45
    else:
        long_share = 0.60
    return {
        "regime": regime,
        "base_long_share": long_share,
        "base_short_share": round(1.0 - long_share, 4),
    }


def assign_symbols(pred: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Map each symbol to the sleeve with higher expected edge."""
    assignment: dict[str, str] = {}
    for sym, row in pred.items():
        long_e = float(row.get("long_edge") or 0)
        short_e = float(row.get("short_edge") or 0)
        # Require a minimum absolute edge to take a side
        if long_e <= 0 and short_e <= 0:
            continue
        if long_e >= short_e and long_e > 0.02:
            assignment[sym] = "long"
        elif short_e > long_e and short_e > 0.02:
            assignment[sym] = "short"
    return assignment


def compute_deploy_split(
    pred: dict[str, dict[str, Any]],
    assignment: dict[str, str],
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Return dynamic long/short max_deploy_pct using opportunity mass + regime."""
    from sleeve_policy import DEFAULT_POLICY, load_sleeve_policy

    policy = policy or load_sleeve_policy()
    tilt = _regime_tilt()
    long_mass = 0.0
    short_mass = 0.0
    for sym, side in assignment.items():
        row = pred.get(sym) or {}
        if side == "long":
            long_mass += max(0.0, float(row.get("long_edge") or 0))
        else:
            short_mass += max(0.0, float(row.get("short_edge") or 0))

    total = long_mass + short_mass
    if total <= 1e-9:
        long_share = float(tilt["base_long_share"])
    else:
        opp_long = long_mass / total
        # Blend opportunity with regime base
        long_share = 0.55 * opp_long + 0.45 * float(tilt["base_long_share"])

    long_share = max(MIN_SHARE, min(1.0 - MIN_SHARE, long_share))
    short_share = 1.0 - long_share

    # Scale into policy ceilings (soft max deploy % of equity)
    base_long = float(policy.get("long_max_deploy_pct", DEFAULT_POLICY["long_max_deploy_pct"]))
    base_short = float(policy.get("short_max_deploy_pct", DEFAULT_POLICY["short_max_deploy_pct"]))
    # When opportunity favors one side, expand toward max bound; shrink the other toward min
    long_pct = MIN_LONG_DEPLOY_PCT + (MAX_LONG_DEPLOY_PCT - MIN_LONG_DEPLOY_PCT) * long_share
    short_pct = MIN_SHORT_DEPLOY_PCT + (MAX_SHORT_DEPLOY_PCT - MIN_SHORT_DEPLOY_PCT) * short_share
    # Never exceed static policy ceilings if user set tighter ones
    long_pct = min(long_pct, max(base_long, MIN_LONG_DEPLOY_PCT))
    short_pct = min(short_pct, max(base_short, MIN_SHORT_DEPLOY_PCT))
    # If opportunity strongly short, allow short to use up to max of policy short and computed
    if short_mass > long_mass * 1.25:
        short_pct = min(MAX_SHORT_DEPLOY_PCT, max(short_pct, base_short))
        long_pct = max(MIN_LONG_DEPLOY_PCT, long_pct * 0.9)

    return {
        "long_max_deploy_pct": round(long_pct, 2),
        "short_max_deploy_pct": round(short_pct, 2),
        "long_share": round(long_share, 4),
        "short_share": round(short_share, 4),
        "long_opportunity_mass": round(long_mass, 4),
        "short_opportunity_mass": round(short_mass, 4),
        **tilt,
    }


def joint_expected_profit_score(
    pred: dict[str, dict[str, Any]],
    assignment: dict[str, str],
    *,
    notional: float,
    long_pct: float,
    short_pct: float,
) -> dict[str, Any]:
    """Rough joint expected profit USD if sleeves deploy at their ceilings into top ideas."""
    long_ideas = [(s, pred[s]) for s, side in assignment.items() if side == "long" and s in pred]
    short_ideas = [(s, pred[s]) for s, side in assignment.items() if side == "short" and s in pred]
    long_ideas.sort(key=lambda x: x[1].get("long_edge", 0), reverse=True)
    short_ideas.sort(key=lambda x: x[1].get("short_edge", 0), reverse=True)

    long_budget = notional * long_pct / 100.0
    short_budget = notional * short_pct / 100.0
    n_long = max(1, min(8, len(long_ideas)))
    n_short = max(1, min(6, len(short_ideas)))

    long_exp = 0.0
    for sym, row in long_ideas[:n_long]:
        slice_usd = long_budget / n_long
        long_exp += slice_usd * float(row.get("expected_return_pct") or 0) / 100.0

    short_exp = 0.0
    for sym, row in short_ideas[:n_short]:
        slice_usd = short_budget / n_short
        # Short profits when return is negative
        short_exp += slice_usd * (-float(row.get("expected_return_pct") or 0)) / 100.0

    return {
        "expected_profit_usd_long": round(long_exp, 2),
        "expected_profit_usd_short": round(short_exp, 2),
        "expected_profit_usd_joint": round(long_exp + short_exp, 2),
        "top_long": [s for s, _ in long_ideas[:5]],
        "top_short": [s for s, _ in short_ideas[:5]],
    }


def coordinate_sleeves(*, total_account_value: float | None = None) -> dict[str, Any]:
    """Build and persist coordination plan for both apps."""
    from sleeve_policy import load_sleeve_policy

    policy = load_sleeve_policy()
    if not policy.get("enabled", True) or not policy.get("coordinate_for_profit", True):
        payload = {
            "enabled": False,
            "reason": "sleeve coordination disabled",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_json(COORD_FILE, payload)
        return payload

    pred = _pred_map()
    # Blend portfolio scores into edges when predictions thin
    long_scores = _portfolio_score_bias(LONG_PORTFOLIO, invert=False)
    short_scores = _portfolio_score_bias(SHORT_PORTFOLIO, invert=True)
    for sym, sc in long_scores.items():
        row = pred.setdefault(
            sym,
            {"expected_return_pct": 0.0, "confidence": 0.5, "samples": 0, "long_edge": 0.0, "short_edge": 0.0},
        )
        row["long_edge"] = round(float(row.get("long_edge") or 0) + max(0.0, sc) * 0.35, 4)
    for sym, sc in short_scores.items():
        row = pred.setdefault(
            sym,
            {"expected_return_pct": 0.0, "confidence": 0.5, "samples": 0, "long_edge": 0.0, "short_edge": 0.0},
        )
        row["short_edge"] = round(float(row.get("short_edge") or 0) + max(0.0, sc) * 0.35, 4)

    assignment = assign_symbols(pred)
    split = compute_deploy_split(pred, assignment, policy=policy)
    notional = float(total_account_value or 0)
    if notional <= 0:
        # try last plan
        for path in (OUTPUT / "strategy_plan.json", OUTPUT / "short" / "short_strategy_plan.json"):
            d = _load_json(path)
            if d.get("total_account_value"):
                notional = float(d["total_account_value"])
                break
    if notional <= 0:
        notional = 100_000.0

    profit = joint_expected_profit_score(
        pred,
        assignment,
        notional=notional,
        long_pct=float(split["long_max_deploy_pct"]),
        short_pct=float(split["short_max_deploy_pct"]),
    )

    long_syms = sorted(s for s, side in assignment.items() if side == "long")
    short_syms = sorted(s for s, side in assignment.items() if side == "short")

    payload = {
        "enabled": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "objective": "maximize_joint_expected_profit",
        "shared_capital": True,
        "position_isolation": True,
        "notional_usd": round(notional, 2),
        "deploy": {
            "long_max_deploy_pct": split["long_max_deploy_pct"],
            "short_max_deploy_pct": split["short_max_deploy_pct"],
            "long_share": split["long_share"],
            "short_share": split["short_share"],
        },
        "opportunity": {
            "long_mass": split["long_opportunity_mass"],
            "short_mass": split["short_opportunity_mass"],
            "regime": split.get("regime"),
        },
        "expected_profit": profit,
        "symbol_assignment": assignment,
        "long_universe": long_syms,
        "short_universe": short_syms,
        "guidance": {
            "long": (
                f"Deploy up to {split['long_max_deploy_pct']}% of free equity into long ideas "
                f"(top: {', '.join(profit['top_long'][:4]) or 'n/a'})."
            ),
            "short": (
                f"Deploy up to {split['short_max_deploy_pct']}% of free equity into short ideas "
                f"(top: {', '.join(profit['top_short'][:4]) or 'n/a'})."
            ),
            "joint": (
                f"Joint expected profit ~${profit['expected_profit_usd_joint']:,.2f} "
                f"(long ${profit['expected_profit_usd_long']:,.2f} + short ${profit['expected_profit_usd_short']:,.2f})."
            ),
        },
    }
    _write_json(COORD_FILE, payload)
    return payload


def effective_deploy_pct(sleeve: str, policy: dict[str, Any] | None = None) -> float:
    """Deploy ceiling for sleeve after coordination (falls back to static policy)."""
    from sleeve_policy import DEFAULT_POLICY, load_sleeve_policy

    policy = policy or load_sleeve_policy()
    key = "long_max_deploy_pct" if sleeve == "long" else "short_max_deploy_pct"
    static = float(policy.get(key, DEFAULT_POLICY[key]))
    if not policy.get("coordinate_for_profit", True):
        return static
    coord = load_coordination()
    if not coord.get("enabled"):
        return static
    deploy = coord.get("deploy") or {}
    dyn = deploy.get(key)
    if dyn is None:
        return static
    return float(dyn)


def preferred_sleeve_for_symbol(symbol: str) -> str | None:
    """Return 'long', 'short', or None if unassigned."""
    sym = str(symbol or "").upper()
    if not sym:
        return None
    coord = load_coordination()
    if not coord.get("enabled"):
        return None
    assignment = coord.get("symbol_assignment") or {}
    side = assignment.get(sym)
    return str(side) if side in {"long", "short"} else None


def symbol_allowed_for_sleeve(symbol: str, sleeve: str) -> bool:
    """New entries: only the assigned sleeve may open a fresh idea (if coordinated)."""
    preferred = preferred_sleeve_for_symbol(symbol)
    if preferred is None:
        return True  # no signal → leave isolation rules only
    return preferred == sleeve
