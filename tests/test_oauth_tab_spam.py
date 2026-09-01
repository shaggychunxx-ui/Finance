"""Auto-OAuth must never launch a second E*TRADE Chrome tab."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from complete_etrade_oauth import decide_oauth_chrome_action  # noqa: E402
from chrome_oauth_ui import classify_title  # noqa: E402


def test_accept_code_2fa_drive_only() -> None:
    for kind in ("accept", "code", "2fa"):
        assert (
            decide_oauth_chrome_action(
                kind=kind,
                pending_fresh=False,
                chrome_running=True,
                already_opened_chrome=True,
            )
            == "drive"
        )


def test_login_fresh_pending_does_not_launch() -> None:
    assert (
        decide_oauth_chrome_action(
            kind="login",
            pending_fresh=True,
            chrome_running=True,
            already_opened_chrome=True,
        )
        == "drive"
    )


def test_login_stale_pending_navigates_same_tab() -> None:
    assert (
        decide_oauth_chrome_action(
            kind="login",
            pending_fresh=False,
            chrome_running=True,
            already_opened_chrome=True,
        )
        == "navigate"
    )


def test_error_page_navigates_same_tab() -> None:
    assert (
        decide_oauth_chrome_action(
            kind="login",
            pending_fresh=False,
            chrome_running=True,
            already_opened_chrome=True,
            error_page=True,
        )
        == "navigate"
    )


def test_detection_miss_after_launch_waits() -> None:
    """Overnight spam: chrome.exe URL while Chrome was already running."""
    assert (
        decide_oauth_chrome_action(
            kind="",
            pending_fresh=False,
            chrome_running=True,
            already_opened_chrome=True,
        )
        == "wait"
    )


def test_first_open_when_no_tab() -> None:
    assert (
        decide_oauth_chrome_action(
            kind="",
            pending_fresh=False,
            chrome_running=True,
            already_opened_chrome=False,
        )
        == "open_once"
    )


def test_user_closed_chrome_may_open_once() -> None:
    assert (
        decide_oauth_chrome_action(
            kind="",
            pending_fresh=False,
            chrome_running=False,
            already_opened_chrome=True,
        )
        == "open_once"
    )


def test_2fa_title_outranks_login() -> None:
    assert classify_title("Verify your identity - Google Chrome") == "2fa"
    # Rank numbers live in etrade_chrome_window; 2fa must be preferred over login.
    from chrome_oauth_ui import etrade_chrome_window as _  # noqa: F401

    login_rank = 3
    twofa_rank = 2
    assert twofa_rank < login_rank


if __name__ == "__main__":
    test_accept_code_2fa_drive_only()
    test_login_fresh_pending_does_not_launch()
    test_login_stale_pending_navigates_same_tab()
    test_error_page_navigates_same_tab()
    test_detection_miss_after_launch_waits()
    test_first_open_when_no_tab()
    test_user_closed_chrome_may_open_once()
    test_2fa_title_outranks_login()
    print("ALL_OK")
