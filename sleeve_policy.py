#!/usr/bin/env python3
"""Shared-account sleeve policy for Long Trader + Short Trader.

Capital: one pool (total account equity / buying power). Both sleeves size
against the same account; soft max_deploy_pct caps prevent either side from
claiming the whole book, but cash is not ring-fenced into exclusive buckets.

Positions: strict isolation.
  - Long sleeve only opens/closes LONG positions (BUY / SELL of longs).
  - Short sleeve only opens/closes SHORT positions (SELL_SHORT / BUY_TO_COVER).
  - Neither may open a symbol the other already holds on the opposite side.
  - Long never trims/covers shorts; short never sells longs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Literal

from app_paths import OUTPUT, ROOT

Sleeve = Literal["long", "short"]

SLEEVE_STATE_FILE = OUTPUT / "sleeve_policy_state.json"
SHORT_DAY_STATE = OUTPUT / "short" / "short_day_state.json"
LONG_DAY_STATE = OUTPUT / "day_trade_state.json"
LONG_PLAN = OUTPUT / "strategy_plan.json"
SHORT_PLAN = OUTPUT / "short" / "short_strategy_plan.json"

DEFAULT_POLICY = {
    "enabled": True,
    # One capital pool — both sleeves use total account value / buying power.
    "shared_capital": True,
    # Soft ceilings as % of total equity (not exclusive reservations).
    "long_max_deploy_pct": 75.0,
    "short_max_deploy_pct": 35.0,
    # Hard capital cap for the buy (long) app: "pct" | "usd" | "off".
    # pct  → use long_max_deploy_pct of free equity
    # usd  → hard dollar ceiling (long_max_capital_usd), e.g. $5,000 of a $20k account
    # off  → no long soft ceiling (only cash buffer / buying power)
    "long_capital_cap_mode": "pct",
    "long_max_capital_usd": 0.0,
    "shared_cash_buffer_pct": 5.0,
    # Never open long if short is open (and vice versa) on the same symbol.
    "forbid_opposite_side": True,
    # Block new entries that would flip through an existing opposite position.
    "forbid_same_symbol_both_sleeves": True,
    # Dynamically tilt capital + assign symbols for joint profit.
    "coordinate_for_profit": True,
}


def load_sleeve_policy(config_path: Path | None = None) -> dict[str, Any]:
    settings = dict(DEFAULT_POLICY)
    paths = []
    if config_path is not None:
        paths.append(Path(config_path))
    paths.extend([ROOT / "etrade_config.json", ROOT / "short_etrade_config.json"])
    for path in paths:
        if not path.exists():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        user = raw.get("sleeve_policy")
        if isinstance(user, dict):
            settings.update({k: user[k] for k in user})
            break  # first found wins; both configs should stay in sync
    return settings


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def split_positions(positions: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return (long_map, short_map) keyed by symbol. Quantities are abs for shorts."""
    longs: dict[str, dict[str, Any]] = {}
    shorts: dict[str, dict[str, Any]] = {}
    for pos in positions or []:
        if not isinstance(pos, dict):
            continue
        sym = str(pos.get("symbol") or "").upper()
        if not sym:
            continue
        ptype = str(pos.get("position_type") or "LONG").upper()
        qty = float(pos.get("quantity") or 0)
        is_short = ptype == "SHORT" or qty < 0
        abs_qty = abs(qty)
        if abs_qty <= 0:
            continue
        row = dict(pos)
        row["symbol"] = sym
        row["quantity"] = int(abs_qty) if abs_qty == int(abs_qty) else abs_qty
        row["market_value"] = abs(float(pos.get("market_value") or 0))
        row["position_type"] = "SHORT" if is_short else "LONG"
        bucket = shorts if is_short else longs
        if sym in bucket:
            bucket[sym]["quantity"] = float(bucket[sym].get("quantity") or 0) + float(row["quantity"])
            bucket[sym]["market_value"] = float(bucket[sym].get("market_value") or 0) + float(row["market_value"])
        else:
            bucket[sym] = row
    return longs, shorts


def long_position_map(positions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    longs, _ = split_positions(positions)
    return longs


def short_position_map(positions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    _, shorts = split_positions(positions)
    return shorts


def _symbols_from_day_state(path: Path) -> set[str]:
    data = _load_json(path)
    out: set[str] = set()
    for raw in data.get("positions") or []:
        if isinstance(raw, dict) and raw.get("symbol"):
            out.add(str(raw["symbol"]).upper())
    return out


def _symbols_from_plan_targets(path: Path) -> set[str]:
    data = _load_json(path)
    out: set[str] = set()
    for h in data.get("target_holdings") or data.get("holdings") or []:
        if isinstance(h, dict) and h.get("symbol"):
            out.add(str(h["symbol"]).upper())
    for p in data.get("current_positions") or []:
        if isinstance(p, dict) and p.get("symbol"):
            out.add(str(p["symbol"]).upper())
    return out


def sleeve_claimed_symbols(sleeve: Sleeve) -> set[str]:
    """Symbols this sleeve already manages (day book + last plan)."""
    if sleeve == "long":
        return _symbols_from_day_state(LONG_DAY_STATE) | _symbols_from_plan_targets(LONG_PLAN)
    return _symbols_from_day_state(SHORT_DAY_STATE) | _symbols_from_plan_targets(SHORT_PLAN)


def blocked_symbols_for_new_entry(
    sleeve: Sleeve,
    positions: list[dict[str, Any]],
    *,
    policy: dict[str, Any] | None = None,
) -> set[str]:
    """Symbols the sleeve must not open (opposite side, other book, or profit coordinator)."""
    policy = policy or load_sleeve_policy()
    if not policy.get("enabled", True):
        return set()
    longs, shorts = split_positions(positions)
    blocked: set[str] = set()
    if policy.get("forbid_opposite_side", True):
        if sleeve == "long":
            blocked |= set(shorts)
        else:
            blocked |= set(longs)
    if policy.get("forbid_same_symbol_both_sleeves", True):
        other: Sleeve = "short" if sleeve == "long" else "long"
        blocked |= sleeve_claimed_symbols(other)
    # Profit coordination: only the assigned sleeve may open a fresh idea
    if policy.get("coordinate_for_profit", True):
        try:
            from sleeve_coordinator import load_coordination

            coord = load_coordination()
            if coord.get("enabled"):
                assignment = coord.get("symbol_assignment") or {}
                for sym, side in assignment.items():
                    if side and side != sleeve:
                        blocked.add(str(sym).upper())
        except Exception:
            pass
    return blocked


def _normalize_cap_mode(raw: Any) -> str:
    mode = str(raw or "pct").strip().lower()
    if mode in {"usd", "dollar", "dollars", "fixed", "amount", "$"}:
        return "usd"
    if mode in {"off", "none", "disabled", "false", "0"}:
        return "off"
    return "pct"


def shared_capital_budget(
    total_account_value: float,
    *,
    sleeve: Sleeve,
    policy: dict[str, Any] | None = None,
    balance: dict[str, Any] | None = None,
) -> dict[str, float | str | bool]:
    """Compute deployable notional from the shared capital pool.

    Cash is shared. Each sleeve gets a soft ceiling as a fraction of equity
    (optionally tilted by sleeve_coordinator for joint profit); available
    buying power is the shared BP pool (not reserved exclusively).

    Long sleeve also supports a hard capital cap:
      long_capital_cap_mode = "pct" | "usd" | "off"
      long_max_capital_usd  = absolute $ ceiling when mode is "usd"
      long_max_deploy_pct   = % of free equity when mode is "pct"
    """
    policy = policy or load_sleeve_policy()
    total = max(0.0, float(total_account_value or 0))
    buffer = float(policy.get("shared_cash_buffer_pct", 5.0)) / 100.0
    free_equity = total * max(0.0, 1.0 - buffer)

    long_pct = float(policy.get("long_max_deploy_pct", 75.0))
    short_pct = float(policy.get("short_max_deploy_pct", 35.0))
    long_mode = _normalize_cap_mode(policy.get("long_capital_cap_mode", "pct"))
    long_max_usd = max(0.0, float(policy.get("long_max_capital_usd") or 0))

    # Coordinator tilts % ceilings only when long is in percent mode.
    if policy.get("coordinate_for_profit", True) and long_mode == "pct":
        try:
            from sleeve_coordinator import coordinate_sleeves, effective_deploy_pct

            # Refresh coordination so both apps see the same joint plan
            coordinate_sleeves(total_account_value=total if total > 0 else None)
            long_pct = effective_deploy_pct("long", policy)
            short_pct = effective_deploy_pct("short", policy)
        except Exception:
            pass
    elif policy.get("coordinate_for_profit", True):
        # Still tilt short % even when long is USD-capped
        try:
            from sleeve_coordinator import coordinate_sleeves, effective_deploy_pct

            coordinate_sleeves(total_account_value=total if total > 0 else None)
            short_pct = effective_deploy_pct("short", policy)
        except Exception:
            pass

    if long_mode == "usd" and long_max_usd > 0:
        long_cap = long_max_usd
    elif long_mode == "off":
        long_cap = free_equity  # no soft long ceiling beyond free equity
    else:
        long_cap = free_equity * max(0.0, long_pct) / 100.0

    short_cap = free_equity * max(0.0, short_pct) / 100.0
    ceiling = long_cap if sleeve == "long" else short_cap

    bp = 0.0
    if balance:
        bp = float(
            balance.get("margin_buying_power")
            or balance.get("cash_buying_power")
            or balance.get("cash_available_for_investment")
            or balance.get("net_cash")
            or 0
        )
    # Shared capital: use min of sleeve ceiling and available BP when known
    if bp > 0 and policy.get("shared_capital", True):
        deployable = min(ceiling, bp) if ceiling > 0 else bp
    else:
        deployable = ceiling

    return {
        "total_account_value": round(total, 2),
        "shared_free_equity": round(free_equity, 2),
        "sleeve_ceiling_usd": round(max(0.0, ceiling), 2),
        "shared_buying_power": round(bp, 2),
        "deployable_usd": round(max(0.0, deployable), 2),
        "long_max_deploy_pct": round(long_pct, 2),
        "short_max_deploy_pct": round(short_pct, 2),
        "long_capital_cap_mode": long_mode,
        "long_max_capital_usd": round(long_max_usd, 2),
        "shared_cash_buffer_pct": float(policy.get("shared_cash_buffer_pct", 5.0)),
        "coordinate_for_profit": bool(policy.get("coordinate_for_profit", True)),
    }


def filter_orders_for_sleeve(
    orders: list[Any],
    *,
    sleeve: Sleeve,
    positions: list[dict[str, Any]],
    policy: dict[str, Any] | None = None,
) -> list[Any]:
    """Drop orders that would violate sleeve isolation.

    Long allowed actions: BUY, SELL (only reducing longs)
    Short allowed actions: SELL_SHORT, BUY_TO_COVER (only covering shorts)
    """
    policy = policy or load_sleeve_policy()
    if not policy.get("enabled", True):
        return list(orders)

    longs, shorts = split_positions(positions)
    blocked_new = blocked_symbols_for_new_entry(sleeve, positions, policy=policy)
    kept: list[Any] = []

    for order in orders:
        action = str(getattr(order, "action", None) or (order.get("action") if isinstance(order, dict) else "")).upper()
        sym = str(getattr(order, "symbol", None) or (order.get("symbol") if isinstance(order, dict) else "")).upper()
        if not sym or not action:
            continue

        if sleeve == "long":
            if action not in {"BUY", "SELL"}:
                _mark_blocked(order, "sleeve: long may only BUY/SELL")
                continue
            if action == "SELL":
                if sym not in longs:
                    _mark_blocked(order, "sleeve: will not SELL — not a long position (short book isolated)")
                    continue
                # Cap sell qty to long shares only
                long_qty = int(float(longs[sym].get("quantity") or 0))
                qty = int(getattr(order, "quantity", None) or (order.get("quantity") if isinstance(order, dict) else 0) or 0)
                if long_qty <= 0:
                    _mark_blocked(order, "sleeve: no long qty to sell")
                    continue
                if qty > long_qty:
                    if hasattr(order, "quantity"):
                        order.quantity = long_qty
                    elif isinstance(order, dict):
                        order["quantity"] = long_qty
            if action == "BUY" and sym in blocked_new:
                _mark_blocked(order, "sleeve: symbol blocked (short open or short sleeve claim)")
                continue

        else:  # short
            if action not in {"SELL_SHORT", "BUY_TO_COVER"}:
                _mark_blocked(order, "sleeve: short may only SELL_SHORT/BUY_TO_COVER")
                continue
            if action == "BUY_TO_COVER":
                if sym not in shorts:
                    _mark_blocked(order, "sleeve: will not BUY_TO_COVER — not a short position (long book isolated)")
                    continue
                short_qty = int(float(shorts[sym].get("quantity") or 0))
                qty = int(getattr(order, "quantity", None) or (order.get("quantity") if isinstance(order, dict) else 0) or 0)
                if short_qty <= 0:
                    _mark_blocked(order, "sleeve: no short qty to cover")
                    continue
                if qty > short_qty:
                    if hasattr(order, "quantity"):
                        order.quantity = short_qty
                    elif isinstance(order, dict):
                        order["quantity"] = short_qty
            if action == "SELL_SHORT" and sym in blocked_new:
                _mark_blocked(order, "sleeve: symbol blocked (long open or long sleeve claim)")
                continue

        kept.append(order)
    return kept


def _mark_blocked(order: Any, message: str) -> None:
    if hasattr(order, "status"):
        order.status = "blocked"
        order.message = message
    elif isinstance(order, dict):
        order["status"] = "blocked"
        order["message"] = message


def apply_sleeve_to_plan(
    plan: Any,
    *,
    sleeve: Sleeve,
    positions: list[dict[str, Any]],
    policy: dict[str, Any] | None = None,
) -> Any:
    """Filter plan.orders in place and stamp meta with sleeve policy."""
    policy = policy or load_sleeve_policy()
    if not getattr(plan, "orders", None):
        return plan
    before = len(plan.orders)
    plan.orders = filter_orders_for_sleeve(
        plan.orders,
        sleeve=sleeve,
        positions=positions,
        policy=policy,
    )
    meta = dict(getattr(plan, "meta", None) or {})
    budget = shared_capital_budget(
        float(getattr(plan, "total_account_value", 0) or 0),
        sleeve=sleeve,
        policy=policy,
    )
    meta["sleeve"] = sleeve
    meta["sleeve_policy"] = {
        "enabled": bool(policy.get("enabled", True)),
        "shared_capital": bool(policy.get("shared_capital", True)),
        "forbid_opposite_side": bool(policy.get("forbid_opposite_side", True)),
        "orders_kept": len(plan.orders),
        "orders_before_filter": before,
        **budget,
    }
    plan.meta = meta
    return plan


def save_sleeve_snapshot(
    *,
    positions: list[dict[str, Any]],
    total_account_value: float,
) -> Path:
    longs, shorts = split_positions(positions)
    payload = {
        "shared_capital": True,
        "total_account_value": total_account_value,
        "long_symbols": sorted(longs),
        "short_symbols": sorted(shorts),
        "long_claimed": sorted(sleeve_claimed_symbols("long")),
        "short_claimed": sorted(sleeve_claimed_symbols("short")),
        "policy": load_sleeve_policy(),
    }
    SLEEVE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SLEEVE_STATE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return SLEEVE_STATE_FILE


def ensure_config_sleeve_block(path: Path) -> None:
    """Write default sleeve_policy into config if missing."""
    if not path.exists():
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(raw, dict):
        return
    if "sleeve_policy" in raw and isinstance(raw["sleeve_policy"], dict):
        # Ensure shared_capital stays true unless user explicitly set it
        sp = raw["sleeve_policy"]
        sp.setdefault("shared_capital", True)
        sp.setdefault("enabled", True)
        sp.setdefault("forbid_opposite_side", True)
        sp.setdefault("forbid_same_symbol_both_sleeves", True)
        sp.setdefault("coordinate_for_profit", True)
        sp.setdefault("long_capital_cap_mode", DEFAULT_POLICY["long_capital_cap_mode"])
        sp.setdefault("long_max_capital_usd", DEFAULT_POLICY["long_max_capital_usd"])
        sp.setdefault("long_max_deploy_pct", DEFAULT_POLICY["long_max_deploy_pct"])
        raw["sleeve_policy"] = sp
    else:
        raw["sleeve_policy"] = dict(DEFAULT_POLICY)
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
