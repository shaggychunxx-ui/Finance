"""Phone pack publish quality + held-lot counting (no network)."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import phone_bridge as pb  # noqa: E402


def test_pack_held_lot_count_ignores_idea_rows() -> None:
    pack = {
        "portfolio": {"held_position_count": 16, "row_count": 50},
        "positions": (
            [{"symbol": "RIVN", "quantity": 1, "side": "LONG"}] * 16
            + [{"symbol": "IDEA", "quantity": 0, "side": "TARGET", "proposed_status": "idea"}] * 34
        ),
    }
    assert pb._pack_held_lot_count(pack) == 16
    thinner_ideas = dict(pack)
    thinner_ideas["positions"] = pack["positions"][:16] + pack["positions"][16 : 16 + 32]
    assert pb._pack_held_lot_count(thinner_ideas) == 16


def test_publish_allows_idea_row_drop_same_held_lots() -> None:
    with tempfile.TemporaryDirectory() as raw:
        dest = Path(raw) / "etrade-dashboard.json"
        orig = pb._oxygen_dashboard_path
        pb._oxygen_dashboard_path = lambda: dest  # type: ignore[method-assign]
        try:
            prior = {
                "portfolio": {"held_position_count": 16, "row_count": 50},
                "positions": [{"symbol": "RIVN", "quantity": 1, "side": "LONG"}] * 16
                + [{"symbol": "IDEA", "quantity": 0, "side": "TARGET"}] * 34,
                "data_pull": {"live": False},
            }
            dest.write_text(json.dumps(prior), encoding="utf-8")
            newer = {
                "portfolio": {"held_position_count": 16, "row_count": 48},
                "positions": [{"symbol": "RIVN", "quantity": 1, "side": "LONG"}] * 16
                + [{"symbol": "IDEA", "quantity": 0, "side": "TARGET"}] * 32,
                "data_pull": {"live": False, "marks_source": "yahoo_public"},
                "updated_at": 1,
            }
            pb._publish_dashboard_to_oxygen(newer)
            saved = json.loads(dest.read_text(encoding="utf-8"))
            assert saved.get("updated_at") == 1
            assert saved["portfolio"]["row_count"] == 48
        finally:
            pb._oxygen_dashboard_path = orig  # type: ignore[method-assign]


def test_publish_blocks_held_lot_collapse() -> None:
    with tempfile.TemporaryDirectory() as raw:
        dest = Path(raw) / "etrade-dashboard.json"
        orig = pb._oxygen_dashboard_path
        pb._oxygen_dashboard_path = lambda: dest  # type: ignore[method-assign]
        try:
            prior = {
                "portfolio": {"held_position_count": 16},
                "positions": [{"symbol": "RIVN", "quantity": 1, "side": "LONG"}] * 16,
                "updated_at": 9,
            }
            dest.write_text(json.dumps(prior), encoding="utf-8")
            stub = {
                "portfolio": {"held_position_count": 1},
                "positions": [{"symbol": "RIVN", "quantity": 1, "side": "LONG"}],
                "data_pull": {"live": False},
                "updated_at": 99,
            }
            pb._publish_dashboard_to_oxygen(stub)
            saved = json.loads(dest.read_text(encoding="utf-8"))
            assert saved.get("updated_at") == 9
        finally:
            pb._oxygen_dashboard_path = orig  # type: ignore[method-assign]


def test_overlay_marks_updates_price() -> None:
    pb._MARKS_CACHE.clear()
    snap = {
        "fetched_at": "2026-08-12T13:30:23+00:00",
        "balance": {"cash": 100.0, "total_account_value": 116.48},
        "positions": [
            {
                "symbol": "RIVN",
                "quantity": 1.0,
                "price": 16.48,
                "market_value": 16.48,
                "cost_basis": 16.6299,
                "position_type": "LONG",
            }
        ],
    }
    orig = pb._yahoo_last_price
    pb._yahoo_last_price = lambda symbol, timeout=8.0: 16.74  # type: ignore[method-assign]
    try:
        marked = pb._overlay_public_marks(snap)
        assert marked["positions"][0]["price"] == 16.74
        assert marked["marks_source"] == "yahoo_public"
        assert marked["marks_count"] == 1
        assert marked["balance"]["total_account_value"] == 116.74
    finally:
        pb._yahoo_last_price = orig  # type: ignore[method-assign]


def test_overlay_skips_fresh_broker_book() -> None:
    pb._MARKS_CACHE.clear()
    snap = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "positions": [{"symbol": "RIVN", "quantity": 1.0, "price": 16.48, "position_type": "LONG"}],
    }

    def boom(symbols, overall_timeout=20.0):  # noqa: ARG001
        raise AssertionError("should not fetch")

    orig = pb._latest_public_quotes
    pb._latest_public_quotes = boom  # type: ignore[method-assign]
    try:
        out = pb._overlay_public_marks(snap)
        assert out["positions"][0]["price"] == 16.48
        assert "marks_source" not in out
    finally:
        pb._latest_public_quotes = orig  # type: ignore[method-assign]


if __name__ == "__main__":
    tests = [
        test_pack_held_lot_count_ignores_idea_rows,
        test_publish_allows_idea_row_drop_same_held_lots,
        test_publish_blocks_held_lot_collapse,
        test_overlay_marks_updates_price,
        test_overlay_skips_fresh_broker_book,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"OK {fn.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    if failed:
        raise SystemExit(1)
    print("ALL_OK")
