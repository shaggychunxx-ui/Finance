"""Ten-day candlestick chart for the Trades tab detail panel."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests
import tkinter as tk

CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Finance/1.0)"}

_cache: dict[str, tuple[float, list["CandleBar"]]] = {}
CACHE_TTL_SECONDS = 300.0
CHART_DAYS = 10
CHART_WIDTH_FRACTION = 0.45


@dataclass(frozen=True)
class CandleBar:
    date_label: str
    open: float
    high: float
    low: float
    close: float
    volume: float


def fetch_candle_bars(symbol: str, *, days: int = CHART_DAYS) -> list[CandleBar]:
    """Return the last *days* daily OHLCV bars for *symbol*."""
    sym = (symbol or "").strip().upper().replace(".", "-")
    if not sym:
        return []

    now = time.time()
    cached = _cache.get(sym)
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    bars: list[CandleBar] = []
    try:
        resp = requests.get(
            CHART_API.format(symbol=sym),
            params={"interval": "1d", "range": "1mo"},
            headers=HEADERS,
            timeout=20,
        )
        if resp.status_code == 429:
            time.sleep(2)
            resp = requests.get(
                CHART_API.format(symbol=sym),
                params={"interval": "1d", "range": "1mo"},
                headers=HEADERS,
                timeout=20,
            )
        resp.raise_for_status()
        result = (resp.json().get("chart") or {}).get("result") or []
        if not result:
            _cache[sym] = (now, bars)
            return bars

        timestamps = result[0].get("timestamp") or []
        quote = ((result[0].get("indicators") or {}).get("quote") or [{}])[0]
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []

        rows: list[tuple[int, float, float, float, float, float]] = []
        for ts, o, h, l, c, v in zip(timestamps, opens, highs, lows, closes, volumes):
            if o is None or h is None or l is None or c is None:
                continue
            rows.append((int(ts), float(o), float(h), float(l), float(c), float(v or 0)))

        for ts, o, h, l, c, v in rows[-days:]:
            label = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m/%d")
            bars.append(CandleBar(date_label=label, open=o, high=h, low=l, close=c, volume=v))
    except Exception:
        bars = []

    _cache[sym] = (now, bars)
    return bars


class CandleChartWidget(tk.Frame):
    """Tkinter canvas candlestick chart."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        width: int = 340,
        height: int = 200,
        bg: str = "#0d1424",
        up_color: str = "#00e676",
        down_color: str = "#ff5252",
        text_color: str = "#8b9cb8",
        grid_color: str = "#1e2d4a",
        font: tuple[str, int] = ("Segoe UI", 8),
    ) -> None:
        super().__init__(master, bg=bg)
        self._width = width
        self._height = height
        self._bg = bg
        self._up = up_color
        self._down = down_color
        self._text = text_color
        self._grid = grid_color
        self._font = font
        self._symbol = ""
        self._bars: list[CandleBar] = []

        self._title = tk.Label(self, text="10-day chart", bg=bg, fg=text_color, font=("Segoe UI", 9, "bold"), anchor="w")
        self._title.pack(fill=tk.X, padx=6, pady=(4, 0))

        self._stats = tk.Label(self, text="", bg=bg, fg=text_color, font=font, anchor="w", justify=tk.LEFT)
        self._stats.pack(fill=tk.X, padx=6, pady=(0, 2))

        self._canvas = tk.Canvas(self, width=width, height=height, bg=bg, highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))
        self._last_canvas_size: tuple[int, int] | None = None
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        self._placeholder = tk.Label(
            self,
            text="Select a symbol to load chart",
            bg=bg,
            fg=text_color,
            font=font,
        )

    def show_placeholder(self, message: str = "Select a symbol to load chart") -> None:
        self._symbol = ""
        self._bars = []
        self._title.configure(text="10-day chart")
        self._stats.configure(text="")
        self._canvas.delete("all")
        self._placeholder.configure(text=message)
        self._placeholder.place(relx=0.5, rely=0.55, anchor=tk.CENTER)

    def load_symbol(
        self,
        symbol: str,
        *,
        bars: list[CandleBar] | None = None,
        current_price: float | None = None,
    ) -> None:
        sym = (symbol or "").strip().upper()
        self._symbol = sym
        self._placeholder.place_forget()
        self._bars = bars if bars is not None else fetch_candle_bars(sym, days=CHART_DAYS)
        self._title.configure(text=f"{sym} — 10 trading days" if sym else "10-day chart")
        self._update_stats(current_price=current_price)
        self._draw()

    def _update_stats(self, *, current_price: float | None = None) -> None:
        if not self._bars:
            self._stats.configure(text="")
            return
        last = self._bars[-1]
        chg = last.close - last.open
        chg_pct = (chg / last.open * 100.0) if last.open else 0.0
        sign = "+" if chg >= 0 else ""
        color = self._up if chg >= 0 else self._down
        price_note = ""
        if current_price is not None and current_price > 0:
            price_note = f"Now ${current_price:.2f}  ·  "
        self._stats.configure(
            text=(
                f"{price_note}Last day  O ${last.open:.2f}  H ${last.high:.2f}  "
                f"L ${last.low:.2f}  C ${last.close:.2f}  ({sign}{chg_pct:.1f}%)"
            ),
            fg=color,
        )

    def _on_canvas_configure(self, event: tk.Event) -> None:
        size = (int(event.width), int(event.height))
        if size[0] < 20 or size[1] < 20:
            return
        if size == self._last_canvas_size:
            return
        self._last_canvas_size = size
        if self._bars:
            self._draw()
        elif self._placeholder.winfo_ismapped():
            self._canvas.delete("all")
            self._placeholder.place(relx=0.5, rely=0.55, anchor=tk.CENTER)

    def redraw(self) -> None:
        """Repaint candles after the widget is resized."""
        self._last_canvas_size = None
        if self._bars:
            self._draw()

    def _draw(self) -> None:
        canvas = self._canvas
        canvas.delete("all")
        w = max(200, int(self._canvas.winfo_width() or self._width))
        h = max(120, int(self._canvas.winfo_height() or self._height))

        if not self._bars:
            canvas.create_text(
                w / 2,
                h / 2,
                text="No price data available",
                fill=self._text,
                font=self._font,
            )
            return

        margin_l, margin_r, margin_t, margin_b = 42, 10, 6, 18
        plot_w = max(40, w - margin_l - margin_r)
        plot_h = max(40, h - margin_t - margin_b)

        lows = [bar.low for bar in self._bars]
        highs = [bar.high for bar in self._bars]
        y_min = min(lows)
        y_max = max(highs)
        pad = max((y_max - y_min) * 0.06, 0.04)
        y_min -= pad
        y_max += pad
        span = max(y_max - y_min, 0.01)

        def y_pos(price: float) -> float:
            return margin_t + plot_h * (1.0 - (price - y_min) / span)

        for i in range(4):
            y = margin_t + plot_h * i / 3
            canvas.create_line(margin_l, y, w - margin_r, y, fill=self._grid, dash=(2, 4))
            price = y_max - span * i / 3
            canvas.create_text(margin_l - 4, y, text=f"${price:.2f}", fill=self._text, font=self._font, anchor="e")

        slot = plot_w / len(self._bars)
        body_w = max(2, min(6, int(slot * 0.16)))
        tick_len = max(3, body_w + 2)

        for index, bar in enumerate(self._bars):
            cx = margin_l + slot * index + slot / 2
            bullish = bar.close >= bar.open
            color = self._up if bullish else self._down
            y_high = y_pos(bar.high)
            y_low = y_pos(bar.low)
            y_open = y_pos(bar.open)
            y_close = y_pos(bar.close)

            # Wick: full high-low range
            canvas.create_line(cx, y_high, cx, y_low, fill=color, width=1)

            # Body: open-to-close (market open at one edge, close at the other)
            top = min(y_open, y_close)
            bottom = max(y_open, y_close)
            body_h = max(1.5, bottom - top)
            if bullish:
                canvas.create_rectangle(
                    cx - body_w / 2,
                    top,
                    cx + body_w / 2,
                    top + body_h,
                    fill=self._bg,
                    outline=color,
                    width=1,
                )
            else:
                canvas.create_rectangle(
                    cx - body_w / 2,
                    top,
                    cx + body_w / 2,
                    top + body_h,
                    fill=color,
                    outline=color,
                    width=1,
                )

            # Open tick (left) and close tick (right)
            canvas.create_line(cx - tick_len, y_open, cx - body_w / 2, y_open, fill=color, width=1)
            canvas.create_line(cx + body_w / 2, y_close, cx + tick_len, y_close, fill=color, width=1)

            canvas.create_text(cx, h - 8, text=bar.date_label, fill=self._text, font=self._font)