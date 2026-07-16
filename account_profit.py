"""Detect external transfers/deposits and compute profit excluding them."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

EXTERNAL_FLOW_MIN_ABS = 25.0
EXTERNAL_FLOW_MIN_PCT = 0.20
CASH_MATCH_MIN_RATIO = 0.55


def _parse_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def collapse_to_transitions(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the first snapshot at each distinct balance level (skip refresh duplicates)."""
    collapsed: list[dict[str, Any]] = []
    last_key: tuple[float | None, float | None] | None = None
    for row in sorted(points, key=lambda item: str(item.get("at", ""))):
        if not isinstance(row, dict):
            continue
        total = _float(row.get("total_account_value"))
        cash = _float(row.get("cash_buying_power"))
        if total is None or total <= 0:
            continue
        key = (round(total, 2), round(cash, 2) if cash is not None else None)
        if key == last_key:
            continue
        collapsed.append(row)
        last_key = key
    return collapsed


def _flow_threshold(prior_total: float) -> float:
    return max(EXTERNAL_FLOW_MIN_ABS, abs(prior_total) * EXTERNAL_FLOW_MIN_PCT)


def _is_external_deposit(total_delta: float, cash_delta: float | None, prior_total: float) -> bool:
    if total_delta < _flow_threshold(prior_total):
        return False
    if cash_delta is None:
        return False
    if cash_delta <= 0:
        return False
    return cash_delta >= total_delta * CASH_MATCH_MIN_RATIO


def _is_external_withdrawal(total_delta: float, cash_delta: float | None, prior_total: float) -> bool:
    if total_delta > -_flow_threshold(prior_total):
        return False
    if cash_delta is None:
        return False
    if cash_delta >= 0:
        return False
    return abs(cash_delta) >= abs(total_delta) * CASH_MATCH_MIN_RATIO


def detect_external_flow_events(
    points: list[dict[str, Any]],
    account_id_key: str = "",
) -> list[dict[str, Any]]:
    """Infer deposits/withdrawals from large balance jumps matched by cash movement."""
    from account_growth_chart import points_for_account

    scoped = points_for_account(points, account_id_key)
    if not scoped:
        scoped = [row for row in points if isinstance(row, dict)]
    transitions = collapse_to_transitions(scoped)
    events: list[dict[str, Any]] = []
    prev_total: float | None = None
    prev_cash: float | None = None

    for row in transitions:
        total = _float(row.get("total_account_value"))
        cash = _float(row.get("cash_buying_power"))
        if total is None:
            continue
        if prev_total is not None:
            total_delta = total - prev_total
            cash_delta = None if cash is None or prev_cash is None else cash - prev_cash
            kind = ""
            if _is_external_deposit(total_delta, cash_delta, prev_total):
                kind = "deposit"
            elif _is_external_withdrawal(total_delta, cash_delta, prev_total):
                kind = "withdrawal"
            if kind:
                events.append(
                    {
                        "at": str(row.get("at") or ""),
                        "amount": round(total_delta, 2),
                        "kind": kind,
                        "total_before": round(prev_total, 2),
                        "total_after": round(total, 2),
                        "cash_before": round(prev_cash, 2) if prev_cash is not None else None,
                        "cash_after": round(cash, 2) if cash is not None else None,
                        "account_id_key": str(row.get("account_id_key") or account_id_key or ""),
                    }
                )
        prev_total = total
        prev_cash = cash
    return events


def net_external_flow_amount(events: list[dict[str, Any]]) -> float:
    return round(sum(_float(event.get("amount")) or 0.0 for event in events), 2)


def net_external_flows_before(events: list[dict[str, Any]], at: str) -> float:
    stamp = str(at or "")
    return round(
        sum(_float(event.get("amount")) or 0.0 for event in events if str(event.get("at") or "") <= stamp),
        2,
    )


def external_flows_on_utc_date(events: list[dict[str, Any]], day: datetime.date) -> float:
    total = 0.0
    for event in events:
        ts = _parse_at(str(event.get("at") or ""))
        if ts is None or ts.date() != day:
            continue
        total += _float(event.get("amount")) or 0.0
    return round(total, 2)


def profit_metrics_for_account(
    growth: dict[str, Any],
    account_id_key: str = "",
) -> dict[str, Any]:
    """Profit = latest balance − opening − net external deposits/withdrawals."""
    from account_growth_chart import points_for_account, resolve_opening_balance_for_account

    key = str(account_id_key or "").strip()
    points = list(growth.get("points") or [])
    accounts_meta = growth.get("accounts") if isinstance(growth.get("accounts"), dict) else {}

    scoped = points_for_account(points, key)
    if not scoped and points:
        scoped = [row for row in points if isinstance(row, dict)]

    opening = resolve_opening_balance_for_account(key, scoped, accounts_meta=accounts_meta)
    if opening is None:
        opening = _float(growth.get("baseline_value"))

    latest = _float(scoped[-1].get("total_account_value")) if scoped else _float(growth.get("latest_value"))
    events = detect_external_flow_events(scoped, key)
    net_flows = net_external_flow_amount(events)

    opening_f = _float(opening)
    invested = round(opening_f + net_flows, 2) if opening_f is not None else None

    profit_amt: float | None = None
    profit_pct: float | None = None
    if invested is not None and invested > 0 and latest is not None:
        profit_amt = round(latest - invested, 2)
        profit_pct = round(profit_amt / invested * 100, 2)

    return {
        "account_id_key": key or None,
        "opening_balance": opening_f,
        "latest_value": latest,
        "net_external_flows": net_flows,
        "invested_capital": invested,
        "profit_amount": profit_amt,
        "profit_pct": profit_pct,
        "external_flow_events": events,
        "growth_pct": profit_pct,
    }


def profit_at_point(
    value: float,
    opening: float,
    events: list[dict[str, Any]],
    at: str,
) -> tuple[float, float]:
    net = net_external_flows_before(events, at)
    invested = opening + net
    if invested <= 0:
        return 0.0, 0.0
    amt = value - invested
    return amt, amt / invested * 100