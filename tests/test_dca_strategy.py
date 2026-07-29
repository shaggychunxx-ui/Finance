"""Unit tests for the Dollar-Cost Averaging (DCA) strategy module."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_dca_worked_example_matches_volatile_asset_scenario() -> None:
    """Matches the canonical $1,000/month, 4-month worked example."""
    from dca_strategy import DCAPlan

    plan = DCAPlan(symbol="TEST", fixed_amount_usd=1000.0, interval_days=30)
    for price in (100.0, 50.0, 40.0, 80.0):
        plan.deploy(price)

    assert plan.total_capital_usd == 4000.0
    assert plan.total_shares == 67.5
    assert plan.simple_average_price == 67.5
    assert plan.volume_weighted_cost_basis == pytest.approx(59.259259, rel=1e-6)
    assert plan.portfolio_value(80.0) == 5400.0
    assert plan.net_return_pct(80.0) == 35.0
    # Volume-weighted cost basis is structurally lower than the simple average.
    assert plan.volume_weighted_cost_basis < plan.simple_average_price


def test_dca_cost_basis_lower_than_simple_average_under_volatility() -> None:
    from dca_strategy import DCAPlan

    plan = DCAPlan(symbol="VOLATILE", fixed_amount_usd=500.0, interval_days=7)
    for price in (10.0, 5.0, 20.0, 8.0, 12.0):
        plan.deploy(price)

    assert plan.total_capital_usd == 2500.0
    assert plan.total_shares == pytest.approx(279.16666667, rel=1e-6)
    assert plan.simple_average_price == 11.0
    assert plan.volume_weighted_cost_basis == pytest.approx(8.955224, rel=1e-6)
    assert plan.volume_weighted_cost_basis <= plan.simple_average_price


def test_dca_deploy_rejects_non_positive_price_or_capital() -> None:
    from dca_strategy import DCAPlan

    plan = DCAPlan(symbol="BAD")
    with pytest.raises(ValueError):
        plan.deploy(0.0)
    with pytest.raises(ValueError):
        plan.deploy(10.0, capital_usd=0.0)


def test_dca_fractional_shares_disabled_raises_when_price_exceeds_amount() -> None:
    from dca_strategy import DCAPlan

    plan = DCAPlan(symbol="WHOLE", fixed_amount_usd=50.0, allow_fractional_shares=False)
    with pytest.raises(ValueError):
        plan.deploy(100.0)

    # A price under the fixed amount still buys whole shares only.
    plan.deploy(20.0)
    assert plan.total_shares == 2.0


def test_dca_is_due_gates_on_rigid_interval_not_market_conditions() -> None:
    from dca_strategy import DCAPlan

    plan = DCAPlan(symbol="SCHEDULED", fixed_amount_usd=1000.0, interval_days=30)
    assert plan.is_due() is True  # never deployed -> always due

    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    plan.deploy(100.0, executed_at=now.isoformat())

    assert plan.is_due(as_of=now + timedelta(days=10)) is False
    assert plan.is_due(as_of=now + timedelta(days=30)) is True
    assert plan.next_due_at() == now + timedelta(days=30)


def test_dca_record_deployment_persists_and_round_trips(tmp_path, monkeypatch) -> None:
    import dca_strategy

    monkeypatch.setattr(dca_strategy, "DCA_DIR", tmp_path / "dca")

    summary = dca_strategy.record_deployment("ACME", 100.0, capital_usd=1000.0)
    assert summary["deployments"] == 1
    assert summary["total_shares"] == 10.0

    reloaded = dca_strategy.load_dca_plan("ACME")
    assert reloaded.total_shares == 10.0
    assert reloaded.total_capital_usd == 1000.0


def test_dca_due_symbols_filters_only_scheduled_ones(tmp_path, monkeypatch) -> None:
    import dca_strategy

    monkeypatch.setattr(dca_strategy, "DCA_DIR", tmp_path / "dca")

    dca_strategy.record_deployment("FRESH", 50.0, capital_usd=500.0)
    due = dca_strategy.due_symbols(["FRESH", "NEVER_DEPLOYED"])

    assert "NEVER_DEPLOYED" in due
    assert "FRESH" not in due


def test_dca_plan_path_rejects_empty_symbol() -> None:
    from dca_strategy import load_dca_plan

    with pytest.raises(ValueError):
        load_dca_plan("")
