#!/usr/bin/env python3
"""Dollar-cost averaging sleeve — calendar BUYs isolated from signal rebalance.

Pipeline place:
  1) Agent ``dca-strategy`` (research lane) publishes knowledge + next lots.
  2) This engine builds a BUY-only ``StrategyPlan`` when a period is due.
  3) ``etrade_worker`` runs it after long rebalance and before day trading.
  4) Filled quantities are protected from strategy SELL/trim.
  5) Due-period cash is reserved in sleeve_policy so other sleeves do not spend it.

Live tickets stay off until ``dca_strategy.enabled`` is true.

When enabled, a 0-100 **use score** (cash slack, dip, VIX, regime, breadth)
decides skip / half / full / lean-in. Leftover cash below 1 share rolls.
"""

from __future__ import annotations

import json
from datetime import datetime, time as dt_time, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app_paths import OUTPUT, ROOT
from strategy_engine import StrategyPlan, TradeOrder, _quote_price

ET_TZ = ZoneInfo("America/New_York")
CONFIG_PATH = ROOT / "etrade_config.json"
STATE_FILE = OUTPUT / "dca_state.json"
PLAN_FILE = OUTPUT / "dca_plan.json"
SCORE_FILE = OUTPUT / "dca_use_score.json"

DEFAULT_UNIVERSE: list[dict[str, Any]] = [
    {"symbol": "VTI", "weight_pct": 70.0, "name": "US total market"},
    {"symbol": "VXUS", "weight_pct": 20.0, "name": "International ex-US"},
    {"symbol": "BND", "weight_pct": 10.0, "name": "US aggregate bonds"},
]

DEFAULT_DCA: dict[str, Any] = {
    "enabled": False,
    "amount_usd": 100.0,
    "cadence": "weekly",
    "weekday": "Friday",
    "month_day": 1,
    "execute_after_et": "10:30",
    "min_trade_usd": 50.0,
    "order_type": "MARKET",
    "protect_lots": True,
    "vix_overlay": "off",
    "vix_high": 30.0,
    "skip_if_cash_below_usd": 200.0,
    "use_score": True,
    "min_score_full": 60.0,
    "min_score_half": 40.0,
    "min_score_lean": 85.0,
    "lean_multiplier": 1.5,
    "universe": list(DEFAULT_UNIVERSE),
}

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
}


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


def load_dca_settings(config_path: Path | None = None) -> dict[str, Any]:
    settings = dict(DEFAULT_DCA)
    settings["universe"] = [dict(row) for row in DEFAULT_UNIVERSE]
    path = Path(config_path) if config_path else CONFIG_PATH
    if not path.exists():
        return settings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return settings
    user = raw.get("dca_strategy")
    if not isinstance(user, dict):
        return settings
    for key, default in DEFAULT_DCA.items():
        if key == "universe":
            continue
        if key in user:
            settings[key] = user[key]
    universe = user.get("universe")
    if isinstance(universe, list) and universe:
        cleaned: list[dict[str, Any]] = []
        for row in universe:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").upper().strip()
            if not sym:
                continue
            cleaned.append(
                {
                    "symbol": sym,
                    "weight_pct": float(row.get("weight_pct") or 0),
                    "name": str(row.get("name") or sym),
                }
            )
        if cleaned:
            settings["universe"] = cleaned
    settings["enabled"] = bool(settings.get("enabled"))
    settings["cadence"] = str(settings.get("cadence") or "weekly").strip().lower()
    settings["weekday"] = str(settings.get("weekday") or "Friday")
    settings["protect_lots"] = bool(settings.get("protect_lots", True))
    settings["vix_overlay"] = str(settings.get("vix_overlay") or "off").strip().lower()
    try:
        settings["amount_usd"] = max(0.0, float(settings.get("amount_usd") or 0))
    except (TypeError, ValueError):
        settings["amount_usd"] = 0.0
    try:
        settings["month_day"] = max(1, min(28, int(settings.get("month_day") or 1)))
    except (TypeError, ValueError):
        settings["month_day"] = 1
    try:
        settings["min_trade_usd"] = max(0.0, float(settings.get("min_trade_usd") or 50))
    except (TypeError, ValueError):
        settings["min_trade_usd"] = 50.0
    try:
        settings["skip_if_cash_below_usd"] = max(
            0.0, float(settings.get("skip_if_cash_below_usd") or 0)
        )
    except (TypeError, ValueError):
        settings["skip_if_cash_below_usd"] = 0.0
    try:
        settings["vix_high"] = float(settings.get("vix_high") or 30.0)
    except (TypeError, ValueError):
        settings["vix_high"] = 30.0
    settings["use_score"] = bool(settings.get("use_score", True))
    for key, default in (
        ("min_score_full", 60.0),
        ("min_score_half", 40.0),
        ("min_score_lean", 85.0),
        ("lean_multiplier", 1.5),
    ):
        try:
            settings[key] = float(settings.get(key) if settings.get(key) is not None else default)
        except (TypeError, ValueError):
            settings[key] = default
    return settings


def public_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = dict(settings or load_dca_settings())
    return {
        "enabled": bool(raw.get("enabled")),
        "amount_usd": float(raw.get("amount_usd") or 0),
        "cadence": raw.get("cadence"),
        "weekday": raw.get("weekday"),
        "month_day": raw.get("month_day"),
        "execute_after_et": raw.get("execute_after_et"),
        "min_trade_usd": raw.get("min_trade_usd"),
        "protect_lots": bool(raw.get("protect_lots", True)),
        "vix_overlay": raw.get("vix_overlay"),
        "vix_high": raw.get("vix_high"),
        "skip_if_cash_below_usd": raw.get("skip_if_cash_below_usd"),
        "use_score": bool(raw.get("use_score", True)),
        "min_score_full": raw.get("min_score_full"),
        "min_score_half": raw.get("min_score_half"),
        "min_score_lean": raw.get("min_score_lean"),
        "lean_multiplier": raw.get("lean_multiplier"),
        "universe": list(raw.get("universe") or []),
    }


def _now_et(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(ET_TZ)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc).astimezone(ET_TZ)
    return now.astimezone(ET_TZ)


def _parse_hhmm(value: str) -> dt_time:
    text = str(value or "10:30").strip()
    try:
        parts = text.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        return dt_time(max(0, min(23, hour)), max(0, min(59, minute)))
    except (TypeError, ValueError, IndexError):
        return dt_time(10, 30)


def period_key(settings: dict[str, Any] | None = None, *, now: datetime | None = None) -> str:
    settings = settings or load_dca_settings()
    et = _now_et(now)
    cadence = str(settings.get("cadence") or "weekly")
    if cadence == "monthly":
        return et.strftime("%Y-%m")
    iso = et.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def is_period_due(
    settings: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> bool:
    settings = settings or load_dca_settings()
    et = _now_et(now)
    if et.weekday() >= 5:
        return False
    after = _parse_hhmm(str(settings.get("execute_after_et") or "10:30"))
    if et.timetz().replace(tzinfo=None) < after:
        return False
    cadence = str(settings.get("cadence") or "weekly")
    if cadence == "monthly":
        target = int(settings.get("month_day") or 1)
        return et.day >= target
    wanted = WEEKDAYS.get(str(settings.get("weekday") or "friday").strip().lower(), 4)
    return et.weekday() >= wanted


def load_dca_state() -> dict[str, Any]:
    data = _load_json(STATE_FILE)
    data.setdefault("lots", [])
    data.setdefault("filled_periods", [])
    data.setdefault("protected", {})
    try:
        data["leftover_usd"] = max(0.0, float(data.get("leftover_usd") or 0))
    except (TypeError, ValueError):
        data["leftover_usd"] = 0.0
    return data


def save_dca_state(state: dict[str, Any]) -> None:
    _write_json(STATE_FILE, state)


def already_filled(key: str | None = None, state: dict[str, Any] | None = None) -> bool:
    state = state or load_dca_state()
    period = key or period_key()
    filled = {str(x) for x in (state.get("filled_periods") or [])}
    return period in filled


def protected_quantities(state: dict[str, Any] | None = None) -> dict[str, int]:
    settings = load_dca_settings()
    if not settings.get("protect_lots", True):
        return {}
    state = state or load_dca_state()
    out: dict[str, int] = {}
    stored = state.get("protected")
    if isinstance(stored, dict):
        for sym, qty in stored.items():
            try:
                n = int(qty)
            except (TypeError, ValueError):
                continue
            if n > 0:
                out[str(sym).upper()] = n
    if out:
        return out
    for lot in state.get("lots") or []:
        if not isinstance(lot, dict):
            continue
        sym = str(lot.get("symbol") or "").upper()
        try:
            qty = int(lot.get("qty") or lot.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0
        if sym and qty > 0:
            out[sym] = out.get(sym, 0) + qty
    return out


def leftover_usd(state: dict[str, Any] | None = None) -> float:
    state = state or load_dca_state()
    try:
        return max(0.0, float(state.get("leftover_usd") or 0))
    except (TypeError, ValueError):
        return 0.0


def reserved_cash_usd(
    settings: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> float:
    settings = settings or load_dca_settings()
    if not settings.get("enabled"):
        return 0.0
    if already_filled(period_key(settings, now=now)):
        return 0.0
    if not is_period_due(settings, now=now):
        return 0.0
    decision = score_dca_use(settings)
    if str(decision.get("action") or "") == "skip":
        return 0.0
    try:
        mult = float(decision.get("multiplier") or 1.0)
    except (TypeError, ValueError):
        mult = 1.0
    base = max(0.0, float(settings.get("amount_usd") or 0)) * max(0.0, mult)
    return round(base + leftover_usd(), 2)


def _normalize_weights(universe: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [dict(row) for row in universe or []]
    total = sum(max(0.0, float(row.get("weight_pct") or 0)) for row in rows)
    if total <= 0:
        n = max(len(rows), 1)
        for row in rows:
            row["weight_pct"] = 100.0 / n
        return rows
    for row in rows:
        row["weight_pct"] = 100.0 * max(0.0, float(row.get("weight_pct") or 0)) / total
    return rows


def _vix_level() -> float | None:
    markets = _load_json(OUTPUT / "markets.json")
    for key in ("vix", "VIX", "^VIX"):
        block = markets.get(key)
        if isinstance(block, dict):
            for field in ("last", "price", "close", "value"):
                try:
                    val = float(block.get(field))
                except (TypeError, ValueError):
                    continue
                if val > 0:
                    return val
    meta = markets.get("metrics") if isinstance(markets.get("metrics"), dict) else {}
    try:
        val = float(meta.get("vix") or 0)
        return val if val > 0 else None
    except (TypeError, ValueError):
        return None


def overlay_amount(settings: dict[str, Any]) -> tuple[float, str]:
    amount = max(0.0, float(settings.get("amount_usd") or 0))
    mode = str(settings.get("vix_overlay") or "off")
    if mode not in {"skip_high", "lean_in"}:
        return amount, "off"
    vix = _vix_level()
    high = float(settings.get("vix_high") or 30.0)
    if vix is None:
        return amount, f"{mode}:vix_unknown"
    if vix >= high and mode == "skip_high":
        return 0.0, f"skip_high:vix={vix:.1f}"
    if vix >= high and mode == "lean_in":
        return round(amount * 1.5, 2), f"lean_in:vix={vix:.1f}"
    return amount, f"{mode}:vix={vix:.1f}"


def _index_day_change() -> float | None:
    markets = _load_json(OUTPUT / "markets.json")
    indices = markets.get("indices")
    if not isinstance(indices, list):
        return None
    prefer = ("SPY", "^GSPC", "VTI", "QQQ", "^DJI")
    by_sym: dict[str, float] = {}
    for row in indices:
        if not isinstance(row, dict):
            continue
        try:
            chg = float(row.get("day_chg_pct"))
        except (TypeError, ValueError):
            continue
        by_sym[str(row.get("symbol") or "").upper()] = chg
    for key in prefer:
        if key in by_sym:
            return by_sym[key]
    if by_sym:
        return sum(by_sym.values()) / len(by_sym)
    return None


def _breadth_level() -> float | None:
    markets = _load_json(OUTPUT / "markets.json")
    metrics = markets.get("metrics") if isinstance(markets.get("metrics"), dict) else {}
    try:
        val = float(metrics.get("breadth_score"))
        return val
    except (TypeError, ValueError):
        return None


def _risk_on_level() -> tuple[float | None, str]:
    try:
        from agent_fusion import current_regime

        regime = current_regime() or {}
        score = float(regime.get("risk_on_score"))
        posture = str(regime.get("posture") or "neutral")
        return score, posture
    except Exception:
        pass
    markets = _load_json(OUTPUT / "markets.json")
    metrics = markets.get("metrics") if isinstance(markets.get("metrics"), dict) else {}
    try:
        score = float(metrics.get("risk_on_score"))
    except (TypeError, ValueError):
        score = None
    posture = "neutral"
    if score is not None:
        if score >= 0.58:
            posture = "risk-on"
        elif score <= 0.42:
            posture = "risk-off"
    return score, posture


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def score_dca_use(
    settings: dict[str, Any] | None = None,
    *,
    cash: float | None = None,
    vix: float | None = None,
    spy_day_chg_pct: float | None = None,
    risk_on_score: float | None = None,
    breadth_score: float | None = None,
    posture: str | None = None,
) -> dict[str, Any]:
    """0-100 use score. Pipeline maps it to skip / half / full / lean-in.

    Factors (weights sum to 100):
      cash_slack 25 | cheapness 25 | vix 20 | regime 20 | breadth 10
    DCA still wants to buy on a schedule; the score sizes or defers, it does
    not try to time a single-name entry.
    """
    settings = settings or load_dca_settings()
    amount = max(0.0, float(settings.get("amount_usd") or 0))
    floor = max(0.0, float(settings.get("skip_if_cash_below_usd") or 0))
    parts: dict[str, float] = {}
    reasons: list[str] = []

    if cash is None:
        parts["cash_slack"] = 12.0
        reasons.append("cash unknown, mid slack")
    elif cash < floor:
        parts["cash_slack"] = 0.0
        reasons.append(f"cash ${cash:.0f} below floor ${floor:.0f}")
    else:
        coverage = cash / max(amount, 1.0)
        parts["cash_slack"] = round(_clip(8.0 + 5.0 * coverage, 0.0, 25.0), 2)
        reasons.append(f"cash ${cash:.0f} covers {coverage:.1f}x envelope")

    if spy_day_chg_pct is None:
        spy_day_chg_pct = _index_day_change()
    if spy_day_chg_pct is None:
        parts["cheapness"] = 12.0
        reasons.append("index change unknown")
    else:
        # Dip = more points (classic DCA). Melt-up still some points so cash invests.
        if spy_day_chg_pct <= -2.0:
            parts["cheapness"] = 25.0
        elif spy_day_chg_pct <= -1.0:
            parts["cheapness"] = 20.0
        elif spy_day_chg_pct < 0:
            parts["cheapness"] = 16.0
        elif spy_day_chg_pct < 1.0:
            parts["cheapness"] = 12.0
        else:
            parts["cheapness"] = 8.0
        reasons.append(f"index day {spy_day_chg_pct:+.2f}%")

    if vix is None:
        vix = _vix_level()
    if vix is None:
        parts["vix"] = 10.0
        reasons.append("vix unknown")
    else:
        if vix < 12:
            parts["vix"] = 6.0
        elif vix < 18:
            parts["vix"] = 12.0
        elif vix < 25:
            parts["vix"] = 16.0
        elif vix < 35:
            parts["vix"] = 20.0
        else:
            parts["vix"] = 14.0
        reasons.append(f"vix={vix:.1f}")

    if risk_on_score is None or posture is None:
        live_score, live_posture = _risk_on_level()
        if risk_on_score is None:
            risk_on_score = live_score
        if posture is None:
            posture = live_posture
    posture = str(posture or "neutral").lower()
    if risk_on_score is None:
        parts["regime"] = 12.0
        reasons.append("regime unknown")
    else:
        # Risk-off favors buying the core cheaper. Risk-on still invests (DCA).
        if posture == "risk-off" or risk_on_score <= 0.42:
            parts["regime"] = 18.0 if risk_on_score is not None and risk_on_score > 0.22 else 20.0
        elif posture == "risk-on" or risk_on_score >= 0.58:
            parts["regime"] = 10.0
        else:
            parts["regime"] = 14.0
        reasons.append(f"regime {posture} risk_on={float(risk_on_score):.2f}")

    if breadth_score is None:
        breadth_score = _breadth_level()
    if breadth_score is None:
        parts["breadth"] = 5.0
    else:
        # Low breadth = more names down = better DCA entry.
        if breadth_score <= 0.40:
            parts["breadth"] = 10.0
        elif breadth_score <= 0.55:
            parts["breadth"] = 7.0
        else:
            parts["breadth"] = 4.0
        reasons.append(f"breadth={breadth_score:.2f}")

    score = round(sum(float(v) for v in parts.values()), 2)
    min_half = float(settings.get("min_score_half") or 40.0)
    min_full = float(settings.get("min_score_full") or 60.0)
    min_lean = float(settings.get("min_score_lean") or 85.0)
    lean_mult = float(settings.get("lean_multiplier") or 1.5)
    if not settings.get("use_score", True):
        action, multiplier = "full", 1.0
        reasons.append("use_score disabled, calendar full size")
    elif score < min_half:
        action, multiplier = "skip", 0.0
    elif score < min_full:
        action, multiplier = "half", 0.5
    elif score < min_lean:
        action, multiplier = "full", 1.0
    else:
        action, multiplier = "lean", lean_mult

    result = {
        "score": score,
        "action": action,
        "multiplier": multiplier,
        "parts": {k: round(float(v), 2) for k, v in parts.items()},
        "reasons": reasons,
        "thresholds": {
            "min_score_half": min_half,
            "min_score_full": min_full,
            "min_score_lean": min_lean,
            "lean_multiplier": lean_mult,
        },
        "inputs": {
            "cash": cash,
            "vix": vix,
            "spy_day_chg_pct": spy_day_chg_pct,
            "risk_on_score": risk_on_score,
            "breadth_score": breadth_score,
            "posture": posture,
        },
        "note": f"use_score={score:.0f} action={action} x{multiplier}",
    }
    try:
        _write_json(SCORE_FILE, result)
    except OSError:
        pass
    return result


def planned_lots(
    settings: dict[str, Any] | None = None,
    *,
    price_fn: Callable[[str], tuple[float, str]] | None = None,
    prices: dict[str, float] | None = None,
    amount_usd: float | None = None,
    overlay_note: str | None = None,
) -> list[dict[str, Any]]:
    settings = settings or load_dca_settings()
    if amount_usd is None:
        amount, computed_note = overlay_amount(settings)
    else:
        amount, computed_note = max(0.0, float(amount_usd)), "override"
    overlay_note = overlay_note or computed_note
    universe = _normalize_weights(list(settings.get("universe") or DEFAULT_UNIVERSE))
    min_trade = float(settings.get("min_trade_usd") or 0)
    lots: list[dict[str, Any]] = []
    for row in universe:
        sym = str(row.get("symbol") or "").upper()
        if not sym:
            continue
        weight = float(row.get("weight_pct") or 0)
        slice_usd = amount * weight / 100.0
        source = "config"
        if price_fn is not None:
            try:
                px, source = price_fn(sym)
            except Exception:
                px, source = 0.0, "error"
        elif prices and prices.get(sym):
            px, source = float(prices[sym]), "passed"
        else:
            px, source = 0.0, "missing"
        px = float(px or 0)
        shares = int(slice_usd // px) if px > 0 else 0
        spent = shares * px
        leftover = max(0.0, slice_usd - spent)
        if spent < min_trade:
            leftover = slice_usd
            shares = 0
            spent = 0.0
        lots.append(
            {
                "symbol": sym,
                "name": str(row.get("name") or sym),
                "weight_pct": round(weight, 4),
                "amount_usd": round(slice_usd, 2),
                "price": round(px, 4) if px else 0.0,
                "shares": shares,
                "spent_usd": round(spent, 2),
                "leftover_usd": round(leftover, 2),
                "data_source": source,
                "overlay": overlay_note,
            }
        )
    return lots


def record_fills(
    orders: list[TradeOrder] | list[dict[str, Any]],
    *,
    period: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    state = load_dca_state()
    key = period or period_key()
    ts = _now_et(now).strftime("%Y-%m-%dT%H:%M:%S%z")
    lots = list(state.get("lots") or [])
    protected = dict(protected_quantities(state))
    added = False
    for order in orders or []:
        if hasattr(order, "to_dict"):
            row = order.to_dict()
        elif isinstance(order, dict):
            row = order
        else:
            continue
        status = str(row.get("status") or "").lower()
        if status not in {"placed", "dry_run", "filled"}:
            continue
        if str(row.get("action") or "").upper() != "BUY":
            continue
        try:
            qty = int(row.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0
        sym = str(row.get("symbol") or "").upper()
        if not sym or qty <= 0:
            continue
        lots.append(
            {
                "symbol": sym,
                "qty": qty,
                "period": key,
                "filled_at": ts,
                "price": row.get("estimated_price"),
                "status": status,
            }
        )
        protected[sym] = int(protected.get(sym, 0) or 0) + qty
        added = True
    if added:
        filled = [str(x) for x in (state.get("filled_periods") or [])]
        if key not in filled:
            filled.append(key)
        state["filled_periods"] = filled[-48:]
        state["lots"] = lots[-500:]
        state["protected"] = protected
        state["updated"] = ts
        save_dca_state(state)
    return state


def settle_dca_period(
    plan: StrategyPlan | None = None,
    *,
    leftover: float | None = None,
    mark_filled: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Persist unused envelope and optionally consume the calendar period."""
    state = load_dca_state()
    lots_meta = []
    if plan is not None:
        lots_meta = list((plan.meta or {}).get("lots") or [])
    if leftover is None:
        leftover = 0.0
        for row in lots_meta:
            if not isinstance(row, dict):
                continue
            try:
                leftover += float(row.get("leftover_usd") or 0)
            except (TypeError, ValueError):
                continue
    try:
        leftover_f = max(0.0, float(leftover or 0))
    except (TypeError, ValueError):
        leftover_f = 0.0
    state["leftover_usd"] = round(leftover_f, 2)
    if mark_filled:
        key = ""
        if plan is not None:
            key = str((plan.meta or {}).get("period_key") or "")
        key = key or period_key()
        filled = [str(x) for x in (state.get("filled_periods") or [])]
        if key not in filled:
            filled.append(key)
        state["filled_periods"] = filled[-48:]
    state["updated"] = _now_et(now).strftime("%Y-%m-%dT%H:%M:%S%z")
    save_dca_state(state)
    return state


def build_dca_plan(
    client: Any,
    account_id_key: str,
    account_name: str = "",
    *,
    settings: dict[str, Any] | None = None,
    now: datetime | None = None,
    force: bool = False,
) -> StrategyPlan:
    settings = settings or load_dca_settings()
    et = _now_et(now)
    key = period_key(settings, now=et)
    meta: dict[str, Any] = {
        "sleeve": "dca",
        "period_key": key,
        "enabled": bool(settings.get("enabled")),
        "cadence": settings.get("cadence"),
    }
    orders: list[TradeOrder] = []
    skip_reason = ""
    total_value = 0.0
    if not settings.get("enabled") and not force:
        skip_reason = "dca_strategy.enabled is false"
    elif already_filled(key) and not force:
        skip_reason = f"period {key} already filled"
    elif not is_period_due(settings, now=et) and not force:
        skip_reason = f"period {key} not due yet"
    else:
        prices: dict[str, float] = {}

        def _px(symbol: str) -> tuple[float, str]:
            if client is not None:
                try:
                    live = float(_quote_price(client, symbol) or 0)
                except Exception:
                    live = 0.0
                if live > 0:
                    prices[symbol] = live
                    return live, "etrade"
            return 0.0, "missing"

        blocked: set[str] = set()
        try:
            from sleeve_policy import blocked_symbols_for_new_entry

            positions = client.get_portfolio(account_id_key) if client is not None else []
            blocked = blocked_symbols_for_new_entry("long", positions)
        except Exception:
            blocked = set()
        cash = None
        try:
            if client is not None:
                balance = client.get_balance(account_id_key)
                total_value = float(balance.get("total_account_value") or 0)
                cash = float(
                    balance.get("cash_available_for_investment")
                    or balance.get("cash_buying_power")
                    or balance.get("net_cash")
                    or 0
                )
        except Exception:
            cash = None
        floor = float(settings.get("skip_if_cash_below_usd") or 0)
        decision = score_dca_use(settings, cash=cash)
        meta["use_score"] = decision
        bank = leftover_usd()
        meta["leftover_bank_usd"] = bank
        meta["cash"] = cash
        meta["skip_if_cash_below_usd"] = floor
        if cash is not None and cash < floor:
            skip_reason = f"cash ${cash:.2f} below floor ${floor:.2f}"
        elif str(decision.get("action") or "") == "skip":
            skip_reason = (
                f"use_score {decision.get('score')} below "
                f"{decision.get('thresholds', {}).get('min_score_half')} (skip)"
            )
        else:
            try:
                mult = float(decision.get("multiplier") or 1.0)
            except (TypeError, ValueError):
                mult = 1.0
            budget = max(0.0, float(settings.get("amount_usd") or 0)) * max(0.0, mult) + bank
            meta["budget_usd"] = round(budget, 2)
            lots = planned_lots(
                settings,
                price_fn=_px,
                amount_usd=budget,
                overlay_note=str(decision.get("note") or ""),
            )
            meta["lots"] = lots
            for lot in lots:
                sym = lot["symbol"]
                shares = int(lot.get("shares") or 0)
                if shares <= 0:
                    continue
                if sym in blocked:
                    continue
                px = float(lot.get("price") or 0)
                orders.append(
                    TradeOrder(
                        symbol=sym,
                        action="BUY",
                        quantity=shares,
                        target_weight_pct=float(lot.get("weight_pct") or 0),
                        current_weight_pct=0.0,
                        target_value_usd=float(lot.get("spent_usd") or 0),
                        current_value_usd=0.0,
                        estimated_price=px,
                        rationale=(
                            f"DCA {key} {settings.get('cadence')} "
                            f"{decision.get('action')} score={decision.get('score')}"
                        ),
                        price_type=str(settings.get("order_type") or "MARKET"),
                    )
                )

    if skip_reason:
        meta["skip_reason"] = skip_reason

    plan = StrategyPlan(
        generated_at=et.strftime("%Y-%m-%dT%H:%M:%SZ"),
        account_id_key=account_id_key,
        account_name=account_name,
        sandbox=bool(getattr(getattr(client, "config", None), "sandbox", False)),
        total_account_value=float(total_value or 0),
        investable_usd=float((meta.get("budget_usd") if isinstance(meta, dict) else None) or settings.get("amount_usd") or 0),
        cash_buffer_pct=0.0,
        regime={"sleeve": "dca", "period_key": key},
        target_holdings=list(settings.get("universe") or []),
        current_positions=[],
        orders=orders,
        meta=meta,
    )
    _write_json(PLAN_FILE, plan.to_dict())
    return plan
