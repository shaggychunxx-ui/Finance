#!/usr/bin/env python3
"""Unified E*TRADE Trader — desktop UI aligned with the phone E*TRADE Trader app.

Windows (match phone swipe order):
  Dashboard · Positions · Orders · Agents · Settings

Data comes from the same builders as the phone bridge (`phone_bridge.build_*`)
so PC and phone show the same balances, positions, orders, and modes.
Long/Short power tools remain under Settings → Advanced tools.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_paths import ICON_FILE, ensure_app_path
from gui_theme import (
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
    ScreenMetrics,
    configure_trader_notebooks,
    configure_treeview_style,
    load_palette_from_prefs,
    load_ui_layout,
    save_ui_layout,
    sync_module_globals,
)

ensure_app_path()

import tkinter as tk
from tkinter import messagebox, ttk

UNIFIED_APP_ID = "Finance.ETrade.UnifiedTrader.1"
UNIFIED_MUTEX_NAME = "Local\\Finance.ETrade.UnifiedTrader.SingleInstance"
UNIFIED_WINDOW_TITLE = "E*TRADE Trader"
UNIFIED_LOG = ROOT / "output" / "unified_trader.log"
LONG_CONFIG = ROOT / "etrade_config.json"
SHORT_CONFIG = ROOT / "short_etrade_config.json"

# Held for process lifetime so a second launch exits instead of opening another window.
_single_instance_mutex: int | None = None

# Phone WindowScheme colors (Dashboard · Positions · Orders · Agents · Settings)
PHONE_WINDOWS: list[dict[str, str]] = [
    {
        "id": "dashboard",
        "title": "Dashboard",
        "accent": "#E8B84A",
        "bg": "#14110C",
        "panel": "#1E1A14",
        "data": "#2A241C",
        "edge": "#4A3C28",
        "text": "#FFF6E8",
        "muted": "#C4B49A",
        "up": "#5DFF9A",
        "down": "#FF7A8C",
        "warn": "#FFC14D",
        "on_btn": "#1A1208",
    },
    {
        "id": "positions",
        "title": "Positions",
        "accent": "#3DDC97",
        "bg": "#0A1410",
        "panel": "#12201A",
        "data": "#1A2C24",
        "edge": "#2A4A3A",
        "text": "#F0FFF6",
        "muted": "#A8C8B8",
        "up": "#6EFFB0",
        "down": "#FF8A9A",
        "warn": "#FFC14D",
        "on_btn": "#041208",
    },
    {
        "id": "orders",
        "title": "Orders",
        "accent": "#C084FC",
        "bg": "#120F18",
        "panel": "#1C1626",
        "data": "#2A2038",
        "edge": "#4A3A62",
        "text": "#F8F0FF",
        "muted": "#C4B0D8",
        "up": "#6EFFB0",
        "down": "#FF8A9A",
        "warn": "#FFC14D",
        "on_btn": "#100818",
    },
    {
        "id": "agents",
        "title": "Agents",
        "accent": "#6EB5FF",
        "bg": "#0A1018",
        "panel": "#121C28",
        "data": "#1A2838",
        "edge": "#2A4460",
        "text": "#F0F6FF",
        "muted": "#A0B8D0",
        "up": "#6EFFB0",
        "down": "#FF8A9A",
        "warn": "#FFC14D",
        "on_btn": "#061018",
    },
    {
        "id": "settings",
        "title": "Settings",
        "accent": "#FF7A5C",
        "bg": "#121214",
        "panel": "#1C1C20",
        "data": "#28282E",
        "edge": "#3A3A42",
        "text": "#FAFAFC",
        "muted": "#B0B0B8",
        "up": "#6EFFB0",
        "down": "#FF8A9A",
        "warn": "#FFC14D",
        "on_btn": "#180808",
    },
]

# Performance range chips — phone default is 1W
RANGE_CHIPS: list[tuple[str, str]] = [
    ("all", "All"),
    ("1w", "1W"),
    ("1m", "1M"),
    ("3m", "3M"),
    ("6m", "6M"),
    ("1y", "1Y"),
]

ORDER_SORT_FIELDS: list[tuple[str, str]] = [
    ("placed", "Placed"),
    ("symbol", "Symbol"),
    ("status", "Status"),
    ("action", "Action"),
    ("value", "Value"),
    ("qty", "Qty"),
    ("price", "Price"),
]


def _log(msg: str) -> None:
    UNIFIED_LOG.parent.mkdir(parents=True, exist_ok=True)
    with UNIFIED_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")


def _apply_identity() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(UNIFIED_APP_ID)
    except Exception:
        pass


def _focus_existing_trader() -> None:
    """Bring an already-running trader window forward (no new instance)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        SW_RESTORE = 9
        found = wintypes.HWND(0)

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def _enum(hwnd: int, _lparam: int) -> bool:
            nonlocal found
            if not user32.IsWindowVisible(hwnd):
                return True
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            title = buf.value or ""
            if title == UNIFIED_WINDOW_TITLE or title.startswith(UNIFIED_WINDOW_TITLE + " "):
                found = wintypes.HWND(hwnd)
                return False
            return True

        user32.EnumWindows(_enum, 0)
        if not found:
            return
        if user32.IsIconic(found):
            user32.ShowWindow(found, SW_RESTORE)
        user32.SetForegroundWindow(found)
        user32.BringWindowToTop(found)
    except Exception as exc:
        _log(f"focus existing trader failed: {exc}")


def _acquire_single_instance() -> bool:
    """Return False if another Unified Trader GUI already holds the mutex."""
    global _single_instance_mutex
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        ERROR_ALREADY_EXISTS = 183
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, UNIFIED_MUTEX_NAME)
        if not handle:
            return True
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            _focus_existing_trader()
            _log("Another E*TRADE Trader instance is already running - exiting duplicate")
            return False
        _single_instance_mutex = int(handle)
        return True
    except Exception as exc:
        _log(f"single-instance mutex note: {exc}")
        return True


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _set_worker_flag(path: Path, **flags: Any) -> None:
    raw = _read_json(path)
    worker = dict(raw.get("background_worker") or {})
    worker.update(flags)
    if flags.get("dry_run"):
        worker["live_trading"] = False
    elif "dry_run" in flags and not flags["dry_run"] and worker.get("auto_execute"):
        worker["live_trading"] = True
    raw["background_worker"] = worker
    _write_json(path, raw)


def _money(v: Any) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    sign = "-" if n < 0 else ""
    return f"{sign}${abs(n):,.2f}"


def _pct(v: Any) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return ""
    return f"{n:+.2f}%"


def _pl_color(v: Any, scheme: dict[str, str], neutral: str | None = None) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return neutral or scheme["text"]
    if n > 0:
        return scheme["up"]
    if n < 0:
        return scheme["down"]
    return neutral or scheme["text"]


def _parse_at_ms(at: str) -> float | None:
    text = str(at or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp() * 1000.0
    except ValueError:
        return None


class UnifiedTraderApp:
    def __init__(self) -> None:
        load_palette_from_prefs()
        sync_module_globals(sys.modules[__name__])

        # Default chrome = phone Dashboard scheme
        self._scheme = dict(PHONE_WINDOWS[0])
        self._selected_range = "1w"
        self._order_sort = "placed"
        self._order_sort_asc = False
        self._last_dash: dict[str, Any] = {}
        self._last_orders: list[dict[str, Any]] = []
        self._last_agents: list[dict[str, Any]] = []

        self._window = tk.Tk()
        self._window.title(UNIFIED_WINDOW_TITLE)
        self._window.configure(bg=self._scheme["bg"])
        self._m = ScreenMetrics(self._window, window_profile="trader")
        layout = load_ui_layout("etrade_unified")
        geo = str(layout.get("geometry") or "").strip()
        if geo and "x" in geo:
            self._window.geometry(geo)
        else:
            w = max(self._m.win_w, min(self._m.screen_w - 40, 1280))
            h = max(self._m.win_h, min(self._m.screen_h - 80, 860))
            self._window.geometry(f"{w}x{h}")
        self._window.minsize(self._m.px(980), self._m.px(680))

        try:
            icon = ROOT / "etrade_short_trader.ico"
            if not icon.exists():
                icon = ICON_FILE
            if icon.exists():
                self._window.iconbitmap(str(icon))
        except tk.TclError:
            pass

        self._long_app = None
        self._short_app = None
        self._sleeves_built = False
        self._refresh_after: str | None = None
        self._range_btns: dict[str, tk.Button] = {}
        self._sort_btns: dict[str, tk.Button] = {}
        self._scheme_widgets: list[tuple[tk.Misc, str, str]] = []  # (widget, attr, key)

        self._long_dry = tk.BooleanVar(value=True)
        self._short_dry = tk.BooleanVar(value=True)
        self._sandbox = tk.BooleanVar(value=True)
        self._dry_both = tk.BooleanVar(value=False)

        self._build()
        self._window.protocol("WM_DELETE_WINDOW", self._on_close)
        self._window.after(80, self._refresh_all)
        self._window.after(200, self._lazy_build_sleeves)
        self._window.bind("<Configure>", self._on_configure, add="+")
        self._window.bind("<F5>", lambda _e: self._refresh_all(force=True))

    # ================================================================ layout
    def _build(self) -> None:
        style = ttk.Style(self._window)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        self._style = style
        self._apply_notebook_style()
        configure_treeview_style(style, self._m, prefix="Unified")

        s = self._scheme
        pad = self._m.px(12)

        # ---- top chrome (phone: title · page · banner) ----
        chrome = tk.Frame(self._window, bg=s["bg"])
        chrome.pack(fill=tk.X, padx=pad, pady=(self._m.px(10), self._m.px(4)))
        self._chrome = chrome

        head = tk.Frame(chrome, bg=s["bg"])
        head.pack(fill=tk.X)
        title_col = tk.Frame(head, bg=s["bg"])
        title_col.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._app_title = tk.Label(
            title_col,
            text="E*TRADE Trader",
            bg=s["bg"],
            fg=s["accent"],
            font=self._m.font(16, "bold"),
            anchor="w",
        )
        self._app_title.pack(fill=tk.X)
        self._page_indicator = tk.Label(
            head,
            text="Dashboard  ·  1/5",
            bg=s["bg"],
            fg=s["text"],
            font=self._m.font(11, "bold"),
            anchor="e",
        )
        self._page_indicator.pack(side=tk.RIGHT)

        self._banner = tk.Label(
            chrome,
            text="Loading…",
            bg=s["panel"],
            fg=s["text"],
            font=self._m.font(10),
            anchor="w",
            padx=self._m.px(12),
            pady=self._m.px(8),
            highlightbackground=s["edge"],
            highlightthickness=1,
        )
        self._banner.pack(fill=tk.X, pady=(self._m.px(8), self._m.px(4)))

        # Action row under banner
        actions = tk.Frame(chrome, bg=s["bg"])
        actions.pack(fill=tk.X, pady=(0, self._m.px(2)))
        self._actions = actions
        self._btn_refresh = self._chrome_btn(actions, "Refresh  F5", self._on_refresh_click, side=tk.RIGHT)
        self._btn_stop_all = tk.Button(
            actions,
            text="Stop all",
            command=self._toggle_stop_all,
            bg=s["down"],
            fg="#fff",
            relief=tk.FLAT,
            font=self._m.font(9, "bold"),
            padx=12,
            pady=5,
            cursor="hand2",
            bd=0,
            activebackground="#cc4040",
            activeforeground="#fff",
        )
        self._btn_stop_all.pack(side=tk.RIGHT, padx=(0, 8))
        self._mode_pills = tk.Frame(actions, bg=s["bg"])
        self._mode_pills.pack(side=tk.LEFT)
        self._pill_long = self._pill(self._mode_pills, "Long: …", s["up"])
        self._pill_short = self._pill(self._mode_pills, "Short: …", s["down"])
        self._pill_env = self._pill(self._mode_pills, "…", s["muted"])

        # ---- main notebook (phone windows) ----
        self._nb = ttk.Notebook(self._window, style="Trader.TNotebook")
        self._nb.pack(fill=tk.BOTH, expand=True, padx=pad, pady=(0, self._m.px(4)))

        self._tab_dash = tk.Frame(self._nb, bg=s["bg"])
        self._tab_pos = tk.Frame(self._nb, bg=s["bg"])
        self._tab_ord = tk.Frame(self._nb, bg=s["bg"])
        self._tab_agents = tk.Frame(self._nb, bg=s["bg"])
        self._tab_settings = tk.Frame(self._nb, bg=s["bg"])
        self._nb.add(self._tab_dash, text="  Dashboard  ")
        self._nb.add(self._tab_pos, text="  Positions  ")
        self._nb.add(self._tab_ord, text="  Orders  ")
        self._nb.add(self._tab_agents, text="  Agents  ")
        self._nb.add(self._tab_settings, text="  Settings  ")
        self._nb.bind("<<NotebookTabChanged>>", self._on_tab)

        self._build_dashboard()
        self._build_positions()
        self._build_orders()
        self._build_agents()
        self._build_settings()

        # ---- footer ----
        foot = tk.Frame(self._window, bg=s["panel"], highlightbackground=s["edge"], highlightthickness=1)
        foot.pack(fill=tk.X, side=tk.BOTTOM)
        self._footer = foot
        self._status = tk.Label(
            foot,
            text="Loading…",
            bg=s["panel"],
            fg=s["muted"],
            font=self._m.font(9),
            anchor="w",
        )
        self._status.pack(fill=tk.X, padx=pad, pady=self._m.px(6))

    def _apply_notebook_style(self) -> None:
        s = self._scheme
        style = self._style
        metrics = self._m
        tab_pad = (metrics.px(16), metrics.px(9))
        style.configure("Trader.TNotebook", background=s["bg"], borderwidth=0, tabmargins=(2, 4, 2, 0))
        style.configure(
            "Trader.TNotebook.Tab",
            background=s["panel"],
            foreground=s["muted"],
            padding=tab_pad,
            font=metrics.font(11, "bold"),
        )
        style.map(
            "Trader.TNotebook.Tab",
            background=[("selected", s["data"])],
            foreground=[("selected", s["accent"])],
        )
        style.configure(
            "Unified.Treeview",
            background=s["data"],
            fieldbackground=s["data"],
            foreground=s["text"],
            rowheight=metrics.px(40),
            font=metrics.font(11),
        )
        style.configure(
            "Unified.Treeview.Heading",
            background=s["panel"],
            foreground=s["text"],
            font=metrics.font(10, "bold"),
            padding=(metrics.px(8), metrics.px(6)),
        )
        style.map(
            "Unified.Treeview",
            background=[("selected", s["accent"])],
            foreground=[("selected", s["on_btn"])],
        )

    def _chrome_btn(self, parent: tk.Misc, text: str, cmd: Callable[[], None], *, side: str = tk.LEFT) -> tk.Button:
        s = self._scheme
        btn = tk.Button(
            parent,
            text=text,
            command=cmd,
            bg=s["panel"],
            fg=s["text"],
            relief=tk.FLAT,
            font=self._m.font(9, "bold"),
            padx=10,
            pady=5,
            cursor="hand2",
            bd=0,
            highlightthickness=1,
            highlightbackground=s["edge"],
            activebackground=s["data"],
            activeforeground=s["text"],
        )
        btn.pack(side=side, padx=(8, 0) if side == tk.RIGHT else (0, 8))
        return btn

    def _pill(self, parent: tk.Misc, text: str, color: str) -> tk.Label:
        s = self._scheme
        lbl = tk.Label(
            parent,
            text=f"  {text}  ",
            bg=s["data"],
            fg=color,
            font=self._m.font(9, "bold"),
            highlightbackground=s["edge"],
            highlightthickness=1,
            padx=4,
            pady=3,
        )
        lbl.pack(side=tk.LEFT, padx=(0, 8))
        return lbl

    def _card(self, parent: tk.Misc, **pack_kw: Any) -> tk.Frame:
        s = self._scheme
        card = tk.Frame(
            parent,
            bg=s["data"],
            highlightbackground=s["edge"],
            highlightthickness=1,
        )
        if pack_kw:
            card.pack(**pack_kw)
        return card

    def _section_title(self, parent: tk.Misc, text: str) -> tk.Label:
        s = self._scheme
        lbl = tk.Label(
            parent,
            text=text,
            bg=s["bg"],
            fg=s["accent"],
            font=self._m.font(16, "bold"),
            anchor="w",
        )
        lbl.pack(fill=tk.X, pady=(0, self._m.px(6)))
        return lbl

    # ============================================================ dashboard
    def _build_dashboard(self) -> None:
        s = self._scheme
        root = self._tab_dash
        pad = self._m.px(10)

        outer = tk.Frame(root, bg=s["bg"])
        outer.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad)
        self._dash_root = outer

        row = tk.Frame(outer, bg=s["bg"])
        row.pack(fill=tk.X)
        self._dash_title = tk.Label(
            row, text="Dashboard", bg=s["bg"], fg=s["accent"], font=self._m.font(16, "bold"), anchor="w"
        )
        self._dash_title.pack(side=tk.LEFT, fill=tk.X, expand=True)

        tk.Label(
            outer,
            text="ACCOUNT",
            bg=s["bg"],
            fg=s["muted"],
            font=self._m.font(9, "bold"),
            anchor="w",
        ).pack(fill=tk.X, pady=(self._m.px(4), 0))
        self._acct_label = tk.Label(
            outer,
            text="—",
            bg=s["bg"],
            fg=s["text"],
            font=self._m.font(11),
            anchor="w",
        )
        self._acct_label.pack(fill=tk.X)

        # Balance card
        bal = self._card(outer, fill=tk.X, pady=(self._m.px(10), self._m.px(6)))
        bi = tk.Frame(bal, bg=s["data"])
        bi.pack(fill=tk.X, padx=self._m.px(16), pady=self._m.px(14))
        tk.Label(bi, text="BALANCE", bg=s["data"], fg=s["muted"], font=self._m.font(9, "bold"), anchor="w").pack(
            fill=tk.X
        )
        self._bal_value = tk.Label(
            bi, text="—", bg=s["data"], fg=s["text"], font=self._m.font(26, "bold"), anchor="w"
        )
        self._bal_value.pack(fill=tk.X, pady=(6, 0))
        self._cash_line = tk.Label(
            bi, text="", bg=s["data"], fg=s["muted"], font=self._m.font(10), anchor="w", wraplength=900, justify=tk.LEFT
        )
        self._cash_line.pack(fill=tk.X, pady=(4, 0))

        # Day P/L + Total P/L
        pl_row = tk.Frame(outer, bg=s["bg"])
        pl_row.pack(fill=tk.X, pady=(0, self._m.px(6)))
        pl_row.columnconfigure((0, 1), weight=1, uniform="pl")

        day_card = tk.Frame(pl_row, bg=s["data"], highlightbackground=s["edge"], highlightthickness=1)
        day_card.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        di = tk.Frame(day_card, bg=s["data"])
        di.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        head_d = tk.Frame(di, bg=s["data"])
        head_d.pack(fill=tk.X)
        self._day_pl_label = tk.Label(
            head_d, text="TODAY", bg=s["data"], fg=s["muted"], font=self._m.font(8, "bold"), anchor="w"
        )
        self._day_pl_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._day_avg_label = tk.Label(
            head_d, text="AVG 1W", bg=s["data"], fg=s["muted"], font=self._m.font(8, "bold"), anchor="e"
        )
        self._day_avg_label.pack(side=tk.RIGHT, fill=tk.X, expand=True)
        vals_d = tk.Frame(di, bg=s["data"])
        vals_d.pack(fill=tk.X, pady=(6, 0))
        self._day_pl_value = tk.Label(
            vals_d, text="—", bg=s["data"], fg=s["text"], font=self._m.font(14, "bold"), anchor="w"
        )
        self._day_pl_value.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._day_avg_value = tk.Label(
            vals_d, text="—", bg=s["data"], fg=s["text"], font=self._m.font(14, "bold"), anchor="e"
        )
        self._day_avg_value.pack(side=tk.RIGHT, fill=tk.X, expand=True)
        pcts_d = tk.Frame(di, bg=s["data"])
        pcts_d.pack(fill=tk.X, pady=(2, 0))
        self._day_pl_pct = tk.Label(pcts_d, text="", bg=s["data"], fg=s["muted"], font=self._m.font(10), anchor="w")
        self._day_pl_pct.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._day_avg_pct = tk.Label(pcts_d, text="", bg=s["data"], fg=s["muted"], font=self._m.font(10), anchor="e")
        self._day_avg_pct.pack(side=tk.RIGHT, fill=tk.X, expand=True)

        tot_card = tk.Frame(pl_row, bg=s["data"], highlightbackground=s["edge"], highlightthickness=1)
        tot_card.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        ti = tk.Frame(tot_card, bg=s["data"])
        ti.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        self._total_pl_label = tk.Label(
            ti, text="TOTAL P/L", bg=s["data"], fg=s["muted"], font=self._m.font(8, "bold"), anchor="w"
        )
        self._total_pl_label.pack(fill=tk.X)
        self._total_pl_value = tk.Label(
            ti, text="—", bg=s["data"], fg=s["text"], font=self._m.font(14, "bold"), anchor="w"
        )
        self._total_pl_value.pack(fill=tk.X, pady=(6, 0))
        self._total_pl_pct = tk.Label(ti, text="", bg=s["data"], fg=s["muted"], font=self._m.font(10), anchor="w")
        self._total_pl_pct.pack(fill=tk.X, pady=(2, 0))

        # Range chips
        chips = tk.Frame(outer, bg=s["bg"])
        chips.pack(fill=tk.X, pady=(self._m.px(4), self._m.px(4)))
        for key, label in RANGE_CHIPS:
            btn = tk.Button(
                chips,
                text=f"  {label}  ",
                command=lambda k=key: self._set_range(k),
                bg=s["panel"],
                fg=s["text"],
                relief=tk.FLAT,
                font=self._m.font(9, "bold"),
                bd=0,
                cursor="hand2",
                padx=6,
                pady=4,
                highlightthickness=1,
                highlightbackground=s["edge"],
            )
            btn.pack(side=tk.LEFT, padx=(0, 6))
            self._range_btns[key] = btn
        self._sync_range_chips()

        # Chart
        chart_card = self._card(outer, fill=tk.BOTH, expand=True, pady=(0, 0))
        self._chart_canvas = tk.Canvas(
            chart_card,
            bg=s["data"],
            highlightthickness=0,
            height=self._m.px(220),
        )
        self._chart_canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self._chart_canvas.bind("<Configure>", lambda _e: self._draw_chart())
        self._chart_hint = tk.Label(
            chart_card,
            text="Performance (deposit-excluded P/L)",
            bg=s["data"],
            fg=s["muted"],
            font=self._m.font(8),
        )
        self._chart_hint.place(relx=0.02, rely=0.02)

    def _set_range(self, key: str) -> None:
        self._selected_range = key
        self._sync_range_chips()
        self._apply_range_metrics()
        self._draw_chart()

    def _sync_range_chips(self) -> None:
        s = self._scheme
        for key, btn in self._range_btns.items():
            selected = key == self._selected_range
            btn.configure(
                bg=s["accent"] if selected else s["panel"],
                fg=s["on_btn"] if selected else s["text"],
                highlightbackground=s["accent"] if selected else s["edge"],
            )

    # ============================================================ positions
    def _build_positions(self) -> None:
        s = self._scheme
        root = self._tab_pos
        pad = self._m.px(10)
        outer = tk.Frame(root, bg=s["bg"])
        outer.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad)
        self._pos_root = outer

        row = tk.Frame(outer, bg=s["bg"])
        row.pack(fill=tk.X)
        self._pos_title = tk.Label(
            row, text="Positions", bg=s["bg"], fg=s["accent"], font=self._m.font(16, "bold"), anchor="w"
        )
        self._pos_title.pack(side=tk.LEFT, fill=tk.X, expand=True)

        summary = self._card(outer, fill=tk.X, pady=(self._m.px(8), self._m.px(8)))
        si = tk.Frame(summary, bg=s["data"])
        si.pack(fill=tk.X, padx=14, pady=12)
        si.columnconfigure((0, 1), weight=1)
        tk.Label(si, text="Portfolio value", bg=s["data"], fg=s["muted"], font=self._m.font(9), anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(si, text="Open P/L", bg=s["data"], fg=s["muted"], font=self._m.font(9), anchor="w").grid(
            row=0, column=1, sticky="w"
        )
        self._port_mv = tk.Label(
            si, text="—", bg=s["data"], fg=s["text"], font=self._m.font(14, "bold"), anchor="w"
        )
        self._port_mv.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._port_pl = tk.Label(
            si, text="—", bg=s["data"], fg=s["text"], font=self._m.font(14, "bold"), anchor="w"
        )
        self._port_pl.grid(row=1, column=1, sticky="w", pady=(4, 0))

        cols = ("symbol", "side", "value", "price", "pl", "qty")
        tree_wrap = tk.Frame(outer, bg=s["bg"])
        tree_wrap.pack(fill=tk.BOTH, expand=True)
        self._pos_tree = ttk.Treeview(tree_wrap, columns=cols, show="headings", style="Unified.Treeview")
        headings = {
            "symbol": ("Symbol", 90),
            "side": ("Side", 80),
            "value": ("Value", 110),
            "price": ("Price", 100),
            "pl": ("P/L", 110),
            "qty": ("Qty", 70),
        }
        for c, (title, w) in headings.items():
            self._pos_tree.heading(c, text=title)
            self._pos_tree.column(c, width=w, anchor="w" if c in ("symbol", "side") else "e")
        ysb = ttk.Scrollbar(tree_wrap, orient=tk.VERTICAL, command=self._pos_tree.yview)
        self._pos_tree.configure(yscrollcommand=ysb.set)
        self._pos_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        self._pos_empty = tk.Label(
            outer, text="", bg=s["bg"], fg=s["muted"], font=self._m.font(10), anchor="w"
        )
        self._pos_empty.pack(fill=tk.X, pady=(4, 0))

    # ============================================================ orders
    def _build_orders(self) -> None:
        s = self._scheme
        root = self._tab_ord
        pad = self._m.px(10)
        outer = tk.Frame(root, bg=s["bg"])
        outer.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad)
        self._ord_root = outer

        row = tk.Frame(outer, bg=s["bg"])
        row.pack(fill=tk.X)
        self._ord_title = tk.Label(
            row, text="Orders", bg=s["bg"], fg=s["accent"], font=self._m.font(16, "bold"), anchor="w"
        )
        self._ord_title.pack(side=tk.LEFT, fill=tk.X, expand=True)

        summary = self._card(outer, fill=tk.X, pady=(self._m.px(8), self._m.px(6)))
        si = tk.Frame(summary, bg=s["data"])
        si.pack(fill=tk.X, padx=14, pady=12)
        si.columnconfigure((0, 1), weight=1)
        tk.Label(si, text="Open", bg=s["data"], fg=s["muted"], font=self._m.font(9), anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(si, text="Notional", bg=s["data"], fg=s["muted"], font=self._m.font(9), anchor="w").grid(
            row=0, column=1, sticky="w"
        )
        self._ord_open = tk.Label(
            si, text="—", bg=s["data"], fg=s["text"], font=self._m.font(14, "bold"), anchor="w"
        )
        self._ord_open.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._ord_notional = tk.Label(
            si, text="—", bg=s["data"], fg=s["text"], font=self._m.font(14, "bold"), anchor="w"
        )
        self._ord_notional.grid(row=1, column=1, sticky="w", pady=(4, 0))

        # Compact sort bar (phone: chips + Asc/Desc, no title/help)
        sort_bar = tk.Frame(outer, bg=s["panel"], highlightbackground=s["edge"], highlightthickness=1)
        sort_bar.pack(fill=tk.X, pady=(0, self._m.px(6)))
        self._sort_bar = sort_bar
        inner = tk.Frame(sort_bar, bg=s["panel"])
        inner.pack(fill=tk.X, padx=6, pady=4)
        for key, label in ORDER_SORT_FIELDS:
            btn = tk.Button(
                inner,
                text=f" {label} ",
                command=lambda k=key: self._set_order_sort(k),
                bg=s["data"],
                fg=s["text"],
                relief=tk.FLAT,
                font=self._m.font(8, "bold"),
                bd=0,
                cursor="hand2",
                padx=4,
                pady=2,
            )
            btn.pack(side=tk.LEFT, padx=(0, 4))
            self._sort_btns[key] = btn
        self._sort_dir_btn = tk.Button(
            inner,
            text=" Desc ",
            command=self._toggle_order_sort_dir,
            bg=s["accent"],
            fg=s["on_btn"],
            relief=tk.FLAT,
            font=self._m.font(8, "bold"),
            bd=0,
            cursor="hand2",
            padx=6,
            pady=2,
        )
        self._sort_dir_btn.pack(side=tk.RIGHT)
        self._sync_sort_chips()

        cols = ("symbol", "action", "value", "pl", "status", "qty", "price")
        tree_wrap = tk.Frame(outer, bg=s["bg"])
        tree_wrap.pack(fill=tk.BOTH, expand=True)
        self._ord_tree = ttk.Treeview(tree_wrap, columns=cols, show="headings", style="Unified.Treeview")
        headings = {
            "symbol": ("Symbol", 90),
            "action": ("Action", 70),
            "value": ("Value", 100),
            "pl": ("P/L", 90),
            "status": ("Status", 90),
            "qty": ("Qty", 60),
            "price": ("Price", 90),
        }
        for c, (title, w) in headings.items():
            self._ord_tree.heading(c, text=title)
            self._ord_tree.column(c, width=w, anchor="w" if c in ("symbol", "action", "status") else "e")
        ysb = ttk.Scrollbar(tree_wrap, orient=tk.VERTICAL, command=self._ord_tree.yview)
        self._ord_tree.configure(yscrollcommand=ysb.set)
        self._ord_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        self._ord_empty = tk.Label(outer, text="", bg=s["bg"], fg=s["muted"], font=self._m.font(10), anchor="w")
        self._ord_empty.pack(fill=tk.X, pady=(4, 0))

    def _set_order_sort(self, key: str) -> None:
        if self._order_sort == key:
            self._order_sort_asc = not self._order_sort_asc
        else:
            self._order_sort = key
            self._order_sort_asc = key in ("symbol", "status", "action")
        self._sync_sort_chips()
        self._fill_orders(self._last_orders)

    def _toggle_order_sort_dir(self) -> None:
        self._order_sort_asc = not self._order_sort_asc
        self._sync_sort_chips()
        self._fill_orders(self._last_orders)

    def _sync_sort_chips(self) -> None:
        s = self._scheme
        for key, btn in self._sort_btns.items():
            selected = key == self._order_sort
            btn.configure(
                bg=s["accent"] if selected else s["data"],
                fg=s["on_btn"] if selected else s["text"],
            )
        self._sort_dir_btn.configure(text=f" {'Asc' if self._order_sort_asc else 'Desc'} ")

    # ============================================================ agents
    def _build_agents(self) -> None:
        s = self._scheme
        root = self._tab_agents
        pad = self._m.px(10)
        outer = tk.Frame(root, bg=s["bg"])
        outer.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad)
        self._agents_root = outer

        row = tk.Frame(outer, bg=s["bg"])
        row.pack(fill=tk.X)
        self._agents_title = tk.Label(
            row, text="Agents", bg=s["bg"], fg=s["accent"], font=self._m.font(16, "bold"), anchor="w"
        )
        self._agents_title.pack(side=tk.LEFT, fill=tk.X, expand=True)

        summary = self._card(outer, fill=tk.X, pady=(self._m.px(8), self._m.px(8)))
        si = tk.Frame(summary, bg=s["data"])
        si.pack(fill=tk.X, padx=14, pady=12)
        tk.Label(si, text="Agents", bg=s["data"], fg=s["muted"], font=self._m.font(9), anchor="w").pack(fill=tk.X)
        self._agents_count = tk.Label(
            si, text="—", bg=s["data"], fg=s["text"], font=self._m.font(14, "bold"), anchor="w"
        )
        self._agents_count.pack(fill=tk.X, pady=(4, 0))
        self._agents_meta = tk.Label(
            si, text="", bg=s["data"], fg=s["muted"], font=self._m.font(9), anchor="w", wraplength=900, justify=tk.LEFT
        )
        self._agents_meta.pack(fill=tk.X, pady=(4, 0))

        cols = ("name", "group", "role", "signal", "updated")
        tree_wrap = tk.Frame(outer, bg=s["bg"])
        tree_wrap.pack(fill=tk.BOTH, expand=True)
        self._agents_tree = ttk.Treeview(tree_wrap, columns=cols, show="headings", style="Unified.Treeview")
        for c, (title, w) in {
            "name": ("Agent", 160),
            "group": ("Group", 120),
            "role": ("Role", 100),
            "signal": ("Signal", 100),
            "updated": ("Updated", 140),
        }.items():
            self._agents_tree.heading(c, text=title)
            self._agents_tree.column(c, width=w, anchor="w")
        ysb = ttk.Scrollbar(tree_wrap, orient=tk.VERTICAL, command=self._agents_tree.yview)
        self._agents_tree.configure(yscrollcommand=ysb.set)
        self._agents_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        self._agents_empty = tk.Label(outer, text="", bg=s["bg"], fg=s["muted"], font=self._m.font(10), anchor="w")
        self._agents_empty.pack(fill=tk.X, pady=(4, 0))

    # ============================================================ settings
    def _build_settings(self) -> None:
        s = self._scheme
        root = self._tab_settings
        pad = self._m.px(10)

        # Nested notebook: Modes (phone) + Advanced long/short tools (PC-only)
        self._settings_nb = ttk.Notebook(root, style="Trader.TNotebook")
        self._settings_nb.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad)

        self._tab_modes = tk.Frame(self._settings_nb, bg=s["bg"])
        self._tab_adv_long = tk.Frame(self._settings_nb, bg=s["bg"])
        self._tab_adv_short = tk.Frame(self._settings_nb, bg=s["bg"])
        self._settings_nb.add(self._tab_modes, text="  Trade modes  ")
        self._settings_nb.add(self._tab_adv_long, text="  Long tools  ")
        self._settings_nb.add(self._tab_adv_short, text="  Short tools  ")

        outer = tk.Frame(self._tab_modes, bg=s["bg"])
        outer.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad)

        self._settings_title = tk.Label(
            outer, text="Settings", bg=s["bg"], fg=s["accent"], font=self._m.font(16, "bold"), anchor="w"
        )
        self._settings_title.pack(fill=tk.X)

        modes = self._card(outer, fill=tk.X, pady=(self._m.px(10), self._m.px(8)))
        mi = tk.Frame(modes, bg=s["data"])
        mi.pack(fill=tk.X, padx=14, pady=14)
        tk.Label(
            mi, text="Trade modes", bg=s["data"], fg=s["text"], font=self._m.font(12, "bold"), anchor="w"
        ).pack(fill=tk.X)
        tk.Label(
            mi,
            text="Shared API environment · independent practice per sleeve (same as phone).",
            bg=s["data"],
            fg=s["muted"],
            font=self._m.font(9),
            anchor="w",
            wraplength=800,
            justify=tk.LEFT,
        ).pack(fill=tk.X, pady=(4, 8))
        self._modes_status = tk.Label(
            mi, text="", bg=s["data"], fg=s["muted"], font=self._m.font(9), anchor="w"
        )
        self._modes_status.pack(fill=tk.X, pady=(0, 8))

        cb_kw = dict(
            bg=s["data"],
            fg=s["text"],
            selectcolor=s["panel"],
            activebackground=s["data"],
            activeforeground=s["text"],
            font=self._m.font(10),
            anchor="w",
        )
        tk.Checkbutton(
            mi, text="Sandbox (practice API)", variable=self._sandbox, command=self._on_sandbox_toggle, **cb_kw
        ).pack(fill=tk.X)
        tk.Checkbutton(
            mi,
            text="Practice long (dry-run — no real buys)",
            variable=self._long_dry,
            command=self._save_long_practice,
            **cb_kw,
        ).pack(fill=tk.X)
        tk.Checkbutton(
            mi,
            text="Practice short (dry-run — no real shorts)",
            variable=self._short_dry,
            command=self._save_short_practice,
            **cb_kw,
        ).pack(fill=tk.X)
        tk.Checkbutton(
            mi,
            text="Dry-run both sleeves",
            variable=self._dry_both,
            command=self._save_both_practice,
            **cb_kw,
        ).pack(fill=tk.X)

        btn_row = tk.Frame(mi, bg=s["data"])
        btn_row.pack(fill=tk.X, pady=(12, 0))
        tk.Button(
            btn_row,
            text="Apply modes",
            command=self._apply_modes,
            bg=s["accent"],
            fg=s["on_btn"],
            relief=tk.FLAT,
            font=self._m.font(10, "bold"),
            padx=14,
            pady=8,
            cursor="hand2",
            bd=0,
        ).pack(side=tk.LEFT)

        note = self._card(outer, fill=tk.X, pady=(0, 0))
        ni = tk.Frame(note, bg=s["data"])
        ni.pack(fill=tk.X, padx=14, pady=12)
        tk.Label(
            ni,
            text="Advanced tools",
            bg=s["data"],
            fg=s["text"],
            font=self._m.font(11, "bold"),
            anchor="w",
        ).pack(fill=tk.X)
        tk.Label(
            ni,
            text="Use the Long tools / Short tools tabs above for connect, OAuth, agents pipeline controls, "
            "and day-trading panels. Main windows match the phone app.",
            bg=s["data"],
            fg=s["muted"],
            font=self._m.font(9),
            anchor="w",
            wraplength=800,
            justify=tk.LEFT,
        ).pack(fill=tk.X, pady=(4, 0))

        self._placeholder(self._tab_adv_long, "Long tools loading…")
        self._placeholder(self._tab_adv_short, "Short tools loading…")

    def _placeholder(self, parent: tk.Misc, msg: str) -> None:
        s = self._scheme
        f = tk.Frame(parent, bg=s["bg"])
        f.pack(fill=tk.BOTH, expand=True)
        tk.Label(f, text=msg, bg=s["bg"], fg=s["muted"], font=self._m.font(11)).place(
            relx=0.5, rely=0.45, anchor="center"
        )
        parent._ph = f  # type: ignore[attr-defined]

    def _clear_ph(self, parent: tk.Misc) -> None:
        ph = getattr(parent, "_ph", None)
        if ph is not None:
            try:
                ph.destroy()
            except tk.TclError:
                pass
            parent._ph = None  # type: ignore[attr-defined]

    # ============================================================== chrome
    def _window_index(self) -> int:
        try:
            sel = str(self._nb.select())
        except tk.TclError:
            return 0
        tabs = [self._tab_dash, self._tab_pos, self._tab_ord, self._tab_agents, self._tab_settings]
        for i, t in enumerate(tabs):
            if sel == str(t):
                return i
        return 0

    def _apply_window_chrome(self, index: int | None = None) -> None:
        idx = self._window_index() if index is None else index
        scheme = PHONE_WINDOWS[idx]
        self._scheme = dict(scheme)
        s = self._scheme
        self._window.configure(bg=s["bg"])
        for w in (self._chrome, self._actions, self._mode_pills):
            try:
                w.configure(bg=s["bg"])
            except tk.TclError:
                pass
        self._app_title.configure(bg=s["bg"], fg=s["accent"])
        self._page_indicator.configure(
            bg=s["bg"],
            fg=s["text"],
            text=f"{s['title']}  ·  {idx + 1}/{len(PHONE_WINDOWS)}",
        )
        self._banner.configure(bg=s["panel"], fg=s["text"], highlightbackground=s["edge"])
        self._footer.configure(bg=s["panel"], highlightbackground=s["edge"])
        self._status.configure(bg=s["panel"], fg=s["muted"])
        for tab in (self._tab_dash, self._tab_pos, self._tab_ord, self._tab_agents, self._tab_settings):
            try:
                tab.configure(bg=s["bg"])
            except tk.TclError:
                pass
        self._btn_refresh.configure(
            bg=s["panel"], fg=s["text"], highlightbackground=s["edge"], activebackground=s["data"]
        )
        self._apply_notebook_style()
        self._sync_range_chips()
        self._sync_sort_chips()
        # Title accents per page
        for attr in ("_dash_title", "_pos_title", "_ord_title", "_agents_title", "_settings_title"):
            lbl = getattr(self, attr, None)
            if lbl is not None:
                try:
                    lbl.configure(fg=s["accent"])
                except tk.TclError:
                    pass

    def _on_tab(self, _e: tk.Event | None = None) -> None:
        self._apply_window_chrome()
        idx = self._window_index()
        if idx == 0:
            self._apply_dashboard_view()
        elif idx == 1:
            self._apply_positions_view()
        elif idx == 2:
            self._apply_orders_view()
        elif idx == 3:
            self._apply_agents_view()

    def _on_refresh_click(self) -> None:
        self._refresh_all(force=True)

    # ============================================================== data
    def _load_phone_dashboard_cache(self) -> dict[str, Any]:
        """Last published phone dashboard (Oxygen-OS bus) when PC live pack is empty."""
        paths = [
            Path.home() / "Documents" / "GitHub" / "Oxygen-OS" / "work" / "phone" / "etrade-dashboard.json",
            ROOT.parent / "Oxygen-OS" / "work" / "phone" / "etrade-dashboard.json",
        ]
        for path in paths:
            data = _read_json(path)
            if data.get("account") or data.get("positions"):
                data.setdefault("status_line", "Loaded from phone dashboard cache")
                return data
        return {}

    def _refresh_all(self, force: bool = False) -> None:
        try:
            from phone_bridge import (
                build_agents_for_phone,
                build_dashboard,
                build_orders_for_phone,
            )

            # Desktop refresh: do not publish empty packs over the phone JSON bus.
            # Prefer live PC build; if that has no positions, fall back to last
            # published Oxygen-OS phone dashboard (same file the app loads offline).
            dash = build_dashboard(force_refresh=force, publish=False)
            if not isinstance(dash, dict):
                dash = {}
            if not (dash.get("positions") or []) and not (dash.get("account") or {}).get("balance"):
                cached = self._load_phone_dashboard_cache()
                if cached:
                    dash = cached
            self._last_dash = dash
            orders_pack = build_orders_for_phone()
            self._last_orders = list((orders_pack or {}).get("orders") or [])
            # Prefer orders embedded in full pack / cache when live list empty
            if not self._last_orders and isinstance(dash.get("orders"), list):
                self._last_orders = list(dash.get("orders") or [])
            agents_pack = build_agents_for_phone()
            self._last_agents = list((agents_pack or {}).get("agents") or [])
            self._modes_message = str((agents_pack or {}).get("message") or "")
            self._agents_pack = agents_pack if isinstance(agents_pack, dict) else {}
        except Exception as exc:
            _log(f"refresh failed: {exc}\n{traceback.format_exc()}")
            self._status.configure(text=f"Refresh failed: {exc}", fg=self._scheme["warn"])
            self._schedule_refresh()
            return

        self._sync_mode_vars_from_dash()
        self._update_banner()
        self._apply_window_chrome()
        self._apply_dashboard_view()
        self._apply_positions_view()
        self._apply_orders_view()
        self._apply_agents_view()
        status = str(self._last_dash.get("status_line") or "Ready")
        self._status.configure(text=status, fg=self._scheme["text"])
        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        if self._refresh_after:
            try:
                self._window.after_cancel(self._refresh_after)
            except tk.TclError:
                pass
        try:
            self._refresh_after = self._window.after(30_000, lambda: self._refresh_all(force=False))
        except tk.TclError:
            self._refresh_after = None

    def _sync_mode_vars_from_dash(self) -> None:
        d = self._last_dash
        long_b = d.get("long") or {}
        short_b = d.get("short") or {}
        self._long_dry.set(bool(long_b.get("dry_run", False)))
        self._short_dry.set(bool(short_b.get("dry_run", True)))
        self._dry_both.set(bool(self._long_dry.get()) and bool(self._short_dry.get()))
        env = str(d.get("api_environment") or "").lower()
        self._sandbox.set(env == "sandbox" or "sandbox" in env)
        both_paused = bool(d.get("paused"))
        self._update_stop_all_btn(both_paused)

        lm = str(long_b.get("mode") or "—")
        sm = str(short_b.get("mode") or "—")
        env_disp = str(d.get("api_environment") or "—")
        self._pill_long.configure(text=f"  Long: {lm}  ", fg=self._scheme["up"] if "PRACTICE" not in lm else self._scheme["warn"])
        self._pill_short.configure(
            text=f"  Short: {sm}  ",
            fg=self._scheme["down"] if "LIVE" in sm else self._scheme["warn"],
        )
        self._pill_env.configure(
            text=f"  {env_disp} API  " if not both_paused else "  STOPPED  ",
            fg=self._scheme["warn"] if both_paused else self._scheme["up"],
        )
        if hasattr(self, "_modes_status"):
            self._modes_status.configure(
                text=f"Long {lm} · Short {sm} · {env_disp} · shared API · independent practice"
            )

    def _update_banner(self) -> None:
        d = self._last_dash
        acct = d.get("account") or {}
        name = str(acct.get("account_name") or acct.get("display_label") or "account")
        long_b = d.get("long") or {}
        short_b = d.get("short") or {}
        lm = str(long_b.get("mode") or "—")
        sm = str(short_b.get("mode") or "—")
        env = str(d.get("api_environment") or "")
        modes = f"Shared {env} · L {lm} · S {sm}" if env else f"L {lm} · S {sm}"
        when = ""
        try:
            ts = float(d.get("updated_at") or 0)
            if ts > 0:
                when = f" · {datetime.fromtimestamp(ts):%b %d %I:%M %p}"
        except (TypeError, ValueError, OSError):
            pass
        src = ""
        pull = d.get("data_pull") or {}
        if isinstance(pull, dict) and pull.get("source"):
            src = f" · {pull.get('source')}"
        self._banner.configure(text=f"E*TRADE · {name} · {modes}{when}{src}")

    def _apply_dashboard_view(self) -> None:
        d = self._last_dash
        acct = d.get("account") or {}
        disp = acct.get("display") if isinstance(acct.get("display"), dict) else {}
        self._acct_label.configure(text=str(acct.get("account_name") or "—"))
        bal = disp.get("balance") or _money(acct.get("balance"))
        self._bal_value.configure(text=str(bal))

        cash_bits = [
            f"Cash {disp.get('cash') or _money(acct.get('cash'))}",
        ]
        if acct.get("account_name"):
            cash_bits.append(str(acct.get("account_name")))
        inv = disp.get("invested") or _money(acct.get("invested_capital"))
        if inv and inv != "—":
            cash_bits.append(f"capital {inv}")
        dep = disp.get("deposits") or _money(acct.get("deposits_total"))
        if dep and dep != "—" and str(dep) not in ("$0.00", "—"):
            cash_bits.append(f"deposits {dep} (not P/L)")
        shared = d.get("shared_api") or {}
        metrics = d.get("metrics") or {}
        if metrics.get("api_environment") or d.get("api_environment"):
            cash_bits.append(str(metrics.get("api_environment") or d.get("api_environment")))
        self._cash_line.configure(text="  ·  ".join(cash_bits))
        self._apply_range_metrics()
        self._draw_chart()

    def _range_points(self) -> list[dict[str, Any]]:
        perf = self._last_dash.get("performance") or {}
        ranges = perf.get("ranges") if isinstance(perf.get("ranges"), dict) else {}
        key = self._selected_range
        pts = ranges.get(key) if ranges else None
        if not pts:
            pts = perf.get("points") or []
        return [p for p in pts if isinstance(p, dict)]

    def _apply_range_metrics(self) -> None:
        s = self._scheme
        d = self._last_dash
        acct = d.get("account") or {}
        disp = acct.get("display") if isinstance(acct.get("display"), dict) else {}
        range_label = dict(RANGE_CHIPS).get(self._selected_range, self._selected_range.upper())
        is_full = self._selected_range in ("all", "open")

        # Today
        day_pl = acct.get("day_pl")
        day_pct = acct.get("day_pl_pct")
        self._day_pl_label.configure(text="TODAY")
        self._day_pl_value.configure(text=disp.get("day_pl") or _money(day_pl), fg=_pl_color(day_pl, s))
        self._day_pl_pct.configure(text=disp.get("day_pl_pct") or _pct(day_pct), fg=_pl_color(day_pl, s, s["muted"]))

        # Period / avg from series
        pts = self._range_points()
        period_pl = None
        period_pct = None
        day_count = 1
        if len(pts) >= 2:
            first, last = pts[0], pts[-1]
            fpl, lpl = first.get("profit_amount"), last.get("profit_amount")
            try:
                if fpl is not None and lpl is not None:
                    period_pl = float(lpl) - float(fpl)
            except (TypeError, ValueError):
                period_pl = None
            t0 = _parse_at_ms(str(first.get("at") or ""))
            t1 = _parse_at_ms(str(last.get("at") or ""))
            if t0 and t1 and t1 > t0:
                day_count = max(1, int((t1 - t0) / 86_400_000.0 + 0.999))
            else:
                day_count = max(1, len(pts) - 1)
            inv = acct.get("invested_capital")
            try:
                if period_pl is not None and inv is not None and float(inv) > 0:
                    period_pct = period_pl / float(inv) * 100.0
            except (TypeError, ValueError):
                period_pct = None

        if is_full:
            try:
                period_pl = float(acct.get("total_pl")) if acct.get("total_pl") is not None else period_pl
            except (TypeError, ValueError):
                pass
            try:
                period_pct = float(acct.get("total_pl_pct")) if acct.get("total_pl_pct") is not None else period_pct
            except (TypeError, ValueError):
                pass
            self._total_pl_label.configure(text="TOTAL P/L")
            self._total_pl_value.configure(
                text=disp.get("total_pl") or _money(period_pl),
                fg=_pl_color(period_pl, s),
            )
            self._total_pl_pct.configure(
                text=disp.get("total_pl_pct") or _pct(period_pct),
                fg=_pl_color(period_pl, s, s["muted"]),
            )
        else:
            self._total_pl_label.configure(text=f"{range_label} P/L")
            self._total_pl_value.configure(text=_money(period_pl), fg=_pl_color(period_pl, s))
            self._total_pl_pct.configure(text=_pct(period_pct), fg=_pl_color(period_pl, s, s["muted"]))

        avg = (period_pl / day_count) if period_pl is not None else None
        avg_pct = (period_pct / day_count) if period_pct is not None else None
        self._day_avg_label.configure(text=f"AVG {range_label}")
        self._day_avg_value.configure(text=_money(avg), fg=_pl_color(avg, s))
        extra = f" · {day_count}d" if avg is not None else ""
        self._day_avg_pct.configure(
            text=((_pct(avg_pct) if avg_pct is not None else "") + extra).strip(" ·"),
            fg=_pl_color(avg, s, s["muted"]),
        )

    def _draw_chart(self) -> None:
        canvas = getattr(self, "_chart_canvas", None)
        if canvas is None:
            return
        s = self._scheme
        canvas.delete("all")
        w = max(canvas.winfo_width(), 40)
        h = max(canvas.winfo_height(), 40)
        canvas.configure(bg=s["data"])
        pts = self._range_points()
        values: list[float] = []
        for p in pts:
            v = p.get("profit_amount")
            if v is None:
                v = p.get("value")
            try:
                values.append(float(v))
            except (TypeError, ValueError):
                continue
        if len(values) < 2:
            canvas.create_text(
                w // 2,
                h // 2,
                text="No performance history yet",
                fill=s["muted"],
                font=self._m.font(10),
            )
            return
        lo, hi = min(values), max(values)
        if abs(hi - lo) < 1e-9:
            hi = lo + 1.0
        pad_x, pad_y = 16, 20
        coords: list[float] = []
        n = len(values)
        for i, v in enumerate(values):
            x = pad_x + (w - 2 * pad_x) * (i / (n - 1))
            y = pad_y + (h - 2 * pad_y) * (1.0 - (v - lo) / (hi - lo))
            coords.extend([x, y])
        # Zero line when range crosses 0
        if lo < 0 < hi:
            zy = pad_y + (h - 2 * pad_y) * (1.0 - (0 - lo) / (hi - lo))
            canvas.create_line(pad_x, zy, w - pad_x, zy, fill=s["edge"], dash=(3, 3))
        color = s["up"] if values[-1] >= values[0] else s["down"]
        canvas.create_line(*coords, fill=color, width=2, smooth=True)
        canvas.create_text(
            pad_x,
            10,
            text=f"{_money(values[0])} → {_money(values[-1])}",
            fill=s["muted"],
            font=self._m.font(8),
            anchor="w",
        )

    def _apply_positions_view(self) -> None:
        s = self._scheme
        d = self._last_dash
        port = d.get("portfolio") or {}
        pdisp = port.get("display") if isinstance(port.get("display"), dict) else {}
        self._port_mv.configure(text=str(pdisp.get("market_value") or _money(port.get("market_value"))))
        pl = port.get("unrealized_pl")
        self._port_pl.configure(
            text=str(pdisp.get("unrealized_pl") or _money(pl)),
            fg=_pl_color(pl, s),
        )
        positions = list(d.get("positions") or [])
        tree = self._pos_tree
        for item in tree.get_children():
            tree.delete(item)
        if not positions:
            self._pos_empty.configure(text="No positions yet — connect / refresh when the market session is ready.")
            return
        self._pos_empty.configure(text=f"{len(positions)} positions · Value · Price · P/L · Qty")
        for i, p in enumerate(positions):
            if not isinstance(p, dict):
                continue
            disp = p.get("display") if isinstance(p.get("display"), dict) else {}
            side = str(p.get("side") or "LONG").upper()
            if p.get("transfer_as_deposit"):
                side = "DEPOSIT"
            pl_txt = disp.get("unrealized_pl") or _money(p.get("unrealized_pl"))
            if p.get("transfer_as_deposit"):
                pl_txt = "Deposit"
            tree.insert(
                "",
                tk.END,
                values=(
                    str(p.get("symbol") or "—"),
                    side,
                    disp.get("market_value") or _money(p.get("market_value")),
                    disp.get("price") or _money(p.get("price")),
                    pl_txt,
                    disp.get("quantity") or str(p.get("quantity") or "—"),
                ),
                tags=("even" if i % 2 else "odd",),
            )
        tree.tag_configure("odd", background=s["data"])
        tree.tag_configure("even", background=s["panel"])

    def _apply_orders_view(self) -> None:
        self._fill_orders(self._last_orders)

    def _fill_orders(self, orders: list[dict[str, Any]]) -> None:
        s = self._scheme
        rows = [o for o in orders if isinstance(o, dict)]
        key = self._order_sort
        reverse = not self._order_sort_asc

        def sort_key(o: dict[str, Any]) -> Any:
            if key == "symbol":
                return str(o.get("symbol") or "").upper()
            if key == "status":
                return str(o.get("status") or "").upper()
            if key == "action":
                return str(o.get("action") or o.get("side") or "").upper()
            if key == "value":
                try:
                    return float(o.get("value") or o.get("notional") or o.get("estimated_value") or 0)
                except (TypeError, ValueError):
                    return 0.0
            if key == "qty":
                try:
                    return float(o.get("quantity") or o.get("qty") or 0)
                except (TypeError, ValueError):
                    return 0.0
            if key == "price":
                try:
                    return float(o.get("price") or o.get("limit_price") or o.get("avg_price") or 0)
                except (TypeError, ValueError):
                    return 0.0
            # placed
            return str(o.get("placed_at") or o.get("created_at") or o.get("order_id") or "")

        rows = sorted(rows, key=sort_key, reverse=reverse)

        open_n = sum(
            1
            for o in rows
            if str(o.get("status") or "").upper()
            in ("OPEN", "PENDING", "PARTIAL", "WORKING", "QUEUED", "ACCEPTED", "")
        )
        notional = 0.0
        for o in rows:
            for k in ("value", "notional", "estimated_value"):
                try:
                    notional += abs(float(o.get(k)))
                    break
                except (TypeError, ValueError):
                    continue
        self._ord_open.configure(text=str(open_n if rows else "—"))
        self._ord_notional.configure(text=_money(notional) if rows else "—")

        tree = self._ord_tree
        for item in tree.get_children():
            tree.delete(item)
        if not rows:
            self._ord_empty.configure(
                text="No broker orders yet — login on Long tools if the session expired, then Refresh."
            )
            return
        self._ord_empty.configure(text=f"{len(rows)} orders")
        for i, o in enumerate(rows):
            disp = o.get("display") if isinstance(o.get("display"), dict) else {}
            tree.insert(
                "",
                tk.END,
                values=(
                    str(o.get("symbol") or "—"),
                    str(o.get("action") or o.get("side") or "—").upper(),
                    disp.get("value") or _money(o.get("value") or o.get("notional")),
                    disp.get("pl") or ( _money(o.get("pl")) if o.get("pl") is not None else "—"),
                    str(o.get("status") or "—"),
                    str(o.get("quantity") or o.get("qty") or "—"),
                    disp.get("price") or _money(o.get("price") or o.get("limit_price")),
                ),
                tags=("even" if i % 2 else "odd",),
            )
        tree.tag_configure("odd", background=s["data"])
        tree.tag_configure("even", background=s["panel"])

    def _apply_agents_view(self) -> None:
        s = self._scheme
        pack = getattr(self, "_agents_pack", {}) or {}
        agents = [a for a in self._last_agents if isinstance(a, dict)]
        count = pack.get("agent_count")
        if count is None:
            count = len(agents)
        self._agents_count.configure(text=str(count))
        meta_bits = []
        if pack.get("source"):
            meta_bits.append(str(pack.get("source")))
        if pack.get("message"):
            meta_bits.append(str(pack.get("message")))
        if pack.get("disabled"):
            meta_bits.append("feed disabled on PC")
        self._agents_meta.configure(text=" · ".join(meta_bits) if meta_bits else "Specialist groups from Finance output")

        tree = self._agents_tree
        for item in tree.get_children():
            tree.delete(item)
        if not agents:
            self._agents_empty.configure(
                text=str(pack.get("message") or "No agents snapshot yet — run agents on PC.")
            )
            return
        self._agents_empty.configure(text=f"{len(agents)} agents")
        for i, a in enumerate(agents):
            tree.insert(
                "",
                tk.END,
                values=(
                    str(a.get("name") or a.get("id") or "—"),
                    str(a.get("group") or a.get("group_name") or "—"),
                    str(a.get("role") or a.get("specialty") or "—"),
                    str(a.get("signal") or a.get("stance") or a.get("last_signal") or "—"),
                    str(a.get("updated_at") or a.get("last_run") or "—")[:19],
                ),
                tags=("even" if i % 2 else "odd",),
            )
        tree.tag_configure("odd", background=s["data"])
        tree.tag_configure("even", background=s["panel"])

    # ============================================================== modes
    def _on_sandbox_toggle(self) -> None:
        # Shared sandbox flag on long config (mirrored to short via shared API)
        raw = _read_json(LONG_CONFIG)
        raw["sandbox"] = bool(self._sandbox.get())
        _write_json(LONG_CONFIG, raw)
        try:
            from shared_etrade_api import mirror_shared_api_into_short

            mirror_shared_api_into_short()
        except Exception:
            pass
        self._refresh_all(force=False)

    def _save_long_practice(self) -> None:
        dry = bool(self._long_dry.get())
        _set_worker_flag(LONG_CONFIG, dry_run=dry)
        if self._long_app is not None:
            try:
                self._long_app._dry_run_var.set(dry)
                self._long_app._persist_trading_settings()
            except Exception:
                pass
        self._dry_both.set(dry and bool(self._short_dry.get()))
        self._refresh_all(force=False)

    def _save_short_practice(self) -> None:
        dry = bool(self._short_dry.get())
        _set_worker_flag(SHORT_CONFIG, dry_run=dry)
        if self._short_app is not None:
            try:
                self._short_app._dry_run_var.set(dry)
                self._short_app._persist_trading_settings()
            except Exception:
                pass
        self._dry_both.set(bool(self._long_dry.get()) and dry)
        self._refresh_all(force=False)

    def _save_both_practice(self) -> None:
        dry = bool(self._dry_both.get())
        self._long_dry.set(dry)
        self._short_dry.set(dry)
        _set_worker_flag(LONG_CONFIG, dry_run=dry)
        _set_worker_flag(SHORT_CONFIG, dry_run=dry)
        for app, flag in ((self._long_app, dry), (self._short_app, dry)):
            if app is None:
                continue
            try:
                app._dry_run_var.set(flag)
                app._persist_trading_settings()
            except Exception:
                pass
        self._refresh_all(force=False)

    def _apply_modes(self) -> None:
        self._on_sandbox_toggle()
        self._save_long_practice()
        self._save_short_practice()
        self._status.configure(text="Trade modes applied (shared API · independent practice).", fg=self._scheme["up"])

    # ============================================================== stop/resume
    def _update_stop_all_btn(self, paused: bool) -> None:
        if not hasattr(self, "_btn_stop_all"):
            return
        s = self._scheme
        if paused:
            self._btn_stop_all.configure(text="Resume all", bg=s["up"], activebackground="#00c853")
        else:
            self._btn_stop_all.configure(text="Stop all", bg=s["down"], activebackground="#cc4040")

    def _toggle_stop_all(self) -> None:
        paused = bool(self._last_dash.get("paused"))
        if not paused:
            long_raw = _read_json(LONG_CONFIG)
            short_raw = _read_json(SHORT_CONFIG)
            lw = long_raw.get("background_worker") or {}
            sw = short_raw.get("background_worker") or {}
            paused = bool(lw.get("paused")) or bool(sw.get("paused"))
        if paused:
            self._resume_all()
        else:
            self._stop_all()

    def _stop_all(self) -> None:
        if not messagebox.askyesno(
            "Stop trading",
            "Stop TRADING on BOTH buy and short sleeves?\n\n"
            "Halts swing orders and day trading until you resume.\n"
            "Agent pipeline on BOXONE (if dual-PC) keeps running.",
        ):
            return
        try:
            from etrade_worker import set_automation_paused

            set_automation_paused(True, both_sleeves=True)
        except Exception as exc:
            messagebox.showerror("Stop failed", str(exc))
            return
        self._sync_embedded_automation()
        self._status.configure(
            text="Trading stopped on buy + short (pipeline keeps running if remote).",
            fg=self._scheme["warn"],
        )
        self._refresh_all(force=False)

    def _resume_all(self) -> None:
        try:
            from etrade_worker import set_automation_paused

            set_automation_paused(False, both_sleeves=True)
        except Exception as exc:
            messagebox.showerror("Resume failed", str(exc))
            return
        self._sync_embedded_automation(resume=True)
        self._status.configure(text="Automation resumed on buy + short sleeves.", fg=self._scheme["up"])
        self._refresh_all(force=False)

    def _sync_embedded_automation(self, *, resume: bool = False) -> None:
        for app in (self._long_app, self._short_app):
            if app is None:
                continue
            try:
                if not resume:
                    app._cancel_background_schedules()
                app._load_trading_settings_from_config()
                app._refresh_automation_snapshot()
                app._apply_automation_ui_state()
                if resume:
                    app._apply_automation_running_state()
            except Exception:
                pass

    # ============================================================== sleeves
    def _lazy_build_sleeves(self) -> None:
        if self._sleeves_built:
            return
        s = self._scheme
        self._status.configure(text="Loading Long tools…")
        self._window.update_idletasks()
        try:
            from etrade_trader_gui import ETradeTraderApp

            self._clear_ph(self._tab_adv_long)
            host = tk.Frame(self._tab_adv_long, bg=s["bg"])
            host.pack(fill=tk.BOTH, expand=True)
            self._long_app = ETradeTraderApp(
                host,
                embedded=True,
                manage_window_close=False,
                app_title="Long — buy stocks",
                layout_key="etrade_unified_long",
            )
        except Exception as exc:
            _log(f"Long failed: {exc}\n{traceback.format_exc()}")
            self._clear_ph(self._tab_adv_long)
            tk.Label(
                self._tab_adv_long,
                text=f"Long tools failed:\n{exc}",
                bg=s["bg"],
                fg=s["down"],
                justify=tk.LEFT,
            ).pack(padx=16, pady=16)

        self._status.configure(text="Loading Short tools…")
        self._window.update_idletasks()
        try:
            from short_trader_gui import ShortTraderApp

            self._clear_ph(self._tab_adv_short)
            host = tk.Frame(self._tab_adv_short, bg=s["bg"])
            host.pack(fill=tk.BOTH, expand=True)
            self._short_app = ShortTraderApp(host, embedded=True, manage_window_close=False)
        except Exception as exc:
            _log(f"Short failed: {exc}\n{traceback.format_exc()}")
            self._clear_ph(self._tab_adv_short)
            tk.Label(
                self._tab_adv_short,
                text=f"Short tools failed:\n{exc}",
                bg=s["bg"],
                fg=s["down"],
                justify=tk.LEFT,
            ).pack(padx=16, pady=16)

        self._sleeves_built = True
        self._status.configure(text="Ready — windows match phone: Dashboard · Positions · Orders · Agents · Settings")
        self._refresh_all(force=False)

    def _on_configure(self, _e: tk.Event | None = None) -> None:
        try:
            save_ui_layout("etrade_unified", {"geometry": self._window.geometry()})
        except Exception:
            pass

    def _on_close(self) -> None:
        for app in (self._long_app, self._short_app):
            if app is None:
                continue
            try:
                app._shutting_down = True
                app._cancel_background_schedules()
            except Exception:
                pass
        try:
            self._window.destroy()
        except tk.TclError:
            pass

    def run(self) -> None:
        self._window.mainloop()


def main() -> int:
    try:
        _apply_identity()
        if not _acquire_single_instance():
            return 0
        try:
            from short_trader_gui import _ensure_short_config_seeded
            from sleeve_policy import ensure_config_sleeve_block

            _ensure_short_config_seeded()
            ensure_config_sleeve_block(LONG_CONFIG)
            ensure_config_sleeve_block(SHORT_CONFIG)
        except Exception:
            pass
        app = UnifiedTraderApp()
        tab = os.environ.get("ETRADE_TAB", "").lower()
        # Map legacy long/short env tabs to Settings advanced tools
        if tab in {"short", "short-sleeve"}:
            app._window.after(
                400,
                lambda: (app._nb.select(app._tab_settings), app._settings_nb.select(app._tab_adv_short)),
            )
        elif tab in {"long", "long-sleeve"}:
            app._window.after(
                400,
                lambda: (app._nb.select(app._tab_settings), app._settings_nb.select(app._tab_adv_long)),
            )
        elif tab in {"positions", "pos"}:
            app._window.after(400, lambda: app._nb.select(app._tab_pos))
        elif tab in {"orders", "ord"}:
            app._window.after(400, lambda: app._nb.select(app._tab_ord))
        elif tab in {"agents"}:
            app._window.after(400, lambda: app._nb.select(app._tab_agents))
        elif tab in {"settings", "setup"}:
            app._window.after(400, lambda: app._nb.select(app._tab_settings))
        app.run()
        return 0
    except Exception as exc:
        _log(f"Fatal: {exc}\n{traceback.format_exc()}")
        try:
            messagebox.showerror("E*TRADE Trader", str(exc))
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
