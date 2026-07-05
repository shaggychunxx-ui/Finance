#!/usr/bin/env python3
"""Generate PWA icons for the mobile monitor."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
ICON_DIR = ROOT / "mobile_icons"


def _draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (10, 14, 23, 255))
    draw = ImageDraw.Draw(img)
    margin = max(8, size // 10)
    draw.rounded_rectangle(
        (margin, margin, size - margin, size - margin),
        radius=size // 6,
        fill=(18, 26, 43, 255),
        outline=(108, 92, 231, 255),
        width=max(2, size // 64),
    )
    bar_w = max(4, size // 18)
    gap = max(6, size // 14)
    base_y = int(size * 0.58)
    heights = [0.35, 0.55, 0.42, 0.72]
    colors = [(0, 206, 201, 255), (0, 230, 118, 255), (255, 213, 79, 255), (108, 92, 231, 255)]
    start_x = int(size * 0.28)
    for idx, (h, color) in enumerate(zip(heights, colors)):
        x0 = start_x + idx * (bar_w + gap)
        bar_h = int(size * h * 0.35)
        draw.rounded_rectangle(
            (x0, base_y - bar_h, x0 + bar_w, base_y),
            radius=bar_w // 2,
            fill=color,
        )
    try:
        font = ImageFont.truetype("segoeui.ttf", max(12, size // 7))
    except OSError:
        font = ImageFont.load_default()
    draw.text((size * 0.22, size * 0.18), "E*", fill=(232, 237, 245, 255), font=font)
    return img


def main() -> int:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        path = ICON_DIR / f"icon-{size}.png"
        _draw_icon(size).save(path, format="PNG")
        print(f"Wrote {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())