"""Phone Orders pack must flatten nested E*TRADE List Orders payloads."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phone_bridge import flatten_etrade_orders


NESTED_OPEN = {
    "orderId": 417,
    "orderType": "EQ",
    "OrderDetail": {
        "placedTime": 1788356877249,
        "orderValue": 156.1,
        "status": "OPEN",
        "orderTerm": "GOOD_UNTIL_CANCEL",
        "priceType": "STOP_LIMIT",
        "limitPrice": 15.61,
        "stopPrice": 15.69,
        "marketSession": "REGULAR",
        "Instrument": {
            "symbolDescription": "SOFI TECHNOLOGIES INC COM",
            "orderAction": "SELL",
            "orderedQuantity": 10,
            "filledQuantity": 0,
            "Product": {"securityType": "EQ", "symbol": "SOFI"},
        },
    },
}

NESTED_EXECUTED = {
    "orderId": 415,
    "orderType": "EQ",
    "OrderDetail": {
        "placedTime": 1788350000000,
        "executedTime": 1788350100000,
        "status": "EXECUTED",
        "priceType": "MARKET",
        "Instrument": {
            "orderAction": "BUY",
            "orderedQuantity": 13,
            "filledQuantity": 13,
            "averageExecutionPrice": 14.2,
            "Product": {"symbol": "SOFI"},
        },
    },
}


def test_flatten_nested_open_stop_limit() -> None:
    rows = flatten_etrade_orders([NESTED_OPEN])
    assert len(rows) == 1
    row = rows[0]
    assert row["order_id"] == "417"
    assert row["symbol"] == "SOFI"
    assert row["action"] == "SELL"
    assert row["status"] == "OPEN"
    assert row["quantity"] == 10
    assert row["limit_price"] == 15.61
    assert row["stop_price"] == 15.69
    assert row["placed_time_ms"] == 1788356877249
    assert "Stop" in str(row["display"]["price"])
    assert row["display"]["status"] == "OPEN"


def test_flatten_nested_executed_and_dedupes_open_plus_all() -> None:
    rows = flatten_etrade_orders([NESTED_OPEN, NESTED_OPEN, NESTED_EXECUTED])
    assert [r["order_id"] for r in rows] == ["417", "415"]
    assert rows[1]["status"] == "EXECUTED"
    assert rows[1]["action"] == "BUY"
    assert rows[1]["average_fill_price"] == 14.2


def test_flatten_already_flat_row_still_works() -> None:
    rows = flatten_etrade_orders(
        [
            {
                "order_id": "99",
                "symbol": "AFRM",
                "action": "BUY",
                "status": "OPEN",
                "quantity": 2,
                "limit_price": 10.5,
            }
        ]
    )
    assert rows[0]["symbol"] == "AFRM"
    assert rows[0]["action"] == "BUY"
    assert rows[0]["quantity"] == 2
