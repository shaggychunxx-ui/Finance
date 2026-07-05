"""Shared Tkinter theme tokens, typography, and screen scaling."""

from __future__ import annotations

from typing import Literal

import tkinter as tk
from tkinter import ttk

WindowProfile = Literal["agents", "trader"]

BG = "#0a0e17"
PANEL = "#121a2b"
BORDER = "#1e2d4a"
TEXT = "#e8edf5"
MUTED = "#8b9cb8"
ACCENT = "#6c5ce7"
ACCENT2 = "#00cec9"
UP = "#00e676"
DOWN = "#ff5252"
WARN = "#ffd54f"

FONT = "Segoe UI"
MONO = "Consolas"
UI_FONT_MIN = 10
UI_FONT_BOOST = 1.12

TREE_ROW_ODD = "#0d1424"
TREE_ROW_EVEN = "#152238"
TREE_HEADING_BG = "#243352"
TREE_NUMERIC_COLS = frozenset({
    "current_pct", "target_pct", "current_usd", "target_usd", "drift",
    "qty", "price", "est_usd", "entry", "target", "stop",
})
TREE_CENTER_COLS = frozenset({"action", "status"})


class ScreenMetrics:
    def __init__(self, root: tk.Misc, *, window_profile: WindowProfile = "agents") -> None:
        self.screen_w = root.winfo_screenwidth()
        self.screen_h = root.winfo_screenheight()
        try:
            dpi = float(root.winfo_fpixels("1i"))
        except tk.TclError:
            dpi = 96.0
        dpi_scale = dpi / 96.0
        res_scale = min(self.screen_w / 1366, self.screen_h / 768)
        self.scale = max(0.72, min(1.35, res_scale * dpi_scale))

        if window_profile == "trader":
            self.win_w = max(1120, int(self.screen_w * 0.94))
            self.win_h = max(780, int(self.screen_h * 0.92))
            self.min_w = max(980, int(self.screen_w * 0.55))
            self.min_h = max(640, int(self.screen_h * 0.55))
        else:
            self.win_w = max(960, int(self.screen_w * 0.9))
            self.win_h = max(640, int(self.screen_h * 0.88))
            self.min_w = max(800, int(self.screen_w * 0.55))
            self.min_h = max(560, int(self.screen_h * 0.55))

    def px(self, value: int | float) -> int:
        return max(1, int(round(value * self.scale)))

    def _font_px(self, size: int | float, *, mono: bool = False) -> int:
        boost = 1.08 if mono else UI_FONT_BOOST
        return max(UI_FONT_MIN, self.px(float(size) * boost))

    def font(self, size: int | float, weight: str = "") -> tuple[str, int, str] | tuple[str, int]:
        px = self._font_px(size)
        return (FONT, px, weight) if weight else (FONT, px)

    def mono(self, size: int | float) -> tuple[str, int]:
        return (MONO, self._font_px(size, mono=True))


def configure_treeview_style(style: ttk.Style, metrics: ScreenMetrics, *, prefix: str) -> None:
    style.configure(
        f"{prefix}.Treeview",
        background=TREE_ROW_ODD,
        fieldbackground=TREE_ROW_ODD,
        foreground=TEXT,
        rowheight=metrics.px(38),
        font=metrics.font(11),
    )
    style.configure(
        f"{prefix}.Treeview.Heading",
        background=TREE_HEADING_BG,
        foreground=TEXT,
        font=metrics.font(11, "bold"),
        padding=(metrics.px(8), metrics.px(6)),
    )
    style.map(
        f"{prefix}.Treeview",
        background=[("selected", ACCENT)],
        foreground=[("selected", "#ffffff")],
    )