"""Account balance equity curve for the Balance & gains tab."""

from __future__ import annotations

import tkinter as tk
from datetime import datetime, timedelta, timezone
from typing import Callable

from gui_theme import ACCENT2, BORDER, CARD_ACTIVE, CARD_BG, DOWN, MUTED, TEXT, UP

RANGE_OPTIONS: tuple[tuple[str, int | None], ...] = (
    ("Open", None),
    ("1W", 7),
    ("1M", 30),
    ("3M", 90),
    ("6M", 180),
    ("1Y", 365),
)

METRIC_OPTIONS: tuple[tuple[str, str], ...] = (
    ("balance", "Balance"),
    ("cash", "Buying power"),
)


def range_days_for(key: str) -> int | None:
    for label, days in RANGE_OPTIONS:
        if label == key:
            return days
    return None


def points_for_account(points: list[dict], account_id_key: str = "") -> list[dict]:
    """Keep rows for the active account; fall back to all rows when unscoped."""
    rows = [row for row in (points or []) if isinstance(row, dict)]
    key = str(account_id_key or "").strip()
    if not key:
        return rows
    scoped = [row for row in rows if str(row.get("account_id_key") or "").strip() == key]
    return scoped if scoped else rows


def parse_opened_at(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def resolve_opening_balance_for_account(
    account_id_key: str,
    points: list[dict],
    *,
    accounts_meta: dict | None = None,
) -> float | None:
    key = str(account_id_key or "").strip()
    if key and isinstance(accounts_meta, dict):
        meta = accounts_meta.get(key)
        if isinstance(meta, dict) and meta.get("opening_balance") is not None:
            try:
                return float(meta["opening_balance"])
            except (TypeError, ValueError):
                pass
    scoped = points_for_account(points, key)
    if scoped:
        try:
            return float(scoped[0].get("total_account_value"))
        except (TypeError, ValueError):
            pass
    return None


def resolve_opened_at_for_account(
    account_id_key: str,
    points: list[dict],
    *,
    config_selected: dict | None = None,
    accounts_meta: dict | None = None,
) -> datetime | None:
    """Prefer stored open date over the first balance snapshot."""
    key = str(account_id_key or "").strip()
    candidates: list[str | datetime | None] = []
    if key and isinstance(accounts_meta, dict):
        meta = accounts_meta.get(key)
        if isinstance(meta, dict):
            candidates.append(meta.get("opened_at"))
    if key and isinstance(config_selected, dict) and str(config_selected.get("account_id_key") or "").strip() == key:
        candidates.append(config_selected.get("account_opened_at"))
    for candidate in candidates:
        if (parsed := parse_opened_at(candidate)) is not None:
            return parsed
    return account_open_at(points)


def inject_account_open_anchor(
    rows: list[dict],
    opened_at: datetime,
    *,
    opening_balance: float | None = None,
) -> list[dict]:
    """Add a start-of-account point when tracking began after the real open date."""
    if not rows:
        return rows
    stamps = [
        ts
        for row in rows
        if (ts := AccountGrowthChart._parse_at(str(row.get("at", "")))) is not None
    ]
    if not stamps:
        return rows
    first_ts = min(stamps)
    if opened_at >= first_ts:
        return rows
    first_row = min(rows, key=lambda row: str(row.get("at", "")))
    anchor_at = opened_at.replace(hour=0, minute=0, second=0, microsecond=0)
    anchor = {
        "at": anchor_at.isoformat(),
        "total_account_value": opening_balance if opening_balance is not None else first_row.get("total_account_value"),
        "cash_buying_power": first_row.get("cash_buying_power"),
        "account_id_key": first_row.get("account_id_key"),
        "source": "account_open_anchor",
    }
    return [anchor, *rows]


def account_open_at(
    points: list[dict],
    *,
    opened_at: str | datetime | None = None,
) -> datetime | None:
    parsed = parse_opened_at(opened_at)
    if parsed is not None:
        return parsed
    stamps = [
        ts
        for row in points
        if (ts := AccountGrowthChart._parse_at(str(row.get("at", "")))) is not None
    ]
    return min(stamps) if stamps else None


def filter_point_rows(
    points: list[dict],
    range_key: str,
    *,
    account_id_key: str = "",
    account_opened_at: str | datetime | None = None,
    opening_balance: float | None = None,
) -> list[dict]:
    """Return rows from account open through the selected lookback window."""
    scoped = points_for_account(points, account_id_key)
    if not scoped:
        return []

    open_ts = resolve_opened_at_for_account(
        account_id_key,
        scoped,
        accounts_meta=None,
        config_selected={"account_opened_at": account_opened_at, "account_id_key": account_id_key}
        if account_opened_at
        else None,
    )
    if open_ts is not None:
        scoped = inject_account_open_anchor(scoped, open_ts, opening_balance=opening_balance)
    days = range_days_for(range_key)
    if days is None:
        return list(scoped)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    if open_ts is not None and open_ts > cutoff:
        cutoff = open_ts

    filtered: list[dict] = []
    for row in scoped:
        ts = AccountGrowthChart._parse_at(str(row.get("at", "")))
        if ts is not None and ts >= cutoff:
            filtered.append(row)
    return filtered if filtered else list(scoped)


def compress_chart_points(
    points: list[tuple[str, float]],
    *,
    min_flat_interval_hours: float = 6.0,
) -> list[tuple[str, float]]:
    """Collapse duplicate-value bursts so the chart shows real moves, not refresh noise."""
    if len(points) <= 2:
        return list(points)

    compressed: list[tuple[str, float]] = [points[0]]
    last_kept_ts = AccountGrowthChart._parse_at(points[0][0])
    last_val = points[0][1]
    min_delta = max(6.0, min_flat_interval_hours) * 3600.0

    for at, val in points[1:]:
        ts = AccountGrowthChart._parse_at(at)
        if val != last_val:
            compressed.append((at, val))
            last_val = val
            last_kept_ts = ts
            continue
        if ts is None or last_kept_ts is None:
            continue
        if (ts - last_kept_ts).total_seconds() >= min_delta:
            compressed.append((at, val))
            last_kept_ts = ts

    if compressed[-1] != points[-1]:
        compressed.append(points[-1])
    return compressed


class AccountGrowthChart(tk.Frame):
    """Line chart of account value over time with selectable lookback range."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        width: int = 640,
        height: int = 160,
        bg: str = CARD_BG,
        font: tuple[str, int] | tuple[str, int, str] = ("Segoe UI", 8),
        default_range: str = "Open",
        default_metric: str = "balance",
        on_range_change: Callable[[str], None] | None = None,
        on_metric_change: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent, bg=bg)
        self._bg = bg
        self._font = font
        self._width = width
        self._height = height
        self._raw_rows: list[dict] = []
        self._all_points: list[tuple[str, float]] = []
        self._points: list[tuple[str, float]] = []
        self._baseline: float | None = None
        self._range_key = default_range if any(k == default_range for k, _ in RANGE_OPTIONS) else "Open"
        self._metric_key = default_metric if any(k == default_metric for k, _ in METRIC_OPTIONS) else "balance"
        self._account_id_key = ""
        self._account_open_ts: datetime | None = None
        self._account_open_value: float | None = None
        self._on_range_change = on_range_change
        self._on_metric_change = on_metric_change
        self._range_buttons: dict[str, tk.Button] = {}
        self._metric_buttons: dict[str, tk.Button] = {}

        head = tk.Frame(self, bg=bg)
        head.pack(fill=tk.X, padx=self._pad(8), pady=(self._pad(6), 0))
        tk.Label(head, text="Equity curve", bg=bg, fg=TEXT, font=self._title_font(), anchor="w").pack(
            side=tk.LEFT,
        )
        self._stats = tk.Label(head, text="", bg=bg, fg=MUTED, font=font, anchor="e")
        self._stats.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(self._pad(8), 0))

        metric_row = tk.Frame(self, bg=bg)
        metric_row.pack(fill=tk.X, padx=self._pad(8), pady=(self._pad(4), 0))
        tk.Label(metric_row, text="Metric", bg=bg, fg=MUTED, font=font, anchor="w").pack(side=tk.LEFT)
        metric_wrap = tk.Frame(metric_row, bg=bg)
        metric_wrap.pack(side=tk.RIGHT)
        for key, label in METRIC_OPTIONS:
            btn = self._make_chip(metric_wrap, label, lambda k=key: self.set_metric(k))
            self._metric_buttons[key] = btn

        range_row = tk.Frame(self, bg=bg)
        range_row.pack(fill=tk.X, padx=self._pad(8), pady=(self._pad(4), 0))
        tk.Label(range_row, text="Range", bg=bg, fg=MUTED, font=font, anchor="w").pack(side=tk.LEFT)
        btn_wrap = tk.Frame(range_row, bg=bg)
        btn_wrap.pack(side=tk.RIGHT)
        for label, _days in RANGE_OPTIONS:
            btn = self._make_chip(btn_wrap, label, lambda key=label: self.set_range(key))
            self._range_buttons[label] = btn
        self._sync_range_buttons()
        self._sync_metric_buttons()

        self._canvas = tk.Canvas(self, width=width, height=height, bg=bg, highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True, padx=self._pad(6), pady=(self._pad(4), self._pad(8)))
        self._last_size: tuple[int, int] | None = None
        self._canvas.bind("<Configure>", self._on_resize)

        self._placeholder = tk.Label(self, text="No balance history yet", bg=bg, fg=MUTED, font=font)
        self.show_placeholder()

    @property
    def range_key(self) -> str:
        return self._range_key

    @property
    def metric_key(self) -> str:
        return self._metric_key

    def _make_chip(self, parent: tk.Misc, text: str, command: Callable[[], None]) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=CARD_BG,
            fg=MUTED,
            activebackground=CARD_ACTIVE,
            activeforeground=TEXT,
            relief=tk.FLAT,
            font=self._font,
            padx=self._pad(8),
            pady=self._pad(2),
            cursor="hand2",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=BORDER,
        )

    @staticmethod
    def _pad(value: int) -> int:
        return max(1, value)

    def _title_font(self) -> tuple[str, int, str]:
        if len(self._font) >= 3:
            family, size, weight = self._font[0], int(self._font[1]), str(self._font[2])
            return (family, size + 2, weight)
        family, size = self._font[0], int(self._font[1])
        return (family, size + 2, "bold")

    @staticmethod
    def _parse_at(value: str) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    def _range_days(self) -> int | None:
        for label, days in RANGE_OPTIONS:
            if label == self._range_key:
                return days
        return 30

    def _metric_label(self) -> str:
        for key, label in METRIC_OPTIONS:
            if key == self._metric_key:
                return label
        return "Balance"

    def _sync_range_buttons(self) -> None:
        for label, btn in self._range_buttons.items():
            active = label == self._range_key
            btn.configure(bg=CARD_ACTIVE if active else CARD_BG, fg=TEXT if active else MUTED)
            btn.pack(side=tk.LEFT, padx=(self._pad(3), 0))

    def _sync_metric_buttons(self) -> None:
        for key, btn in self._metric_buttons.items():
            active = key == self._metric_key
            btn.configure(bg=CARD_ACTIVE if active else CARD_BG, fg=TEXT if active else MUTED)
            btn.pack(side=tk.LEFT, padx=(self._pad(3), 0))

    def set_range(self, range_key: str) -> None:
        if range_key not in self._range_buttons:
            return
        self._range_key = range_key
        self._sync_range_buttons()
        self._apply_range()
        if self._on_range_change:
            self._on_range_change(range_key)

    def set_metric(self, metric_key: str) -> None:
        if metric_key not in self._metric_buttons:
            return
        self._metric_key = metric_key
        self._sync_metric_buttons()
        self._rebuild_series()
        if self._on_metric_change:
            self._on_metric_change(metric_key)

    def _value_from_row(self, row: dict) -> float | None:
        if self._metric_key == "cash":
            value = row.get("cash_buying_power")
        else:
            value = row.get("total_account_value")
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _rebuild_series(self) -> None:
        parsed: list[tuple[str, float]] = []
        for row in self._raw_rows:
            value = self._value_from_row(row)
            if value is None:
                continue
            parsed.append((str(row.get("at", "")), value))
        parsed.sort(key=lambda item: item[0])
        self._all_points = parsed
        self._account_open_value = parsed[0][1] if parsed else None
        if self._metric_key == "balance" and self._account_open_value is not None:
            if self._baseline is None:
                self._baseline = self._account_open_value
        if not self._all_points:
            self.show_placeholder(f"No {self._metric_label().lower()} history yet")
            return
        self._apply_range()

    def _apply_range(self) -> None:
        filtered = self._filter_points(self._all_points)
        self._points = compress_chart_points(filtered)
        if not self._points:
            if self._all_points:
                self._points = compress_chart_points(self._all_points)
            else:
                self.show_placeholder()
                return
        self._placeholder.place_forget()
        self._update_stats()
        self._draw()

    def _filter_points(self, points: list[tuple[str, float]]) -> list[tuple[str, float]]:
        if not points:
            return []
        days = self._range_days()
        if days is None:
            return list(points)

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        if self._account_open_ts is not None and self._account_open_ts > cutoff:
            cutoff = self._account_open_ts
        filtered = [
            (at, val)
            for at, val in points
            if (ts := self._parse_at(at)) is not None and ts >= cutoff
        ]
        return filtered if filtered else list(points)

    def _update_stats(self) -> None:
        if not self._points:
            self._stats.configure(text="")
            return
        open_val = self._account_open_value if self._account_open_value is not None else self._points[0][1]
        first = self._points[0][1]
        last = self._points[-1][1]
        delta = last - open_val
        pct = (delta / open_val * 100) if open_val else 0.0
        sign = "+" if delta >= 0 else ""
        color = UP if delta >= 0 else DOWN
        flat_note = " · flat" if abs(delta) < 0.01 else ""
        open_label = ""
        if self._account_open_ts is not None:
            open_label = f" · since {self._account_open_ts.strftime('%b %d')}"
        self._stats.configure(
            text=(
                f"{self._range_key} · {self._metric_label()} · {len(self._points)} pts · "
                f"${open_val:,.2f} → ${last:,.2f} ({sign}{pct:.2f}%){open_label}{flat_note}"
            ),
            fg=color if abs(delta) >= 0.01 else MUTED,
        )

    def apply_theme(self) -> None:
        import sys

        from gui_theme import sync_module_globals

        sync_module_globals(sys.modules[__name__])
        self._bg = CARD_BG
        self._sync_range_buttons()
        self._sync_metric_buttons()
        if self._points:
            self._draw()

    def show_placeholder(self, message: str = "No balance history yet") -> None:
        self._raw_rows = []
        self._all_points = []
        self._points = []
        self._baseline = None
        self._stats.configure(text="")
        self._canvas.delete("all")
        self._placeholder.configure(text=message)
        self._placeholder.place(relx=0.5, rely=0.58, anchor=tk.CENTER)

    def load_points(
        self,
        points: list[dict],
        *,
        baseline: float | None = None,
        range_key: str | None = None,
        account_id_key: str = "",
        account_opened_at: str | datetime | None = None,
        accounts_meta: dict | None = None,
        config_selected: dict | None = None,
    ) -> None:
        self._account_id_key = str(account_id_key or "").strip()
        scoped = points_for_account(
            [row for row in (points or []) if isinstance(row, dict)],
            self._account_id_key,
        )
        self._account_open_ts = resolve_opened_at_for_account(
            self._account_id_key,
            scoped,
            config_selected=config_selected,
            accounts_meta=accounts_meta,
        )
        if self._account_open_ts is None and account_opened_at:
            self._account_open_ts = parse_opened_at(account_opened_at)
        opening_balance = resolve_opening_balance_for_account(
            self._account_id_key,
            scoped,
            accounts_meta=accounts_meta,
        )
        if self._account_open_ts is not None:
            scoped = inject_account_open_anchor(
                scoped,
                self._account_open_ts,
                opening_balance=opening_balance,
            )
        self._raw_rows = scoped
        if self._metric_key == "balance":
            self._baseline = baseline if baseline is not None else opening_balance
        else:
            self._baseline = None
        if range_key:
            self._range_key = range_key
            self._sync_range_buttons()
        if not self._raw_rows:
            self.show_placeholder()
            return
        self._rebuild_series()

    def _on_resize(self, event: tk.Event) -> None:
        size = (int(event.width), int(event.height))
        if size[0] < 40 or size[1] < 40 or size == self._last_size:
            return
        self._last_size = size
        if self._points:
            self._draw()

    @staticmethod
    def _format_axis_date(value: str) -> str:
        ts = AccountGrowthChart._parse_at(value)
        if ts is None:
            return value[:10] if value else ""
        if ts.hour or ts.minute:
            return ts.strftime("%b %d %H:%M")
        return ts.strftime("%b %d")

    def _y_bounds(self, values: list[float]) -> tuple[float, float, bool]:
        y_min = min(values)
        y_max = max(values)
        if self._baseline is not None and self._metric_key == "balance":
            y_min = min(y_min, float(self._baseline))
            y_max = max(y_max, float(self._baseline))
        center = (y_max + y_min) / 2.0
        raw_span = y_max - y_min
        is_flat = raw_span < max(0.01, abs(center) * 0.0005)

        if is_flat:
            half = max(abs(center) * 0.03, 1.0, center * 0.02 if center else 1.0)
            return center - half, center + half, True

        pad = max(raw_span * 0.15, abs(center) * 0.005, 0.25)
        return y_min - pad, y_max + pad, False

    def _draw(self) -> None:
        canvas = self._canvas
        canvas.delete("all")
        w = max(120, int(canvas.winfo_width() or self._width))
        h = max(80, int(canvas.winfo_height() or self._height))
        pad_l, pad_r, pad_t, pad_b = 52, 14, 12, 30
        plot_w = max(10, w - pad_l - pad_r)
        plot_h = max(10, h - pad_t - pad_b)

        if not self._points:
            return

        values = [v for _, v in self._points]
        y_min, y_max, is_flat = self._y_bounds(values)
        span = max(y_max - y_min, 0.01)

        def y_pos(val: float) -> float:
            return pad_t + plot_h * (1.0 - (val - y_min) / span)

        canvas.create_rectangle(pad_l, pad_t, pad_l + plot_w, pad_t + plot_h, outline=BORDER, width=1, fill=self._bg)

        for i in range(1, 4):
            gy = pad_t + plot_h * i / 4
            canvas.create_line(pad_l, gy, pad_l + plot_w, gy, fill=BORDER, dash=(2, 6))

        open_value = self._account_open_value if self._account_open_value is not None else self._baseline
        if open_value is not None and self._metric_key == "balance":
            oy = y_pos(float(open_value))
            if pad_t <= oy <= pad_t + plot_h:
                canvas.create_line(pad_l, oy, pad_l + plot_w, oy, fill=MUTED, dash=(5, 4))
                canvas.create_text(
                    pad_l + plot_w - 2,
                    oy - 8,
                    text="account open",
                    anchor="e",
                    fill=MUTED,
                    font=self._font,
                )

        coords: list[float] = []
        n = len(self._points)
        if n == 1:
            x = pad_l + plot_w / 2
            y = y_pos(values[0])
            coords.extend([x, y, x, y])
        else:
            for i, (_, val) in enumerate(self._points):
                x = pad_l + (plot_w * i / (n - 1))
                y = y_pos(val)
                coords.extend([x, y])

        line_color = UP if values[-1] >= values[0] else DOWN
        if is_flat:
            line_color = MUTED

        if len(coords) >= 4:
            canvas.create_line(*coords, fill=line_color, width=2, smooth=False)
            lx, ly = coords[-2], coords[-1]
            canvas.create_oval(lx - 4, ly - 4, lx + 4, ly + 4, fill=line_color, outline=TEXT, width=1)

        canvas.create_text(pad_l - 6, y_pos(y_max), text=f"${y_max:,.2f}", anchor="e", fill=MUTED, font=self._font)
        canvas.create_text(pad_l - 6, y_pos(y_min), text=f"${y_min:,.2f}", anchor="e", fill=MUTED, font=self._font)

        start_label = self._format_axis_date(self._points[0][0])
        end_label = self._format_axis_date(self._points[-1][0])
        first_ts = self._parse_at(self._points[0][0])
        if self._account_open_ts and first_ts == self._account_open_ts:
            start_label = f"Open · {start_label}"
        canvas.create_text(pad_l, pad_t + plot_h + 14, text=start_label, anchor="w", fill=MUTED, font=self._font)
        canvas.create_text(
            pad_l + plot_w,
            pad_t + plot_h + 14,
            text=end_label,
            anchor="e",
            fill=ACCENT2,
            font=self._font,
        )

        if is_flat:
            canvas.create_text(
                pad_l + plot_w / 2,
                pad_t + plot_h / 2,
                text=f"No change in range (${values[-1]:,.2f}) — try Buying power",
                anchor=tk.CENTER,
                fill=MUTED,
                font=self._font,
            )