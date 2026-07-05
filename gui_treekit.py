"""Reusable Treeview helpers for Finance desktop apps."""

from __future__ import annotations

from typing import Any

import tkinter as tk
from tkinter import ttk

from gui_theme import (
    DOWN,
    PANEL,
    TEXT,
    TREE_CENTER_COLS,
    TREE_NUMERIC_COLS,
    TREE_ROW_EVEN,
    TREE_ROW_ODD,
    UP,
    WARN,
    ScreenMetrics,
)


def column_anchor(column: str) -> str:
    if column in TREE_CENTER_COLS:
        return "center"
    if column in TREE_NUMERIC_COLS:
        return "e"
    return "w"


def configure_data_tree_tags(tree: ttk.Treeview, *, trading: bool = False) -> None:
    tree.tag_configure("odd", background=TREE_ROW_ODD, foreground=TEXT)
    tree.tag_configure("even", background=TREE_ROW_EVEN, foreground=TEXT)
    if trading:
        tree.tag_configure("buy", foreground=UP)
        tree.tag_configure("sell", foreground=DOWN)
        tree.tag_configure("drift_high", foreground=WARN)


def tree_clear(tree: ttk.Treeview) -> None:
    for item in tree.get_children():
        tree.delete(item)
    tree._zebra_i = 0  # type: ignore[attr-defined]


def tree_insert(
    tree: ttk.Treeview,
    values: tuple[Any, ...],
    *,
    extra_tags: tuple[str, ...] = (),
) -> None:
    row = getattr(tree, "_zebra_i", 0)
    stripe = "even" if row % 2 else "odd"
    tree.insert("", tk.END, values=values, tags=(stripe, *extra_tags))
    tree._zebra_i = row + 1  # type: ignore[attr-defined]


def make_data_tree(
    parent: tk.Misc,
    columns: tuple[str, ...],
    headings: dict[str, tuple[str, int]],
    metrics: ScreenMetrics,
    *,
    style: str,
    panel_bg: str = PANEL,
    compact_pad: bool = False,
) -> ttk.Treeview:
    pad = metrics.px(6 if compact_pad else 8)
    frame = tk.Frame(parent, bg=panel_bg)
    frame.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad)
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)

    tree = ttk.Treeview(frame, columns=columns, show="headings", style=style)
    last_col = columns[-1]
    for col in columns:
        title, width = headings[col]
        anchor = column_anchor(col)
        tree.heading(col, text=title, anchor=anchor)
        tree.column(
            col,
            width=metrics.px(width),
            minwidth=metrics.px(max(48, width // 2)),
            stretch=col == last_col,
            anchor=anchor,
        )

    configure_data_tree_tags(tree, trading=True)
    tree._zebra_i = 0  # type: ignore[attr-defined]

    yscroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
    xscroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=tree.xview)
    tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
    tree.grid(row=0, column=0, sticky="nsew")
    yscroll.grid(row=0, column=1, sticky="ns")
    xscroll.grid(row=1, column=0, sticky="ew")
    return tree