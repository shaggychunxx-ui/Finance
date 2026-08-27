"""Image-finder tests for taskbar Chrome E*TRADE OAuth (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chrome_oauth_ui import (  # noqa: E402
    ACCEPT_FILL,
    ERROR_YELLOW,
    LOGON_PURPLE,
    VERIFIER_BORDER,
    classify_title,
    find_accept_button,
    find_error_banner,
    find_logon_button,
    find_verifier_box,
    image_is_usable,
)


def test_classify_title() -> None:
    assert classify_title("Log on to E*TRADE - Google Chrome") == "login"
    assert classify_title("us.etrade.com/e/t/etws/authorize?key=abc") == "accept"
    assert classify_title("us.etrade.com/e/t/etws/TradingAPICustomerInfo") == "code"
    assert classify_title("Verify your identity - Google Chrome") == "2fa"
    assert classify_title("Gmail") == "other"


def test_find_logon_button_on_synthetic() -> None:
    img = Image.new("RGB", (1200, 1000), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle((315, 700, 315 + 548, 739), fill=LOGON_PURPLE)
    box = find_logon_button(img)
    assert box is not None
    assert 500 < box.cx < 700
    assert 705 < box.cy < 735
    assert box.width >= 400
    assert box.height >= 20


def test_find_accept_clicks_left_button() -> None:
    img = Image.new("RGB", (1200, 1000), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Accept (left) and Decline (right) — must click left.
    draw.rectangle((516, 593, 516 + 72, 618), fill=ACCEPT_FILL)
    draw.rectangle((599, 593, 599 + 77, 618), fill=ACCEPT_FILL)
    box = find_accept_button(img)
    assert box is not None
    assert box.cx < 599  # left button, not Decline
    assert 516 <= box.x0 <= 530
    assert 593 <= box.y0 <= 600


def test_find_accept_on_small_window_chips() -> None:
    """Live 800x667 window uses ~48px Accept/Decline chips (old min_width=50 missed)."""
    img = Image.new("RGB", (800, 667), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle((345, 389, 345 + 48, 403), fill=ACCEPT_FILL)
    draw.rectangle((400, 389, 400 + 51, 403), fill=ACCEPT_FILL)
    box = find_accept_button(img)
    assert box is not None
    assert box.cx < 400


def test_find_verifier_box_between_gray_borders() -> None:
    img = Image.new("RGB", (1200, 1000), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.line((473, 412, 473 + 249, 412), fill=VERIFIER_BORDER)
    draw.line((473, 443, 473 + 249, 443), fill=VERIFIER_BORDER)
    box = find_verifier_box(img)
    assert box is not None
    assert abs(box.cx - 597) <= 15
    assert 412 <= box.cy <= 443


def test_image_is_usable_rejects_dark_overlay() -> None:
    blank = Image.new("RGB", (800, 667), (20, 20, 20))
    assert image_is_usable(blank) is False
    page = Image.new("RGB", (800, 667), (255, 255, 255))
    draw = ImageDraw.Draw(page)
    draw.rectangle((210, 466, 575, 505), fill=LOGON_PURPLE)
    assert image_is_usable(page) is True


def test_find_error_banner_on_yellow_strip() -> None:
    img = Image.new("RGB", (800, 667), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle((40, 120, 760, 155), fill=ERROR_YELLOW)
    box = find_error_banner(img)
    assert box is not None
    assert box.width >= 400


def test_finders_on_captured_pages_if_present() -> None:
    debug = ROOT / "output" / "chrome-oauth-debug"
    login = debug / "taskbar-chrome-0.png"
    accept = debug / "taskbar-chrome-retry-0.png"
    code = debug / "taskbar-chrome-code-retry.png"
    if login.is_file():
        box = find_logon_button(Image.open(login).convert("RGB"))
        assert box is not None
        assert box.width >= 300
    if accept.is_file():
        box = find_accept_button(Image.open(accept).convert("RGB"))
        assert box is not None
        assert box.cx < 600
    if code.is_file():
        box = find_verifier_box(Image.open(code).convert("RGB"))
        assert box is not None
        assert 450 < box.cx < 750


if __name__ == "__main__":
    test_classify_title()
    test_find_logon_button_on_synthetic()
    test_find_accept_clicks_left_button()
    test_find_accept_on_small_window_chips()
    test_find_verifier_box_between_gray_borders()
    test_image_is_usable_rejects_dark_overlay()
    test_find_error_banner_on_yellow_strip()
    test_finders_on_captured_pages_if_present()
    print("ALL_OK")
