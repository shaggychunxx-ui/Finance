#!/usr/bin/env python3
"""Complete E*TRADE OAuth in the taskbar Chrome (shaggychunxx Default profile).

When the access token is dead (midnight ET or missing), this:
  1) reuses an existing E*TRADE Chrome tab if one is already open
  2) otherwise reuses a fresh pending request token, or mints ONE
  3) opens the authorize URL in taskbar Chrome AT MOST once
  4) clicks Log on then the left gray Accept
  5) copies the verification code and calls finish_etrade_login

Never mint a new token or open another tab while an authorize/login/code
tab is already on screen. That was the tab-spam bug.

Never uses Playwright ~/.grok/browser-profile or --user-data-dir.
Safe no-op if the session is already live. Cooldown + lock prevent spam.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    from process_guard import ensure_finance_packages

    ensure_finance_packages()
except Exception:
    site = ROOT / ".venv" / "Lib" / "site-packages"
    if site.is_dir() and str(site) not in sys.path:
        sys.path.insert(0, str(site))

from etrade_runtime import (  # noqa: E402
    assert_live_for_broker_action,
    ensure_sys_path,
    resolve_live_root,
)

LOG = ROOT / "output" / "oauth_auto.log"
LOCK = ROOT / "output" / "oauth_auto.lock"
LAST = ROOT / "output" / "oauth_auto_last.json"
CHROME_OPENED = ROOT / "output" / "oauth_chrome_opened.txt"
COOLDOWN_FAIL_SEC = 10 * 60
# After a harvest/2FA miss, do not click Log on / launch Chrome every 10 min.
# Overnight 2026-09-01: 30 starts, 15 chrome.exe launches, 29 harvest fails.
COOLDOWN_HARVEST_SEC = 60 * 60
LOCK_STALE_SEC = 180
UI_BUDGET_SEC = 120
# Request tokens die quickly. Reuse the pending authorize URL only this long.
PENDING_MAX_AGE_SEC = 12 * 60
DEBUG_DIR = ROOT / "output" / "chrome-oauth-debug"
_HARVEST_FAIL_MARKERS = (
    "harvest",
    "2fa",
    "another tab",
    "already opened",
    "already launched",
    "not launching",
)


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def _session_live() -> tuple[bool, str]:
    from etrade_api.config import load_config
    from etrade_api.oauth import session_is_live

    decision = resolve_live_root()
    ensure_sys_path(decision.root)
    cfg = load_config(decision.config_path)
    cfg.token_path = decision.token_path
    return session_is_live(cfg)


def _read_last() -> dict:
    try:
        if LAST.exists():
            data = json.loads(LAST.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _write_last(ok: bool, detail: str) -> None:
    LAST.parent.mkdir(parents=True, exist_ok=True)
    LAST.write_text(
        json.dumps(
            {
                "ok": ok,
                "detail": detail[:400],
                "ts": time.time(),
                "when": datetime.now().isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _acquire_lock() -> bool:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        if LOCK.exists():
            age = time.time() - LOCK.stat().st_mtime
            if age < LOCK_STALE_SEC:
                return False
            LOCK.unlink(missing_ok=True)
        LOCK.write_text(f"{os_getpid()}\n{time.time():.3f}\n", encoding="utf-8")
        return True
    except OSError:
        return False


def os_getpid() -> int:
    import os

    return os.getpid()


def _release_lock() -> None:
    try:
        LOCK.unlink(missing_ok=True)
    except OSError:
        pass


def _pending_path() -> Path:
    return ROOT / "output" / "oauth_pending.json"


def _chrome_opened_this_cycle() -> bool:
    return CHROME_OPENED.exists()


def _mark_chrome_opened() -> None:
    try:
        CHROME_OPENED.parent.mkdir(parents=True, exist_ok=True)
        CHROME_OPENED.write_text(f"{time.time():.3f}\n", encoding="utf-8")
    except OSError:
        pass


def _clear_chrome_opened() -> None:
    try:
        CHROME_OPENED.unlink(missing_ok=True)
    except OSError:
        pass


def decide_oauth_chrome_action(
    *,
    kind: str,
    pending_fresh: bool,
    chrome_running: bool,
    already_opened_chrome: bool,
    error_page: bool = False,
) -> str:
    """Pick one Chrome action. Never open a second E*TRADE tab.

    drive     — OAuth tab is on screen; click through, no mint, no chrome.exe
    navigate  — put a URL in the SAME tab (error page / stale pending)
    open_once — no tab yet this cycle; mint if needed, launch Chrome once
    wait      — we already launched; window detection missed; do not add a tab
    """
    kind = kind or ""
    if kind in ("code", "accept", "2fa"):
        return "drive"
    if error_page and kind:
        return "navigate"
    if kind in ("login", "etrade"):
        return "drive" if pending_fresh else "navigate"
    if already_opened_chrome and chrome_running:
        return "wait"
    if already_opened_chrome and not chrome_running:
        return "open_once"
    return "open_once"


def _harvest_like_fail(detail: str) -> bool:
    text = (detail or "").lower()
    return any(marker in text for marker in _HARVEST_FAIL_MARKERS)


def _pending_url(*, max_age_sec: float | None = PENDING_MAX_AGE_SEC) -> str | None:
    pending = _pending_path()
    if not pending.exists():
        return None
    try:
        if max_age_sec is not None:
            age = time.time() - pending.stat().st_mtime
            if age > max_age_sec:
                _log(f"pending token stale age={age:.0f}s (>{max_age_sec:.0f}s)")
                return None
        return json.loads(pending.read_text(encoding="utf-8")).get("authorize_url")
    except (OSError, json.JSONDecodeError):
        return None


def _etrade_oauth_tab_open() -> bool:
    """True if taskbar Chrome already has an E*TRADE login/accept/code window."""
    try:
        import chrome_oauth_ui as ui

        return ui.etrade_chrome_window() is not None
    except Exception:
        return False


def _save_debug(image, tag: str) -> None:
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        path = DEBUG_DIR / f"auto-{tag}.png"
        image.save(path)
    except Exception:
        pass


def _begin_oauth() -> str | None:
    from begin_etrade_login import main as begin_main

    rc = begin_main(["--force", "--no-browser"])
    pending = _pending_path()
    if rc not in (0, None) and not pending.exists():
        return None
    try:
        return json.loads(pending.read_text(encoding="utf-8")).get("authorize_url")
    except (OSError, json.JSONDecodeError):
        return None


def _open_taskbar_chrome(url: str, *, force: bool = False) -> bool:
    if _etrade_oauth_tab_open():
        _log("E*TRADE tab already open — not opening another")
        return True
    if not force:
        try:
            from open_chrome_url import chrome_running
        except Exception:
            chrome_running = lambda: False  # noqa: E731
        if chrome_running() and _chrome_opened_this_cycle():
            _log("Chrome already launched this OAuth cycle — not opening another tab")
            return False
    from open_chrome_url import open_url_chrome

    proof = open_url_chrome(url)
    _log(f"chrome open proof={proof}")
    ok = bool(proof.get("ok") or proof.get("launched"))
    if ok:
        _mark_chrome_opened()
    return ok


def _finish(code: str) -> int:
    from finish_etrade_login import main as finish_main

    return int(finish_main([code]))


def _drive_ui() -> tuple[str, str]:
    """Click through login/Accept and return (verifier, status).

    status: ok | error | 2fa | timeout
    """
    import chrome_oauth_ui as ui
    from etrade_api.oauth import normalize_verifier

    deadline = time.time() + UI_BUDGET_SEC
    clicked_logon = 0.0
    logon_attempts = 0
    clicked_accept = False
    logged_accept_miss = False
    logged_blank = False
    last_kind = ""
    while time.time() < deadline:
        win = ui.etrade_chrome_window()
        if win is None:
            time.sleep(0.6)
            continue
        kind = ui.classify_title(win.title)
        try:
            image = ui.screenshot_window(win)
        except Exception as exc:
            _log(f"screenshot failed ({exc}); retry")
            time.sleep(0.8)
            continue
        if not ui.image_is_usable(image):
            if not logged_blank:
                _log("screenshot unusable (overlay/blank) — PrintWindow miss")
                _save_debug(image, "blank")
                logged_blank = True
            time.sleep(0.8)
            continue
        if ui.find_error_banner(image) is not None:
            _log("logon-delay / try-again banner — need a fresh request token")
            _save_debug(image, "error")
            return "", "error"
        if kind != last_kind:
            _log(f"page kind={kind} title={win.title[:80]!r}")
            last_kind = kind
        if kind == "code":
            raw = ui.harvest_verifier(win, image)
            code = normalize_verifier(raw)
            if code and 4 <= len(code) <= 16 and "http" not in code.lower():
                _log(f"verifier harvested len={len(code)}")
                return code, "ok"
            _log("code page but clipboard not a verifier")
            time.sleep(0.8)
            continue
        if kind == "2fa":
            _log("2FA page — waiting (human/device approve)")
            time.sleep(2.0)
            continue
        if kind == "login":
            if logon_attempts >= 2:
                time.sleep(0.5)
                continue
            if clicked_logon and (time.time() - clicked_logon) < 8:
                time.sleep(0.5)
                continue
            box = ui.find_logon_button(image)
            ui.foreground(win)
            if box is None:
                _log("login page but Log on button not found — password+Enter fallback")
                _save_debug(image, "login-miss")
                ui.click_window(win, win.width // 2, int(win.height * 0.48))
                time.sleep(0.2)
                ui.tap_enter()
            else:
                # Autofill often needs a password-field click before Log on submits.
                ui.click_window(win, box.cx, max(40, box.y0 - 70))
                time.sleep(0.25)
                ui.click_window(win, box.cx, box.cy)
                time.sleep(0.15)
                ui.tap_enter()
                _log(f"clicked Log on at {box.cx},{box.cy} attempt={logon_attempts + 1}")
            logon_attempts += 1
            clicked_logon = time.time()
            time.sleep(1.5)
            continue
        if kind == "accept" and not clicked_accept:
            box = ui.find_accept_button(image)
            if box is None:
                if not logged_accept_miss:
                    _log("accept page but Accept button not found (will retry, no new tab)")
                    _save_debug(image, "accept-miss")
                    logged_accept_miss = True
                time.sleep(0.8)
                continue
            ui.click_window(win, box.cx, box.cy)
            clicked_accept = True
            _log(f"clicked Accept at {box.cx},{box.cy}")
            time.sleep(1.2)
            continue
        time.sleep(0.5)
    return "", "2fa" if last_kind == "2fa" else "timeout"


def complete_oauth_if_needed(*, force: bool = False) -> tuple[bool, str]:
    """Return (ok, detail). No-op success if already live."""
    try:
        decision = resolve_live_root()
        assert_live_for_broker_action(decision)
        ensure_sys_path(decision.root)
    except Exception as exc:
        return False, f"runtime: {exc}"

    try:
        live, detail = _session_live()
    except Exception as exc:
        live, detail = False, f"probe: {exc}"
    if live and not force:
        return True, f"already live ({detail})"

    last = _read_last()
    if not force and last.get("ok") is False:
        age = time.time() - float(last.get("ts") or 0)
        if age < COOLDOWN_FAIL_SEC:
            return False, f"cooldown {age:.0f}s after failed auto-oauth ({last.get('detail')})"

    if not _acquire_lock():
        return False, "auto-oauth already running"

    try:
        _log(f"AUTO OAUTH start force={force} prior={detail}")
        import chrome_oauth_ui as ui

        win = ui.etrade_chrome_window()
        kind = ui.classify_title(win.title) if win is not None else ""
        url = _pending_url()
        # accept/code/2fa: keep this tab. login/error/none: put the pending URL in the tab.
        reuse_ui = kind in ("accept", "code", "2fa") and bool(url)
        if reuse_ui:
            _log(f"existing {kind} tab + fresh pending — drive UI, no new token")
        else:
            if not url:
                url = _begin_oauth()
                if not url:
                    msg = "begin_etrade_login did not produce authorize URL"
                    _write_last(False, msg)
                    _log(msg)
                    return False, msg
            navigated = False
            if win is not None:
                ui.foreground(win)
                navigated = ui.navigate_same_tab(win, url)
            if navigated:
                _log("navigated existing E*TRADE tab to authorize URL")
            elif not _open_taskbar_chrome(url, force=True):
                msg = "failed to open/navigate taskbar Chrome"
                _write_last(False, msg)
                _log(msg)
                return False, msg
            time.sleep(2.0)

        code, status = _drive_ui()
        if status == "error":
            url = _begin_oauth()
            if url:
                try:
                    import chrome_oauth_ui as ui

                    win = ui.etrade_chrome_window()
                    if win is not None:
                        ui.navigate_same_tab(win, url)
                        _log("fresh token after logon-delay; retrying UI")
                        time.sleep(2.0)
                        code, status = _drive_ui()
                except Exception as exc:
                    _log(f"error-retry navigate failed: {exc}")
        if not code:
            msg = (
                "2FA waiting on Chrome (human/device)"
                if status == "2fa"
                else (
                    "logon-delay error page"
                    if status == "error"
                    else "could not harvest verification code (2FA or UI changed)"
                )
            )
            _write_last(False, msg)
            _log(msg)
            return False, msg
        rc = _finish(code)
        if rc != 0:
            msg = f"finish_etrade_login exit {rc}"
            _write_last(False, msg)
            _log(msg)
            return False, msg
        live2, detail2 = _session_live()
        if not live2:
            msg = f"finished but session still dead ({detail2})"
            _write_last(False, msg)
            _log(msg)
            return False, msg
        _write_last(True, detail2)
        _log(f"AUTO OAUTH OK {detail2}")
        return True, detail2
    except Exception as exc:
        msg = f"auto-oauth error: {exc}"
        _write_last(False, msg)
        _log(msg)
        return False, msg
    finally:
        _release_lock()


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    force = "--force" in args
    ok, detail = complete_oauth_if_needed(force=force)
    print(detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
