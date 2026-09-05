"""Trader summary email formatter — no network, no send."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from send_etrade_trader_summary_email import (  # noqa: E402
    body_looks_filled,
    compose_url,
    format_subject,
    format_text,
)


SAMPLE = {
    "generated_at": "2026-09-04 17:40 UTC",
    "host": "GROMIT",
    "account_name": "Individual Brokerage · CASH · #8804",
    "fetched_at": "2026-09-05T00:27:24.461801+00:00",
    "source": "phone_bridge_live_pull",
    "equity": 3955.34,
    "cash_bp": 125.86,
    "market_value": 6437.15,
    "unrealized_pl": 12.34,
    "position_count": 2,
    "positions": [
        {
            "symbol": "UMC",
            "quantity": 44.0,
            "price": 20.77,
            "market_value": 913.88,
            "cost_basis": 19.93,
            "unrealized_pl": 36.96,
        },
        {
            "symbol": "SOFI",
            "quantity": 16.0,
            "price": 18.22,
            "market_value": 291.52,
            "cost_basis": 18.00,
            "unrealized_pl": 3.52,
        },
    ],
    "total_pl": -105.94,
    "total_pl_pct": -2.66,
    "total_avg_pl_pct": -1.62,
    "baseline_value": 4029.48,
    "daily": {"actual_pct": -0.58, "target_pct": 2.0, "status": "negative"},
    "weekly": {"actual_pct": -4.06},
    "monthly": {"actual_pct": -2.63},
    "flags": {
        "dry_run": False,
        "auto_execute": True,
        "live_trading": True,
        "day_trading": True,
        "paused": False,
        "sandbox": False,
    },
    "long_mode": "LIVE AUTO",
    "market_open": False,
    "agent_count": 83,
    "plan_generated_at": "2026-09-02T23:56:00Z",
    "plan_error": "Not enough bullish signals to build a portfolio.",
    "regime_label": "Neutral",
    "pdt_count": 3,
    "pdt_window_days": ["2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"],
    "orders_source": "pc_live",
    "orders_message": "100 orders from PC",
    "open_order_count": 35,
    "order_count": 100,
    "open_groups": [
        {
            "symbol": "SOFI",
            "action": "SELL",
            "price_type": "STOP_LIMIT",
            "stop_price": "15.69",
            "limit_price": "15.61",
            "quantity": "10",
            "count": 4,
        }
    ],
    "brief_actions": ["Lead walk-forward edge: dca-strategy"],
    "account_id_key": "SHOULD_NOT_APPEAR",
}


def test_format_includes_equity_and_open_orders() -> None:
    text = format_text(SAMPLE)
    assert "$3,955.34" in text
    assert "UMC" in text
    assert "35 of 100" in text
    assert "SOFI" in text
    assert "STOP_LIMIT" in text
    assert "LIVE AUTO" in text
    assert "SHOULD_NOT_APPEAR" not in text


def test_subject_has_equity_and_day_pl() -> None:
    sub = format_subject(SAMPLE)
    assert "$3,955.34" in sub
    assert "day" in sub.lower()
    assert "SHOULD_NOT_APPEAR" not in sub


def test_compose_url_includes_body() -> None:
    url = compose_url("shaggychunxx@gmail.com", "E*TRADE trader summary", "== Positions ==\nUMC qty 44")
    assert "mail.google.com" in url
    assert "view=cm" in url
    assert "to=shaggychunxx" in url
    assert "body=" in url
    assert "Positions" in url


def test_body_looks_filled_rejects_blank_compose() -> None:
    from PIL import Image

    blank = Image.new("RGB", (974, 523), (255, 255, 255))
    assert body_looks_filled(blank) is False
    filled = Image.new("RGB", (974, 523), (255, 255, 255))
    px = filled.load()
    for y in range(180, 420):
        for x in range(80, 900):
            if (x + y) % 3 == 0:
                px[x, y] = (32, 32, 32)
    assert body_looks_filled(filled) is True
