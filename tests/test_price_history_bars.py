"""Bar-cache helpers — no network (merge, tip freshness, coverage)."""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _bar(day: str, close: float = 100.0) -> dict:
    return {"at": f"{day}T20:00:00+00:00", "close": close}


def test_merge_daily_bars_overwrites_same_day() -> None:
    from price_history import merge_daily_bars

    existing = [_bar("2024-01-02", 10.0), _bar("2024-01-03", 11.0)]
    newer = [_bar("2024-01-03", 11.5), _bar("2024-01-04", 12.0)]
    merged = merge_daily_bars(existing, newer)
    assert [b["at"][:10] for b in merged] == ["2024-01-02", "2024-01-03", "2024-01-04"]
    assert merged[1]["close"] == 11.5
    assert merged[2]["close"] == 12.0


def test_bar_tip_is_fresh_weekend_window() -> None:
    from price_history import bar_tip_is_fresh

    # Friday bar on Monday = 3 calendar days — still fresh at max_age_days=3.
    friday = [_bar("2024-01-05")]  # Friday
    monday = datetime(2024, 1, 8, 15, 0, tzinfo=timezone.utc)
    assert bar_tip_is_fresh(friday, now=monday, max_age_days=3) is True

    tuesday = datetime(2024, 1, 9, 15, 0, tzinfo=timezone.utc)
    assert bar_tip_is_fresh(friday, now=tuesday, max_age_days=3) is False


def test_fetch_daily_bars_pure_cache_hit() -> None:
    import price_history as ph

    with tempfile.TemporaryDirectory() as td:
        cache_dir = Path(td)
        old_dir = ph.BAR_CACHE_DIR
        old_yahoo = ph._yahoo_daily_bars
        try:
            ph.BAR_CACHE_DIR = cache_dir
            now = datetime.now(timezone.utc)
            bars = []
            for i in range(80):
                d = (now - timedelta(days=80 - i)).date().isoformat()
                bars.append(_bar(d, 100.0 + i * 0.1))
            ph._write_bar_cache(cache_dir / "SPY.json", "SPY", bars)

            def boom(*_a, **_k):
                raise AssertionError("network should not be called on pure cache hit")

            ph._yahoo_daily_bars = boom  # type: ignore[assignment]
            out = ph.fetch_daily_bars("SPY", days=100, use_cache=True)
            assert len(out) == 80
            assert ph.last_bar_fetch_source() == "cache"
        finally:
            ph.BAR_CACHE_DIR = old_dir
            ph._yahoo_daily_bars = old_yahoo


def test_fetch_daily_bars_incremental_merge() -> None:
    import price_history as ph

    with tempfile.TemporaryDirectory() as td:
        cache_dir = Path(td)
        old_dir = ph.BAR_CACHE_DIR
        old_yahoo = ph._yahoo_daily_bars
        try:
            ph.BAR_CACHE_DIR = cache_dir
            now = datetime.now(timezone.utc)
            # Stale tip: last bar 10 days ago (beyond BAR_CACHE_TIP_MAX_AGE_DAYS).
            bars = []
            for i in range(80):
                d = (now - timedelta(days=90 - i)).date().isoformat()
                bars.append(_bar(d, 50.0 + i))
            ph._write_bar_cache(cache_dir / "QQQ.json", "QQQ", bars)

            tip_day = now.date().isoformat()
            tip = [_bar(tip_day, 999.0)]

            def fake_yahoo(symbol, period1, period2):
                assert symbol == "QQQ"
                return tip

            ph._yahoo_daily_bars = fake_yahoo  # type: ignore[assignment]
            out = ph.fetch_daily_bars("QQQ", days=100, use_cache=True)
            assert ph.last_bar_fetch_source() == "incremental"
            assert out[-1]["close"] == 999.0
            assert len(out) >= 80  # history preserved + tip
            reloaded = ph.load_daily_bars("QQQ")
            assert reloaded[-1]["close"] == 999.0
        finally:
            ph.BAR_CACHE_DIR = old_dir
            ph._yahoo_daily_bars = old_yahoo


if __name__ == "__main__":
    test_merge_daily_bars_overwrites_same_day()
    test_bar_tip_is_fresh_weekend_window()
    test_fetch_daily_bars_pure_cache_hit()
    test_fetch_daily_bars_incremental_merge()
    print("ok")
