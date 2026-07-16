#!/usr/bin/env python3
"""Headless short-selling worker — isolated from the long ETrade worker."""

from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from short_config import get_selected_account, load_merged_short_config, worker_settings
from short_paths import (
    SHORT_CONFIG,
    SHORT_SERVICE_MUTEX_NAME,
    SHORT_WORKER_LOCK,
    SHORT_WORKER_LOG,
    SHORT_WORKER_STATE,
    ensure_short_dirs,
)
from short_portfolio import generate_short_portfolio, load_short_strategy_settings, save_short_portfolio
from short_strategy_engine import (
    build_short_strategy_plan,
    execute_short_orders,
    preview_short_orders,
    save_short_strategy_plan,
)
from short_day_trader import build_short_day_trade_plan, load_short_day_settings

ET_TZ = ZoneInfo("America/New_York")
_service_mutex_handle: int | None = None


def _log(msg: str) -> None:
    ensure_short_dirs()
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with SHORT_WORKER_LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def load_worker_state() -> dict[str, Any]:
    ensure_short_dirs()
    if not SHORT_WORKER_STATE.exists():
        return {}
    try:
        data = json.loads(SHORT_WORKER_STATE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_worker_state(state: dict[str, Any]) -> None:
    ensure_short_dirs()
    state["updated_at"] = datetime.now(ET_TZ).astimezone().isoformat()
    SHORT_WORKER_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def is_us_market_open(now: datetime | None = None) -> bool:
    now = now or datetime.now(ET_TZ)
    if now.weekday() >= 5:
        return False
    open_ = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_ <= now <= close


def _interval_due(last_at: Any, interval_minutes: int, *, force: bool = False) -> bool:
    if force:
        return True
    if not last_at:
        return True
    try:
        return (time.time() - float(last_at)) >= max(1, interval_minutes) * 60
    except (TypeError, ValueError):
        return True


def acquire_service_lock() -> bool:
    global _service_mutex_handle
    ensure_short_dirs()
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.CreateMutexW(None, False, SHORT_SERVICE_MUTEX_NAME)
            last_error = kernel32.GetLastError()
            if not handle:
                return False
            # ERROR_ALREADY_EXISTS = 183
            if last_error == 183:
                kernel32.CloseHandle(handle)
                return False
            _service_mutex_handle = handle
        except Exception:
            pass
    if SHORT_WORKER_LOCK.exists():
        try:
            age = time.time() - SHORT_WORKER_LOCK.stat().st_mtime
            pid_txt = SHORT_WORKER_LOCK.read_text(encoding="utf-8").strip()
            pid = int(pid_txt) if pid_txt.isdigit() else 0
            if age < 7200 and pid and _pid_is_running(pid) and pid != __import__("os").getpid():
                return False
        except OSError:
            pass
    SHORT_WORKER_LOCK.write_text(str(__import__("os").getpid()), encoding="utf-8")
    return True


def release_service_lock() -> None:
    global _service_mutex_handle
    try:
        if SHORT_WORKER_LOCK.exists():
            SHORT_WORKER_LOCK.unlink()
    except OSError:
        pass
    if _service_mutex_handle and sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.CloseHandle(_service_mutex_handle)  # type: ignore[attr-defined]
        except Exception:
            pass
        _service_mutex_handle = None


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            kernel32.CloseHandle(handle)
            return True
        except Exception:
            return False
    try:
        import os

        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _connect_client():
    from etrade_api.client import ETradeClient
    from etrade_api.config import build_config, load_config
    from etrade_api.oauth import load_tokens

    raw = load_merged_short_config()
    try:
        key = str(raw.get("consumer_key") or "")
        secret = str(raw.get("consumer_secret") or "")
        token_path = Path(str(raw.get("token_path") or "etrade_tokens.json"))
        if not token_path.is_absolute():
            token_path = (ROOT / token_path).resolve()
        cfg = build_config(
            key,
            secret,
            sandbox=bool(raw.get("sandbox", True)),
            callback_url=str(raw.get("callback_url") or "http://127.0.0.1:8765/callback"),
            use_oob=bool(raw.get("use_oob", True)),
            config_path=SHORT_CONFIG if SHORT_CONFIG.exists() else ROOT / "etrade_config.json",
            token_path=token_path,
        )
    except Exception as exc:
        try:
            cfg = load_config(ROOT / "etrade_config.json")
            _log(f"Short config incomplete ({exc}); using long etrade_config.json.")
        except Exception as exc2:
            _log(f"Missing API credentials: {exc2}")
            return None

    tokens = load_tokens(cfg.token_path, cfg.sandbox)
    if not tokens:
        _log("No OAuth tokens — connect via Short Trader Settings or long ETrade Trader first.")
        return None
    try:
        return ETradeClient(cfg, tokens)
    except Exception as exc:
        _log(f"Client connect failed: {exc}")
        return None


def _resolve_account(client) -> dict[str, Any] | None:
    sel = get_selected_account()
    if sel and sel.get("account_id_key"):
        return sel
    try:
        accounts = client.list_accounts()
        if not accounts:
            return None
        acct = accounts[0]
        return {
            "account_id_key": acct.get("account_id_key") or acct.get("accountIdKey"),
            "display_label": acct.get("label") or acct.get("account_name") or "Account",
        }
    except Exception as exc:
        _log(f"Account resolve failed: {exc}")
        return None


def run_short_plan_cycle(*, force: bool = False, dry_run: bool | None = None) -> int:
    settings = worker_settings()
    if settings.get("paused"):
        _log("Paused — skip plan cycle.")
        return 0
    state = load_worker_state()
    plan_iv = int(settings.get("plan_interval_minutes", 30))
    if not _interval_due(state.get("last_plan_at"), plan_iv, force=force):
        _log("Short plan skipped — not due yet.")
        return 0

    client = _connect_client()
    if not client:
        return 1
    acct = _resolve_account(client)
    if not acct or not acct.get("account_id_key"):
        _log("No account selected.")
        return 1

    strat = load_short_strategy_settings()
    portfolio = generate_short_portfolio(notional_usd=None, settings=strat)
    # Fill notional after balance
    try:
        bal = client.get_balance(acct["account_id_key"])
        tv = float(bal.get("total_account_value") or 0)
        if tv > 0:
            portfolio = generate_short_portfolio(notional_usd=tv, settings=strat)
    except Exception:
        pass
    save_short_portfolio(portfolio)
    plan = build_short_strategy_plan(
        client,
        acct["account_id_key"],
        account_name=str(acct.get("display_label") or ""),
        portfolio=portfolio,
        settings=strat,
    )
    save_short_strategy_plan(plan)
    state["last_plan_at"] = time.time()
    state["last_plan_orders"] = len(plan.orders)
    save_worker_state(state)
    _log(f"Short plan built: {len(plan.orders)} order(s), {len(plan.target_holdings)} target short(s).")

    do_dry = settings.get("dry_run", True) if dry_run is None else dry_run
    live = bool(settings.get("live_trading")) and bool(settings.get("auto_execute")) and not do_dry
    market_ok = is_us_market_open() or bool(settings.get("allow_off_hours_trading"))
    exec_iv = int(settings.get("execute_min_interval_minutes", 20))
    if live and market_ok and _interval_due(state.get("last_execute_at"), exec_iv, force=force):
        if plan.orders:
            result = execute_short_orders(client, plan, dry_run=False, settings=strat)
            placed = sum(1 for o in result.orders if o.status not in {"error", "blocked", "skipped"})
            _log(f"Live short execute attempted for {placed} order(s).")
            state["last_execute_at"] = time.time()
            save_worker_state(state)
        else:
            _log("Short plan has no orders.")
    else:
        if plan.orders:
            preview_short_orders(client, plan)
            save_short_strategy_plan(plan)
            _log(
                f"Short orders previewed only "
                f"(dry_run={do_dry}, live={settings.get('live_trading')}, auto={settings.get('auto_execute')})."
            )
        else:
            _log("Short plan has no orders.")
    return 0


def run_short_day_cycle(*, force: bool = False) -> int:
    settings = worker_settings()
    day_settings = load_short_day_settings()
    if settings.get("paused") or not day_settings.get("enabled"):
        return 0
    if not settings.get("day_trading", True):
        return 0
    if not is_us_market_open() and not settings.get("allow_off_hours_trading"):
        return 0
    state = load_worker_state()
    iv = int(settings.get("day_trading_interval_minutes", 5))
    if not _interval_due(state.get("last_day_trade_at"), iv, force=force):
        return 0

    client = _connect_client()
    if not client:
        return 1
    acct = _resolve_account(client)
    if not acct or not acct.get("account_id_key"):
        return 1

    plan = build_short_day_trade_plan(
        client,
        acct["account_id_key"],
        account_name=str(acct.get("display_label") or ""),
        settings=day_settings,
    )
    state["last_day_trade_at"] = time.time()
    save_worker_state(state)
    _log(f"Short day plan: {len(plan.orders)} order(s).")

    do_dry = bool(settings.get("dry_run", True))
    live = bool(settings.get("live_trading")) and bool(settings.get("auto_execute")) and not do_dry
    if plan.orders and live:
        execute_short_orders(client, plan, dry_run=False)
        _log("Short day orders submitted (live).")
    elif plan.orders:
        preview_short_orders(client, plan)
        _log("Short day orders previewed (dry-run).")
    return 0


def run_service_loop() -> int:
    ensure_short_dirs()
    if not acquire_service_lock():
        _log("Short worker already running — exit.")
        return 0
    _log(f"Short worker service started (pid {__import__('os').getpid()}).")
    try:
        while True:
            try:
                settings = worker_settings()
                if settings.get("paused"):
                    _log("Service heartbeat — paused.")
                else:
                    run_short_plan_cycle()
                    run_short_day_cycle()
                    _log("Service heartbeat — sleeping 20s.")
            except Exception:
                _log("Cycle error:\n" + traceback.format_exc())
            time.sleep(20)
    finally:
        release_service_lock()
        _log("Short worker service stopped.")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ensure_short_dirs()
    if "--service" in argv:
        return run_service_loop()
    if "--day" in argv:
        return run_short_day_cycle(force=True)
    if "--plan" in argv or not argv:
        return run_short_plan_cycle(force=True)
    _log(f"Unknown args: {argv}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
