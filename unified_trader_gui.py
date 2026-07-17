#!/usr/bin/env python3
"""Unified E*TRADE Trader — dense, scannable Long + Short dashboard."""

from __future__ import annotations

import json
import os
import sys
import traceback
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
UNIFIED_LOG = ROOT / "output" / "unified_trader.log"
LONG_CONFIG = ROOT / "etrade_config.json"
SHORT_CONFIG = ROOT / "short_etrade_config.json"


def _log(msg: str) -> None:
    UNIFIED_LOG.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime

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


def _mode(dry: bool, auto: bool) -> tuple[str, str]:
    if dry:
        return "PRACTICE", WARN
    if auto:
        return "LIVE AUTO", DOWN
    return "LIVE MANUAL", ACCENT2


class UnifiedTraderApp:
    def __init__(self) -> None:
        load_palette_from_prefs()
        sync_module_globals(sys.modules[__name__])

        self._window = tk.Tk()
        self._window.title("E*TRADE Trader")
        self._window.configure(bg=BG)
        self._m = ScreenMetrics(self._window, window_profile="trader")
        layout = load_ui_layout("etrade_unified")
        geo = str(layout.get("geometry") or "").strip()
        if geo and "x" in geo:
            self._window.geometry(geo)
        else:
            # Prefer a wide window so the dual dashboard fits without scrolling
            w = max(self._m.win_w, min(self._m.screen_w - 40, 1400))
            h = max(self._m.win_h, min(self._m.screen_h - 80, 900))
            self._window.geometry(f"{w}x{h}")
        self._window.minsize(self._m.px(1100), self._m.px(700))

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

        self._long_dry = tk.BooleanVar(value=True)
        self._short_dry = tk.BooleanVar(value=True)
        self._long_auto = tk.BooleanVar(value=False)
        self._short_auto = tk.BooleanVar(value=False)

        self._build()
        self._window.protocol("WM_DELETE_WINDOW", self._on_close)
        self._window.after(120, self._lazy_build_sleeves)
        self._window.bind("<Configure>", self._on_configure, add="+")
        self._window.bind("<F5>", lambda _e: self._refresh_dashboard())

    # ================================================================ layout
    def _build(self) -> None:
        style = ttk.Style(self._window)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        configure_trader_notebooks(style, self._m)
        configure_treeview_style(style, self._m, prefix="Unified")

        # ---- always-visible top strip (modes + accounts) ----
        strip = tk.Frame(self._window, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        strip.pack(fill=tk.X, padx=self._m.px(10), pady=(self._m.px(8), self._m.px(4)))
        si = tk.Frame(strip, bg=PANEL)
        si.pack(fill=tk.X, padx=self._m.px(10), pady=self._m.px(6))

        tk.Label(si, text="E*TRADE", bg=PANEL, fg=TEXT, font=self._m.font(13, "bold")).pack(side=tk.LEFT)
        tk.Label(si, text="  Long + Short", bg=PANEL, fg=MUTED, font=self._m.font(10)).pack(side=tk.LEFT)

        self._strip_long = self._pill(si, "Long: …", UP)
        self._strip_short = self._pill(si, "Short: …", DOWN)
        self._strip_ready = self._pill(si, "Loading", MUTED)

        tk.Button(
            si,
            text="Refresh  F5",
            command=self._refresh_dashboard,
            bg=CARD_BG,
            fg=TEXT,
            relief=tk.FLAT,
            font=self._m.font(9, "bold"),
            padx=10,
            pady=4,
            cursor="hand2",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
        ).pack(side=tk.RIGHT, padx=(8, 0))
        self._btn_stop_all = tk.Button(
            si,
            text="Stop all",
            command=self._toggle_stop_all,
            bg=DOWN,
            fg="#fff",
            relief=tk.FLAT,
            font=self._m.font(9, "bold"),
            padx=12,
            pady=4,
            cursor="hand2",
            bd=0,
            activebackground="#cc4040",
            activeforeground="#fff",
        )
        self._btn_stop_all.pack(side=tk.RIGHT, padx=(8, 0))

        # ---- main notebook ----
        self._nb = ttk.Notebook(self._window, style="Trader.TNotebook")
        self._nb.pack(fill=tk.BOTH, expand=True, padx=self._m.px(10), pady=(0, self._m.px(4)))

        self._tab_dash = tk.Frame(self._nb, bg=BG)
        self._tab_long = tk.Frame(self._nb, bg=BG)
        self._tab_short = tk.Frame(self._nb, bg=BG)
        self._nb.add(self._tab_dash, text="  Dashboard  ")
        self._nb.add(self._tab_long, text="  Long  ")
        self._nb.add(self._tab_short, text="  Short  ")
        self._nb.bind("<<NotebookTabChanged>>", self._on_tab)

        self._build_dashboard()
        self._placeholder(self._tab_long, "Long tools loading…")
        self._placeholder(self._tab_short, "Short tools loading…")

        # ---- footer ----
        foot = tk.Frame(self._window, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        foot.pack(fill=tk.X, side=tk.BOTTOM)
        self._status = tk.Label(
            foot,
            text="Loading dashboard…",
            bg=CARD_BG,
            fg=MUTED,
            font=self._m.font(9),
            anchor="w",
        )
        self._status.pack(fill=tk.X, padx=self._m.px(12), pady=self._m.px(6))

    def _pill(self, parent: tk.Misc, text: str, color: str) -> tk.Label:
        lbl = tk.Label(
            parent,
            text=f"  {text}  ",
            bg=CARD_BG,
            fg=color,
            font=self._m.font(9, "bold"),
            highlightbackground=BORDER,
            highlightthickness=1,
            padx=4,
            pady=3,
        )
        lbl.pack(side=tk.LEFT, padx=(10, 0))
        return lbl

    def _placeholder(self, parent: tk.Misc, msg: str) -> None:
        f = tk.Frame(parent, bg=BG)
        f.pack(fill=tk.BOTH, expand=True)
        tk.Label(f, text=msg, bg=BG, fg=MUTED, font=self._m.font(11)).place(relx=0.5, rely=0.45, anchor="center")
        parent._ph = f  # type: ignore[attr-defined]

    def _clear_ph(self, parent: tk.Misc) -> None:
        ph = getattr(parent, "_ph", None)
        if ph is not None:
            try:
                ph.destroy()
            except tk.TclError:
                pass
            parent._ph = None  # type: ignore[attr-defined]

    # ============================================================ dashboard
    def _build_dashboard(self) -> None:
        """Dense no-scroll-if-possible dashboard: metrics + dual controls + idea lists."""
        root = self._tab_dash
        pad = self._m.px(10)

        # Row 1: 6 metric tiles
        metrics = tk.Frame(root, bg=BG)
        metrics.pack(fill=tk.X, padx=pad, pady=(pad, self._m.px(6)))
        for i in range(6):
            metrics.columnconfigure(i, weight=1, uniform="m")
        self._m_long_mode = self._metric(metrics, 0, "LONG MODE", "—", UP)
        self._m_short_mode = self._metric(metrics, 1, "SHORT MODE", "—", DOWN)
        self._m_long_acct = self._metric(metrics, 2, "LONG ACCOUNT", "—", ACCENT2)
        self._m_short_acct = self._metric(metrics, 3, "SHORT ACCOUNT", "—", ACCENT2)
        self._m_split = self._metric(metrics, 4, "CAPITAL SPLIT", "—", WARN)
        self._m_edge = self._metric(metrics, 5, "JOINT EDGE", "—", ACCENT)

        # Row 2: side-by-side controls (equal height)
        controls = tk.Frame(root, bg=BG)
        controls.pack(fill=tk.X, padx=pad, pady=(0, self._m.px(6)))
        controls.columnconfigure((0, 1), weight=1, uniform="c")

        self._build_side_panel(
            controls,
            0,
            title="LONG — buy",
            color=UP,
            dry_var=self._long_dry,
            auto_var=self._long_auto,
            on_change=self._save_long,
            open_cmd=lambda: self._nb.select(self._tab_long),
            practice_lbl="Practice (no real buys)",
            auto_lbl="Auto-place long trades",
            open_lbl="Open Long tools",
            attr_prefix="long",
        )
        self._build_side_panel(
            controls,
            1,
            title="SHORT — sell short",
            color=DOWN,
            dry_var=self._short_dry,
            auto_var=self._short_auto,
            on_change=self._save_short,
            open_cmd=lambda: self._nb.select(self._tab_short),
            practice_lbl="Practice (no real shorts)",
            auto_lbl="Auto-place short trades",
            open_lbl="Open Short tools",
            attr_prefix="short",
        )

        # Row 3: opportunities + comparison (fills remaining height)
        bottom = tk.Frame(root, bg=BG)
        bottom.pack(fill=tk.BOTH, expand=True, padx=pad, pady=(0, pad))
        bottom.columnconfigure(0, weight=2)
        bottom.columnconfigure(1, weight=2)
        bottom.columnconfigure(2, weight=3)
        bottom.rowconfigure(0, weight=1)

        # Top long ideas
        left = tk.Frame(bottom, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        tk.Label(left, text="  Top long ideas", bg=PANEL, fg=UP, font=self._m.font(10, "bold"), anchor="w").pack(
            fill=tk.X, pady=(6, 2)
        )
        self._long_ideas = self._listbox(left)

        # Top short ideas
        mid = tk.Frame(bottom, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        mid.grid(row=0, column=1, sticky="nsew", padx=4)
        tk.Label(mid, text="  Top short ideas", bg=PANEL, fg=DOWN, font=self._m.font(10, "bold"), anchor="w").pack(
            fill=tk.X, pady=(6, 2)
        )
        self._short_ideas = self._listbox(mid)

        # Comparison table
        right = tk.Frame(bottom, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        right.grid(row=0, column=2, sticky="nsew", padx=(4, 0))
        tk.Label(
            right, text="  Side-by-side snapshot", bg=PANEL, fg=TEXT, font=self._m.font(10, "bold"), anchor="w"
        ).pack(fill=tk.X, pady=(6, 2))

        tree_wrap = tk.Frame(right, bg=PANEL)
        tree_wrap.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        cols = ("item", "long", "short")
        self._snap = ttk.Treeview(
            tree_wrap,
            columns=cols,
            show="headings",
            style="Unified.Treeview",
            height=12,
        )
        self._snap.heading("item", text="What")
        self._snap.heading("long", text="Long")
        self._snap.heading("short", text="Short")
        self._snap.column("item", width=120, anchor="w")
        self._snap.column("long", width=160, anchor="w")
        self._snap.column("short", width=160, anchor="w")
        yscroll = ttk.Scrollbar(tree_wrap, orient=tk.VERTICAL, command=self._snap.yview)
        self._snap.configure(yscrollcommand=yscroll.set)
        self._snap.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Tiny help line
        tk.Label(
            root,
            text="Dashboard shows both sides at once. Press F5 to refresh. Use Long / Short tabs for full connect, agents, and orders.",
            bg=BG,
            fg=MUTED,
            font=self._m.font(8),
            anchor="w",
        ).pack(fill=tk.X, padx=pad, pady=(0, self._m.px(4)))

    def _metric(self, parent: tk.Misc, col: int, title: str, value: str, color: str) -> tk.Label:
        cell = tk.Frame(parent, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        cell.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 3, 0 if col == 5 else 3))
        tk.Frame(cell, bg=color, height=2).pack(fill=tk.X)
        tk.Label(cell, text=title, bg=CARD_BG, fg=MUTED, font=self._m.font(7, "bold")).pack(
            anchor="w", padx=8, pady=(6, 0)
        )
        val = tk.Label(cell, text=value, bg=CARD_BG, fg=TEXT, font=self._m.font(11, "bold"), anchor="w")
        val.pack(fill=tk.X, padx=8, pady=(2, 8))
        return val

    def _listbox(self, parent: tk.Misc) -> tk.Listbox:
        frame = tk.Frame(parent, bg=PANEL)
        frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        lb = tk.Listbox(
            frame,
            bg=CARD_BG,
            fg=TEXT,
            selectbackground=ACCENT,
            selectforeground="#fff",
            relief=tk.FLAT,
            font=self._m.mono(9),
            activestyle="none",
            highlightthickness=0,
            borderwidth=0,
        )
        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        return lb

    def _build_side_panel(
        self,
        parent: tk.Misc,
        col: int,
        *,
        title: str,
        color: str,
        dry_var: tk.BooleanVar,
        auto_var: tk.BooleanVar,
        on_change: Callable[[], None],
        open_cmd: Callable[[], None],
        practice_lbl: str,
        auto_lbl: str,
        open_lbl: str,
        attr_prefix: str,
    ) -> None:
        card = tk.Frame(parent, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 4, 0 if col == 1 else 4))
        tk.Frame(card, bg=color, height=3).pack(fill=tk.X)
        inner = tk.Frame(card, bg=CARD_BG)
        inner.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        head = tk.Frame(inner, bg=CARD_BG)
        head.pack(fill=tk.X)
        tk.Label(head, text=title, bg=CARD_BG, fg=TEXT, font=self._m.font(11, "bold")).pack(side=tk.LEFT)
        badge = tk.Label(head, text="  —  ", bg=PANEL, fg=MUTED, font=self._m.font(8, "bold"), padx=4, pady=2)
        badge.pack(side=tk.RIGHT)
        setattr(self, f"_{attr_prefix}_badge", badge)

        acct = tk.Label(inner, text="Account —", bg=CARD_BG, fg=MUTED, font=self._m.font(9), anchor="w")
        acct.pack(fill=tk.X, pady=(4, 4))
        setattr(self, f"_{attr_prefix}_acct", acct)

        tk.Checkbutton(
            inner,
            text=practice_lbl,
            variable=dry_var,
            command=on_change,
            bg=CARD_BG,
            fg=WARN,
            selectcolor=PANEL,
            activebackground=CARD_BG,
            font=self._m.font(9),
            anchor="w",
        ).pack(fill=tk.X)
        tk.Checkbutton(
            inner,
            text=auto_lbl,
            variable=auto_var,
            command=on_change,
            bg=CARD_BG,
            fg=TEXT,
            selectcolor=PANEL,
            activebackground=CARD_BG,
            font=self._m.font(9),
            anchor="w",
        ).pack(fill=tk.X)

        btns = tk.Frame(inner, bg=CARD_BG)
        btns.pack(fill=tk.X, pady=(8, 0))
        tk.Button(
            btns,
            text=open_lbl,
            command=open_cmd,
            bg=PANEL,
            fg=TEXT,
            relief=tk.FLAT,
            font=self._m.font(9, "bold"),
            padx=10,
            pady=5,
            cursor="hand2",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
        ).pack(side=tk.LEFT)

    # ============================================================== data fill
    def _set_metric(self, lbl: tk.Label, text: str, color: str | None = None) -> None:
        lbl.configure(text=text)
        if color:
            lbl.configure(fg=color)

    def _fill_list(self, lb: tk.Listbox, rows: list[str]) -> None:
        lb.delete(0, tk.END)
        if not rows:
            lb.insert(tk.END, "  (none yet — run agents)")
            return
        for row in rows:
            lb.insert(tk.END, f"  {row}")

    def _refresh_dashboard(self) -> None:
        long_raw = _read_json(LONG_CONFIG)
        short_raw = _read_json(SHORT_CONFIG)
        lw = long_raw.get("background_worker") or {}
        sw = short_raw.get("background_worker") or {}
        long_acct = (long_raw.get("selected_account") or {}).get("display_label") or "Not set"
        short_acct = (short_raw.get("selected_account") or {}).get("display_label") or "Not set"

        self._long_dry.set(bool(lw.get("dry_run", False)))
        self._short_dry.set(bool(sw.get("dry_run", True)))
        self._long_auto.set(bool(lw.get("auto_execute", True)))
        self._short_auto.set(bool(sw.get("auto_execute", False)))

        both_paused = bool(lw.get("paused")) or bool(sw.get("paused"))
        self._update_stop_all_btn(both_paused)

        lm, lc = _mode(bool(lw.get("dry_run")), bool(lw.get("auto_execute")))
        sm, sc = _mode(bool(sw.get("dry_run")), bool(sw.get("auto_execute")))
        if both_paused:
            lm, lc = "STOPPED", WARN
            sm, sc = "STOPPED", WARN
        env_l = "Sandbox" if long_raw.get("sandbox") else "Production"
        env_s = "Sandbox" if short_raw.get("sandbox") else "Production"

        # Top strip
        self._strip_long.configure(text=f"  Long: {lm} · {env_l}  ", fg=lc)
        self._strip_short.configure(text=f"  Short: {sm} · {env_s}  ", fg=sc)
        self._strip_ready.configure(
            text="  STOPPED  " if both_paused else ("  Ready  " if self._sleeves_built else "  Loading  "),
            fg=WARN if both_paused else (UP if self._sleeves_built else WARN),
        )

        # Metrics
        self._set_metric(self._m_long_mode, lm, lc)
        self._set_metric(self._m_short_mode, sm, sc)
        # Truncate long account names for tiles
        self._set_metric(self._m_long_acct, self._shorten(long_acct, 22))
        self._set_metric(self._m_short_acct, self._shorten(short_acct, 22))

        self._long_badge.configure(text=f"  {lm}  ", fg=lc)
        self._short_badge.configure(text=f"  {sm}  ", fg=sc)
        self._long_acct.configure(text=f"{long_acct}  ·  {env_l}")
        self._short_acct.configure(text=f"{short_acct}  ·  {env_s}")

        # Coordination
        try:
            from sleeve_coordinator import coordinate_sleeves

            coord = coordinate_sleeves()
            deploy = coord.get("deploy") or {}
            exp = coord.get("expected_profit") or {}
            long_pct = deploy.get("long_max_deploy_pct", "—")
            short_pct = deploy.get("short_max_deploy_pct", "—")
            joint = float(exp.get("expected_profit_usd_joint") or 0)
            self._set_metric(self._m_split, f"L {long_pct}% / S {short_pct}%", WARN)
            self._set_metric(self._m_edge, f"${joint:,.0f}" if joint else "—", ACCENT)

            tops_l = exp.get("top_long") or []
            tops_s = exp.get("top_short") or []
            # richer list from assignment edges if available
            assignment = coord.get("symbol_assignment") or {}
            long_rows = []
            short_rows = []
            # Prefer ordered top lists with ranks
            for i, sym in enumerate(tops_l[:12], 1):
                long_rows.append(f"{i:>2}. {sym}")
            for i, sym in enumerate(tops_s[:12], 1):
                short_rows.append(f"{i:>2}. {sym}")
            if not long_rows:
                long_rows = [s for s, side in sorted(assignment.items()) if side == "long"][:12]
            if not short_rows:
                short_rows = [s for s, side in sorted(assignment.items()) if side == "short"][:12]
            self._fill_list(self._long_ideas, long_rows)
            self._fill_list(self._short_ideas, short_rows)

            # Snapshot table
            for item in self._snap.get_children():
                self._snap.delete(item)
            rows = [
                ("Mode", lm, sm),
                ("Environment", env_l, env_s),
                ("Account", self._shorten(long_acct, 28), self._shorten(short_acct, 28)),
                ("Practice", "ON" if lw.get("dry_run") else "OFF", "ON" if sw.get("dry_run") else "OFF"),
                ("Auto-trade", "ON" if lw.get("auto_execute") else "OFF", "ON" if sw.get("auto_execute") else "OFF"),
                ("Budget %", f"{long_pct}%", f"{short_pct}%"),
                ("Exp. profit $", f"${float(exp.get('expected_profit_usd_long') or 0):,.0f}", f"${float(exp.get('expected_profit_usd_short') or 0):,.0f}"),
                ("Top idea", tops_l[0] if tops_l else "—", tops_s[0] if tops_s else "—"),
                ("# ideas", str(len(long_rows)), str(len(short_rows))),
                ("Config", LONG_CONFIG.name, SHORT_CONFIG.name),
                ("Isolation", "Longs only", "Shorts only"),
                ("Shared capital", "Yes", "Yes"),
            ]
            for i, (a, b, c) in enumerate(rows):
                tag = "even" if i % 2 else "odd"
                self._snap.insert("", tk.END, values=(a, b, c), tags=(tag,))
            self._snap.tag_configure("odd", background=CARD_BG)
            self._snap.tag_configure("even", background=PANEL)

            g = coord.get("guidance") or {}
            self._status.configure(
                text=g.get("joint") or "Dashboard refreshed. F5 to refresh again.",
                fg=TEXT,
            )
        except Exception as exc:
            self._set_metric(self._m_split, "—")
            self._set_metric(self._m_edge, "—")
            self._fill_list(self._long_ideas, [])
            self._fill_list(self._short_ideas, [])
            self._status.configure(text=f"Could not load coordination: {exc}", fg=WARN)

        if self._refresh_after:
            try:
                self._window.after_cancel(self._refresh_after)
            except tk.TclError:
                pass
        try:
            self._refresh_after = self._window.after(30_000, self._refresh_dashboard)
        except tk.TclError:
            self._refresh_after = None

    @staticmethod
    def _shorten(text: str, n: int) -> str:
        t = str(text or "")
        return t if len(t) <= n else t[: n - 1] + "…"

    # ============================================================== actions
    def _update_stop_all_btn(self, paused: bool) -> None:
        if not hasattr(self, "_btn_stop_all"):
            return
        if paused:
            self._btn_stop_all.configure(
                text="Resume all",
                bg=UP,
                activebackground="#00c853",
            )
        else:
            self._btn_stop_all.configure(
                text="Stop all",
                bg=DOWN,
                activebackground="#cc4040",
            )

    def _toggle_stop_all(self) -> None:
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
            "Stop all",
            "Stop all automation on BOTH buy and short apps?\n\n"
            "Halts agents, strategy, swing trades, and day trading "
            "for long + short (and both headless workers) until you resume.",
        ):
            return
        try:
            from etrade_worker import set_automation_paused

            set_automation_paused(True, both_sleeves=True)
        except Exception as exc:
            messagebox.showerror("Stop failed", str(exc))
            return
        for app in (self._long_app, self._short_app):
            if app is None:
                continue
            try:
                app._cancel_background_schedules()
                app._load_trading_settings_from_config()
                app._refresh_automation_snapshot()
                app._apply_automation_ui_state()
            except Exception:
                pass
        self._status.configure(text="All automation stopped on buy + short apps.", fg=WARN)
        self._refresh_dashboard()

    def _resume_all(self) -> None:
        try:
            from etrade_worker import set_automation_paused

            set_automation_paused(False, both_sleeves=True)
        except Exception as exc:
            messagebox.showerror("Resume failed", str(exc))
            return
        for app in (self._long_app, self._short_app):
            if app is None:
                continue
            try:
                app._load_trading_settings_from_config()
                app._refresh_automation_snapshot()
                app._apply_automation_ui_state()
                app._apply_automation_running_state()
            except Exception:
                pass
        self._status.configure(text="Automation resumed on buy + short apps.", fg=UP)
        self._refresh_dashboard()

    def _save_long(self) -> None:
        dry, auto = bool(self._long_dry.get()), bool(self._long_auto.get())
        _set_worker_flag(LONG_CONFIG, dry_run=dry, auto_execute=auto, live_trading=auto and not dry)
        if self._long_app is not None:
            try:
                self._long_app._dry_run_var.set(dry)
                self._long_app._auto_execute_var.set(auto)
                self._long_app._persist_trading_settings()
                self._long_app._update_bg_status()
            except Exception:
                pass
        self._refresh_dashboard()

    def _save_short(self) -> None:
        dry, auto = bool(self._short_dry.get()), bool(self._short_auto.get())
        _set_worker_flag(SHORT_CONFIG, dry_run=dry, auto_execute=auto, live_trading=auto and not dry)
        if self._short_app is not None:
            try:
                self._short_app._dry_run_var.set(dry)
                self._short_app._auto_execute_var.set(auto)
                self._short_app._persist_trading_settings()
                self._short_app._update_bg_status()
            except Exception:
                pass
        self._refresh_dashboard()

    def _lazy_build_sleeves(self) -> None:
        if self._sleeves_built:
            return
        self._status.configure(text="Loading Long tools…")
        self._window.update_idletasks()
        try:
            from etrade_trader_gui import ETradeTraderApp

            self._clear_ph(self._tab_long)
            host = tk.Frame(self._tab_long, bg=BG)
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
            self._clear_ph(self._tab_long)
            tk.Label(self._tab_long, text=f"Long tools failed:\n{exc}", bg=BG, fg=DOWN, justify=tk.LEFT).pack(
                padx=16, pady=16
            )

        self._status.configure(text="Loading Short tools…")
        self._window.update_idletasks()
        try:
            from short_trader_gui import ShortTraderApp

            self._clear_ph(self._tab_short)
            host = tk.Frame(self._tab_short, bg=BG)
            host.pack(fill=tk.BOTH, expand=True)
            self._short_app = ShortTraderApp(host, embedded=True, manage_window_close=False)
        except Exception as exc:
            _log(f"Short failed: {exc}\n{traceback.format_exc()}")
            self._clear_ph(self._tab_short)
            tk.Label(self._tab_short, text=f"Short tools failed:\n{exc}", bg=BG, fg=DOWN, justify=tk.LEFT).pack(
                padx=16, pady=16
            )

        self._sleeves_built = True
        self._status.configure(text="Ready — Dashboard shows both sides. Long/Short tabs have full tools.")
        self._refresh_dashboard()

    def _on_tab(self, _e: tk.Event | None = None) -> None:
        try:
            sel = str(self._nb.select())
        except tk.TclError:
            return
        if sel == str(self._tab_dash):
            self._refresh_dashboard()

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
        if tab in {"short", "short-sleeve"}:
            app._window.after(400, lambda: app._nb.select(app._tab_short))
        elif tab in {"long", "long-sleeve"}:
            app._window.after(400, lambda: app._nb.select(app._tab_long))
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
