#!/usr/bin/env python3
"""E*TRADE Short Trader — short-selling sleeve (standalone or embedded in unified UI)."""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from short_paths import (
    SHORT_APP_LOG,
    SHORT_APP_USER_MODEL_ID,
    SHORT_CONFIG,
    SHORT_CONFIG_EXAMPLE,
    SHORT_DAY_PLAN_FILE,
    SHORT_DAY_STATE_FILE,
    SHORT_ICON,
    SHORT_OUTPUT,
    SHORT_PLAN_FILE,
    SHORT_PORTFOLIO_FILE,
    SHORT_WORKER_LOG,
    SHORT_WORKER_STATE,
    ensure_short_dirs,
)

ensure_short_dirs()

from etrade_trader_gui import (  # noqa: E402
    ACCENT,
    ACCENT2,
    BG,
    BORDER,
    CARD_BG,
    DOWN,
    MUTED,
    PANEL,
    TEXT,
    UP,
    WARN,
    ETradeTraderApp,
    messagebox,
    tk,
    ttk,
)
from strategy_engine import StrategyPlan, plan_from_dict  # noqa: E402


def short_path_bundle() -> dict[str, Path]:
    return {
        "config": SHORT_CONFIG,
        "config_example": SHORT_CONFIG_EXAMPLE,
        "plan": SHORT_PLAN_FILE,
        "day_state": SHORT_DAY_STATE_FILE,
        "day_plan": SHORT_DAY_PLAN_FILE,
        "app_log": SHORT_APP_LOG,
        "worker_log": SHORT_WORKER_LOG,
    }


def _log_crash(msg: str) -> None:
    ensure_short_dirs()
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with SHORT_APP_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] {msg}\n")


def _apply_short_identity() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(SHORT_APP_USER_MODEL_ID)
    except Exception:
        pass


def _ensure_short_config_seeded() -> None:
    from short_config import ensure_short_config, load_merged_short_config, write_short_config_raw

    ensure_short_config()
    merged = load_merged_short_config()
    if not SHORT_CONFIG.exists() or not merged.get("consumer_key"):
        return
    raw: dict[str, Any] = {}
    try:
        raw = json.loads(SHORT_CONFIG.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        raw = {}
    changed = False
    for key in ("consumer_key", "consumer_secret", "token_path", "callback_url", "use_oob", "sandbox"):
        if (not raw.get(key) or str(raw.get(key, "")).startswith("YOUR_")) and merged.get(key) is not None:
            raw[key] = merged[key]
            changed = True
    if not (raw.get("selected_account") or {}).get("account_id_key"):
        sel = merged.get("selected_account")
        if isinstance(sel, dict) and sel.get("account_id_key"):
            raw["selected_account"] = sel
            changed = True
    raw.setdefault("inherit_credentials_from", "etrade_config.json")
    raw.setdefault(
        "background_worker",
        merged.get("background_worker")
        or {
            "auto_execute": False,
            "live_trading": False,
            "day_trading": True,
            "paused": False,
            "dry_run": True,
        },
    )
    raw.setdefault("short_strategy", merged.get("short_strategy") or {})
    raw.setdefault("short_day_trading", merged.get("short_day_trading") or {})
    if changed or not SHORT_CONFIG.exists():
        write_short_config_raw(raw)


class ShortTraderApp(ETradeTraderApp):
    """Short-selling sleeve UI — isolated config/plan paths from the long sleeve."""

    def __init__(
        self,
        parent: tk.Misc | None = None,
        *,
        embedded: bool = False,
        manage_window_close: bool = True,
    ) -> None:
        _ensure_short_config_seeded()
        super().__init__(
            parent,
            path_bundle=short_path_bundle(),
            embedded=embedded,
            app_title="E*TRADE Short Trader — Finance Agents",
            layout_key="etrade_short_trader",
            manage_window_close=manage_window_close and not embedded,
        )
        self._relabel_for_short()
        if not embedded:
            self._force_midnight_branding()
        try:
            raw = json.loads(SHORT_CONFIG.read_text(encoding="utf-8")) if SHORT_CONFIG.exists() else {}
            worker = raw.get("background_worker") or {}
            if "dry_run" not in worker:
                self._dry_run_var.set(True)
            if "auto_execute" not in worker:
                self._auto_execute_var.set(False)
        except Exception:
            self._dry_run_var.set(True)
            self._auto_execute_var.set(False)
        self._update_automation_control_ui()
        self._update_bg_status()

    def _apply_window_icons(self) -> None:
        if self._embedded:
            return
        icon = SHORT_ICON if SHORT_ICON.exists() else None
        if icon is None:
            try:
                from create_short_app_icon import main as build_short_icon

                build_short_icon()
            except Exception:
                pass
            icon = SHORT_ICON if SHORT_ICON.exists() else None
        if icon is not None and icon.exists():
            try:
                self._window.iconbitmap(str(icon))
                return
            except tk.TclError:
                pass
        super()._apply_window_icons()

    def _force_midnight_branding(self) -> None:
        try:
            from gui_theme import (
                BG,
                apply_palette,
                build_color_remap,
                current_palette_name,
                refresh_trader_theme,
                sync_module_globals,
            )

            previous = current_palette_name()
            apply_palette("midnight")
            sync_module_globals(sys.modules[__name__])
            import etrade_trader_gui as long_gui

            sync_module_globals(sys.modules[long_gui.__name__])
            self._window.configure(bg=BG)
            self.configure(bg=BG)
            self._build_styles()
            if previous != "midnight":
                color_map = build_color_remap(previous, "midnight")
                refresh_trader_theme(
                    self._window,
                    ttk.Style(self._window),
                    self._m,
                    color_map=color_map,
                )
            if hasattr(self, "_sync_palette_buttons"):
                self._sync_palette_buttons()
            if hasattr(self, "_balance_growth_chart") and hasattr(self._balance_growth_chart, "apply_theme"):
                self._balance_growth_chart.apply_theme()
            if self._finance_agents is not None and hasattr(self._finance_agents, "refresh_theme"):
                try:
                    self._finance_agents.refresh_theme(previous)
                except Exception:
                    pass
        except Exception as exc:
            self._log_line(f"Midnight theme apply note: {exc}")
        self._apply_window_icons()

    def _relabel_for_short(self) -> None:
        if not self._embedded:
            self._window.title("E*TRADE Short Trader — Finance Agents")
        self._retitle_labels(
            self,
            {
                "E*TRADE Trader": "E*TRADE Short Trader",
                "Agent research · automated swing & day trading": (
                    "Bearish research · automated short swing & day covers"
                ),
                "Your trading dashboard": "Your short-trading dashboard",
                "How do you want to trade?": "How do you want to short?",
                "Swing investing": "Swing shorting",
                "Automatically place swing trades": "Automatically place swing shorts",
                "Day trading": "Day shorting",
                "Enable day trading": "Enable day shorting",
                "Pending trades": "Pending shorts",
            },
        )
        try:
            self._trades_notebook.tab(self._tab_holdings, text="  Short book  ")
            self._orders_notebook.tab(self._tab_swing_orders, text="  Swing short  ")
            self._orders_notebook.tab(self._tab_day_orders, text="  Day short  ")
        except (tk.TclError, AttributeError):
            pass

    def _retitle_labels(self, root: tk.Misc, mapping: dict[str, str]) -> None:
        try:
            if isinstance(root, tk.Label):
                text = root.cget("text")
                if text in mapping:
                    root.configure(text=mapping[text])
            for child in root.winfo_children():
                self._retitle_labels(child, mapping)
        except tk.TclError:
            pass

    def _worker_settings(self) -> dict[str, Any]:
        try:
            from short_config import worker_settings

            return worker_settings(SHORT_CONFIG)
        except Exception:
            return super()._worker_settings()

    def _gui_should_defer_to_worker(self) -> bool:
        try:
            if SHORT_WORKER_LOG.exists() and (time.time() - SHORT_WORKER_LOG.stat().st_mtime) < 900:
                return True
            from short_config import worker_settings

            return bool(worker_settings(SHORT_CONFIG).get("gui_defer_to_worker", True))
        except Exception:
            return False

    def _sync_status_from_worker(self) -> bool:
        try:
            if SHORT_WORKER_STATE.exists():
                state = json.loads(SHORT_WORKER_STATE.read_text(encoding="utf-8"))
                for key, attr in (
                    ("last_pipeline_at", "_last_pipeline_at"),
                    ("last_plan_at", "_last_plan_at"),
                    ("last_execute_at", "_last_execute_at"),
                    ("last_day_trade_at", "_last_day_trade_at"),
                ):
                    val = state.get(key)
                    if val:
                        setattr(self, attr, float(val))
            if SHORT_WORKER_LOG.exists():
                return (time.time() - SHORT_WORKER_LOG.stat().st_mtime) < 120
        except Exception:
            pass
        return False

    def _poll_worker_status(self) -> None:
        self._sync_status_from_worker()
        worker_active = False
        try:
            if SHORT_WORKER_LOG.exists():
                worker_active = (time.time() - SHORT_WORKER_LOG.stat().st_mtime) < 120
            if SHORT_WORKER_STATE.exists():
                state = json.loads(SHORT_WORKER_STATE.read_text(encoding="utf-8"))
                self._worker_pipeline_progress = str(state.get("pipeline_progress") or "")
                if state.get("pipeline_active"):
                    worker_active = True
        except Exception:
            self._worker_pipeline_progress = ""
        self._bg_pipeline_running = worker_active
        self._bg_day_trading_running = worker_active
        if SHORT_PLAN_FILE.exists():
            try:
                mtime = SHORT_PLAN_FILE.stat().st_mtime
                if mtime != self._cached_plan_mtime:
                    self._cached_plan_mtime = mtime
                    data = json.loads(SHORT_PLAN_FILE.read_text(encoding="utf-8"))
                    if data:
                        self._plan = plan_from_dict(data)
                        self._render_plan(self._plan, focus_orders_tab=False)
            except Exception:
                pass
        self._update_bg_status()

    def _load_trading_settings_from_config(self) -> None:
        raw = json.loads(SHORT_CONFIG.read_text(encoding="utf-8")) if SHORT_CONFIG.exists() else {}
        worker = raw.get("background_worker", {})
        if "auto_execute" in worker:
            self._auto_execute_var.set(bool(worker["auto_execute"]))
        if "day_trading" in worker:
            self._day_trading_var.set(bool(worker["day_trading"]))
        if "dry_run" in worker:
            self._dry_run_var.set(bool(worker["dry_run"]))
        else:
            self._dry_run_var.set(True)
        self._automation_paused = bool(worker.get("paused", False))
        self._gui_defers_to_worker = self._gui_should_defer_to_worker()

    def _persist_trading_settings(self) -> None:
        raw = json.loads(SHORT_CONFIG.read_text(encoding="utf-8")) if SHORT_CONFIG.exists() else {}
        worker = dict(raw.get("background_worker") or {})
        auto = bool(self._auto_execute_var.get())
        day = bool(self._day_trading_var.get())
        dry = bool(self._dry_run_var.get())
        worker["auto_execute"] = auto
        worker["day_trading"] = day
        worker["dry_run"] = dry
        worker["live_trading"] = auto and not dry
        worker["paused"] = bool(self._automation_paused)
        raw["background_worker"] = worker
        day_cfg = dict(raw.get("short_day_trading") or {})
        day_cfg["enabled"] = day and not self._automation_paused
        raw["short_day_trading"] = day_cfg
        try:
            SHORT_CONFIG.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _plan_worker(self, acct: dict[str, Any], *, background: bool = True) -> None:
        try:
            if background:
                self._schedule(self._update_bg_status)
            else:
                self._schedule(self._set_status, "Building short strategy plan…", WARN)
            from short_portfolio import (
                generate_short_portfolio,
                load_short_strategy_settings,
                save_short_portfolio,
            )
            from short_strategy_engine import build_short_strategy_plan, save_short_strategy_plan

            balance = self._client.get_balance(acct["account_id_key"])
            notional = balance.get("total_account_value") or None
            settings = load_short_strategy_settings(SHORT_CONFIG)
            portfolio = generate_short_portfolio(notional_usd=notional, settings=settings)
            save_short_portfolio(portfolio)
            plan = build_short_strategy_plan(
                self._client,
                acct["account_id_key"],
                acct.get("account_name", "") or acct.get("display_label", ""),
                portfolio=portfolio,
                settings=settings,
            )
            save_short_strategy_plan(plan)
            self._plan = plan
            self._last_plan_at = time.time()
            self._schedule(self._render_plan, plan, not background)
            self._schedule(self._set_status, f"Short plan ready — {len(plan.orders)} orders", UP)
            prefix = "[bg] " if background else ""
            self._schedule(
                self._log_line,
                f"{prefix}Short strategy plan: {len(plan.orders)} proposed SELL_SHORT/BUY_TO_COVER.",
            )
            if background and plan.orders and not self._shutting_down:
                self._schedule(self._trigger_auto_execute, plan)
        except Exception as exc:
            if background:
                self._schedule(self._log_line, f"[bg] Short plan error: {exc}")
            else:
                self._schedule(messagebox.showerror, "Short Plan Error", str(exc))
        finally:
            self._bg_plan_running = False
            self._schedule(self._update_bg_status)
            self._schedule(self._schedule_background_plan)

    def _execute_plan_worker(self, plan: StrategyPlan, *, background: bool = True, force: bool = False) -> None:
        try:
            if background and not force and not self._should_auto_execute(plan):
                return
            dry_run = self._dry_run_var.get()
            from short_portfolio import load_short_strategy_settings
            from short_strategy_engine import (
                execute_short_orders,
                preview_short_orders,
                save_short_strategy_plan,
            )

            settings = load_short_strategy_settings(SHORT_CONFIG)
            preview_short_orders(self._client, plan)
            previewed = sum(1 for o in plan.orders if o.status == "previewed")
            if previewed == 0:
                self._schedule(self._set_status, "No valid short orders to execute", WARN)
                return
            execute_short_orders(self._client, plan, dry_run=dry_run, settings=settings)
            save_short_strategy_plan(plan)
            self._plan = plan
            self._last_execute_at = time.time()
            placed = sum(1 for o in plan.orders if o.status in {"placed", "dry_run", "previewed"})
            self._schedule(self._render_plan, plan, False)
            msg = f"Dry run — simulated {placed} short orders" if dry_run else f"Submitted {placed} short orders"
            self._schedule(self._set_status, msg, ACCENT2 if dry_run else UP)
            self._schedule(self._log_line, msg)
            self._schedule(self._refresh_account, silent=True)
        except Exception as exc:
            self._schedule(self._log_line, f"Short execute error: {exc}")
        finally:
            self._bg_execute_running = False
            if not background:
                self._schedule(self._set_busy, False)
            self._schedule(self._update_bg_status)

    def _day_trading_background_worker(self) -> None:
        try:
            from short_worker import run_short_day_cycle

            run_short_day_cycle(force=False)
            self._schedule(self._refresh_day_trading_panel)
            self._schedule(self._log_line, "[bg] Day short cycle complete.")
        except Exception as exc:
            self._schedule(self._log_line, f"[bg] Day short error: {exc}")
        finally:
            self._bg_day_trading_running = False
            self._schedule(self._schedule_background_day_trading)

    def _pipeline_worker(self, *, background: bool = True) -> None:
        try:
            self._schedule(
                self._log_line,
                "[bg] Short sleeve reuses shared agent research in output/.",
            )
            self._last_pipeline_at = time.time()
            self._schedule(self._refresh_reports_ui, select_latest=True)
        except Exception as exc:
            self._schedule(self._log_line, f"[bg] Pipeline note: {exc}")
        finally:
            self._bg_pipeline_running = False
            self._schedule(self._update_bg_status)
            self._schedule(self._schedule_background_pipeline)


def main() -> int:
    try:
        _apply_short_identity()
        _ensure_short_config_seeded()
        app = ShortTraderApp()
        if os.environ.get("ETRADE_TAB", "").lower() in {"agents", "finance-agents"}:
            app._window.after(200, app._select_agents_tab)
        app._window.mainloop()
    except Exception as exc:
        _log_crash(f"Fatal error: {exc}\n{traceback.format_exc()}")
        try:
            messagebox.showerror(
                "E*TRADE Short Trader",
                f"The app closed due to an error:\n\n{exc}\n\nDetails: {SHORT_APP_LOG}",
            )
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
