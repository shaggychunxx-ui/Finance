"""Detect external transfers/deposits and compute profit excluding them.

Profit must never include deposits (or other external capital). Formula:

    profit = latest_balance − opening_balance − net_external_flows

Deposits are inferred from cash-matched balance jumps, large jumps without cash
data, and any material gap between a recorded opening balance and the first
tracked snapshot (common when tracking starts after a deposit, or early history
rolls off the retention window).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Cash-matched jumps of this size (or larger) count as external transfers.
# Future deposits: any cash-matched equity jump ≥ this is excluded from P&L/goals.
EXTERNAL_FLOW_MIN_ABS = 10.0
# When cash data is missing, require a stronger absolute / relative jump.
EXTERNAL_FLOW_NO_CASH_MIN_ABS = 50.0
EXTERNAL_FLOW_NO_CASH_PCT = 0.10
# Cash movement must cover at least this fraction of the total-value jump.
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


def _no_cash_threshold(prior_total: float) -> float:
    return max(EXTERNAL_FLOW_NO_CASH_MIN_ABS, abs(prior_total) * EXTERNAL_FLOW_NO_CASH_PCT)


def _is_external_deposit(total_delta: float, cash_delta: float | None, prior_total: float) -> bool:
    """True when a balance jump is capital in (deposit), not trading gain.

    Future deposits are caught when:
      • cash buying power rises with total equity (cash-matched), or
      • cash series is missing and the jump is large (no-cash threshold).
    """
    if total_delta < EXTERNAL_FLOW_MIN_ABS:
        return False
    if cash_delta is not None:
        if cash_delta <= 0:
            return False
        # Cash rose with equity — treat as deposit (covers future ACH/wires).
        if cash_delta >= total_delta * CASH_MATCH_MIN_RATIO:
            return True
        # Cash rose almost as much as equity even if slightly noisy.
        if cash_delta >= EXTERNAL_FLOW_MIN_ABS and cash_delta >= total_delta * 0.40:
            return True
        return False
    # No cash series: only large jumps (avoids classifying ordinary P&L as deposits).
    return total_delta >= _no_cash_threshold(prior_total)


def _is_external_withdrawal(total_delta: float, cash_delta: float | None, prior_total: float) -> bool:
    if total_delta > -EXTERNAL_FLOW_MIN_ABS:
        return False
    if cash_delta is not None:
        if cash_delta >= 0:
            return False
        return abs(cash_delta) >= abs(total_delta) * CASH_MATCH_MIN_RATIO
    return total_delta <= -_no_cash_threshold(prior_total)


def _make_flow_event(
    *,
    at: str,
    amount: float,
    kind: str,
    total_before: float,
    total_after: float,
    cash_before: float | None,
    cash_after: float | None,
    account_id_key: str,
    source: str = "transition",
) -> dict[str, Any]:
    return {
        "at": at,
        "amount": round(amount, 2),
        "kind": kind,
        "total_before": round(total_before, 2),
        "total_after": round(total_after, 2),
        "cash_before": round(cash_before, 2) if cash_before is not None else None,
        "cash_after": round(cash_after, 2) if cash_after is not None else None,
        "account_id_key": account_id_key,
        "source": source,
    }


def opening_gap_event(
    opening_balance: float,
    first_row: dict[str, Any],
    account_id_key: str = "",
) -> dict[str, Any] | None:
    """If recorded open balance differs from the first snapshot, that gap is capital in/out.

    Happens when tracking starts after a deposit, or early history is rolled off the
    retention window while opening_balance still reflects the true account open.
    """
    first_total = _float(first_row.get("total_account_value"))
    if first_total is None or opening_balance <= 0:
        return None
    delta = first_total - float(opening_balance)
    if abs(delta) < EXTERNAL_FLOW_MIN_ABS:
        return None
    kind = "deposit" if delta > 0 else "withdrawal"
    return _make_flow_event(
        at=str(first_row.get("at") or ""),
        amount=delta,
        kind=kind,
        total_before=float(opening_balance),
        total_after=first_total,
        cash_before=None,
        cash_after=_float(first_row.get("cash_buying_power")),
        account_id_key=str(first_row.get("account_id_key") or account_id_key or ""),
        source="opening_gap",
    )


def detect_external_flow_events(
    points: list[dict[str, Any]],
    account_id_key: str = "",
    *,
    opening_balance: float | None = None,
) -> list[dict[str, Any]]:
    """Infer deposits/withdrawals from balance jumps (cash-matched or large no-cash).

    When ``opening_balance`` is provided and differs from the first tracked total by
    at least ``EXTERNAL_FLOW_MIN_ABS``, the gap is recorded as a deposit/withdrawal
    so pre-tracking capital is never counted as profit.
    """
    from account_growth_chart import points_for_account

    scoped = points_for_account(points, account_id_key)
    if not scoped:
        scoped = [row for row in points if isinstance(row, dict)]
    transitions = collapse_to_transitions(scoped)
    events: list[dict[str, Any]] = []

    opening_f = _float(opening_balance)
    if opening_f is not None and transitions:
        # Skip synthetic open-anchor rows so the gap uses the first real snapshot.
        first_real = next(
            (
                row
                for row in transitions
                if str(row.get("source") or "") != "account_open_anchor"
            ),
            transitions[0],
        )
        gap = opening_gap_event(opening_f, first_real, account_id_key)
        if gap is not None:
            events.append(gap)

    prev_total: float | None = None
    prev_cash: float | None = None
    prev_source: str = ""

    for row in transitions:
        total = _float(row.get("total_account_value"))
        cash = _float(row.get("cash_buying_power"))
        source = str(row.get("source") or "")
        if total is None:
            continue
        if prev_total is not None:
            # Opening-gap already accounts for open-anchor → first real snapshot.
            skip = prev_source == "account_open_anchor" or source == "account_open_anchor"
            if not skip:
                total_delta = total - prev_total
                cash_delta = None if cash is None or prev_cash is None else cash - prev_cash
                kind = ""
                if _is_external_deposit(total_delta, cash_delta, prev_total):
                    kind = "deposit"
                elif _is_external_withdrawal(total_delta, cash_delta, prev_total):
                    kind = "withdrawal"
                if kind:
                    events.append(
                        _make_flow_event(
                            at=str(row.get("at") or ""),
                            amount=total_delta,
                            kind=kind,
                            total_before=prev_total,
                            total_after=total,
                            cash_before=prev_cash,
                            cash_after=cash,
                            account_id_key=str(row.get("account_id_key") or account_id_key or ""),
                            source="transition",
                        )
                    )
        prev_total = total
        prev_cash = cash
        prev_source = source
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


def external_flows_between(
    events: list[dict[str, Any]],
    *,
    start_ts: datetime | None,
    end_ts: datetime | None,
    include_start: bool = False,
) -> float:
    """Net external flows with event timestamps in (start_ts, end_ts] (UTC).

    Deposits are positive; withdrawals negative. Used so horizon gains never
    count capital added or removed as trading P&L.
    """
    if not events:
        return 0.0
    start_epoch: float | None = None
    end_epoch: float | None = None
    if start_ts is not None:
        st = start_ts if start_ts.tzinfo else start_ts.replace(tzinfo=timezone.utc)
        start_epoch = st.timestamp()
    if end_ts is not None:
        et = end_ts if end_ts.tzinfo else end_ts.replace(tzinfo=timezone.utc)
        end_epoch = et.timestamp()
    total = 0.0
    for event in events:
        ts = _parse_at(str(event.get("at") or ""))
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        epoch = ts.timestamp()
        if start_epoch is not None:
            if include_start:
                if epoch < start_epoch:
                    continue
            elif epoch <= start_epoch:
                continue
        if end_epoch is not None and epoch > end_epoch:
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
    events = detect_external_flow_events(scoped, key, opening_balance=opening)
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
