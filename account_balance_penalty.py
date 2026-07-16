"""Reward or penalize agents based on account balance trend and bullish attribution."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app_paths import OUTPUT

HISTORY_ROOT = OUTPUT / "history"
TICKER_DIR = HISTORY_ROOT / "tickers"
PENALTIES_FILE = HISTORY_ROOT / "balance_penalties.json"

DECLINE_GROWTH_THRESHOLD_PCT = -0.25
DRAWDOWN_THRESHOLD_PCT = -1.0
RISE_GROWTH_THRESHOLD_PCT = 0.25
MAX_TREND_STRENGTH_PCT = 5.0
MAX_AGENT_PENALTY = 0.45
MAX_AGENT_REWARD = 0.30
MIN_MULTIPLIER = 0.55
MAX_MULTIPLIER = 1.45
ATTRIBUTION_LOOKBACK = 10
ATTRIBUTION_NORM = 2.5
DAILY_GROWTH_BENCHMARKS_PCT: tuple[int, ...] = (1, 2, 3, 4, 5)
BENCHMARK_TIER_REWARD = 0.06


def _load_json(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _opening_balance(growth: dict[str, Any]) -> float | None:
    accounts = growth.get("accounts")
    if isinstance(accounts, dict):
        for meta in accounts.values():
            if isinstance(meta, dict) and meta.get("opening_balance") is not None:
                try:
                    return float(meta["opening_balance"])
                except (TypeError, ValueError):
                    pass
    baseline = growth.get("baseline_value")
    if baseline is not None:
        try:
            return float(baseline)
        except (TypeError, ValueError):
            pass
    points = growth.get("points") or []
    if points:
        try:
            return float(points[0].get("total_account_value"))
        except (TypeError, ValueError, IndexError):
            pass
    return None


def _parse_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _daily_balance_metrics(
    points: list[dict[str, Any]],
    latest_f: float | None,
    *,
    external_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compare latest balance to the start of the current UTC trading day."""
    if latest_f is None or latest_f <= 0:
        return {
            "day_open_value": None,
            "daily_growth_pct": None,
            "benchmark_tiers_hit": [],
            "benchmark_peak_pct": 0,
            "benchmark_tier_count": 0,
        }

    today = datetime.now(timezone.utc).date()
    today_rows: list[tuple[datetime, float]] = []
    prior_rows: list[tuple[datetime, float]] = []

    for row in points:
        if not isinstance(row, dict):
            continue
        ts = _parse_at(str(row.get("at") or ""))
        if ts is None:
            continue
        try:
            val = float(row.get("total_account_value", 0) or 0)
        except (TypeError, ValueError):
            continue
        if val <= 0:
            continue
        if ts.date() == today:
            today_rows.append((ts, val))
        elif ts.date() < today:
            prior_rows.append((ts, val))

    day_open: float | None = None
    if today_rows:
        today_rows.sort(key=lambda item: item[0])
        day_open = today_rows[0][1]
    elif prior_rows:
        prior_rows.sort(key=lambda item: item[0])
        day_open = prior_rows[-1][1]
    elif points:
        try:
            day_open = float(points[0].get("total_account_value"))
        except (TypeError, ValueError):
            day_open = None

    daily_growth_pct: float | None = None
    if day_open and day_open > 0:
        today_flows = 0.0
        if external_events:
            from account_profit import external_flows_on_utc_date

            today_flows = external_flows_on_utc_date(external_events, today)
        daily_growth_pct = round((latest_f - day_open - today_flows) / day_open * 100, 2)

    tiers_hit = [
        tier
        for tier in DAILY_GROWTH_BENCHMARKS_PCT
        if daily_growth_pct is not None and daily_growth_pct >= tier
    ]
    peak_tier = max(tiers_hit) if tiers_hit else 0

    return {
        "day_open_value": round(day_open, 2) if day_open is not None else None,
        "daily_growth_pct": daily_growth_pct,
        "benchmark_tiers_hit": tiers_hit,
        "benchmark_peak_pct": peak_tier,
        "benchmark_tier_count": len(tiers_hit),
    }


def account_balance_state() -> dict[str, Any]:
    """Summarize account trend for reward/penalty scaling."""
    from account_profit import profit_metrics_for_account
    from analysis_history import get_account_growth

    growth = get_account_growth()
    primary = ""
    points = growth.get("points") or []
    if points and isinstance(points[-1], dict):
        primary = str(points[-1].get("account_id_key") or "").strip()
    metrics = profit_metrics_for_account(growth, primary)
    latest = metrics.get("latest_value") if metrics.get("latest_value") is not None else growth.get("latest_value")
    opening = metrics.get("opening_balance")
    if opening is None:
        opening = _opening_balance(growth)
    growth_pct = metrics.get("profit_pct")
    if growth_pct is None:
        growth_pct = growth.get("profit_pct") if growth.get("profit_pct") is not None else growth.get("growth_pct")
    external_events = list(metrics.get("external_flow_events") or [])

    try:
        latest_f = float(latest) if latest is not None else None
    except (TypeError, ValueError):
        latest_f = None

    peak = latest_f
    trough = latest_f
    points = growth.get("points") or []
    for row in points:
        if not isinstance(row, dict):
            continue
        try:
            val = float(row.get("total_account_value", 0) or 0)
        except (TypeError, ValueError):
            continue
        if val > 0:
            peak = val if peak is None else max(peak, val)
            trough = val if trough is None else min(trough, val)

    drawdown_pct: float | None = None
    if latest_f is not None and peak and peak > 0:
        drawdown_pct = round((latest_f - peak) / peak * 100, 2)

    recovery_pct: float | None = None
    if latest_f is not None and trough and trough > 0 and peak and peak > trough:
        recovery_pct = round((latest_f - trough) / trough * 100, 2)

    net_external_flows = metrics.get("net_external_flows") or growth.get("net_external_flows") or 0.0
    invested_capital = metrics.get("invested_capital")
    if growth_pct is None and invested_capital and latest_f is not None and float(invested_capital) > 0:
        growth_pct = round((latest_f - float(invested_capital)) / float(invested_capital) * 100, 2)
    elif growth_pct is None and opening and latest_f is not None and opening > 0:
        growth_pct = round((latest_f - float(opening) - float(net_external_flows)) / float(opening) * 100, 2)

    try:
        growth_f = float(growth_pct) if growth_pct is not None else 0.0
    except (TypeError, ValueError):
        growth_f = 0.0

    drawdown_f = float(drawdown_pct) if drawdown_pct is not None else 0.0
    decline_amount = max(0.0, -growth_f, -drawdown_f)
    is_declining = (
        growth_f <= DECLINE_GROWTH_THRESHOLD_PCT
        or drawdown_f <= DRAWDOWN_THRESHOLD_PCT
    )
    penalty_strength = min(1.0, decline_amount / MAX_TREND_STRENGTH_PCT) if is_declining else 0.0

    rise_amount = max(0.0, growth_f)
    if recovery_pct is not None and recovery_pct > rise_amount:
        rise_amount = float(recovery_pct)
    is_rising = growth_f >= RISE_GROWTH_THRESHOLD_PCT and not is_declining
    reward_strength = min(1.0, rise_amount / MAX_TREND_STRENGTH_PCT) if is_rising else 0.0

    trend = "neutral"
    if is_declining and penalty_strength > 0:
        trend = "declining"
    elif is_rising and reward_strength > 0:
        trend = "rising"

    daily = _daily_balance_metrics(points, latest_f, external_events=external_events)
    if daily.get("benchmark_tier_count"):
        trend = "daily_benchmark"

    return {
        "opening_balance": opening,
        "latest_value": latest_f,
        "growth_pct": growth_pct,
        "profit_pct": growth_pct,
        "net_external_flows": net_external_flows,
        "invested_capital": invested_capital,
        "drawdown_from_peak_pct": drawdown_pct,
        "recovery_from_trough_pct": recovery_pct,
        "is_declining": is_declining,
        "is_rising": is_rising,
        "trend": trend,
        "penalty_strength": round(penalty_strength, 3),
        "reward_strength": round(reward_strength, 3),
        "severity": round(penalty_strength, 3),
        "points": len(points),
        **daily,
    }


def held_symbols() -> set[str]:
    """Symbols the account is exposed to via plan, portfolio, or live positions."""
    symbols: set[str] = set()

    def _add_from_rows(rows: Any) -> None:
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or row.get("Product") or "").strip().upper()
            if sym and not sym.startswith("^"):
                symbols.add(sym)

    portfolio = _load_json(OUTPUT / "portfolio.json")
    if isinstance(portfolio, dict):
        _add_from_rows(portfolio.get("holdings"))

    plan = _load_json(OUTPUT / "strategy_plan.json")
    if isinstance(plan, dict):
        _add_from_rows(plan.get("current_positions"))
        _add_from_rows(plan.get("target_holdings"))

    return symbols


def _agent_bullish_attribution(agent_id: str, held: set[str], *, lookback: int) -> float:
    if not held:
        return 0.0
    aid = str(agent_id or "").strip()
    if not aid:
        return 0.0
    total = 0.0
    for sym in held:
        series = _load_json(TICKER_DIR / f"{sym}.json")
        if not isinstance(series, dict):
            continue
        points = list(series.get("points") or [])[-lookback:]
        for point in points:
            if not isinstance(point, dict):
                continue
            if str(point.get("agent") or "") != aid:
                continue
            try:
                score = float(point.get("score", 0) or 0)
            except (TypeError, ValueError):
                score = 0.0
            if score > 0:
                total += score
    return total


def _global_bullish_attribution(agent_id: str, *, lookback: int) -> float:
    """Fallback when no held symbols are known."""
    aid = str(agent_id or "").strip()
    if not aid or not TICKER_DIR.exists():
        return 0.0
    total = 0.0
    for path in TICKER_DIR.glob("*.json"):
        series = _load_json(path)
        if not isinstance(series, dict):
            continue
        points = list(series.get("points") or [])[-lookback:]
        for point in points:
            if not isinstance(point, dict) or str(point.get("agent") or "") != aid:
                continue
            try:
                score = float(point.get("score", 0) or 0)
            except (TypeError, ValueError):
                score = 0.0
            if score > 0:
                total += score
    return total


def _normalized_attribution(attr: float, max_attr: float) -> float:
    if attr <= 0:
        return 0.0
    normalized = min(1.0, attr / ATTRIBUTION_NORM)
    if max_attr > 0:
        normalized = max(normalized, attr / max_attr * 0.5)
    return normalized


def agent_balance_penalty_multiplier(
    agent_id: str,
    *,
    store: dict[str, Any] | None = None,
) -> float:
    """Return 0.55–1.30 multiplier from account trend and recent bullish attribution."""
    if store is None:
        store = _load_json(PENALTIES_FILE) or {}
    agents = store.get("agents")
    if isinstance(agents, dict):
        entry = agents.get(str(agent_id or ""))
        if isinstance(entry, dict) and entry.get("multiplier") is not None:
            try:
                return float(entry["multiplier"])
            except (TypeError, ValueError):
                pass
    return 1.0


def rebuild_balance_penalties(*, lookback: int = ATTRIBUTION_LOOKBACK) -> dict[str, Any]:
    """Recompute per-agent balance rewards/penalties from trend and attribution."""
    from agents.platform_catalog import active_agent_sources

    state = account_balance_state()
    held = held_symbols()
    penalty_strength = float(state.get("penalty_strength") or state.get("severity") or 0.0)
    reward_strength = float(state.get("reward_strength") or 0.0)
    is_declining = bool(state.get("is_declining"))
    is_rising = bool(state.get("is_rising"))
    trend = str(state.get("trend") or "neutral")

    raw_attr: dict[str, float] = {}
    for src in active_agent_sources(check_remote=False):
        aid = str(src.get("id") or "")
        if not aid:
            continue
        attr = _agent_bullish_attribution(aid, held, lookback=lookback)
        if attr <= 0 and not held:
            attr = _global_bullish_attribution(aid, lookback=lookback) * 0.35
        raw_attr[aid] = attr

    max_attr = max(raw_attr.values()) if raw_attr else 0.0
    tier_count = int(state.get("benchmark_tier_count") or 0)
    tiers_hit = list(state.get("benchmark_tiers_hit") or [])
    agents: dict[str, Any] = {}
    for aid, attr in raw_attr.items():
        multiplier = 1.0
        blame = 0.0
        credit = 0.0
        benchmark_credit = 0.0
        normalized = _normalized_attribution(attr, max_attr)

        if is_declining and penalty_strength > 0 and attr > 0:
            blame = round(normalized * penalty_strength, 3)
            multiplier = 1.0 - blame * MAX_AGENT_PENALTY
        elif is_rising and reward_strength > 0 and attr > 0:
            credit = round(normalized * reward_strength, 3)
            multiplier = 1.0 + credit * MAX_AGENT_REWARD

        if tier_count > 0 and attr > 0:
            benchmark_credit = round(normalized * tier_count * BENCHMARK_TIER_REWARD, 3)
            multiplier += benchmark_credit

        multiplier = round(max(MIN_MULTIPLIER, min(MAX_MULTIPLIER, multiplier)), 3)

        agents[aid] = {
            "multiplier": multiplier,
            "bullish_attribution": round(attr, 3),
            "blame_score": blame,
            "reward_score": credit,
            "benchmark_reward_score": benchmark_credit,
            "benchmark_tiers_hit": tiers_hit,
            "held_overlap": bool(held),
        }

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "account": state,
        "held_symbols": sorted(held),
        "lookback_points": lookback,
        "daily_benchmarks_pct": list(DAILY_GROWTH_BENCHMARKS_PCT),
        "trend": trend,
        "is_declining": is_declining,
        "is_rising": is_rising,
        "benchmark_tiers_hit": tiers_hit,
        "benchmark_peak_pct": state.get("benchmark_peak_pct", 0),
        "daily_growth_pct": state.get("daily_growth_pct"),
        "agents": agents,
    }
    _write_json(PENALTIES_FILE, payload)
    return payload


def penalty_label(agent_id: str) -> str:
    store = _load_json(PENALTIES_FILE) or {}
    entry = (store.get("agents") or {}).get(str(agent_id or ""))
    if not isinstance(entry, dict):
        return ""
    parts: list[str] = []
    tiers = entry.get("benchmark_tiers_hit") or store.get("benchmark_tiers_hit") or []
    if tiers:
        peak = max(int(t) for t in tiers)
        parts.append(f"day T{peak}")
    mult = entry.get("multiplier")
    if mult is not None:
        try:
            value = float(mult)
            if value < 0.999 or value > 1.001:
                delta = (value - 1.0) * 100
                sign = "+" if delta > 0 else "−"
                parts.append(f"bal {sign}{abs(delta):.0f}%")
        except (TypeError, ValueError):
            pass
    return " · ".join(parts)