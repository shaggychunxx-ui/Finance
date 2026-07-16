#!/usr/bin/env python3
"""E*TRADE Short Trader — same UI shell as the long trader, short-selling backend."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

# Ensure project root imports resolve before long-gui import.
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

# ---------------------------------------------------------------------------
# Import long GUI and redirect its paths to the short sister-app surface.
# This keeps layout/theme/widgets identical while isolating short state.
# ---------------------------------------------------------------------------
import etrade_trader_gui as long_gui  # noqa: E402

long_gui.CONFIG_PATH = SHORT_CONFIG
long_gui.CONFIG_EXAMPLE = SHORT_CONFIG_EXAMPLE
long_gui.APP_LOG = SHORT_APP_LOG
long_gui.WORKER_LOG = SHORT_WORKER_LOG
long_gui.PLAN_FILE = SHORT_PLAN_FILE
long_gui.DAY_STATE_FILE = SHORT_DAY_STATE_FILE
long_gui.DAY_PLAN_FILE = SHORT_DAY_PLAN_FILE

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
    # Materialize inherited credentials so the shared Settings form works offline.
    merged = load_merged_short_config()
    if not SHORT_CONFIG.exists() or not merged.get("consumer_key"):
        return
    raw = {}
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
    raw.setdefault("background_worker", merged.get("background_worker") or {
        "auto_execute": False,
        "live_trading": False,
        "day_trading": True,
        "paused": False,
        "dry_run": True,
    })
    raw.setdefault("short_strategy", merged.get("short_strategy") or {})
    raw.setdefault("short_day_trading", merged.get("short_day_trading") or {})
    if changed or not SHORT_CONFIG.exists():
        write_short_config_raw(raw)


class ShortTraderApp(ETradeTraderApp):
    """Pixel-matched sister UI; short book, SELL_SHORT / BUY_TO_COVER execution."""

    def __init__(self, parent: tk.Misc | None = None) -> None:
        _ensure_short_config_seeded()
        super().__init__(parent)
        self._relabel_for_short()
        self._force_midnight_branding()
        # Prefer dry-run / no auto-execute defaults for shorts if first launch
        try:
            raw = long_gui._read_config_file(SHORT_CONFIG)
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
        """Use dedicated midnight Short Trader .ico (not the long-app icon)."""
        icon = SHORT_ICON if SHORT_ICON.exists() else None
        if icon is None:
            # Best-effort generate on first launch
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
        """Lock Short Trader visuals to the Midnight palette without rewriting long-app prefs."""
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
            sync_module_globals(sys.modules[long_gui.__name__])
            sync_module_globals(sys.modules[__name__])
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

    # ------------------------------------------------------------------ UI copy
    def _relabel_for_short(self) -> None:
        self._window.title("E*TRADE Short Trader — Finance Agents")
        # Header title + subtitle (first title labels in the root frame tree)
        self._retitle_labels(self, {
            "E*TRADE Trader": "E*TRADE Short Trader",
            "Agent research · automated swing & day trading": (
                "Bearish research · automated short swing & day covers"
            ),
            "Your trading dashboard": "Your short-trading dashboard",
            "Everything runs automatically in the background. Use Stop all when you want everything to halt.": (
                "Short book, covers, and day shorts run in the background. "
                "Use Stop all to halt. Defaults keep dry-run on until you opt in."
            ),
            "How do you want to trade?": "How do you want to short?",
            "Swing investing": "Swing shorting",
            "Agents choose all stocks — swing trades follow the agent portfolio. Strategy updates every 30 minutes.": (
                "Agents pick bearish / weakest names — SELL_SHORT toward the short book. "
                "Plan rebuilds about every 30 minutes."
            ),
            "Automatically place swing trades": "Automatically place swing shorts",
            "Day trading": "Day shorting",
            "Shorter trades on agent portfolio picks. Runs automatically every 5 minutes "
            "(in this app and when closed via the background worker). Closes positions same day.": (
                "Intraday SELL_SHORT on 24h down signals. Covers same day; flattens before the close."
            ),
            "Enable day trading": "Enable day shorting",
            "Practice mode — dry run only (no real orders sent to E*TRADE)": (
                "Practice mode — dry run only (no real short/cover orders sent to E*TRADE)"
            ),
            "Agents, strategy, swing orders, and day trading run automatically in the background.": (
                "Agents, short plan, SELL_SHORT / BUY_TO_COVER, and day shorts run in the background."
            ),
            "Pending trades": "Pending shorts",
            "Settings & setup": "Short Trader settings",
            "Connect your E*TRADE account in four steps. Start in Sandbox (paper money) to test safely before going live.": (
                "Same E*TRADE connection as the long app (shared tokens by default). "
                "Start in Sandbox and keep dry-run on until short/borrow previews succeed."
            ),
            "You're ready to trade": "You're ready to short",
            "Agents and strategy plan update automatically. Use Preview → Execute when ready to trade.": (
                "Short book rebuilds from bearish agent scores. Preview → Execute for SELL_SHORT / BUY_TO_COVER."
            ),
            "Portfolio vs agent targets — select a row for analysis →": (
                "Short book vs bearish agent targets — select a row for analysis →"
            ),
            "Swing rebalance orders — select a row for analysis →": (
                "Swing short / cover orders — select a row for analysis →"
            ),
            "Day trades": "Day shorts",
            "Open today": "Open short today",
            "Turn on day trading on the Home tab.": "Turn on day shorting on the Home tab.",
            "Select a row in Holdings or Orders to see agent reasoning and a 10-day chart.": (
                "Select a row in Short book or Orders to see agent reasoning and a 10-day chart."
            ),
        })
        # Notebook tabs
        try:
            self._notebook.tab(self._tab_dashboard, text="  Home  ")
            self._notebook.tab(self._tab_agents, text="  Agents  ")
            self._notebook.tab(self._tab_trades, text="  Trades  ")
            self._notebook.tab(self._tab_setup, text="  Settings  ")
            self._notebook.tab(self._tab_log, text="  Activity  ")
        except tk.TclError:
            pass
        try:
            self._trades_notebook.tab(self._tab_overview, text="  Overview  ")
            self._trades_notebook.tab(self._tab_holdings, text="  Short book  ")
            self._trades_notebook.tab(self._tab_orders, text="  Orders  ")
            self._trades_notebook.tab(self._tab_performance, text="  Performance  ")
        except (tk.TclError, AttributeError):
            pass
        try:
            self._orders_notebook.tab(self._tab_swing_orders, text="  Swing short  ")
            self._orders_notebook.tab(self._tab_day_orders, text="  Day short  ")
        except (tk.TclError, AttributeError):
            pass
        # Automation chips
        for chip, title in (
            (getattr(self, "_bg_agents_label", None), None),
        ):
            del chip, title  # chips are value labels; retitle via parent frames
        self._retitle_chip_headers({
            "RESEARCH AGENTS": "RESEARCH AGENTS",
            "SWING STRATEGY": "SHORT STRATEGY",
            "SWING ORDERS": "SHORT ORDERS",
            "DAY TRADING": "DAY SHORTS",
        })
        # Welcome activity log (clear long-app defaults if still present)
        try:
            self._log.delete("1.0", tk.END)
            from datetime import datetime

            ts = datetime.now().strftime("%H:%M:%S")
            for msg in (
                "Welcome to Short Trader — same UI as the long app, short-selling backend.",
                "Home: toggle swing shorts, day shorts, and practice (dry-run) mode.",
                "Trades → Short book / Orders: review SELL_SHORT and BUY_TO_COVER plans.",
                "Keeps running when closed: run Install ETrade Short Background.bat once.",
                f"Isolated output: {SHORT_OUTPUT}",
            ):
                self._log.insert(tk.END, f"[{ts}] {msg}\n")
        except tk.TclError:
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

    def _retitle_chip_headers(self, mapping: dict[str, str]) -> None:
        """Rename the small bold titles above automation status chips."""
        try:
            for widget in self.winfo_children():
                self._walk_chip_headers(widget, mapping)
        except tk.TclError:
            pass

    def _walk_chip_headers(self, root: tk.Misc, mapping: dict[str, str]) -> None:
        try:
            if isinstance(root, tk.Label):
                text = root.cget("text")
                if text in mapping:
                    root.configure(text=mapping[text])
            for child in root.winfo_children():
                self._walk_chip_headers(child, mapping)
        except tk.TclError:
            pass

    # -------------------------------------------------------------- worker I/O
    def _worker_settings(self) -> dict[str, Any]:
        try:
            from short_config import worker_settings

            return worker_settings(SHORT_CONFIG)
        except Exception:
            return super()._worker_settings()

    def _gui_should_defer_to_worker(self) -> bool:
        try:
            # Defer when short worker log is fresh
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
                self._worker_pipeline_stuck = False
                if state.get("pipeline_active"):
                    worker_active = True
        except Exception:
            self._worker_pipeline_progress = ""
            self._worker_pipeline_stuck = False
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

        polls_per_refresh = max(
            1,
            self._day_panel_refresh_ms() // self._bg_status_poll_delay_ms(),
        )
        self._day_poll_counter += 1
        if self._day_poll_counter >= polls_per_refresh:
            self._day_poll_counter = 0
            self._refresh_day_trading_panel()
        self._update_bg_status()

    def _load_trading_settings_from_config(self) -> None:
        raw = long_gui._read_config_file(SHORT_CONFIG)
        worker = raw.get("background_worker", {})
        if "auto_execute" in worker:
            self._auto_execute_var.set(bool(worker["auto_execute"]))
        if "day_trading" in worker:
            self._day_trading_var.set(bool(worker["day_trading"]))
        else:
            day_cfg = raw.get("short_day_trading", {})
            if isinstance(day_cfg, dict) and "enabled" in day_cfg:
                self._day_trading_var.set(bool(day_cfg["enabled"]))
        if "dry_run" in worker:
            self._dry_run_var.set(bool(worker["dry_run"]))
        else:
            self._dry_run_var.set(True)
        self._automation_paused = bool(worker.get("paused", False))
        self._gui_defers_to_worker = self._gui_should_defer_to_worker()

    def _persist_trading_settings(self) -> None:
        """Write Home-tab toggles into short_etrade_config.json."""
        raw = long_gui._read_config_file(SHORT_CONFIG)
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
            long_gui._write_config_file(SHORT_CONFIG, raw)
        except OSError:
            pass

    def _set_short_automation_paused(self, paused: bool) -> None:
        raw = long_gui._read_config_file(SHORT_CONFIG)
        worker = dict(raw.get("background_worker") or {})
        worker["paused"] = paused
        if paused:
            worker["auto_execute"] = False
            worker["day_trading"] = False
            worker["live_trading"] = False
        else:
            worker["auto_execute"] = True
            worker["day_trading"] = True
            dry = bool(worker.get("dry_run", True))
            worker["live_trading"] = not dry
        raw["background_worker"] = worker
        day_cfg = dict(raw.get("short_day_trading") or {})
        day_cfg["enabled"] = not paused
        raw["short_day_trading"] = day_cfg
        long_gui._write_config_file(SHORT_CONFIG, raw)

    def _stop_all_automation(self) -> None:
        if not messagebox.askyesno(
            "Stop all",
            "Stop all Short Trader background automation?\n\n"
            "This halts short plans, swing shorts, and day shorts "
            "in this app and the short headless worker until you resume.",
        ):
            return
        self._cancel_background_schedules()
        self._set_short_automation_paused(True)
        self._load_trading_settings_from_config()
        self._refresh_automation_snapshot()
        self._apply_automation_ui_state()
        self._log_line("All short automation stopped.")
        self._set_status("All short automation stopped", WARN)

    def _resume_all_automation(self) -> None:
        self._set_short_automation_paused(False)
        self._load_trading_settings_from_config()
        self._refresh_automation_snapshot()
        self._apply_automation_ui_state()
        self._log_line("Short automation resumed — plan, swing shorts, and day shorts re-enabled.")
        self._set_status("Short automation resumed", UP)
        self._apply_automation_running_state()

    def _update_automation_control_ui(self) -> None:
        super()._update_automation_control_ui()
        if not hasattr(self, "_automation_status_label"):
            return
        if self._automation_paused:
            return
        if self._gui_defers_to_worker:
            hint = (
                "Low-CPU mode — the short headless worker runs automation; this window only shows status."
            )
        else:
            hint = (
                "Agents, short plan, SELL_SHORT / BUY_TO_COVER, and day shorts run in the background."
            )
        try:
            self._automation_status_label.configure(text=hint, fg=MUTED)
        except tk.TclError:
            pass

    # ----------------------------------------------------------- plan / orders
    def _load_cached_plan(self) -> None:
        if not SHORT_PLAN_FILE.exists():
            return
        try:
            data = json.loads(SHORT_PLAN_FILE.read_text(encoding="utf-8"))
            self._plan = plan_from_dict(data)
            self._render_plan(self._plan, focus_orders_tab=False)
            self._log_line("Loaded cached short strategy plan.")
        except Exception as exc:
            self._log_line(f"Could not load cached short plan: {exc}")

    def _portfolio_holdings_map(self) -> dict[str, dict[str, Any]]:
        try:
            if SHORT_PORTFOLIO_FILE.exists():
                data = json.loads(SHORT_PORTFOLIO_FILE.read_text(encoding="utf-8"))
                return {
                    str(h.get("symbol", "")).upper(): h
                    for h in (data.get("holdings") or [])
                    if h.get("symbol")
                }
        except Exception:
            pass
        return super()._portfolio_holdings_map()

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
                self._schedule(self._set_status, f"Background short plan error: {exc}", DOWN)
            else:
                self._schedule(messagebox.showerror, "Short Plan Error", str(exc))
                self._schedule(self._set_status, str(exc), DOWN)
        finally:
            self._bg_plan_running = False
            self._schedule(self._update_bg_status)
            self._schedule(self._schedule_background_plan)

    def _execute_plan_worker(self, plan: StrategyPlan, *, background: bool = True, force: bool = False) -> None:
        try:
            if background and not force and not self._should_auto_execute(plan):
                return
            dry_run = self._dry_run_var.get()
            prefix = "[bg] " if background else ""
            self._schedule(
                self._set_status,
                f"{'Simulating' if dry_run else 'Submitting'} {len(plan.orders)} short orders…",
                WARN,
            )
            self._schedule(self._log_line, f"{prefix}Previewing {len(plan.orders)} short orders with E*TRADE…")

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
                self._schedule(self._log_line, f"{prefix}No short orders passed preview.")
                self._schedule(self._set_status, "No valid short orders to execute", WARN)
                return

            execute_short_orders(self._client, plan, dry_run=dry_run, settings=settings)
            save_short_strategy_plan(plan)
            self._plan = plan
            self._last_executed_plan_sig = self._plan_order_signature(plan)
            self._last_execute_at = time.time()

            placed = sum(1 for o in plan.orders if o.status in {"placed", "dry_run", "previewed"})
            self._schedule(self._render_plan, plan, False)
            if dry_run:
                self._schedule(self._set_status, f"Dry run — simulated {placed} short orders", ACCENT2)
                self._schedule(self._log_line, f"{prefix}Short dry run complete — {placed} orders simulated.")
            else:
                self._schedule(self._set_status, f"Submitted {placed} short orders to E*TRADE", UP)
                self._schedule(self._log_line, f"{prefix}Short orders placed: {placed}")
                if self._config and not self._config.sandbox:
                    self._schedule(self._log_line, f"{prefix}PRODUCTION — live short trades submitted.")
            self._schedule(self._refresh_account, silent=True)
        except Exception as exc:
            if background:
                self._schedule(self._log_line, f"[bg] Short execute error: {exc}")
                self._schedule(self._set_status, f"Auto-execute error: {exc}", DOWN)
            else:
                self._schedule(messagebox.showerror, "Execute Error", str(exc))
                self._schedule(self._set_status, str(exc), DOWN)
        finally:
            self._bg_execute_running = False
            if not background:
                self._schedule(self._set_busy, False)
            self._schedule(self._update_bg_status)

    def _preview_thread(self) -> None:
        try:
            from short_strategy_engine import preview_short_orders, save_short_strategy_plan

            preview_short_orders(self._client, self._plan)
            save_short_strategy_plan(self._plan)
            self._schedule(self._render_plan, self._plan)
            ok = sum(1 for o in self._plan.orders if o.status == "previewed")
            self._schedule(self._set_status, f"Previewed {ok}/{len(self._plan.orders)} short orders", UP)
            self._schedule(self._log_line, f"E*TRADE short preview: {ok} orders validated.")
        except Exception as exc:
            self._schedule(messagebox.showerror, "Preview Error", str(exc))
        finally:
            self._schedule(self._set_busy, False)

    def _render_plan(self, plan: StrategyPlan, focus_orders_tab: bool = True) -> None:
        super()._render_plan(plan, focus_orders_tab=focus_orders_tab)
        # Color SELL_SHORT as sell (red) and BUY_TO_COVER as buy (green)
        try:
            for item in self._orders_tree.get_children():
                vals = self._orders_tree.item(item, "values")
                if not vals or len(vals) < 2:
                    continue
                action = str(vals[1]).upper()
                tags = list(self._orders_tree.item(item, "tags") or ())
                tags = [t for t in tags if t not in {"buy", "sell"}]
                if action == "SELL_SHORT":
                    tags.append("sell")
                elif action == "BUY_TO_COVER":
                    tags.append("buy")
                self._orders_tree.item(item, tags=tuple(tags))
        except tk.TclError:
            pass

    def _day_trade_scan_worker(self) -> None:
        try:
            from short_day_trader import build_short_day_trade_plan, load_short_day_settings, load_short_day_state
            from short_strategy_engine import execute_short_orders, preview_short_orders, save_short_strategy_plan

            acct = self._selected_account()
            if not acct or not self._client:
                return
            settings = load_short_day_settings(SHORT_CONFIG)
            state = load_short_day_state()
            plan = build_short_day_trade_plan(
                self._client,
                acct["account_id_key"],
                acct.get("account_name", "") or acct.get("display_label", ""),
                settings=settings,
                state=state,
            )
            self._schedule(self._refresh_day_trading_panel)
            n = len(plan.orders)
            self._schedule(self._log_line, f"Day short scan: {n} proposed intraday order(s).")
            self._schedule(self._set_status, f"Day short scan — {n} order(s)", UP if n else ACCENT2)

            # Populate day orders tree via refresh panel; also preview if requested path
            if n:
                try:
                    if self._dry_run_var.get() or not self._auto_execute_var.get():
                        preview_short_orders(self._client, plan)
                    else:
                        execute_short_orders(self._client, plan, dry_run=False)
                    save_short_strategy_plan(plan)
                except Exception as exc:
                    self._schedule(self._log_line, f"Day short order step: {exc}")
        except Exception as exc:
            self._schedule(messagebox.showerror, "Day Short Scan", str(exc))
            self._schedule(self._log_line, f"Day short scan error: {exc}")
        finally:
            self._schedule(self._set_busy, False)

    def _read_day_state(self) -> dict[str, Any]:
        try:
            from short_day_trader import load_short_day_state

            return load_short_day_state()
        except Exception:
            return {}

    def _pipeline_worker(self, *, background: bool = True) -> None:
        """Short app reuses long-agent research; only refresh UI, don't run long pipeline here."""
        try:
            prefix = "[bg] " if background else ""
            self._schedule(
                self._log_line,
                f"{prefix}Short Trader reuses agent research from the long app output/ folder.",
            )
            self._last_pipeline_at = time.time()
            self._schedule(self._refresh_reports_ui, select_latest=True)
            self._schedule(self._set_status, "Agent research ready for short book", UP)
        except Exception as exc:
            self._schedule(self._log_line, f"[bg] Pipeline note: {exc}")
        finally:
            self._bg_pipeline_running = False
            self._schedule(self._update_bg_status)
            self._schedule(self._schedule_background_pipeline)

    def _day_trading_background_worker(self) -> None:
        try:
            from short_worker import run_short_day_cycle

            code = run_short_day_cycle(force=False)
            self._schedule(self._refresh_day_trading_panel)
            self._schedule(self._update_bg_status)
            if code == 0:
                self._schedule(self._log_line, "[bg] Day short cycle complete.")
            else:
                self._schedule(self._log_line, "[bg] Day short cycle returned error.")
        except Exception as exc:
            self._schedule(self._log_line, f"[bg] Day short error: {exc}")
        finally:
            self._bg_day_trading_running = False
            self._schedule(self._schedule_background_day_trading)

    def _start_background_engine(self) -> None:
        if self._shutting_down or self._automation_paused:
            if self._automation_paused:
                self._log_line("Automation is paused — click Resume all on Home to restart.")
                self._update_bg_status()
            return
        self._gui_defers_to_worker = self._gui_should_defer_to_worker()
        ws = self._worker_settings()
        day_on = "on" if self._day_trading_var.get() else "off"
        if self._gui_defers_to_worker:
            self._log_line(
                "Low-CPU mode: short headless worker runs plans/day shorts — this window is display-only. "
                f"See {SHORT_WORKER_LOG.name}."
            )
        else:
            self._log_line(
                f"Short background engine — plan every {ws.get('plan_interval_minutes', 30)} min, "
                f"day shorts every {ws.get('day_trading_interval_minutes', 5)} min ({day_on}). "
                "Agent pipeline stays with the long app / shared output."
            )
        self._update_bg_status()
        self._refresh_day_trading_panel()
        if self._gui_defers_to_worker:
            self._schedule_bg_status_poll()
        else:
            self._schedule_day_trading_refresh()
            self._schedule_background_plan(initial=True)
            self._schedule_background_day_trading(initial=True)

    def _create_config_file(self) -> None:
        if SHORT_CONFIG.exists():
            messagebox.showinfo(
                "Config Exists",
                f"{SHORT_CONFIG.name} already exists. Edit the fields below and click Save Settings.",
            )
            return
        _ensure_short_config_seeded()
        self._load_settings_form()
        self._log_line(f"Created {SHORT_CONFIG.name}")
        self._setup_save_status.configure(text="Short config created — keys inherited when possible", fg=ACCENT2)

    def _persist_settings_from_form(self, *, silent: bool = False):
        """Save credentials into short_etrade_config.json (not the long app config)."""
        result = super()._persist_settings_from_form(silent=silent)
        # Parent already wrote SHORT_CONFIG because we patched CONFIG_PATH.
        # Ensure short-specific blocks remain.
        try:
            raw = long_gui._read_config_file(SHORT_CONFIG)
            raw.setdefault("short_strategy", {})
            raw.setdefault("short_day_trading", {})
            raw.setdefault("background_worker", {
                "auto_execute": bool(self._auto_execute_var.get()),
                "live_trading": bool(self._auto_execute_var.get()) and not bool(self._dry_run_var.get()),
                "day_trading": bool(self._day_trading_var.get()),
                "paused": bool(self._automation_paused),
                "dry_run": bool(self._dry_run_var.get()),
            })
            raw["inherit_credentials_from"] = raw.get("inherit_credentials_from") or "etrade_config.json"
            long_gui._write_config_file(SHORT_CONFIG, raw)
        except Exception:
            pass
        return result


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
