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
    """Connect via the **shared** long-app E*TRADE API (keys, sandbox, tokens)."""
    try:
        from shared_etrade_api import connect_shared_client, load_shared_api_config, mirror_shared_api_into_short

        mirror_shared_api_into_short()
        client = connect_shared_client()
        if client is None:
            cfg = load_shared_api_config()
            env = "sandbox" if cfg.sandbox else "production"
            _log(
                f"No OAuth tokens for shared API ({env}) — "
                "connect once via Unified/Long Settings (same API for short)."
            )
            return None
        env = "sandbox" if client.config.sandbox else "production"
        _log(f"Short sleeve using shared E*TRADE API ({env}).")
        return client
    except Exception as exc:
        _log(f"Shared API connect failed: {exc}")
        return None


def _resolve_account(client) -> dict[str, Any] | None:
    """Prefer shared selected_account from etrade_config.json."""
    try:
        from shared_etrade_api import get_shared_selected_account

        sel = get_shared_selected_account()
        if sel and sel.get("account_id_key"):
            return sel
    except Exception:
        pass
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
    # Practice mode: always simulate fills when we have orders (builds success-rate log).
    # Live: only during market hours (or allow_off_hours) and on execute cadence.
    should_exec = False
    if plan.orders:
        if do_dry:
            should_exec = True
        elif live and market_ok and _interval_due(state.get("last_execute_at"), exec_iv, force=force):
            should_exec = True

    if should_exec and plan.orders:
        result = execute_short_orders(client, plan, dry_run=do_dry, settings=strat)
        save_short_strategy_plan(result)
        placed = sum(1 for o in result.orders if o.status not in {"error", "blocked", "skipped"})
        mode = "DRY-RUN" if do_dry else "LIVE"
        _log(f"{mode} short execute: {placed} order(s) logged.")
        state["last_execute_at"] = time.time()
        save_worker_state(state)
    elif plan.orders:
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
    if plan.orders and (do_dry or live):
        execute_short_orders(client, plan, dry_run=do_dry)
        _log("Short day orders " + ("simulated (dry-run)." if do_dry else "submitted (live)."))
    elif plan.orders:
        preview_short_orders(client, plan)
        _log("Short day orders previewed only.")
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


def _yahoo_last(symbol: str) -> float:
    import urllib.request

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "FinanceShortDryRun/1.0"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        payload = json.loads(resp.read().decode())
    meta = ((payload.get("chart") or {}).get("result") or [{}])[0].get("meta") or {}
    return float(meta.get("regularMarketPrice") or meta.get("previousClose") or 0)


def run_forced_short_dry_run(*, max_names: int = 5) -> int:
    """Force a practice short cycle: 1-share sim orders + trade log + sim book.

    Works offline (Yahoo prices) when E*TRADE tokens are missing so we can still
    accumulate simulated success-rate data on small accounts.
    """
    from strategy_engine import StrategyPlan, TradeOrder

    strat = load_short_strategy_settings()
    strat = dict(strat)
    strat["min_trade_usd"] = min(float(strat.get("min_trade_usd") or 75), 5.0)
    strat["min_drift_pct"] = 0.0
    strat["force_min_share_dry_run"] = True
    strat["simulate_min_share"] = True
    strat["max_positions"] = max_names

    client = _connect_client()
    acct = _resolve_account(client) if client else None
    notional = None
    account_key = "SIM-DRY-RUN"
    account_name = "Simulated short (practice)"
    if acct and acct.get("account_id_key"):
        account_key = str(acct["account_id_key"])
        account_name = str(acct.get("display_label") or account_name)
        try:
            bal = client.get_balance(account_key)  # type: ignore[union-attr]
            notional = float(bal.get("total_account_value") or 0) or None
        except Exception as exc:
            _log(f"Balance fetch note: {exc}")

    if notional is None:
        # Prefer last known short plan equity, else a stable sim notional
        try:
            prev = json.loads((ROOT / "output" / "short" / "short_strategy_plan.json").read_text(encoding="utf-8"))
            notional = float(prev.get("total_account_value") or 0) or 1000.0
        except Exception:
            notional = 1000.0

    try:
        portfolio = generate_short_portfolio(notional_usd=notional, settings=strat)
    except Exception as exc:
        _log(f"Portfolio generate failed ({exc}); reusing last short_portfolio.json")
        from short_paths import SHORT_PORTFOLIO_FILE

        portfolio = {}
        if SHORT_PORTFOLIO_FILE.exists():
            try:
                portfolio = json.loads(SHORT_PORTFOLIO_FILE.read_text(encoding="utf-8"))
            except Exception:
                portfolio = {}
        if not isinstance(portfolio, dict):
            portfolio = {}
    holdings = list(portfolio.get("holdings") or [])[:max_names]
    portfolio["holdings"] = holdings
    if holdings:
        save_short_portfolio(portfolio)

    plan: StrategyPlan | None = None
    if client and acct and acct.get("account_id_key"):
        try:
            plan = build_short_strategy_plan(
                client,
                account_key,
                account_name=account_name,
                portfolio=portfolio,
                settings=strat,
            )
        except Exception as exc:
            _log(f"Live short plan failed ({exc}); synthesizing offline dry-run.")
            plan = None

    if plan is None or not plan.orders:
        synth: list[TradeOrder] = []
        for h in holdings:
            sym = str(h.get("symbol") or "").upper()
            if not sym:
                continue
            px = float(h.get("price") or 0)
            if px <= 0:
                try:
                    px = _yahoo_last(sym)
                except Exception as exc:
                    _log(f"Quote fail {sym}: {exc}")
                    px = 0.0
            if px <= 0:
                continue
            synth.append(
                TradeOrder(
                    symbol=sym,
                    action="SELL_SHORT",
                    quantity=1,
                    target_weight_pct=float(h.get("weight_pct") or 0),
                    current_weight_pct=0.0,
                    target_value_usd=px,
                    current_value_usd=0.0,
                    estimated_price=px,
                    status="dry_run",
                    message="Simulated short fill (offline practice)",
                    rationale=f"[sim 1-share forced] {h.get('rationale') or 'bearish target'}",
                )
            )
        plan = StrategyPlan(
            generated_at=datetime.now().astimezone().isoformat(),
            account_id_key=account_key,
            account_name=account_name,
            sandbox=True,
            total_account_value=float(notional or 0),
            investable_usd=float(notional or 0),
            cash_buffer_pct=float(strat.get("cash_buffer_pct") or 20),
            regime={},
            target_holdings=holdings,
            current_positions=[],
            orders=synth,
            meta={
                "mode": "short_swing",
                "side": "short",
                "forced_dry_run": True,
                "offline": client is None,
                "synthesized_orders": len(synth),
            },
        )

    # Ensure statuses for logging
    for order in plan.orders:
        if order.status in {"", None, "proposed", "previewed"}:
            order.status = "dry_run"
        if not order.message:
            order.message = "Simulated short fill (practice mode)"

    save_short_strategy_plan(plan)
    _log(f"Forced dry-run plan: {len(plan.orders)} order(s), {len(holdings)} target(s).")
    if not plan.orders:
        _log("Forced dry-run produced no orders — check portfolio / quotes.")
        return 1

    if client is not None:
        result = execute_short_orders(client, plan, dry_run=True, settings=strat)
    else:
        # Offline: log + sim book without broker
        from short_strategy_engine import _append_short_trade_log, _update_short_sim_book

        _append_short_trade_log(plan, dry_run=True)
        _update_short_sim_book(plan, dry_run=True)
        result = plan

    save_short_strategy_plan(result)
    placed = sum(1 for o in result.orders if o.status not in {"error", "blocked", "skipped"})
    _log(f"Forced DRY-RUN short execute: {placed} simulated fill(s) logged.")
    state = load_worker_state()
    state["last_plan_at"] = time.time()
    state["last_execute_at"] = time.time()
    state["last_forced_dry_run_at"] = time.time()
    state["last_plan_orders"] = len(result.orders)
    save_worker_state(state)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ensure_short_dirs()
    if "--service" in argv:
        return run_service_loop()
    if "--day" in argv:
        return run_short_day_cycle(force=True)
    if "--force-dry-run" in argv or "--sim" in argv:
        return run_forced_short_dry_run()
    if "--plan" in argv or not argv:
        return run_short_plan_cycle(force=True)
    _log(f"Unknown args: {argv}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
