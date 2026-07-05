"""Windows taskbar / Start identity so shortcuts control the running app icon."""

from __future__ import annotations

APP_USER_MODEL_ID = "Finance.ETrade.Trader.1"


def apply_windows_app_identity() -> None:
    import sys

    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass