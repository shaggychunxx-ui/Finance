"""Account growth goals — daily / weekly / monthly targets + agent bonus hooks."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app_paths import OUTPUT, ROOT

CONFIG_PATH = ROOT / "etrade_config.json"

DEFAULT_ACCOUNT_GOALS: dict[str, Any] = {
    "enabled": True,
    "daily_gain_pct": 2.0,
    "weekly_gain_pct": 12.0,
    "monthly_gain_pct": 48.0,
    "agent_goal_bonus": True,
    # Award group-appropriate points for each full 1.0% total (and daily) P/L
    "pl_points_enabled": True,
    "notes": (
        "Primary goal: increase daily and total average P/L. "
        "Targets +2% day / +12% week / +48% month. "
        "Groups earn role-scaled points per full 1.0% total P/L (and half-weight per daily 1%)."
    ),
}

# Horizon windows used for progress measurement
HORIZON_HOURS = {
    "daily": 24.0,
    "weekly": 24.0 * 7.0,
    "monthly": 24.0 * 30.0,
}


def load_account_goals(config_path: Path | None = None) -> dict[str, Any]:
    """Load account goals from etrade_config.json (strategy.account_goals or top-level)."""
    goals = dict(DEFAULT_ACCOUNT_GOALS)
    path = config_path or CONFIG_PATH
    if not path.exists():
        return goals
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return goals
    user = raw.get("account_goals")
    if not isinstance(user, dict):
        strat = raw.get("strategy") if isinstance(raw.get("strategy"), dict) else {}
        user = strat.get("account_goals") if isinstance(strat.get("account_goals"), dict) else {}
    if isinstance(user, dict):
        for key in (
            "enabled",
            "daily_gain_pct",
            "weekly_gain_pct",
            "monthly_gain_pct",
            "agent_goal_bonus",
            "pl_points_enabled",
            "notes",
        ):
            if key in user:
                goals[key] = user[key]
    try:
        goals["daily_gain_pct"] = float(goals.get("daily_gain_pct") or 0.0)
        goals["weekly_gain_pct"] = float(goals.get("weekly_gain_pct") or 0.0)
        if goals.get("monthly_gain_pct") is not None:
            goals["monthly_gain_pct"] = float(goals["monthly_gain_pct"])
    except (TypeError, ValueError):
        pass
    goals["enabled"] = bool(goals.get("enabled", True))
    goals["agent_goal_bonus"] = bool(goals.get("agent_goal_bonus", True))
    goals["pl_points_enabled"] = bool(goals.get("pl_points_enabled", True))
    return goals


def _pct_change(latest: float, older: float) -> float | None:
    if older is None or older <= 0 or latest is None:
        return None
    return (float(latest) - float(older)) / float(older) * 100.0


def _point_value(point: dict[str, Any]) -> float | None:
    for key in ("total_account_value", "total", "value", "equity"):
        if key in point and point[key] is not None:
            try:
                return float(point[key])
            except (TypeError, ValueError):
                continue
    return None


def _point_ts(point: dict[str, Any]) -> datetime | None:
    raw = point.get("at") or point.get("ts") or point.get("timestamp")
    if not raw:
        return None
    try:
        text = str(raw).replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except Exception:
        return None


def measure_horizon_gain_pct(
    points: list[dict[str, Any]],
    *,
    hours: float,
    external_events: list[dict[str, Any]] | None = None,
    account_id_key: str = "",
    opening_balance: float | None = None,
) -> float | None:
    """Return trading P&L % over the horizon — deposits/withdrawals excluded.

    Formula (same spirit as account_profit):
        gain_$ = (latest − older) − net_external_flows_in_window
        gain_% = gain_$ / older × 100

    External flows are inferred from cash-matched balance jumps (and large
    no-cash jumps) via account_profit.detect_external_flow_events.
    """
    if not points:
        return None
    latest_val = _point_value(points[-1])
    if latest_val is None:
        return None
    latest_ts = _point_ts(points[-1]) or datetime.now(timezone.utc)
    if latest_ts.tzinfo is None:
        latest_ts = latest_ts.replace(tzinfo=timezone.utc)
    cutoff = latest_ts.timestamp() - float(hours) * 3600.0
    older_val: float | None = None
    older_ts: datetime | None = None
    for point in points:
        ts = _point_ts(point)
        val = _point_value(point)
        if val is None:
            continue
        if ts is None:
            older_val = val
            older_ts = None
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts.timestamp() <= cutoff:
            older_val = val
            older_ts = ts
    if older_val is None and len(points) >= 2:
        older_val = _point_value(points[0])
        older_ts = _point_ts(points[0])
        if older_ts is not None and older_ts.tzinfo is None:
            older_ts = older_ts.replace(tzinfo=timezone.utc)
    if older_val is None or older_val <= 0:
        return None

    # Net deposits (+) / withdrawals (−) strictly after older snapshot through latest
    flows_in_window = 0.0
    try:
        from account_profit import (
            detect_external_flow_events,
            external_flows_between,
        )

        events = external_events
        if events is None:
            events = detect_external_flow_events(
                points,
                account_id_key,
                opening_balance=opening_balance,
            )
        flows_in_window = external_flows_between(
            events or [],
            start_ts=older_ts,
            end_ts=latest_ts,
            include_start=False,
        )
    except Exception:
        flows_in_window = 0.0

    # Remove capital that was deposited (or add back withdrawals) from the delta
    trading_gain = float(latest_val) - float(older_val) - float(flows_in_window)
    return (trading_gain / float(older_val)) * 100.0


def _progress(actual: float | None, target: float) -> dict[str, Any]:
    if target <= 0:
        return {
            "target_pct": target,
            "actual_pct": actual,
            "remaining_pct": None,
            "progress_ratio": None,
            "status": "no_target",
        }
    if actual is None:
        return {
            "target_pct": target,
            "actual_pct": None,
            "remaining_pct": target,
            "progress_ratio": 0.0,
            "status": "unknown",
        }
    remaining = target - actual
    ratio = max(0.0, min(actual / target, 2.0))
    if actual >= target:
        status = "met"
    elif actual >= target * 0.5:
        status = "on_track"
    elif actual >= 0:
        status = "behind"
    else:
        status = "negative"
    return {
        "target_pct": round(target, 4),
        "actual_pct": round(actual, 4),
        "remaining_pct": round(remaining, 4),
        "progress_ratio": round(ratio, 4),
        "status": status,
    }


def goal_progress(config_path: Path | None = None) -> dict[str, Any]:
    """Goals + realized progress for dashboard / agent context / bonuses.

    Progress % excludes deposits and withdrawals (trading P&L only).
    """
    goals = load_account_goals(config_path)
    daily_target = float(goals.get("daily_gain_pct") or 0.0)
    weekly_target = float(goals.get("weekly_gain_pct") or 0.0)
    monthly_target = (
        float(goals.get("monthly_gain_pct") or 0.0)
        if goals.get("monthly_gain_pct") is not None
        else 0.0
    )

    points: list[dict[str, Any]] = []
    growth: dict[str, Any] = {}
    account_key = ""
    opening: float | None = None
    external_events: list[dict[str, Any]] = []
    try:
        from analysis_history import get_account_growth

        growth = get_account_growth() or {}
        points = list(growth.get("points") or [])
        if points and isinstance(points[-1], dict):
            account_key = str(points[-1].get("account_id_key") or "").strip()
    except Exception:
        growth = {}

    # Prefer profit_metrics (already deposit-aware) for events + opening + total P/L
    metrics: dict[str, Any] = {}
    try:
        from account_profit import detect_external_flow_events, profit_metrics_for_account

        metrics = profit_metrics_for_account(growth, account_key)
        opening = metrics.get("opening_balance")
        if opening is not None:
            opening = float(opening)
        external_events = list(metrics.get("external_flow_events") or [])
        if not external_events and points:
            external_events = detect_external_flow_events(
                points, account_key, opening_balance=opening
            )
    except Exception:
        try:
            from account_profit import detect_external_flow_events

            external_events = detect_external_flow_events(
                points, account_key, opening_balance=None
            )
        except Exception:
            external_events = []

    daily_actual = measure_horizon_gain_pct(
        points,
        hours=HORIZON_HOURS["daily"],
        external_events=external_events,
        account_id_key=account_key,
        opening_balance=opening,
    )
    weekly_actual = measure_horizon_gain_pct(
        points,
        hours=HORIZON_HOURS["weekly"],
        external_events=external_events,
        account_id_key=account_key,
        opening_balance=opening,
    )
    monthly_actual = measure_horizon_gain_pct(
        points,
        hours=HORIZON_HOURS["monthly"],
        external_events=external_events,
        account_id_key=account_key,
        opening_balance=opening,
    )

    # Daily fallback only from balance_penalties (already strips same-day external flows)
    if daily_actual is None:
        try:
            from account_balance_penalty import account_balance_state

            pen = account_balance_state() or {}
            if pen.get("daily_growth_pct") is not None:
                daily_actual = float(pen["daily_growth_pct"])
        except Exception:
            pass

    net_flows = None
    try:
        net_flows = float(growth.get("net_external_flows")) if growth.get("net_external_flows") is not None else None
    except (TypeError, ValueError):
        net_flows = None
    if net_flows is None and external_events:
        try:
            from account_profit import net_external_flow_amount

            net_flows = net_external_flow_amount(external_events)
        except Exception:
            pass

    # Lifetime / total trading P/L % (deposit-aware) + simple average of daily & total
    total_pl_pct: float | None = None
    total_pl_amount: float | None = None
    try:
        if metrics.get("profit_pct") is not None:
            total_pl_pct = float(metrics["profit_pct"])
        if metrics.get("profit_amount") is not None:
            total_pl_amount = float(metrics["profit_amount"])
    except (TypeError, ValueError):
        pass

    # "Total average" = mean of daily actual and total P/L when both known
    avg_components: list[float] = []
    if daily_actual is not None:
        avg_components.append(float(daily_actual))
    if total_pl_pct is not None:
        avg_components.append(float(total_pl_pct))
    total_avg_pl_pct = (
        round(sum(avg_components) / len(avg_components), 4) if avg_components else None
    )

    result = {
        "enabled": bool(goals.get("enabled", True)),
        "agent_goal_bonus": bool(goals.get("agent_goal_bonus", True)),
        "pl_points_enabled": bool(goals.get("pl_points_enabled", True)),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "exclude_deposits": True,
        "primary_goal": "increase_daily_and_total_average_pl",
        "daily": _progress(daily_actual, daily_target),
        "weekly": _progress(weekly_actual, weekly_target),
        "monthly": _progress(monthly_actual, monthly_target),
        "total_pl_pct": round(total_pl_pct, 4) if total_pl_pct is not None else None,
        "total_pl_amount": total_pl_amount,
        "total_avg_pl_pct": total_avg_pl_pct,
        "notes": goals.get("notes"),
        "baseline_value": growth.get("baseline_value") if isinstance(growth, dict) else None,
        "latest_value": growth.get("latest_value") if isinstance(growth, dict) else None,
        "net_external_flows": net_flows,
        "external_flow_event_count": len(external_events),
    }
    return result


def apply_goals_to_horizon_weights(
    weights: dict[str, float],
    goals: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Tilt multi-horizon weights toward goal horizons (day/week/month)."""
    goals = goals or load_account_goals()
    if not goals.get("enabled", True):
        return weights
    out = dict(weights)
    daily_t = float(goals.get("daily_gain_pct") or 0)
    weekly_t = float(goals.get("weekly_gain_pct") or 0)
    monthly_t = float(goals.get("monthly_gain_pct") or 0) if goals.get("monthly_gain_pct") is not None else 0.0
    if daily_t >= 1.0 or weekly_t >= 5.0 or monthly_t >= 10.0:
        out["daily"] = max(out.get("daily", 0.25), 0.38)
        out["weekly"] = max(out.get("weekly", 0.25), 0.32)
        out["monthly"] = max(out.get("monthly", 0.25), 0.22)
        out["yearly"] = min(out.get("yearly", 0.25), 0.08)
    total = sum(out.values()) or 1.0
    return {k: v / total for k, v in out.items()}


def goal_min_buy_return_pct(goals: dict[str, Any] | None = None) -> float:
    """Suggested minimum expected return for new BUYs under account goals."""
    goals = goals or load_account_goals()
    if not goals.get("enabled", True):
        return 0.05
    daily = float(goals.get("daily_gain_pct") or 0.0)
    return max(0.25, min(daily * 0.35, 1.5))


def agent_goal_bonus_score(
    normalized_attribution: float,
    progress: dict[str, Any] | None = None,
    *,
    goals: dict[str, Any] | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Bonus points for agents whose bullish picks sit in the book while goals progress.

    Returns a small additive multiplier boost (0..~0.30) and per-horizon credits.
    Only positive account progress counts — agents are not rewarded for losses.

    When ``agent_id`` is set and pl_points_enabled, also awards group-appropriate
    points for each full 1.0% of total P/L (and half-weight for daily %).
    """
    goals = goals or load_account_goals()
    progress = progress or goal_progress()
    if not goals.get("enabled", True) or not goals.get("agent_goal_bonus", True):
        return {
            "bonus": 0.0,
            "points": 0.0,
            "pl_points": 0.0,
            "horizons": {},
            "eligible": False,
        }
    attr = max(0.0, float(normalized_attribution or 0.0))
    if attr <= 0:
        return {
            "bonus": 0.0,
            "points": 0.0,
            "pl_points": 0.0,
            "horizons": {},
            "eligible": False,
        }

    # Weights for how much each horizon contributes to the bonus
    # Tilt toward daily so daily average P/L is the primary lever
    horizon_weights = {"daily": 0.50, "weekly": 0.30, "monthly": 0.20}
    horizons: dict[str, Any] = {}
    raw = 0.0
    for key, w in horizon_weights.items():
        g = progress.get(key) if isinstance(progress.get(key), dict) else {}
        target = float(g.get("target_pct") or 0.0)
        actual = g.get("actual_pct")
        if target <= 0 or actual is None:
            horizons[key] = {"credit": 0.0, "status": "no_data"}
            continue
        actual_f = float(actual)
        if actual_f <= 0:
            horizons[key] = {
                "credit": 0.0,
                "status": "negative_or_flat",
                "actual_pct": actual_f,
            }
            continue
        # Progress toward goal (capped); meeting the goal gets a 1.25x boost
        ratio = min(1.5, actual_f / target)
        met = actual_f >= target
        if met:
            ratio = max(ratio, 1.25)
        credit = round(w * attr * ratio, 4)
        raw += credit
        horizons[key] = {
            "credit": credit,
            "actual_pct": round(actual_f, 4),
            "target_pct": target,
            "status": "met" if met else "progress",
            "ratio": round(ratio, 4),
        }

    # Extra credit when total P/L is positive (lifetime trading profit %)
    total_pl = progress.get("total_pl_pct")
    total_pl_credit = 0.0
    if total_pl is not None:
        try:
            tp = float(total_pl)
            if tp > 0:
                # Soft credit: 1% total PL → ~0.05 raw at full attribution
                total_pl_credit = round(min(0.5, tp / 20.0) * attr * 0.25, 4)
                raw += total_pl_credit
        except (TypeError, ValueError):
            pass

    # raw roughly 0..~2 → bonus multiplier add-on 0..0.30
    bonus = round(min(0.30, raw * 0.20), 4)
    # Leaderboard-style points 0..100 from horizon bonus path
    points = round(min(100.0, bonus / 0.30 * 100.0), 2)

    # Group-appropriate P/L points (each full 1.0% total + half daily)
    pl_detail: dict[str, Any] = {}
    pl_points = 0.0
    if goals.get("pl_points_enabled", True) and agent_id:
        try:
            from agent_groups import pl_points_for_total_gain

            daily_actual = None
            daily_block = progress.get("daily") if isinstance(progress.get("daily"), dict) else {}
            if daily_block.get("actual_pct") is not None:
                daily_actual = float(daily_block["actual_pct"])
            pl_detail = pl_points_for_total_gain(
                agent_id,
                float(total_pl) if total_pl is not None else None,
                attribution=attr,
                daily_pl_pct=daily_actual,
            )
            pl_points = float(pl_detail.get("points") or 0.0)
            # Fold a capped share of PL points into the leaderboard points
            points = round(min(100.0, points + min(40.0, pl_points * 0.5)), 2)
            # Small multiplier bump from PL points (max +0.10)
            if pl_points > 0:
                bonus = round(min(0.35, bonus + min(0.10, pl_points * 0.005)), 4)
        except Exception:
            pl_detail = {}
            pl_points = 0.0

    return {
        "bonus": bonus,
        "points": points,
        "pl_points": round(pl_points, 2),
        "pl_detail": pl_detail,
        "total_pl_credit": total_pl_credit,
        "horizons": horizons,
        "eligible": True,
        "attribution": round(attr, 4),
    }


def group_pl_leaderboard(
    progress: dict[str, Any] | None = None,
    *,
    goals: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Per-group points for current total/daily P/L (full attribution, catalog view)."""
    goals = goals or load_account_goals()
    if not goals.get("enabled", True) or not goals.get("pl_points_enabled", True):
        return []
    progress = progress or goal_progress()
    total_pl = progress.get("total_pl_pct")
    daily_block = progress.get("daily") if isinstance(progress.get("daily"), dict) else {}
    daily_actual = daily_block.get("actual_pct")
    try:
        from agent_groups import AGENT_GROUPS, pl_points_for_total_gain

        rows: list[dict[str, Any]] = []
        for gid in AGENT_GROUPS:
            row = pl_points_for_total_gain(
                gid,
                float(total_pl) if total_pl is not None else None,
                attribution=1.0,
                daily_pl_pct=float(daily_actual) if daily_actual is not None else None,
                is_group_id=True,
            )
            rows.append(row)
        rows.sort(key=lambda r: (-float(r.get("points") or 0), str(r.get("group_id") or "")))
        return rows
    except Exception:
        return []


def write_goals_status(path: Path | None = None) -> dict[str, Any]:
    """Persist progress snapshot for UI / share."""
    progress = goal_progress()
    dest = path or (OUTPUT / "account_goals_status.json")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(progress, indent=2), encoding="utf-8")
    except OSError:
        pass
    return progress
