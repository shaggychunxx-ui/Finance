#!/usr/bin/env python3
"""Headless E*TRADE worker — agents, strategy plan, and orders without the GUI."""

from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import datetime, time as dt_time, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from etrade_api.client import ETradeClient
from etrade_api.config import get_selected_account, load_config
from etrade_api.oauth import is_expired_for_day, load_tokens, needs_renewal, renew_access_token
from finance_runners import load_finance_runners
from strategy_engine import (
    PLAN_FILE,
    StrategyPlan,
    build_strategy_plan,
    execute_orders,
    preview_orders,
    run_agent_pipeline,
    save_strategy_plan,
)

OUTPUT = ROOT / "output"
LOG_FILE = OUTPUT / "etrade_worker.log"
STATE_FILE = OUTPUT / "etrade_worker_state.json"
LOCK_FILE = OUTPUT / "etrade_worker.lock"
CONFIG_PATH = ROOT / "etrade_config.json"
SERVICE_CHECK_SECONDS = 60

DEFAULT_WORKER = {
    "auto_execute": True,
    "live_trading": True,
    "day_trading": True,
    "dry_run": False,
    "paused": False,
    "pipeline_interval_minutes": 5,
    "accuracy_interval_minutes": 15,
    "plan_interval_minutes": 30,
    "execute_min_interval_minutes": 15,
    "day_trading_interval_minutes": 5,
    "allow_off_hours_trading": False,
    "gui_defer_to_worker": True,
    "ui_poll_ms": 500,
    "day_panel_refresh_minutes": 5,
    "worker_status_poll_ms": 60000,
}


def automation_paused(config_path: Path = CONFIG_PATH) -> bool:
    return bool(worker_settings(config_path).get("paused", False))


def set_automation_paused(paused: bool, config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Pause or resume all automation (desktop Stop all / Resume all)."""
    from etrade_api.config import read_config_raw, write_config_raw

    raw = read_config_raw(config_path)
    worker = dict(raw.get("background_worker", {}))
    worker["paused"] = paused
    if paused:
        worker["auto_execute"] = False
        worker["day_trading"] = False
        worker["live_trading"] = False
    else:
        worker["auto_execute"] = True
        worker["day_trading"] = True
        dry = bool(worker.get("dry_run", False))
        worker["live_trading"] = not dry
    raw["background_worker"] = worker
    day_cfg = dict(raw.get("day_trading", {}))
    day_cfg["enabled"] = not paused
    raw["day_trading"] = day_cfg
    write_config_raw(config_path, raw)
    msg = "All automation stopped (mobile)." if paused else "Automation resumed (mobile)."
    _log(msg)
    settings = worker_settings(config_path)
    return {
        "paused": paused,
        "auto_execute": bool(settings.get("auto_execute")),
        "day_trading": bool(settings.get("day_trading")),
        "dry_run": bool(settings.get("dry_run")),
        "live_trading": bool(settings.get("live_trading")),
        "message": msg,
    }


def gui_should_defer_to_worker(config_path: Path = CONFIG_PATH) -> bool:
    """When True, the GUI should not duplicate headless agent/trading loops."""
    settings = worker_settings(config_path)
    if "gui_defer_to_worker" in settings:
        return bool(settings["gui_defer_to_worker"])
    if LOG_FILE.exists():
        return (time.time() - LOG_FILE.stat().st_mtime) < 900
    return False


def _next_service_sleep_seconds(config_path: Path = CONFIG_PATH) -> float:
    """Sleep until the next task is due instead of waking every minute."""
    settings = worker_settings(config_path)
    state = load_worker_state()
    now = time.time()
    waits: list[float] = [30.0]
    for last_key, interval_key, default_min in (
        ("last_pipeline_at", "pipeline_interval_minutes", 5),
        ("last_accuracy_at", "accuracy_interval_minutes", 15),
        ("last_plan_at", "plan_interval_minutes", 30),
        ("last_execute_at", "execute_min_interval_minutes", 15),
        ("last_day_trade_at", "day_trading_interval_minutes", 5),
    ):
        last = state.get(last_key)
        interval = max(60.0, int(settings.get(interval_key, default_min)) * 60)
        if last:
            waits.append(max(0.0, interval - (now - float(last))))
        else:
            waits.append(0.0)
    return min(max(min(waits), 15.0), 300.0)


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def worker_settings(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    raw = _read_json(config_path)
    settings = dict(DEFAULT_WORKER)
    legacy = raw.get("background_worker", {})
    settings.update(legacy)
    if "pipeline_interval_minutes" not in legacy and "full_cycle_interval_minutes" in legacy:
        settings["pipeline_interval_minutes"] = int(legacy["full_cycle_interval_minutes"])
    day_cfg = raw.get("day_trading", {})
    if isinstance(day_cfg, dict):
        if "enabled" in day_cfg and "day_trading" not in legacy:
            settings["day_trading"] = bool(day_cfg["enabled"])
        if "interval_minutes" in day_cfg:
            settings["day_trading_interval_minutes"] = int(day_cfg["interval_minutes"])
    return settings


def load_worker_state() -> dict[str, Any]:
    return _read_json(STATE_FILE)


def save_worker_state(state: dict[str, Any]) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(STATE_FILE, state)


def plan_order_signature(plan: StrategyPlan) -> str:
    items = tuple(
        (o.symbol.upper(), o.action.upper(), int(o.quantity))
        for o in plan.orders
        if o.quantity > 0
    )
    return repr(sorted(items))


def acquire_worker_lock(max_age_seconds: int = 7200) -> bool:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        age = time.time() - LOCK_FILE.stat().st_mtime
        if age < max_age_seconds:
            _log(f"Worker lock active ({int(age)}s old) - skipping this run.")
            return False
        _log("Stale worker lock found - taking over.")
    LOCK_FILE.write_text(str(int(time.time())), encoding="utf-8")
    return True


def release_worker_lock() -> None:
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _interval_due(last_at: Any, interval_minutes: int, *, force: bool = False) -> bool:
    if force:
        return True
    if not last_at:
        return True
    interval = max(1, int(interval_minutes)) * 60
    return (time.time() - float(last_at)) >= interval


def is_us_market_open(now: datetime | None = None) -> bool:
    """US equity regular session (Mon-Fri 9:30-16:00 Eastern)."""
    now = now or datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    return dt_time(9, 30) <= now.time() <= dt_time(16, 0)


def live_trading_enabled(settings: dict[str, Any], *, sandbox: bool) -> bool:
    if not settings.get("auto_execute", True):
        return False
    if not settings.get("live_trading", True):
        return False
    if settings.get("dry_run", False):
        return False
    if sandbox and not settings.get("live_trading_sandbox", False):
        return False
    return True


def day_trading_enabled(settings: dict[str, Any], day_settings: dict[str, Any] | None = None) -> bool:
    """Day trading runs on its own schedule — not tied to swing auto-execute."""
    if not settings.get("day_trading", True):
        return False
    if day_settings is not None and not day_settings.get("enabled", True):
        return False
    return True


def day_trading_can_execute(settings: dict[str, Any], *, sandbox: bool) -> bool:
    """True when day orders may be submitted (live or dry-run simulation)."""
    if settings.get("dry_run", False):
        return True
    if sandbox and not settings.get("live_trading_sandbox", settings.get("live_trading", True)):
        return False
    return True


def _execute_due(state: dict[str, Any], settings: dict[str, Any], sig: str) -> bool:
    if not settings.get("auto_execute", True):
        return False
    if sig and sig == state.get("last_executed_plan_sig"):
        return False
    last = state.get("last_execute_at")
    if not last:
        return True
    interval = int(settings.get("execute_min_interval_minutes", 15)) * 60
    return (time.time() - float(last)) >= interval


def _connect_client(config_path: Path = CONFIG_PATH) -> ETradeClient | None:
    try:
        config = load_config(config_path)
    except Exception as exc:
        _log(f"Config error: {exc}")
        return None

    tokens = load_tokens(config.token_path, config.sandbox)
    if not tokens:
        _log("No saved E*TRADE token - connect via the GUI once.")
        return None

    if is_expired_for_day(tokens):
        _log("E*TRADE token expired (past midnight ET). Reconnect in the GUI.")
        return None

    if needs_renewal(tokens):
        try:
            tokens = renew_access_token(config, tokens)
        except Exception as exc:
            _log(f"Token renewal skipped ({exc}); using existing token.")

    try:
        client = ETradeClient(config, tokens)
        client.list_accounts()
        _log(f"Connected to E*TRADE ({'sandbox' if config.sandbox else 'production'}).")
        return client
    except Exception as exc:
        _log(f"E*TRADE connection failed: {exc}")
        return None


def _resolve_account(client: ETradeClient, config_path: Path = CONFIG_PATH) -> dict[str, Any] | None:
    accounts = client.list_accounts()
    if not accounts:
        return None

    selected = get_selected_account(config_path)
    if not selected:
        _log("No confirmed account saved - open the GUI, pick an account, and confirm.")
        return None

    key = selected["account_id_key"]
    for acct in accounts:
        if acct.get("account_id_key") == key:
            label = acct.get("display_label") or selected.get("display_label") or acct.get("account_name") or key
            _log(f"Using saved account: {label}")
            return acct

    _log(f"Saved account {key} not found at E*TRADE - confirm an account in the GUI.")
    return None


def _run_live_scoring(*, force: bool = False, config_path: Path = CONFIG_PATH) -> bool:
    """Score matured predictions between full pipeline runs."""
    settings = worker_settings(config_path)
    try:
        from live_accuracy import load_live_accuracy_settings

        live_settings = load_live_accuracy_settings(config_path)
        interval = int(
            live_settings.get(
                "accuracy_interval_minutes",
                settings.get("accuracy_interval_minutes", 15),
            )
        )
    except Exception:
        interval = int(settings.get("accuracy_interval_minutes", 15))

    state = load_worker_state()
    if not _interval_due(state.get("last_accuracy_at"), interval, force=force):
        return False

    try:
        from prediction_accuracy import run_live_scoring_cycle

        stats = run_live_scoring_cycle(rebuild_learning=True)
        state["last_accuracy_at"] = time.time()
        state["live_scoring"] = stats
        save_worker_state(state)
        _log(
            "Live scoring — "
            f"{stats.get('scored', 0)} matured, "
            f"{stats.get('pending', 0)} pending, "
            f"{stats.get('live_primary_agents', 0)} agents on live weights, "
            f"{stats.get('blended_agents', 0)} blended."
        )
        return True
    except Exception as exc:
        _log(f"Live scoring skipped: {exc}")
        return False


def _run_pipeline(*, force: bool = False, config_path: Path = CONFIG_PATH) -> bool:
    state = load_worker_state()
    settings = worker_settings(config_path)
    if not _interval_due(state.get("last_pipeline_at"), settings["pipeline_interval_minutes"], force=force):
        _log("Pipeline skipped - not due yet.")
        return False

    _log("Running Finance agent pipeline...")
    runners = load_finance_runners()
    ok = run_agent_pipeline(runners, on_progress=_log, check_remote=False)
    state["last_pipeline_at"] = time.time()
    save_worker_state(state)
    _log(f"Pipeline complete - {ok} agent reports updated.")
    return True


def _submit_plan_orders(
    client: ETradeClient,
    plan: StrategyPlan,
    settings: dict[str, Any],
    state: dict[str, Any],
    *,
    force: bool = False,
) -> bool:
    sig = plan_order_signature(plan)
    if not plan.orders:
        _log("Strategy plan has no orders.")
        return False
    if not force and not _execute_due(state, settings, sig):
        _log("Live trading not due yet or plan unchanged since last execution.")
        return False
    if not live_trading_enabled(settings, sandbox=client.config.sandbox):
        _log("Live trading disabled (dry run, sandbox, or auto_execute off).")
        return False
    if not is_us_market_open() and not settings.get("allow_off_hours_trading", False):
        _log("US market closed - live trading task will retry during market hours.")
        return False

    mode = "LIVE PRODUCTION" if not client.config.sandbox else "LIVE SANDBOX"
    dry_run = bool(settings.get("dry_run", False))
    proposed = len(plan.orders)
    _log(f"=== {mode} TRADING TASK: {proposed} orders ===")
    preview_orders(client, plan)
    blocked = sum(1 for o in plan.orders if o.status == "blocked")
    if blocked:
        guards = (plan.meta or {}).get("trade_guards", {})
        bp = guards.get("available_usd")
        pdt = guards.get("day_trades_5d")
        extra = []
        if bp is not None:
            extra.append(f"${bp:,.2f} buying power available")
        if pdt is not None and guards.get("pdt_applies"):
            extra.append(f"{pdt}/{guards.get('max_day_trades_5d', 3)} day trades in 5d")
        suffix = f" ({'; '.join(extra)})" if extra else ""
        _log(f"Trade guards blocked {blocked}/{proposed} order(s) before E*TRADE preview{suffix}.")
    previewed = sum(1 for o in plan.orders if o.status == "previewed")
    if previewed == 0:
        _log("No orders passed E*TRADE preview.")
        return False

    execute_orders(client, plan, dry_run=dry_run)
    save_strategy_plan(plan)
    placed = sum(1 for o in plan.orders if o.status in {"placed", "dry_run"})
    state["last_executed_plan_sig"] = sig
    state["last_execute_at"] = time.time()
    if dry_run:
        _log(f"Dry run complete - simulated {placed} orders.")
    else:
        _log(f"LIVE orders submitted to E*TRADE: {placed}")
    return True


def _run_plan_build(client: ETradeClient, *, force: bool = False, config_path: Path = CONFIG_PATH) -> StrategyPlan | None:
    state = load_worker_state()
    settings = worker_settings(config_path)
    if not _interval_due(state.get("last_plan_at"), settings["plan_interval_minutes"], force=force):
        _log("Plan skipped - not due yet.")
        return None

    acct = _resolve_account(client, config_path)
    if not acct:
        return None

    _log(
        f"Building strategy plan for "
        f"{acct.get('display_label') or acct.get('account_name') or acct.get('account_id')}..."
    )
    from portfolio_generator import generate_portfolio, save_portfolio
    from strategy_engine import PORTFOLIO_FILE

    balance = client.get_balance(acct["account_id_key"])
    notional = balance.get("total_account_value") or None
    portfolio = generate_portfolio(OUTPUT, notional_usd=notional)
    save_portfolio(portfolio, PORTFOLIO_FILE)
    plan = build_strategy_plan(
        client,
        acct["account_id_key"],
        acct.get("account_name", ""),
        portfolio=portfolio,
    )
    save_strategy_plan(plan)
    state["last_plan_at"] = time.time()
    save_worker_state(state)
    _log(f"Strategy plan ready - {len(plan.orders)} proposed orders.")
    return plan


def _run_day_trading(
    client: ETradeClient,
    *,
    force: bool = False,
    config_path: Path = CONFIG_PATH,
) -> bool:
    from day_trader import (
        apply_day_trade_executions,
        build_day_trade_plan,
        is_day_trading_session,
        load_day_state,
        load_day_trade_settings,
        minutes_to_market_close,
    )

    state = load_worker_state()
    settings = worker_settings(config_path)
    day_settings = load_day_trade_settings(config_path)

    if not day_trading_enabled(settings, day_settings):
        return False
    if not day_trading_can_execute(settings, sandbox=client.config.sandbox):
        _log("Day trading disabled for this environment (sandbox live off).")
        return False

    interval = int(settings.get("day_trading_interval_minutes", day_settings.get("interval_minutes", 5)))
    if not _interval_due(state.get("last_day_trade_at"), interval, force=force):
        return False

    minutes_left = minutes_to_market_close()
    if minutes_left is None or (minutes_left <= 0 and not is_day_trading_session()):
        if not force:
            return False

    acct = _resolve_account(client, config_path)
    if not acct:
        return False

    day_state = load_day_state()
    _log(
        f"Day trading scan — {len(day_state.get('positions', []))} open intraday position(s)…"
    )
    plan = build_day_trade_plan(
        client,
        acct["account_id_key"],
        acct.get("account_name", ""),
        settings=day_settings,
        state=day_state,
    )
    if not plan.orders:
        state["last_day_trade_at"] = time.time()
        save_worker_state(state)
        _log("Day trading: no intraday orders this cycle.")
        return False

    if not is_us_market_open() and not settings.get("allow_off_hours_trading", False):
        _log("US market closed — day trading orders deferred.")
        return False

    mode = "LIVE PRODUCTION" if not client.config.sandbox else "LIVE SANDBOX"
    dry_run = bool(settings.get("dry_run", False))
    proposed = len(plan.orders)
    _log(f"=== DAY TRADE {mode}: {proposed} orders ===")
    preview_orders(client, plan)
    blocked = sum(1 for o in plan.orders if o.status == "blocked")
    if blocked:
        guards = (plan.meta or {}).get("trade_guards", {})
        bp = guards.get("available_usd")
        pdt = guards.get("day_trades_5d")
        extra = []
        if bp is not None:
            extra.append(f"${bp:,.2f} buying power available")
        if pdt is not None and guards.get("pdt_applies"):
            extra.append(f"{pdt}/{guards.get('max_day_trades_5d', 3)} day trades in 5d")
        suffix = f" ({'; '.join(extra)})" if extra else ""
        _log(f"Day trade guards blocked {blocked}/{proposed} order(s) before E*TRADE preview{suffix}.")
    previewed = sum(1 for o in plan.orders if o.status == "previewed")
    if previewed == 0:
        _log("Day trading: no orders passed E*TRADE preview.")
        state["last_day_trade_at"] = time.time()
        save_worker_state(state)
        return False

    execute_orders(client, plan, dry_run=dry_run)
    apply_day_trade_executions(plan, state=day_state, settings=day_settings)
    placed = sum(1 for o in plan.orders if o.status in {"placed", "dry_run"})
    state["last_day_trade_at"] = time.time()
    save_worker_state(state)
    if dry_run:
        _log(f"Day trading dry run — simulated {placed} order(s).")
    else:
        _log(f"Day trading LIVE — submitted {placed} order(s).")
    return True


def _run_live_execute(
    client: ETradeClient,
    *,
    force: bool = False,
    config_path: Path = CONFIG_PATH,
) -> bool:
    from strategy_engine import load_strategy_plan, plan_from_dict

    state = load_worker_state()
    settings = worker_settings(config_path)
    data = load_strategy_plan(PLAN_FILE)
    if not data:
        _log("No saved strategy plan - run plan task first.")
        return False
    plan = plan_from_dict(data)
    executed = _submit_plan_orders(client, plan, settings, state, force=force)
    save_worker_state(state)
    return executed


def _run_plan_and_orders(client: ETradeClient, *, force: bool = False, config_path: Path = CONFIG_PATH) -> bool:
    plan = _run_plan_build(client, force=force, config_path=config_path)
    if plan and plan.orders:
        state = load_worker_state()
        settings = worker_settings(config_path)
        _submit_plan_orders(client, plan, settings, state, force=force)
        save_worker_state(state)
        return True
    if plan:
        _log("No trades needed - portfolio already aligned.")
        return True
    return _run_live_execute(client, force=force, config_path=config_path)


def run_full_cycle(*, force: bool = False, config_path: Path = CONFIG_PATH) -> int:
    if automation_paused(config_path):
        _log("Automation paused — worker cycle skipped.")
        return 0
    if not acquire_worker_lock():
        return 0

    exit_code = 0
    try:
        _log("=== E*TRADE background worker started ===")
        pipeline_ran = _run_pipeline(force=force, config_path=config_path)
        client = _connect_client(config_path)
        plan_ran = False
        if client:
            plan_ran = _run_plan_and_orders(client, force=force, config_path=config_path)
            _run_day_trading(client, force=force, config_path=config_path)
        else:
            _log("Skipping plan/orders - not connected to E*TRADE.")

        if not pipeline_ran and not plan_ran and client:
            _log("Nothing due this cycle.")
        _log("=== Worker cycle finished ===")
    except Exception as exc:
        exit_code = 1
        _log(f"Worker failed: {exc}")
        _log(traceback.format_exc())
    finally:
        release_worker_lock()

    return exit_code


def run_day_trading_for_client(
    client: ETradeClient,
    *,
    force: bool = False,
    config_path: Path = CONFIG_PATH,
) -> bool:
    """Run one day-trading cycle using an existing connected client (GUI or service)."""
    return _run_day_trading(client, force=force, config_path=config_path)


def run_day_trading_cycle(*, force: bool = False, config_path: Path = CONFIG_PATH) -> int:
    if automation_paused(config_path):
        _log("Automation paused — day trading skipped.")
        return 0
    if not acquire_worker_lock(max_age_seconds=900):
        return 0

    exit_code = 0
    try:
        _log("=== Day trading task started ===")
        client = _connect_client(config_path)
        if not client:
            return 1
        _run_day_trading(client, force=force, config_path=config_path)
        _log("=== Day trading task finished ===")
    except Exception as exc:
        exit_code = 1
        _log(f"Day trading task failed: {exc}")
        _log(traceback.format_exc())
    finally:
        release_worker_lock()
    return exit_code


def run_live_trading_cycle(*, force: bool = False, config_path: Path = CONFIG_PATH) -> int:
    """Scheduled task entry: submit live orders from the saved strategy plan."""
    if automation_paused(config_path):
        _log("Automation paused — live trading skipped.")
        return 0
    if not acquire_worker_lock(max_age_seconds=900):
        return 0

    exit_code = 0
    try:
        settings = worker_settings(config_path)
        _log("=== Live trading task started ===")
        if not settings.get("live_trading", True):
            _log("Live trading disabled in background_worker config.")
            return 0

        client = _connect_client(config_path)
        if not client:
            return 1
        _run_live_execute(client, force=force, config_path=config_path)
        _log("=== Live trading task finished ===")
    except Exception as exc:
        exit_code = 1
        _log(f"Live trading task failed: {exc}")
        _log(traceback.format_exc())
    finally:
        release_worker_lock()
    return exit_code


def run_service_loop(config_path: Path = CONFIG_PATH) -> int:
    settings = worker_settings(config_path)
    pipeline_min = int(settings.get("pipeline_interval_minutes", 5))
    plan_min = int(settings.get("plan_interval_minutes", 30))
    execute_min = int(settings.get("execute_min_interval_minutes", 15))
    day_min = int(settings.get("day_trading_interval_minutes", 5))
    live = "ON" if settings.get("live_trading", True) and not settings.get("dry_run") else "OFF"
    day_on = "ON" if settings.get("day_trading", True) else "OFF"
    _log(
        f"Background service started - agents every {pipeline_min} min, "
        f"plan every {plan_min} min, live trading every {execute_min} min ({live}), "
        f"day trading every {day_min} min ({day_on})."
    )
    _log(f"Log file: {LOG_FILE}")

    client: ETradeClient | None = None
    client_refreshed_at = 0.0

    while True:
        try:
            if automation_paused(config_path):
                time.sleep(120)
                continue

            if not client or (time.time() - client_refreshed_at) > 1800:
                client = _connect_client(config_path)
                client_refreshed_at = time.time()

            _run_pipeline(config_path=config_path)
            _run_live_scoring(config_path=config_path)

            if client:
                _run_plan_build(client, config_path=config_path)
                _run_live_execute(client, config_path=config_path)
                _run_day_trading(client, config_path=config_path)
            else:
                _log("Plan/live/day trading waiting for E*TRADE connection.")
        except Exception as exc:
            _log(f"Service loop error: {exc}")
            _log(traceback.format_exc())
            client = None

        time.sleep(_next_service_sleep_seconds(config_path))


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="E*TRADE headless background worker")
    parser.add_argument("--force", action="store_true", help="Run pipeline and plan even if not due")
    parser.add_argument("--service", action="store_true", help="Run continuously in a loop")
    parser.add_argument("--live-trading", action="store_true", help="Run live trading task only")
    parser.add_argument("--day-trading", action="store_true", help="Run day trading task only")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args()

    if args.service:
        return run_service_loop(args.config)
    if args.day_trading:
        return run_day_trading_cycle(force=args.force, config_path=args.config)
    if args.live_trading:
        return run_live_trading_cycle(force=args.force, config_path=args.config)
    return run_full_cycle(force=args.force, config_path=args.config)


if __name__ == "__main__":
    raise SystemExit(main())