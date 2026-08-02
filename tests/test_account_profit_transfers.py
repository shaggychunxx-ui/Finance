"""Transfer / ACATS lots count as deposits; zero false P/L at book-in.

Deposits and transferred positions remain usable capital (equity/BP/sellable);
only book-in is excluded from trading P/L.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from account_profit import (
    _is_capital_event,
    _is_external_deposit,
    detect_external_flow_events,
    profit_metrics_for_account,
)


def test_acats_cash_flat_is_deposit():
    """Equity up, cash flat → in-kind transfer = deposit (not trading gain)."""
    prior = 2055.0
    total_delta = 1502.20  # e.g. SPCX + SAGMF window
    cash_delta = 2.0  # noise only
    assert _is_external_deposit(total_delta, cash_delta, prior) is True


def test_cash_matched_wire_is_deposit():
    prior = 2000.0
    total_delta = 500.0
    cash_delta = 500.0
    assert _is_external_deposit(total_delta, cash_delta, prior) is True


def test_ordinary_pl_not_deposit():
    prior = 5000.0
    total_delta = 40.0  # day gain
    cash_delta = -5.0  # cash down a bit
    assert _is_external_deposit(total_delta, cash_delta, prior) is False


def test_capital_event_mixed_acats():
    """~94% equity jump is capital-event even with partial cash."""
    prior = 2055.0
    total_delta = 1944.0  # 2055 → 3999
    assert _is_capital_event(total_delta, prior) is True
    assert _is_external_deposit(total_delta, 100.0, prior) is True


def test_detect_flow_tags_acats_source():
    points = [
        {
            "at": "2026-07-30T18:00:00+00:00",
            "total_account_value": 2055.0,
            "cash_buying_power": 500.0,
            "account_id_key": "t1",
        },
        {
            "at": "2026-07-30T20:00:00+00:00",
            "total_account_value": 3557.2,
            "cash_buying_power": 502.0,  # cash essentially flat
            "account_id_key": "t1",
        },
    ]
    events = detect_external_flow_events(points, "t1", opening_balance=2055.0)
    deposits = [e for e in events if e.get("kind") == "deposit"]
    assert deposits, f"expected deposit events, got {events}"
    # Prefer acats_transfer when cash flat
    assert any(e.get("source") in ("acats_transfer", "capital_event", "transition") for e in deposits)


def test_profit_excludes_transfer_book_in():
    """After transfer book-in, open account P/L should not include the deposit amount."""
    growth = {
        "baseline_value": 2055.0,
        "points": [
            {
                "at": "2026-07-30T18:00:00+00:00",
                "total_account_value": 2055.0,
                "cash_buying_power": 500.0,
                "account_id_key": "t1",
            },
            {
                "at": "2026-07-30T20:00:00+00:00",
                "total_account_value": 3557.2,
                "cash_buying_power": 500.0,
                "account_id_key": "t1",
            },
            {
                "at": "2026-07-31T12:00:00+00:00",
                "total_account_value": 3550.0,  # slight MTM after transfer
                "cash_buying_power": 500.0,
                "account_id_key": "t1",
            },
        ],
        "accounts": {"t1": {"opening_balance": 2055.0}},
    }
    metrics = profit_metrics_for_account(growth, "t1")
    # Invested = opening + transfer deposit (~1502) ≈ 3557; latest 3550 → small loss, not +$1500 profit
    assert metrics["net_external_flows"] and metrics["net_external_flows"] > 1000
    assert metrics["profit_amount"] is not None
    assert abs(metrics["profit_amount"]) < 100, metrics
    # Deposits / transfers raise capital — usable equity is full latest balance
    assert metrics.get("deposits_are_capital") is True
    assert metrics.get("transfer_positions_are_capital") is True
    assert metrics.get("usable_capital") == 3550.0
    assert metrics.get("invested_capital") and metrics["invested_capital"] > 3000
