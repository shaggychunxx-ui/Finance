"""Reusable Treeview helpers for Finance desktop apps."""

from __future__ import annotations

import re
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

_AGE_RE = re.compile(r"^(\d+)\s*([mhd])\s*ago$", re.I)
_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


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
    if hasattr(tree, "_sort_col"):
        tree._sort_col = None  # type: ignore[attr-defined]
        tree._sort_reverse = False  # type: ignore[attr-defined]
        _refresh_sort_headings(tree)


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


def _parse_age_seconds(text: str) -> float | None:
    raw = (text or "").strip().lower()
    if not raw or raw in ("—", "?", "-"):
        return None
    if raw == "just now":
        return 0.0
    match = _AGE_RE.match(raw)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit == "m":
        return float(amount * 60)
    if unit == "h":
        return float(amount * 3600)
    return float(amount * 86400)


def _parse_accuracy_key(text: str) -> tuple[int, float, str]:
    raw = (text or "").strip().lower()
    if not raw or raw in ("—", "?", "-"):
        return (3, 0.0, raw)
    if raw.endswith("%"):
        nums = _NUM_RE.findall(raw)
        if nums:
            return (0, float(nums[0]), raw)
    if " tracking" in raw:
        nums = _NUM_RE.findall(raw)
        return (1, float(nums[0]) if nums else 0.0, raw)
    if " scored" in raw:
        nums = _NUM_RE.findall(raw)
        return (2, float(nums[0]) if nums else 0.0, raw)
    nums = _NUM_RE.findall(raw)
    if nums:
        return (0, float(nums[0]), raw)
    return (4, 0.0, raw)


def sort_key_for_cell(text: str, column: str) -> tuple[Any, ...]:
    """Build a comparable key: numeric values first, then alphabetical fallback."""
    raw = (text or "").strip()
    if column == "status":
        age = _parse_age_seconds(raw)
        if age is not None:
            return (0, age, raw.lower())
        return (1, raw.lower())

    if column == "accuracy":
        return _parse_accuracy_key(raw)

    if column in TREE_NUMERIC_COLS or any(ch in raw for ch in "$%"):
        cleaned = raw.replace(",", "").replace("$", "").replace("%", "").replace("+", "").strip()
        if cleaned.startswith("(") and cleaned.endswith(")"):
            cleaned = f"-{cleaned[1:-1]}"
        nums = _NUM_RE.findall(cleaned)
        if nums:
            return (0, float(nums[0]), raw.lower())

    if not raw or raw in ("—", "?", "-"):
        return (1, "")

    nums = _NUM_RE.findall(raw.replace(",", ""))
    if nums and column in {"qty", "quantity"}:
        return (0, float(nums[0]), raw.lower())

    return (1, raw.lower())


def _value_column_index(column: str, columns: tuple[str, ...]) -> int | None:
    if column == "#0":
        return None
    data_cols = [col for col in columns if col != "#0"]
    try:
        return data_cols.index(column)
    except ValueError:
        return None


def _cell_text(tree: ttk.Treeview, item: str, column: str, columns: tuple[str, ...]) -> str:
    if column == "#0":
        return str(tree.item(item, "text") or "")
    index = _value_column_index(column, columns)
    if index is None:
        return ""
    values = tree.item(item, "values") or ()
    if index >= len(values):
        return ""
    return str(values[index])


def _sort_tree_children(
    tree: ttk.Treeview,
    parent: str,
    column: str,
    columns: tuple[str, ...],
    *,
    reverse: bool,
) -> None:
    children = list(tree.get_children(parent))
    if len(children) < 2:
        return
    children.sort(
        key=lambda item: sort_key_for_cell(_cell_text(tree, item, column, columns), column),
        reverse=reverse,
    )
    for index, item in enumerate(children):
        tree.move(item, parent, index)


def refresh_tree_zebra(tree: ttk.Treeview, parent: str = "") -> None:
    for index, item in enumerate(tree.get_children(parent)):
        tags = tuple(tree.item(item, "tags") or ())
        stripe = "even" if index % 2 else "odd"
        other = tuple(tag for tag in tags if tag not in ("odd", "even"))
        if stripe not in other:
            tree.item(item, tags=(stripe, *other))
        refresh_tree_zebra(tree, item)


def _refresh_sort_headings(tree: ttk.Treeview) -> None:
    titles: dict[str, str] = getattr(tree, "_heading_titles", {})
    sort_col: str | None = getattr(tree, "_sort_col", None)
    reverse: bool = getattr(tree, "_sort_reverse", False)
    for col, title in titles.items():
        label = title
        if col == sort_col:
            label = f"{title} {'▼' if reverse else '▲'}"
        anchor = column_anchor(col) if col != "#0" else "w"
        tree.heading(col, text=label, anchor=anchor)


def _toggle_tree_sort(
    tree: ttk.Treeview,
    column: str,
    columns: tuple[str, ...],
    *,
    hierarchical: bool = False,
) -> None:
    current = getattr(tree, "_sort_col", None)
    reverse = getattr(tree, "_sort_reverse", False)
    if current == column:
        reverse = not reverse
    else:
        reverse = False
    tree._sort_col = column  # type: ignore[attr-defined]
    tree._sort_reverse = reverse  # type: ignore[attr-defined]

    if hierarchical:
        for parent in tree.get_children(""):
            _sort_tree_children(tree, parent, column, columns, reverse=reverse)
    else:
        _sort_tree_children(tree, "", column, columns, reverse=reverse)
        refresh_tree_zebra(tree)

    _refresh_sort_headings(tree)


def reapply_tree_sort(
    tree: ttk.Treeview,
    columns: tuple[str, ...],
    *,
    hierarchical: bool = False,
) -> None:
    column = getattr(tree, "_sort_col", None)
    if not column:
        return
    reverse = getattr(tree, "_sort_reverse", False)
    if hierarchical:
        for parent in tree.get_children(""):
            _sort_tree_children(tree, parent, column, columns, reverse=reverse)
    else:
        _sort_tree_children(tree, "", column, columns, reverse=reverse)
        refresh_tree_zebra(tree)


def bind_tree_sort(
    tree: ttk.Treeview,
    columns: tuple[str, ...],
    headings: dict[str, tuple[str, int]],
    *,
    hierarchical: bool = False,
) -> None:
    tree._heading_titles = {col: headings[col][0] for col in columns}  # type: ignore[attr-defined]
    tree._sort_col = None  # type: ignore[attr-defined]
    tree._sort_reverse = False  # type: ignore[attr-defined]

    for col in columns:
        anchor = column_anchor(col) if col != "#0" else "w"
        tree.heading(
            col,
            text=headings[col][0],
            anchor=anchor,
            command=lambda c=col: _toggle_tree_sort(tree, c, columns, hierarchical=hierarchical),
        )


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
    bind_tree_sort(tree, columns, headings)

    yscroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
    xscroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=tree.xview)
    tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
    tree.grid(row=0, column=0, sticky="nsew")
    yscroll.grid(row=0, column=1, sticky="ns")
    xscroll.grid(row=1, column=0, sticky="ew")
    return tree