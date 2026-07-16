#!/usr/bin/env python3
"""Generate Short Trader icons in the Midnight palette (purple/magenta on deep violet)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_ICO = ROOT / "etrade_short_trader.ico"
OUT_SRC = ROOT / "etrade_short_trader_source.png"
OUT_ALT = ROOT / "short_app_icon.ico"

# gui_theme midnight tokens
MIDNIGHT = {
    "BG": (0x0D, 0x08, 0x14, 255),
    "PANEL": (0x16, 0x0F, 0x22, 255),
    "CARD": (0x11, 0x0A, 0x1A, 255),
    "BORDER": (0x3B, 0x2A, 0x5C, 255),
    "ACCENT": (0x93, 0x33, 0xEA, 255),
    "ACCENT2": (0xD9, 0x46, 0xEF, 255),
    "TEXT": (0xF0, 0xE8, 0xF8, 255),
    "DOWN": (0xFB, 0x71, 0x85, 255),
    "UP": (0x4A, 0xDE, 0x80, 255),
}

ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
MASTER_PX = 1024


def _hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _blend(c1: tuple[int, ...], c2: tuple[int, ...], t: float) -> tuple[int, int, int, int]:
    return (
        int(_lerp(c1[0], c2[0], t)),
        int(_lerp(c1[1], c2[1], t)),
        int(_lerp(c1[2], c2[2], t)),
        int(_lerp(c1[3] if len(c1) > 3 else 255, c2[3] if len(c2) > 3 else 255, t)),
    )


def _rounded_mask(size: int, radius: float):
    from PIL import Image, ImageDraw

    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def _draw_down_arrow(draw, box: tuple[int, int, int, int], fill) -> None:
    """Filled downward arrow for short-selling identity."""
    x0, y0, x1, y1 = box
    w = x1 - x0
    h = y1 - y0
    cx = (x0 + x1) / 2
    # Shaft
    shaft_w = w * 0.28
    shaft_top = y0 + h * 0.12
    shaft_bot = y0 + h * 0.52
    draw.rectangle(
        [cx - shaft_w / 2, shaft_top, cx + shaft_w / 2, shaft_bot],
        fill=fill,
    )
    # Arrow head
    head_top = shaft_bot - h * 0.02
    head_bot = y0 + h * 0.88
    draw.polygon(
        [
            (cx, head_bot),
            (x0 + w * 0.12, head_top),
            (x1 - w * 0.12, head_top),
        ],
        fill=fill,
    )


def _draw_sparkline(draw, box: tuple[int, int, int, int], color, width: int = 6) -> None:
    """Descending polyline suggesting a short thesis."""
    x0, y0, x1, y1 = box
    w = x1 - x0
    h = y1 - y0
    pts = [
        (x0 + w * 0.10, y0 + h * 0.28),
        (x0 + w * 0.32, y0 + h * 0.22),
        (x0 + w * 0.48, y0 + h * 0.40),
        (x0 + w * 0.62, y0 + h * 0.48),
        (x0 + w * 0.78, y0 + h * 0.68),
        (x0 + w * 0.90, y0 + h * 0.78),
    ]
    draw.line(pts, fill=color, width=max(2, width), joint="curve")


def build_master(size: int = MASTER_PX):
    from PIL import Image, ImageDraw, ImageFilter

    bg = MIDNIGHT["BG"]
    panel = MIDNIGHT["PANEL"]
    accent = MIDNIGHT["ACCENT"]
    accent2 = MIDNIGHT["ACCENT2"]
    down = MIDNIGHT["DOWN"]
    border = MIDNIGHT["BORDER"]
    text = MIDNIGHT["TEXT"]

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()

    # Radial-ish gradient background (midnight BG → PANEL → deep accent tint)
    cx = cy = size / 2
    max_d = (size * 0.72)
    for y in range(size):
        for x in range(size):
            dx = (x - cx) / max_d
            dy = (y - cy) / max_d
            d = (dx * dx + dy * dy) ** 0.5
            t = min(1.0, d)
            if t < 0.45:
                c = _blend(panel, bg, t / 0.45)
            else:
                c = _blend(bg, (accent[0] // 5, accent[1] // 8, accent[2] // 5, 255), (t - 0.45) / 0.55)
            px[x, y] = c

    # Soft accent glow behind glyph
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    pad = int(size * 0.18)
    gdraw.ellipse([pad, pad, size - pad, size - pad], fill=(accent[0], accent[1], accent[2], 70))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=size * 0.06))
    img = Image.alpha_composite(img, glow)
    draw = ImageDraw.Draw(img)

    # Rounded tile border (midnight BORDER → ACCENT)
    inset = int(size * 0.06)
    radius = size * 0.18
    for i, col in enumerate(
        [
            (border[0], border[1], border[2], 220),
            (accent[0], accent[1], accent[2], 180),
        ]
    ):
        o = inset + i * max(1, size // 256)
        draw.rounded_rectangle(
            [o, o, size - 1 - o, size - 1 - o],
            radius=radius - i * 2,
            outline=col,
            width=max(2, size // 64),
        )

    # Descending sparkline (magenta)
    _draw_sparkline(
        draw,
        (int(size * 0.16), int(size * 0.18), int(size * 0.84), int(size * 0.55)),
        (accent2[0], accent2[1], accent2[2], 255),
        width=max(3, size // 48),
    )

    # Short arrow (DOWN rose from midnight, with accent tip glow)
    arrow_box = (
        int(size * 0.32),
        int(size * 0.38),
        int(size * 0.68),
        int(size * 0.88),
    )
    _draw_down_arrow(draw, arrow_box, (down[0], down[1], down[2], 255))
    # Accent shaft highlight
    cx = size / 2
    shaft_w = size * 0.06
    draw.rectangle(
        [cx - shaft_w / 2, size * 0.42, cx + shaft_w / 2, size * 0.58],
        fill=(accent[0], accent[1], accent[2], 255),
    )

    # Small "S" badge for Short (text-colored)
    try:
        from PIL import ImageFont

        font_size = max(12, size // 7)
        try:
            font = ImageFont.truetype("segoeui.ttf", font_size)
        except OSError:
            try:
                font = ImageFont.truetype("arial.ttf", font_size)
            except OSError:
                font = ImageFont.load_default()
        label = "S"
        # Badge circle
        br = size * 0.11
        bx = size * 0.78
        by = size * 0.78
        draw.ellipse(
            [bx - br, by - br, bx + br, by + br],
            fill=(accent[0], accent[1], accent[2], 255),
            outline=(text[0], text[1], text[2], 255),
            width=max(1, size // 128),
        )
        # Center letter
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            (bx - tw / 2 - bbox[0], by - th / 2 - bbox[1] - size * 0.01),
            label,
            font=font,
            fill=(text[0], text[1], text[2], 255),
        )
    except Exception:
        pass

    # Apply rounded alpha mask so corners are transparent (modern Win tile look)
    mask = _rounded_mask(size, radius)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0))
    out.putalpha(mask)
    return out


def save_icons(master) -> None:
    sizes = [(s, s) for s in ICO_SIZES]
    master.save(OUT_SRC, format="PNG")
    master.save(OUT_ICO, format="ICO", sizes=sizes)
    master.save(OUT_ALT, format="ICO", sizes=sizes)


def main() -> int:
    master = build_master(MASTER_PX)
    save_icons(master)
    print(f"Created {OUT_ICO.name}, {OUT_ALT.name}, {OUT_SRC.name} (midnight palette, {len(ICO_SIZES)} sizes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
