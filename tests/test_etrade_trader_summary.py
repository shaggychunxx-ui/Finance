"""Trader summary email formatter — no network, no send."""

from __future__ import annotations

import base64
import re
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from send_etrade_trader_summary_email import (  # noqa: E402
    body_looks_filled,
    build_summary_pdf,
    compose_url,
    daily_closes_from_points,
    fill_missing_closes,
    format_email_body,
    format_subject,
    format_text,
    implied_non_equity,
    reconstruct_equity,
    week_daily_rows,
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
    "week_start": "2026-09-01",
    "week_end": "2026-09-04",
    "daily_rows": [
        {
            "date": "2026-09-01",
            "weekday": "Mon",
            "close": 3898.84,
            "pl": 2.64,
            "pl_pct": 0.07,
            "source": "history",
            "pdt": 0,
            "pdt_symbols": [],
        },
        {
            "date": "2026-09-02",
            "weekday": "Tue",
            "close": 3877.14,
            "pl": -21.70,
            "pl_pct": -0.56,
            "source": "history",
            "pdt": 0,
            "pdt_symbols": [],
        },
        {
            "date": "2026-09-03",
            "weekday": "Wed",
            "close": None,
            "pl": None,
            "pl_pct": None,
            "source": "missing",
            "pdt": 2,
            "pdt_symbols": ["SOFI"],
        },
        {
            "date": "2026-09-04",
            "weekday": "Thu",
            "close": 3955.34,
            "pl": 78.20,
            "pl_pct": 2.02,
            "source": "snapshot",
            "pdt": 1,
            "pdt_symbols": ["UMC"],
        },
    ],
    "holding_daily": [
        {"symbol": "UMC", "last": 20.77, "day_chg_pct": 1.2, "week_chg_pct": -0.5},
        {"symbol": "SOFI", "last": 18.22, "day_chg_pct": -0.8, "week_chg_pct": 2.1},
    ],
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
    "brief_benchmark": "Accuracy benchmark: 10000/10000 walk-forward trials.",
    "top_agents": [
        {
            "agent_id": "dca-strategy",
            "accuracy_pct": 43.4,
            "edge_score": 0.4609,
            "posture": "calibrated",
            "preferred_horizon": "24h",
        }
    ],
    "pdt_by_date": {"2026-09-03": 2, "2026-09-04": 1},
    "account_id_key": "SHOULD_NOT_APPEAR",
}


def _a85(data: bytes) -> bytes:
    payload = data.strip().replace(b"\r", b"").replace(b"\n", b"")
    if payload.startswith(b"<~"):
        payload = payload[2:]
    if payload.endswith(b"~>"):
        payload = payload[:-2]
    return base64.a85decode(payload, adobe=False, foldspaces=False)


def _pdf_text(path: Path) -> str:
    data = path.read_bytes()
    chunks: list[str] = []
    for match in re.finditer(rb"stream\r?\n(.+?)\r?\nendstream", data, re.S):
        chunk = match.group(1)
        decoded = None
        for decoder in (
            lambda x: x,
            _a85,
            lambda x: zlib.decompress(x),
            lambda x: zlib.decompress(_a85(x)),
        ):
            try:
                decoded = decoder(chunk)
                break
            except Exception:
                continue
        if decoded:
            chunks.append(decoded.decode("latin-1", errors="ignore"))
    return "\n".join(chunks)


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
    assert "weekly" in sub.lower()
    assert "week" in sub.lower()
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


def test_email_body_mentions_pdf_and_keeps_tables() -> None:
    text = format_email_body(SAMPLE, "etrade_weekly_summary.pdf")
    assert "etrade_weekly_summary.pdf" in text
    assert "$3,955.34" in text
    assert "Daily this week" in text
    assert "2026-09-04" in text
    assert "Holdings daily" in text
    assert "SHOULD_NOT_APPEAR" not in text


def test_summary_pdf_has_positions_orders_and_strips_secrets(tmp_path: Path) -> None:
    path = tmp_path / "etrade_trader_summary.pdf"
    built = build_summary_pdf(SAMPLE, path)
    assert built.is_file()
    raw = built.read_bytes()
    assert raw.startswith(b"%PDF")
    assert built.stat().st_size > 1500
    text = _pdf_text(built)
    assert "UMC" in text
    assert "SOFI" in text
    assert "STOP_LIMIT" in text
    assert "dca-strategy" in text
    assert "SHOULD_NOT_APPEAR" not in text
    assert "3,955.34" in text
    assert "Daily this week" in text
    assert "2026-09-04" in text
    assert "Holdings daily" in text


def test_week_daily_rows_use_et_and_prior_close() -> None:
    from datetime import datetime, timezone

    points = [
        {"at": "2026-08-31T20:00:00+00:00", "total_account_value": 3896.20, "account_id_key": "SHOULD_NOT_APPEAR"},
        {"at": "2026-09-01T20:00:00+00:00", "total_account_value": 3898.84},
        {"at": "2026-09-02T23:55:00+00:00", "total_account_value": 3877.14},
        {"at": "2026-09-05T01:12:00+00:00", "total_account_value": 3955.34, "source": "snapshot"},
    ]
    now = datetime(2026, 9, 5, 1, 20, tzinfo=timezone.utc)
    rows = week_daily_rows(
        daily_closes_from_points(points),
        now=now,
        pdt_by_date={"2026-09-03": 2, "2026-09-04": 1},
        pdt_symbols_by_date={"2026-09-03": ["SOFI"], "2026-09-04": ["UMC"]},
    )
    days = [r["date"] for r in rows]
    assert days == ["2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"]
    fri = rows[4]
    assert fri["close"] == 3955.34
    assert fri["source"] == "snapshot"
    assert fri["pdt"] == 1
    assert "UMC" in fri["pdt_symbols"]
    thu = rows[3]
    assert thu["date"] == "2026-09-03"
    assert thu["source"] == "missing"
    assert thu["close"] is None
    text = format_text({**SAMPLE, "daily_rows": rows})
    assert "SHOULD_NOT_APPEAR" not in text
    assert "Mon 2026-08-31" in text
    assert "Fri 2026-09-04" in text


def test_fill_missing_thursday_from_same_lots_and_marks() -> None:
    from datetime import date, datetime, timezone

    points = [
        {"at": "2026-09-02T23:55:00+00:00", "total_account_value": 3877.14},
        {"at": "2026-09-05T01:12:00+00:00", "total_account_value": 3955.34, "source": "snapshot"},
    ]
    lots = [
        {"symbol": "UMC", "quantity": 44.0, "price": 20.77, "market_value": 913.88},
        {"symbol": "SOFI", "quantity": 16.0, "price": 18.22, "market_value": 291.52},
    ]
    mv = 913.88 + 291.52
    non_eq = implied_non_equity(3955.34, lots)
    assert non_eq is not None
    assert abs(non_eq - (3955.34 - mv)) < 0.01
    thu_umc, thu_sofi = 19.86, 18.51
    recon = reconstruct_equity(
        lots, {"UMC": thu_umc, "SOFI": thu_sofi}, non_eq
    )
    assert recon == round(thu_umc * 44 + thu_sofi * 16 + non_eq, 2)
    closes = fill_missing_closes(
        daily_closes_from_points(points),
        monday=date(2026, 8, 31),
        today=date(2026, 9, 4),
        lots=lots,
        marks_by_day={"2026-09-03": {"UMC": thu_umc, "SOFI": thu_sofi}},
        non_equity=non_eq,
        trade_dates=set(),
    )
    now = datetime(2026, 9, 5, 1, 20, tzinfo=timezone.utc)
    rows = week_daily_rows(closes, now=now)
    thu = next(r for r in rows if r["date"] == "2026-09-03")
    assert thu["source"] == "marks"
    assert thu["close"] == recon
    assert thu["close"] is not None
    fri = next(r for r in rows if r["date"] == "2026-09-04")
    assert fri["close"] == 3955.34
    text = format_text({**SAMPLE, "daily_rows": rows})
    assert "filled from same lots" in text
    # A trade on Thursday means lots may have changed — leave the gap.
    skipped = fill_missing_closes(
        daily_closes_from_points(points),
        monday=date(2026, 8, 31),
        today=date(2026, 9, 4),
        lots=lots,
        marks_by_day={"2026-09-03": {"UMC": thu_umc, "SOFI": thu_sofi}},
        non_equity=non_eq,
        trade_dates={"2026-09-03"},
    )
    skipped_rows = week_daily_rows(skipped, now=now)
    assert next(r for r in skipped_rows if r["date"] == "2026-09-03")["source"] == "missing"
