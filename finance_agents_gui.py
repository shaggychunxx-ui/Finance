#!/usr/bin/env python3
"""Finance Agents — Windows desktop control panel for all intelligence agents."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any, Callable

from tkinter import messagebox, ttk
import tkinter as tk

from agent_report_formatter import format_report_summary
from agent_report_status import (
    agent_accuracy_label,
    agent_age_info,
    agent_mtime,
    agent_status,
    fresh_report_counts,
)
from app_paths import ICON_FILE, OUTPUT, ROOT, ensure_app_path
from finance_runners import load_finance_runners
from gui_treekit import bind_tree_sort, reapply_tree_sort
from gui_theme import (
    ACCENT,
    ACCENT2,
    BG,
    BORDER,
    BTN_PRIMARY_FG,
    BTN_PRIMARY_HOVER,
    DOWN,
    MUTED,
    PANEL,
    TEXT,
    TREE_HEADING_BG,
    UP,
    WARN,
    ScreenMetrics,
    build_color_remap,
    configure_finance_styles,
    current_palette_name,
    load_palette_from_prefs,
    load_ui_layout,
    pane_sash_ratio,
    place_pane_ratio,
    save_ui_layout,
    recolor_widget_tree,
    sync_module_globals,
)

ensure_app_path()

def get_agent_catalog(*, refresh: bool = False) -> list[dict[str, str]]:
    """Load all runnable agents from local packages and check GitHub for new ones."""
    from agents.platform_catalog import full_agent_catalog

    return full_agent_catalog(check_remote=refresh)


AGENT_CATALOG: list[dict[str, str]] = get_agent_catalog()

DASHBOARDS: list[dict[str, str]] = [
    {"label": "Predictions Dashboard", "file": "predictions_dashboard.html", "module": "predictions"},
    {"label": "Sales Dashboard", "file": "sales_dashboard.html", "module": "sales"},
    {"label": "World Events Tracker", "file": "index.html", "module": "events"},
    {"label": "Mobile Dashboard", "file": "mobile_dashboard.html", "module": "mobile"},
]

CATEGORY_ICONS: dict[str, str] = {
    "Energy & Infrastructure": "⚡",
    "Markets & Finance": "📈",
    "Probability & Stats": "📊",
    "Intelligence": "🌐",
    "Data Platform": "🗄",
    "Ensemble": "🎯",
}

STATUS_COLORS = {"Fresh": UP, "Stale": WARN, "Old": DOWN, "—": MUTED}


class FinanceAgentsApp(tk.Frame):
    def __init__(self, parent: tk.Misc | None = None, *, embedded: bool = False) -> None:
        self._embedded = embedded
        if parent is None:
            self._window = tk.Tk()
            parent = self._window
        else:
            self._window = parent.winfo_toplevel()
        super().__init__(parent, bg=BG if not embedded else PANEL)

        self._m = ScreenMetrics(self._window)
        self._layout_save_after_id: str | None = None
        self._layout_key = "finance_agents_embedded" if embedded else "finance_agents"
        if not embedded:
            self._window.title("Finance Agents")
            self._window.configure(bg=BG)
            saved_geometry = str(load_ui_layout(self._layout_key).get("geometry") or "").strip()
            if saved_geometry and "x" in saved_geometry:
                self._window.geometry(saved_geometry)
            else:
                self._window.geometry(f"{self._m.win_w}x{self._m.win_h}")
                self._center_window()
            self._window.minsize(self._m.min_w, self._m.min_h)
        self.pack(fill=tk.BOTH, expand=True)

        global AGENT_CATALOG
        AGENT_CATALOG = get_agent_catalog(refresh=not embedded)
        self._runners = load_finance_runners()
        self._running = False
        self._batch_running = False
        self._selected_id: str | None = None
        self._agent_rows: dict[str, str] = {}
        self._ui_queue: queue.Queue[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] = (
            queue.Queue()
        )
        self._ui_poll_job: str | None = None

        load_palette_from_prefs()
        sync_module_globals(sys.modules[__name__])

        if not embedded:
            self._set_icon()
            self._build_menu()
            self._window.protocol("WM_DELETE_WINDOW", self._on_close)
            self._window.bind("<Configure>", self._on_window_configure, add="+")
        self._build_styles()
        self._build_ui()
        self._start_ui_queue_poller()
        self._hydrate_agent_learning()
        self._select_default_agent()

    def _pad(self) -> int:
        return self._m.px(8 if self._embedded else 16)

    def _center_window(self) -> None:
        x = max(0, (self._m.screen_w - self._m.win_w) // 2)
        y = max(0, (self._m.screen_h - self._m.win_h) // 2)
        self._window.geometry(f"{self._m.win_w}x{self._m.win_h}+{x}+{y}")

    def _schedule_layout_save(self) -> None:
        if self._layout_save_after_id:
            return
        try:
            self._layout_save_after_id = self._window.after(350, self._flush_layout_save)
        except tk.TclError:
            pass

    def _on_window_configure(self, event: tk.Event) -> None:
        if event.widget is not self._window:
            return
        self._schedule_layout_save()

    def _flush_layout_save(self) -> None:
        self._layout_save_after_id = None
        patch: dict[str, Any] = {}
        if not self._embedded:
            try:
                patch["geometry"] = self._window.geometry()
            except tk.TclError:
                pass
        if hasattr(self, "_splitter"):
            ratio = pane_sash_ratio(self._splitter)
            if ratio is not None:
                patch["sidebar_split_ratio"] = round(ratio, 4)
        save_ui_layout(self._layout_key, patch)

    def _restore_saved_layout(self) -> None:
        layout = load_ui_layout(self._layout_key)
        ratio = layout.get("sidebar_split_ratio")
        if ratio is not None and hasattr(self, "_splitter"):
            place_pane_ratio(self._splitter, float(ratio), min_total=self._m.px(260))

    def _on_close(self) -> None:
        if self._layout_save_after_id:
            try:
                self._window.after_cancel(self._layout_save_after_id)
            except tk.TclError:
                pass
            self._layout_save_after_id = None
        self._flush_layout_save()
        self._window.destroy()

    def _set_icon(self) -> None:
        if ICON_FILE.exists():
            try:
                self._window.iconbitmap(str(ICON_FILE))
            except tk.TclError:
                pass

    def _build_styles(self) -> None:
        style = ttk.Style(self._window)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        configure_finance_styles(style, self._m, embedded=self._embedded)
        style.configure(
            "Finance.Horizontal.TProgressbar",
            troughcolor=BORDER,
            background=ACCENT2,
            thickness=self._m.px(6),
        )
        style.configure("Finance.TNotebook", background=BG, borderwidth=0)
        style.configure(
            "Finance.TNotebook.Tab",
            background=PANEL,
            foreground=MUTED,
            padding=(self._m.px(18), self._m.px(10)),
            font=self._m.font(11, "bold"),
        )
        style.map(
            "Finance.TNotebook.Tab",
            background=[("selected", BORDER)],
            foreground=[("selected", TEXT)],
        )

    def refresh_theme(self, previous_palette: str | None = None) -> None:
        from gui_treekit import refresh_tree_tags_in_widget

        previous = previous_palette or current_palette_name()
        sync_module_globals(sys.modules[__name__])
        self._build_styles()
        color_map = build_color_remap(previous, current_palette_name())
        recolor_widget_tree(self, color_map)
        refresh_tree_tags_in_widget(self, trading=False)

    def _make_button(
        self,
        parent: tk.Misc,
        text: str,
        command: Callable[[], None],
        *,
        variant: str = "secondary",
        side: str = tk.LEFT,
        padx: tuple[int, int] | int = 0,
    ) -> tk.Button:
        styles = {
            "primary": (ACCENT, BTN_PRIMARY_FG, BTN_PRIMARY_HOVER, self._m.font(10, "bold")),
            "accent": (ACCENT2, BG, ACCENT2, self._m.font(10, "bold")),
            "secondary": (BORDER, TEXT, ACCENT, self._m.font(10)),
            "ghost": (PANEL, MUTED, BORDER, self._m.font(9)),
        }
        bg, fg, active_bg, font = styles.get(variant, styles["secondary"])
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=active_bg,
            activeforeground=fg if variant != "secondary" else "#fff",
            relief=tk.FLAT,
            font=font,
            padx=self._m.px(12),
            pady=self._m.px(8),
            cursor="hand2",
            bd=0,
        )
        btn.pack(side=side, padx=padx)
        return btn

    def _build_menu(self) -> None:
        menubar = tk.Menu(self._window, bg=PANEL, fg=TEXT, activebackground=ACCENT, activeforeground="#fff")
        self._window.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0, bg=PANEL, fg=TEXT, activebackground=ACCENT)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Open Output Folder", command=self._open_output_folder)
        file_menu.add_command(label="Import JSON Report…", command=self._import_json)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._window.destroy)

        tools_menu = tk.Menu(menubar, tearoff=0, bg=PANEL, fg=TEXT, activebackground=ACCENT)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Open Market Predictor App", command=self._open_market_predictor)
        tools_menu.add_command(label="Sync Agents from GitHub", command=self._sync_agents)
        tools_menu.add_command(label="Start Mobile API Server", command=self._start_mobile_server)

        help_menu = tk.Menu(menubar, tearoff=0, bg=PANEL, fg=TEXT, activebackground=ACCENT)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="GitHub Repository", command=self._open_github)
        help_menu.add_command(label="About", command=self._show_about)

    def _build_ui(self) -> None:
        pad = self._pad()
        shell_bg = PANEL if self._embedded else BG

        if self._embedded:
            header = tk.Frame(self, bg=PANEL)
            header.pack(fill=tk.X, padx=pad, pady=(self._m.px(6), self._m.px(2)))
            self._embedded_summary = tk.Label(
                header,
                text="",
                bg=PANEL,
                fg=MUTED,
                font=self._m.font(11),
            )
            self._embedded_summary.pack(side=tk.LEFT)
            tools = tk.Frame(header, bg=PANEL)
            tools.pack(side=tk.RIGHT)
            self._make_button(
                tools, "Sync GitHub", self._sync_agents, variant="ghost", side=tk.LEFT
            )
            self._update_embedded_summary()
        else:
            header = tk.Frame(self, bg=BG)
            header.pack(fill=tk.X, padx=pad, pady=(pad, self._m.px(6)))
            title_block = tk.Frame(header, bg=BG)
            title_block.pack(side=tk.LEFT, fill=tk.Y)
            tk.Label(
                title_block,
                text="Finance Agents",
                bg=BG,
                fg=TEXT,
                font=self._m.font(20, "bold"),
            ).pack(anchor="w")
            tk.Label(
                title_block,
                text="Agent reports update automatically — select an agent to review its analysis",
                bg=BG,
                fg=MUTED,
                font=self._m.font(10),
            ).pack(anchor="w")

        body = tk.Frame(self, bg=shell_bg)
        body.pack(fill=tk.BOTH, expand=True, padx=pad, pady=(0, self._m.px(4 if self._embedded else 8)))
        splitter = tk.PanedWindow(
            body,
            orient=tk.HORIZONTAL,
            bg=shell_bg,
            sashwidth=self._m.px(6),
            sashrelief=tk.FLAT,
            opaqueresize=True,
            showhandle=False,
        )
        splitter.pack(fill=tk.BOTH, expand=True)
        self._splitter = splitter
        splitter.bind("<ButtonRelease-1>", lambda _e: self._schedule_layout_save())
        self.after(200, self._restore_saved_layout)

        sidebar = tk.Frame(splitter, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        sidebar_width = self._m.px(580 if self._embedded else 340)
        splitter.add(sidebar, minsize=self._m.px(440 if self._embedded else 260), width=sidebar_width)

        if not self._embedded:
            sb_head = tk.Frame(sidebar, bg=PANEL)
            sb_head.pack(fill=tk.X, padx=self._m.px(12), pady=(self._m.px(12), self._m.px(6)))
            tk.Label(sb_head, text="Agents", bg=PANEL, fg=TEXT, font=self._m.font(12, "bold")).pack(
                side=tk.LEFT
            )

        search_wrap = tk.Frame(sidebar, bg=PANEL)
        search_wrap.pack(
            fill=tk.X,
            padx=self._m.px(10 if self._embedded else 12),
            pady=(self._m.px(8 if self._embedded else 12), self._m.px(6)),
        )
        tk.Label(search_wrap, text="🔍", bg=PANEL, fg=MUTED, font=self._m.font(10)).pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._filter_agents())
        self._search_entry = tk.Entry(
            search_wrap,
            textvariable=self._search_var,
            bg="#0d1424",
            fg=TEXT,
            insertbackground=TEXT,
            relief=tk.FLAT,
            font=self._m.font(10),
        )
        self._search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(self._m.px(6), 0), ipady=self._m.px(6))
        self._search_entry.insert(0, "")
        self._search_entry.bind("<FocusIn>", self._on_search_focus_in)
        self._search_entry.bind("<FocusOut>", self._on_search_focus_out)
        self._search_placeholder = "Search agents…"
        self._show_search_placeholder()

        tree_frame = tk.Frame(sidebar, bg=PANEL)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=self._m.px(8), pady=(0, self._m.px(8)))
        self._tree = ttk.Treeview(
            tree_frame,
            columns=("status", "accuracy"),
            show="tree headings",
            style="Finance.Treeview",
            selectmode="browse",
        )
        self._tree.column("#0", width=self._m.px(300 if self._embedded else 220), stretch=True, minwidth=self._m.px(180))
        self._tree.column("status", width=self._m.px(80), stretch=False, anchor="center")
        self._tree.column("accuracy", width=self._m.px(150), stretch=False, anchor="center")
        scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=scroll.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        bind_tree_sort(
            self._tree,
            ("#0", "status", "accuracy"),
            {"#0": ("Agent", 300), "status": ("Age", 80), "accuracy": ("Accuracy", 150)},
            hierarchical=True,
        )
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._tree.bind("<Double-1>", lambda _e: self._on_tree_select())
        self._populate_agent_tree()

        legend = tk.Frame(sidebar, bg=PANEL)
        legend.pack(fill=tk.X, padx=self._m.px(10 if self._embedded else 12), pady=(0, self._m.px(8)))
        for label, color in (("<6h", UP), ("<24h", WARN), ("older", DOWN)):
            tk.Label(legend, text="●", bg=PANEL, fg=color, font=self._m.font(8)).pack(side=tk.LEFT)
            tk.Label(legend, text=label, bg=PANEL, fg=MUTED, font=self._m.font(8)).pack(
                side=tk.LEFT, padx=(2, self._m.px(8))
            )

        main_bg = PANEL if self._embedded else BG
        main = tk.Frame(splitter, bg=main_bg)
        splitter.add(main, minsize=self._m.px(420 if self._embedded else 360))

        self._report_panel = tk.Frame(main, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        self._report_panel.pack(fill=tk.BOTH, expand=True)
        self._build_report_panel()

        if self._embedded:
            self._status_dot = None
            self._status_label = None
            self._progress = ttk.Progressbar(self, mode="indeterminate", style="Finance.Horizontal.TProgressbar")
        else:
            footer = tk.Frame(self, bg=BORDER, height=self._m.px(36))
            footer.pack(fill=tk.X, side=tk.BOTTOM)
            footer.pack_propagate(False)
            foot_inner = tk.Frame(footer, bg=BORDER)
            foot_inner.pack(fill=tk.BOTH, expand=True, padx=pad, pady=self._m.px(6))
            self._status_dot = tk.Label(foot_inner, text="●", bg=BORDER, fg=ACCENT2, font=self._m.font(10))
            self._status_dot.pack(side=tk.LEFT)
            self._status_label = tk.Label(
                foot_inner,
                text="Ready — select an agent to view its latest report",
                bg=BORDER,
                fg=TEXT,
                font=self._m.font(10),
                anchor="w",
            )
            self._status_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(self._m.px(6), 0))
            self._progress = ttk.Progressbar(
                foot_inner, mode="indeterminate", style="Finance.Horizontal.TProgressbar", length=self._m.px(120)
            )

    def _build_report_panel(self) -> None:
        pad = self._m.px(10 if self._embedded else 14)
        wrap = tk.Frame(self._report_panel, bg=PANEL)
        wrap.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad)
        wrap.columnconfigure(0, weight=1)

        header = tk.Frame(wrap, bg="#152238", highlightbackground=BORDER, highlightthickness=1)
        header.grid(row=0, column=0, sticky="ew", pady=(0, self._m.px(8)))
        header.columnconfigure(0, weight=1)

        title_size = 17 if self._embedded else 16
        self._title_label = tk.Label(
            header,
            text="Select an agent",
            bg="#152238",
            fg=TEXT,
            font=self._m.font(title_size, "bold"),
            anchor="w",
        )
        self._title_label.grid(row=0, column=0, sticky="ew", padx=self._m.px(12), pady=(self._m.px(10), self._m.px(4)))

        meta_row = tk.Frame(header, bg="#152238")
        meta_row.grid(row=1, column=0, sticky="ew", padx=self._m.px(12), pady=(0, self._m.px(8)))
        chip_font = self._m.font(10 if self._embedded else 9)
        chip_pad = (self._m.px(8), self._m.px(4))

        self._status_badge = tk.Label(
            meta_row, text="", bg=BORDER, fg=MUTED, font=chip_font, padx=chip_pad[0], pady=chip_pad[1]
        )
        self._status_badge.pack(side=tk.LEFT, padx=(0, self._m.px(6)))
        self._updated_label = tk.Label(
            meta_row, text="", bg=BORDER, fg=TEXT, font=chip_font, padx=chip_pad[0], pady=chip_pad[1]
        )
        self._updated_label.pack(side=tk.LEFT, padx=(0, self._m.px(6)))
        self._accuracy_chip = tk.Label(
            meta_row, text="", bg=BORDER, fg=ACCENT2, font=chip_font, padx=chip_pad[0], pady=chip_pad[1]
        )
        self._accuracy_chip.pack(side=tk.LEFT, padx=(0, self._m.px(6)))
        self._personality_chip = tk.Label(
            meta_row, text="", bg=BORDER, fg=MUTED, font=chip_font, padx=chip_pad[0], pady=chip_pad[1]
        )
        self._personality_chip.pack(side=tk.LEFT, padx=(0, self._m.px(6)))
        self._learning_chip = tk.Label(
            meta_row, text="", bg=BORDER, fg=MUTED, font=chip_font, padx=chip_pad[0], pady=chip_pad[1]
        )
        self._learning_chip.pack(side=tk.LEFT)

        self._desc_label = tk.Label(
            header,
            text="Choose an agent from the list to view its latest analysis.",
            bg="#152238",
            fg=MUTED,
            font=self._m.font(11 if self._embedded else 10),
            wraplength=self._m.px(720),
            justify=tk.LEFT,
            anchor="w",
        )
        self._desc_label.grid(row=2, column=0, sticky="ew", padx=self._m.px(12), pady=(0, self._m.px(10)))

        actions = tk.Frame(wrap, bg=PANEL)
        actions.grid(row=1, column=0, sticky="ew", pady=(0, self._m.px(8)))
        btn_pad = (0, self._m.px(4)) if self._embedded else (0, 6)
        self._btn_open_json = self._make_button(
            actions, "Open JSON", self._open_selected_json, variant="secondary", padx=btn_pad
        )
        if not self._embedded:
            self._make_button(actions, "Import JSON…", self._import_json, variant="secondary", padx=btn_pad)
        self._make_button(actions, "Output Folder", self._open_output_folder, variant="ghost", padx=btn_pad)
        if not self._embedded:
            self._make_button(actions, "Run Agent", self._run_selected, variant="accent", padx=btn_pad)
            self._make_button(actions, "Run All", self._run_all_agents, variant="primary", padx=btn_pad)
            self._make_button(
                actions, "Full Pipeline", self._run_predictor_pipeline, variant="secondary", padx=btn_pad
            )
            self._make_button(actions, "Dashboard", self._open_related_dashboard, variant="ghost")

        output_frame = tk.Frame(wrap, bg="#0d1424", highlightbackground=BORDER, highlightthickness=1)
        output_frame.grid(row=2, column=0, sticky="nsew")
        output_frame.rowconfigure(0, weight=1)
        output_frame.columnconfigure(0, weight=1)
        wrap.rowconfigure(2, weight=1)

        report_wrap = tk.WORD
        mono_size = 13 if self._embedded else 11
        self._output = tk.Text(
            output_frame,
            bg="#0d1424",
            fg=TEXT,
            insertbackground=TEXT,
            relief=tk.FLAT,
            font=self._m.mono(mono_size),
            wrap=report_wrap,
            spacing1=self._m.px(5),
            spacing2=self._m.px(3),
            spacing3=self._m.px(5),
            padx=self._m.px(14),
            pady=self._m.px(14),
            tabs=(self._m.px(200), self._m.px(360)),
        )
        title_font = self._m.font(14 if self._embedded else 13, "bold")
        section_font = self._m.font(12 if self._embedded else 11, "bold")
        body_font = self._m.font(11 if self._embedded else 10)
        self._output.tag_configure("title", foreground=TEXT, font=title_font)
        self._output.tag_configure("section", foreground=ACCENT2, font=section_font, spacing1=8)
        self._output.tag_configure("body", foreground=TEXT, font=body_font)
        self._output.tag_configure("muted", foreground=MUTED, font=body_font)
        self._output.tag_configure("positive", foreground=UP, font=body_font)
        self._output.tag_configure("negative", foreground=DOWN, font=body_font)

        out_yscroll = ttk.Scrollbar(output_frame, orient=tk.VERTICAL, command=self._output.yview)
        out_xscroll = ttk.Scrollbar(output_frame, orient=tk.HORIZONTAL, command=self._output.xview)
        self._output.configure(yscrollcommand=out_yscroll.set, xscrollcommand=out_xscroll.set)
        self._output.grid(row=0, column=0, sticky="nsew")
        out_yscroll.grid(row=0, column=1, sticky="ns")
        if not self._embedded:
            out_xscroll.grid(row=1, column=0, sticky="ew")

        wrap.bind("<Configure>", self._on_report_wrap_resize)

    def _on_report_wrap_resize(self, event: tk.Event) -> None:
        if event.width > 40:
            wrap_w = max(self._m.px(280), event.width - self._m.px(24))
            self._desc_label.configure(wraplength=wrap_w)
            try:
                self._output.configure(width=max(20, int(event.width / 8)))
            except tk.TclError:
                pass

    def _show_search_placeholder(self) -> None:
        if not self._search_var.get():
            self._search_entry.delete(0, tk.END)
            self._search_entry.insert(0, self._search_placeholder)
            self._search_entry.configure(fg=MUTED)

    def _on_search_focus_in(self, _event: tk.Event) -> None:
        if self._search_entry.get() == self._search_placeholder:
            self._search_entry.delete(0, tk.END)
            self._search_entry.configure(fg=TEXT)

    def _on_search_focus_out(self, _event: tk.Event) -> None:
        if not self._search_var.get().strip():
            self._show_search_placeholder()

    def _populate_agent_tree(self) -> None:
        categories: dict[str, str] = {}
        by_cat: dict[str, list[dict[str, str]]] = {}
        for agent in AGENT_CATALOG:
            by_cat.setdefault(agent["category"], []).append(agent)
        for agents in by_cat.values():
            agents.sort(key=agent_mtime, reverse=True)

        for cat, agents in sorted(by_cat.items()):
            icon = CATEGORY_ICONS.get(cat, "•")
            node = self._tree.insert("", tk.END, text=f"{icon}  {cat}", open=True, tags=("category",))
            categories[cat] = node
            for agent in agents:
                bucket, age_label, age_tag = agent_age_info(agent)
                acc_label = agent_accuracy_label(agent)
                item = self._tree.insert(
                    node,
                    tk.END,
                    text=f"  {agent['label']}",
                    values=(age_label, acc_label),
                    tags=("agent", agent["id"], age_tag),
                )
                self._agent_rows[agent["id"]] = item

        self._tree.tag_configure("category", foreground=MUTED)
        self._tree.tag_configure("fresh", foreground=UP)
        self._tree.tag_configure("stale", foreground=WARN)
        self._tree.tag_configure("old", foreground=DOWN)
        self._tree.tag_configure("none", foreground=MUTED)
        reapply_tree_sort(self._tree, ("#0", "status", "accuracy"), hierarchical=True)

    def _update_embedded_summary(self) -> None:
        if not self._embedded or not hasattr(self, "_embedded_summary"):
            return
        fresh, total = self.fresh_report_counts()
        with_data = sum(1 for agent in AGENT_CATALOG if agent_mtime(agent) > 0)
        self._embedded_summary.configure(
            text=f"{with_data} reports · {fresh}/{total} fresh · drag divider to resize · select an agent",
        )

    def _filter_agents(self) -> None:
        raw = self._search_var.get().strip()
        if raw == self._search_placeholder:
            raw = ""
        query = raw.lower()
        for agent in AGENT_CATALOG:
            item = self._agent_rows.get(agent["id"])
            if not item:
                continue
            hay = f"{agent['label']} {agent['id']} {agent['category']} {agent['desc']}".lower()
            parent = self._tree.parent(item)
            if not query or query in hay:
                self._tree.reattach(item, parent, tk.END)
            else:
                self._tree.detach(item)

    def _on_tree_select(self, _event: tk.Event | None = None) -> None:
        selection = self._tree.selection()
        if not selection:
            return
        item = selection[0]
        tags = self._tree.item(item, "tags")
        if "agent" not in tags:
            return
        agent_id = next((t for t in tags if t in self._agent_rows), None)
        if agent_id:
            self._select_agent(agent_id)
            return
        label = self._tree.item(item, "text").strip()
        for agent in AGENT_CATALOG:
            if agent["label"] == label:
                self._select_agent(agent["id"])
                break

    def _select_default_agent(self) -> None:
        if not AGENT_CATALOG:
            return
        def _rank(agent: dict[str, str]) -> tuple[float, float]:
            from agent_report_status import agent_accuracy_pct

            acc = agent_accuracy_pct(agent) or 0.0
            return acc, agent_mtime(agent)

        chosen = None
        fresh_agents = [a for a in AGENT_CATALOG if agent_status(a) == "Fresh"]
        if fresh_agents:
            chosen = max(fresh_agents, key=_rank)["id"]
        if chosen is None:
            ranked = sorted(AGENT_CATALOG, key=agent_mtime, reverse=True)
            if ranked and agent_mtime(ranked[0]) > 0:
                chosen = ranked[0]["id"]
            else:
                chosen = AGENT_CATALOG[0]["id"]
        item = self._agent_rows.get(chosen)
        if item:
            self._tree.selection_set(item)
            self._tree.focus(item)
            self._tree.see(item)
        self._select_agent(chosen)

    def _select_agent(self, agent_id: str) -> None:
        self._selected_id = agent_id
        agent = next((a for a in AGENT_CATALOG if a["id"] == agent_id), None)
        if not agent:
            return
        self._title_label.configure(text=agent["label"])
        self._desc_label.configure(text=agent["desc"])
        self._desc_label.grid()
        bucket, age_label, _ = agent_age_info(agent)
        status = agent_status(agent)
        self._status_badge.configure(
            text=f" {status} ",
            bg=STATUS_COLORS.get(status, MUTED),
            fg="#0a0e17" if status in ("Fresh", "Stale") else TEXT,
        )
        acc_label = agent_accuracy_label(agent)
        try:
            from agent_personality import personality_label

            pers_label = personality_label(agent["id"])
        except Exception:
            pers_label = ""
        if bucket == "none":
            self._updated_label.configure(text=" No report yet ", bg=BORDER, fg=MUTED)
            self._accuracy_chip.configure(text="", bg="#152238")
            self._personality_chip.configure(text="", bg="#152238")
            self._learning_chip.configure(text="", bg="#152238")
        else:
            self._updated_label.configure(text=f" Updated {age_label} ", bg=BORDER, fg=TEXT)
            if acc_label not in ("—", ""):
                acc_color = ACCENT2
                if acc_label.endswith("%"):
                    try:
                        pct = float(acc_label.rstrip("%"))
                        acc_color = UP if pct >= 65 else WARN if pct >= 50 else DOWN
                    except ValueError:
                        pass
                self._accuracy_chip.configure(text=f" Accuracy {acc_label} ", bg=BORDER, fg=acc_color)
            else:
                self._accuracy_chip.configure(text="", bg="#152238")
            if pers_label:
                self._personality_chip.configure(text=f" {pers_label} ", bg=BORDER, fg=ACCENT)
            else:
                self._personality_chip.configure(text="", bg="#152238")
            try:
                from agent_learning import learning_label

                learn_label = learning_label(agent["id"])
            except Exception:
                learn_label = ""
            if learn_label:
                learn_color = UP if "Confident" in learn_label else WARN if "Cautious" in learn_label else ACCENT2
                self._learning_chip.configure(text=f" {learn_label} ", bg=BORDER, fg=learn_color)
            else:
                self._learning_chip.configure(text="", bg="#152238")
        self._load_agent_output(agent)

    def _trim_report_header(self, text: str) -> str:
        """Drop duplicate title block — agent name already shown in the panel header."""
        lines = text.splitlines()
        if len(lines) < 3:
            return text
        if lines[1].strip().startswith("="):
            start = 2
            if start < len(lines) and lines[start].strip() == "":
                start += 1
            if start < len(lines) and lines[start].startswith("Tracked accuracy:"):
                start += 1
                if start < len(lines) and lines[start].strip() == "":
                    start += 1
            if start < len(lines) and lines[start].startswith("Personality:"):
                start += 1
                if start < len(lines) and lines[start].strip() == "":
                    start += 1
            if start < len(lines) and lines[start].startswith("Learning:"):
                start += 1
                if start < len(lines) and lines[start].strip() == "":
                    start += 1
            return "\n".join(lines[start:]).lstrip("\n")
        return text

    def _render_report_text(self, text: str) -> None:
        display = self._trim_report_header(text) if self._embedded else text
        self._output.delete("1.0", tk.END)
        self._output.insert(tk.END, display)
        for tag in ("title", "section", "body", "muted", "positive", "negative"):
            self._output.tag_remove(tag, "1.0", tk.END)

        if not self._embedded:
            first_line_end = self._output.index("1.0 lineend")
            if first_line_end != "1.0":
                self._output.tag_add("title", "1.0", first_line_end)

        section_names = (
            "Key metrics",
            "Market signals",
            "Recommendations",
            "Recent events",
            "Top movers",
            "Tracked accuracy",
            "Personality",
            "Learning",
        )
        for section in section_names:
            start = "1.0"
            while True:
                idx = self._output.search(section, start, tk.END)
                if not idx:
                    break
                end = f"{idx}+{len(section)}c"
                self._output.tag_add("section", idx, end)
                start = end

        line_count = int(self._output.index("end-1c").split(".")[0])
        for line_no in range(1, line_count + 1):
            line = self._output.get(f"{line_no}.0", f"{line_no}.0 lineend")
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("="):
                continue
            if not any(line.startswith(prefix) for prefix in ("  ", "•", "-", "Key ", "Market ", "Tracked ")):
                if len(stripped) > 40 and not stripped.endswith(":"):
                    self._output.tag_add("body", f"{line_no}.0", f"{line_no}.0 lineend")
            if line.startswith("  •") or line.startswith("  -"):
                self._output.tag_add("muted", f"{line_no}.0", f"{line_no}.0 lineend")
            if "+" in line and "%" in line and "BUY" not in line.upper():
                if any(token in line for token in ("+0.", "+1.", "+2.", "+3.", "+4.", "+5.")):
                    self._output.tag_add("positive", f"{line_no}.0", f"{line_no}.0 lineend")
            if "-" in line and "%" in line and "stop" not in line.lower():
                if any(token in line for token in ("-0.", "-1.", "-2.")):
                    self._output.tag_add("negative", f"{line_no}.0", f"{line_no}.0 lineend")

        self._output.see("1.0")

    def _load_agent_output(self, agent: dict[str, str]) -> None:
        path = OUTPUT / agent["output"]
        if not path.exists():
            self._render_report_text(
                "No report yet.\n\n"
                "Reports appear here automatically when E*TRADE Trader runs agents in the background.\n\n"
                f"Expected file:\n  {path.name}"
            )
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._render_report_text(format_report_summary(data))
        except Exception as exc:
            self._render_report_text(f"Could not read {path.name}: {exc}")

    def _set_status(self, text: str, color: str = ACCENT2) -> None:
        if self._embedded:
            if hasattr(self, "_embedded_summary"):
                self._embedded_summary.configure(
                    text=text,
                    fg=MUTED if color == ACCENT2 else color,
                )
                if color in (UP, DOWN, WARN):
                    try:
                        self.after(3500, self._update_embedded_summary)
                    except tk.TclError:
                        pass
            return
        if self._status_label is not None:
            self._status_label.configure(text=text, fg=TEXT)
        if self._status_dot is not None:
            self._status_dot.configure(fg=color)

    def _start_ui_queue_poller(self) -> None:
        self._poll_ui_queue()

    def _poll_ui_queue(self) -> None:
        try:
            while True:
                fn, args, kwargs = self._ui_queue.get_nowait()
                fn(*args, **kwargs)
        except queue.Empty:
            pass
        self._ui_poll_job = self.after(50, self._poll_ui_queue)

    def _schedule_ui(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        self._ui_queue.put((fn, args, kwargs))

    def _set_running(self, running: bool) -> None:
        self._running = running
        if self._embedded:
            return
        if running:
            self._progress.pack(side=tk.RIGHT)
            self._progress.start(12)
        else:
            self._progress.stop()
            self._progress.pack_forget()

    def _hydrate_agent_learning(self) -> None:
        try:
            from prediction_accuracy import sync_benchmark_to_accuracy_store

            sync_benchmark_to_accuracy_store()
        except Exception:
            pass

    def _apply_learning_patch(self, agent_id: str, output_name: str) -> None:
        try:
            from agent_learning import patch_agent_output_learning

            patch_agent_output_learning(OUTPUT / output_name, agent_id)
        except Exception:
            pass

    def _run_selected(self) -> None:
        if self._running or self._batch_running:
            return
        if not self._selected_id:
            return
        agent = next((a for a in AGENT_CATALOG if a["id"] == self._selected_id), None)
        if not agent:
            return
        self._set_running(True)
        self._set_status(f"Running {agent['label']}…", WARN)
        threading.Thread(target=self._agent_thread, args=(agent,), daemon=True).start()

    def _resolve_runner(self, agent_id: str):
        from agents.platform_catalog import resolve_runner

        return resolve_runner(agent_id, self._runners)

    def _apply_personality_patch(self, agent_id: str, output_name: str) -> None:
        try:
            from agent_personality import patch_agent_output_personality

            patch_agent_output_personality(OUTPUT / output_name, agent_id)
        except Exception:
            pass

    def _agent_thread(self, agent: dict[str, str]) -> None:
        try:
            runner = self._resolve_runner(agent["id"])
            if runner is None:
                raise KeyError(f"No runner registered for {agent['id']}")
            OUTPUT.mkdir(parents=True, exist_ok=True)
            runner(output=OUTPUT / agent["output"])
            self._apply_personality_patch(agent["id"], agent["output"])
            self._apply_learning_patch(agent["id"], agent["output"])
            self._schedule_ui(self._refresh_agent, agent["id"])
            self._schedule_ui(self._set_status, f"Complete — {agent['label']}", UP)
        except Exception as exc:
            self._schedule_ui(messagebox.showerror, "Agent Error", str(exc))
            self._schedule_ui(self._set_status, f"Failed: {exc}", DOWN)
        finally:
            self._schedule_ui(self._set_running, False)

    def _refresh_agent(self, agent_id: str) -> None:
        agent = next((a for a in AGENT_CATALOG if a["id"] == agent_id), None)
        if not agent:
            return
        item = self._agent_rows.get(agent_id)
        if item:
            _, age_label, age_tag = agent_age_info(agent)
            self._tree.item(item, values=(age_label, agent_accuracy_label(agent)))
            self._tree.item(item, tags=("agent", agent_id, age_tag))
        if self._selected_id == agent_id:
            self._select_agent(agent_id)
        self._update_embedded_summary()

    def _run_all_agents(self) -> None:
        if self._running or self._batch_running:
            return
        if not messagebox.askyesno(
            "Run All Agents",
            f"Run all {len(AGENT_CATALOG)} agents sequentially?\n\n"
            "This may take several minutes and requires network access.",
        ):
            return
        self._batch_running = True
        self._progress.pack(side=tk.RIGHT)
        self._progress.start(12)
        threading.Thread(target=self._batch_thread, daemon=True).start()

    def _batch_thread(self) -> None:
        ok = 0
        failures: list[str] = []
        OUTPUT.mkdir(parents=True, exist_ok=True)
        runnable = [a for a in AGENT_CATALOG if a["id"] != "market-predictor"]
        total = len(runnable)
        for index, agent in enumerate(runnable, start=1):
            self._schedule_ui(
                self._set_status,
                f"Batch {index}/{total}: {agent['label']}…",
                WARN,
            )
            runner = self._resolve_runner(agent["id"])
            if runner is None:
                failures.append(f"{agent['label']}: no runner")
                continue
            try:
                runner(output=OUTPUT / agent["output"])
                self._apply_personality_patch(agent["id"], agent["output"])
                self._apply_learning_patch(agent["id"], agent["output"])
                ok += 1
                self._schedule_ui(self._refresh_agent, agent["id"])
            except Exception as exc:
                failures.append(f"{agent['label']}: {exc}")

        msg = f"Batch complete — {ok}/{total} agents succeeded"
        if failures:
            preview = "\n".join(failures[:8])
            if len(failures) > 8:
                preview += f"\n…and {len(failures) - 8} more"
            self._schedule_ui(messagebox.showwarning, "Batch Warnings", f"{msg}\n\n{preview}")
        self._schedule_ui(self._set_status, msg, UP if ok == total else WARN)
        self._schedule_ui(self._batch_done)

    def _batch_done(self) -> None:
        self._batch_running = False
        self._progress.stop()
        self._progress.pack_forget()

    def _pipeline_backtest_note(self) -> str:
        try:
            from historical_simulation import pipeline_benchmark_config

            cfg = pipeline_benchmark_config()
            if cfg.get("enabled"):
                return (
                    f"\n\nIncludes walk-forward backtest "
                    f"({int(cfg['target_trials']):,} trials / {int(cfg['max_symbols']):,} symbols)."
                )
        except Exception:
            pass
        return ""

    def _run_predictor_pipeline(self) -> None:
        if self._running or self._batch_running:
            return
        backtest_note = self._pipeline_backtest_note()
        if not messagebox.askyesno(
            "Market Predictor Pipeline",
            "Run all platform agents, walk-forward backtest, then fuse into Market Predictor?"
            f"{backtest_note}\n\n"
            "This is the full ensemble pipeline (~8–20 min).",
        ):
            return
        self._batch_running = True
        self._progress.pack(side=tk.RIGHT)
        self._progress.start(12)
        threading.Thread(target=self._predictor_pipeline_thread, daemon=True).start()

    def _predictor_pipeline_thread(self) -> None:
        platform = [a for a in AGENT_CATALOG if a["id"] != "market-predictor"]
        total = len(platform)
        try:
            from strategy_engine import run_agent_pipeline

            def on_progress(msg: str) -> None:
                self._schedule_ui(self._set_status, msg, WARN)

            ok = run_agent_pipeline(self._runners, on_progress=on_progress, check_remote=False)
            for agent in AGENT_CATALOG:
                self._schedule_ui(self._refresh_agent, agent["id"])
            self._schedule_ui(self.refresh_agent_statuses)
            if self._selected_id:
                self._schedule_ui(self._select_agent, self._selected_id)
            self._schedule_ui(
                self._set_status,
                f"Pipeline complete — {ok}/{total} agents + backtest + predictor",
                UP if ok == total else WARN,
            )
        except Exception as exc:
            self._schedule_ui(messagebox.showerror, "Pipeline Error", str(exc))
            self._schedule_ui(self._set_status, f"Pipeline failed: {exc}", DOWN)
        finally:
            self._schedule_ui(self._batch_done)

    def _open_selected_json(self) -> None:
        agent = next((a for a in AGENT_CATALOG if a["id"] == self._selected_id), None)
        if not agent:
            return
        path = OUTPUT / agent["output"]
        if not path.exists():
            messagebox.showinfo("No Output", f"No report file yet.\n\nExpected: {path}")
            return
        subprocess.Popen(["notepad", str(path)])

    def _import_json(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title="Import JSON report",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialdir=str(OUTPUT if OUTPUT.exists() else ROOT),
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self._output.delete("1.0", tk.END)
            self._output.insert(tk.END, format_report_summary(data))
            self._set_status(f"Imported {Path(path).name}", ACCENT2)
        except Exception as exc:
            messagebox.showerror("Import Error", str(exc))

    def _open_related_dashboard(self) -> None:
        agent_id = self._selected_id or ""
        mapping = {
            "market-predictor": DASHBOARDS[0],
            "sales-analytics": DASHBOARDS[1],
            "events": DASHBOARDS[2],
        }
        dash = mapping.get(agent_id)
        if dash:
            self._open_dashboard(dash)
        else:
            self._open_dashboard(DASHBOARDS[0])

    def _open_dashboard(self, dash: dict[str, str]) -> None:
        html = ROOT / dash["file"]
        if not html.exists():
            messagebox.showwarning("Missing", f"{dash['file']} not found.")
            return
        try:
            if dash["module"] == "predictions":
                from dashboard_server import open_predictions_dashboard

                path = open_predictions_dashboard(ROOT)
            elif dash["module"] == "mobile":
                webbrowser.open(html.as_uri())
                path = str(html)
            else:
                webbrowser.open(html.as_uri())
                path = str(html)
            self._set_status(f"Opened {dash['label']}", ACCENT2)
        except Exception as exc:
            messagebox.showerror("Dashboard", str(exc))

    def _open_output_folder(self) -> None:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(OUTPUT)])

    def _open_market_predictor(self) -> None:
        try:
            from dashboard_server import open_predictions_dashboard

            open_predictions_dashboard(ROOT)
            self._set_status("Opened Predictions Dashboard", ACCENT2)
        except Exception as exc:
            messagebox.showwarning(
                "Market Predictor",
                "Predictions dashboard unavailable.\n\n"
                "Use Full Pipeline to refresh market_predictions.json.\n\n"
                f"{exc}",
            )

    def _sync_agents(self) -> None:
        if not messagebox.askyesno(
            "Sync GitHub",
            "Pull the latest platform code and agents from GitHub?\n\n"
            "This will:\n"
            "• Update changed repo files (agents, scripts, requirements)\n"
            "• Install/update Python dependencies\n"
            "• Run any newly added agents immediately\n"
            "• Re-run the full pipeline if existing agents were updated\n\n"
            "Your etrade_config.json, tokens, and output/ folder are not overwritten.",
        ):
            return
        self._set_status("Syncing from GitHub…", WARN)
        if not self._embedded:
            self._progress.pack(side=tk.RIGHT)
            self._progress.start(12)
        threading.Thread(target=self._sync_thread, daemon=True).start()

    def _sync_thread(self) -> None:
        from github_sync import format_sync_summary, sync_github_repository

        def progress(message: str) -> None:
            self._schedule_ui(self._set_status, message, WARN)

        try:
            result = sync_github_repository(on_progress=progress)
            self._schedule_ui(self.refresh_ui, select_latest=bool(result.new_packages))
            if result.ok and not result.errors:
                self._schedule_ui(self._set_status, "GitHub sync complete", UP)
                level = messagebox.showinfo
            else:
                self._schedule_ui(self._set_status, "GitHub sync finished with warnings", WARN)
                level = messagebox.showwarning
            self._schedule_ui(level, "Sync Complete", format_sync_summary(result))
        except Exception as exc:
            self._schedule_ui(messagebox.showerror, "Sync Error", str(exc))
            self._schedule_ui(self._set_status, f"Sync failed: {exc}", DOWN)
        finally:
            if not self._embedded:
                self._schedule_ui(self._progress.stop)
                self._schedule_ui(self._progress.pack_forget)

    def _start_mobile_server(self) -> None:
        bat = ROOT / "Start Mobile Server.bat"
        if bat.exists():
            subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(ROOT))
            self._set_status("Mobile API server starting…", ACCENT2)
        else:
            messagebox.showwarning("Missing", "Start Mobile Server.bat not found.")

    def _open_github(self) -> None:
        webbrowser.open("https://github.com/shaggychunxx-ui/Finance")

    def _show_about(self) -> None:
        messagebox.showinfo(
            "About Finance Agents",
            "Finance Agents Desktop v2.0\n\n"
            "Control panel for the Finance intelligence platform.\n"
            f"Repository: github.com/shaggychunxx-ui/Finance\n\n"
            f"{len(AGENT_CATALOG)} agents available\n"
            f"Output folder: {OUTPUT}\n\n"
            "Agent reports and trading signals update automatically via E*TRADE Trader.\n"
            "Select an agent in the sidebar to review its latest analysis.",
        )

    def fresh_report_counts(self) -> tuple[int, int]:
        return fresh_report_counts(AGENT_CATALOG)

    def refresh_agent_statuses(self) -> None:
        for agent in AGENT_CATALOG:
            self._refresh_agent(agent["id"])

    def refresh_ui(self, *, select_latest: bool = False) -> None:
        global AGENT_CATALOG
        AGENT_CATALOG = get_agent_catalog(refresh=True)
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._agent_rows.clear()
        self._populate_agent_tree()
        self._update_embedded_summary()
        if select_latest:
            self._select_default_agent()
        elif self._selected_id:
            self._select_agent(self._selected_id)


def main() -> int:
    if os.environ.get("FINANCE_AGENTS_STANDALONE") != "1":
        os.environ.setdefault("ETRADE_TAB", "agents")
        from etrade_trader_gui import main as etrade_main

        return etrade_main()
    try:
        app = FinanceAgentsApp()
        app._window.mainloop()
    except Exception as exc:
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Finance Agents", f"Failed to start:\n{exc}")
            root.destroy()
        except Exception:
            print(f"Failed to start: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())