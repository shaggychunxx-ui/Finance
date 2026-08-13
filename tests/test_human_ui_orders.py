"""Human UI sells must not be canceled or re-placed by the equity API."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from etrade_api.client import (  # noqa: E402
    iter_open_order_legs,
    skip_cancel_reason,
)
from strategy_engine import TradeOrder, _is_mutual_fund_holding  # noqa: E402
from symbol_universe import is_mutual_fund_symbol  # noqa: E402


def _order(
    *,
    symbol: str,
    action: str = "SELL",
    client_order_id: str = "",
    price_type: str = "MARKET",
    security_type: str = "EQ",
    order_id: int = 1,
) -> dict:
    return {
        "orderId": order_id,
        "clientOrderId": client_order_id,
        "OrderDetail": [
            {
                "status": "OPEN",
                "priceType": price_type,
                "Instrument": [
                    {
                        "orderAction": action,
                        "Product": {"symbol": symbol, "securityType": security_type},
                    }
                ],
            }
        ],
    }


def test_known_holdings_are_mutual_funds() -> None:
    for sym in ("ETMUX", "ETBOX", "TAIBX", "PHYZX", "PRBLX"):
        assert is_mutual_fund_symbol(sym)
        assert _is_mutual_fund_holding(sym, {"quantity": 9.01})
    assert not is_mutual_fund_symbol("AAPL")
    assert not _is_mutual_fund_holding("AAPL", {"quantity": 10})


def test_never_cancel_human_ui_fund_sell() -> None:
    legs = iter_open_order_legs(
        _order(symbol="PRBLX", client_order_id="UI123", security_type="MF")
    )
    assert len(legs) == 1
    assert skip_cancel_reason(legs[0], {"PRBLX"}, actions={"SELL", "SELL_SHORT"}) == "mutual_fund"


def test_never_cancel_human_sell_without_fin_prefix() -> None:
    legs = iter_open_order_legs(_order(symbol="CSQR", client_order_id=""))
    assert skip_cancel_reason(legs[0], {"CSQR"}, actions={"SELL"}) == "human_or_external"
    legs = iter_open_order_legs(_order(symbol="CSQR", client_order_id="ETRADE-UI-99"))
    assert skip_cancel_reason(legs[0], {"CSQR"}, actions={"SELL"}) == "human_or_external"


def test_may_cancel_worker_protective_stop() -> None:
    legs = iter_open_order_legs(
        _order(
            symbol="CSQR",
            client_order_id="FIN123456ABCDEF",
            price_type="STOP_LIMIT",
        )
    )
    assert skip_cancel_reason(legs[0], {"CSQR"}, actions={"SELL"}) is None


def test_never_cancel_worker_market_sell() -> None:
    legs = iter_open_order_legs(
        _order(symbol="CSQR", client_order_id="FIN123456ABCDEF", price_type="MARKET")
    )
    assert skip_cancel_reason(legs[0], {"CSQR"}, actions={"SELL"}) == "price_type_filtered"


def test_preview_skips_fund_sells_and_does_not_cancel_them() -> None:
    from strategy_engine import StrategyPlan, preview_orders

    cancelled: list[set[str]] = []

    class FakeClient:
        config = SimpleNamespace(sandbox=False)

        def get_balance(self, _acct):
            return {"cash_buying_power": 1000.0, "total_account_value": 4000.0}

        def cancel_open_orders_for_symbols(self, _acct, symbols, **_kwargs):
            cancelled.append(set(symbols))
            raise AssertionError("must not cancel when only fund sells remain")

        def preview_equity_order(self, *_a, **_k):
            raise AssertionError("must not preview fund equity orders")

    plan = StrategyPlan(
        generated_at="t",
        account_id_key="acct",
        account_name="test",
        sandbox=False,
        total_account_value=4000.0,
        investable_usd=3800.0,
        cash_buffer_pct=5.0,
        regime={},
        target_holdings=[],
        current_positions=[],
        orders=[
            TradeOrder(
                symbol="PRBLX",
                action="SELL",
                quantity=9,
                target_weight_pct=0,
                current_weight_pct=14,
                target_value_usd=0,
                current_value_usd=560,
                estimated_price=62.0,
                rationale="Trim position not in agent portfolio",
            )
        ],
        meta={},
    )
    out = preview_orders(FakeClient(), plan)  # type: ignore[arg-type]
    assert out.orders[0].status == "skipped"
    assert "Mutual fund" in (out.orders[0].message or "")
    assert cancelled == []
