"""Paths for the E*TRADE Short Trader sister app (isolated from long book)."""

from __future__ import annotations

from pathlib import Path

from app_paths import OUTPUT, ROOT, ensure_app_path

SHORT_OUTPUT = OUTPUT / "short"
SHORT_CONFIG = ROOT / "short_etrade_config.json"
SHORT_CONFIG_EXAMPLE = ROOT / "short_etrade_config.example.json"
SHORT_PLAN_FILE = SHORT_OUTPUT / "short_strategy_plan.json"
SHORT_PORTFOLIO_FILE = SHORT_OUTPUT / "short_portfolio.json"
SHORT_DAY_STATE_FILE = SHORT_OUTPUT / "short_day_state.json"
SHORT_DAY_PLAN_FILE = SHORT_OUTPUT / "short_day_plan.json"
SHORT_WORKER_LOG = SHORT_OUTPUT / "short_worker.log"
SHORT_WORKER_STATE = SHORT_OUTPUT / "short_worker_state.json"
SHORT_WORKER_LOCK = SHORT_OUTPUT / "short_worker.lock"
SHORT_APP_LOG = SHORT_OUTPUT / "short_trader.log"
SHORT_TRADE_HISTORY = SHORT_OUTPUT / "history" / "trade_history.json"
SHORT_PDT_TRACKER = SHORT_OUTPUT / "pdt_tracker.json"

# Windows AppUserModelID — distinct from long ETrade Trader
SHORT_APP_USER_MODEL_ID = "Finance.ETrade.ShortTrader.1"
SHORT_SERVICE_MUTEX_NAME = "Local\\FinanceETradeShortWorkerService"
SHORT_ICON = ROOT / "etrade_short_trader.ico"
SHORT_ICON_SOURCE = ROOT / "etrade_short_trader_source.png"
SHORT_ICON_ALT = ROOT / "short_app_icon.ico"


def ensure_short_dirs() -> Path:
    ensure_app_path()
    SHORT_OUTPUT.mkdir(parents=True, exist_ok=True)
    (SHORT_OUTPUT / "history").mkdir(parents=True, exist_ok=True)
    return SHORT_OUTPUT
