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
from agent_report_status import agent_age_info, agent_mtime, agent_status, fresh_report_counts
from app_paths import ICON_FILE, OUTPUT, ROOT, ensure_app_path
from finance_runners import load_finance_runners
from gui_theme import (
    ACCENT,
    ACCENT2,
    BG,
    BORDER,
    DOWN,
    MUTED,
    PANEL,
    TEXT,
    UP,
    WARN,
    ScreenMetrics,
    configure_treeview_style,
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
        if not embedded:
            self._window.title("Finance Agents")
            self._window.configure(bg=BG)
            self._window.geometry(f"{self._m.win_w}x{self._m.win_h}")
            self._window.minsize(self._m.min_w, self._m.min_h)
            self._center_window()
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

        if not embedded:
            self._set_icon()
            self._build_menu()
        self._build_styles()
        self._build_ui()
        self._start_ui_queue_poller()
        self._select_default_agent()

    def _pad(self) -> int:
        return self._m.px(8 if self._embedded else 16)

    def _center_window(self) -> None:
        x = max(0, (self._m.screen_w - self._m.win_w) // 2)
        y = max(0, (self._m.screen_h - self._m.win_h) // 2)
        self._window.geometry(f"{self._m.win_w}x{self._m.win_h}+{x}+{y}")

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
        style.configure(
            "Finance.TFrame",
            background=PANEL,
        )
        style.configure(
            "Finance.TLabel",
            background=PANEL,
            foreground=TEXT,
            font=self._m.font(11),
        )
        style.configure(
            "FinanceTitle.TLabel",
            background=PANEL,
            foreground=TEXT,
            font=self._m.font(15, "bold"),
        )
        style.configure(
            "FinanceMuted.TLabel",
            background=PANEL,
            foreground=MUTED,
            font=self._m.font(10),
        )
        style.configure(
            "Finance.TButton",
            font=self._m.font(11),
            padding=(self._m.px(12), self._m.px(8)),
        )
        configure_treeview_style(style, self._m, prefix="Finance")
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
            "primary": (ACCENT, "#ffffff", "#5a4bd6", self._m.font(10, "bold")),
            "accent": (ACCENT2, "#0a0e17", "#00b5b0", self._m.font(10, "bold")),
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
                font=self._m.font(10),
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
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        sidebar = tk.Frame(body, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, self._m.px(6 if self._embedded else 10)))
        sidebar.configure(width=self._m.px(290 if self._embedded else 260))
        sidebar.pack_propagate(False)

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
            columns=("status",),
            show="tree headings",
            style="Finance.Treeview",
            selectmode="browse",
        )
        self._tree.heading("#0", text="Agent", anchor="w")
        self._tree.heading("status", text="Updated", anchor="center")
        self._tree.column("#0", width=self._m.px(210 if self._embedded else 200), stretch=True)
        self._tree.column("status", width=self._m.px(72), stretch=False, anchor="center")
        scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=scroll.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
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
        main = tk.Frame(body, bg=main_bg)
        main.grid(row=0, column=1, sticky="nsew")
        main.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)

        self._report_panel = tk.Frame(main, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        self._report_panel.grid(row=0, column=0, sticky="nsew")
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
        pad = self._m.px(8 if self._embedded else 14)
        wrap = tk.Frame(self._report_panel, bg=PANEL)
        wrap.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad)
        wrap.columnconfigure(0, weight=1)

        title_row = tk.Frame(wrap, bg=PANEL)
        title_row.grid(row=0, column=0, sticky="ew", pady=(0, self._m.px(4)))
        title_size = 14 if self._embedded else 16
        self._title_label = tk.Label(
            title_row, text="Select an agent", bg=PANEL, fg=TEXT, font=self._m.font(title_size, "bold")
        )
        self._title_label.pack(side=tk.LEFT)
        self._status_badge = tk.Label(
            title_row, text="", bg=BORDER, fg=MUTED, font=self._m.font(8), padx=6, pady=2
        )
        self._status_badge.pack(side=tk.RIGHT)
        self._updated_label = tk.Label(
            title_row, text="", bg=PANEL, fg=MUTED, font=self._m.font(9)
        )
        self._updated_label.pack(side=tk.RIGHT, padx=(0, self._m.px(8)))

        self._desc_label = tk.Label(
            wrap,
            text="Choose an agent from the sidebar to view its latest analysis.",
            bg=PANEL,
            fg=MUTED,
            font=self._m.font(10 if self._embedded else 10),
            wraplength=self._m.px(900 if self._embedded else 680),
            justify=tk.LEFT,
        )
        self._desc_label.grid(row=1, column=0, sticky="ew", pady=(0, self._m.px(6)))

        actions = tk.Frame(wrap, bg=PANEL)
        actions.grid(row=2, column=0, sticky="ew", pady=(0, self._m.px(6)))
        self._btn_open_json = self._make_button(
            actions, "Open JSON", self._open_selected_json, variant="secondary", padx=(0, 6)
        )
        if not self._embedded:
            self._make_button(actions, "Import JSON…", self._import_json, variant="secondary", padx=(0, 6))
        self._make_button(actions, "Output Folder", self._open_output_folder, variant="ghost", padx=(0, 6))
        if not self._embedded:
            self._make_button(actions, "Run Agent", self._run_selected, variant="accent", padx=(0, 6))
            self._make_button(actions, "Run All", self._run_all_agents, variant="primary", padx=(0, 6))
            self._make_button(
                actions, "Full Pipeline", self._run_predictor_pipeline, variant="secondary", padx=(0, 6)
            )
            self._make_button(actions, "Dashboard", self._open_related_dashboard, variant="ghost")

        output_frame = tk.Frame(wrap, bg="#0d1424", highlightbackground=BORDER, highlightthickness=1)
        output_frame.grid(row=3, column=0, sticky="nsew")
        output_frame.rowconfigure(0, weight=1)
        output_frame.columnconfigure(0, weight=1)
        wrap.rowconfigure(3, weight=1)

        report_wrap = tk.WORD if self._embedded else tk.NONE
        self._output = tk.Text(
            output_frame,
            bg="#0d1424",
            fg=TEXT,
            insertbackground=TEXT,
            relief=tk.FLAT,
            font=self._m.mono(12 if self._embedded else 11),
            wrap=report_wrap,
            spacing1=4,
            spacing2=2,
            spacing3=4,
            padx=self._m.px(12),
            pady=self._m.px(12),
            tabs=(self._m.px(180), self._m.px(320)),
        )
        self._output.tag_configure("title", foreground=TEXT, font=self._m.font(13, "bold"))
        self._output.tag_configure("section", foreground=ACCENT2, font=self._m.font(11, "bold"))
        self._output.tag_configure("muted", foreground=MUTED)
        self._output.tag_configure("positive", foreground=UP)
        self._output.tag_configure("negative", foreground=DOWN)

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
            self._desc_label.configure(wraplength=max(self._m.px(240), event.width - self._m.px(8)))

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
                item = self._tree.insert(
                    node,
                    tk.END,
                    text=f"  {agent['label']}",
                    values=(age_label,),
                    tags=("agent", agent["id"], age_tag),
                )
                self._agent_rows[agent["id"]] = item

        self._tree.tag_configure("category", foreground=MUTED)
        self._tree.tag_configure("fresh", foreground=UP)
        self._tree.tag_configure("stale", foreground=WARN)
        self._tree.tag_configure("old", foreground=DOWN)
        self._tree.tag_configure("none", foreground=MUTED)

    def _update_embedded_summary(self) -> None:
        if not self._embedded or not hasattr(self, "_embedded_summary"):
            return
        fresh, total = self.fresh_report_counts()
        with_data = sum(1 for agent in AGENT_CATALOG if agent_mtime(agent) > 0)
        self._embedded_summary.configure(
            text=f"{with_data} reports on disk · {fresh} fresh · select an agent to review",
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
        preferred = ("market-predictor", "finance", "markets")
        chosen = None
        for agent_id in preferred:
            agent = next((a for a in AGENT_CATALOG if a["id"] == agent_id), None)
            if agent and agent_status(agent) == "Fresh":
                chosen = agent["id"]
                break
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
        bucket, age_label, _ = agent_age_info(agent)
        status = agent_status(agent)
        self._status_badge.configure(
            text=f"  {status}  ",
            bg=STATUS_COLORS.get(status, MUTED),
            fg="#0a0e17" if status in ("Fresh", "Stale") else TEXT,
        )
        if bucket == "none":
            self._updated_label.configure(text="No report yet")
        else:
            self._updated_label.configure(text=f"Updated {age_label}")
        self._load_agent_output(agent)

    def _render_report_text(self, text: str) -> None:
        self._output.delete("1.0", tk.END)
        self._output.insert(tk.END, text)
        self._output.tag_remove("title", "1.0", tk.END)
        self._output.tag_remove("section", "1.0", tk.END)
        self._output.tag_remove("muted", "1.0", tk.END)
        self._output.tag_remove("positive", "1.0", tk.END)
        self._output.tag_remove("negative", "1.0", tk.END)

        first_line_end = self._output.index("1.0 lineend")
        if first_line_end != "1.0":
            self._output.tag_add("title", "1.0", first_line_end)

        section_names = (
            "Key metrics",
            "Market signals",
            "Recommendations",
            "Recent events",
            "Top movers",
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
            if line.startswith("  •"):
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

    def _run_selected(self) -> None:
        if self._running or not self._selected_id:
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

    def _agent_thread(self, agent: dict[str, str]) -> None:
        try:
            runner = self._resolve_runner(agent["id"])
            if runner is None:
                raise KeyError(f"No runner registered for {agent['id']}")
            OUTPUT.mkdir(parents=True, exist_ok=True)
            runner(output=OUTPUT / agent["output"])
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
            self._tree.item(item, values=(age_label,))
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

    def _run_predictor_pipeline(self) -> None:
        if self._running or self._batch_running:
            return
        if not messagebox.askyesno(
            "Market Predictor Pipeline",
            "Run all platform agents, then fuse into Market Predictor?\n\n"
            "This is the full ensemble pipeline (~5–12 min).",
        ):
            return
        self._batch_running = True
        self._progress.pack(side=tk.RIGHT)
        self._progress.start(12)
        threading.Thread(target=self._predictor_pipeline_thread, daemon=True).start()

    def _predictor_pipeline_thread(self) -> None:
        ok = 0
        failures: list[str] = []
        platform = [a for a in AGENT_CATALOG if a["id"] != "market-predictor"]
        total = len(platform)
        OUTPUT.mkdir(parents=True, exist_ok=True)
        for index, agent in enumerate(platform, start=1):
            self._schedule_ui(self._set_status, f"Pipeline {index}/{total}: {agent['label']}…", WARN)
            runner = self._resolve_runner(agent["id"])
            if runner is None:
                failures.append(agent["label"])
                continue
            try:
                runner(output=OUTPUT / agent["output"])
                ok += 1
                self._schedule_ui(self._refresh_agent, agent["id"])
            except Exception as exc:
                failures.append(f"{agent['label']}: {exc}")

        try:
            self._schedule_ui(self._set_status, "Fusing Market Predictor…", WARN)
            from agents.market_predictor import run_market_predictor_analysis

            run_market_predictor_analysis(output=OUTPUT / "market_predictions.json")
            self._schedule_ui(self._refresh_agent, "market-predictor")
            self._schedule_ui(
                self._set_status,
                f"Pipeline complete — {ok}/{total} agents + predictor",
                UP,
            )
        except Exception as exc:
            self._schedule_ui(messagebox.showerror, "Predictor Error", str(exc))
            self._schedule_ui(self._set_status, f"Predictor failed: {exc}", DOWN)
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
        launcher = ROOT / "Launch Market Predictor.vbs"
        gui = ROOT / "market_predictor_gui.py"
        pyw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
        if launcher.exists():
            subprocess.Popen(["wscript.exe", str(launcher)], cwd=str(ROOT))
        elif pyw.exists() and gui.exists():
            subprocess.Popen([str(pyw), str(gui)], cwd=str(ROOT))
        else:
            messagebox.showwarning("Missing", "Market Predictor launcher not found.")

    def _sync_agents(self) -> None:
        self._set_status("Syncing agents from GitHub…", WARN)
        threading.Thread(target=self._sync_thread, daemon=True).start()

    def _sync_thread(self) -> None:
        try:
            fetch = subprocess.run(
                ["git", "fetch", "origin", "main"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if fetch.returncode != 0:
                raise RuntimeError(fetch.stderr or fetch.stdout or "git fetch failed")
            checkout = subprocess.run(
                ["git", "checkout", "origin/main", "--", "agents/"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if checkout.returncode != 0:
                raise RuntimeError(checkout.stderr or checkout.stdout or "git checkout failed")
            cache = OUTPUT / "agent_catalog_cache.json"
            if cache.exists():
                cache.unlink()
            self._schedule_ui(self.refresh_ui)
            self._schedule_ui(self._set_status, "Agent sync complete", UP)
            self._schedule_ui(
                messagebox.showinfo,
                "Sync Complete",
                "Agents updated from https://github.com/shaggychunxx-ui/Finance/tree/main/agents",
            )
        except Exception as exc:
            self._schedule_ui(messagebox.showerror, "Sync Error", str(exc))
            self._schedule_ui(self._set_status, f"Sync failed: {exc}", DOWN)

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
        AGENT_CATALOG = get_agent_catalog(refresh=False)
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