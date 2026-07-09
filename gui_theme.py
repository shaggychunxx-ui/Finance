"""Shared Tkinter theme tokens, typography, and screen scaling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import tkinter as tk
from tkinter import ttk

WindowProfile = Literal["agents", "trader"]

THEME_KEYS: tuple[str, ...] = (
    "BG",
    "PANEL",
    "CARD_BG",
    "CARD_ACTIVE",
    "BORDER",
    "TEXT",
    "MUTED",
    "ACCENT",
    "ACCENT2",
    "UP",
    "DOWN",
    "WARN",
    "TREE_ROW_ODD",
    "TREE_ROW_EVEN",
    "TREE_HEADING_BG",
    "BTN_PRIMARY_FG",
    "BTN_PRIMARY_HOVER",
    "BTN_ACCENT_HOVER",
    "BTN_DANGER_HOVER",
)

PALETTES: dict[str, dict[str, str]] = {
    "midnight": {
        "label": "Midnight",
        "BG": "#0d0814",
        "PANEL": "#160f22",
        "CARD_BG": "#110a1a",
        "CARD_ACTIVE": "#261a3d",
        "BORDER": "#3b2a5c",
        "TEXT": "#f0e8f8",
        "MUTED": "#9a8ab5",
        "ACCENT": "#9333ea",
        "ACCENT2": "#d946ef",
        "UP": "#4ade80",
        "DOWN": "#fb7185",
        "WARN": "#facc15",
        "TREE_ROW_ODD": "#110a1a",
        "TREE_ROW_EVEN": "#1a1230",
        "TREE_HEADING_BG": "#3b2a5c",
        "BTN_PRIMARY_FG": "#ffffff",
        "BTN_PRIMARY_HOVER": "#7e22ce",
        "BTN_ACCENT_HOVER": "#c026d3",
        "BTN_DANGER_HOVER": "#e11d48",
    },
    "ocean": {
        "label": "Ocean",
        "BG": "#061018",
        "PANEL": "#0c1a2a",
        "CARD_BG": "#081420",
        "CARD_ACTIVE": "#14304a",
        "BORDER": "#1a3a5c",
        "TEXT": "#e6f0fa",
        "MUTED": "#7fa3c4",
        "ACCENT": "#3b82f6",
        "ACCENT2": "#22d3ee",
        "UP": "#34d399",
        "DOWN": "#f87171",
        "WARN": "#fbbf24",
        "TREE_ROW_ODD": "#081420",
        "TREE_ROW_EVEN": "#102638",
        "TREE_HEADING_BG": "#1a3a5c",
        "BTN_PRIMARY_FG": "#ffffff",
        "BTN_PRIMARY_HOVER": "#2563eb",
        "BTN_ACCENT_HOVER": "#06b6d4",
        "BTN_DANGER_HOVER": "#dc2626",
    },
    "ember": {
        "label": "Ember",
        "BG": "#120c0a",
        "PANEL": "#1c1410",
        "CARD_BG": "#16100c",
        "CARD_ACTIVE": "#2a1c14",
        "BORDER": "#3d2a1f",
        "TEXT": "#f5ebe4",
        "MUTED": "#b39a88",
        "ACCENT": "#f97316",
        "ACCENT2": "#fbbf24",
        "UP": "#4ade80",
        "DOWN": "#fb7185",
        "WARN": "#fde047",
        "TREE_ROW_ODD": "#16100c",
        "TREE_ROW_EVEN": "#221812",
        "TREE_HEADING_BG": "#3d2a1f",
        "BTN_PRIMARY_FG": "#ffffff",
        "BTN_PRIMARY_HOVER": "#ea580c",
        "BTN_ACCENT_HOVER": "#d97706",
        "BTN_DANGER_HOVER": "#e11d48",
    },
    "forest": {
        "label": "Forest",
        "BG": "#08120e",
        "PANEL": "#0f1f18",
        "CARD_BG": "#0b1812",
        "CARD_ACTIVE": "#163026",
        "BORDER": "#1f4a3a",
        "TEXT": "#e5f4ec",
        "MUTED": "#86a897",
        "ACCENT": "#10b981",
        "ACCENT2": "#6ee7b7",
        "UP": "#22c55e",
        "DOWN": "#ef4444",
        "WARN": "#eab308",
        "TREE_ROW_ODD": "#0b1812",
        "TREE_ROW_EVEN": "#122820",
        "TREE_HEADING_BG": "#1f4a3a",
        "BTN_PRIMARY_FG": "#ffffff",
        "BTN_PRIMARY_HOVER": "#059669",
        "BTN_ACCENT_HOVER": "#34d399",
        "BTN_DANGER_HOVER": "#dc2626",
    },
    "slate": {
        "label": "Slate",
        "BG": "#111318",
        "PANEL": "#1a1f28",
        "CARD_BG": "#141820",
        "CARD_ACTIVE": "#252c38",
        "BORDER": "#313a4a",
        "TEXT": "#eef1f6",
        "MUTED": "#9aa3b5",
        "ACCENT": "#64748b",
        "ACCENT2": "#94a3b8",
        "UP": "#2dd4bf",
        "DOWN": "#f472b6",
        "WARN": "#fcd34d",
        "TREE_ROW_ODD": "#141820",
        "TREE_ROW_EVEN": "#1c222c",
        "TREE_HEADING_BG": "#313a4a",
        "BTN_PRIMARY_FG": "#ffffff",
        "BTN_PRIMARY_HOVER": "#475569",
        "BTN_ACCENT_HOVER": "#7c8aa0",
        "BTN_DANGER_HOVER": "#db2777",
    },
}

DEFAULT_PALETTE = "midnight"
_current_palette_name = DEFAULT_PALETTE
UI_PREFS_PATH = Path(__file__).resolve().parent / "ui_prefs.json"

BG = "#0d0814"
PANEL = "#160f22"
CARD_BG = "#110a1a"
CARD_ACTIVE = "#261a3d"
BORDER = "#3b2a5c"
TEXT = "#f0e8f8"
MUTED = "#9a8ab5"
ACCENT = "#9333ea"
ACCENT2 = "#d946ef"
UP = "#4ade80"
DOWN = "#fb7185"
WARN = "#facc15"
BTN_PRIMARY_FG = "#ffffff"
BTN_PRIMARY_HOVER = "#7e22ce"
BTN_ACCENT_HOVER = "#c026d3"
BTN_DANGER_HOVER = "#e11d48"

FONT = "Segoe UI"
MONO = "Consolas"
UI_FONT_MIN = 10
UI_FONT_BOOST = 1.12

TREE_ROW_ODD = "#110a1a"
TREE_ROW_EVEN = "#1a1230"
TREE_HEADING_BG = "#3b2a5c"
TREE_NUMERIC_COLS = frozenset({
    "current_pct", "target_pct", "current_usd", "target_usd", "drift",
    "qty", "price", "est_usd", "entry", "target", "stop",
    "total", "buying_power", "gain_amt", "gain_pct", "value", "pnl",
    "realized", "wins", "losses", "win_rate", "trades",
})
TREE_CENTER_COLS = frozenset({"action", "status", "mode", "source"})

_TK_COLOR_ATTRS = (
    "bg",
    "fg",
    "activebackground",
    "activeforeground",
    "highlightbackground",
    "highlightcolor",
    "insertbackground",
    "selectbackground",
    "selectforeground",
    "readonlybackground",
    "disabledbackground",
    "disabledforeground",
)


def _normalize_color(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in ("#fff", "white"):
        return "#ffffff"
    return text


def _apply_tokens(tokens: dict[str, str]) -> None:
    module = globals()
    for key in THEME_KEYS:
        if key in tokens:
            module[key] = tokens[key]


def apply_palette(name: str) -> str:
    """Switch the active palette; returns the palette id actually applied."""
    global _current_palette_name
    palette_id = str(name or "").strip().lower()
    if palette_id not in PALETTES:
        palette_id = DEFAULT_PALETTE
    _current_palette_name = palette_id
    _apply_tokens(PALETTES[palette_id])
    return palette_id


def current_palette_name() -> str:
    return _current_palette_name


def palette_choices() -> list[tuple[str, str]]:
    return [(key, PALETTES[key]["label"]) for key in PALETTES]


def palette_preview(name: str) -> dict[str, str]:
    palette_id = str(name or "").strip().lower()
    return dict(PALETTES.get(palette_id, PALETTES[DEFAULT_PALETTE]))


def build_color_remap(old_palette: str, new_palette: str) -> dict[str, str]:
    old = palette_preview(old_palette)
    new = palette_preview(new_palette)
    remap: dict[str, str] = {}
    for key in THEME_KEYS:
        old_color = _normalize_color(old.get(key, ""))
        new_color = new.get(key, "")
        if old_color and new_color and old_color != _normalize_color(new_color):
            remap[old_color] = new_color
    remap["#fff"] = BTN_PRIMARY_FG
    remap["#ffffff"] = BTN_PRIMARY_FG
    return remap


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_palette_from_prefs(path: Path | None = None) -> str:
    prefs_path = path or UI_PREFS_PATH
    data = _load_json(prefs_path) or {}
    palette = data.get("color_palette")
    if not palette and prefs_path != UI_PREFS_PATH:
        return apply_palette(DEFAULT_PALETTE)
    if not palette:
        etrade_config = prefs_path.parent / "etrade_config.json"
        raw = _load_json(etrade_config) or {}
        ui = raw.get("ui")
        if isinstance(ui, dict):
            palette = ui.get("color_palette")
    return apply_palette(str(palette or DEFAULT_PALETTE))


def save_palette_to_prefs(name: str, path: Path | None = None) -> str:
    palette_id = apply_palette(name)
    prefs_path = path or UI_PREFS_PATH
    data = _load_json(prefs_path) or {}
    data["color_palette"] = palette_id
    _write_json(prefs_path, data)
    return palette_id


def load_ui_layout(app_key: str, path: Path | None = None) -> dict[str, Any]:
    """Return saved window/pane layout for an app section."""
    prefs_path = path or UI_PREFS_PATH
    data = _load_json(prefs_path) or {}
    layout = data.get("layout")
    if not isinstance(layout, dict):
        return {}
    section = layout.get(app_key)
    return dict(section) if isinstance(section, dict) else {}


def save_ui_layout(app_key: str, patch: dict[str, Any], path: Path | None = None) -> None:
    """Merge layout fields for an app section into ui_prefs.json."""
    if not patch:
        return
    prefs_path = path or UI_PREFS_PATH
    data = _load_json(prefs_path) or {}
    layout = data.get("layout")
    if not isinstance(layout, dict):
        layout = {}
        data["layout"] = layout
    section = layout.get(app_key)
    if not isinstance(section, dict):
        section = {}
    section.update(patch)
    layout[app_key] = section
    _write_json(prefs_path, data)


def pane_sash_ratio(paned: tk.PanedWindow, index: int = 0) -> float | None:
    """Return sash position as a 0–1 ratio along the paned window axis."""
    try:
        orient = str(paned.cget("orient"))
        if orient == str(tk.HORIZONTAL):
            total = max(int(paned.winfo_width()), 1)
            x, _y = paned.sash_coord(index)
            return max(0.05, min(0.95, x / total))
        total = max(int(paned.winfo_height()), 1)
        _x, y = paned.sash_coord(index)
        return max(0.05, min(0.95, y / total))
    except (tk.TclError, ZeroDivisionError, TypeError, ValueError):
        return None


def place_pane_ratio(
    paned: tk.PanedWindow,
    ratio: float,
    *,
    index: int = 0,
    min_total: int = 320,
) -> None:
    """Place a paned sash using a saved ratio."""
    try:
        ratio = max(0.05, min(0.95, float(ratio)))
        orient = str(paned.cget("orient"))
        if orient == str(tk.HORIZONTAL):
            total = max(int(paned.winfo_width()), int(paned.winfo_reqwidth()), min_total)
            paned.sash_place(index, int(total * ratio), 0)
        else:
            total = max(int(paned.winfo_height()), int(paned.winfo_reqheight()), min_total)
            paned.sash_place(index, 0, int(total * ratio))
    except (tk.TclError, TypeError, ValueError):
        pass


def sync_module_globals(module: Any) -> None:
    """Copy current theme tokens into another module namespace."""
    for key in THEME_KEYS:
        module.__dict__[key] = globals()[key]


def recolor_widget_tree(widget: tk.Misc, color_map: dict[str, str]) -> None:
    if not color_map:
        return
    for attr in _TK_COLOR_ATTRS:
        try:
            current = widget.cget(attr)
        except tk.TclError:
            continue
        if not isinstance(current, str) or not current:
            continue
        replacement = color_map.get(_normalize_color(current))
        if replacement:
            try:
                widget.configure(**{attr: replacement})
            except tk.TclError:
                pass
    for child in widget.winfo_children():
        recolor_widget_tree(child, color_map)


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
        foreground=[("selected", BTN_PRIMARY_FG)],
    )


def configure_trader_notebooks(style: ttk.Style, metrics: ScreenMetrics) -> None:
    """Main app tabs + compact nested Trades sub-tabs."""
    tab_pad = (metrics.px(16), metrics.px(9))
    style.configure("Trader.TNotebook", background=BG, borderwidth=0, tabmargins=(2, 4, 2, 0))
    style.configure(
        "Trader.TNotebook.Tab",
        background=PANEL,
        foreground=MUTED,
        padding=tab_pad,
        font=metrics.font(11, "bold"),
    )
    style.map(
        "Trader.TNotebook.Tab",
        background=[("selected", CARD_ACTIVE)],
        foreground=[("selected", TEXT)],
    )

    sub_pad = (metrics.px(11), metrics.px(7))
    style.configure("Trader.Trades.TNotebook", background=PANEL, borderwidth=0, tabmargins=(0, 2, 0, 0))
    style.configure(
        "Trader.Trades.TNotebook.Tab",
        background=CARD_BG,
        foreground=MUTED,
        padding=sub_pad,
        font=metrics.font(10),
    )
    style.map(
        "Trader.Trades.TNotebook.Tab",
        background=[("selected", CARD_ACTIVE)],
        foreground=[("selected", ACCENT2)],
    )

    style.configure(
        "Trader.TCombobox",
        fieldbackground=CARD_BG,
        background=CARD_BG,
        foreground=TEXT,
        arrowcolor=MUTED,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        font=metrics.font(9),
    )
    style.map(
        "Trader.TCombobox",
        fieldbackground=[("readonly", CARD_BG)],
        foreground=[("readonly", TEXT)],
    )
    style.configure(
        "Trader.Vertical.TScrollbar",
        background=BORDER,
        troughcolor=CARD_BG,
        bordercolor=BORDER,
        arrowcolor=MUTED,
    )
    style.configure(
        "Trader.Horizontal.TScrollbar",
        background=BORDER,
        troughcolor=CARD_BG,
        bordercolor=BORDER,
        arrowcolor=MUTED,
    )
    style.configure("Trader.Horizontal.TProgressbar", troughcolor=BORDER, background=ACCENT2)


def refresh_trader_theme(root: tk.Misc, style: ttk.Style, metrics: ScreenMetrics, *, color_map: dict[str, str]) -> None:
    configure_treeview_style(style, metrics, prefix="Trader")
    configure_trader_notebooks(style, metrics)
    recolor_widget_tree(root, color_map)
    from gui_treekit import refresh_tree_tags_in_widget

    refresh_tree_tags_in_widget(root, trading=True)


def configure_finance_styles(style: ttk.Style, metrics: ScreenMetrics, *, embedded: bool) -> None:
    style.configure("Finance.TFrame", background=PANEL)
    style.configure("Finance.TLabel", background=PANEL, foreground=TEXT, font=metrics.font(11))
    style.configure("FinanceTitle.TLabel", background=PANEL, foreground=TEXT, font=metrics.font(15, "bold"))
    style.configure("FinanceMuted.TLabel", background=PANEL, foreground=MUTED, font=metrics.font(10))
    style.configure("Finance.TButton", font=metrics.font(11), padding=(metrics.px(12), metrics.px(8)))
    tree_row = metrics.px(44 if embedded else 38)
    tree_font = metrics.font(12 if embedded else 11)
    style.configure(
        "Finance.Treeview",
        background=TREE_ROW_ODD,
        fieldbackground=TREE_ROW_ODD,
        foreground=TEXT,
        rowheight=tree_row,
        font=tree_font,
    )
    style.configure(
        "Finance.Treeview.Heading",
        background=TREE_HEADING_BG,
        foreground=TEXT,
        font=metrics.font(11, "bold"),
        padding=(metrics.px(8), metrics.px(7)),
    )
    style.map(
        "Finance.Treeview",
        background=[("selected", ACCENT)],
        foreground=[("selected", BTN_PRIMARY_FG)],
    )


apply_palette(DEFAULT_PALETTE)