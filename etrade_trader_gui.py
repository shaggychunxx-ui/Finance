#!/usr/bin/env python3
"""E*TRADE Trader — desktop app connecting Finance agent strategies to your brokerage account."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any, Callable

from tkinter import messagebox, ttk
import tkinter as tk

from app_paths import ICON_FILE, OUTPUT, ROOT, ensure_app_path
from gui_theme import (
    ACCENT,
    ACCENT2,
    BG,
    BORDER,
    BTN_ACCENT_HOVER,
    BTN_DANGER_HOVER,
    BTN_PRIMARY_FG,
    BTN_PRIMARY_HOVER,
    CARD_BG,
    CARD_ACTIVE,
    DOWN,
    MUTED,
    PANEL,
    TEXT,
    UP,
    WARN,
    ScreenMetrics,
    build_color_remap,
    configure_trader_notebooks,
    configure_treeview_style,
    current_palette_name,
    load_palette_from_prefs,
    load_ui_layout,
    pane_sash_ratio,
    place_pane_ratio,
    save_ui_layout,
    palette_choices,
    palette_preview,
    refresh_trader_theme,
    save_palette_to_prefs,
    sync_module_globals,
)
from gui_treekit import make_data_tree, tree_clear, tree_insert

ensure_app_path()

from etrade_api.accounts import accounts_look_like_sandbox_demo, format_account_label
from etrade_api.client import ETradeClient
from etrade_api.config import (
    DEFAULT_CONFIG_PATH,
    KEY_PLACEHOLDER,
    SECRET_PLACEHOLDER,
    ETradeConfig,
    build_config,
    clear_selected_account,
    credential_hint,
    get_selected_account,
    load_config,
    read_config_raw,
    save_selected_account,
    sanitize_credential,
    write_config_raw,
)
from etrade_api.oauth import (
    OAuthPending,
    authenticate,
    finish_authorization,
    is_expired_for_day,
    load_tokens,
    normalize_verifier,
    revoke_access_token,
    start_authorization,
    test_api_credentials,
)
from strategy_engine import (
    DEFAULT_CASH_BUFFER_PCT,
    DEFAULT_MIN_DRIFT_PCT,
    DEFAULT_MIN_TRADE_USD,
    PLAN_FILE,
    StrategyPlan,
    TradeOrder,
    build_strategy_plan,
    execute_orders,
    load_strategy_plan,
    plan_from_dict,
    preview_orders,
    run_agent_pipeline,
    save_strategy_plan,
)

DAY_STATE_FILE = OUTPUT / "day_trade_state.json"
DAY_PLAN_FILE = OUTPUT / "day_trade_plan.json"
APP_LOG = OUTPUT / "etrade_trader.log"
CONFIG_PATH = ROOT / "etrade_config.json"
CONFIG_EXAMPLE = ROOT / "etrade_config.example.json"

DEV_PORTAL_URL = "https://developer.etrade.com"
DEFAULT_CALLBACK_URL = "http://127.0.0.1:8765/callback"
BG_PIPELINE_INTERVAL_MS = 5 * 60 * 1000
BG_PLAN_INTERVAL_MS = 30 * 60 * 1000
BG_STARTUP_DELAY_MS = 4000
BG_EXECUTE_MIN_INTERVAL_MS = 15 * 60 * 1000
BG_DAY_TRADING_INTERVAL_MS = 5 * 60 * 1000
BG_STATUS_POLL_MS = 60 * 1000
NETWORK_TASK_TIMEOUT_SEC = 45
WORKER_LOG = OUTPUT / "etrade_worker.log"
ACCOUNT_PLACEHOLDER = "— Select account —"


def _log_crash(msg: str) -> None:
    APP_LOG.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with APP_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] {msg}\n")


def _read_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_config_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _config_keys_valid(data: dict[str, Any]) -> bool:
    key = sanitize_credential(data.get("consumer_key") or "", KEY_PLACEHOLDER)
    secret = sanitize_credential(data.get("consumer_secret") or "", SECRET_PLACEHOLDER)
    placeholders = {"", KEY_PLACEHOLDER, SECRET_PLACEHOLDER}
    return key not in placeholders and secret not in placeholders


class OAuthVerifyDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        authorize_url: str,
        metrics: ScreenMetrics,
        on_submit: Callable[[str], None],
        on_cancel: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self._on_submit = on_submit
        self._on_cancel = on_cancel
        self._m = metrics

        self.title("E*TRADE Verification Code")
        self.configure(bg=PANEL)
        self.transient(parent)
        self.resizable(False, False)

        pad = self._m.px(16)
        tk.Label(
            self, text="Enter your E*TRADE verification code",
            bg=PANEL, fg=TEXT, font=self._m.font(13, "bold"),
        ).pack(anchor="w", padx=pad, pady=(pad, self._m.px(6)))

        tk.Label(
            self,
            text=(
                "1. Click Open E*TRADE below and sign in\n"
                "2. Click Accept on the authorization page\n"
                "3. Copy the verification code shown (e.g. WXYZ89)\n"
                "4. Paste it here and click Connect"
            ),
            bg=PANEL, fg=MUTED, font=self._m.font(10), justify=tk.LEFT,
        ).pack(anchor="w", padx=pad, pady=(0, self._m.px(10)))

        entry_frame = tk.Frame(self, bg=PANEL)
        entry_frame.pack(fill=tk.X, padx=pad, pady=(0, self._m.px(10)))
        self._code_var = tk.StringVar()
        self._entry = tk.Entry(
            entry_frame, textvariable=self._code_var, bg="#0d1424", fg=TEXT,
            insertbackground=TEXT, relief=tk.FLAT, font=self._m.font(12), width=28,
        )
        self._entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=self._m.px(8))
        self._entry.focus_set()
        self._entry.bind("<Return>", lambda _e: self._submit())

        paste_btn = tk.Button(
            entry_frame, text="Paste", command=self._paste,
            bg=BORDER, fg=TEXT, activebackground=ACCENT, relief=tk.FLAT,
            font=self._m.font(9), padx=self._m.px(10), pady=self._m.px(6), cursor="hand2", bd=0,
        )
        paste_btn.pack(side=tk.LEFT, padx=(self._m.px(8), 0))

        self._status = tk.Label(self, text="", bg=PANEL, fg=DOWN, font=self._m.font(9))
        self._status.pack(anchor="w", padx=pad, pady=(0, self._m.px(8)))

        btn_row = tk.Frame(self, bg=PANEL)
        btn_row.pack(fill=tk.X, padx=pad, pady=(0, pad))
        tk.Button(
            btn_row, text="Open E*TRADE", command=lambda: webbrowser.open(authorize_url),
            bg=BORDER, fg=TEXT, activebackground=ACCENT, relief=tk.FLAT,
            font=self._m.font(10), padx=self._m.px(12), pady=self._m.px(8), cursor="hand2", bd=0,
        ).pack(side=tk.LEFT)
        tk.Button(
            btn_row, text="Connect", command=self._submit,
            bg=ACCENT, fg="#fff", activebackground="#5a4bd6", relief=tk.FLAT,
            font=self._m.font(10, "bold"), padx=self._m.px(14), pady=self._m.px(8), cursor="hand2", bd=0,
        ).pack(side=tk.RIGHT)
        tk.Button(
            btn_row, text="Cancel", command=self._cancel,
            bg=BORDER, fg=MUTED, activebackground=PANEL, relief=tk.FLAT,
            font=self._m.font(10), padx=self._m.px(12), pady=self._m.px(8), cursor="hand2", bd=0,
        ).pack(side=tk.RIGHT, padx=(0, self._m.px(8)))

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.update_idletasks()
        w, h = self._m.px(460), self._m.px(280)
        px = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
        self.geometry(f"{w}x{h}+{max(0, px)}+{max(0, py)}")
        self.lift()
        self.attributes("-topmost", True)
        self.after(300, lambda: self.attributes("-topmost", False))
        self.grab_set()
        self.focus_force()

    def _paste(self) -> None:
        try:
            clip = self.clipboard_get().strip()
        except tk.TclError:
            self._status.configure(text="Clipboard is empty", fg=WARN)
            return
        self._code_var.set(normalize_verifier(clip))
        self._status.configure(text="", fg=MUTED)

    def _submit(self) -> None:
        code = normalize_verifier(self._code_var.get())
        if not code:
            self._status.configure(text="Enter the verification code from E*TRADE", fg=DOWN)
            return
        self.grab_release()
        self.destroy()
        self._on_submit(code)

    def _cancel(self) -> None:
        self.grab_release()
        self.destroy()
        self._on_cancel()


class ETradeTraderApp(tk.Frame):
    def __init__(
        self,
        parent: tk.Misc | None = None,
        *,
        path_bundle: dict[str, Any] | None = None,
        embedded: bool = False,
        app_title: str | None = None,
        layout_key: str = "etrade_trader",
        manage_window_close: bool = True,
    ) -> None:
        # Per-instance paths so Long + Short can live in one process/UI.
        bundle = path_bundle or {}
        self.CONFIG_PATH = Path(bundle.get("config", CONFIG_PATH))
        self.CONFIG_EXAMPLE = Path(bundle.get("config_example", CONFIG_EXAMPLE))
        self.PLAN_FILE = Path(bundle.get("plan", PLAN_FILE))
        self.DAY_STATE_FILE = Path(bundle.get("day_state", DAY_STATE_FILE))
        self.DAY_PLAN_FILE = Path(bundle.get("day_plan", DAY_PLAN_FILE))
        self.WORKER_LOG = Path(bundle.get("worker_log", WORKER_LOG))
        self.APP_LOG = Path(bundle.get("app_log", APP_LOG))
        self._embedded = bool(embedded)
        self._layout_key = layout_key
        self._app_title = app_title or "E*TRADE Trader — Finance Agents"

        if parent is None:
            self._window = tk.Tk()
            parent = self._window
        else:
            self._window = parent.winfo_toplevel()
        super().__init__(parent, bg=BG)

        if not self._embedded:
            self._window.title(self._app_title)
            self._window.configure(bg=BG)
            self._m = ScreenMetrics(self._window, window_profile="trader")
            self._layout_save_after_id: str | None = None
            saved_layout = load_ui_layout(self._layout_key)
            saved_geometry = str(saved_layout.get("geometry") or "").strip()
            if saved_geometry and "x" in saved_geometry:
                self._window.geometry(saved_geometry)
            else:
                self._window.geometry(f"{self._m.win_w}x{self._m.win_h}")
            self._window.minsize(self._m.px(980), self._m.px(640))
        else:
            self._m = ScreenMetrics(self._window, window_profile="trader")
            self._layout_save_after_id = None
        self.pack(fill=tk.BOTH, expand=True)

        self._config: ETradeConfig | None = None
        self._client: ETradeClient | None = None
        self._accounts: list[dict[str, Any]] = []
        self._plan: StrategyPlan | None = None
        self._trade_analysis_context = "portfolio"
        self._busy = False
        self._refresh_running = False
        self._bg_pipeline_running = False
        self._bg_plan_running = False
        self._bg_execute_running = False
        self._bg_day_trading_running = False
        self._bg_pipeline_after_id: str | None = None
        self._bg_plan_after_id: str | None = None
        self._bg_day_trading_after_id: str | None = None
        self._day_refresh_after_id: str | None = None
        self._bg_status_poll_after_id: str | None = None
        self._automation_paused = False
        self._automation_snapshot: tuple[bool, bool, bool, bool] | None = None
        self._automation_sync_ticks = 0
        self._gui_defers_to_worker = False
        self._worker_pipeline_progress = ""
        self._worker_pipeline_stuck = False
        self._last_pipeline_at: float | None = None
        self._last_plan_at: float | None = None
        self._last_execute_at: float | None = None
        self._last_day_trade_at: float | None = None
        self._last_executed_plan_sig: str | None = None
        self._cached_plan_mtime: float = 0.0
        self._cached_pipeline_at: float = 0.0
        self._day_poll_counter: int = 0
        self._ui_queue: queue.Queue = queue.Queue()
        self._log_flush_after_id: str | None = None
        self._pending_log_lines: list[str] = []
        self._account_var = tk.StringVar()
        self._auto_execute_var = tk.BooleanVar(value=True)
        self._day_trading_var = tk.BooleanVar(value=True)
        self._dry_run_var = tk.BooleanVar(value=False)
        # Buy-app capital cap: pct | usd | off
        self._capital_cap_mode_var = tk.StringVar(value="pct")
        self._capital_cap_pct_var = tk.StringVar(value="75")
        self._capital_cap_usd_var = tk.StringVar(value="5000")
        self._sandbox_var = tk.BooleanVar(value=True)
        self._oob_var = tk.BooleanVar(value=False)
        self._key_var = tk.StringVar()
        self._secret_var = tk.StringVar()
        self._setup_step_labels: list[tk.Label] = []
        self._setup_step_icons: list[tk.Label] = []
        self._setup_sections: list[tk.Frame] = []
        self._setup_canvas: tk.Canvas | None = None
        self._oauth_dialog: OAuthVerifyDialog | None = None
        self._oauth_pending: OAuthPending | None = None
        self._connect_epoch = 0
        self._shutting_down = False
        self._confirmed_account_idx: int | None = None
        self._suppress_account_change = False
        self._persisted_account_key: str | None = None
        self._finance_agents: Any = None

        self._apply_window_icons()
        self._palette_buttons: dict[str, tk.Frame] = {}
        load_palette_from_prefs()
        sync_module_globals(sys.modules[__name__])

        if self.CONFIG_PATH.exists():
            try:
                self._load_trading_settings_from_config()
                self._refresh_automation_snapshot()
            except Exception:
                pass

        self._build_styles()
        self._build_ui()
        if manage_window_close and not self._embedded:
            self._window.protocol("WM_DELETE_WINDOW", self._on_close)
            self._window.report_callback_exception = self._on_tk_exception
            self._window.after(100, self._ensure_visible)
        self._poll_ui()
        self._bootstrap_config()
        self._load_cached_plan()
        self._window.after(5000, self._start_background_engine)

    def _apply_window_icons(self) -> None:
        # Multi-size .ico for the title bar. Do not call iconphoto(True, …) on Windows —
        # it replaces the taskbar icon with a soft upscaled bitmap and ignores the .exe icon.
        if ICON_FILE.exists():
            try:
                self._window.iconbitmap(str(ICON_FILE))
            except tk.TclError:
                pass

    def _pad(self) -> int:
        return self._m.px(16)

    def _worker_settings(self) -> dict[str, Any]:
        try:
            from etrade_worker import worker_settings

            return worker_settings(self.CONFIG_PATH)
        except Exception:
            return {}

    def _ui_poll_delay_ms(self) -> int:
        base = max(100, int(self._worker_settings().get("ui_poll_ms", 300)))
        if self._gui_defers_to_worker:
            return max(base, 500)
        return base

    def _bg_status_poll_delay_ms(self) -> int:
        return max(15_000, int(self._worker_settings().get("worker_status_poll_ms", BG_STATUS_POLL_MS)))

    def _day_panel_refresh_ms(self) -> int:
        mins = max(1, int(self._worker_settings().get("day_panel_refresh_minutes", 5)))
        return mins * 60 * 1000

    def _pipeline_interval_ms(self) -> int:
        mins = max(1, int(self._worker_settings().get("pipeline_interval_minutes", 5)))
        return mins * 60 * 1000

    def _plan_interval_ms(self) -> int:
        mins = max(1, int(self._worker_settings().get("plan_interval_minutes", 30)))
        return mins * 60 * 1000

    def _day_trading_interval_ms(self) -> int:
        mins = max(1, int(self._worker_settings().get("day_trading_interval_minutes", 5)))
        return mins * 60 * 1000

    def _gui_should_defer_to_worker(self) -> bool:
        try:
            from etrade_worker import gui_should_defer_to_worker

            return gui_should_defer_to_worker(self.CONFIG_PATH)
        except Exception:
            return False

    def _sync_status_from_worker(self) -> bool:
        """Pull last-run timestamps from the headless worker; return True if recently active."""
        try:
            from etrade_worker import LOG_FILE as worker_log
            from etrade_worker import load_worker_state

            state = load_worker_state()
            for key, attr in (
                ("last_pipeline_at", "_last_pipeline_at"),
                ("last_plan_at", "_last_plan_at"),
                ("last_execute_at", "_last_execute_at"),
                ("last_day_trade_at", "_last_day_trade_at"),
            ):
                val = state.get(key)
                if val:
                    setattr(self, attr, float(val))
            if worker_log.exists():
                return (time.time() - worker_log.stat().st_mtime) < 120
        except Exception:
            pass
        return False

    def _schedule_bg_status_poll(self) -> None:
        if self._automation_paused or self._shutting_down or not self._gui_defers_to_worker:
            return
        if self._bg_status_poll_after_id:
            try:
                self.after_cancel(self._bg_status_poll_after_id)
            except tk.TclError:
                pass
        self._poll_worker_status()
        try:
            self._bg_status_poll_after_id = self.after(
                self._bg_status_poll_delay_ms(),
                self._schedule_bg_status_poll,
            )
        except tk.TclError:
            pass

    def _poll_worker_status(self) -> None:
        self._sync_status_from_worker()
        try:
            from etrade_worker import worker_pipeline_status

            pipe = worker_pipeline_status()
            self._worker_pipeline_progress = str(pipe.get("progress") or "")
            self._worker_pipeline_stuck = bool(pipe.get("stuck"))
            worker_active = bool(pipe.get("active"))
        except Exception:
            self._worker_pipeline_progress = ""
            self._worker_pipeline_stuck = False
            worker_active = False
            try:
                from etrade_worker import LOG_FILE as worker_log

                if worker_log.exists():
                    worker_active = (time.time() - worker_log.stat().st_mtime) < 120
            except Exception:
                pass
        self._bg_pipeline_running = worker_active or self._worker_pipeline_stuck
        self._bg_day_trading_running = worker_active

        pipeline_at = float(self._last_pipeline_at or 0)
        if pipeline_at > self._cached_pipeline_at:
            self._cached_pipeline_at = pipeline_at
            self._refresh_reports_ui(select_latest=True)

        if self.PLAN_FILE.exists():
            try:
                mtime = self.PLAN_FILE.stat().st_mtime
                if mtime != self._cached_plan_mtime:
                    self._cached_plan_mtime = mtime
                    data = load_strategy_plan(self.PLAN_FILE)
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
        raw = _read_config_file(self.CONFIG_PATH)
        worker = raw.get("background_worker", {})
        if "auto_execute" in worker:
            self._auto_execute_var.set(bool(worker["auto_execute"]))
        if "day_trading" in worker:
            self._day_trading_var.set(bool(worker["day_trading"]))
        else:
            day_cfg = raw.get("day_trading", {})
            if isinstance(day_cfg, dict) and "enabled" in day_cfg:
                self._day_trading_var.set(bool(day_cfg["enabled"]))
        if "dry_run" in worker:
            self._dry_run_var.set(bool(worker["dry_run"]))
        self._automation_paused = bool(worker.get("paused", False))
        self._gui_defers_to_worker = self._gui_should_defer_to_worker()
        self._load_capital_cap_from_raw(raw)

    def _load_capital_cap_from_raw(self, raw: dict[str, Any]) -> None:
        sp = raw.get("sleeve_policy") if isinstance(raw.get("sleeve_policy"), dict) else {}
        mode = str(sp.get("long_capital_cap_mode") or "pct").strip().lower()
        if mode in {"usd", "dollar", "dollars", "fixed", "amount", "$"}:
            mode = "usd"
        elif mode in {"off", "none", "disabled"}:
            mode = "off"
        else:
            mode = "pct"
        self._capital_cap_mode_var.set(mode)
        pct = sp.get("long_max_deploy_pct", 75.0)
        try:
            self._capital_cap_pct_var.set(str(float(pct)).rstrip("0").rstrip(".") if float(pct) != int(float(pct)) else str(int(float(pct))))
        except (TypeError, ValueError):
            self._capital_cap_pct_var.set("75")
        usd = sp.get("long_max_capital_usd", 5000.0)
        try:
            usd_f = float(usd or 0)
            self._capital_cap_usd_var.set(
                str(int(usd_f)) if usd_f == int(usd_f) else f"{usd_f:.2f}"
            )
        except (TypeError, ValueError):
            self._capital_cap_usd_var.set("5000")
        self._update_capital_cap_ui_state()

    def _refresh_automation_snapshot(self) -> None:
        self._automation_snapshot = (
            self._automation_paused,
            bool(self._auto_execute_var.get()),
            bool(self._day_trading_var.get()),
            bool(self._dry_run_var.get()),
        )

    def _apply_automation_ui_state(self) -> None:
        self._sync_trade_flags()
        self._update_automation_control_ui()
        self._update_bg_status()
        self._refresh_day_trading_panel()

    def _apply_automation_running_state(self) -> None:
        self._schedule_day_trading_refresh()
        if self._gui_should_defer_to_worker():
            self._gui_defers_to_worker = True
            self._schedule_bg_status_poll()
        else:
            self._gui_defers_to_worker = False
            self._schedule_background_pipeline()
            self._schedule_background_plan()
            self._schedule_background_day_trading()

    def _sync_automation_from_config(self) -> None:
        """Pick up Stop all / Resume all changes made from the phone app."""
        if self._shutting_down:
            return
        try:
            raw = read_config_raw(self.CONFIG_PATH)
        except Exception:
            return
        worker = raw.get("background_worker", {})
        if not isinstance(worker, dict):
            return
        paused = bool(worker.get("paused", False))
        auto = bool(worker.get("auto_execute", True)) if "auto_execute" in worker else bool(self._auto_execute_var.get())
        day = bool(worker.get("day_trading", True)) if "day_trading" in worker else bool(self._day_trading_var.get())
        dry = bool(worker.get("dry_run", False)) if "dry_run" in worker else bool(self._dry_run_var.get())
        snapshot = (paused, auto, day, dry)
        if snapshot == self._automation_snapshot:
            return

        prev_paused = self._automation_paused
        self._load_trading_settings_from_config()
        self._automation_snapshot = (
            self._automation_paused,
            bool(self._auto_execute_var.get()),
            bool(self._day_trading_var.get()),
            bool(self._dry_run_var.get()),
        )

        if self._automation_paused and not prev_paused:
            self._cancel_background_schedules()
            self._log_line("Automation stopped from phone.")
            self._set_status("All automation stopped", WARN)
        elif not self._automation_paused and prev_paused:
            self._log_line("Automation resumed from phone.")
            self._set_status("Automation resumed", UP)
            self._apply_automation_running_state()

        self._apply_automation_ui_state()

    def _persist_trading_settings(self) -> None:
        raw = read_config_raw(self.CONFIG_PATH)
        worker = dict(raw.get("background_worker", {}))
        auto = bool(self._auto_execute_var.get())
        day = bool(self._day_trading_var.get())
        dry = bool(self._dry_run_var.get())
        worker["auto_execute"] = auto
        worker["day_trading"] = day
        worker["live_trading"] = auto and not dry
        worker["dry_run"] = dry
        raw["background_worker"] = worker
        day_cfg = dict(raw.get("day_trading", {}))
        day_cfg["enabled"] = day
        raw["day_trading"] = day_cfg
        self._apply_capital_cap_to_raw(raw)
        try:
            write_config_raw(self.CONFIG_PATH, raw)
            self._sync_sleeve_policy_to_short_config(raw.get("sleeve_policy") or {})
        except OSError:
            pass

    def _apply_capital_cap_to_raw(self, raw: dict[str, Any]) -> None:
        sp = dict(raw.get("sleeve_policy") or {})
        mode = str(self._capital_cap_mode_var.get() or "pct").strip().lower()
        if mode not in {"pct", "usd", "off"}:
            mode = "pct"
        sp["long_capital_cap_mode"] = mode
        try:
            pct = float(str(self._capital_cap_pct_var.get()).replace("%", "").strip() or 75)
        except ValueError:
            pct = 75.0
        pct = max(0.0, min(100.0, pct))
        sp["long_max_deploy_pct"] = pct
        try:
            usd = float(str(self._capital_cap_usd_var.get()).replace("$", "").replace(",", "").strip() or 0)
        except ValueError:
            usd = 0.0
        sp["long_max_capital_usd"] = max(0.0, usd)
        sp.setdefault("enabled", True)
        sp.setdefault("shared_capital", True)
        sp.setdefault("short_max_deploy_pct", 35.0)
        sp.setdefault("shared_cash_buffer_pct", 5.0)
        sp.setdefault("forbid_opposite_side", True)
        sp.setdefault("forbid_same_symbol_both_sleeves", True)
        sp.setdefault("coordinate_for_profit", True)
        raw["sleeve_policy"] = sp

    def _sync_sleeve_policy_to_short_config(self, sleeve_policy: dict[str, Any]) -> None:
        """Keep short app sleeve_policy in sync so both apps share one capital view."""
        short_path = ROOT / "short_etrade_config.json"
        if not short_path.exists() or not isinstance(sleeve_policy, dict):
            return
        try:
            short_raw = read_config_raw(short_path)
            short_raw["sleeve_policy"] = dict(sleeve_policy)
            write_config_raw(short_path, short_raw)
        except OSError:
            pass

    def _on_capital_cap_changed(self) -> None:
        self._update_capital_cap_ui_state()
        self._persist_trading_settings()
        mode = self._capital_cap_mode_var.get()
        if mode == "usd":
            msg = f"Buy capital cap: fixed ${self._capital_cap_usd_var.get()}"
        elif mode == "off":
            msg = "Buy capital cap: off (uses full free equity / buying power)"
        else:
            msg = f"Buy capital cap: {self._capital_cap_pct_var.get()}% of free equity"
        self._log_line(msg)
        self._refresh_capital_cap_status()

    def _update_capital_cap_ui_state(self) -> None:
        mode = str(self._capital_cap_mode_var.get() or "pct")
        pct_state = tk.NORMAL if mode == "pct" else tk.DISABLED
        usd_state = tk.NORMAL if mode == "usd" else tk.DISABLED
        if hasattr(self, "_capital_cap_pct_entry"):
            try:
                self._capital_cap_pct_entry.configure(state=pct_state)
            except tk.TclError:
                pass
        if hasattr(self, "_capital_cap_usd_entry"):
            try:
                self._capital_cap_usd_entry.configure(state=usd_state)
            except tk.TclError:
                pass

    def _refresh_capital_cap_status(self) -> None:
        if not hasattr(self, "_capital_cap_status"):
            return
        mode = str(self._capital_cap_mode_var.get() or "pct")
        try:
            from sleeve_policy import shared_capital_budget

            # Prefer live account value when known; else show config-only summary
            total = 0.0
            bal = getattr(self, "_last_balance", None)
            if isinstance(bal, dict):
                total = float(bal.get("total_account_value") or 0)
            if total <= 0:
                total = float(getattr(self, "_balance_total_value", 0) or 0)
            raw = _read_config_file(self.CONFIG_PATH)
            sp = raw.get("sleeve_policy") if isinstance(raw.get("sleeve_policy"), dict) else {}
            if total > 0:
                budget = shared_capital_budget(total, sleeve="long", policy=sp)
                ceiling = budget.get("sleeve_ceiling_usd", 0)
                self._capital_cap_status.configure(
                    text=(
                        f"This buy app may use up to ${float(ceiling):,.0f} "
                        f"of ${total:,.0f} account value "
                        f"({mode if mode != 'off' else 'no soft cap'})."
                    ),
                    fg=ACCENT2,
                )
            elif mode == "usd":
                self._capital_cap_status.configure(
                    text=f"Fixed cap: ${self._capital_cap_usd_var.get()} (connect account to see vs equity).",
                    fg=MUTED,
                )
            elif mode == "off":
                self._capital_cap_status.configure(
                    text="No soft capital cap — full free equity / buying power may be used.",
                    fg=MUTED,
                )
            else:
                self._capital_cap_status.configure(
                    text=f"Cap: {self._capital_cap_pct_var.get()}% of free equity (after cash buffer).",
                    fg=MUTED,
                )
        except Exception:
            self._capital_cap_status.configure(text="Capital limit ready.", fg=MUTED)

    def _on_trade_setting_changed(self) -> None:
        if self._automation_paused and (self._auto_execute_var.get() or self._day_trading_var.get()):
            self._auto_execute_var.set(False)
            self._day_trading_var.set(False)
            messagebox.showinfo(
                "Automation paused",
                "Click Resume all before changing trading settings.",
            )
            return
        self._sync_trade_flags()
        self._persist_trading_settings()
        self._update_bg_status()
        self._refresh_day_trading_panel()
        mode = "dry run" if self._dry_run_var.get() else "LIVE production" if self._config and not self._config.sandbox else "live"
        self._log_line(
            f"Trading tasks updated — auto-execute: {self._auto_execute_var.get()}, "
            f"day trading: {self._day_trading_var.get()}, mode: {mode}"
        )

    def _sync_trade_flags(self) -> None:
        self._auto_execute_enabled = bool(self._auto_execute_var.get()) and not self._automation_paused
        self._dry_run_enabled = bool(self._dry_run_var.get())
        self._update_bg_status()

    def _cancel_background_schedules(self) -> None:
        for after_id in (
            self._bg_pipeline_after_id,
            self._bg_plan_after_id,
            self._bg_day_trading_after_id,
            self._day_refresh_after_id,
            self._bg_status_poll_after_id,
            self._log_flush_after_id,
        ):
            if after_id:
                try:
                    self.after_cancel(after_id)
                except tk.TclError:
                    pass
        self._bg_pipeline_after_id = None
        self._bg_plan_after_id = None
        self._bg_day_trading_after_id = None
        self._day_refresh_after_id = None
        self._bg_status_poll_after_id = None
        self._log_flush_after_id = None

    def _update_automation_control_ui(self) -> None:
        if not hasattr(self, "_btn_stop_all"):
            return
        if self._automation_paused:
            self._btn_stop_all.configure(text="Resume all", bg=UP, activebackground="#00c853")
            if hasattr(self, "_automation_status_label"):
                self._automation_status_label.configure(
                    text=(
                        "All automation is stopped on BOTH buy and short apps — "
                        "no agents, plans, or trades until you resume."
                    ),
                    fg=WARN,
                )
        else:
            self._btn_stop_all.configure(text="Stop all", bg=DOWN, activebackground="#cc4040")
            if hasattr(self, "_automation_status_label"):
                if self._gui_defers_to_worker:
                    hint = (
                        "Low-CPU mode — the headless worker runs automation; this window only shows status. "
                        "Stop all halts buy + short apps."
                    )
                else:
                    hint = (
                        "Agents, strategy, swing orders, and day trading run in the background. "
                        "Stop all halts buy + short apps together."
                    )
                self._automation_status_label.configure(text=hint, fg=MUTED)

    def _toggle_automation_pause(self) -> None:
        if self._automation_paused:
            self._resume_all_automation()
        else:
            self._stop_all_automation()

    def _stop_all_automation(self) -> None:
        if not messagebox.askyesno(
            "Stop all",
            "Stop all background automation on BOTH apps?\n\n"
            "This halts agents, strategy updates, swing trades, and day trading "
            "for the buy app and the short app (and both headless workers) until you resume.",
        ):
            return
        from etrade_worker import set_automation_paused

        self._cancel_background_schedules()
        # both_sleeves=True (default): long + short configs/workers
        set_automation_paused(True, self.CONFIG_PATH, both_sleeves=True)
        self._load_trading_settings_from_config()
        self._refresh_automation_snapshot()
        self._apply_automation_ui_state()
        self._log_line("All automation stopped on buy + short apps.")
        self._set_status("All automation stopped (buy + short)", WARN)

    def _resume_all_automation(self) -> None:
        from etrade_worker import set_automation_paused

        set_automation_paused(False, self.CONFIG_PATH, both_sleeves=True)
        self._load_trading_settings_from_config()
        self._refresh_automation_snapshot()
        self._apply_automation_ui_state()
        self._log_line("Automation resumed on buy + short apps.")
        self._set_status("Automation resumed (buy + short)", UP)
        self._apply_automation_running_state()

    def _build_styles(self) -> None:
        style = ttk.Style(self._window)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        configure_treeview_style(style, self._m, prefix="Trader")
        configure_trader_notebooks(style, self._m)
    def _sync_theme_tokens(self) -> None:
        sync_module_globals(sys.modules[__name__])

    def _set_color_palette(self, palette_id: str) -> None:
        previous = current_palette_name()
        if palette_id == previous:
            return
        save_palette_to_prefs(palette_id)
        self._sync_theme_tokens()
        self._window.configure(bg=BG)
        self.configure(bg=BG)
        self._build_styles()
        color_map = build_color_remap(previous, palette_id)
        refresh_trader_theme(self._window, ttk.Style(self._window), self._m, color_map=color_map)
        self._sync_palette_buttons()
        if hasattr(self, "_balance_growth_chart"):
            self._balance_growth_chart.apply_theme()
        if self._finance_agents is not None and hasattr(self._finance_agents, "refresh_theme"):
            self._finance_agents.refresh_theme(previous)
        self._log_line(f"Color palette: {palette_preview(palette_id).get('label', palette_id)}")

    def _sync_palette_buttons(self) -> None:
        active = current_palette_name()
        for palette_id, frame in self._palette_buttons.items():
            preview = palette_preview(palette_id)
            selected = palette_id == active
            frame.configure(
                bg=preview["CARD_ACTIVE"] if selected else preview["CARD_BG"],
                highlightbackground=preview["ACCENT"] if selected else preview["BORDER"],
                highlightthickness=2 if selected else 1,
            )

    def _build_appearance_section(self, parent: tk.Misc) -> None:
        section = self._section(parent, "Appearance", "Pick a color palette — applies instantly across the app.")
        section.pack(fill=tk.X, pady=(0, self._m.px(12)))
        inner = section._inner
        row = tk.Frame(inner, bg=CARD_BG)
        row.pack(fill=tk.X)
        self._palette_buttons.clear()
        for palette_id, label in palette_choices():
            preview = palette_preview(palette_id)
            chip = tk.Frame(
                row,
                bg=preview["CARD_BG"],
                highlightbackground=preview["BORDER"],
                highlightthickness=1,
                cursor="hand2",
            )
            chip.pack(side=tk.LEFT, padx=(0, self._m.px(10)), pady=self._m.px(2))
            swatches = tk.Frame(chip, bg=preview["CARD_BG"])
            swatches.pack(fill=tk.X, padx=self._m.px(8), pady=(self._m.px(8), self._m.px(4)))
            for color_key in ("ACCENT", "ACCENT2", "UP", "BG"):
                tk.Frame(swatches, bg=preview[color_key], width=self._m.px(18), height=self._m.px(10)).pack(
                    side=tk.LEFT,
                    padx=(0, self._m.px(3)),
                )
            name = tk.Label(
                chip,
                text=label,
                bg=preview["CARD_BG"],
                fg=preview["TEXT"],
                font=self._m.font(9, "bold"),
                cursor="hand2",
            )
            name.pack(padx=self._m.px(8), pady=(0, self._m.px(8)))
            for widget in (chip, swatches, name):
                widget.bind("<Button-1>", lambda _e, pid=palette_id: self._set_color_palette(pid))
            self._palette_buttons[palette_id] = chip
        self._sync_palette_buttons()

    def _show_dashboard_tab(self) -> None:
        if hasattr(self, "_tab_dashboard"):
            self._notebook.select(self._tab_dashboard)

    def _show_trades_tab(
        self,
        *,
        swing: bool = True,
        portfolio: bool = False,
        balance: bool = False,
        history: bool = False,
        attribution: bool = False,
    ) -> None:
        self._notebook.select(self._tab_trades)
        if hasattr(self, "_trades_notebook"):
            if history or attribution:
                self._trades_notebook.select(self._tab_performance)
                if hasattr(self, "_perf_notebook"):
                    if attribution:
                        self._perf_notebook.select(self._tab_attribution)
                    else:
                        self._perf_notebook.select(self._tab_history)
            elif balance:
                self._trades_notebook.select(self._tab_overview)
            elif portfolio:
                self._trades_notebook.select(self._tab_holdings)
            else:
                self._trades_notebook.select(self._tab_orders)
                if hasattr(self, "_orders_notebook"):
                    self._orders_notebook.select(self._tab_swing_orders if swing else self._tab_day_orders)

    def _panel(self, parent: tk.Misc, *, title: str = "", pad: int | None = None) -> tk.Frame:
        outer = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        inner = tk.Frame(outer, bg=PANEL)
        inner.pack(fill=tk.BOTH, expand=True, padx=pad or self._m.px(14), pady=pad or self._m.px(12))
        if title:
            tk.Label(inner, text=title, bg=PANEL, fg=TEXT, font=self._m.font(11, "bold")).pack(anchor="w")
        outer._inner = inner  # type: ignore[attr-defined]
        return outer

    def _make_btn(self, parent: tk.Misc, text: str, cmd: Callable[[], None],
                  *, variant: str = "secondary", side=tk.LEFT, padx=0, compact: bool = False) -> tk.Button:
        palette = {
            "primary": (ACCENT, BTN_PRIMARY_FG, BTN_PRIMARY_HOVER),
            "accent": (ACCENT2, BG, BTN_ACCENT_HOVER),
            "danger": (DOWN, BTN_PRIMARY_FG, BTN_DANGER_HOVER),
            "secondary": (CARD_BG, TEXT, CARD_ACTIVE),
        }
        bg, fg, abg = palette.get(variant, palette["secondary"])
        btn = tk.Button(
            parent,
            text=text,
            command=cmd,
            bg=bg,
            fg=fg,
            activebackground=abg,
            activeforeground=fg,
            relief=tk.FLAT,
            font=self._m.font(8 if compact else 10, "bold" if variant != "secondary" else ""),
            padx=self._m.px(10 if compact else 14),
            pady=self._m.px(4 if compact else 7),
            cursor="hand2",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=BORDER,
        )
        btn.pack(side=side, padx=padx)
        return btn

    def _automation_chip(self, parent: tk.Misc, title: str, initial: str) -> tk.Label:
        cell = tk.Frame(parent, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        cell.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, self._m.px(6)))
        tk.Label(cell, text=title, bg=CARD_BG, fg=MUTED, font=self._m.font(9, "bold")).pack(
            anchor="w", padx=10, pady=(8, 0),
        )
        val = tk.Label(
            cell, text=initial, bg=CARD_BG, fg=ACCENT2, font=self._m.font(12, "bold"),
            wraplength=self._m.px(180), justify=tk.LEFT,
        )
        val.pack(anchor="w", padx=10, pady=(2, 10))
        return val

    def _build_dashboard_tab(self) -> None:
        scroll_outer = tk.Frame(self._tab_dashboard, bg=BG)
        scroll_outer.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(scroll_outer, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(scroll_outer, orient=tk.VERTICAL, command=canvas.yview)
        body = tk.Frame(canvas, bg=BG)
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_wheel(event: tk.Event) -> None:
            if event.delta:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<MouseWheel>", _on_wheel)
        canvas.bind("<Enter>", lambda _e: canvas.focus_set())

        pad_x = self._m.px(14)
        tk.Label(
            body, text="Your trading dashboard",
            bg=BG, fg=TEXT, font=self._m.font(16, "bold"),
        ).pack(anchor="w", padx=pad_x, pady=(self._m.px(14), self._m.px(4)))
        tk.Label(
            body,
            text=(
                "Everything runs automatically in the background. "
                "Use Stop all to halt BOTH the buy and short apps (and their workers)."
            ),
            bg=BG, fg=MUTED, font=self._m.font(10), wraplength=self._m.px(900), justify=tk.LEFT,
        ).pack(anchor="w", padx=pad_x, pady=(0, self._m.px(12)))

        cards = tk.Frame(body, bg=BG)
        cards.pack(fill=tk.X, padx=pad_x, pady=(0, self._m.px(10)))
        cards.columnconfigure((0, 1, 2, 3), weight=1)
        self._card_value = self._stat_card(cards, "Account value", "—", accent=ACCENT2)
        self._card_cash = self._stat_card(cards, "Buying power", "—")
        self._card_reports = self._stat_card(cards, "Agent reports", "—", accent=ACCENT)
        self._card_orders = self._stat_card(cards, "Pending trades", "—", accent=WARN)
        for col, card in enumerate((self._card_value, self._card_cash, self._card_reports, self._card_orders)):
            card.grid(row=0, column=col, sticky="ew", padx=(0, 6 if col < 3 else 0))

        auto_panel = self._panel(body, title="Automation status")
        auto_panel.pack(fill=tk.X, padx=pad_x, pady=(0, self._m.px(10)))
        auto_row = tk.Frame(auto_panel._inner, bg=PANEL)  # type: ignore[attr-defined]
        auto_row.pack(fill=tk.X, pady=(self._m.px(8), 0))
        self._bg_agents_label = self._automation_chip(auto_row, "RESEARCH AGENTS", "Starting…")
        self._bg_plan_label = self._automation_chip(auto_row, "SWING STRATEGY", "Waiting")
        self._bg_orders_label = self._automation_chip(auto_row, "SWING ORDERS", "Auto")
        self._bg_day_label = self._automation_chip(auto_row, "DAY TRADING", "On")
        self._bg_updated_label = tk.Label(
            auto_panel._inner, text="Last update: —", bg=PANEL, fg=MUTED, font=self._m.font(9),  # type: ignore[attr-defined]
        )
        self._bg_updated_label.pack(anchor="e", pady=(self._m.px(8), 0))

        trade_panel = self._panel(body, title="How do you want to trade?")
        trade_panel.pack(fill=tk.X, padx=pad_x, pady=(0, self._m.px(10)))
        tin = trade_panel._inner  # type: ignore[attr-defined]

        swing_card = tk.Frame(tin, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        swing_card.pack(fill=tk.X, pady=(self._m.px(8), self._m.px(6)))
        swing_in = tk.Frame(swing_card, bg=CARD_BG)
        swing_in.pack(fill=tk.X, padx=12, pady=10)
        tk.Label(swing_in, text="Swing investing", bg=CARD_BG, fg=TEXT, font=self._m.font(11, "bold")).pack(anchor="w")
        tk.Label(
            swing_in,
            text="Agents choose all stocks — swing trades follow the agent portfolio. Strategy updates every 30 minutes.",
            bg=CARD_BG, fg=MUTED, font=self._m.font(9), wraplength=self._m.px(700), justify=tk.LEFT,
        ).pack(anchor="w", pady=(2, 0))
        tk.Checkbutton(
            swing_in, text="Automatically place swing trades", variable=self._auto_execute_var,
            bg=CARD_BG, fg=TEXT, selectcolor=PANEL, activebackground=CARD_BG,
            activeforeground=TEXT, font=self._m.font(10), command=self._on_trade_setting_changed,
        ).pack(anchor="w", pady=(8, 0))

        day_card = tk.Frame(tin, bg=CARD_BG, highlightbackground=ACCENT, highlightthickness=1)
        day_card.pack(fill=tk.X, pady=(0, self._m.px(6)))
        day_in = tk.Frame(day_card, bg=CARD_BG)
        day_in.pack(fill=tk.X, padx=12, pady=10)
        tk.Label(day_in, text="Day trading", bg=CARD_BG, fg=ACCENT2, font=self._m.font(11, "bold")).pack(anchor="w")
        tk.Label(
            day_in,
            text="Shorter trades on agent portfolio picks. Runs automatically every 5 minutes "
                 "(in this app and when closed via the background worker). Closes positions same day.",
            bg=CARD_BG, fg=MUTED, font=self._m.font(9), wraplength=self._m.px(700), justify=tk.LEFT,
        ).pack(anchor="w", pady=(2, 0))
        tk.Checkbutton(
            day_in, text="Enable day trading", variable=self._day_trading_var,
            bg=CARD_BG, fg=ACCENT2, selectcolor=PANEL, activebackground=CARD_BG,
            activeforeground=ACCENT2, font=self._m.font(10, "bold"), command=self._on_trade_setting_changed,
        ).pack(anchor="w", pady=(8, 0))
        self._day_status_label = tk.Label(day_in, text="Day positions: —", bg=CARD_BG, fg=MUTED, font=self._m.font(9))
        self._day_status_label.pack(anchor="w", pady=(4, 0))

        tk.Checkbutton(
            tin, text="Practice mode — dry run only (no real orders sent to E*TRADE)",
            variable=self._dry_run_var, bg=PANEL, fg=WARN, selectcolor="#0d1424",
            activebackground=PANEL, activeforeground=WARN, font=self._m.font(10),
            command=self._on_trade_setting_changed,
        ).pack(anchor="w", pady=(self._m.px(4), 0))

        # --- Capital limit: max $ or % of account the buy app may deploy ---
        cap_panel = self._panel(body, title="Capital limit (buy app)")
        cap_panel.pack(fill=tk.X, padx=pad_x, pady=(0, self._m.px(10)))
        cin_cap = cap_panel._inner  # type: ignore[attr-defined]
        tk.Label(
            cin_cap,
            text=(
                "Limit how much of your account this buy app can use. "
                "Example: account has $20,000 — set a fixed $5,000, or a percentage of free equity."
            ),
            bg=PANEL, fg=MUTED, font=self._m.font(9), wraplength=self._m.px(700), justify=tk.LEFT,
        ).pack(anchor="w", pady=(self._m.px(8), self._m.px(6)))

        mode_row = tk.Frame(cin_cap, bg=PANEL)
        mode_row.pack(fill=tk.X, pady=(0, self._m.px(6)))
        for value, label in (
            ("pct", "Percentage of free equity"),
            ("usd", "Fixed dollar amount"),
            ("off", "No limit (full free equity)"),
        ):
            tk.Radiobutton(
                mode_row,
                text=label,
                variable=self._capital_cap_mode_var,
                value=value,
                bg=PANEL,
                fg=TEXT,
                selectcolor=CARD_BG,
                activebackground=PANEL,
                activeforeground=TEXT,
                font=self._m.font(10),
                command=self._on_capital_cap_changed,
            ).pack(anchor="w", pady=1)

        fields = tk.Frame(cin_cap, bg=PANEL)
        fields.pack(fill=tk.X, pady=(self._m.px(4), self._m.px(4)))

        pct_row = tk.Frame(fields, bg=PANEL)
        pct_row.pack(fill=tk.X, pady=2)
        tk.Label(pct_row, text="Max % of free equity", bg=PANEL, fg=TEXT, font=self._m.font(9), width=22, anchor="w").pack(side=tk.LEFT)
        self._capital_cap_pct_entry = tk.Entry(
            pct_row, textvariable=self._capital_cap_pct_var, bg=CARD_BG, fg=TEXT,
            insertbackground=TEXT, relief=tk.FLAT, font=self._m.font(10), width=10,
        )
        self._capital_cap_pct_entry.pack(side=tk.LEFT, ipady=4, padx=(0, 6))
        tk.Label(pct_row, text="%", bg=PANEL, fg=MUTED, font=self._m.font(9)).pack(side=tk.LEFT)
        self._capital_cap_pct_entry.bind("<FocusOut>", lambda _e: self._on_capital_cap_changed())
        self._capital_cap_pct_entry.bind("<Return>", lambda _e: self._on_capital_cap_changed())

        usd_row = tk.Frame(fields, bg=PANEL)
        usd_row.pack(fill=tk.X, pady=2)
        tk.Label(usd_row, text="Max dollars ($)", bg=PANEL, fg=TEXT, font=self._m.font(9), width=22, anchor="w").pack(side=tk.LEFT)
        self._capital_cap_usd_entry = tk.Entry(
            usd_row, textvariable=self._capital_cap_usd_var, bg=CARD_BG, fg=TEXT,
            insertbackground=TEXT, relief=tk.FLAT, font=self._m.font(10), width=10,
        )
        self._capital_cap_usd_entry.pack(side=tk.LEFT, ipady=4, padx=(0, 6))
        tk.Label(usd_row, text="e.g. 5000", bg=PANEL, fg=MUTED, font=self._m.font(9)).pack(side=tk.LEFT)
        self._capital_cap_usd_entry.bind("<FocusOut>", lambda _e: self._on_capital_cap_changed())
        self._capital_cap_usd_entry.bind("<Return>", lambda _e: self._on_capital_cap_changed())

        self._capital_cap_status = tk.Label(
            cin_cap, text="", bg=PANEL, fg=MUTED, font=self._m.font(9), wraplength=self._m.px(700), justify=tk.LEFT,
        )
        self._capital_cap_status.pack(anchor="w", pady=(self._m.px(4), 0))
        self._update_capital_cap_ui_state()
        self._refresh_capital_cap_status()

        control = self._panel(body, title="Automation control")
        control.pack(fill=tk.X, padx=pad_x, pady=(0, self._m.px(14)))
        cin = control._inner  # type: ignore[attr-defined]
        self._automation_status_label = tk.Label(
            cin,
            text="Agents, strategy, swing orders, and day trading run automatically in the background.",
            bg=PANEL, fg=MUTED, font=self._m.font(9), wraplength=self._m.px(700), justify=tk.LEFT,
        )
        self._automation_status_label.pack(anchor="w", pady=(self._m.px(8), self._m.px(10)))
        ctrl_row = tk.Frame(cin, bg=PANEL)
        ctrl_row.pack(fill=tk.X)
        self._btn_stop_all = self._make_btn(
            ctrl_row, "Stop all", self._toggle_automation_pause, variant="danger",
        )
        self._update_automation_control_ui()

    def _build_agents_tab(self) -> None:
        try:
            from finance_agents_gui import FinanceAgentsApp

            self._finance_agents = FinanceAgentsApp(parent=self._tab_agents, embedded=True)
        except Exception as exc:
            self._finance_agents = None
            tk.Label(
                self._tab_agents,
                text=(
                    "Agents panel could not load.\n\n"
                    f"{exc}\n\n"
                    "Run Install ETrade Trader.bat to rebuild the app, or launch via pythonw."
                ),
                bg=PANEL,
                fg=DOWN,
                font=self._m.font(10),
                justify=tk.LEFT,
                wraplength=self._m.px(700),
            ).pack(fill=tk.BOTH, expand=True, padx=self._m.px(20), pady=self._m.px(20))
            _log_crash(f"Agents tab load error: {exc}\n{traceback.format_exc()}")
        self._update_reports_card()

    def _select_agents_tab(self) -> None:
        self._notebook.select(self._tab_agents)

    def _on_main_tab_changed(self, _event: tk.Event | None = None) -> None:
        try:
            selected = str(self._notebook.select())
        except tk.TclError:
            return
        self._schedule_layout_save()
        if selected == str(self._tab_agents) and self._finance_agents is not None:
            self._finance_agents.refresh_agent_statuses()
        elif selected == str(self._tab_log):
            try:
                self._log.see("1.0")
            except tk.TclError:
                pass

    def _refresh_reports_ui(self, *, select_latest: bool = False) -> None:
        if self._finance_agents is not None:
            self._finance_agents.refresh_ui(select_latest=select_latest)
        self._update_reports_card()

    def _update_reports_card(self) -> None:
        if not hasattr(self, "_card_reports"):
            return
        if self._finance_agents is not None:
            fresh, total = self._finance_agents.fresh_report_counts()
        else:
            fresh, total = 0, 0
        self._set_card(self._card_reports, f"{fresh}/{total}", ACCENT2 if fresh else MUTED)

    def _build_ui(self) -> None:
        pad = self._m.px(8) if self._embedded else self._pad()

        header = tk.Frame(self, bg=BG)
        header.pack(fill=tk.X, padx=pad, pady=(self._m.px(4 if self._embedded else 10), self._m.px(2 if self._embedded else 4)))
        title_row = tk.Frame(header, bg=BG)
        title_row.pack(fill=tk.X)
        title_block = tk.Frame(title_row, bg=BG)
        title_block.pack(side=tk.LEFT, fill=tk.X, expand=True)
        if self._embedded:
            # Compact one-line header when nested in unified UI
            tk.Label(
                title_block,
                text=self._app_title,
                bg=BG,
                fg=TEXT,
                font=self._m.font(12, "bold"),
            ).pack(side=tk.LEFT)
        else:
            tk.Label(title_block, text="E*TRADE Trader", bg=BG, fg=TEXT, font=self._m.font(18, "bold")).pack(anchor="w")
            tk.Label(
                title_block,
                text="Agent research · automated swing & day trading",
                bg=BG,
                fg=MUTED,
                font=self._m.font(9),
            ).pack(anchor="w", pady=(self._m.px(2), 0))
        self._env_badge = tk.Label(
            title_row,
            text="  Not configured  ",
            bg=CARD_BG,
            fg=MUTED,
            font=self._m.font(8, "bold"),
            padx=self._m.px(8),
            pady=self._m.px(4),
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        self._env_badge.pack(side=tk.RIGHT, anchor="n")

        conn = tk.Frame(self, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        conn.pack(fill=tk.X, padx=pad, pady=(0, self._m.px(2 if self._embedded else 4)))
        conn_inner = tk.Frame(conn, bg=CARD_BG)
        conn_inner.pack(fill=tk.X, padx=self._m.px(8 if self._embedded else 10), pady=self._m.px(4 if self._embedded else 6))

        conn_row = tk.Frame(conn_inner, bg=CARD_BG)
        conn_row.pack(fill=tk.X)
        self._conn_status = tk.Label(conn_row, text="● Offline", bg=CARD_BG, fg=DOWN, font=self._m.font(9, "bold"))
        self._conn_status.pack(side=tk.LEFT, padx=(0, self._m.px(10)))
        tk.Label(conn_row, text="Account", bg=CARD_BG, fg=MUTED, font=self._m.font(8, "bold")).pack(
            side=tk.LEFT, padx=(0, self._m.px(4)),
        )
        self._account_combo = ttk.Combobox(
            conn_row,
            textvariable=self._account_var,
            state="readonly",
            values=[ACCOUNT_PLACEHOLDER],
            style="Trader.TCombobox",
            width=28,
        )
        self._account_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, self._m.px(6)))
        self._account_combo.current(0)
        self._account_var.set(ACCOUNT_PLACEHOLDER)
        self._account_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_account_changed())
        conn_btns = tk.Frame(conn_row, bg=CARD_BG)
        conn_btns.pack(side=tk.RIGHT)
        self._make_btn(conn_btns, "Connect", self._connect, variant="primary", padx=(0, 4), compact=True)
        self._make_btn(conn_btns, "Disconnect", self._disconnect, variant="secondary", padx=(0, 4), compact=True)
        self._make_btn(conn_btns, "Refresh", self._refresh_account, variant="secondary", padx=(0, 4), compact=True)
        self._make_btn(conn_btns, "Settings", self._show_setup_tab, variant="secondary", compact=True)

        self._sandbox_notice = tk.Frame(self, bg="#2a2200", highlightbackground=WARN, highlightthickness=1)
        notice_inner = tk.Frame(self._sandbox_notice, bg="#2a2200")
        notice_inner.pack(fill=tk.X, padx=pad, pady=self._m.px(8))
        self._sandbox_notice_label = tk.Label(
            notice_inner,
            text="",
            bg="#2a2200", fg=WARN, font=self._m.font(9), wraplength=self._m.px(900), justify=tk.LEFT,
        )
        self._sandbox_notice_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._make_btn(
            notice_inner, "Use My Real Accounts", self._switch_to_production_accounts,
            variant="accent", padx=(self._m.px(10), 0),
        )

        self._body_frame = tk.Frame(self, bg=BG)
        self._body_frame.pack(fill=tk.BOTH, expand=True, padx=pad, pady=(0, self._m.px(4)))

        self._notebook = ttk.Notebook(self._body_frame, style="Trader.TNotebook")
        self._notebook.pack(fill=tk.BOTH, expand=True)

        self._tab_dashboard = tk.Frame(self._notebook, bg=BG)
        self._tab_agents = tk.Frame(self._notebook, bg=PANEL)
        self._tab_trades = tk.Frame(self._notebook, bg=PANEL)
        self._tab_setup = tk.Frame(self._notebook, bg=PANEL)
        self._tab_log = tk.Frame(self._notebook, bg=PANEL)
        self._notebook.add(self._tab_dashboard, text="  Home  ")
        self._notebook.add(self._tab_agents, text="  Agents  ")
        self._notebook.add(self._tab_trades, text="  Trades  ")
        self._notebook.add(self._tab_setup, text="  Settings  ")
        self._notebook.add(self._tab_log, text="  Activity  ")
        self._notebook.bind("<<NotebookTabChanged>>", self._on_main_tab_changed)

        self._build_dashboard_tab()
        self._build_agents_tab()
        self._build_setup_tab()

        self._trades_detail_hidden = False
        self._trades_splitter = tk.PanedWindow(
            self._tab_trades,
            orient=tk.HORIZONTAL,
            bg=PANEL,
            sashwidth=self._m.px(5),
            sashrelief=tk.FLAT,
            opaqueresize=True,
            showhandle=False,
        )
        self._trades_splitter.pack(fill=tk.BOTH, expand=True, padx=self._m.px(4), pady=self._m.px(4))
        self._trades_splitter.bind("<ButtonRelease-1>", lambda _e: self._schedule_layout_save())

        trades_data = tk.Frame(self._trades_splitter, bg=PANEL)
        self._trades_splitter.add(trades_data, minsize=self._m.px(520))

        self._trades_notebook = ttk.Notebook(trades_data, style="Trader.Trades.TNotebook")
        self._trades_notebook.pack(fill=tk.BOTH, expand=True, padx=self._m.px(2), pady=self._m.px(2))

        self._tab_overview = tk.Frame(self._trades_notebook, bg=PANEL)
        self._tab_holdings = tk.Frame(self._trades_notebook, bg=PANEL)
        self._tab_orders = tk.Frame(self._trades_notebook, bg=PANEL)
        self._tab_performance = tk.Frame(self._trades_notebook, bg=PANEL)
        self._trades_notebook.add(self._tab_overview, text="  Overview  ")
        self._trades_notebook.add(self._tab_holdings, text="  Holdings  ")
        self._trades_notebook.add(self._tab_orders, text="  Orders  ")
        self._trades_notebook.add(self._tab_performance, text="  Performance  ")
        self._trades_notebook.bind("<<NotebookTabChanged>>", self._on_trades_tab_changed)

        self._build_overview_tab()
        self._build_holdings_tab()
        self._build_orders_tab()
        self._build_performance_tab()

        self._trades_detail_panel = tk.Frame(self._trades_splitter, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        self._trades_splitter.add(self._trades_detail_panel, minsize=self._m.px(260), width=self._m.px(340))
        detail_head = tk.Frame(self._trades_detail_panel, bg=CARD_BG)
        detail_head.pack(fill=tk.X, padx=self._m.px(8), pady=(self._m.px(6), self._m.px(2)))
        self._trade_detail_title = tk.Label(
            detail_head,
            text="Analysis",
            bg=CARD_BG,
            fg=TEXT,
            font=self._m.font(10, "bold"),
            anchor="w",
        )
        self._trade_detail_title.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._trade_detail_toggle_btn = self._make_btn(
            detail_head,
            "Hide",
            self._toggle_trades_detail_panel,
            variant="secondary",
            compact=True,
        )
        detail_body = tk.Frame(self._trades_detail_panel, bg=CARD_BG)
        detail_body.pack(fill=tk.BOTH, expand=True, padx=self._m.px(6), pady=(0, self._m.px(6)))
        detail_body.rowconfigure(2, weight=1)
        detail_body.columnconfigure(0, weight=1)

        from position_chart import CandleChartWidget

        self._trade_chart_token = 0
        self._trade_detail_chart = CandleChartWidget(
            detail_body,
            width=self._m.px(300),
            height=self._m.px(140),
            bg=CARD_BG,
            up_color=UP,
            down_color=DOWN,
            text_color=MUTED,
            grid_color=BORDER,
            font=self._m.font(8),
        )
        self._trade_detail_chart.grid(row=0, column=0, sticky="ew", pady=(0, self._m.px(4)))
        self._trade_detail_chart.show_placeholder()

        self._trade_detail_projection = tk.Label(
            detail_body,
            text="",
            bg=CARD_BG,
            fg=UP,
            font=self._m.font(10, "bold"),
            anchor="w",
            justify=tk.LEFT,
            wraplength=self._m.px(300),
        )
        self._trade_detail_projection.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=self._m.px(4),
            pady=(0, self._m.px(4)),
        )

        detail_text_frame = tk.Frame(detail_body, bg=CARD_BG)
        detail_text_frame.grid(row=2, column=0, sticky="nsew")
        detail_text_frame.rowconfigure(0, weight=1)
        detail_text_frame.columnconfigure(0, weight=1)
        self._trade_detail_text = tk.Text(
            detail_text_frame,
            bg=CARD_BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief=tk.FLAT,
            wrap=tk.WORD,
            font=self._m.font(9),
            padx=self._m.px(6),
            pady=self._m.px(6),
            height=8,
            state=tk.DISABLED,
        )
        detail_scroll = ttk.Scrollbar(
            detail_text_frame,
            orient=tk.VERTICAL,
            command=self._trade_detail_text.yview,
            style="Trader.Vertical.TScrollbar",
        )
        self._trade_detail_text.configure(yscrollcommand=detail_scroll.set)
        self._trade_detail_text.grid(row=0, column=0, sticky="nsew")
        detail_scroll.grid(row=0, column=1, sticky="ns")
        self._trade_detail_text.insert(
            tk.END,
            "Select a row in Holdings or Orders to see agent reasoning and a 10-day chart.",
        )
        self._window.bind("<Configure>", self._on_window_configure, add="+")
        self.after(200, self._restore_saved_layout)

        log_frame = tk.Frame(self._tab_log, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=self._m.px(8), pady=self._m.px(8))
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self._log = tk.Text(
            log_frame,
            bg=CARD_BG,
            fg=TEXT,
            font=self._m.mono(12),
            relief=tk.FLAT,
            wrap=tk.NONE,
            spacing1=3,
            spacing3=3,
            padx=self._m.px(10),
            pady=self._m.px(10),
        )
        log_yscroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self._log.yview, style="Trader.Vertical.TScrollbar")
        log_xscroll = ttk.Scrollbar(log_frame, orient=tk.HORIZONTAL, command=self._log.xview, style="Trader.Horizontal.TScrollbar")
        self._log.configure(yscrollcommand=log_yscroll.set, xscrollcommand=log_xscroll.set)
        self._log.grid(row=0, column=0, sticky="nsew")
        log_yscroll.grid(row=0, column=1, sticky="ns")
        log_xscroll.grid(row=1, column=0, sticky="ew")

        footer = tk.Frame(self, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        foot = tk.Frame(footer, bg=CARD_BG)
        foot.pack(fill=tk.X, padx=pad, pady=self._m.px(7))
        self._status_dot = tk.Label(foot, text="●", bg=CARD_BG, fg=ACCENT2, font=self._m.font(11))
        self._status_dot.pack(side=tk.LEFT)
        self._status_label = tk.Label(foot, text="Ready", bg=CARD_BG, fg=TEXT, font=self._m.font(10))
        self._status_label.pack(side=tk.LEFT, padx=(6, 0))
        self._progress = ttk.Progressbar(foot, mode="indeterminate", style="Trader.Horizontal.TProgressbar",
                                       length=self._m.px(140))

        from datetime import datetime
        welcome_ts = datetime.now().strftime("%H:%M:%S")
        for welcome_msg in (
            "Welcome! Connect your account on Home, enable day trading if you want — it runs every 5 min in the background.",
            "Keeps running when closed: run Install ETrade Background.bat once.",
            "New here? Open Settings and follow the 4-step wizard.",
        ):
            self._log.insert(tk.END, f"[{welcome_ts}] {welcome_msg}\n")
        self._sync_trade_flags()
        self._update_sandbox_notice()
        self._refresh_day_trading_panel()
        self._update_automation_control_ui()
        self._show_dashboard_tab()


    def _entry(self, parent: tk.Misc, textvariable: tk.StringVar, *, show: str = "", width: int = 42) -> tk.Entry:
        entry = tk.Entry(
            parent,
            textvariable=textvariable,
            bg="#0d1424",
            fg=TEXT,
            insertbackground=TEXT,
            relief=tk.FLAT,
            font=self._m.font(10),
            show=show,
            width=width,
        )
        entry.pack(fill=tk.X, ipady=self._m.px(7))
        return entry

    def _section(self, parent: tk.Misc, title: str, subtitle: str = "", *, step: int = 0) -> tk.Frame:
        block = tk.Frame(parent, bg="#0d1424", highlightbackground=BORDER, highlightthickness=1)
        inner = tk.Frame(block, bg="#0d1424")
        inner.pack(fill=tk.BOTH, expand=True, padx=self._m.px(16), pady=self._m.px(14))
        head = tk.Frame(inner, bg="#0d1424")
        head.pack(fill=tk.X, pady=(0, self._m.px(10)))
        title_row = tk.Frame(head, bg="#0d1424")
        title_row.pack(fill=tk.X)
        if step:
            tk.Label(title_row, text=f" {step} ", bg=BORDER, fg=ACCENT2, font=self._m.font(9, "bold")).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(title_row, text=title, bg="#0d1424", fg=TEXT, font=self._m.font(12, "bold")).pack(side=tk.LEFT, anchor="w")
        if subtitle:
            tk.Label(head, text=subtitle, bg="#0d1424", fg=MUTED, font=self._m.font(9), wraplength=self._m.px(720), justify=tk.LEFT).pack(anchor="w", pady=(4, 0))
        block._inner = inner  # type: ignore[attr-defined]
        block._step = step  # type: ignore[attr-defined]
        return block

    def _form_row(self, parent: tk.Misc, label: str, hint: str = "") -> tk.Frame:
        row = tk.Frame(parent, bg="#0d1424")
        row.pack(fill=tk.X, pady=(0, self._m.px(10)))
        tk.Label(row, text=label, bg="#0d1424", fg=TEXT, font=self._m.font(10, "bold")).pack(anchor="w")
        if hint:
            tk.Label(row, text=hint, bg="#0d1424", fg=MUTED, font=self._m.font(8), wraplength=self._m.px(680), justify=tk.LEFT).pack(anchor="w", pady=(2, 4))
        return row

    def _build_setup_tab(self) -> None:
        outer = tk.Frame(self._tab_setup, bg=PANEL)
        outer.pack(fill=tk.BOTH, expand=True, padx=self._m.px(14), pady=self._m.px(14))

        canvas = tk.Canvas(outer, bg=PANEL, highlightthickness=0)
        self._setup_canvas = canvas
        scroll = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        self._setup_scroll = tk.Frame(canvas, bg=PANEL)
        self._setup_scroll.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._setup_scroll, anchor="nw", tags="setup_window")
        canvas.bind("<Configure>", self._on_setup_canvas_resize)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._bind_setup_scroll(canvas)
        wrap = self._setup_scroll
        self._setup_sections.clear()

        tk.Label(wrap, text="Settings & setup", bg=PANEL, fg=TEXT, font=self._m.font(18, "bold")).pack(anchor="w")
        tk.Label(
            wrap,
            text="Connect your E*TRADE account in four steps. Start in Sandbox (paper money) to test safely before going live.",
            bg=PANEL, fg=MUTED, font=self._m.font(10), wraplength=self._m.px(760), justify=tk.LEFT,
        ).pack(anchor="w", pady=(4, self._m.px(12)))

        self._build_appearance_section(wrap)

        hero = tk.Frame(wrap, bg="#0d1424", highlightbackground=ACCENT, highlightthickness=1)
        hero.pack(fill=tk.X, pady=(0, self._m.px(14)))
        hero_inner = tk.Frame(hero, bg="#0d1424")
        hero_inner.pack(fill=tk.X, padx=self._m.px(16), pady=self._m.px(14))
        hero_top = tk.Frame(hero_inner, bg="#0d1424")
        hero_top.pack(fill=tk.X)
        self._setup_progress_label = tk.Label(
            hero_top, text="0 of 4 steps complete", bg="#0d1424", fg=TEXT, font=self._m.font(11, "bold"),
        )
        self._setup_progress_label.pack(side=tk.LEFT)
        self._setup_next_btn = tk.Button(
            hero_top, text="Continue to Step 1", command=self._go_to_next_setup_step,
            bg=ACCENT, fg="#fff", activebackground="#5a4bd6", relief=tk.FLAT,
            font=self._m.font(10, "bold"), padx=self._m.px(14), pady=self._m.px(8), cursor="hand2", bd=0,
        )
        self._setup_next_btn.pack(side=tk.RIGHT)
        self._setup_progress_bar = ttk.Progressbar(
            hero_inner, mode="determinate", maximum=4, style="Trader.Horizontal.TProgressbar",
        )
        self._setup_progress_bar.pack(fill=tk.X, pady=(self._m.px(10), self._m.px(6)))
        self._setup_next_hint = tk.Label(
            hero_inner, text="Enter your API credentials to get started.", bg="#0d1424", fg=MUTED, font=self._m.font(9),
        )
        self._setup_next_hint.pack(anchor="w")

        progress = tk.Frame(wrap, bg=PANEL)
        progress.pack(fill=tk.X, pady=(0, self._m.px(16)))
        steps = [
            ("1", "API Keys"),
            ("2", "Connect"),
            ("3", "Account"),
            ("4", "Ready"),
        ]
        self._setup_step_icons.clear()
        self._setup_step_labels.clear()
        for idx, (num, label) in enumerate(steps):
            cell = tk.Frame(progress, bg=PANEL, cursor="hand2")
            cell.pack(side=tk.LEFT, padx=(0, self._m.px(18)))
            cell.bind("<Button-1>", lambda e, i=idx: self._scroll_to_setup_step(i))
            icon = tk.Label(cell, text="○", bg=PANEL, fg=MUTED, font=self._m.font(14, "bold"), cursor="hand2")
            icon.pack()
            icon.bind("<Button-1>", lambda e, i=idx: self._scroll_to_setup_step(i))
            tk.Label(cell, text=f"Step {num}", bg=PANEL, fg=MUTED, font=self._m.font(8), cursor="hand2").pack()
            lbl = tk.Label(cell, text=label, bg=PANEL, fg=TEXT, font=self._m.font(9, "bold"), cursor="hand2")
            lbl.pack()
            lbl.bind("<Button-1>", lambda e, i=idx: self._scroll_to_setup_step(i))
            self._setup_step_icons.append(icon)
            self._setup_step_labels.append(lbl)
            if idx < len(steps) - 1:
                tk.Label(progress, text="→", bg=PANEL, fg=BORDER, font=self._m.font(12)).pack(side=tk.LEFT, padx=(0, self._m.px(10)))

        guide = self._section(
            wrap,
            "How to get API keys (one-time)",
            "Do this once at developer.etrade.com before entering credentials below.",
        )
        guide.pack(fill=tk.X, pady=(0, self._m.px(12)))
        guide_inner = guide._inner
        for n, text in (
            ("1", "Sign in at developer.etrade.com and create a new application."),
            ("2", "Set the callback URL to the value below (required for browser login)."),
            ("3", "Copy your Consumer Key and Consumer Secret into Step 1."),
            ("4", "Choose Sandbox for testing — switch to Production only when you're confident."),
        ):
            row = tk.Frame(guide_inner, bg="#0d1424")
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=n, bg=BORDER, fg=ACCENT2, font=self._m.font(9, "bold"), width=2).pack(side=tk.LEFT, padx=(0, 8))
            tk.Label(row, text=text, bg="#0d1424", fg=MUTED, font=self._m.font(9), wraplength=self._m.px(680), justify=tk.LEFT).pack(side=tk.LEFT, anchor="w")

        cb_row = tk.Frame(guide_inner, bg="#0d1424")
        cb_row.pack(fill=tk.X, pady=(self._m.px(10), 0))
        tk.Label(cb_row, text="Callback URL", bg="#0d1424", fg=TEXT, font=self._m.font(9, "bold")).pack(anchor="w")
        cb_inner = tk.Frame(cb_row, bg="#0d1424")
        cb_inner.pack(fill=tk.X, pady=(4, 0))
        self._callback_var = tk.StringVar(value=DEFAULT_CALLBACK_URL)
        cb_entry = tk.Entry(
            cb_inner, textvariable=self._callback_var, bg=PANEL, fg=ACCENT2, relief=tk.FLAT,
            font=self._m.mono(9), state="readonly", readonlybackground=PANEL,
        )
        cb_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=self._m.px(6))
        self._make_btn(cb_inner, "Copy", self._copy_callback_url, variant="secondary", padx=(8, 0))
        self._make_btn(guide_inner, "Open Developer Portal", lambda: webbrowser.open(DEV_PORTAL_URL), variant="secondary")

        creds = self._section(
            wrap,
            "Enter API credentials",
            "Paste the Consumer Key and Secret from your developer application.",
            step=1,
        )
        creds.pack(fill=tk.X, pady=(0, self._m.px(12)))
        self._setup_sections.append(creds)
        creds_inner = creds._inner

        btn_row = tk.Frame(creds_inner, bg="#0d1424")
        btn_row.pack(fill=tk.X, pady=(0, self._m.px(10)))
        self._make_btn(btn_row, "Create Config File", self._create_config_file, variant="secondary", padx=(0, 6))

        key_row = self._form_row(creds_inner, "Consumer Key", "From your E*TRADE developer application dashboard.")
        key_field = tk.Frame(key_row, bg="#0d1424")
        key_field.pack(fill=tk.X)
        self._entry(key_field, self._key_var)
        self._key_status = tk.Label(key_field, text="", bg="#0d1424", fg=MUTED, font=self._m.font(8))
        self._key_status.pack(anchor="w", pady=(4, 0))

        secret_row = self._form_row(creds_inner, "Consumer Secret", "Keep this private — stored only on your computer.")
        secret_field = tk.Frame(secret_row, bg="#0d1424")
        secret_field.pack(fill=tk.X)
        self._secret_entry = self._entry(secret_field, self._secret_var, show="•")
        self._secret_status = tk.Label(secret_field, text="", bg="#0d1424", fg=MUTED, font=self._m.font(8))
        self._secret_status.pack(anchor="w", pady=(4, 0))
        self._show_secret_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            secret_row, text="Show secret", variable=self._show_secret_var, command=self._toggle_secret_visibility,
            bg="#0d1424", fg=MUTED, selectcolor=PANEL, activebackground="#0d1424", activeforeground=TEXT,
            font=self._m.font(9),
        ).pack(anchor="w", pady=(4, 0))

        env_row = tk.Frame(creds_inner, bg="#0d1424")
        env_row.pack(fill=tk.X, pady=(0, self._m.px(10)))
        tk.Label(env_row, text="Environment", bg="#0d1424", fg=TEXT, font=self._m.font(10, "bold")).pack(anchor="w")
        radios = tk.Frame(env_row, bg="#0d1424")
        radios.pack(anchor="w", pady=(6, 0))
        tk.Radiobutton(
            radios, text="Sandbox (recommended — paper trading)", variable=self._sandbox_var, value=True,
            bg="#0d1424", fg=TEXT, selectcolor=PANEL, activebackground="#0d1424", font=self._m.font(10),
            command=self._on_env_changed,
        ).pack(anchor="w")
        tk.Radiobutton(
            radios, text="Production (live money — advanced users only)", variable=self._sandbox_var, value=False,
            bg="#0d1424", fg=WARN, selectcolor=PANEL, activebackground="#0d1424", font=self._m.font(10),
            command=self._on_env_changed,
        ).pack(anchor="w", pady=(4, 0))

        oob_row = tk.Frame(creds_inner, bg="#0d1424")
        oob_row.pack(fill=tk.X, pady=(0, self._m.px(10)))
        tk.Checkbutton(
            oob_row,
            text="Use verification code (OOB) — required if E*TRADE shows a code instead of redirecting",
            variable=self._oob_var,
            bg="#0d1424", fg=TEXT, selectcolor=PANEL, activebackground="#0d1424",
            activeforeground=TEXT, font=self._m.font(9), wraplength=self._m.px(680), justify=tk.LEFT,
        ).pack(anchor="w")

        save_row = tk.Frame(creds_inner, bg="#0d1424")
        save_row.pack(fill=tk.X)
        self._make_btn(save_row, "Save Settings", self._save_settings, variant="accent", padx=(0, 6))
        self._make_btn(save_row, "Test API Keys", self._test_api_keys, variant="secondary", padx=(0, 6))
        self._setup_save_status = tk.Label(save_row, text="", bg="#0d1424", fg=MUTED, font=self._m.font(9))
        self._setup_save_status.pack(side=tk.LEFT)

        auth = self._section(
            wrap,
            "Authorize this app",
            "Click Connect — your browser opens E*TRADE to sign in. We only store a local access token, never your password.",
            step=2,
        )
        auth.pack(fill=tk.X, pady=(0, self._m.px(12)))
        self._setup_sections.append(auth)
        auth_inner = auth._inner
        self._setup_auth_status = tk.Label(auth_inner, text="Status: Not connected", bg="#0d1424", fg=DOWN, font=self._m.font(10))
        self._setup_auth_status.pack(anchor="w", pady=(0, self._m.px(6)))
        tk.Label(
            auth_inner,
            text=(
                "Click Connect — a verification window opens. Sign in to E*TRADE, accept access, "
                "then paste the code shown on the E*TRADE page."
            ),
            bg="#0d1424", fg=MUTED, font=self._m.font(9), wraplength=self._m.px(680), justify=tk.LEFT,
        ).pack(anchor="w", pady=(0, self._m.px(10)))
        auth_btns = tk.Frame(auth_inner, bg="#0d1424")
        auth_btns.pack(anchor="w")
        self._make_btn(auth_btns, "Connect to E*TRADE", self._connect, variant="primary", padx=(0, 6))
        self._make_btn(auth_btns, "Disconnect", self._disconnect, variant="secondary")

        acct = self._section(
            wrap,
            "Choose your account",
            "Sandbox shows E*TRADE demo accounts (not your real portfolio). "
            "Switch to Production in Step 1 to see your actual brokerage accounts.",
            step=3,
        )
        acct.pack(fill=tk.X, pady=(0, self._m.px(12)))
        self._setup_sections.append(acct)
        acct_inner = acct._inner
        acct_row = tk.Frame(acct_inner, bg="#0d1424")
        acct_row.pack(fill=tk.X)
        tk.Label(acct_row, text="Account", bg="#0d1424", fg=TEXT, font=self._m.font(10, "bold")).pack(anchor="w")
        combo_row = tk.Frame(acct_row, bg="#0d1424")
        combo_row.pack(fill=tk.X, pady=(6, 0))
        self._setup_account_combo = ttk.Combobox(
            combo_row, textvariable=self._account_var, state="readonly", width=56,
            values=[ACCOUNT_PLACEHOLDER],
        )
        self._setup_account_combo.pack(side=tk.LEFT)
        self._setup_account_combo.current(0)
        self._setup_account_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_account_changed())
        self._make_btn(combo_row, "Refresh Accounts", self._refresh_account, variant="secondary", padx=(8, 0))
        tk.Label(
            acct_inner,
            text=(
                "If the list is empty, click Refresh Accounts after connecting. "
                "Pick an account and confirm — plans and orders use only the account you confirm."
            ),
            bg="#0d1424", fg=MUTED, font=self._m.font(8), wraplength=self._m.px(680), justify=tk.LEFT,
        ).pack(anchor="w", pady=(8, 0))

        ready = self._section(
            wrap,
            "You're ready to trade",
            "Agents and strategy plan update automatically. Use Preview → Execute when ready to trade.",
            step=4,
        )
        ready.pack(fill=tk.X, pady=(0, self._m.px(12)))
        self._setup_sections.append(ready)
        ready_inner = ready._inner
        self._setup_ready_msg = tk.Label(
            ready_inner,
            text="Complete steps 1–3 to unlock automated trading.",
            bg="#0d1424", fg=MUTED, font=self._m.font(10), wraplength=self._m.px(720), justify=tk.LEFT,
        )
        self._setup_ready_msg.pack(anchor="w", pady=(0, self._m.px(10)))
        ready_btns = tk.Frame(ready_inner, bg="#0d1424")
        ready_btns.pack(anchor="w")
        self._make_btn(ready_btns, "Go to Home", self._show_dashboard_tab, variant="primary", padx=(0, 6))
        self._make_btn(ready_btns, "Agents", self._select_agents_tab, variant="secondary", padx=(0, 6))
        self._make_btn(ready_btns, "Trades", lambda: self._show_trades_tab(swing=True), variant="secondary")

        safety = tk.Frame(wrap, bg="#1a2338", highlightbackground=BORDER, highlightthickness=1)
        safety.pack(fill=tk.X, pady=(self._m.px(8), self._m.px(4)))
        safety_inner = tk.Frame(safety, bg="#1a2338")
        safety_inner.pack(fill=tk.X, padx=self._m.px(14), pady=self._m.px(12))
        tk.Label(safety_inner, text="Safety checklist", bg="#1a2338", fg=WARN, font=self._m.font(10, "bold")).pack(anchor="w")
        for tip in (
            "Home tab: choose swing investing, day trading, or both",
            "Trades tab: review swing and day-trade orders before they execute",
            "Practice mode (dry run) simulates trades without sending them to E*TRADE",
            "Keep Sandbox enabled until you have tested the full workflow",
            "Never share your Consumer Secret or token file",
            "This app is a tool — not financial advice",
        ):
            tk.Label(safety_inner, text=f"✓  {tip}", bg="#1a2338", fg=MUTED, font=self._m.font(9)).pack(anchor="w", pady=2)

        help_box = tk.Frame(wrap, bg="#0d1424", highlightbackground=BORDER, highlightthickness=1)
        help_box.pack(fill=tk.X, pady=(self._m.px(8), self._m.px(4)))
        help_inner = tk.Frame(help_box, bg="#0d1424")
        help_inner.pack(fill=tk.X, padx=self._m.px(14), pady=self._m.px(12))
        tk.Label(help_inner, text="Troubleshooting", bg="#0d1424", fg=TEXT, font=self._m.font(10, "bold")).pack(anchor="w")
        for q, a in (
            ("Connect failed or request rejected?", "Save Settings first. If E*TRADE shows a verification code, enable OOB in Setup. Otherwise match the callback URL in the developer portal."),
            ("Browser login fails?", "Confirm Sandbox vs Production matches your developer app environment."),
            ("No accounts in the list?", "Click Refresh Accounts while connected. Disconnect and reconnect if needed."),
            ("Changed API keys?", "Disconnect, update keys, Save Settings, then Connect again."),
        ):
            tk.Label(help_inner, text=q, bg="#0d1424", fg=ACCENT2, font=self._m.font(9, "bold")).pack(anchor="w", pady=(6, 0))
            tk.Label(help_inner, text=a, bg="#0d1424", fg=MUTED, font=self._m.font(8), wraplength=self._m.px(700), justify=tk.LEFT).pack(anchor="w", pady=(0, 2))

        self._key_var.trace_add("write", lambda *_: self._validate_setup_fields())
        self._secret_var.trace_add("write", lambda *_: self._validate_setup_fields())

    def _toggle_secret_visibility(self) -> None:
        self._secret_entry.configure(show="" if self._show_secret_var.get() else "•")

    def _on_setup_canvas_resize(self, event: tk.Event) -> None:
        if self._setup_canvas is not None:
            self._setup_canvas.itemconfigure("setup_window", width=event.width)

    def _bind_setup_scroll(self, canvas: tk.Canvas) -> None:
        def _on_wheel(event: tk.Event) -> None:
            if event.delta:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            elif event.num == 4:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                canvas.yview_scroll(1, "units")

        def _bind_wheel(_event: tk.Event | None = None) -> None:
            canvas.bind_all("<MouseWheel>", _on_wheel)
            canvas.bind_all("<Button-4>", _on_wheel)
            canvas.bind_all("<Button-5>", _on_wheel)

        def _unbind_wheel(_event: tk.Event | None = None) -> None:
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        canvas.bind("<Enter>", _bind_wheel)
        canvas.bind("<Leave>", _unbind_wheel)

    def _scroll_to_setup_step(self, step_index: int) -> None:
        if not self._setup_canvas or step_index >= len(self._setup_sections):
            return
        section = self._setup_sections[step_index]
        self._setup_canvas.update_idletasks()
        y = section.winfo_y()
        total = max(self._setup_scroll.winfo_height(), 1)
        fraction = max(0.0, min(1.0, (y - self._m.px(8)) / total))
        self._setup_canvas.yview_moveto(fraction)

    def _go_to_next_setup_step(self) -> None:
        raw = _read_config_file(self.CONFIG_PATH)
        keys_ok = _config_keys_valid(raw) or (
            self._key_var.get().strip() and self._secret_var.get().strip()
            and self._key_var.get().strip() not in ("", "YOUR_CONSUMER_KEY")
            and self._secret_var.get().strip() not in ("", "YOUR_CONSUMER_SECRET")
        )
        connected = self._client is not None
        has_account = self._confirmed_account_idx is not None and self._confirmed_account_idx > 0
        if not keys_ok:
            self._scroll_to_setup_step(0)
            if not _config_keys_valid(raw):
                messagebox.showinfo("Step 1", "Enter your Consumer Key and Secret, then click Save Settings.")
            return
        if not connected:
            self._scroll_to_setup_step(1)
            self._connect()
            return
        if not self._accounts:
            self._scroll_to_setup_step(2)
            self._refresh_account()
            return
        if not has_account:
            self._scroll_to_setup_step(2)
            messagebox.showinfo(
                "Confirm Account",
                "Accounts are loaded. Select your account from the dropdown and confirm to continue.",
            )
            return
        self._scroll_to_setup_step(3)

    def _copy_callback_url(self) -> None:
        url = self._callback_var.get() or DEFAULT_CALLBACK_URL
        self._window.clipboard_clear()
        self._window.clipboard_append(url)
        self._setup_save_status.configure(text="Callback URL copied to clipboard", fg=ACCENT2)
        self._log_line("Callback URL copied — paste it in the E*TRADE developer portal.")

    def _validate_setup_fields(self) -> None:
        key = self._key_var.get().strip()
        secret = self._secret_var.get().strip()
        placeholders = {"", "YOUR_CONSUMER_KEY", "YOUR_CONSUMER_SECRET"}

        if key and key not in placeholders:
            self._key_status.configure(text="✓ Looks good", fg=UP)
        elif key:
            self._key_status.configure(text="Replace the placeholder with your real key", fg=WARN)
        else:
            self._key_status.configure(text="Required", fg=MUTED)

        if secret and secret not in placeholders:
            self._secret_status.configure(text="✓ Looks good", fg=UP)
        elif secret:
            self._secret_status.configure(text="Replace the placeholder with your real secret", fg=WARN)
        else:
            self._secret_status.configure(text="Required", fg=MUTED)

    def _setup_completion_state(self) -> tuple[int, int, list[bool]]:
        raw = _read_config_file(self.CONFIG_PATH)
        form_valid = (
            self._key_var.get().strip() not in ("", "YOUR_CONSUMER_KEY")
            and self._secret_var.get().strip() not in ("", "YOUR_CONSUMER_SECRET")
        )
        keys_ok = _config_keys_valid(raw) or form_valid
        connected = self._client is not None
        has_account = self._confirmed_account_idx is not None and self._confirmed_account_idx > 0
        all_done = keys_ok and connected and has_account
        completed = sum([keys_ok, connected, has_account, all_done])
        return completed, (0 if not keys_ok else 1 if not connected else 2 if not has_account else 3), [
            keys_ok, connected, has_account, all_done,
        ]

    def _update_env_badge(self, sandbox: bool) -> None:
        if sandbox:
            self._env_badge.configure(
                text="  SANDBOX — demo accounts  ",
                fg="#0a0e17", bg=ACCENT2,
            )
        else:
            self._env_badge.configure(
                text="  PRODUCTION — your accounts  ",
                fg="#fff", bg=DOWN,
            )
        self._update_sandbox_notice()

    def _update_sandbox_notice(self) -> None:
        pad = self._pad()
        sandbox = bool(self._config and self._config.sandbox) or (
            not self._config and self._sandbox_var.get()
        )
        if not sandbox:
            self._sandbox_notice.pack_forget()
            return

        demo = accounts_look_like_sandbox_demo(self._accounts)
        if demo or self._accounts:
            text = (
                "You are connected to E*TRADE Sandbox. The accounts listed here are E*TRADE demo accounts "
                "(paper trading), not your real brokerage accounts."
            )
        else:
            text = (
                "Sandbox mode is on. Accounts shown here are for testing only, not your real E*TRADE portfolio."
            )
        self._sandbox_notice_label.configure(text=text)
        try:
            if not self._sandbox_notice.winfo_ismapped():
                self._sandbox_notice.pack(fill=tk.X, padx=pad, pady=(0, self._m.px(8)), before=self._body_frame)
        except tk.TclError:
            pass

    def _switch_to_production_accounts(self) -> None:
        if not messagebox.askyesno(
            "Switch to Real Accounts",
            "This will switch to PRODUCTION and connect to your real E*TRADE accounts.\n\n"
            "Trades can use real money. Check Dry run if you want simulation only.\n\n"
            "You must Disconnect and Connect again after saving.\n\n"
            "Continue?",
        ):
            return
        self._sandbox_var.set(False)
        self._save_settings()
        if self._client:
            self._disconnect()
        self._show_setup_tab()
        messagebox.showinfo(
            "Reconnect Required",
            "Production mode saved.\n\n"
            "1. Click Connect to E*TRADE\n"
            "2. Sign in with your real E*TRADE username\n"
            "3. Paste the verification code\n"
            "4. Refresh Accounts — you should see your real accounts",
        )

    def _on_env_changed(self) -> None:
        if not self._sandbox_var.get():
            if not messagebox.askyesno(
                "Production Mode",
                "Production connects to your REAL E*TRADE accounts and can place live trades.\n\n"
                "Sandbox accounts (like NickName-1) are demo-only and will be replaced\n"
                "by your actual accounts after you reconnect in Production.\n\n"
                "Switch to Production?",
            ):
                self._sandbox_var.set(True)
        self._update_sandbox_notice()

    def _show_setup_tab(self) -> None:
        self._notebook.select(self._tab_setup)

    def _create_config_file(self) -> None:
        if self.CONFIG_PATH.exists():
            messagebox.showinfo("Config Exists", f"{self.CONFIG_PATH.name} already exists. Edit the fields below and click Save Settings.")
            return
        if self.CONFIG_EXAMPLE.exists():
            shutil.copy(self.CONFIG_EXAMPLE, self.CONFIG_PATH)
        else:
            _write_config_file(self.CONFIG_PATH, {"consumer_key": "", "consumer_secret": "", "sandbox": True})
        self._load_settings_form()
        self._log_line(f"Created {self.CONFIG_PATH.name}")
        self._setup_save_status.configure(text="Config file created — enter your keys", fg=ACCENT2)

    def _load_settings_form(self) -> None:
        raw = _read_config_file(self.CONFIG_PATH)
        if not raw and self.CONFIG_EXAMPLE.exists():
            raw = _read_config_file(self.CONFIG_EXAMPLE)
        self._key_var.set(raw.get("consumer_key", ""))
        secret = raw.get("consumer_secret", "")
        if secret in ("", "YOUR_CONSUMER_SECRET"):
            self._secret_var.set("")
        else:
            self._secret_var.set(secret)
        self._sandbox_var.set(bool(raw.get("sandbox", True)))
        self._oob_var.set(bool(raw.get("use_oob", False)))
        if hasattr(self, "_callback_var"):
            self._callback_var.set(raw.get("callback_url", DEFAULT_CALLBACK_URL))
        self._validate_setup_fields()

    def _config_from_form(self) -> ETradeConfig:
        callback = getattr(self, "_callback_var", tk.StringVar(value=DEFAULT_CALLBACK_URL)).get().strip()
        return build_config(
            self._key_var.get(),
            self._secret_var.get(),
            sandbox=bool(self._sandbox_var.get()),
            callback_url=callback or DEFAULT_CALLBACK_URL,
            use_oob=bool(self._oob_var.get()),
            config_path=self.CONFIG_PATH,
        )

    def _persist_settings_from_form(self, *, silent: bool = False) -> ETradeConfig | None:
        try:
            config = self._config_from_form()
        except ValueError as exc:
            if not silent:
                messagebox.showwarning("Missing Fields", str(exc))
            return None

        existing = _read_config_file(self.CONFIG_PATH)
        if not existing and self.CONFIG_EXAMPLE.exists():
            existing = _read_config_file(self.CONFIG_EXAMPLE)
        existing["consumer_key"] = config.consumer_key
        existing["consumer_secret"] = config.consumer_secret
        existing["sandbox"] = config.sandbox
        existing["use_oob"] = config.use_oob
        existing["callback_url"] = config.callback_url
        existing.setdefault("token_path", "etrade_tokens.json")
        existing.setdefault("strategy", {
            "cash_buffer_pct": DEFAULT_CASH_BUFFER_PCT,
            "min_drift_pct": DEFAULT_MIN_DRIFT_PCT,
            "min_trade_usd": DEFAULT_MIN_TRADE_USD,
        })

        try:
            _write_config_file(self.CONFIG_PATH, existing)
            self._config = config
            self._update_env_badge(config.sandbox)
            self._setup_save_status.configure(text="✓ Settings saved", fg=UP)
            self._log_line(
                f"API settings saved (key {credential_hint(config.consumer_key)}, "
                f"{'sandbox' if config.sandbox else 'production'})."
            )
            self._set_status("Settings saved — click Connect to authorize", ACCENT2)
            self._update_setup_progress()
            return config
        except Exception as exc:
            if not silent:
                messagebox.showerror("Save Failed", str(exc))
            self._setup_save_status.configure(text=f"Error: {exc}", fg=DOWN)
            return None

    def _save_settings(self) -> None:
        if self._persist_settings_from_form(silent=False) is None:
            if not sanitize_credential(self._key_var.get(), KEY_PLACEHOLDER) or not sanitize_credential(
                self._secret_var.get(), SECRET_PLACEHOLDER
            ):
                messagebox.showwarning("Missing Fields", "Enter both Consumer Key and Consumer Secret.")
            elif self._key_var.get().strip() in ("", KEY_PLACEHOLDER) or self._secret_var.get().strip() in (
                "",
                SECRET_PLACEHOLDER,
            ):
                messagebox.showwarning(
                    "Placeholder Values",
                    "Replace the placeholder values with your real API credentials.",
                )

    def _test_api_keys(self) -> None:
        config = self._persist_settings_from_form(silent=True)
        if config is None:
            messagebox.showwarning(
                "Missing Fields",
                "Enter both Consumer Key and Consumer Secret, then click Test API Keys.",
            )
            return
        if self._busy:
            return
        self._set_busy(True)
        self._set_status("Testing API keys with E*TRADE…", WARN)
        threading.Thread(target=self._test_api_keys_thread, args=(config,), daemon=True).start()

    def _test_api_keys_thread(self, config: ETradeConfig) -> None:
        try:
            ok, msg = self._run_network_task(test_api_credentials, config)
            if ok:
                self._schedule(self._show_info, "API Keys OK", msg)
                self._schedule(self._set_status, "API keys verified — click Connect", UP)
                self._schedule(self._log_line, msg)
            else:
                self._schedule(self._show_error, "API Keys Rejected", msg)
                self._schedule(self._set_status, "API keys rejected — see error dialog", DOWN)
                self._schedule(self._log_line, f"API key test failed: {msg}")
        except Exception as exc:
            self._schedule(self._show_error, "Test Failed", str(exc))
            self._schedule(self._set_status, "API key test failed", DOWN)
            self._schedule(self._log_line, f"API key test error: {exc}")
        finally:
            self._schedule(self._set_busy, False)

    def _update_setup_progress(self) -> None:
        if not self._setup_step_icons:
            return

        completed, active_step, states = self._setup_completion_state()

        for i, done in enumerate(states):
            color = UP if done else (ACCENT2 if i == active_step and not states[3] else MUTED)
            self._setup_step_icons[i].configure(text="✓" if done else str(i + 1), fg=color)
            self._setup_step_labels[i].configure(fg=TEXT if done or i == active_step else MUTED)

        for i, section in enumerate(self._setup_sections):
            if states[3]:
                border, thick = (UP, 2) if states[i] else (BORDER, 1)
            elif i == active_step:
                border, thick = ACCENT2, 2
            elif states[i]:
                border, thick = UP, 1
            else:
                border, thick = BORDER, 1
            section.configure(highlightbackground=border, highlightthickness=thick)

        if hasattr(self, "_setup_progress_bar"):
            self._setup_progress_bar.configure(value=completed)
        if hasattr(self, "_setup_progress_label"):
            self._setup_progress_label.configure(text=f"{completed} of 4 steps complete")

        next_labels = (
            "Continue to Step 1",
            "Continue to Step 2 — Connect",
            "Continue to Step 3 — Choose Account",
            "Start Trading",
        )
        next_hints = (
            "Enter your API credentials to get started.",
            "API keys saved. Connect to E*TRADE to authorize this app.",
            "Connected! Refresh accounts, pick one from the dropdown, and confirm your choice.",
            "All set! Agents and strategy plan update automatically — preview orders when ready.",
        )
        if hasattr(self, "_setup_next_btn"):
            self._setup_next_btn.configure(text=next_labels[active_step])
        if hasattr(self, "_setup_next_hint"):
            self._setup_next_hint.configure(text=next_hints[active_step])

        if connected := self._client is not None:
            self._setup_auth_status.configure(text="Status: Connected to E*TRADE", fg=UP)
        else:
            self._setup_auth_status.configure(text="Status: Not connected — click Connect above", fg=DOWN)

        if states[3]:
            self._setup_ready_msg.configure(
                text="All set! Agents and plan run in the background. Use Preview → Execute when you're ready to trade.",
                fg=UP,
            )
        elif states[0] and not connected:
            self._setup_ready_msg.configure(text="API keys saved. Connect to E*TRADE to continue.", fg=ACCENT2)
        elif connected and not self._accounts:
            self._setup_ready_msg.configure(text="Connected. Click Refresh Accounts to load your brokerage accounts.", fg=WARN)
        elif connected and not states[2]:
            self._setup_ready_msg.configure(
                text="Accounts loaded. Select one from the dropdown and confirm to enable trading.",
                fg=WARN,
            )
        else:
            self._setup_ready_msg.configure(text="Complete steps 1–3 to unlock automated trading.", fg=MUTED)

        if not states[0]:
            self._show_setup_tab()
        self._validate_setup_fields()

    def _stat_card(self, parent: tk.Misc, title: str, value: str, *, accent: str | None = None) -> tk.Frame:
        f = tk.Frame(parent, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        stripe_color = accent or BORDER
        tk.Frame(f, bg=stripe_color, height=self._m.px(3)).pack(fill=tk.X)
        inner = tk.Frame(f, bg=CARD_BG)
        inner.pack(fill=tk.BOTH, expand=True)
        tk.Label(inner, text=title, bg=CARD_BG, fg=MUTED, font=self._m.font(9, "bold")).pack(
            anchor="w", padx=self._m.px(14), pady=(self._m.px(10), 0),
        )
        val = tk.Label(inner, text=value, bg=CARD_BG, fg=TEXT, font=self._m.mono(16))
        val.pack(anchor="w", padx=self._m.px(14), pady=(self._m.px(4), self._m.px(12)))
        f._value_label = val  # type: ignore[attr-defined]
        return f

    def _set_card(self, card: tk.Frame, value: str, color: str = TEXT) -> None:
        card._value_label.configure(text=value, fg=color)  # type: ignore[attr-defined]

    def _trades_tab_header(
        self,
        parent: tk.Misc,
        *,
        title: str,
        subtitle: str,
        actions: Callable[[tk.Frame], None] | None = None,
    ) -> None:
        wrap = tk.Frame(parent, bg=PANEL)
        wrap.pack(fill=tk.X, padx=self._m.px(12), pady=(self._m.px(10), 0))
        top = tk.Frame(wrap, bg=PANEL)
        top.pack(fill=tk.X)
        text_col = tk.Frame(top, bg=PANEL)
        text_col.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(text_col, text=title, bg=PANEL, fg=TEXT, font=self._m.font(12, "bold"), anchor="w").pack(
            fill=tk.X,
        )
        tk.Label(text_col, text=subtitle, bg=PANEL, fg=MUTED, font=self._m.font(9), anchor="w").pack(
            fill=tk.X, pady=(self._m.px(2), 0),
        )
        if actions is not None:
            btn_row = tk.Frame(top, bg=PANEL)
            btn_row.pack(side=tk.RIGHT, anchor="n", padx=(self._m.px(8), 0))
            actions(btn_row)
        tk.Frame(wrap, bg=BORDER, height=1).pack(fill=tk.X, pady=(self._m.px(8), self._m.px(4)))

    def _stat_card_row(self, parent: tk.Misc, specs: list[tuple[str, str | None]]) -> list[tk.Frame]:
        cards = tk.Frame(parent, bg=PANEL)
        cards.pack(fill=tk.X, padx=self._m.px(12), pady=(0, self._m.px(8)))
        for col in range(len(specs)):
            cards.columnconfigure(col, weight=1)
        built: list[tk.Frame] = []
        for col, (title, accent) in enumerate(specs):
            card = self._stat_card(cards, title, "—", accent=accent)
            card.grid(row=0, column=col, sticky="ew", padx=(0, self._m.px(6) if col < len(specs) - 1 else 0))
            built.append(card)
        return built

    def _meta_chip_bar(self, parent: tk.Misc) -> tuple[tk.Label, tk.Label]:
        bar = tk.Frame(parent, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        bar.pack(fill=tk.X, padx=self._m.px(12), pady=(0, self._m.px(8)))
        inner = tk.Frame(bar, bg=CARD_BG)
        inner.pack(fill=tk.X, padx=self._m.px(10), pady=self._m.px(6))
        baseline = tk.Label(inner, text="Account open: —", bg=CARD_BG, fg=MUTED, font=self._m.font(9), anchor="w")
        baseline.pack(side=tk.LEFT, fill=tk.X, expand=True)
        updated = tk.Label(inner, text="Last updated: —", bg=CARD_BG, fg=MUTED, font=self._m.font(9), anchor="e")
        updated.pack(side=tk.RIGHT)
        return baseline, updated

    def _section_heading(self, parent: tk.Misc, title: str) -> None:
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill=tk.X, padx=self._m.px(12), pady=(self._m.px(4), self._m.px(4)))
        tk.Label(row, text=title, bg=PANEL, fg=TEXT, font=self._m.font(10, "bold"), anchor="w").pack(
            side=tk.LEFT,
        )
        tk.Frame(row, bg=BORDER, height=1).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(self._m.px(10), 0), pady=6)

    def _set_trades_split_ratio(self, ratio: float = 0.64) -> None:
        if not hasattr(self, "_trades_splitter") or self._trades_detail_hidden:
            return
        place_pane_ratio(self._trades_splitter, ratio, min_total=self._m.px(900))

    def _schedule_layout_save(self) -> None:
        if self._shutting_down or self._layout_save_after_id:
            return
        try:
            self._layout_save_after_id = self.after(350, self._flush_layout_save)
        except tk.TclError:
            pass

    def _on_window_configure(self, event: tk.Event) -> None:
        if self._shutting_down or event.widget is not self._window:
            return
        self._schedule_layout_save()

    def _flush_layout_save(self) -> None:
        self._layout_save_after_id = None
        if self._shutting_down:
            return
        patch: dict[str, Any] = {}
        try:
            patch["geometry"] = self._window.geometry()
        except tk.TclError:
            pass
        if hasattr(self, "_trades_splitter"):
            ratio = pane_sash_ratio(self._trades_splitter)
            if ratio is not None:
                patch["trades_split_ratio"] = round(ratio, 4)
            patch["trades_detail_hidden"] = bool(self._trades_detail_hidden)
        if hasattr(self, "_day_orders_split"):
            day_ratio = pane_sash_ratio(self._day_orders_split)
            if day_ratio is not None:
                patch["day_orders_split_ratio"] = round(day_ratio, 4)
        try:
            patch["main_notebook_tab"] = int(self._notebook.index(self._notebook.select()))
        except tk.TclError:
            pass
        try:
            patch["trades_notebook_tab"] = int(self._trades_notebook.index(self._trades_notebook.select()))
        except tk.TclError:
            pass
        save_ui_layout(getattr(self, "_layout_key", "etrade_trader"), patch)

    def _restore_saved_layout(self) -> None:
        layout = load_ui_layout(getattr(self, "_layout_key", "etrade_trader"))
        if layout.get("trades_detail_hidden"):
            if not self._trades_detail_hidden:
                self._toggle_trades_detail_panel()
        elif layout.get("trades_split_ratio") is not None:
            self._set_trades_split_ratio(float(layout["trades_split_ratio"]))
        else:
            self._set_trades_split_ratio()
        if layout.get("day_orders_split_ratio") is not None and hasattr(self, "_day_orders_split"):
            place_pane_ratio(
                self._day_orders_split,
                float(layout["day_orders_split_ratio"]),
                min_total=self._m.px(200),
            )
        main_tab = layout.get("main_notebook_tab")
        if isinstance(main_tab, int):
            tabs = self._notebook.tabs()
            if 0 <= main_tab < len(tabs):
                try:
                    self._notebook.select(tabs[main_tab])
                except tk.TclError:
                    pass
        trades_tab = layout.get("trades_notebook_tab")
        if isinstance(trades_tab, int):
            tabs = self._trades_notebook.tabs()
            if 0 <= trades_tab < len(tabs):
                try:
                    self._trades_notebook.select(tabs[trades_tab])
                except tk.TclError:
                    pass

    def _toggle_trades_detail_panel(self) -> None:
        if not hasattr(self, "_trades_splitter"):
            return
        try:
            if self._trades_detail_hidden:
                layout = load_ui_layout(getattr(self, "_layout_key", "etrade_trader"))
                ratio = float(layout.get("trades_split_ratio") or 0.64)
                place_pane_ratio(self._trades_splitter, ratio, min_total=self._m.px(700))
                self._trades_detail_hidden = False
                if hasattr(self, "_trade_detail_toggle_btn"):
                    self._trade_detail_toggle_btn.configure(text="Hide")
            else:
                total = max(self._trades_splitter.winfo_width(), self._m.px(700))
                self._trades_splitter.sash_place(0, total - self._m.px(4), 0)
                self._trades_detail_hidden = True
                if hasattr(self, "_trade_detail_toggle_btn"):
                    self._trade_detail_toggle_btn.configure(text="Show")
        except tk.TclError:
            pass
        self._schedule_layout_save()

    def _build_overview_tab(self) -> None:
        hdr = tk.Frame(self._tab_overview, bg=PANEL)
        hdr.pack(fill=tk.X, padx=self._m.px(10), pady=(self._m.px(8), 0))
        tk.Label(hdr, text="Account snapshot", bg=PANEL, fg=TEXT, font=self._m.font(11, "bold")).pack(
            side=tk.LEFT,
        )
        self._make_btn(hdr, "Refresh", self._fetch_confirmed_balance, variant="secondary", compact=True)
        (
            self._balance_total_card,
            self._balance_cash_card,
            self._balance_gain_amt_card,
            self._balance_gain_pct_card,
        ) = self._stat_card_row(
            self._tab_overview,
            [
                ("Account balance", ACCENT2),
                ("Buying power", None),
                ("Gain / loss ($)", UP),
                ("Gain / loss (%)", UP),
            ],
        )
        self._balance_baseline_label, self._balance_updated_label = self._meta_chip_bar(self._tab_overview)

        chart_wrap = tk.Frame(self._tab_overview, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        chart_wrap.pack(fill=tk.BOTH, expand=True, padx=self._m.px(10), pady=(0, self._m.px(8)))

        from account_growth_chart import AccountGrowthChart

        self._balance_growth_points: list[dict] = []
        self._balance_growth_baseline: float | None = None
        self._balance_growth_chart = AccountGrowthChart(
            chart_wrap,
            width=max(self._m.px(400), int(self._m.win_w * 0.5)),
            height=self._m.px(120),
            bg=CARD_BG,
            font=self._m.font(8),
            default_range="Open",
            on_range_change=self._on_balance_chart_range_changed,
        )
        self._balance_growth_chart.pack(fill=tk.BOTH, expand=True, padx=self._m.px(4), pady=self._m.px(4))

    def _build_holdings_tab(self) -> None:
        tk.Label(
            self._tab_holdings,
            text="Portfolio vs agent targets — select a row for analysis →",
            bg=PANEL,
            fg=MUTED,
            font=self._m.font(9),
            anchor="w",
        ).pack(fill=tk.X, padx=self._m.px(10), pady=(self._m.px(8), self._m.px(4)))
        self._holdings_tree = self._make_tree(
            self._tab_holdings,
            ("symbol", "current_pct", "target_pct", "projected", "current_usd", "target_usd", "drift"),
            {
                "symbol": ("Symbol", 72),
                "current_pct": ("Current %", 80),
                "target_pct": ("Target %", 80),
                "projected": ("Projected", 148),
                "current_usd": ("Current $", 92),
                "target_usd": ("Target $", 92),
                "drift": ("Drift", 72),
            },
        )
        self._bind_trade_tree_select(self._holdings_tree, "portfolio")

    def _build_orders_tab(self) -> None:
        self._orders_notebook = ttk.Notebook(self._tab_orders, style="Trader.Trades.TNotebook")
        self._orders_notebook.pack(fill=tk.BOTH, expand=True, padx=self._m.px(2), pady=self._m.px(2))
        self._tab_swing_orders = tk.Frame(self._orders_notebook, bg=PANEL)
        self._tab_day_orders = tk.Frame(self._orders_notebook, bg=PANEL)
        self._orders_notebook.add(self._tab_swing_orders, text="  Swing  ")
        self._orders_notebook.add(self._tab_day_orders, text="  Day  ")

        tk.Label(
            self._tab_swing_orders,
            text="Swing rebalance orders — select a row for analysis →",
            bg=PANEL,
            fg=MUTED,
            font=self._m.font(9),
            anchor="w",
        ).pack(fill=tk.X, padx=self._m.px(10), pady=(self._m.px(8), self._m.px(4)))
        self._orders_tree = self._make_tree(
            self._tab_swing_orders,
            ("symbol", "action", "type", "qty", "price", "est_usd", "status", "message"),
            {
                "symbol": ("Symbol", 88), "action": ("Action", 64), "type": ("Type", 108), "qty": ("Qty", 56),
                "price": ("Est $", 88), "est_usd": ("Value", 96), "status": ("Status", 88), "message": ("Note", 280),
            },
        )
        self._bind_trade_tree_select(self._orders_tree, "swing_order")

        day_hdr = tk.Frame(self._tab_day_orders, bg=PANEL)
        day_hdr.pack(fill=tk.X, padx=self._m.px(10), pady=(self._m.px(8), 0))
        tk.Label(day_hdr, text="Day trades", bg=PANEL, fg=MUTED, font=self._m.font(9)).pack(side=tk.LEFT)
        self._make_btn(day_hdr, "Refresh", self._refresh_day_trading_panel, variant="secondary", compact=True)
        self._day_summary_label = tk.Label(
            self._tab_day_orders,
            text="Turn on day trading on the Home tab.",
            bg=PANEL,
            fg=TEXT,
            font=self._m.font(9),
            anchor="w",
            wraplength=self._m.px(700),
            justify=tk.LEFT,
        )
        self._day_summary_label.pack(fill=tk.X, padx=self._m.px(10), pady=(self._m.px(4), 0))

        self._day_orders_split = tk.PanedWindow(self._tab_day_orders, orient=tk.VERTICAL, bg=PANEL, sashwidth=self._m.px(4))
        self._day_orders_split.pack(fill=tk.BOTH, expand=True, padx=self._m.px(6), pady=(self._m.px(4), self._m.px(6)))
        self._day_orders_split.bind("<ButtonRelease-1>", lambda _e: self._schedule_layout_save())
        day_split = self._day_orders_split
        pos_wrap = tk.Frame(day_split, bg=PANEL)
        day_split.add(pos_wrap, minsize=self._m.px(100))
        tk.Label(pos_wrap, text="Open today", bg=PANEL, fg=TEXT, font=self._m.font(9, "bold"), anchor="w").pack(
            fill=tk.X, padx=self._m.px(4), pady=(0, self._m.px(2)),
        )
        self._day_positions_tree = self._make_tree(
            pos_wrap,
            ("symbol", "qty", "entry", "target", "stop", "rationale"),
            {
                "symbol": ("Symbol", 88), "qty": ("Qty", 56), "entry": ("Entry $", 92),
                "target": ("Take profit", 92), "stop": ("Stop loss", 92), "rationale": ("Note", 340),
            },
            compact_pad=True,
        )
        ord_wrap = tk.Frame(day_split, bg=PANEL)
        day_split.add(ord_wrap, minsize=self._m.px(100))
        tk.Label(ord_wrap, text="Ready to place", bg=PANEL, fg=TEXT, font=self._m.font(9, "bold"), anchor="w").pack(
            fill=tk.X, padx=self._m.px(4), pady=(0, self._m.px(2)),
        )
        self._day_orders_tree = self._make_tree(
            ord_wrap,
            ("symbol", "action", "type", "qty", "price", "est_usd", "status", "message"),
            {
                "symbol": ("Symbol", 88), "action": ("Action", 64), "type": ("Type", 108), "qty": ("Qty", 56),
                "price": ("Est $", 88), "est_usd": ("Value", 96), "status": ("Status", 88), "message": ("Note", 280),
            },
            compact_pad=True,
        )
        self._bind_trade_tree_select(self._day_positions_tree, "day_position")
        self._bind_trade_tree_select(self._day_orders_tree, "day_order")

    def _build_performance_tab(self) -> None:
        self._perf_notebook = ttk.Notebook(self._tab_performance, style="Trader.Trades.TNotebook")
        self._perf_notebook.pack(fill=tk.BOTH, expand=True, padx=self._m.px(2), pady=self._m.px(2))
        self._tab_history = tk.Frame(self._perf_notebook, bg=PANEL)
        self._tab_attribution = tk.Frame(self._perf_notebook, bg=PANEL)
        self._tab_balance_log = tk.Frame(self._perf_notebook, bg=PANEL)
        self._perf_notebook.add(self._tab_history, text="  Trade history  ")
        self._perf_notebook.add(self._tab_attribution, text="  Attribution  ")
        self._perf_notebook.add(self._tab_balance_log, text="  Balance log  ")
        self._perf_notebook.bind("<<NotebookTabChanged>>", self._on_perf_tab_changed)
        self._build_history_tab()
        self._build_attribution_tab()
        self._build_balance_log_tab()

    def _build_balance_log_tab(self) -> None:
        tk.Label(
            self._tab_balance_log,
            text="Recorded balance snapshots over time",
            bg=PANEL,
            fg=MUTED,
            font=self._m.font(9),
            anchor="w",
        ).pack(fill=tk.X, padx=self._m.px(10), pady=(self._m.px(8), self._m.px(4)))
        self._balance_history_tree = self._make_tree(
            self._tab_balance_log,
            ("at", "total", "buying_power", "gain_amt", "gain_pct", "source"),
            {
                "at": ("Recorded", 150),
                "total": ("Balance", 108),
                "buying_power": ("Buying power", 108),
                "gain_amt": ("Gain $", 96),
                "gain_pct": ("Gain %", 72),
                "source": ("Source", 120),
            },
        )

    def _gain_color(self, value: float | None) -> str:
        if value is None:
            return TEXT
        if value > 0:
            return UP
        if value < 0:
            return DOWN
        return TEXT

    def _format_balance_timestamp(self, raw: str) -> str:
        text = str(raw or "").strip()
        if not text:
            return "—"
        try:
            from datetime import datetime

            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed.strftime("%b %d, %Y %I:%M %p")
        except ValueError:
            return text[:19].replace("T", " ")

    def _clear_balance_tab(self) -> None:
        if not hasattr(self, "_balance_total_card"):
            return
        for card in (
            self._balance_total_card,
            self._balance_cash_card,
            self._balance_gain_amt_card,
            self._balance_gain_pct_card,
        ):
            self._set_card(card, "—")
        self._balance_baseline_label.configure(text="Account open: —")
        self._balance_updated_label.configure(text="Last updated: —")
        self._tree_clear(self._balance_history_tree)
        if hasattr(self, "_balance_growth_chart"):
            self._balance_growth_chart.show_placeholder()

    def _build_history_tab(self) -> None:
        hdr = tk.Frame(self._tab_history, bg=PANEL)
        hdr.pack(fill=tk.X, padx=self._m.px(10), pady=(self._m.px(8), 0))
        tk.Label(hdr, text="Trade history & P&L", bg=PANEL, fg=TEXT, font=self._m.font(11, "bold")).pack(
            side=tk.LEFT,
        )
        self._make_btn(hdr, "Export CSV", self._export_trade_history_csv, variant="accent", compact=True)
        (
            self._pnl_total_card,
            self._pnl_swing_card,
            self._pnl_day_card,
            self._pnl_record_card,
        ) = self._stat_card_row(
            self._tab_history,
            [
                ("Total realized P&L", ACCENT),
                ("Swing P&L", None),
                ("Day P&L", None),
                ("Trades logged", ACCENT2),
            ],
        )
        self._history_tree = self._make_tree(
            self._tab_history,
            ("at", "symbol", "action", "qty", "price", "value", "pnl", "mode", "agents", "note"),
            {
                "at": ("Time", 140),
                "symbol": ("Symbol", 72),
                "action": ("Action", 64),
                "qty": ("Qty", 48),
                "price": ("Price", 80),
                "value": ("Value", 88),
                "pnl": ("P&L", 80),
                "mode": ("Mode", 56),
                "agents": ("Agents", 140),
                "note": ("Note", 260),
            },
        )

    def _build_attribution_tab(self) -> None:
        tk.Label(
            self._tab_attribution,
            text="P&L grouped by agent research source",
            bg=PANEL,
            fg=MUTED,
            font=self._m.font(9),
            anchor="w",
        ).pack(fill=tk.X, padx=self._m.px(10), pady=(self._m.px(8), self._m.px(4)))
        summary_bar = tk.Frame(self._tab_attribution, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        summary_bar.pack(fill=tk.X, padx=self._m.px(10), pady=(0, self._m.px(6)))
        self._attribution_summary_label = tk.Label(
            summary_bar,
            text="—",
            bg=CARD_BG,
            fg=TEXT,
            font=self._m.font(10),
            anchor="w",
            padx=self._m.px(12),
            pady=self._m.px(8),
        )
        self._attribution_summary_label.pack(fill=tk.X)
        self._attribution_tree = self._make_tree(
            self._tab_attribution,
            ("source", "trades", "realized", "wins", "losses", "win_rate"),
            {
                "source": ("Agent source", 180),
                "trades": ("Trades", 72),
                "realized": ("Realized P&L", 120),
                "wins": ("Wins", 56),
                "losses": ("Losses", 64),
                "win_rate": ("Win %", 72),
            },
        )

    def _export_trade_history_csv(self) -> None:
        from tkinter import filedialog

        from trade_history import export_trades_csv

        default_name = f"etrade_trades_{time.strftime('%Y%m%d')}.csv"
        path = filedialog.asksaveasfilename(
            parent=self._window,
            title="Export trade history",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            count = export_trades_csv(path)
            messagebox.showinfo("Export complete", f"Exported {count} trade(s) to:\n{path}", parent=self._window)
            self._log_line(f"Trade history exported: {path} ({count} rows)")
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc), parent=self._window)

    def _update_history_tab(self) -> None:
        if not hasattr(self, "_history_tree"):
            return
        try:
            from trade_history import get_pnl_summary, load_trade_history

            summary = get_pnl_summary()
            store = load_trade_history()
        except Exception:
            summary = {}
            store = {"trades": []}

        total = float(summary.get("total_realized_pnl_usd", 0))
        swing = float(summary.get("swing_realized_pnl_usd", 0))
        day = float(summary.get("day_realized_pnl_usd", 0))
        self._set_card(self._pnl_total_card, f"${total:+,.2f}", self._gain_color(total))
        self._set_card(self._pnl_swing_card, f"${swing:+,.2f}", self._gain_color(swing))
        self._set_card(self._pnl_day_card, f"${day:+,.2f}", self._gain_color(day))
        self._set_card(self._pnl_record_card, str(summary.get("trade_count", 0)))

        self._tree_clear(self._history_tree)
        for trade in reversed((store.get("trades") or [])[-80:]):
            pnl = trade.get("realized_pnl_usd")
            pnl_text = f"${float(pnl):+,.2f}" if pnl is not None else "—"
            pnl_tags: tuple[str, ...] = ()
            if pnl is not None:
                pnl_tags = ("gain_up",) if float(pnl) >= 0 else ("gain_down",)
            agents = ", ".join(trade.get("agent_sources") or []) or "—"
            self._tree_insert(
                self._history_tree,
                (
                    self._format_balance_timestamp(str(trade.get("executed_at", ""))),
                    trade.get("symbol", "—"),
                    trade.get("action", "—"),
                    trade.get("quantity", "—"),
                    f"${float(trade.get('price', 0)):.2f}" if trade.get("price") else "—",
                    f"${float(trade.get('value_usd', 0)):,.2f}" if trade.get("value_usd") else "—",
                    pnl_text,
                    trade.get("mode", "—"),
                    agents[:48],
                    (trade.get("rationale") or "")[:120],
                ),
                extra_tags=pnl_tags,
            )

    def _update_attribution_tab(self) -> None:
        if not hasattr(self, "_attribution_tree"):
            return
        try:
            from trade_history import get_attribution_summary

            rows = get_attribution_summary()
        except Exception:
            rows = []

        total_pnl = sum(float(r.get("realized_pnl_usd", 0)) for r in rows)
        self._attribution_summary_label.configure(
            text=f"{len(rows)} agent source(s)  ·  Combined realized P&L: ${total_pnl:+,.2f}",
            fg=self._gain_color(total_pnl),
        )
        self._tree_clear(self._attribution_tree)
        for row in rows:
            pnl = float(row.get("realized_pnl_usd", 0))
            win_rate = row.get("win_rate_pct")
            self._tree_insert(
                self._attribution_tree,
                (
                    row.get("source", "—"),
                    row.get("trades", 0),
                    f"${pnl:+,.2f}",
                    row.get("wins", 0),
                    row.get("losses", 0),
                    f"{win_rate:.1f}%" if win_rate is not None else "—",
                ),
                extra_tags=("gain_up",) if pnl > 0 else (("gain_down",) if pnl < 0 else ()),
            )

    def _current_account_key(self) -> str:
        return str(getattr(self, "_persisted_account_key", "") or "").strip()

    def _on_balance_chart_range_changed(self, _range_key: str) -> None:
        self._populate_balance_history_tree()

    def _populate_balance_history_tree(self) -> None:
        if not hasattr(self, "_balance_history_tree"):
            return
        from account_growth_chart import (
            filter_point_rows,
            resolve_opened_at_for_account,
            resolve_opening_balance_for_account,
        )

        self._tree_clear(self._balance_history_tree)
        range_key = "Open"
        if hasattr(self, "_balance_growth_chart"):
            range_key = self._balance_growth_chart.range_key
        baseline = self._balance_growth_baseline
        account_key = self._current_account_key()
        config_selected = get_selected_account(self.CONFIG_PATH)
        try:
            from analysis_history import get_account_growth

            accounts_meta = get_account_growth().get("accounts")
        except Exception:
            accounts_meta = {}
        accounts_meta = accounts_meta if isinstance(accounts_meta, dict) else {}
        open_ts = resolve_opened_at_for_account(
            account_key,
            self._balance_growth_points,
            config_selected=config_selected,
            accounts_meta=accounts_meta,
        )
        opening_balance = resolve_opening_balance_for_account(
            account_key,
            self._balance_growth_points,
            accounts_meta=accounts_meta,
        )
        points = filter_point_rows(
            self._balance_growth_points,
            range_key,
            account_id_key=account_key,
            account_opened_at=open_ts.isoformat() if open_ts else None,
            opening_balance=opening_balance,
        )
        for point in reversed(points[-60:]):
            value = point.get("total_account_value")
            point_cash = point.get("cash_buying_power")
            point_gain_amt = "—"
            point_gain_pct = "—"
            gain_tags: tuple[str, ...] = ()
            if baseline is not None and value is not None:
                try:
                    from account_profit import profit_at_point

                    events = getattr(self, "_balance_external_events", None) or []
                    delta, pct = profit_at_point(
                        float(value),
                        float(baseline),
                        events,
                        str(point.get("at") or ""),
                    )
                    sign = "+" if delta >= 0 else ""
                    point_gain_amt = f"{sign}${delta:,.2f}"
                    point_gain_pct = f"{sign}{pct:.2f}%"
                    if delta > 0:
                        gain_tags = ("gain_up",)
                    elif delta < 0:
                        gain_tags = ("gain_down",)
                except (TypeError, ValueError):
                    pass
            self._tree_insert(
                self._balance_history_tree,
                (
                    self._format_balance_timestamp(str(point.get("at", ""))),
                    f"${float(value):,.2f}" if value is not None else "—",
                    f"${float(point_cash):,.2f}" if point_cash is not None else "—",
                    point_gain_amt,
                    point_gain_pct,
                    str(point.get("source") or "—"),
                ),
                extra_tags=gain_tags,
            )

    def _update_balance_tab(
        self,
        total_value: float | None = None,
        buying_power: float | None = None,
    ) -> None:
        if not hasattr(self, "_balance_total_card"):
            return
        try:
            from analysis_history import get_account_growth

            growth = get_account_growth()
        except Exception:
            growth = {}

        from account_growth_chart import (
            points_for_account,
            resolve_opened_at_for_account,
            resolve_opening_balance_for_account,
        )

        account_key = self._current_account_key()
        config_selected = get_selected_account(self.CONFIG_PATH)
        accounts_meta = growth.get("accounts") if isinstance(growth.get("accounts"), dict) else {}
        scoped_points = points_for_account(list(growth.get("points") or []), account_key)
        baseline = resolve_opening_balance_for_account(
            account_key,
            scoped_points,
            accounts_meta=accounts_meta,
        )
        if baseline is None:
            baseline = growth.get("baseline_value")
        latest = total_value if total_value is not None else growth.get("latest_value")
        cash = buying_power if buying_power is not None else None
        self._balance_growth_points = scoped_points
        self._balance_growth_baseline = float(baseline) if baseline is not None else None

        if latest is not None:
            self._set_card(self._balance_total_card, f"${float(latest):,.2f}")
        else:
            self._set_card(self._balance_total_card, "—")

        if cash is not None:
            self._set_card(self._balance_cash_card, f"${float(cash):,.2f}")
        else:
            points = growth.get("points") or []
            last_cash = points[-1].get("cash_buying_power") if points else None
            if last_cash is not None:
                self._set_card(self._balance_cash_card, f"${float(last_cash):,.2f}")
            else:
                self._set_card(self._balance_cash_card, "—")

        from account_profit import profit_metrics_for_account

        profit = profit_metrics_for_account(growth, account_key)
        external_events = list(profit.get("external_flow_events") or [])
        net_flows = profit.get("net_external_flows") or 0.0
        invested = profit.get("invested_capital")
        self._balance_external_events = external_events
        self._balance_invested_capital = float(invested) if invested is not None else None

        gain_amt: float | None = profit.get("profit_amount")
        gain_pct: float | None = profit.get("profit_pct")
        if gain_amt is None and baseline is not None and latest is not None:
            try:
                base = float(invested) if invested is not None else float(baseline) + float(net_flows)
                gain_amt = float(latest) - base
                if gain_pct is None and base != 0:
                    gain_pct = (gain_amt / base) * 100
            except (TypeError, ValueError):
                gain_amt = None

        if gain_amt is not None:
            sign = "+" if gain_amt >= 0 else ""
            self._set_card(self._balance_gain_amt_card, f"{sign}${gain_amt:,.2f}", self._gain_color(gain_amt))
        else:
            self._set_card(self._balance_gain_amt_card, "—")

        if gain_pct is not None:
            sign = "+" if float(gain_pct) >= 0 else ""
            self._set_card(
                self._balance_gain_pct_card,
                f"{sign}{float(gain_pct):.2f}%",
                self._gain_color(float(gain_pct)),
            )
        else:
            self._set_card(self._balance_gain_pct_card, "—")

        open_ts = resolve_opened_at_for_account(
            account_key,
            self._balance_growth_points,
            config_selected=config_selected,
            accounts_meta=accounts_meta,
        )
        transfer_note = ""
        if net_flows:
            sign = "+" if float(net_flows) >= 0 else ""
            transfer_note = f" · {sign}${float(net_flows):,.0f} transfers (excluded from gain)"
        if open_ts is not None and baseline is not None:
            self._balance_baseline_label.configure(
                text=(
                    f"Account open: {open_ts.strftime('%b %d, %Y')} · "
                    f"${float(baseline):,.2f}{transfer_note}"
                ),
            )
        elif baseline is not None:
            self._balance_baseline_label.configure(
                text=f"Account open: ${float(baseline):,.2f}{transfer_note}",
            )
        else:
            self._balance_baseline_label.configure(
                text="Account open: — (recorded on first balance refresh)",
            )

        updated = growth.get("updated_at")
        self._balance_updated_label.configure(
            text=f"Last updated: {self._format_balance_timestamp(str(updated or ''))}",
        )

        if hasattr(self, "_balance_growth_chart"):
            if self._balance_growth_points:
                self._balance_growth_chart.load_points(
                    self._balance_growth_points,
                    baseline=baseline,
                    profit_invested_capital=self._balance_invested_capital,
                    account_id_key=account_key,
                    accounts_meta=accounts_meta,
                    config_selected=config_selected,
                )
            else:
                self._balance_growth_chart.show_placeholder()

        self._populate_balance_history_tree()

    def _on_perf_tab_changed(self, _event: tk.Event | None = None) -> None:
        try:
            selected = str(self._perf_notebook.select())
        except tk.TclError:
            return
        if selected == str(self._tab_history):
            self._update_history_tab()
        elif selected == str(self._tab_attribution):
            self._update_attribution_tab()
        elif selected == str(self._tab_balance_log):
            self._update_balance_tab()

    def _on_trades_tab_changed(self, _event: tk.Event | None = None) -> None:
        try:
            selected = str(self._trades_notebook.select())
        except tk.TclError:
            return
        self._schedule_layout_save()
        if selected == str(self._tab_overview):
            self._update_balance_tab()
            if self._selected_account() and self._client:
                self._fetch_confirmed_balance()
        elif selected == str(self._tab_performance):
            self._on_perf_tab_changed()

    def _tree_clear(self, tree: ttk.Treeview) -> None:
        tree_clear(tree)

    @staticmethod
    def _format_order_type(order: TradeOrder) -> str:
        price_type = (getattr(order, "price_type", None) or "MARKET").upper()
        if price_type == "LIMIT" and getattr(order, "limit_price", None) is not None:
            return f"LIMIT ${order.limit_price:.2f}"
        return price_type

    def _bind_trade_tree_select(self, tree: ttk.Treeview, context: str) -> None:
        tree.bind("<<TreeviewSelect>>", lambda event, ctx=context: self._on_trade_tree_select(event, ctx))
        tree.bind("<Double-1>", lambda event, ctx=context: self._on_trade_tree_select(event, ctx))

    def _on_trade_tree_select(self, event: tk.Event, context: str) -> None:
        tree = event.widget
        if not isinstance(tree, ttk.Treeview):
            return
        selection = tree.selection()
        if not selection:
            return
        values = tree.item(selection[0], "values")
        if not values:
            return
        symbol = str(values[0]).strip().upper()
        if not symbol:
            return
        self._trade_analysis_context = context
        self._show_trade_analysis(symbol, context)

    def _portfolio_holdings_map(self) -> dict[str, dict[str, Any]]:
        try:
            from strategy_engine import PORTFOLIO_FILE

            data = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
            return {
                str(row.get("symbol", "")).upper(): row
                for row in (data.get("holdings") or [])
                if isinstance(row, dict) and row.get("symbol")
            }
        except Exception:
            return {}

    def _holding_with_projection(
        self,
        holding: dict[str, Any] | None,
        symbol: str,
    ) -> dict[str, Any] | None:
        from position_analysis import merge_portfolio_projection

        portfolio_row = self._portfolio_holdings_map().get(symbol.upper())
        return merge_portfolio_projection(holding, portfolio_row)

    def _show_trade_analysis(self, symbol: str, context: str) -> None:
        from position_analysis import (
            build_position_analysis,
            get_company_profile,
            projected_return_compact,
        )

        holding: dict[str, Any] | None = None
        current: dict[str, Any] | None = None
        order: TradeOrder | None = None
        day_pos: dict[str, Any] | None = None

        if self._plan:
            target_map = {h["symbol"].upper(): h for h in self._plan.target_holdings}
            pos_map = {p["symbol"].upper(): p for p in self._plan.current_positions}
            holding = target_map.get(symbol)
            current = pos_map.get(symbol)
            if context == "swing_order":
                order = next((o for o in self._plan.orders if o.symbol.upper() == symbol), None)

        if context in {"day_position", "day_order"}:
            for pos in self._read_day_state().get("positions", []) or []:
                if str(pos.get("symbol", "")).upper() == symbol:
                    day_pos = pos
                    break
            if context == "day_order":
                plan_data = load_strategy_plan(self.DAY_PLAN_FILE)
                if plan_data:
                    try:
                        day_plan = plan_from_dict(plan_data)
                        order = next((o for o in day_plan.orders if o.symbol.upper() == symbol), None)
                    except Exception:
                        order = None

        holding = self._holding_with_projection(holding, symbol)
        text = build_position_analysis(
            symbol,
            holding=holding,
            current_position=current,
            order=order,
            day_position=day_pos,
        )
        projection = projected_return_compact(holding)
        if projection != "—":
            self._trade_detail_projection.configure(
                text=f"Projected return: {projection}",
                fg=UP if projection.startswith("+") else DOWN if projection.startswith("-") else TEXT,
            )
        else:
            self._trade_detail_projection.configure(text="")
        labels = {
            "portfolio": "Portfolio position",
            "swing_order": "Swing trade order",
            "day_position": "Day trade position",
            "day_order": "Day trade order",
        }
        profile = get_company_profile(symbol)
        company_name = str(profile.get("name") or symbol).strip()
        price_bit = ""
        if profile.get("price") is not None:
            price = float(profile["price"])
            price_bit = f" · ${price:.2f}"
            if profile.get("change_pct") is not None:
                price_bit += f" ({float(profile['change_pct']):+.2f}%)"
        self._trade_detail_title.configure(
            text=f"{company_name} ({symbol}){price_bit} — {labels.get(context, 'Analysis')}"
        )
        self._trade_detail_text.configure(state=tk.NORMAL)
        self._trade_detail_text.delete("1.0", tk.END)
        self._trade_detail_text.insert("1.0", text)
        self._trade_detail_text.configure(state=tk.DISABLED)
        self._trade_detail_text.see("1.0")
        current_price = float(profile["price"]) if profile.get("price") is not None else None
        self._load_trade_detail_chart(symbol, current_price=current_price)

    def _load_trade_detail_chart(self, symbol: str, *, current_price: float | None = None) -> None:
        self._trade_chart_token += 1
        token = self._trade_chart_token
        self._trade_detail_chart.show_placeholder("Loading 10-day chart…")

        def _fetch() -> None:
            from position_chart import CHART_DAYS, fetch_candle_bars

            bars = fetch_candle_bars(symbol, days=CHART_DAYS)
            self._window.after(
                0,
                lambda: self._apply_trade_detail_chart(symbol, bars, token, current_price=current_price),
            )

        threading.Thread(target=_fetch, daemon=True, name="trade-chart").start()

    def _apply_trade_detail_chart(
        self,
        symbol: str,
        bars: list[Any],
        token: int,
        *,
        current_price: float | None = None,
    ) -> None:
        if token != self._trade_chart_token:
            return
        self._trade_detail_chart.load_symbol(symbol, bars=bars, current_price=current_price)

    def _tree_insert(
        self,
        tree: ttk.Treeview,
        values: tuple[Any, ...],
        *,
        extra_tags: tuple[str, ...] = (),
    ) -> None:
        tree_insert(tree, values, extra_tags=extra_tags)

    def _make_tree(
        self,
        parent: tk.Misc,
        columns: tuple[str, ...],
        headings: dict[str, tuple[str, int]],
        *,
        compact_pad: bool = False,
    ) -> ttk.Treeview:
        return make_data_tree(
            parent,
            columns,
            headings,
            self._m,
            style="Trader.Treeview",
            panel_bg=PANEL,
            compact_pad=compact_pad,
        )

    def _activity_tab_visible(self) -> bool:
        try:
            return str(self._notebook.select()) == str(self._tab_log)
        except tk.TclError:
            return False

    def _log_line(self, msg: str, *, scroll: bool | None = None) -> None:
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self._log.insert("1.0", f"[{ts}] {msg}\n")
        if scroll is None:
            scroll = self._activity_tab_visible()
        if scroll:
            self._log.see("1.0")

    def _queue_log_line(self, msg: str, *, prefix: str = "") -> None:
        """Batch log writes to avoid redrawing the UI on every agent step."""
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self._pending_log_lines.append(f"[{ts}] {prefix}{msg}\n")
        if self._log_flush_after_id:
            return
        try:
            self._log_flush_after_id = self.after(750, self._flush_pending_log_lines)
        except tk.TclError:
            pass

    def _flush_pending_log_lines(self) -> None:
        self._log_flush_after_id = None
        if not self._pending_log_lines or self._shutting_down:
            self._pending_log_lines.clear()
            return
        chunk = "".join(reversed(self._pending_log_lines))
        self._pending_log_lines.clear()
        try:
            self._log.insert("1.0", chunk)
            if self._activity_tab_visible():
                self._log.see("1.0")
        except tk.TclError:
            pass

    def _set_status(self, text: str, color: str = ACCENT2) -> None:
        self._status_label.configure(text=text, fg=color if color != TEXT else TEXT)
        self._status_dot.configure(fg=color)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = tk.DISABLED if busy else tk.NORMAL

        if busy:
            self._progress.pack(side=tk.RIGHT)
            self._progress.start(12)
        else:
            self._progress.stop()
            self._progress.pack_forget()

    def _poll_ui(self) -> None:
        if self._shutting_down:
            return
        try:
            while True:
                fn, args, kwargs = self._ui_queue.get_nowait()
                try:
                    fn(*args, **kwargs)
                except Exception as exc:
                    tb = traceback.format_exc()
                    _log_crash(f"UI callback error in {getattr(fn, '__name__', fn)}: {exc}\n{tb}")
                    try:
                        self._log_line(f"UI error: {exc}")
                    except Exception:
                        pass
        except queue.Empty:
            pass
        except tk.TclError:
            return
        if not self._shutting_down:
            self._automation_sync_ticks += 1
            if self._automation_sync_ticks >= 8:
                self._automation_sync_ticks = 0
                self._sync_automation_from_config()
            try:
                # Slower poll during background work reduces full-window redraw flicker.
                delay = 150 if self._bg_pipeline_running else self._ui_poll_delay_ms()
                self.after(delay, self._poll_ui)
            except tk.TclError:
                return

    def _schedule(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        if self._shutting_down:
            return
        self._ui_queue.put((fn, args, kwargs))

    def _show_info(self, title: str, msg: str) -> None:
        try:
            self._window.lift()
            self._window.attributes("-topmost", True)
            messagebox.showinfo(title, msg, parent=self._window)
        finally:
            try:
                self._window.attributes("-topmost", False)
            except tk.TclError:
                pass

    def _show_error(self, title: str, msg: str) -> None:
        try:
            self._window.lift()
            self._window.attributes("-topmost", True)
            messagebox.showerror(title, msg, parent=self._window)
        finally:
            try:
                self._window.attributes("-topmost", False)
            except tk.TclError:
                pass

    def _run_network_task(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(fn, *args, **kwargs)
            try:
                return future.result(timeout=NETWORK_TASK_TIMEOUT_SEC)
            except FuturesTimeoutError as exc:
                raise TimeoutError(
                    f"E*TRADE did not respond within {NETWORK_TASK_TIMEOUT_SEC} seconds. "
                    "Check your internet connection and try again."
                ) from exc

    def _on_tk_exception(self, exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        _log_crash(f"Tk callback exception: {text}")
        try:
            messagebox.showerror(
                "Unexpected Error",
                f"The app hit an error but will try to keep running.\n\n{exc}\n\n"
                f"Details were saved to {APP_LOG.name}",
            )
        except Exception:
            pass

    def _ensure_visible(self) -> None:
        """Show maximized at startup without stealing focus."""
        try:
            if self._window.state() == "iconic":
                self._window.deiconify()
            self._window.state("zoomed")
        except tk.TclError:
            try:
                self._window.attributes("-zoomed", True)
            except tk.TclError:
                pass

    def _on_close(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        for after_id in (
            self._bg_pipeline_after_id,
            self._bg_plan_after_id,
            self._bg_day_trading_after_id,
            self._day_refresh_after_id,
            self._bg_status_poll_after_id,
            self._log_flush_after_id,
        ):
            if after_id:
                try:
                    self.after_cancel(after_id)
                except tk.TclError:
                    pass
        if self._setup_canvas is not None:
            try:
                self._setup_canvas.unbind_all("<MouseWheel>")
                self._setup_canvas.unbind_all("<Button-4>")
                self._setup_canvas.unbind_all("<Button-5>")
            except tk.TclError:
                pass
        if self._layout_save_after_id:
            try:
                self.after_cancel(self._layout_save_after_id)
            except tk.TclError:
                pass
            self._layout_save_after_id = None
        self._flush_layout_save()
        try:
            self._window.destroy()
        except tk.TclError:
            pass

    def _bootstrap_config(self) -> None:
        self._load_settings_form()
        if not self.CONFIG_PATH.exists():
            self._env_badge.configure(text="  Setup required  ", fg=WARN, bg="#3d3200")
            self._set_status("Open Settings to enter your API keys", WARN)
            self._show_setup_tab()
            self._update_setup_progress()
            return
        try:
            if not _config_keys_valid(_read_config_file(self.CONFIG_PATH)):
                self._env_badge.configure(text="  Keys needed  ", fg=WARN, bg="#3d3200")
                self._set_status("Enter API keys in Settings and click Save Settings", WARN)
                self._show_setup_tab()
                self._update_setup_progress()
                return
            self._config = load_config(self.CONFIG_PATH)
            self._load_trading_settings_from_config()
            self._sync_trade_flags()
            self._update_automation_control_ui()
            self._update_env_badge(self._config.sandbox)
            persisted = get_selected_account(self.CONFIG_PATH)
            if persisted:
                self._persisted_account_key = persisted.get("account_id_key")
                saved_label = (persisted.get("display_label") or "").strip()
                if saved_label:
                    self._set_status(f"Restoring saved account: {saved_label}…", ACCENT2)
            tokens = load_tokens(self._config.token_path, self._config.sandbox)
            if tokens:
                if is_expired_for_day(tokens):
                    self._set_status(
                        "Session expired (E*TRADE tokens reset at midnight ET) — click Connect",
                        WARN,
                    )
                    self._log_line(
                        "Saved access token is past midnight US/Eastern — full Connect required."
                    )
                else:
                    self._client = ETradeClient(self._config, tokens)
                    self._schedule(self._on_connected)
            else:
                # Tokens may exist for the *other* environment (sandbox vs production).
                other = load_tokens(self._config.token_path, not self._config.sandbox)
                env = "Sandbox" if self._config.sandbox else "Production"
                if other is not None:
                    other_env = "Sandbox" if other.sandbox else "Production"
                    self._set_status(
                        f"Keys OK — click Connect for {env} "
                        f"(saved login is {other_env}, which does not match)",
                        WARN,
                    )
                    self._log_line(
                        f"Token file is for {other_env} but config is {env}. "
                        "Click Connect to authorize this environment."
                    )
                else:
                    self._set_status(
                        f"Settings loaded — click Connect to sign in ({env})",
                        ACCENT2,
                    )
        except Exception as exc:
            self._log_line(f"Config error: {exc}")
            self._show_setup_tab()
        self._update_setup_progress()

    def _load_cached_plan(self) -> None:
        data = load_strategy_plan(self.PLAN_FILE)
        if not data:
            return
        try:
            self._plan = plan_from_dict(data)
            self._render_plan(self._plan, focus_orders_tab=False)
            self._log_line("Loaded cached strategy plan.")
        except Exception as exc:
            self._log_line(f"Could not load cached plan: {exc}")

    def _start_background_engine(self) -> None:
        if self._shutting_down or self._automation_paused:
            if self._automation_paused:
                self._log_line("Automation is paused — click Resume all on Home to restart.")
                self._update_bg_status()
            return

        try:
            from etrade_worker import gui_should_defer_to_worker

            self._gui_defers_to_worker = gui_should_defer_to_worker(self.CONFIG_PATH)
        except Exception:
            self._gui_defers_to_worker = False

        ws = self._worker_settings()
        day_on = "on" if self._day_trading_var.get() else "off"
        if self._gui_defers_to_worker:
            self._log_line(
                "Low-CPU mode: headless worker runs agents and trading — this window is display-only. "
                f"See {self.WORKER_LOG.name}."
            )
        else:
            self._log_line(
                f"Background engine started — agents every {ws.get('pipeline_interval_minutes', 5)} min, "
                f"plan every {ws.get('plan_interval_minutes', 30)} min, "
                f"day trading every {ws.get('day_trading_interval_minutes', 5)} min ({day_on})."
            )
        self._update_bg_status()
        self._refresh_day_trading_panel()
        if self._gui_defers_to_worker:
            self._schedule_bg_status_poll()
        else:
            self._schedule_day_trading_refresh()
            self._schedule_background_pipeline(initial=True)
            self._schedule_background_plan(initial=True)
            self._schedule_background_day_trading(initial=True)

    def _schedule_background_day_trading(self, *, initial: bool = False) -> None:
        if self._automation_paused or self._shutting_down or self._gui_defers_to_worker:
            return
        if self._bg_day_trading_after_id:
            self.after_cancel(self._bg_day_trading_after_id)
        if initial:
            delay = BG_STARTUP_DELAY_MS + 6000
        else:
            delay = self._day_trading_interval_ms()
        self._bg_day_trading_after_id = self.after(delay, self._kick_background_day_trading)

    def _kick_background_day_trading(self, *, manual: bool = False) -> None:
        if self._shutting_down or self._automation_paused:
            return
        if not manual and self._gui_defers_to_worker:
            return
        self._bg_day_trading_after_id = None
        if not self._day_trading_var.get():
            self._schedule_background_day_trading()
            return
        if not self._client or not self._selected_account():
            self._update_bg_status()
            self._schedule_background_day_trading()
            return
        if self._bg_day_trading_running:
            self._schedule_background_day_trading()
            return
        self._bg_day_trading_running = True
        self._update_bg_status()
        threading.Thread(target=self._day_trading_background_worker, daemon=True).start()

    def _day_trading_background_worker(self) -> None:
        try:
            from etrade_worker import run_day_trading_for_client

            if not self._client:
                return
            ran = run_day_trading_for_client(self._client, config_path=self.CONFIG_PATH)
            self._schedule(self._refresh_day_trading_panel)
            self._schedule(self._update_bg_status)
            if ran:
                self._schedule(self._log_line, "[bg] Day trading cycle — orders processed.")
            else:
                self._schedule(self._log_line, "[bg] Day trading scan — nothing to do this cycle.")
        except Exception as exc:
            self._schedule(self._log_line, f"[bg] Day trading error: {exc}")
        finally:
            self._bg_day_trading_running = False
            self._schedule(self._schedule_background_day_trading)

    def _schedule_background_pipeline(self, *, initial: bool = False) -> None:
        if self._automation_paused or self._shutting_down or self._gui_defers_to_worker:
            return
        if self._bg_pipeline_after_id:
            self.after_cancel(self._bg_pipeline_after_id)
        delay = BG_STARTUP_DELAY_MS if initial else self._pipeline_interval_ms()
        self._bg_pipeline_after_id = self.after(delay, self._kick_background_pipeline)

    def _schedule_background_plan(self, *, initial: bool = False, immediate: bool = False) -> None:
        if self._automation_paused or self._shutting_down or self._gui_defers_to_worker:
            return
        if self._bg_plan_after_id:
            self.after_cancel(self._bg_plan_after_id)
        if immediate:
            delay = 1500
        elif initial:
            delay = BG_STARTUP_DELAY_MS + 2000
        else:
            delay = BG_PLAN_INTERVAL_MS
        self._bg_plan_after_id = self.after(delay, self._kick_background_plan)

    def _kick_background_pipeline(self, *, manual: bool = False) -> None:
        if self._shutting_down or self._automation_paused:
            return
        if not manual and self._gui_defers_to_worker:
            return
        self._bg_pipeline_after_id = None
        if self._bg_pipeline_running:
            self._schedule_background_pipeline()
            return
        self._bg_pipeline_running = True
        self._update_bg_status()
        threading.Thread(target=self._pipeline_worker, kwargs={"background": True}, daemon=True).start()

    def _kick_background_plan(self, *, manual: bool = False) -> None:
        if self._shutting_down or self._automation_paused:
            return
        if not manual and self._gui_defers_to_worker:
            return
        self._bg_plan_after_id = None
        if self._bg_pipeline_running or self._bg_execute_running:
            self._schedule_background_plan()
            return
        if not self._client:
            self._update_bg_status()
            self._schedule_background_plan()
            return
        acct = self._selected_account()
        if not acct:
            self._update_bg_status()
            self._schedule_background_plan()
            return
        if self._bg_plan_running:
            self._schedule_background_plan()
            return
        self._bg_plan_running = True
        self._update_bg_status()
        threading.Thread(target=self._plan_worker, args=(acct,), kwargs={"background": True}, daemon=True).start()

    def _account_labels(self, accounts: list[dict[str, Any]] | None = None) -> list[str]:
        source = self._accounts if accounts is None else accounts
        return [a.get("display_label") or format_account_label(a) for a in source]

    def _account_combo_values(self, accounts: list[dict[str, Any]] | None = None) -> list[str]:
        labels = self._account_labels(accounts)
        return [ACCOUNT_PLACEHOLDER] + labels if labels else [ACCOUNT_PLACEHOLDER]

    def _set_account_combo_index(self, idx: int) -> None:
        self._suppress_account_change = True
        try:
            for combo in (self._account_combo, self._setup_account_combo):
                combo.configure(values=self._account_combo_values())
                combo.current(idx)
            if idx > 0 and idx - 1 < len(self._accounts):
                self._account_var.set(self._account_labels()[idx - 1])
            else:
                self._account_var.set(ACCOUNT_PLACEHOLDER)
        finally:
            self._suppress_account_change = False

    def _clear_account_cards(self) -> None:
        self._set_card(self._card_value, "—")
        self._set_card(self._card_cash, "—")
        self._clear_balance_tab()

    def _fetch_confirmed_balance(self) -> None:
        acct = self._selected_account()
        if not acct or not self._client:
            return
        threading.Thread(target=self._fetch_confirmed_balance_thread, args=(acct,), daemon=True).start()

    def _fetch_confirmed_balance_thread(self, acct: dict[str, Any]) -> None:
        try:
            bal = self._client.get_balance(acct["account_id_key"]) if self._client else {}
            total_value = bal.get("total_account_value", 0) or 0
            buying_power = (
                bal.get("cash_buying_power")
                or bal.get("margin_buying_power")
                or bal.get("cash_available_for_investment")
                or bal.get("net_cash")
                or 0
            )
            self._balance_total_value = float(total_value or 0)
            self._schedule(self._set_card, self._card_value, f"${total_value:,.0f}")
            self._schedule(self._set_card, self._card_cash, f"${buying_power:,.0f}")
            self._schedule(self._refresh_capital_cap_status)
            try:
                from analysis_history import get_account_growth, record_account_value

                record_account_value(
                    total_value,
                    account_id_key=acct.get("account_id_key", ""),
                    cash_buying_power=buying_power,
                    source="balance_refresh",
                )
                growth = get_account_growth()
                if growth.get("profit_pct") is not None or growth.get("growth_pct") is not None:
                    pct = growth.get("profit_pct") if growth.get("profit_pct") is not None else growth["growth_pct"]
                    transfer_note = ""
                    if growth.get("net_external_flows"):
                        transfer_note = f" (excludes ${float(growth['net_external_flows']):,.0f} transfers)"
                    self._schedule(
                        self._log_line,
                        f"Account profit since open: {float(pct):+.2f}% "
                        f"(${growth.get('baseline_value', 0):,.0f} → ${growth.get('latest_value', 0):,.0f})"
                        f"{transfer_note}",
                    )
            except Exception:
                pass
            self._schedule(self._update_balance_tab, total_value, buying_power)
        except Exception as exc:
            self._schedule(self._log_line, f"Balance load failed: {exc}")

    def _on_account_changed(self) -> None:
        if self._suppress_account_change:
            return

        idx = self._account_combo.current()
        if idx < 0:
            return

        previous = self._confirmed_account_idx
        if idx == 0:
            self._confirmed_account_idx = None
            self._persisted_account_key = None
            try:
                clear_selected_account(self.CONFIG_PATH)
            except OSError as exc:
                self._log_line(f"Could not clear saved account: {exc}")
            self._clear_account_cards()
            self._set_status("Select and confirm an account to trade", WARN)
            self._log_line("Account selection cleared — confirm an account to enable plans and orders.")
            self._update_setup_progress()
            self._update_bg_status()
            return

        if idx == previous:
            return

        labels = self._account_labels()
        if idx - 1 >= len(self._accounts):
            self._set_account_combo_index(previous if previous is not None else 0)
            return

        label = labels[idx - 1]
        acct = self._accounts[idx - 1]
        env_note = ""
        if self._config:
            if self._config.sandbox:
                env_note = "\n\nSandbox — demo account (not your live portfolio)."
            else:
                env_note = "\n\nPRODUCTION — plans and orders use real money in this account."

        if not messagebox.askyesno(
            "Confirm Account",
            f"Use this account for strategy plans and order execution?\n\n{label}{env_note}\n\n"
            "You can change it anytime from the account dropdown.",
        ):
            self._set_account_combo_index(previous if previous is not None else 0)
            return

        self._confirmed_account_idx = idx
        self._set_account_combo_index(idx)
        try:
            save_selected_account(
                acct["account_id_key"],
                display_label=label,
                path=self.CONFIG_PATH,
            )
            self._persisted_account_key = acct["account_id_key"]
        except OSError as exc:
            self._log_line(f"Could not save account choice: {exc}")
        self._log_line(f"Account confirmed: {label} (saved for restarts)")
        self._set_status(f"Trading account: {label}", UP)
        self._update_setup_progress()
        self._update_bg_status()
        self._fetch_confirmed_balance()
        if self._client:
            self._schedule_background_plan(immediate=True)

    def _schedule_day_trading_refresh(self) -> None:
        if self._shutting_down or self._automation_paused or self._gui_defers_to_worker:
            return
        self._refresh_day_trading_panel()
        try:
            self._day_refresh_after_id = self.after(30000, self._schedule_day_trading_refresh)
        except tk.TclError:
            pass

    def _read_day_state(self) -> dict[str, Any]:
        if not self.DAY_STATE_FILE.exists():
            return {}
        try:
            return json.loads(self.DAY_STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _refresh_day_trading_panel(self) -> None:
        if not hasattr(self, "_day_summary_label"):
            return
        enabled = self._day_trading_var.get()
        state = self._read_day_state()
        positions = state.get("positions", []) or []
        stats = state.get("stats", {}) or {}
        pnl = float(stats.get("realized_pnl_usd", 0))
        wins = int(stats.get("wins", 0))
        losses = int(stats.get("losses", 0))

        if not enabled:
            summary = "Day trading is off — enable it on the Home tab under “How do you want to trade?”"
            status = "Day trading disabled"
            color = MUTED
        else:
            mode = "dry run" if self._dry_run_var.get() else "LIVE"
            summary = (
                f"Day trading {mode} — scans every 5 min during market hours. "
                f"Today: {len(positions)} open, {wins}W/{losses}L, P&L ${pnl:+,.2f}"
            )
            status = f"Day positions: {len(positions)} open · P&L ${pnl:+,.2f}"
            color = ACCENT2 if self._dry_run_var.get() else UP

        self._day_summary_label.configure(text=summary)
        if hasattr(self, "_day_status_label"):
            self._day_status_label.configure(text=status, fg=color)

        if getattr(self, "_day_positions_tree", None) is not None:
            self._tree_clear(self._day_positions_tree)
        if getattr(self, "_day_orders_tree", None) is not None:
            self._tree_clear(self._day_orders_tree)

        for pos in positions:
            sym = pos.get("symbol", "")
            entry = float(pos.get("entry_price", 0))
            tp = float(pos.get("take_profit_pct", 0.75))
            sl = float(pos.get("stop_loss_pct", 0.5))
            self._tree_insert(
                self._day_positions_tree,
                (
                    sym,
                    pos.get("quantity", 0),
                    f"${entry:.2f}",
                    f"+{tp:.2f}%",
                    f"-{sl:.2f}%",
                    (pos.get("rationale") or "")[:160],
                ),
            )

        plan_data = load_strategy_plan(self.DAY_PLAN_FILE)
        if plan_data:
            try:
                day_plan = plan_from_dict(plan_data)
                for order in day_plan.orders:
                    est = order.quantity * order.estimated_price
                    tag = "buy" if order.action == "BUY" else "sell"
                    self._tree_insert(
                        self._day_orders_tree,
                        (
                            order.symbol,
                            order.action,
                            self._format_order_type(order),
                            order.quantity,
                            f"${order.estimated_price:.2f}",
                            f"${est:,.0f}",
                            order.status,
                            order.message or order.rationale[:100],
                        ),
                        extra_tags=(tag,),
                    )
            except Exception:
                pass

    def _run_day_trade_scan(self) -> None:
        if self._automation_paused:
            messagebox.showinfo("Automation paused", "Click Resume all on the Home tab first.")
            return
        if not self._client or not self._selected_account():
            messagebox.showinfo("Connect First", "Connect to E*TRADE and confirm an account.")
            return
        if not self._day_trading_var.get():
            messagebox.showinfo("Day Trading Off", "Enable day trading on the Home tab first.")
            return
        if self._busy:
            return
        self._set_busy(True)
        self._show_trades_tab(swing=False)
        threading.Thread(target=self._day_trade_scan_worker, daemon=True).start()

    def _day_trade_scan_worker(self) -> None:
        try:
            from day_trader import build_day_trade_plan, load_day_state, load_day_trade_settings

            acct = self._selected_account()
            if not acct or not self._client:
                return
            settings = load_day_trade_settings(self.CONFIG_PATH)
            state = load_day_state()
            plan = build_day_trade_plan(
                self._client,
                acct["account_id_key"],
                acct.get("account_name", ""),
                settings=settings,
                state=state,
            )
            self._schedule(self._refresh_day_trading_panel)
            n = len(plan.orders)
            self._schedule(self._log_line, f"Day trade scan: {n} proposed intraday order(s).")
            self._schedule(self._set_status, f"Day trade scan — {n} order(s)", UP if n else ACCENT2)
            if n and self._auto_execute_var.get() and not self._dry_run_var.get():
                if self._config and not self._config.sandbox:
                    self._schedule(
                        messagebox.showinfo,
                        "Day Trade Orders Ready",
                        f"{n} intraday order(s) proposed. Background worker submits them every 5 min, "
                        "or run Install ETrade Background.bat for scheduled day trading.",
                    )
        except Exception as exc:
            self._schedule(messagebox.showerror, "Day Trade Scan", str(exc))
            self._schedule(self._log_line, f"Day trade scan error: {exc}")
        finally:
            self._schedule(self._set_busy, False)

    def _update_bg_status(self) -> None:
        if self._automation_paused:
            stopped = ("Stopped", MUTED)
            self._bg_agents_label.configure(text=stopped[0], fg=stopped[1])
            self._bg_plan_label.configure(text=stopped[0], fg=stopped[1])
            if hasattr(self, "_bg_orders_label"):
                self._bg_orders_label.configure(text=stopped[0], fg=stopped[1])
            if hasattr(self, "_bg_day_label"):
                self._bg_day_label.configure(text=stopped[0], fg=stopped[1])
            if hasattr(self, "_bg_updated_label"):
                self._bg_updated_label.configure(text="Automation paused")
            return

        if self._worker_pipeline_stuck:
            stuck_label = self._worker_pipeline_progress or "Agent stalled"
            agents_text, agents_color = f"Stuck · {stuck_label}", DOWN
        elif self._bg_pipeline_running:
            if self._gui_defers_to_worker and self._worker_pipeline_progress:
                agents_text = self._worker_pipeline_progress
            else:
                agents_text = "Worker active…" if self._gui_defers_to_worker else "Running now…"
            agents_text, agents_color = agents_text, WARN
        elif self._last_pipeline_at:
            from datetime import datetime
            ts = datetime.fromtimestamp(self._last_pipeline_at).strftime("%H:%M")
            agents_text, agents_color = f"Idle · {ts}", UP
        else:
            agents_text, agents_color = "Queued", ACCENT2

        if not self._client:
            plan_text, plan_color = "Connect first", MUTED
        elif not self._selected_account():
            plan_text, plan_color = "Pick account", WARN
        elif self._bg_plan_running:
            plan_text, plan_color = "Updating…", WARN
        elif self._last_plan_at:
            from datetime import datetime
            ts = datetime.fromtimestamp(self._last_plan_at).strftime("%H:%M")
            plan_text, plan_color = f"Ready · {ts}", UP
        else:
            plan_text, plan_color = "Queued", ACCENT2

        self._bg_agents_label.configure(text=agents_text, fg=agents_color)
        self._bg_plan_label.configure(text=plan_text, fg=plan_color)

        if self._auto_execute_var.get():
            if self._bg_execute_running:
                orders_text, orders_color = "Placing orders…", WARN
            elif self._dry_run_var.get():
                orders_text, orders_color = "Practice mode", ACCENT2
            elif self._config and not self._config.sandbox:
                if self._last_execute_at:
                    from datetime import datetime
                    ts = datetime.fromtimestamp(self._last_execute_at).strftime("%H:%M")
                    orders_text, orders_color = f"Live · {ts}", UP
                else:
                    orders_text, orders_color = "Live · waiting", DOWN
            elif self._last_execute_at:
                from datetime import datetime
                ts = datetime.fromtimestamp(self._last_execute_at).strftime("%H:%M")
                orders_text, orders_color = f"Auto · {ts}", UP
            else:
                orders_text, orders_color = "Auto", ACCENT2
        else:
            orders_text, orders_color = "Manual only", MUTED
        if hasattr(self, "_bg_orders_label"):
            self._bg_orders_label.configure(text=orders_text, fg=orders_color)

        if hasattr(self, "_bg_day_label"):
            if self._day_trading_var.get():
                if self._last_day_trade_at:
                    from datetime import datetime
                    ts = datetime.fromtimestamp(self._last_day_trade_at).strftime("%H:%M")
                    label = f"On · {ts}"
                else:
                    label = "On · waiting"
                if self._dry_run_var.get():
                    label = "On · practice"
                self._bg_day_label.configure(text=label, fg=UP if not self._dry_run_var.get() else ACCENT2)
            else:
                self._bg_day_label.configure(text="Off", fg=MUTED)

        latest = max(
            filter(
                None,
                [
                    self._last_pipeline_at,
                    self._last_plan_at,
                    self._last_execute_at,
                    self._last_day_trade_at,
                ],
            ),
            default=None,
        )
        if latest:
            from datetime import datetime
            self._bg_updated_label.configure(text=f"Last update: {datetime.fromtimestamp(latest).strftime('%H:%M:%S')}")
        else:
            self._bg_updated_label.configure(text="Last update: —")

    @staticmethod
    def _plan_order_signature(plan: StrategyPlan) -> str:
        items = tuple(
            (o.symbol.upper(), o.action.upper(), int(o.quantity))
            for o in plan.orders
            if o.quantity > 0
        )
        return repr(sorted(items))

    def _should_auto_execute(self, plan: StrategyPlan) -> bool:
        if self._automation_paused:
            return False
        if not self._auto_execute_var.get() or not self._client or not self._selected_account() or not plan.orders:
            return False
        sig = self._plan_order_signature(plan)
        if sig == self._last_executed_plan_sig:
            return False
        if self._last_execute_at and (time.time() - self._last_execute_at) < BG_EXECUTE_MIN_INTERVAL_MS / 1000:
            return False
        return True

    def _trigger_auto_execute(self, plan: StrategyPlan) -> None:
        if not self._should_auto_execute(plan):
            if plan.orders and self._auto_execute_var.get():
                self._schedule(self._log_line, "[bg] Orders unchanged or recently executed — skipping.")
            return
        if self._bg_execute_running:
            return
        self._bg_execute_running = True
        self._schedule(self._update_bg_status)
        threading.Thread(target=self._execute_plan_worker, args=(plan,), kwargs={"background": True}, daemon=True).start()

    def _connect(self) -> None:
        form_has_keys = bool(
            sanitize_credential(self._key_var.get(), KEY_PLACEHOLDER)
            and sanitize_credential(self._secret_var.get(), SECRET_PLACEHOLDER)
        )
        if not _config_keys_valid(_read_config_file(self.CONFIG_PATH)) and not form_has_keys:
            messagebox.showinfo(
                "Setup Required",
                "Enter your Consumer Key and Secret in the Setup tab,\n"
                "then click Save Settings or Connect.",
            )
            self._show_setup_tab()
            return
        if self._busy:
            return
        config = self._persist_settings_from_form(silent=True)
        if config is None:
            messagebox.showwarning(
                "Missing Fields",
                "Enter both Consumer Key and Consumer Secret before connecting.",
            )
            self._show_setup_tab()
            return
        self._connect_epoch += 1
        epoch = self._connect_epoch
        self._set_busy(True)
        self._set_status("Opening E*TRADE authorization…", WARN)
        threading.Thread(target=self._connect_thread, args=(config, epoch), daemon=True).start()

    def _show_oauth_verify_dialog(self, pending: OAuthPending) -> None:
        if self._oauth_dialog and self._oauth_dialog.winfo_exists():
            self._oauth_dialog.lift()
            return

        self._oauth_pending = pending
        self._set_busy(False)
        try:
            self._window.lift()
            self._window.deiconify()
        except tk.TclError:
            pass
        self._set_status("Waiting for E*TRADE verification code…", WARN)
        self._log_line("Enter the verification code from E*TRADE in the dialog.")

        def _submit(code: str) -> None:
            self._connect_epoch += 1
            epoch = self._connect_epoch
            self._set_busy(True)
            self._set_status("Completing authorization…", WARN)
            threading.Thread(
                target=self._finish_oauth_connect,
                args=(pending, code, epoch),
                daemon=True,
            ).start()

        def _cancel() -> None:
            self._oauth_pending = None
            self._set_busy(False)
            self._set_status("Authorization cancelled", MUTED)
            self._log_line("E*TRADE authorization cancelled.")

        self._oauth_dialog = OAuthVerifyDialog(
            self._window, pending.authorize_url, self._m, _submit, _cancel,
        )
        webbrowser.open(pending.authorize_url)

    def _finish_oauth_connect(self, pending: OAuthPending, verifier: str, epoch: int) -> None:
        try:
            tokens = self._run_network_task(finish_authorization, pending, verifier)
            if epoch != self._connect_epoch:
                return
            self._oauth_pending = None
            self._client = ETradeClient(pending.config, tokens)
            self._config = pending.config
            self._schedule(self._on_connected)
            self._schedule(self._set_status, "Connected to E*TRADE", UP)
            self._schedule(self._log_line, "OAuth complete — account linked.")
        except Exception as exc:
            msg = str(exc)
            self._schedule(self._show_error, "Verification Failed", msg)
            self._schedule(self._set_status, "Verification failed — try Connect again", DOWN)
            self._schedule(self._log_line, f"Verification failed: {msg}")
        finally:
            self._schedule(self._set_busy, False)

    def _connect_thread(self, config: ETradeConfig | None = None, epoch: int = 0) -> None:
        dialog_scheduled = False
        try:
            self._config = config or load_config(self.CONFIG_PATH)
            if self._config.use_oob:
                pending = self._run_network_task(start_authorization, self._config)
                if epoch != self._connect_epoch:
                    return
                self._schedule(self._show_oauth_verify_dialog, pending)
                dialog_scheduled = True
                return

            tokens = self._run_network_task(authenticate, self._config, open_browser=True)
            if epoch != self._connect_epoch:
                return
            self._client = ETradeClient(self._config, tokens)
            self._schedule(self._on_connected)
            self._schedule(self._set_status, "Connected to E*TRADE", UP)
            self._schedule(self._log_line, "OAuth complete — account linked.")
        except Exception as exc:
            msg = str(exc)
            if "callback_rejected" in msg and (not self._config or not self._config.use_oob):
                msg += (
                    "\n\nTip: Enable “Use verification code (OOB)” in Setup, "
                    "click Save Settings, then connect again."
                )
            elif "consumer_key_rejected" in msg:
                msg += (
                    "\n\nTip: Regenerate or recopy both key and secret from developer.etrade.com — "
                    "the secret must be copied at the same time as the key."
                )
            self._schedule(self._show_error, "Connect Failed", msg)
            self._schedule(self._set_status, "Connect failed — see error dialog", DOWN)
            self._schedule(self._log_line, f"Connect failed: {msg}")
        finally:
            if not dialog_scheduled:
                self._schedule(self._set_busy, False)

    def _on_connected(self) -> None:
        self._conn_status.configure(text="● Connected", fg=UP)
        if self._config:
            self._update_env_badge(self._config.sandbox)
        self._update_setup_progress()
        self._update_bg_status()
        self._refresh_account(silent=True)
        self._show_dashboard_tab()

    def _clear_local_tokens(self) -> None:
        if not self._config:
            return
        token_path = Path(self._config.token_path)
        if token_path.exists():
            token_path.unlink()

    def _mark_offline(self, *, status: str = "Disconnected", log: str | None = None) -> None:
        self._client = None
        self._conn_status.configure(text="● Offline", fg=DOWN)
        self._set_status(status, MUTED if status == "Disconnected" else DOWN)
        if log:
            self._log_line(log)
        self._update_setup_progress()
        self._update_bg_status()

    def _disconnect(self) -> None:
        self._connect_epoch += 1
        self._oauth_pending = None
        if self._config:
            try:
                tokens = load_tokens(self._config.token_path, self._config.sandbox)
                if tokens:
                    revoke_access_token(self._config, tokens)
                else:
                    self._clear_local_tokens()
            except Exception:
                self._clear_local_tokens()
        self._client = None
        self._accounts = []
        self._confirmed_account_idx = None
        # Keep persisted account key so reconnect/refresh restores the saved choice.
        self._account_combo.configure(values=[ACCOUNT_PLACEHOLDER])
        self._setup_account_combo.configure(values=[ACCOUNT_PLACEHOLDER])
        self._set_account_combo_index(0)
        self._clear_account_cards()
        self._conn_status.configure(text="● Offline", fg=DOWN)
        self._set_status("Disconnected", MUTED)
        self._log_line("Disconnected from E*TRADE.")
        self._update_setup_progress()
        self._update_bg_status()

    def _selected_account(self) -> dict[str, Any] | None:
        if self._confirmed_account_idx is None or self._confirmed_account_idx <= 0:
            return None
        acct_idx = self._confirmed_account_idx - 1
        if 0 <= acct_idx < len(self._accounts):
            return self._accounts[acct_idx]
        return None

    def _refresh_account(self, *, silent: bool = False) -> None:
        if not self._client:
            if not silent:
                messagebox.showinfo("Not Connected", "Connect to E*TRADE first.")
            return
        if getattr(self, "_refresh_running", False):
            if not silent:
                self._log_line("Account refresh already in progress…")
            return
        self._refresh_running = True
        self._set_busy(True)
        threading.Thread(target=self._refresh_thread, kwargs={"silent": silent}, daemon=True).start()

    def _refresh_thread(self, *, silent: bool = False) -> None:
        try:
            accounts = self._client.list_accounts() if self._client else []
            self._schedule(self._apply_accounts, accounts)
            self._schedule(self._set_status, "Account refreshed", UP)
            self._schedule(self._log_line, f"Loaded {len(accounts)} account(s).")
            if self._selected_account():
                self._schedule(self._fetch_confirmed_balance)
                self._schedule(self._schedule_background_plan, immediate=True)
            elif accounts:
                self._schedule(
                    self._set_status,
                    f"Loaded {len(accounts)} account(s) — select and confirm one to trade",
                    WARN,
                )
        except Exception as exc:
            msg = str(exc)
            if "session expired" in msg.lower() or "token expired" in msg.lower():
                self._schedule(
                    self._mark_offline,
                    status="Session expired — click Connect to sign in again",
                    log=f"Account refresh failed: {msg}",
                )
            elif silent:
                self._schedule(self._log_line, f"Account refresh failed: {msg}")
                self._schedule(self._set_status, msg[:120], DOWN)
            else:
                self._schedule(messagebox.showerror, "Refresh Failed", msg)
                self._schedule(self._set_status, msg[:120], DOWN)
        finally:
            self._refresh_running = False
            self._schedule(self._set_busy, False)

    def _restore_account_keys(self) -> list[str]:
        keys: list[str] = []
        if self._confirmed_account_idx and self._confirmed_account_idx > 0:
            old_idx = self._confirmed_account_idx - 1
            if 0 <= old_idx < len(self._accounts):
                key = self._accounts[old_idx].get("account_id_key")
                if key:
                    keys.append(key)
        if self._persisted_account_key and self._persisted_account_key not in keys:
            keys.append(self._persisted_account_key)
        persisted = get_selected_account(self.CONFIG_PATH)
        if persisted:
            key = persisted.get("account_id_key")
            if key and key not in keys:
                keys.append(key)
            if key:
                self._persisted_account_key = key
        if not keys:
            plan_data = load_strategy_plan(self.PLAN_FILE)
            if plan_data:
                key = str(plan_data.get("account_id_key") or "").strip()
                if key:
                    keys.append(key)
        return keys

    def _apply_accounts(self, accounts: list[dict[str, Any]]) -> None:
        restore_keys = self._restore_account_keys()

        self._accounts = accounts
        values = self._account_combo_values(accounts)
        self._account_combo.configure(values=values)
        self._setup_account_combo.configure(values=values)

        restored = False
        labels = self._account_labels()
        for restore_key in restore_keys:
            if not restore_key:
                continue
            for i, acct in enumerate(accounts):
                if acct.get("account_id_key") == restore_key:
                    self._confirmed_account_idx = i + 1
                    self._set_account_combo_index(i + 1)
                    self._log_line(f"Restored trading account: {labels[i]}")
                    if not get_selected_account(self.CONFIG_PATH):
                        try:
                            save_selected_account(
                                acct["account_id_key"],
                                display_label=labels[i],
                                path=self.CONFIG_PATH,
                            )
                            self._persisted_account_key = acct["account_id_key"]
                            self._log_line("Saved restored account for background worker and restarts.")
                        except OSError as exc:
                            self._log_line(f"Could not save restored account: {exc}")
                    restored = True
                    break
            if restored:
                break
        if restored and self._confirmed_account_idx:
            label = labels[self._confirmed_account_idx - 1]
            self._set_status(f"Trading account: {label}", UP)
            self._update_bg_status()
            self._fetch_confirmed_balance()
            if not self._gui_defers_to_worker:
                self._schedule_background_plan(immediate=True)
        elif not restored:
            self._confirmed_account_idx = None
            self._set_account_combo_index(0)
            self._clear_account_cards()

        if self._config and self._config.sandbox:
            if accounts_look_like_sandbox_demo(accounts):
                self._log_line(
                    "Sandbox demo accounts loaded (NickName-*, etc.). "
                    "These are not your real accounts — switch to Production to see yours."
                )
            else:
                self._log_line("Sandbox accounts loaded — these are for testing, not your live portfolio.")
        else:
            self._log_line(f"Loaded {len(accounts)} production account(s).")

        self._update_sandbox_notice()
        self._update_setup_progress()

    def _on_pipeline_started(self) -> None:
        if hasattr(self, "_bg_agents_label"):
            self._bg_agents_label.configure(text="Running…", fg=WARN)
        self._queue_log_line("Agent pipeline started.", prefix="[bg] ")

    def _on_pipeline_progress_quiet(self, msg: str) -> None:
        """Background agent updates — no status-bar or focus churn."""
        if hasattr(self, "_bg_agents_label") and msg.startswith("Agent "):
            short = msg.split(":", 1)[-1].strip() if ":" in msg else msg
            if len(short) > 28:
                short = short[:25] + "…"
            self._bg_agents_label.configure(text=short, fg=WARN)
        self._queue_log_line(msg, prefix="[bg] ")

    def _run_pipeline(self) -> None:
        if self._bg_pipeline_running:
            messagebox.showinfo("Pipeline Running", "Agent pipeline is already running in the background.")
            return
        self._kick_background_pipeline(manual=True)

    def _pipeline_worker(self, *, background: bool = True) -> None:
        lock_ok = False
        try:
            from etrade_worker import acquire_worker_lock, release_worker_lock

            if not acquire_worker_lock():
                self._schedule(self._log_line, "[bg] Pipeline skipped - headless worker is already running.")
                return
            lock_ok = True

            def progress(msg: str) -> None:
                if background:
                    self._schedule(self._on_pipeline_progress_quiet, msg)
                else:
                    self._schedule(self._set_status, msg, WARN)
                    self._schedule(self._log_line, msg)

            if background:
                self._schedule(self._on_pipeline_started)
            else:
                self._schedule(self._set_status, "Running agent pipeline…", WARN)

            ok = run_agent_pipeline(
                on_progress=progress,
                check_remote=not background,
                reload_runners=True,
            )
            self._last_pipeline_at = time.time()
            self._schedule(self._refresh_reports_ui, select_latest=True)
            if background:
                self._schedule(self._queue_log_line, f"Pipeline complete — {ok} agent reports updated.", prefix="[bg] ")
            else:
                self._schedule(self._set_status, f"Pipeline complete — {ok} agent reports", UP)
                self._schedule(self._log_line, f"Agent reports updated ({ok} agents).")
            self._schedule(self._schedule_background_plan, immediate=True)
        except Exception as exc:
            if background:
                self._schedule(self._log_line, f"[bg] Pipeline error: {exc}")
                self._schedule(self._set_status, f"Background pipeline error: {exc}", DOWN)
            else:
                self._schedule(messagebox.showerror, "Pipeline Error", str(exc))
                self._schedule(self._set_status, str(exc), DOWN)
        finally:
            if lock_ok:
                try:
                    from etrade_worker import release_worker_lock

                    release_worker_lock()
                except Exception:
                    pass
            self._bg_pipeline_running = False
            self._schedule(self._update_bg_status)
            self._schedule(self._schedule_background_pipeline)

    def _build_plan(self) -> None:
        if not self._client:
            messagebox.showinfo("Connect", "Connect to E*TRADE first.")
            return
        if not self._accounts:
            messagebox.showinfo("Account", "Refresh accounts after connecting.")
            return
        if not self._selected_account():
            messagebox.showinfo(
                "Confirm Account",
                "Select an account from the dropdown and confirm your choice before building a plan.",
            )
            return
        if self._bg_plan_running:
            messagebox.showinfo("Plan Updating", "Strategy plan is already updating in the background.")
            return
        self._kick_background_plan(manual=True)

    def _plan_worker(self, acct: dict[str, Any], *, background: bool = True) -> None:
        try:
            if background:
                self._schedule(self._update_bg_status)
            else:
                self._schedule(self._set_status, "Building strategy plan…", WARN)

            from portfolio_generator import generate_portfolio, save_portfolio
            from strategy_engine import PORTFOLIO_FILE

            balance = self._client.get_balance(acct["account_id_key"])
            notional = balance.get("total_account_value") or None
            portfolio = generate_portfolio(OUTPUT, notional_usd=notional)
            save_portfolio(portfolio, PORTFOLIO_FILE)
            plan = build_strategy_plan(
                self._client,
                acct["account_id_key"],
                acct.get("account_name", ""),
                portfolio=portfolio,
            )
            save_strategy_plan(plan)
            self._plan = plan
            self._last_plan_at = time.time()
            self._schedule(self._render_plan, plan, not background)
            self._schedule(self._set_status, f"Plan ready — {len(plan.orders)} orders", UP)
            prefix = "[bg] " if background else ""
            self._schedule(self._log_line, f"{prefix}Strategy plan: {len(plan.orders)} proposed trades.")
            if background and plan.orders and not self._shutting_down:
                self._schedule(self._trigger_auto_execute, plan)
        except Exception as exc:
            if background:
                self._schedule(self._log_line, f"[bg] Plan error: {exc}")
                self._schedule(self._set_status, f"Background plan error: {exc}", DOWN)
            else:
                self._schedule(messagebox.showerror, "Plan Error", str(exc))
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
            self._schedule(self._set_status, f"{'Simulating' if dry_run else 'Submitting'} {len(plan.orders)} orders…", WARN)
            self._schedule(self._log_line, f"{prefix}Previewing {len(plan.orders)} orders with E*TRADE…")

            preview_orders(self._client, plan)
            previewed = sum(1 for o in plan.orders if o.status == "previewed")
            if previewed == 0:
                self._schedule(self._log_line, f"{prefix}No orders passed preview — nothing to execute.")
                self._schedule(self._set_status, "No valid orders to execute", WARN)
                return

            execute_orders(self._client, plan, dry_run=dry_run)
            save_strategy_plan(plan)
            self._plan = plan
            self._last_executed_plan_sig = self._plan_order_signature(plan)
            self._last_execute_at = time.time()

            placed = sum(1 for o in plan.orders if o.status in {"placed", "dry_run"})
            self._schedule(self._render_plan, plan, False)
            if dry_run:
                self._schedule(self._set_status, f"Dry run — simulated {placed} orders", ACCENT2)
                self._schedule(self._log_line, f"{prefix}Dry run complete — {placed} orders simulated.")
            else:
                self._schedule(self._set_status, f"Submitted {placed} orders to E*TRADE", UP)
                self._schedule(self._log_line, f"{prefix}Orders placed: {placed}")
                if self._config and not self._config.sandbox:
                    self._schedule(self._log_line, f"{prefix}PRODUCTION — live trades submitted.")
            self._schedule(self._refresh_account, silent=True)
        except Exception as exc:
            if background:
                self._schedule(self._log_line, f"[bg] Execute error: {exc}")
                self._schedule(self._set_status, f"Auto-execute error: {exc}", DOWN)
            else:
                self._schedule(messagebox.showerror, "Execute Error", str(exc))
                self._schedule(self._set_status, str(exc), DOWN)
        finally:
            self._bg_execute_running = False
            if not background:
                self._schedule(self._set_busy, False)
            self._schedule(self._update_bg_status)

    def _render_plan(self, plan: StrategyPlan, focus_orders_tab: bool = True) -> None:
        self._set_card(self._card_value, f"${plan.total_account_value:,.0f}")
        self._set_card(self._card_orders, str(len(plan.orders)), WARN if plan.orders else UP)
        self._balance_total_value = float(plan.total_account_value or 0)
        self._update_balance_tab(plan.total_account_value)
        self._update_history_tab()
        self._update_attribution_tab()
        self._refresh_capital_cap_status()

        from position_analysis import projected_return_compact

        self._tree_clear(self._holdings_tree)
        self._tree_clear(self._orders_tree)

        portfolio_map = self._portfolio_holdings_map()
        pos_map = {p["symbol"].upper(): p for p in plan.current_positions}
        target_map = {h["symbol"].upper(): h for h in plan.target_holdings}
        symbols = sorted(set(pos_map) | set(target_map))
        total = plan.total_account_value or 1

        for sym in symbols:
            cur = pos_map.get(sym, {})
            tgt = self._holding_with_projection(target_map.get(sym), sym) or {}
            cur_usd = float(cur.get("market_value", 0))
            projection = projected_return_compact(tgt if tgt else portfolio_map.get(sym))
            tgt_usd = float(
                tgt.get("allocation_usd")
                or (plan.investable_usd * float(tgt.get("weight_pct", 0)) / 100)
            )
            cur_pct = cur_usd / total * 100
            tgt_pct = float(tgt.get("weight_pct", 0))
            drift = tgt_pct - cur_pct
            drift_tags = ("drift_high",) if abs(drift) >= 2.0 else ()
            self._tree_insert(
                self._holdings_tree,
                (
                    sym,
                    f"{cur_pct:.1f}%",
                    f"{tgt_pct:.1f}%",
                    projection,
                    f"${cur_usd:,.0f}",
                    f"${tgt_usd:,.0f}",
                    f"{drift:+.1f}%",
                ),
                extra_tags=drift_tags,
            )

        for order in plan.orders:
            est = order.quantity * order.estimated_price
            color_tag = "buy" if order.action == "BUY" else "sell"
            self._tree_insert(
                self._orders_tree,
                (
                    order.symbol,
                    order.action,
                    self._format_order_type(order),
                    order.quantity,
                    f"${order.estimated_price:.2f}",
                    f"${est:,.0f}",
                    order.status,
                    order.message or order.rationale[:100],
                ),
                extra_tags=(color_tag,),
            )
        if focus_orders_tab:
            self._show_trades_tab(swing=True)

    def _preview_orders(self) -> None:
        if not self._client or not self._plan:
            messagebox.showinfo("Plan Required", "Build a strategy plan first (step 2).")
            return
        if not self._selected_account():
            messagebox.showinfo(
                "Confirm Account",
                "Select and confirm an account before previewing orders.",
            )
            return
        if self._busy:
            return
        self._set_busy(True)
        threading.Thread(target=self._preview_thread, daemon=True).start()

    def _preview_thread(self) -> None:
        try:
            preview_orders(self._client, self._plan)
            save_strategy_plan(self._plan)
            self._schedule(self._render_plan, self._plan)
            ok = sum(1 for o in self._plan.orders if o.status == "previewed")
            self._schedule(self._set_status, f"Previewed {ok}/{len(self._plan.orders)} orders", UP)
            self._schedule(self._log_line, f"E*TRADE preview: {ok} orders validated.")
        except Exception as exc:
            self._schedule(messagebox.showerror, "Preview Error", str(exc))
        finally:
            self._schedule(self._set_busy, False)

    def _execute_orders(self) -> None:
        if not self._client or not self._plan:
            messagebox.showinfo("Plan Required", "Build a strategy plan first.")
            return
        if not self._selected_account():
            messagebox.showinfo(
                "Confirm Account",
                "Select and confirm an account before executing orders.",
            )
            return
        if not self._plan.orders:
            messagebox.showinfo("No Orders", "The current plan has no trades to execute.")
            return
        if self._bg_execute_running:
            messagebox.showinfo("Executing", "Orders are already being executed in the background.")
            return
        if not self._dry_run_var.get() and self._config and not self._config.sandbox:
            if not messagebox.askyesno(
                "PRODUCTION WARNING",
                "You are on PRODUCTION (live money).\n\n"
                f"Submit {len(self._plan.orders)} orders to E*TRADE?\n\n"
                "This cannot be undone from this app.",
            ):
                return
        if self._busy:
            return
        self._set_busy(True)
        self._bg_execute_running = True
        threading.Thread(
            target=self._execute_plan_worker,
            args=(self._plan,),
            kwargs={"background": False, "force": True},
            daemon=True,
        ).start()


def main() -> int:
    try:
        from win_app_identity import apply_windows_app_identity

        apply_windows_app_identity()
        app = ETradeTraderApp()
        if os.environ.get("ETRADE_TAB", "").lower() in {"agents", "finance-agents"}:
            app._window.after(200, app._select_agents_tab)
        app._window.mainloop()
    except Exception as exc:
        _log_crash(f"Fatal error: {exc}\n{traceback.format_exc()}")
        try:
            messagebox.showerror(
                "E*TRADE Trader",
                f"The app closed due to an error:\n\n{exc}\n\nDetails: {APP_LOG}",
            )
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())