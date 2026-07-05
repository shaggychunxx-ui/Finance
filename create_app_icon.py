"""Generate multi-size app_icon.ico for the Windows desktop app."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "app_icon.ico"
OUT_ALT = ROOT / "etrade_trader.ico"
SOURCE_CANDIDATES = (
    ROOT / "app_icon_source.png",
    ROOT / "app_icon_source.jpg",
    ROOT / "app_icon_source.jpeg",
)
# Include common Windows DPI sizes so Explorer/taskbar never upscales a tiny bitmap.
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
# Pillow thumbnails each size from this master — keep it as large as possible (max 1024).
MASTER_PX = 1024


def _find_source() -> Path | None:
    for path in SOURCE_CANDIDATES:
        if path.exists():
            return path
    return None


def _square_crop(img):
    from PIL import Image

    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side))


def _save_multi_size_ico(master) -> None:
    """Write a true multi-resolution ICO (Pillow generates each size from master)."""
    sizes = [(s, s) for s in ICO_SIZES]
    master.save(OUT, format="ICO", sizes=sizes)
    master.save(OUT_ALT, format="ICO", sizes=sizes)


def _master_from_source(img) -> object:
    """Build a large master so Pillow can thumbnail each ICO size sharply."""
    from PIL import Image

    side = min(max(img.size), MASTER_PX)
    if img.size[0] != side or img.size[1] != side:
        return img.resize((side, side), Image.Resampling.LANCZOS)
    return img


def _build_from_source(source: Path) -> None:
    from PIL import Image

    img = _square_crop(Image.open(source).convert("RGBA"))
    _save_multi_size_ico(_master_from_source(img))


def _build_fallback() -> None:
    """Simple gradient fallback when no source artwork is present."""
    from PIL import Image

    size = 256
    master = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = master.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (size * 2 - 2)
            r = int(108 + t * (0 - 108))
            g = int(92 + t * (206 - 92))
            b = int(231 + t * (201 - 231))
            margin = size // 16
            a = 255 if margin < x < size - margin and margin < y < size - margin else 0
            px[x, y] = (r, g, b, a)
    _save_multi_size_ico(master)


def main() -> None:
    source = _find_source()
    if source is not None:
        _build_from_source(source)
        print(
            f"Created {OUT.name} and {OUT_ALT.name} from {source.name} ({len(ICO_SIZES)} sizes)"
        )
        return
    _build_fallback()
    print(f"Created {OUT.name} (fallback gradient — add app_icon_source.png for full artwork)")


if __name__ == "__main__":
    main()