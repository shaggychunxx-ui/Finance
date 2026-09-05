"""House day-trade cap is off by default; buying-power guard still applies."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategy_engine import TradeOrder  # noqa: E402
from trade_guards import (  # noqa: E402
    DEFAULT_TRADE_GUARDS,
    apply_buying_power_guard,
    apply_pdt_guard,
)


def _buy(symbol: str = "MRNA", qty: int = 10, price: float = 10.0) -> TradeOrder:
    return TradeOrder(
        symbol=symbol,
        action="BUY",
        quantity=qty,
        target_weight_pct=0.0,
        current_weight_pct=0.0,
        target_value_usd=0.0,
        current_value_usd=0.0,
        estimated_price=price,
        rationale="test",
    )


def _tracker_full_window() -> dict:
    return {
        "day_trades": [
            {"date": "2026-08-31", "symbol": "MRNA"},
            {"date": "2026-08-31", "symbol": "SOFI"},
            {"date": "2026-08-31", "symbol": "BRVE"},
        ],
        "same_day_activity": {},
        "opening_positions": {},
    }


def test_house_3_5_cap_off_by_default() -> None:
    assert DEFAULT_TRADE_GUARDS["pdt_enabled"] is False
    order = _buy()
    summary = apply_pdt_guard(
        [order],
        total_equity=3955.0,
        positions=[],
        day_state=None,
        settings=dict(DEFAULT_TRADE_GUARDS),
        tracker=_tracker_full_window(),
        session_date="2026-09-05",
        is_day_trading_plan=True,
    )
    assert summary["pdt_applies"] is False
    assert summary["pdt_enabled"] is False
    assert summary["blocked_day_trades"] == 0
    assert summary["day_trades_5d"] == 3
    assert order.status != "blocked"


def test_house_cap_can_be_reenabled() -> None:
    order = _buy()
    settings = dict(DEFAULT_TRADE_GUARDS)
    settings["pdt_enabled"] = True
    summary = apply_pdt_guard(
        [order],
        total_equity=3955.0,
        positions=[],
        day_state=None,
        settings=settings,
        tracker=_tracker_full_window(),
        session_date="2026-09-05",
        is_day_trading_plan=True,
    )
    assert summary["pdt_applies"] is True
    assert summary["blocked_day_trades"] == 1
    assert order.status == "blocked"
    assert "PDT limit" in order.message


def test_buying_power_still_blocks_when_pdt_off() -> None:
    order = _buy(qty=20, price=50.0)
    summary = apply_buying_power_guard([order], buying_power=125.86, buffer_pct=2.0)
    assert summary["blocked_buys"] == 1
    assert order.status == "blocked"
    assert "buying power" in order.message.lower()
