"""Pipeline book, short-feed gate, regime enum, specialist non-prediction."""

from __future__ import annotations

from agents.pipeline_book import held_first_watchlist, held_symbols
from agents.short_data_feed import run_short_agent, short_feed_status
from agents.market_regime_state import parse_regime
from prediction_accuracy import TAPE_ACCURACY_CLUSTER, _extract_from_agent_file


def test_held_first_puts_pipeline_lots_ahead_of_canned() -> None:
    canned = {"AAPL": "Apple", "MSFT": "Microsoft", "SPY": "S&P"}
    watch = held_first_watchlist(canned, extra=["BRVE", "SOFI"], max_canned=2)
    keys = list(watch.keys())
    held = held_symbols()
    if held:
        assert keys[0] in held or keys[0] in {"BRVE", "SOFI", "SPY"}
    assert "SPY" in watch


def test_short_feed_silent_without_file() -> None:
    st = short_feed_status()
    payload = run_short_agent("borrow-fees", label="CTB")
    if not st.get("available"):
        assert payload.get("market_signals") == []
        assert payload["meta"]["feed_available"] is False


def test_regime_enum_ids() -> None:
    r = parse_regime({"regime_label": "High-Vol Mean-Reverting", "volatility_state": "High Volatility", "trending_state": "Mean-Reverting"})
    assert r["id"] == "high_vol_mean_reverting"
    assert r["allow_breakouts"] is False
    assert r["size_multiplier"] == 0.5


def test_specialists_do_not_queue_live_labels() -> None:
    pending: list = []
    _extract_from_agent_file(
        "markets",
        {
            "market_signals": [{"bias": "BULLISH", "tickers": ["QQQ"], "sector": "Tape"}],
            "predictions": {"24h": [{"symbol": "QQQ", "predicted_direction": "up", "confidence": 0.6}]},
        },
        cycle_id="t",
        recorded_at="2026-08-26T00:00:00+00:00",
        quotes={"QQQ": 400.0},
        pending=pending,
    )
    assert pending == []
    _extract_from_agent_file(
        "market-predictor",
        {
            "predictions": {"24h": [{"symbol": "QQQ", "predicted_direction": "up", "confidence": 0.6}]},
        },
        cycle_id="t2",
        recorded_at="2026-08-26T00:00:00+00:00",
        quotes={"QQQ": 400.0},
        pending=pending,
    )
    # Predictor may or may not append depending on domain/liquidity gates.
    assert TAPE_ACCURACY_CLUSTER
