"""Drive the taskbar Chrome Default profile for E*TRADE OAuth (no extra profile).

Uses PrintWindow (PW_RENDERFULLCONTENT) + SendInput clicks. Never --user-data-dir.
BitBlt of Chrome is often an occluding overlay (GPU / z-order) — do not prefer it.
Finders are pure functions on PIL images so they can be unit-tested.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable

from PIL import Image

# E*TRADE "Log on" purple (measured on live page).
LOGON_PURPLE = (0x56, 0x27, 0xD8)
# Accept/Decline fill.
ACCEPT_FILL = (0xEF, 0xEF, 0xEF)
# Verification-code input border.
VERIFIER_BORDER = (0x76, 0x76, 0x76)
# "Due to a logon delay..." banner.
ERROR_YELLOW = (0xFF, 0xFB, 0xC4)
VK_L = 0x4C
VK_V = 0x56

PW_RENDERFULLCONTENT = 2
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_RETURN = 0x0D
INPUT_MOUSE = 0
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT_I(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("ii", INPUT_I)]


@dataclass(frozen=True)
class ChromeWindow:
    hwnd: int
    title: str
    left: int
    top: int
    width: int
    height: int


@dataclass(frozen=True)
class Box:
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def cx(self) -> int:
        return (self.x0 + self.x1) // 2

    @property
    def cy(self) -> int:
        return (self.y0 + self.y1) // 2

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0


def _user32():
    u = ctypes.windll.user32
    u.SetProcessDPIAware()
    return u


def classify_title(title: str) -> str:
    t = (title or "").lower()
    if "tradingapicustomerinfo" in t:
        return "code"
    if "log on to e*trade" in t or "log on to etrade" in t:
        return "login"
    if "etws/authorize" in t or "authorize?key=" in t:
        return "accept"
    if any(
        s in t
        for s in (
            "verify your identity",
            "security code",
            "two-step",
            "two step",
            "authenticate",
            "please verify",
        )
    ):
        return "2fa"
    if "etrade" in t or "e*trade" in t:
        return "etrade"
    return "other"


def _color_near(rgb: tuple[int, int, int], target: tuple[int, int, int], tol: int) -> bool:
    return all(abs(a - b) <= tol for a, b in zip(rgb, target, strict=True))


def _horizontal_runs(
    image: Image.Image,
    pred: Callable[[int, int, int], bool],
    *,
    min_width: int,
    max_width: int | None = None,
    y0: int = 0,
    y1: int | None = None,
    step: int = 1,
) -> list[tuple[int, int, int]]:
    """Return (x0, y, width) runs matching pred."""
    w, h = image.size
    end_y = h if y1 is None else min(h, y1)
    runs: list[tuple[int, int, int]] = []
    px = image.load()
    for y in range(max(0, y0), end_y, step):
        x = 0
        while x < w:
            r, g, b = px[x, y][:3]
            if pred(r, g, b):
                x0 = x
                x += 1
                while x < w:
                    r, g, b = px[x, y][:3]
                    if not pred(r, g, b):
                        break
                    x += 1
                length = x - x0
                if length >= min_width and (max_width is None or length <= max_width):
                    runs.append((x0, y, length))
            else:
                x += 1
    return runs


def _merge_band(runs: list[tuple[int, int, int]], *, min_rows: int, max_gap: int = 2) -> Box | None:
    if not runs:
        return None
    runs = sorted(runs, key=lambda t: (t[1], t[0]))
    best: Box | None = None
    i = 0
    while i < len(runs):
        x0, y0, w0 = runs[i]
        x1 = x0 + w0
        y1 = y0
        j = i + 1
        rows = 1
        last_y = y0
        while j < len(runs) and runs[j][1] - last_y <= max_gap + 1:
            rx, ry, rw = runs[j]
            if abs(rx - x0) > 40 and abs((rx + rw) - x1) > 40:
                j += 1
                continue
            x0 = min(x0, rx)
            x1 = max(x1, rx + rw)
            y1 = ry
            if ry != last_y:
                rows += 1
                last_y = ry
            j += 1
        if rows >= min_rows and y1 >= y0:
            box = Box(x0, y0, x1, y1 + 1)
            if best is None or box.width * box.height > best.width * best.height:
                best = box
        i += 1
    return best


def find_logon_button(image: Image.Image) -> Box | None:
    """Largest wide purple rectangle — E*TRADE Log on."""

    def pred(r: int, g: int, b: int) -> bool:
        return _color_near((r, g, b), LOGON_PURPLE, 32)

    w, h = image.size
    runs = _horizontal_runs(image, pred, min_width=max(180, w // 6), y0=int(h * 0.35), y1=int(h * 0.92))
    return _merge_band(runs, min_rows=10, max_gap=2)


def find_accept_button(image: Image.Image) -> Box | None:
    """Left of the two small gray Accept/Decline buttons (Accept is left)."""

    def pred(r: int, g: int, b: int) -> bool:
        return _color_near((r, g, b), ACCEPT_FILL, 10)

    w, h = image.size
    runs = _horizontal_runs(
        image,
        pred,
        # Live Accept/Decline chips are ~46–51px on the small 800x667 window.
        # 50px min missed them and the watchdog opened another tab every retry.
        min_width=36,
        max_width=120,
        y0=int(h * 0.40),
        y1=int(h * 0.80),
    )
    # Pair runs on the same row: left button first.
    by_y: dict[int, list[tuple[int, int]]] = {}
    for x0, y, length in runs:
        by_y.setdefault(y, []).append((x0, length))
    left_runs: list[tuple[int, int, int]] = []
    for y, items in by_y.items():
        items = sorted(items)
        # Two chips on one row = Accept | Decline. Never take a lone right chip.
        if len(items) >= 2:
            x0, length = items[0]
            left_runs.append((x0, y, length))
    box = _merge_band(left_runs, min_rows=5, max_gap=4)
    if box is not None:
        return box
    if left_runs:
        xs = [t[0] for t in left_runs]
        ys = [t[1] for t in left_runs]
        ws = [t[2] for t in left_runs]
        return Box(min(xs), min(ys), min(xs) + min(ws), max(ys) + 1)
    return None


def image_is_usable(image: Image.Image) -> bool:
    """False for BitBlt-of-overlay captures (almost all one dark color)."""
    w, h = image.size
    if w < 200 or h < 200:
        return False
    px = image.load()
    samples = [
        px[x, y][:3]
        for y in range(0, h, max(1, h // 12))
        for x in range(0, w, max(1, w // 16))
    ]
    # Real login/accept pages are mostly white; overlay HUDs are ~rgb(20,20,20).
    dark = sum(1 for r, g, b in samples if r + g + b < 100)
    return dark < int(len(samples) * 0.65)


def find_error_banner(image: Image.Image) -> Box | None:
    """Yellow 'logon delay / try again' strip on the authorize page."""

    def pred(r: int, g: int, b: int) -> bool:
        return r >= 240 and g >= 230 and 140 <= b <= 220 and abs(r - g) <= 20

    w, h = image.size
    runs = _horizontal_runs(
        image,
        pred,
        min_width=max(240, w // 3),
        y0=int(h * 0.10),
        y1=int(h * 0.45),
        step=2,
    )
    return _merge_band(runs, min_rows=6, max_gap=3)


def find_verifier_box(image: Image.Image) -> Box | None:
    """Gray-bordered verification-code field on TradingAPICustomerInfo."""

    def pred(r: int, g: int, b: int) -> bool:
        return _color_near((r, g, b), VERIFIER_BORDER, 14)

    w, h = image.size
    runs = _horizontal_runs(
        image,
        pred,
        min_width=140,
        max_width=320,
        y0=int(h * 0.25),
        y1=int(h * 0.70),
    )
    if len(runs) < 2:
        return None
    # Two parallel borders ~20–40px apart.
    runs = sorted(runs, key=lambda t: t[1])
    best: Box | None = None
    for i, (x0, y0, w0) in enumerate(runs):
        for x1, y1, w1 in runs[i + 1 : i + 8]:
            gap = y1 - y0
            if 18 <= gap <= 45 and abs(x0 - x1) <= 12 and abs(w0 - w1) <= 20:
                box = Box(min(x0, x1), y0, min(x0, x1) + max(w0, w1), y1)
                if best is None or box.width > best.width:
                    best = box
                break
    return best


def list_chrome_windows() -> list[ChromeWindow]:
    user32 = _user32()
    found: list[ChromeWindow] = []

    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def foreach(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        title = buf.value
        if cls.value != "Chrome_WidgetWin_1" or not title:
            return True
        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width < 200 or height < 200:
            return True
        found.append(
            ChromeWindow(
                hwnd=int(hwnd),
                title=title,
                left=rect.left,
                top=rect.top,
                width=width,
                height=height,
            )
        )
        return True

    user32.EnumWindows(EnumWindowsProc(foreach), 0)
    return found


# Prefer 2FA over leftover login windows so we wait instead of clicking
# Log on again (that spawned extra identity tabs overnight).
WINDOW_KIND_RANK = {"code": 0, "accept": 1, "2fa": 2, "login": 3, "etrade": 4, "other": 9}


def etrade_chrome_window() -> ChromeWindow | None:
    windows = list_chrome_windows()
    ranked = []
    for win in windows:
        kind = classify_title(win.title)
        rank = WINDOW_KIND_RANK[kind]
        ranked.append((rank, win))
    ranked.sort(key=lambda t: t[0])
    return ranked[0][1] if ranked and ranked[0][0] < 9 else None


SRCCOPY = 0x00CC0020


def _dib_from_mem(gdi32, mem_dc, bmp, width: int, height: int) -> Image.Image:
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    buf = (ctypes.c_ubyte * (width * height * 4))()
    got = gdi32.GetDIBits(mem_dc, bmp, 0, height, buf, ctypes.byref(bmi), 0)
    if got == 0:
        raise RuntimeError("GetDIBits failed")
    image = Image.frombuffer("RGBA", (width, height), bytes(buf), "raw", "BGRA", 0, 1)
    return image.convert("RGB")


def screenshot_window(win: ChromeWindow) -> Image.Image:
    """Capture the Chrome HWND itself.

    PrintWindow + PW_RENDERFULLCONTENT is required: BitBlt of Chrome's screen
    rect often returns an occluding overlay (dark HUD), which made Log on /
    Accept look missing.
    """
    user32 = _user32()
    gdi32 = ctypes.windll.gdi32
    hwnd = win.hwnd
    if not user32.IsWindow(hwnd):
        raise RuntimeError("Chrome hwnd is gone")
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width = max(1, rect.right - rect.left)
    height = max(1, rect.bottom - rect.top)
    screen_dc = user32.GetDC(0)
    if not screen_dc:
        raise RuntimeError("GetDC(0) failed")
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bmp = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    if not mem_dc or not bmp:
        if screen_dc:
            user32.ReleaseDC(0, screen_dc)
        raise RuntimeError("GDI bitmap failed")
    old = gdi32.SelectObject(mem_dc, bmp)
    try:
        printed = 0
        try:
            printed = int(user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT) or 0)
        except Exception:
            printed = 0
        image = _dib_from_mem(gdi32, mem_dc, bmp, width, height)
        if printed and image_is_usable(image):
            return image
        gdi32.BitBlt(mem_dc, 0, 0, width, height, screen_dc, rect.left, rect.top, SRCCOPY)
        fallback = _dib_from_mem(gdi32, mem_dc, bmp, width, height)
        if image_is_usable(fallback):
            return fallback
        if image_is_usable(image):
            return image
        return fallback
    finally:
        gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(0, screen_dc)


HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_SHOWWINDOW = 0x0040


def foreground(win: ChromeWindow) -> None:
    """Restore + topmost so SendInput hits Chrome, not an overlay HUD."""
    user32 = _user32()
    user32.ShowWindow(win.hwnd, 9)  # SW_RESTORE
    user32.SetWindowPos(
        win.hwnd,
        HWND_TOPMOST,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
    )
    user32.SetForegroundWindow(win.hwnd)
    time.sleep(0.25)


def click_screen(x: int, y: int) -> None:
    user32 = _user32()
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    if sw <= 1 or sh <= 1:
        return
    absx = int(x * 65535 / (sw - 1))
    absy = int(y * 65535 / (sh - 1))

    def send(flags: int, mx: int = 0, my: int = 0) -> None:
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.ii.mi = MOUSEINPUT(mx, my, 0, flags, 0, None)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    send(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, absx, absy)
    time.sleep(0.08)
    send(MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE, absx, absy)
    time.sleep(0.04)
    send(MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE, absx, absy)


def click_window(win: ChromeWindow, rel_x: int, rel_y: int) -> None:
    foreground(win)
    click_screen(win.left + rel_x, win.top + rel_y)


def tap_enter() -> None:
    user32 = _user32()
    user32.keybd_event(VK_RETURN, 0, 0, 0)
    time.sleep(0.04)
    user32.keybd_event(VK_RETURN, 0, KEYEVENTF_KEYUP, 0)


def copy_selection() -> None:
    user32 = _user32()
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(ord("A"), 0, 0, 0)
    time.sleep(0.04)
    user32.keybd_event(ord("A"), 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.04)
    user32.keybd_event(ord("C"), 0, 0, 0)
    time.sleep(0.04)
    user32.keybd_event(ord("C"), 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.15)


def read_clipboard_text() -> str:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    if not user32.OpenClipboard(None):
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def harvest_verifier(win: ChromeWindow, image: Image.Image) -> str:
    box = find_verifier_box(image)
    if box is None:
        # Fallback: center of the form card.
        click_window(win, win.width // 2, int(win.height * 0.42))
    else:
        click_window(win, box.cx, box.cy)
    time.sleep(0.15)
    copy_selection()
    return (read_clipboard_text() or "").strip()


def write_clipboard_text(text: str) -> bool:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    if not text:
        return False
    payload = text + "\x00"
    raw = payload.encode("utf-16le")
    for _ in range(5):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.12)
    else:
        return False
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(raw))
        if not handle:
            return False
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return False
        try:
            ctypes.memmove(ptr, raw, len(raw))
        finally:
            kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            return False
        return True
    finally:
        user32.CloseClipboard()


def tap_ctrl_key(vk: int) -> None:
    user32 = _user32()
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.04)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def navigate_same_tab(win: ChromeWindow, url: str) -> bool:
    """Replace the current tab URL (no extra tab). Used after logon-delay errors."""
    if not url or not write_clipboard_text(url):
        return False
    foreground(win)
    tap_ctrl_key(VK_L)
    time.sleep(0.15)
    tap_ctrl_key(VK_V)
    time.sleep(0.12)
    tap_enter()
    time.sleep(0.8)
    return True
