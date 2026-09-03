#!/usr/bin/env python3
"""LAN bridge so the phone E*TRADE app mirrors the desktop UI and can complete OAuth.

Runs on the broker PC (AI-CODING). Phone connects over Wi-Fi / LAN.

Endpoints (all JSON; require X-Bridge-Token except /health):
  GET  /health
  GET  /api/dashboard      # ?refresh=1|full=1 forces live broker snapshot pull
  GET  /api/full           # full phone pack: dashboard + agents + accounts + orders
  GET  /api/orders         # broker orders when PC tokens available
  GET  /api/features       # shared API + independent practice flags (phone feature catalog)
  GET  /api/agents         # specialist agents + analysis/findings/projections
  GET  /api/auth/status
  POST /api/oauth/start
  POST /api/oauth/finish   body: {"verifier"|"oauth_verifier"|"code": "..."}
  POST /api/controls       body: {"side":"long|short|all", "dry_run"?, "auto_execute"?, "paused"?}
  POST /api/stop_all
  POST /api/resume_all

Secrets (consumer keys, access tokens) never leave this machine.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_paths import ensure_app_path

ensure_app_path()

LONG_CONFIG = ROOT / "etrade_config.json"
SHORT_CONFIG = ROOT / "short_etrade_config.json"
BRIDGE_CONFIG = ROOT / "phone_bridge_config.json"
PENDING_FILE = ROOT / "output" / "oauth_pending.json"
LOG_FILE = ROOT / "output" / "phone_bridge.log"

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8787
BRIDGE_VERSION = "1.6.4"
# Phone "data current" if last GROMIT pack/marks are newer than this (refresh is 15 min).
DATA_CURRENT_MAX_SEC = 20 * 60

# Auto-publish phone dashboard/agents on a timer (config can override).
# Phone asked for current data from GROMIT around the clock, not RTH-only.
DEFAULT_PHONE_REFRESH_INTERVAL_MIN = 15
DEFAULT_PHONE_REFRESH_MARKET_HOURS_ONLY = False
DEFAULT_PHONE_REFRESH_ENABLED = True
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0 (Finance-phone-bridge/1.6.3)"}

# Phone "full data pull" flag for the current request (thread-local).
_pull_ctx = threading.local()

# Human rule (PHONE 2026-07-31): all P/L / chart / average calcs start here.
# Transfer/deposit capital only enters P/L math from each event's date forward.
# Human rule (PHONE): cash deposits + transferred positions ARE usable capital
# (equity, BP, sizing, sellable). They are not trading profit at book-in.
CALCULATION_START_ISO = "2026-07-24"

# Snapshot quality: never clobber a fuller book with a thin pull from a
# *different* account (e.g. #6854 1-lot vs #8804). Same-account live is truth
# even when the book shrank (sold down).
_MIN_POS_KEEP_RICHER = 3  # wrong-account thinner pulls only
_PREFERRED_ACCOUNT_TAIL = "8804"
# Public-mark overlay cache: fetched_at -> (monotonic ts, marked snap)
_MARKS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(line)
    print(line, end="")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# Phone UI: ASCII-only punctuation (blocks mojibake like a-circumflex garbage on handsets).
_PHONE_TEXT_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("\u00e2\u20ac\u00a2", "-"),
    ("\u00e2\u20ac\u201d", "-"),
    ("\u00e2\u20ac\u201c", "-"),
    ("\u00e2\u20ac\u00a6", "..."),
    ("\u00e2\u20ac\u2018", "-"),
    ("\u00e2\u20ac\u2019", "'"),
    ("\u00e2\u20ac\u0153", '"'),
    ("\u00e2\u20ac\u009d", '"'),
    ("\u00e2\u02c6\u2019", "-"),
    ("\u00e2\u2020\u2019", "->"),
    ("\u00c2\u00b7", " | "),
    ("\u2022", "-"),
    ("\u2014", "-"),
    ("\u2013", "-"),
    ("\u2026", "..."),
    ("\u00b7", " | "),
    ("\u2212", "-"),
    ("\u2192", "->"),
    ("\u2011", "-"),
    ("\u2018", "'"),
    ("\u2019", "'"),
    ("\u201c", '"'),
    ("\u201d", '"'),
)


def _phone_ascii_text(value: str) -> str:
    if not value:
        return value
    out = value
    for old, new in _PHONE_TEXT_REPLACEMENTS:
        if old in out:
            out = out.replace(old, new)
    return out.replace(" | ", " | ")


def _sanitize_phone_payload(obj: Any) -> Any:
    if isinstance(obj, str):
        return _phone_ascii_text(obj)
    if isinstance(obj, dict):
        return {k: _sanitize_phone_payload(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_phone_payload(v) for v in obj]
    return obj


def load_bridge_config() -> dict[str, Any]:
    raw = _read_json(BRIDGE_CONFIG)
    changed = False
    if not raw.get("bridge_token"):
        raw["bridge_token"] = secrets.token_urlsafe(18)
        changed = True
    if "port" not in raw:
        raw["port"] = DEFAULT_PORT
        changed = True
    if "host" not in raw:
        raw["host"] = DEFAULT_HOST
        changed = True
    # Phone pack auto-refresh (dashboard + agents -> Oxygen-OS work/phone)
    if "phone_refresh_enabled" not in raw:
        raw["phone_refresh_enabled"] = DEFAULT_PHONE_REFRESH_ENABLED
        changed = True
    if "phone_refresh_interval_minutes" not in raw:
        raw["phone_refresh_interval_minutes"] = DEFAULT_PHONE_REFRESH_INTERVAL_MIN
        changed = True
    if "phone_refresh_market_hours_only" not in raw:
        raw["phone_refresh_market_hours_only"] = DEFAULT_PHONE_REFRESH_MARKET_HOURS_ONLY
        changed = True
    if changed:
        _write_json(BRIDGE_CONFIG, raw)
        _log(f"Wrote {BRIDGE_CONFIG.name} (bridge defaults updated)")
    return raw


def _is_us_equity_rth() -> bool:
    """True during US regular session Mon-Fri 9:30-16:00 America/New_York."""
    from datetime import datetime, time as dt_time, timedelta, timezone

    now = None
    try:
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        try:
            from etrade_worker import is_us_market_open

            return bool(is_us_market_open())
        except Exception:
            # No tzdata / worker: approximate US Eastern from UTC (EDT Mar-Nov).
            now_utc = datetime.now(timezone.utc)
            offset_h = -4 if 3 <= now_utc.month <= 10 else -5
            now = now_utc + timedelta(hours=offset_h)
    if now is None:
        return False
    if now.weekday() >= 5:
        return False
    return dt_time(9, 30) <= now.time() <= dt_time(16, 0)


def run_phone_data_refresh(*, force_refresh: bool = True, reason: str = "scheduled") -> dict[str, Any]:
    """Rebuild + publish dashboard/agents pack for the phone (Oxygen-OS + bridge)."""
    from datetime import datetime, timezone

    started = time.time()
    result: dict[str, Any] = {
        "ok": False,
        "reason": reason,
        "at": datetime.now(timezone.utc).isoformat(),
        "market_open": _is_us_equity_rth(),
    }
    try:
        _log(f"phone auto-refresh starting ({reason}) force_refresh={force_refresh}...")
        # Dual-PC: pull latest broker snapshot/quotes from share before publish
        try:
            from sync_shared_data import pull_broker_feed

            pull = pull_broker_feed()
            result["broker_pull"] = {
                "ok": bool(pull.get("ok")),
                "copied": pull.get("copied"),
                "error": pull.get("error"),
            }
        except Exception as exc:
            result["broker_pull"] = {"ok": False, "error": str(exc)}

        full = build_full_for_phone(force_refresh=force_refresh)
        dash = full.get("dashboard") if isinstance(full, dict) else {}
        if not isinstance(dash, dict):
            dash = {}
        agents = full.get("agents") if isinstance(full, dict) else {}
        if not isinstance(agents, dict):
            agents = {}
        result.update(
            {
                "ok": bool(full.get("ok", True) if isinstance(full, dict) else True),
                "positions": len(dash.get("positions") or []),
                "data_pull": dash.get("data_pull"),
                "long_mode": (dash.get("long") or {}).get("mode")
                if isinstance(dash.get("long"), dict)
                else None,
                "agent_count": agents.get("agent_count")
                or agents.get("count")
                or len(agents.get("agents") or []),
                "elapsed_sec": round(time.time() - started, 2),
            }
        )
        _log(
            f"phone auto-refresh ({reason}): ok={result['ok']} "
            f"pos={result.get('positions')} agents={result.get('agent_count')} "
            f"market_open={result['market_open']} {result.get('elapsed_sec')}s"
        )
    except Exception as exc:
        result["error"] = str(exc)
        _log(f"phone auto-refresh failed ({reason}): {exc}")
        _log(traceback.format_exc())
    try:
        _write_json(ROOT / "output" / "phone_refresh_last.json", result)
    except OSError:
        pass
    return result


def start_phone_refresh_thread(cfg: dict[str, Any] | None = None) -> threading.Thread | None:
    """Background loop: refresh phone pack every N minutes during market hours."""
    cfg = cfg or load_bridge_config()
    if not bool(cfg.get("phone_refresh_enabled", DEFAULT_PHONE_REFRESH_ENABLED)):
        _log("phone auto-refresh disabled (phone_refresh_enabled=false)")
        return None
    try:
        interval_min = float(
            cfg.get("phone_refresh_interval_minutes") or DEFAULT_PHONE_REFRESH_INTERVAL_MIN
        )
    except (TypeError, ValueError):
        interval_min = float(DEFAULT_PHONE_REFRESH_INTERVAL_MIN)
    interval_min = max(5.0, interval_min)  # floor 5 min to avoid thrash
    market_only = bool(
        cfg.get("phone_refresh_market_hours_only", DEFAULT_PHONE_REFRESH_MARKET_HOURS_ONLY)
    )
    interval_sec = interval_min * 60.0

    def _loop() -> None:
        _log(
            f"phone auto-refresh started: every {interval_min:g} min, "
            f"market_hours_only={market_only}"
        )
        # Short delay so HTTP server is up first
        time.sleep(15.0)
        last_run = 0.0
        # First pass as soon as eligible (do not wait a full interval after boot)
        while True:
            try:
                open_now = _is_us_equity_rth()
                never_ran = last_run <= 0.0
                due = never_ran or (time.time() - last_run) >= interval_sec
                should = due and (open_now or not market_only)
                if should:
                    reason = "startup" if never_ran else (
                        "rth_timer" if open_now else "offhours_timer"
                    )
                    run_phone_data_refresh(force_refresh=True, reason=reason)
                    last_run = time.time()
                    time.sleep(min(60.0, interval_sec))
                else:
                    # Wake often enough to catch the open / next slot
                    if market_only and not open_now:
                        time.sleep(60.0)
                    else:
                        remaining = max(5.0, interval_sec - (time.time() - last_run))
                        time.sleep(min(60.0, remaining))
            except Exception as exc:
                _log(f"phone auto-refresh loop error: {exc}")
                time.sleep(60.0)

    thread = threading.Thread(
        target=_loop,
        name="phone-data-refresh",
        daemon=True,
    )
    thread.start()
    return thread


def _snapshot_position_count(snap: dict[str, Any] | None) -> int:
    if not isinstance(snap, dict):
        return 0
    pos = snap.get("positions")
    return len(pos) if isinstance(pos, list) else 0


def _snapshot_age_sec(snap: dict[str, Any] | None) -> float | None:
    """Age of fetched_at in seconds, or None if unknown."""
    if not isinstance(snap, dict):
        return None
    fetched = str(snap.get("fetched_at") or "").strip()
    if not fetched:
        return None
    try:
        from datetime import datetime, timezone

        ts = fetched.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()
    except Exception:
        return None


def _is_held_lot(row: Any) -> bool:
    """True for a real broker lot (qty != 0), not a TARGET / idea stub."""
    if not isinstance(row, dict):
        return False
    if str(row.get("side") or "").upper() == "TARGET":
        return False
    status = str(row.get("proposed_status") or "").strip().lower()
    if status in ("idea", "target"):
        return False
    action = str(row.get("proposed_action") or "").upper()
    if "TARGET" in action and (_f(row.get("quantity")) or 0.0) == 0.0:
        return False
    return (_f(row.get("quantity")) or 0.0) != 0.0


def _pack_held_lot_count(pack: dict[str, Any] | None) -> int:
    """Held broker lots in a phone pack. Never use idea-row count as quality."""
    if not isinstance(pack, dict):
        return 0
    rows = pack.get("positions") if isinstance(pack.get("positions"), list) else []
    counted = sum(1 for row in rows if _is_held_lot(row))
    if counted > 0:
        return counted
    port = pack.get("portfolio") if isinstance(pack.get("portfolio"), dict) else {}
    for key in ("held_position_count", "position_count"):
        raw = port.get(key)
        try:
            n = int(raw)
        except (TypeError, ValueError):
            continue
        if n > 0:
            return n
    pull = pack.get("data_pull") if isinstance(pack.get("data_pull"), dict) else {}
    try:
        n = int(pull.get("held_position_count") or 0)
    except (TypeError, ValueError):
        n = 0
    return n if n > 0 else 0


def _iso_age_sec(value: Any) -> float | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        from datetime import datetime, timezone

        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds()
    except Exception:
        return None


def _yahoo_last_price(symbol: str, timeout: float = 8.0) -> float | None:
    """Last regular-market price from Yahoo chart meta (no E*TRADE session)."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return None
    try:
        import requests

        resp = requests.get(
            YAHOO_CHART_URL.format(symbol=sym),
            params={"range": "5d", "interval": "1d"},
            headers=YAHOO_HEADERS,
            timeout=timeout,
        )
        if resp.status_code != 200:
            return None
        result = (resp.json().get("chart") or {}).get("result") or []
        if not result:
            return None
        meta = result[0].get("meta") if isinstance(result[0], dict) else {}
        px = (meta or {}).get("regularMarketPrice")
        if px is None:
            closes = ((result[0].get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
            for val in reversed(closes):
                if val is not None:
                    px = val
                    break
        out = float(px)
        return out if out > 0 else None
    except Exception:
        return None


def _latest_public_quotes(symbols: list[str], *, overall_timeout: float = 20.0) -> dict[str, float]:
    """Best-effort Yahoo last prices for held lots when the broker session is down."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    uniq: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        sym = str(raw or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        uniq.append(sym)
    if not uniq:
        return {}
    out: dict[str, float] = {}
    workers = min(8, len(uniq))
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_yahoo_last_price, sym): sym for sym in uniq}
            try:
                for fut in as_completed(futs, timeout=overall_timeout):
                    sym = futs[fut]
                    try:
                        px = fut.result()
                    except Exception:
                        px = None
                    if px is not None and px > 0:
                        out[sym] = px
            except TimeoutError:
                pass
    except Exception as exc:
        _log(f"public quote overlay skipped: {exc}")
    return out


def _overlay_public_marks(snap: dict[str, Any] | None) -> dict[str, Any]:
    """Mark a stale broker snapshot with public last prices so the phone is not frozen.

    Does not overwrite output/account_snapshot.json (that stays the last E*TRADE book).
    Skips when the broker pull itself is fresh.
    """
    if not isinstance(snap, dict):
        return {}
    positions = snap.get("positions")
    if not isinstance(positions, list) or not positions:
        return dict(snap)
    marks_age = _iso_age_sec(snap.get("marks_updated_at"))
    if marks_age is not None and 0 <= marks_age < 600:
        return dict(snap)
    cache_key = str(snap.get("fetched_at") or "none")
    cached = _MARKS_CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < 600:
        return dict(cached[1])
    broker_age = _snapshot_age_sec(snap)
    if broker_age is not None and 0 <= broker_age < 900:
        return dict(snap)
    symbols = [
        str(row.get("symbol") or "")
        for row in positions
        if _is_held_lot(row)
    ]
    quotes = _latest_public_quotes(symbols)
    if not quotes:
        return dict(snap)
    from datetime import datetime, timezone

    marked: list[dict[str, Any]] = []
    applied = 0
    mv_sum = 0.0
    for row in positions:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        sym = str(item.get("symbol") or "").strip().upper()
        px = quotes.get(sym)
        qty = _f(item.get("quantity"))
        if px is not None and _is_held_lot(item) and qty:
            item["price"] = round(px, 6)
            item["market_value"] = round(qty * px, 4)
            cost = _f(item.get("cost_basis"))
            if cost:
                item["unrealized_pl"] = round(item["market_value"] - cost * qty, 4)
                if qty:
                    item["unrealized_pl_pct"] = round((px / cost - 1.0) * 100.0, 4) if cost else None
            applied += 1
        mv_sum += abs(_f(item.get("market_value")) or 0.0)
        marked.append(item)
    out = dict(snap)
    out["positions"] = marked
    out["marks_updated_at"] = datetime.now(timezone.utc).isoformat()
    out["marks_source"] = "yahoo_public"
    out["marks_count"] = applied
    bal = dict(out.get("balance") or {}) if isinstance(out.get("balance"), dict) else {}
    cash = _f(bal.get("cash")) if bal.get("cash") is not None else None
    if cash is not None:
        bal["total_account_value"] = round(cash + mv_sum, 4)
        out["balance"] = bal
    _log(f"public marks overlay: {applied}/{len(symbols)} lots from Yahoo")
    _MARKS_CACHE[cache_key] = (time.time(), out)
    return out


def _phone_snapshot(snap: dict[str, Any] | None) -> dict[str, Any]:
    """Snapshot served to the phone: broker book + public marks when session is stale."""
    base = dict(snap) if isinstance(snap, dict) else {}
    marked = _overlay_public_marks(base)
    if marked.get("marks_updated_at"):
        _set_pull_meta(
            marks_updated_at=marked.get("marks_updated_at"),
            marks_source=marked.get("marks_source"),
            marks_count=int(marked.get("marks_count") or 0),
        )
    return marked


def _oxygen_dashboard_path() -> Path:
    return (
        Path.home()
        / "Documents"
        / "GitHub"
        / "Oxygen-OS"
        / "work"
        / "phone"
        / "etrade-dashboard.json"
    )


def _snapshot_quality(snap: dict[str, Any] | None) -> tuple[int, float]:
    """Higher is better: (position_count, -age_seconds). Missing age -> treat as old."""
    n = _snapshot_position_count(snap)
    age = _snapshot_age_sec(snap)
    age_score = -(age if age is not None and age >= 0 else 1e12)
    return (n, age_score)


def _prefer_snapshot(
    a: dict[str, Any] | None,
    b: dict[str, Any] | None,
) -> dict[str, Any]:
    """Pick the stronger of two snapshots (more lots first, then fresher)."""
    if not a and not b:
        return {}
    if not a:
        return dict(b or {})
    if not b:
        return dict(a)
    return dict(a if _snapshot_quality(a) >= _snapshot_quality(b) else b)


def _path_is_unc(path: Path) -> bool:
    """True for SMB/UNC paths. is_file() on a dead host hangs ~20s and stalls /health."""
    text = str(path)
    return text.startswith("\\\\") or text.startswith("//")


def _shared_broker_snapshot_paths() -> list[Path]:
    """Local-only broker snapshot paths. Never probe retired BOXONE UNC shares."""
    paths: list[Path] = []
    try:
        from deployment import load_deployment

        dep = load_deployment()
        root = str(dep.get("shared_root") or "").strip()
        if root:
            candidate = Path(root) / "broker" / "account_snapshot.json"
            if not _path_is_unc(candidate):
                paths.append(candidate)
    except Exception:
        pass
    # Local HelperDrop only. GROMIT is sole Finance host; UNC to 10.10.10.1 hangs /health.
    local_share = Path(r"C:\Users\Public\HelperDrop\FinanceShare\broker\account_snapshot.json")
    if local_share not in paths:
        paths.append(local_share)
    return paths


def _load_shared_broker_snapshot() -> dict[str, Any]:
    """Best broker snapshot from a local share path (never UNC)."""
    best: dict[str, Any] = {}
    best_src = ""
    for path in _shared_broker_snapshot_paths():
        try:
            if _path_is_unc(path) or not path.is_file():
                continue
            data = _read_json(path)
            if _snapshot_position_count(data) <= 0 and not data.get("balance"):
                continue
            if _snapshot_quality(data) > _snapshot_quality(best):
                best = dict(data)
                best["_snapshot_path"] = str(path)
                best_src = str(path)
        except Exception:
            continue
    if best and best_src:
        best.setdefault("source", "shared_broker")
        best["_loaded_from"] = best_src
    return best


def _load_account_snapshot() -> dict[str, Any]:
    """Best available broker snapshot: local output + dual-PC share.

    Role flip B: AI-CODING is often pipeline (thin/no tokens); BOXONE writes
    full lots to share broker/. Prefer the fuller book so the phone never
    sees a 1-lot stub when 14 lots exist on the share.
    """
    local = _read_json(ROOT / "output" / "account_snapshot.json")
    shared = _load_shared_broker_snapshot()
    chosen = _prefer_snapshot(local, shared)
    if not chosen:
        return {}
    # Tag which source won (for data_pull / health)
    if shared and _snapshot_quality(shared) > _snapshot_quality(local):
        chosen.setdefault("source", "shared_broker")
        chosen["_chosen_from"] = "shared_broker"
        # Heal thin local so future cache hits and other tools see the full book
        local_n = _snapshot_position_count(local)
        shared_n = _snapshot_position_count(shared)
        if shared_n >= _MIN_POS_KEEP_RICHER and shared_n > local_n:
            try:
                to_write = {
                    k: v
                    for k, v in chosen.items()
                    if not str(k).startswith("_")
                }
                to_write["source"] = "shared_broker_healed"
                _write_json(ROOT / "output" / "account_snapshot.json", to_write)
                _log(
                    f"healed local account_snapshot from share "
                    f"({local_n} -> {shared_n} lots)"
                )
            except Exception as exc:
                _log(f"heal local snapshot skipped: {exc}")
    else:
        chosen.setdefault("source", local.get("source") or "local_account_snapshot")
        chosen["_chosen_from"] = "local"
    return chosen


def _freshness_from_refresh() -> tuple[float | None, str | None]:
    """Age of last GROMIT phone pack: public marks, else refresh timestamp."""
    last = _read_json(ROOT / "output" / "phone_refresh_last.json")
    if not isinstance(last, dict) or not last:
        return None, None
    pull = last.get("data_pull") if isinstance(last.get("data_pull"), dict) else {}
    marks_at = pull.get("marks_updated_at")
    marks_age = _iso_age_sec(marks_at)
    if marks_age is not None:
        source = str(pull.get("marks_source") or "marks")
        return marks_age, source
    refresh_age = _iso_age_sec(last.get("at"))
    if refresh_age is not None:
        return refresh_age, "refresh"
    return None, None


def _data_quality_report() -> dict[str, Any]:
    """Non-secret snapshot quality for /health. Local files only (no SMB)."""
    local = _read_json(ROOT / "output" / "account_snapshot.json")
    role = "all"
    try:
        from deployment import load_deployment

        role = str(load_deployment().get("role") or "all")
    except Exception:
        pass
    broker_age = _snapshot_age_sec(local)
    marks_age, marks_source = _freshness_from_refresh()
    serving_age = marks_age if marks_age is not None else broker_age
    current = serving_age is not None and 0 <= serving_age < DATA_CURRENT_MAX_SEC
    return {
        "role": role,
        "local_positions": _snapshot_position_count(local),
        "local_age_sec": broker_age,
        "shared_positions": 0,
        "shared_age_sec": None,
        "broker_age_sec": broker_age,
        "marks_age_sec": marks_age,
        "marks_source": marks_source,
        "serving_positions": _snapshot_position_count(local),
        "serving_age_sec": serving_age,
        "serving_source": marks_source
        or local.get("_chosen_from")
        or local.get("source")
        or ("none" if not local else "unknown"),
        "strong": _snapshot_position_count(local) >= _MIN_POS_KEEP_RICHER,
        "data_current": current,
    }


def _last_pull_meta() -> dict[str, Any]:
    meta = getattr(_pull_ctx, "meta", None)
    return meta if isinstance(meta, dict) else {}


def _set_pull_meta(**kwargs: Any) -> None:
    cur = dict(_last_pull_meta())
    cur.update(kwargs)
    _pull_ctx.meta = cur


def same_broker_account(live_key: str, live_label: str, prior: dict[str, Any]) -> bool:
    """True when a live pull is the same brokerage book as the cached snapshot."""
    if not isinstance(prior, dict) or not prior:
        return True
    key = str(live_key or "").strip()
    prior_key = str(prior.get("account_id_key") or "").strip()
    if key and prior_key and key == prior_key:
        return True
    live_lab = str(live_label or prior.get("display_label") or "")
    prior_lab = str(prior.get("display_label") or prior.get("account_name") or "")

    def _has_preferred_tail(text: str) -> bool:
        t = (text or "").replace("|", "·")
        tail = _PREFERRED_ACCOUNT_TAIL
        return f"#{tail}" in t or t.rstrip().endswith(tail)

    if _has_preferred_tail(live_lab) and _has_preferred_tail(prior_lab):
        return True
    return False


def try_refresh_account_snapshot(
    max_age_sec: float = 300.0,
    force: bool = False,
) -> dict[str, Any]:
    """Best-effort live E*TRADE portfolio pull into output/account_snapshot.json.

    Phone "full data pull from PC" needs real lots + qty, not offline TARGET stubs.
    When force=True (phone Refresh / /api/full?refresh=1), always attempt a live pull.

    Quality gate: never overwrite a fuller snapshot with a thinner live response
    from a *different* account (partial OAuth / accounts[0] vs #8804). A thinner
    book on the same selected account is the real E*TRADE book and must replace
    the stale snapshot so the phone matches the broker.
    """
    snap_path = ROOT / "output" / "account_snapshot.json"
    prior = _load_account_snapshot()
    prior_n = _snapshot_position_count(prior)

    if not force:
        try:
            fetched = str(prior.get("fetched_at") or "")
            if fetched and prior_n > 0:
                age = _snapshot_age_sec(prior)
                if age is not None and 0 <= age < max_age_sec:
                    _set_pull_meta(
                        live=False,
                        source=str(prior.get("_chosen_from") or prior.get("source") or "account_snapshot_cache"),
                        fetched_at=fetched,
                        position_count=prior_n,
                        message=(
                            f"Using recent snapshot ({prior_n} lots, "
                            f"source={prior.get('_chosen_from') or prior.get('source') or 'cache'})"
                        ),
                    )
                    return _phone_snapshot(prior)
        except Exception:
            pass

    try:
        from etrade_api.client import ETradeClient
        from etrade_api.config import ETradeConfig

        cfg = None
        if hasattr(ETradeConfig, "load"):
            try:
                cfg = ETradeConfig.load(LONG_CONFIG)
            except Exception:
                cfg = None
        if cfg is None:
            try:
                from etrade_api.config import load_config

                cfg = load_config(LONG_CONFIG)
            except Exception:
                cfg = None
        if cfg is None:
            _set_pull_meta(
                live=False,
                source=str(prior.get("_chosen_from") or "account_snapshot"),
                error="No E*TRADE config on PC",
                position_count=prior_n,
                fetched_at=prior.get("fetched_at"),
                message="No local API config - serving best local/share snapshot",
            )
            return _phone_snapshot(prior)
        client = ETradeClient(cfg)
        accounts: list[Any] = []
        if hasattr(client, "list_accounts"):
            try:
                accounts = client.list_accounts() or []
            except Exception:
                accounts = []
        # Prefer config selected_account (same as etrade_worker). accounts[0] is often
        # a secondary 1-lot account (#6854) while the live book is on #8804.
        key = ""
        label = ""
        try:
            from etrade_api.config import get_selected_account

            selected = get_selected_account(LONG_CONFIG)
        except Exception:
            selected = None
        if isinstance(selected, dict):
            key = str(selected.get("account_id_key") or "").strip()
            label = str(selected.get("display_label") or "").strip()
        if key and accounts:
            match = next(
                (
                    a
                    for a in accounts
                    if isinstance(a, dict)
                    and str(a.get("account_id_key") or "").strip() == key
                ),
                None,
            )
            if match:
                label = str(
                    match.get("display_label")
                    or match.get("account_name")
                    or label
                )
        if not key and accounts and isinstance(accounts[0], dict):
            key = str(accounts[0].get("account_id_key") or "").strip()
            label = str(
                accounts[0].get("display_label")
                or accounts[0].get("account_name")
                or ""
            )
        if not key:
            key = str(prior.get("account_id_key") or "").strip()
            label = str(prior.get("display_label") or "")
        if not key:
            _set_pull_meta(
                live=False,
                source=str(prior.get("_chosen_from") or "account_snapshot"),
                error="No account id on PC",
                position_count=prior_n,
                fetched_at=prior.get("fetched_at"),
                message="No account id - serving best local/share snapshot",
            )
            return _phone_snapshot(prior)
        _log(
            f"live pull account={label or key[:12]} "
            f"(selected={bool(selected and selected.get('account_id_key'))})"
        )
        balance = client.get_balance(key) or {}
        positions = client.get_portfolio(key) or []
        live_n = len(positions) if isinstance(positions, list) else 0
        same = same_broker_account(key, label, prior)
        if live_n == 0 and prior_n > 0 and (not same or not balance):
            _set_pull_meta(
                live=False,
                source=str(prior.get("_chosen_from") or "account_snapshot"),
                error="Live portfolio empty - kept prior/share snapshot",
                position_count=prior_n,
                fetched_at=prior.get("fetched_at"),
                message="Live empty - kept fuller snapshot",
            )
            return _phone_snapshot(prior)
        # Wrong-account protection only. Same selected book is E*TRADE truth.
        if (
            prior_n >= _MIN_POS_KEEP_RICHER
            and live_n < prior_n
            and not same
        ):
            _log(
                f"live pull thinner ({live_n} < prior {prior_n}) "
                f"account={label or key[:12]} - keeping fuller snapshot "
                f"(different account)"
            )
            _set_pull_meta(
                live=False,
                source=str(prior.get("_chosen_from") or "account_snapshot"),
                error=f"Live pull only {live_n} lots vs prior {prior_n}",
                position_count=prior_n,
                fetched_at=prior.get("fetched_at"),
                message=(
                    f"Kept fuller snapshot ({prior_n} lots); "
                    f"live returned {live_n} on {label or 'account'} "
                    f"(check selected_account if wrong book)"
                ),
            )
            return _phone_snapshot(prior)
        if prior_n >= _MIN_POS_KEEP_RICHER and live_n < prior_n and same:
            _log(
                f"live pull same account thinner ({live_n} < prior {prior_n}) "
                f"account={label or key[:12]} - accepting live E*TRADE book"
            )

        from datetime import datetime, timezone

        snap = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "account_id_key": key,
            "display_label": label or prior.get("display_label"),
            "balance": {
                "total_account_value": balance.get("total_account_value"),
                "cash_buying_power": balance.get("cash_buying_power")
                or balance.get("buying_power"),
                "cash": balance.get("cash"),
            },
            "positions": positions if isinstance(positions, list) else [],
            "sandbox": bool(getattr(getattr(client, "config", None), "sandbox", False)),
            "source": "phone_bridge_live_pull",
        }
        _write_json(snap_path, snap)
        _log(f"account_snapshot refreshed live: {len(snap['positions'])} positions")
        _set_pull_meta(
            live=True,
            source="phone_bridge_live_pull",
            fetched_at=snap["fetched_at"],
            position_count=len(snap["positions"]),
            message="Live full PC pull OK",
        )
        return snap
    except Exception as exc:
        _log(f"live account_snapshot refresh skipped: {exc}")
        _set_pull_meta(
            live=False,
            source=str(prior.get("_chosen_from") or "account_snapshot"),
            error=str(exc),
            position_count=prior_n,
            fetched_at=prior.get("fetched_at"),
            message="PC live pull failed - serving best local/share snapshot",
        )
        return _phone_snapshot(prior)


def _publish_dashboard_to_oxygen(payload: dict[str, Any]) -> None:
    """Write non-secret dashboard JSON for phone GitHub bus (cellular path).

    Quality gate: never replace a richer HELD-LOT book with a collapse
    (e.g. 1-lot stub overwriting 14-lot broker publish). Idea-row count
    fluctuates and must not block a regular GROMIT refresh.
    """
    try:
        oxygen = _oxygen_dashboard_path()
        oxygen.parent.mkdir(parents=True, exist_ok=True)

        new_n = _pack_held_lot_count(payload)
        if oxygen.is_file():
            try:
                prev = json.loads(oxygen.read_text(encoding="utf-8-sig"))
                if isinstance(prev, dict):
                    old_n = _pack_held_lot_count(prev)
                    # Collapse only: fewer than half the held lots from a non-live
                    # (Yahoo/stale) rebuild. Live same-account books must publish.
                    if (
                        old_n >= _MIN_POS_KEEP_RICHER
                        and new_n < old_n
                        and new_n < max(1, old_n // 2)
                    ):
                        pull = payload.get("data_pull") if isinstance(payload.get("data_pull"), dict) else {}
                        if pull.get("live"):
                            _log(
                                f"oxygen publish live book {new_n} lots "
                                f"(was {old_n}) - replacing stale pack"
                            )
                        else:
                            _log(
                                f"oxygen publish skipped: held lots {new_n} << prior {old_n} "
                                f"(non-live collapse)"
                            )
                            return
            except (OSError, json.JSONDecodeError, TypeError):
                pass
        # Atomic write so phone/GitHub never reads half a file
        safe = _sanitize_phone_payload(payload)
        if not isinstance(safe, dict):
            safe = payload
        tmp = oxygen.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(safe, indent=2, default=str), encoding="utf-8")
        tmp.replace(oxygen)
        _log(f"published dashboard -> {oxygen} ({new_n} held lots)")
    except Exception as exc:
        _log(f"oxygen dashboard publish failed: {exc}")


def phone_ui_info_enabled() -> bool:
    """Outbound phone UI info (agents + analysis publish). Default True; set false to stop."""
    cfg = load_bridge_config()
    if "phone_ui_info_enabled" not in cfg:
        return True
    return bool(cfg.get("phone_ui_info_enabled"))


def _load_transfer_deposit_symbols() -> set[str]:
    """All known transfer-as-deposit symbols (defaults + cost overrides + learned file)."""
    symbols: set[str] = {
        "SPCX", "SAGMF", "PRBLX", "PHYZX", "TAIBX", "ETBOX", "ETMUX", "DHT", "PLBL",
    }
    # Cost overrides
    try:
        ov_path = ROOT / "output" / "position_cost_overrides.json"
        if ov_path.exists():
            raw = json.loads(ov_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for sym, meta in raw.items():
                    if not isinstance(meta, dict):
                        continue
                    s = str(sym or "").upper().strip()
                    if not s:
                        continue
                    reason = str(meta.get("reason") or "").lower()
                    if meta.get("transfer_as_deposit") is True or "acats" in reason or "transfer" in reason:
                        symbols.add(s)
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    # Learned set (future ACATS lots)
    try:
        learn_path = ROOT / "output" / "transfer_deposit_symbols.json"
        if learn_path.exists():
            raw = json.loads(learn_path.read_text(encoding="utf-8"))
            rows = raw if isinstance(raw, list) else (raw.get("symbols") if isinstance(raw, dict) else [])
            if isinstance(rows, list):
                for item in rows:
                    s = str(item or "").upper().strip()
                    if s:
                        symbols.add(s)
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return symbols


def remember_transfer_deposit_symbols(new_symbols: set[str] | list[str]) -> None:
    """Persist newly detected transfer lots so all future P/L treats them as deposits."""
    known = _load_transfer_deposit_symbols()
    added = {str(s).upper().strip() for s in new_symbols if str(s).strip()} - known
    if not added:
        return
    learn_path = ROOT / "output" / "transfer_deposit_symbols.json"
    existing: list[str] = []
    try:
        if learn_path.exists():
            raw = json.loads(learn_path.read_text(encoding="utf-8"))
            rows = raw if isinstance(raw, list) else (raw.get("symbols") if isinstance(raw, dict) else [])
            if isinstance(rows, list):
                existing = [str(x).upper().strip() for x in rows if str(x).strip()]
    except (OSError, json.JSONDecodeError):
        existing = []
    merged = sorted(set(existing) | added)
    learn_path.parent.mkdir(parents=True, exist_ok=True)
    learn_path.write_text(
        json.dumps(
            {
                "symbols": merged,
                "note": (
                    "Auto-learned ACATS/transfer lots - deposit capital at book-in "
                    "($0 open P/L). Still usable capital (equity/BP/sellable)."
                ),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    # Also stamp cost overrides so GUI/bridge stay aligned
    try:
        ov_path = ROOT / "output" / "position_cost_overrides.json"
        ov: dict = {}
        if ov_path.exists():
            raw = json.loads(ov_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                ov = raw
        changed = False
        for sym in added:
            row = ov.get(sym) if isinstance(ov.get(sym), dict) else {}
            if not row.get("transfer_as_deposit"):
                row = dict(row)
                row["transfer_as_deposit"] = True
                row["usable_as_capital"] = True
                row.setdefault(
                    "reason",
                    "Inbound transfer - deposit capital (usable); zero open P/L at book-in",
                )
                row["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                ov[sym] = row
                changed = True
        if changed:
            ov_path.parent.mkdir(parents=True, exist_ok=True)
            ov_path.write_text(json.dumps(ov, indent=2), encoding="utf-8")
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    _log(f"Learned transfer-as-deposit symbols: {sorted(added)}")


def _mode(dry: bool, auto: bool, paused: bool) -> str:

    if paused:
        return "STOPPED"
    if dry:
        return "PRACTICE"
    if auto:
        return "LIVE AUTO"
    return "LIVE MANUAL"


def _shorten(text: str, n: int) -> str:
    t = str(text or "")
    return t if len(t) <= n else t[: n - 1] + "..."


def _f(val: Any, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _opt_num(val: Any) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return value
    return []


def _epoch_ms(val: Any) -> int | None:
    if val is None or val == "":
        return None
    try:
        n = int(float(val))
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    # E*TRADE sometimes returns seconds.
    if n < 1_000_000_000_000:
        n *= 1000
    return n


def _format_placed(ms: int | None) -> str:
    if not ms:
        return "-"
    try:
        return time.strftime("%b %d %I:%M %p", time.localtime(ms / 1000.0))
    except (OverflowError, OSError, ValueError):
        return "-"


def _price_display(
    price_type: str | None,
    limit_p: float | None,
    stop_p: float | None,
    avg_p: float | None,
) -> str:
    pt = str(price_type or "").upper()
    if avg_p:
        return _money(avg_p)
    if "STOP" in pt and "LIMIT" in pt and stop_p is not None and limit_p is not None:
        return f"Stop {_money(stop_p)} / Lmt {_money(limit_p)}"
    if "STOP" in pt and stop_p is not None:
        return f"Stop {_money(stop_p)}"
    if "LIMIT" in pt and limit_p is not None:
        return _money(limit_p)
    if "MARKET" in pt:
        return "MKT"
    if limit_p is not None:
        return _money(limit_p)
    if stop_p is not None:
        return _money(stop_p)
    return "-"


def flatten_etrade_orders(raw: list[Any] | None) -> list[dict[str, Any]]:
    """Turn nested E*TRADE Order / OrderDetail / Instrument rows into phone cards.

    Live List Orders payloads keep symbol/action/status under OrderDetail, not
    the top-level Order. Without this, the phone Orders window is empty dashes.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for order in raw or []:
        if not isinstance(order, dict):
            continue
        details = _as_list(order.get("OrderDetail") or order.get("details"))
        if not details:
            details = [order]
        for detail in details:
            if not isinstance(detail, dict):
                continue
            instruments = _as_list(
                detail.get("Instrument") or order.get("Instrument")
            )
            if not instruments:
                instruments = [{}]
            for inst in instruments:
                if not isinstance(inst, dict):
                    inst = {}
                product = inst.get("Product") if isinstance(inst.get("Product"), dict) else {}
                symbol = str(
                    product.get("symbol")
                    or inst.get("symbol")
                    or order.get("symbol")
                    or "-"
                ).upper()
                if not symbol:
                    symbol = "-"
                action = str(
                    inst.get("orderAction")
                    or inst.get("action")
                    or detail.get("orderAction")
                    or order.get("action")
                    or "-"
                ).upper()
                status = str(
                    detail.get("status")
                    or order.get("status")
                    or order.get("orderStatus")
                    or "-"
                ).upper()
                oid = str(
                    order.get("orderId")
                    or order.get("order_id")
                    or order.get("orderNumber")
                    or detail.get("orderId")
                    or ""
                )
                qty = _opt_num(
                    inst.get("orderedQuantity")
                    if inst.get("orderedQuantity") is not None
                    else inst.get("quantity")
                    if inst.get("quantity") is not None
                    else order.get("quantity")
                )
                filled = _opt_num(
                    inst.get("filledQuantity")
                    if inst.get("filledQuantity") is not None
                    else order.get("filled_quantity")
                )
                limit_p = _opt_num(
                    detail.get("limitPrice")
                    if detail.get("limitPrice") is not None
                    else order.get("limitPrice") or order.get("limit_price")
                )
                stop_p = _opt_num(
                    detail.get("stopPrice")
                    if detail.get("stopPrice") is not None
                    else order.get("stopPrice") or order.get("stop_price")
                )
                avg_p = _opt_num(
                    inst.get("averageExecutionPrice")
                    if inst.get("averageExecutionPrice") is not None
                    else order.get("average_fill_price")
                )
                price_type = (
                    detail.get("priceType")
                    or order.get("priceType")
                    or order.get("price_type")
                )
                value = _opt_num(detail.get("orderValue") or order.get("orderValue"))
                if value is None:
                    px = avg_p if avg_p is not None else limit_p if limit_p is not None else stop_p
                    if qty is not None and px is not None:
                        value = abs(qty) * float(px)
                placed_ms = _epoch_ms(
                    detail.get("placedTime")
                    or detail.get("placedTimeStamp")
                    or order.get("placedTime")
                    or order.get("placed_time_ms")
                )
                executed_ms = _epoch_ms(
                    detail.get("executedTime")
                    or detail.get("executedTimeStamp")
                    or order.get("executed_time_ms")
                )
                dedupe = oid or f"{symbol}-{action}-{status}-{placed_ms or 0}"
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                desc = str(inst.get("symbolDescription") or "").strip() or None
                out.append(
                    {
                        "order_id": oid or f"{symbol}-{status}",
                        "symbol": symbol,
                        "action": action,
                        "status": status,
                        "quantity": qty,
                        "filled_quantity": filled,
                        "price_type": price_type,
                        "limit_price": limit_p,
                        "stop_price": stop_p,
                        "average_fill_price": avg_p,
                        "order_term": detail.get("orderTerm") or order.get("orderTerm"),
                        "market_session": detail.get("marketSession")
                        or order.get("marketSession"),
                        "order_type": order.get("orderType") or order.get("order_type"),
                        "order_value": value,
                        "placed_time_ms": placed_ms,
                        "executed_time_ms": executed_ms,
                        "description": desc,
                        "display": {
                            "quantity": f"{qty:g}" if qty is not None else "-",
                            "filled": f"{filled:g}" if filled is not None else "-",
                            "price": _price_display(price_type, limit_p, stop_p, avg_p),
                            "value": _money(value) if value is not None else "-",
                            "status": status,
                            "action": action,
                            "placed": _format_placed(placed_ms),
                        },
                    }
                )
    return out


def _call_list_orders(client: Any, key: str, status: str | None) -> list[Any]:
    if hasattr(client, "list_orders"):
        try:
            return client.list_orders(key, status=status, count=100) or []
        except TypeError:
            return client.list_orders(key) or []
    for meth in ("get_orders", "get_order_list"):
        if hasattr(client, meth):
            return getattr(client, meth)(key) or []
    return []


def _money(n: float | None) -> str:
    if n is None:
        return "-"
    return f"${n:,.2f}"


def _pct(n: float | None) -> str:
    if n is None:
        return "-"
    sign = "+" if n > 0 else ""
    return f"{sign}{n:.2f}%"


def _is_plausible_day_pl(day_pl: float | None, account_value: float | None) -> bool:
    """Reject day P/L that looks like a deposit-as-profit artifact."""
    if day_pl is None:
        return False
    if account_value is not None and account_value > 0 and abs(day_pl) > account_value * 0.40:
        return False
    return abs(day_pl) < 50_000


def _snapshot_is_live_broker(snap: dict[str, Any]) -> bool:
    src = str(snap.get("source") or "").lower()
    if "live" in src or src in {"phone_bridge_live_pull", "etrade_worker"}:
        return True
    age = _snapshot_age_sec(snap)
    return age is not None and 0 <= age < 3600


def _overlay_live_broker_account(out: dict[str, Any], snap: dict[str, Any]) -> None:
    """E*TRADE snapshot is the phone equity/cash source when it is the live book."""
    if not isinstance(out, dict) or not isinstance(snap, dict) or not snap:
        return
    live = _snapshot_is_live_broker(snap)
    bal_block = snap.get("balance") if isinstance(snap.get("balance"), dict) else {}
    snap_bal = _f(bal_block.get("total_account_value"))
    cur_bal = _f(out.get("balance"))
    if snap_bal is not None and snap_bal > 0:
        if live or cur_bal is None or cur_bal <= 0:
            out["balance"] = snap_bal
        elif snap_bal >= cur_bal:
            out["balance"] = snap_bal
    elif snap_bal is not None and out.get("balance") is None:
        out["balance"] = snap_bal
    snap_cash = _f(bal_block.get("cash_buying_power") or bal_block.get("cash"))
    if snap_cash is not None:
        if live or out.get("cash") is None or _f(out.get("cash"), 0) <= 0:
            out["cash"] = snap_cash
    label = str(snap.get("display_label") or "").strip()
    key = str(snap.get("account_id_key") or "").strip()
    if key:
        out["account_id_key"] = key
    if label:
        out["account_name"] = label
    if out.get("usable_capital") is None or live:
        if out.get("balance") is not None:
            out["usable_capital"] = out.get("balance")
    bal = out.get("balance")
    invested = out.get("invested_capital")
    if bal is not None and invested is not None and invested > 0:
        out["total_pl"] = round(float(bal) - float(invested), 2)
        out["total_pl_pct"] = round(out["total_pl"] / float(invested) * 100.0, 2)
        out["trend"] = "up" if out["total_pl"] >= 0 else "down"
    disp = dict(out.get("display") or {}) if isinstance(out.get("display"), dict) else {}
    if out.get("balance") is not None:
        disp["balance"] = _money(out.get("balance"))
    if out.get("cash") is not None:
        disp["cash"] = _money(out.get("cash"))
    if out.get("invested_capital") is not None:
        disp["invested"] = _money(out.get("invested_capital"))
    if out.get("total_pl") is not None:
        disp["total_pl"] = _money(out.get("total_pl"))
    if out.get("total_pl_pct") is not None:
        disp["total_pl_pct"] = _pct(out.get("total_pl_pct"))
    if disp:
        out["display"] = disp


def build_account_summary() -> dict[str, Any]:
    """Balance + P/L for phone portfolio UI (best-effort from history + plan).

    Standing rules:
      - Deposits and transferred positions **are usable capital** (equity / BP / sizing).
      - They never count as trading **P/L** at book-in.
      total_pl = latest_value - invested_capital
      invested_capital = opening + deposits - withdrawals
      usable_capital = latest_value (full book)
    """
    out: dict[str, Any] = {
        "balance": None,
        "cash": None,
        "day_open": None,
        "day_pl": None,
        "day_pl_pct": None,
        "total_pl": None,
        "total_pl_pct": None,
        "invested_capital": None,
        "usable_capital": None,
        "opening_balance": None,
        "deposits_total": None,
        "deposits_are_capital": True,
        "transfer_positions_are_capital": True,
        "pl_excludes_deposits": True,
        "pl_excludes_transfer_mtm": False,
        "transfer_open_mtm": None,
        "trend": None,
        "currency": "USD",
    }
    live_events: list[dict[str, Any]] = []
    try:
        from account_balance_penalty import account_balance_state
        from account_profit import profit_metrics_for_account
        from analysis_history import get_account_growth

        st = account_balance_state() or {}
        growth = get_account_growth() or {}
        # Live recompute (capital-event deposit detection) - do not trust stale growth profit.
        metrics = profit_metrics_for_account(growth, str(st.get("account_id_key") or ""))
        live_events = list(metrics.get("external_flow_events") or [])

        balance = _f(metrics.get("latest_value"))
        if balance is None:
            balance = _f(st.get("latest_value"), 0.0) or None
        invested = _f(metrics.get("invested_capital"))
        if invested is None:
            invested = _f(st.get("invested_capital"))
        opening = metrics.get("opening_balance")
        if opening is None:
            opening = st.get("opening_balance")
        deposits_total = _f(metrics.get("net_external_flows"))
        usable = _f(metrics.get("usable_capital"))
        if usable is None:
            usable = balance
        # Canonical formula - always latest - invested (deposits already in invested capital).
        total_pl = None
        total_pl_pct = None
        if balance is not None and invested is not None and invested > 0:
            total_pl = round(balance - invested, 2)
            total_pl_pct = round(total_pl / invested * 100.0, 2)
        elif metrics.get("profit_amount") is not None:
            total_pl = _f(metrics.get("profit_amount"))
            total_pl_pct = _f(metrics.get("profit_pct"))

        day_open = _f(st.get("day_open_value"), 0.0) or None
        day_pl_pct_f = _f(st.get("daily_growth_pct")) if st.get("daily_growth_pct") is not None else None
        day_pl = None
        if balance is not None and day_open is not None and day_open > 0:
            today_flows = 0.0
            try:
                from datetime import datetime, timezone

                from account_profit import external_flows_on_utc_date

                events = live_events or list(growth.get("external_flow_events") or [])
                today_flows = external_flows_on_utc_date(events, datetime.now(timezone.utc).date())
            except Exception:
                today_flows = 0.0
            day_pl = round(balance - day_open - today_flows, 2)
            if day_pl_pct_f is None and day_open:
                day_pl_pct_f = round(day_pl / day_open * 100.0, 2)
        # Scrub deposit-as-day-win artifacts
        if not _is_plausible_day_pl(day_pl, balance):
            day_pl = None
            day_pl_pct_f = None

        out.update(
            {
                "balance": balance,
                "day_open": day_open,
                "day_pl": day_pl,
                "day_pl_pct": day_pl_pct_f,
                "total_pl": total_pl,
                "total_pl_pct": total_pl_pct,
                "invested_capital": invested,
                "usable_capital": usable,
                "opening_balance": _f(opening) if opening is not None else None,
                "deposits_total": deposits_total,
                "deposits_are_capital": True,
                "transfer_positions_are_capital": True,
                "trend": "up" if (total_pl or 0) >= 0 else "down",
            }
        )
    except Exception as exc:
        out["error"] = f"balance: {exc}"

    # Cash from latest growth point / plan
    try:
        from analysis_history import get_account_growth

        growth = get_account_growth() or {}
        points = growth.get("points") or []
        if points and isinstance(points[-1], dict):
            cash = points[-1].get("cash_buying_power")
            if cash is not None:
                out["cash"] = _f(cash)
            live_bal = _f(points[-1].get("total_account_value"))
            # Prefer higher live equity - never let a stale lower figure undercut balance.
            if live_bal is not None:
                cur = out.get("balance")
                if cur is None or live_bal > cur:
                    out["balance"] = live_bal
    except Exception:
        pass

    plan = _read_json(ROOT / "output" / "strategy_plan.json")
    if plan:
        plan_bal = _f(plan.get("total_account_value"))
        # Only fill missing balance from plan; never replace a higher live equity with stale plan.
        if out.get("balance") is None and plan_bal is not None:
            out["balance"] = plan_bal
        elif plan_bal is not None and out.get("balance") is not None:
            # Guard: if plan is far below live (stale), ignore plan equity entirely.
            if plan_bal < _f(out.get("balance"), 0) * 0.5:
                pass
        out["account_name"] = plan.get("account_name")
        out["account_id_key"] = plan.get("account_id_key")

    # Offline / empty plan must not leave OFFLINE ids - use broker snapshot for phone.
    snap = _load_account_snapshot()
    if snap:
        key = str(snap.get("account_id_key") or "").strip()
        label = str(snap.get("display_label") or "").strip()
        offline = str(out.get("account_id_key") or "").upper() in ("", "OFFLINE", "NONE")
        if key and offline:
            out["account_id_key"] = key
        if label and (
            offline
            or not out.get("account_name")
            or str(out.get("account_name")).lower().startswith("offline")
        ):
            out["account_name"] = label
        _overlay_live_broker_account(out, snap)

    # Re-apply formula after balance merges (stale plan must not invent P/L).
    bal = out.get("balance")
    invested = out.get("invested_capital")
    if bal is not None and invested is not None and invested > 0:
        out["total_pl"] = round(bal - invested, 2)
        out["total_pl_pct"] = round(out["total_pl"] / invested * 100.0, 2)
        out["trend"] = "up" if out["total_pl"] >= 0 else "down"
    elif bal is not None and (invested is None or invested <= 0):
        # No invested basis yet — still show live equity; leave P/L blank (not $0 fake).
        out["total_pl"] = None
        out["total_pl_pct"] = None

    day_pl = out.get("day_pl")
    day_pl_pct = out.get("day_pl_pct")
    total_pl = out.get("total_pl")
    total_pl_pct = out.get("total_pl_pct")
    dep = out.get("deposits_total")
    out["display"] = {
        "balance": _money(bal) if bal is not None else "-",
        "cash": _money(out.get("cash")) if out.get("cash") is not None else "-",
        "day_pl": _money(day_pl) if day_pl is not None else "-",
        "day_pl_pct": _pct(day_pl_pct) if day_pl_pct is not None else "-",
        "total_pl": _money(total_pl) if total_pl is not None else "-",
        "total_pl_pct": _pct(total_pl_pct) if total_pl_pct is not None else "-",
        "invested": _money(invested) if invested is not None else "-",
        "deposits": _money(dep) if dep is not None else "-",
    }
    return out


def _format_why_chosen(
    *,
    symbol: str,
    role: Any,
    rationale: Any,
    score: Any,
    confidence: Any,
    projected_return_pct: Any,
    projected_horizon: Any,
    order_type: Any,
    order_type_reason: Any,
    sources: Any,
    transfer_as_deposit: bool,
    weight_pct: Any,
) -> str:
    """Human-readable 'why this position' block for phone detail screen."""
    parts: list[str] = []
    role_s = str(role or "").strip()
    rat_s = str(rationale or "").strip()
    if transfer_as_deposit or "transfer" in role_s.lower() or "deposit" in role_s.lower():
        parts.append(
            f"{symbol} is an inbound transfer / deposit lot - **usable capital** "
            "(counts in equity, may be sold/rebalanced). Cost basis is capital in "
            "(not trading P/L at book-in). Price moves after book-in still affect equity."
        )
    if role_s and "transfer" not in role_s.lower():
        parts.append(f"Role: {role_s}")
    if score is not None:
        try:
            parts.append(f"Model score: {float(score):.2f}")
        except (TypeError, ValueError):
            parts.append(f"Model score: {score}")
    if confidence is not None:
        try:
            c = float(confidence)
            if c <= 1.0:
                c *= 100.0
            parts.append(f"Confidence: {c:.0f}%")
        except (TypeError, ValueError):
            pass
    if projected_return_pct is not None:
        try:
            h = str(projected_horizon or "").strip()
            hbit = f" ({h})" if h else ""
            parts.append(f"Projected return: {float(projected_return_pct):+.2f}%{hbit}")
        except (TypeError, ValueError):
            pass
    if order_type:
        ot = str(order_type).strip()
        otr = str(order_type_reason or "").strip()
        parts.append(f"Order style: {ot}" + (f" - {otr}" if otr else ""))
    if sources:
        if isinstance(sources, (list, tuple)):
            src = ", ".join(str(s) for s in sources if s)
        else:
            src = str(sources).strip()
        if src:
            parts.append(f"Sources: {src}")
    if weight_pct is not None:
        try:
            parts.append(f"Portfolio weight: {float(weight_pct):.1f}%")
        except (TypeError, ValueError):
            pass
    if rat_s:
        parts.append("")
        parts.append("Thesis / why chosen")
        parts.append(rat_s)
    elif not transfer_as_deposit:
        parts.append("")
        parts.append(
            "No active thesis in the latest portfolio plan for this symbol. "
            "It may be a legacy holding, mutual-fund sleeve, or was chosen outside the current research batch. "
            "Refresh portfolio / run agents on the PC to regenerate rationales."
        )
    return "\n".join(parts).strip()


def _index_proposed_actions(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map symbol -> proposed action from strategy_plan orders / target holdings."""
    out: dict[str, dict[str, Any]] = {}
    for row in plan.get("orders") or []:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").upper().strip()
        if not sym:
            continue
        action = str(
            row.get("action")
            or row.get("side")
            or row.get("order_action")
            or ""
        ).strip().upper()
        if not action:
            continue
        # Normalize common labels
        if action in ("B", "BUY_TO_COVER"):
            action = "BUY"
        if action in ("S", "SELL_SHORT", "SHORT"):
            action = "SELL" if "SHORT" not in action else action
        out[sym] = {
            "action": action,
            "quantity": row.get("quantity"),
            "order_type": row.get("order_type") or row.get("price_type"),
            "estimated_price": row.get("estimated_price"),
            "target_weight_pct": row.get("target_weight_pct"),
            "target_value_usd": row.get("target_value_usd"),
            "status": row.get("status"),
            "rationale": row.get("rationale") or row.get("reason") or row.get("message"),
        }
    # Target holdings without an open order -> HOLD signal when currently held
    for row in plan.get("target_holdings") or []:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").upper().strip()
        if not sym or sym in out:
            continue
        out[sym] = {
            "action": "HOLD",
            "quantity": row.get("quantity") or row.get("target_quantity"),
            "order_type": None,
            "estimated_price": row.get("price"),
            "target_weight_pct": row.get("weight_pct") or row.get("target_weight_pct"),
            "target_value_usd": row.get("allocation_usd") or row.get("target_value_usd"),
            "status": "target",
            "rationale": row.get("rationale") or "In target portfolio - no trade proposed",
        }
    return out


def build_positions(force_refresh: bool = False) -> list[dict[str, Any]]:
    """Merge live plan positions with portfolio enrichment for phone UI.

    Prefer a full broker snapshot (live pull or account_snapshot.json) over offline
    plan TARGET stubs so the phone always gets real lots + qty from the PC.
    """
    plan = _read_json(ROOT / "output" / "strategy_plan.json")
    portfolio = _read_json(ROOT / "output" / "portfolio.json")
    proposed_by_sym = _index_proposed_actions(plan)
    enrich: dict[str, dict[str, Any]] = {}
    for row in portfolio.get("holdings") or []:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").upper().strip()
        if sym:
            enrich[sym] = row
    # Also index recommendations if present
    for row in portfolio.get("recommendations") or []:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").upper().strip()
        if sym and sym not in enrich:
            enrich[sym] = row

    # Cost-basis overrides (ACATS / transfer resets)
    cost_overrides: dict[str, Any] = {}
    try:
        ov_path = ROOT / "output" / "position_cost_overrides.json"
        if ov_path.exists():
            raw_ov = json.loads(ov_path.read_text(encoding="utf-8"))
            if isinstance(raw_ov, dict):
                cost_overrides = raw_ov
    except (OSError, json.JSONDecodeError):
        cost_overrides = {}

    positions: list[dict[str, Any]] = []
    live = plan.get("current_positions") or []
    # Full broker lots: plan may be "offline rebuild" with empty current_positions
    # or TARGET idea stubs. Always prefer account_snapshot (worker / live pull).
    live_has_qty = any(
        isinstance(r, dict) and (_f(r.get("quantity")) or 0) != 0
        for r in (live if isinstance(live, list) else [])
    )
    plan_offline = bool((plan.get("meta") or {}).get("offline")) if isinstance(plan, dict) else False
    want_full = force_refresh or not live_has_qty or plan_offline
    if want_full:
        try_refresh_account_snapshot(
            max_age_sec=0.0 if force_refresh else 600.0,
            force=force_refresh,
        )
        snap = _phone_snapshot(_load_account_snapshot())
        snap_pos = snap.get("positions") if isinstance(snap, dict) else None
        if isinstance(snap_pos, list) and snap_pos:
            live = snap_pos
            _log(
                f"positions: full PC pull from account_snapshot "
                f"({len(live)} lots) - plan empty/offline or force_refresh={force_refresh}"
            )
        elif not live_has_qty:
            _set_pull_meta(
                live=False,
                source="plan_or_empty",
                error="No account_snapshot positions and plan has no qty",
                position_count=0,
            )
    total_mv = 0.0
    for row in live:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").upper().strip()
        if not sym:
            continue
        qty = _f(row.get("quantity"))
        price = _f(row.get("price"))
        mv = row.get("market_value")
        market_value = _f(mv) if mv is not None else (qty * price if qty and price else 0.0)
        cost_basis = _f(row.get("cost_basis"))  # often per-share
        ov = cost_overrides.get(sym) if isinstance(cost_overrides.get(sym), dict) else None
        if ov is not None:
            cb_ov = ov.get("cost_basis_per_share", ov.get("cost_basis"))
            if cb_ov is not None:
                cost_basis = _f(cb_ov, cost_basis)
        cost_total = cost_basis * qty if cost_basis and qty else None
        side = str(row.get("position_type") or row.get("side") or "LONG").upper()
        unreal = None
        unreal_pct = None
        if cost_total is not None and market_value is not None:
            if side.startswith("SHORT"):
                unreal = cost_total - market_value
            else:
                unreal = market_value - cost_total
            if cost_total:
                unreal_pct = (unreal / abs(cost_total)) * 100.0
        total_mv += abs(market_value or 0.0)
        extra = enrich.get(sym) or {}
        # All inbound transfers = deposits (cost basis capital; never trading P/L book-in)
        transfer_syms = _load_transfer_deposit_symbols()
        ov_reason = str((ov or {}).get("reason") or "").lower() if ov else ""
        is_xfer = (
            sym in transfer_syms
            or "transfer" in str(extra.get("role") or "").lower()
            or "deposit" in str(extra.get("role") or "").lower()
            or "acats" in str(extra.get("role") or "").lower()
            or "acats" in str(extra.get("rationale") or "").lower()
            or "inbound transfer" in str(extra.get("rationale") or "").lower()
            or "transfer as deposit" in str(extra.get("rationale") or "").lower()
            or "acats" in ov_reason
            or "transfer" in ov_reason
        )
        if ov is not None and ov.get("transfer_as_deposit"):
            is_xfer = True
        role = extra.get("role")
        rationale = extra.get("rationale")
        score = extra.get("score")
        conf = extra.get("confidence")
        proj = extra.get("projected_return_pct")
        proj_h = extra.get("projected_return_horizon")
        order_type = extra.get("order_type")
        order_reason = extra.get("order_type_reason")
        sources = extra.get("sources")
        w_pct = extra.get("weight_pct")
        why = _format_why_chosen(
            symbol=sym,
            role=role,
            rationale=rationale,
            score=score,
            confidence=conf,
            projected_return_pct=proj,
            projected_horizon=proj_h,
            order_type=order_type,
            order_type_reason=order_reason,
            sources=sources,
            transfer_as_deposit=is_xfer,
            weight_pct=w_pct,
        )
        # Transfer/deposit lots: $0 open P/L at book-in (capital), fully usable + tradeable
        if is_xfer:
            role = role or "transfer/deposit"
            if not rationale or "transfer" not in str(rationale).lower():
                rationale = (
                    "Inbound transfer from an outside account (ACATS/broker). "
                    "Cost is deposit capital - usable for sizing/equity; not trading P/L at book-in. "
                    "Position is tradeable (SELL/rebalance allowed)."
                )
            unreal = 0.0
            unreal_pct = 0.0
        prop = dict(proposed_by_sym.get(sym) or {})
        if not prop:
            prop = {
                "action": "HOLD",
                "quantity": None,
                "order_type": None,
                "estimated_price": None,
                "target_weight_pct": w_pct,
                "target_value_usd": None,
                "status": "deposit" if is_xfer else "no_order",
                "rationale": (
                    "Transfer/deposit lot - usable capital; tradeable when plan has orders"
                    if is_xfer
                    else "No open order in latest strategy plan - hold current lot"
                ),
            }
        prop_action = str(prop.get("action") or "HOLD").upper()
        prop_qty = prop.get("quantity")
        prop_px = _f(prop.get("estimated_price"))
        prop_rationale = str(prop.get("rationale") or "").strip()
        # Display line for phone detail hero (transfer lots keep plan SELL/BUY)
        is_trade = prop_action in ("BUY", "SELL", "SELL_SHORT", "BUY_TO_COVER")
        if is_trade and prop_qty is not None:
            try:
                qf = float(prop_qty)
                qtxt = f"{qf:g}"
            except (TypeError, ValueError):
                qtxt = str(prop_qty)
            prop_display = f"{prop_action} {qtxt}"
            if prop_px is not None:
                prop_display += f" @ {_money(prop_px)}"
        elif is_trade:
            prop_display = prop_action
        elif is_xfer:
            prop_display = "HOLD  |  capital"
        else:
            prop_display = prop_action
        if is_xfer:
            pl_display = "Capital"
            pl_pct_display = "-"
        else:
            pl_display = _money(unreal) if unreal is not None else "-"
            pl_pct_display = _pct(unreal_pct) if unreal_pct is not None else "-"

        positions.append(
            {
                "symbol": sym,
                "side": side,
                "quantity": qty,
                "price": price,
                "market_value": market_value,
                "cost_basis": cost_basis,
                "cost_total": cost_total,
                "unrealized_pl": unreal,
                "unrealized_pl_pct": unreal_pct,
                "weight_pct": w_pct,
                "score": score,
                "projected_return_pct": proj,
                "projected_return_horizon": proj_h,
                "confidence": conf,
                "role": role,
                "rationale": rationale,
                "why_chosen": why,
                "order_type": order_type or prop.get("order_type"),
                "order_type_reason": order_reason,
                "sources": sources,
                "trading_gate": extra.get("trading_gate"),
                "allocation_usd": extra.get("allocation_usd"),
                "transfer_as_deposit": is_xfer,
                # Deposits / ACATS lots count toward capital (equity, BP, sellable).
                "usable_as_capital": True,
                "proposed_action": prop_action,
                "proposed_quantity": prop_qty,
                "proposed_price": prop_px,
                "proposed_order_type": prop.get("order_type"),
                "proposed_status": prop.get("status"),
                "proposed_rationale": prop_rationale or None,
                "proposed_target_weight_pct": prop.get("target_weight_pct"),
                "proposed_target_value_usd": prop.get("target_value_usd"),
                "display": {
                    "price": _money(price) if price else "-",
                    "market_value": _money(market_value) if market_value is not None else "-",
                    "cost_basis": _money(cost_basis) if cost_basis else "-",
                    "cost_total": _money(cost_total) if cost_total is not None else "-",
                    "unrealized_pl": pl_display,
                    "unrealized_pl_pct": pl_pct_display,
                    "quantity": f"{qty:g}" if qty else "-",
                    "proposed_action": prop_display,
                },
            }
        )

    # Always surface portfolio + Market Predictor ideas for the phone Market
    # Predictor tab. Live broker lots often have zero overlap with model targets
    # (transfers / current book vs agent picks), so TARGET rows must still ship
    # when held positions already exist - not only when the book is empty.
    positions = _append_prediction_target_rows(positions, portfolio)

    # Portfolio weight by market value if missing (held lots only)
    if total_mv > 0:
        for p in positions:
            if p.get("weight_pct") is None and p.get("market_value") is not None:
                side = str(p.get("side") or "").upper()
                if side == "TARGET":
                    continue
                p["weight_pct"] = round(abs(_f(p["market_value"])) / total_mv * 100.0, 2)

    def _sort_key(row: dict[str, Any]) -> tuple[int, float]:
        side = str(row.get("side") or "").upper()
        is_target = 1 if side == "TARGET" else 0
        return (is_target, -abs(_f(row.get("market_value")) or 0.0))

    positions.sort(key=_sort_key)
    return positions


def _prediction_row_from_portfolio(row: dict[str, Any]) -> dict[str, Any] | None:
    """Build a TARGET position dict from portfolio.json holdings/recommendations."""
    if not isinstance(row, dict):
        return None
    sym = str(row.get("symbol") or "").upper().strip()
    if not sym:
        return None
    score = row.get("score")
    proj = row.get("projected_return_pct")
    conf = row.get("confidence")
    sources = row.get("sources")
    src_list = (
        [str(s) for s in sources]
        if isinstance(sources, (list, tuple, set))
        else ([str(sources)] if sources else [])
    )
    from_predictor = any(
        "market-predictor" in s.lower() or "market_predictor" in s.lower() for s in src_list
    )
    if score is None and proj is None and conf is None and not from_predictor:
        return None
    price = _f(row.get("price"))
    alloc = _f(row.get("allocation_usd"))
    return {
        "symbol": sym,
        "side": "TARGET",
        "quantity": None,
        "price": price,
        "market_value": alloc or None,
        "cost_basis": None,
        "cost_total": None,
        "unrealized_pl": None,
        "unrealized_pl_pct": _f(proj) if proj is not None else None,
        "weight_pct": row.get("weight_pct"),
        "score": score,
        "projected_return_pct": proj,
        "projected_return_horizon": row.get("projected_return_horizon"),
        "confidence": conf,
        "role": row.get("role") or "market-predictor",
        "rationale": row.get("rationale"),
        "why_chosen": row.get("rationale") or "Market Predictor / portfolio target",
        "order_type": row.get("order_type"),
        "order_type_reason": row.get("order_type_reason"),
        "sources": src_list or ["market-predictor"],
        "allocation_usd": alloc,
        "transfer_as_deposit": False,
        "usable_as_capital": False,
        "proposed_action": "TARGET",
        "proposed_status": "idea",
        "display": {
            "price": _money(price) if price else "-",
            "market_value": _money(alloc) if alloc else "-",
            "cost_basis": "-",
            "cost_total": "-",
            "unrealized_pl": "-",
            "unrealized_pl_pct": _pct(_f(proj)) if proj is not None else "-",
            "quantity": "-",
            "proposed_action": "TARGET idea",
        },
    }


def _prediction_rows_from_market_file() -> list[dict[str, Any]]:
    """Flatten market_predictions.json into TARGET rows (preferred horizons first)."""
    mp = _read_json(ROOT / "output" / "market_predictions.json")
    if not mp:
        return []
    by_sym: dict[str, dict[str, Any]] = {}
    # Prefer near-term horizons the phone Market Predictor tab cares about.
    for horizon in ("24h", "1h", "1wk", "1m", "1mo", "1yr"):
        bucket = (mp.get("predictions") or {}).get(horizon)
        if not isinstance(bucket, list):
            continue
        for row in bucket:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").upper().strip()
            if not sym or sym in by_sym:
                continue
            proj = row.get("predicted_return_pct")
            conf = row.get("confidence")
            score = row.get("composite_score")
            if score is None and proj is not None:
                try:
                    score = float(proj) / 100.0
                except (TypeError, ValueError):
                    score = None
            sources = row.get("sources") or ["market-predictor"]
            if isinstance(sources, str):
                sources = [sources]
            src_list = [str(s) for s in sources]
            if "market-predictor" not in {s.lower() for s in src_list}:
                src_list = list(src_list) + ["market-predictor"]
            price = _f(row.get("price_at_prediction") or row.get("price"))
            by_sym[sym] = {
                "symbol": sym,
                "side": "TARGET",
                "quantity": None,
                "price": price,
                "market_value": None,
                "cost_basis": None,
                "cost_total": None,
                "unrealized_pl": None,
                "unrealized_pl_pct": _f(proj) if proj is not None else None,
                "weight_pct": None,
                "score": score,
                "projected_return_pct": proj,
                "projected_return_horizon": horizon,
                "confidence": conf,
                "role": "market-predictor",
                "rationale": row.get("rationale")
                or f"Market Predictor {horizon} {row.get('predicted_direction') or ''}".strip(),
                "why_chosen": row.get("rationale")
                or f"Market Predictor signal ({horizon})",
                "order_type": None,
                "sources": src_list,
                "predicted_direction": row.get("predicted_direction"),
                "transfer_as_deposit": False,
                "usable_as_capital": False,
                "proposed_action": "TARGET",
                "proposed_status": "idea",
                "display": {
                    "price": _money(price) if price else "-",
                    "market_value": "-",
                    "cost_basis": "-",
                    "cost_total": "-",
                    "unrealized_pl": "-",
                    "unrealized_pl_pct": _pct(_f(proj)) if proj is not None else "-",
                    "quantity": "-",
                    "proposed_action": f"PRED {horizon}",
                },
            }
    return list(by_sym.values())


def _append_prediction_target_rows(
    positions: list[dict[str, Any]],
    portfolio: dict[str, Any],
) -> list[dict[str, Any]]:
    """Ensure Market Predictor symbols appear even when not currently held."""
    out = list(positions or [])
    seen = {
        str(p.get("symbol") or "").upper().strip()
        for p in out
        if str(p.get("symbol") or "").strip()
    }

    # Enrich held lots missing model fields from portfolio / market_predictions.
    enrich_from_file: dict[str, dict[str, Any]] = {}
    for idea in _prediction_rows_from_market_file():
        sym = str(idea.get("symbol") or "").upper()
        if sym:
            enrich_from_file[sym] = idea
    for row in (portfolio.get("holdings") or []) + (portfolio.get("recommendations") or []):
        idea = _prediction_row_from_portfolio(row if isinstance(row, dict) else {})
        if not idea:
            continue
        sym = str(idea.get("symbol") or "").upper()
        if sym:
            # Portfolio holdings prefer over raw predictor when both exist
            enrich_from_file[sym] = idea

    for p in out:
        sym = str(p.get("symbol") or "").upper().strip()
        if not sym:
            continue
        extra = enrich_from_file.get(sym)
        if not extra:
            continue
        if p.get("score") is None and extra.get("score") is not None:
            p["score"] = extra.get("score")
        if p.get("projected_return_pct") is None and extra.get("projected_return_pct") is not None:
            p["projected_return_pct"] = extra.get("projected_return_pct")
            p["projected_return_horizon"] = extra.get("projected_return_horizon")
        if p.get("confidence") is None and extra.get("confidence") is not None:
            p["confidence"] = extra.get("confidence")
        if not p.get("sources") and extra.get("sources"):
            p["sources"] = extra.get("sources")
        if not p.get("rationale") and extra.get("rationale"):
            p["rationale"] = extra.get("rationale")

    # Append TARGET ideas not already in the book (phone Market Predictor tab).
    for row in portfolio.get("holdings") or []:
        idea = _prediction_row_from_portfolio(row if isinstance(row, dict) else {})
        if not idea:
            continue
        sym = str(idea.get("symbol") or "").upper()
        if not sym or sym in seen:
            continue
        out.append(idea)
        seen.add(sym)

    for idea in _prediction_rows_from_market_file():
        sym = str(idea.get("symbol") or "").upper()
        if not sym or sym in seen:
            continue
        out.append(idea)
        seen.add(sym)

    return out


def _shared_api_for_phone() -> dict[str, Any]:
    """One E*TRADE API for long+short; practice mode stays independent per sleeve."""
    try:
        from shared_etrade_api import feature_snapshot, mirror_shared_api_into_short

        mirror_shared_api_into_short()
        return feature_snapshot()
    except Exception as exc:
        long_raw = _read_json(LONG_CONFIG)
        short_raw = _read_json(SHORT_CONFIG)
        lw = dict(long_raw.get("background_worker") or {})
        sw = dict(short_raw.get("background_worker") or {})
        acct = long_raw.get("selected_account") if isinstance(long_raw.get("selected_account"), dict) else {}
        sandbox = bool(long_raw.get("sandbox", True))
        return {
            "feature": "shared_etrade_api",
            "error": str(exc),
            "api": {
                "source": "etrade_config.json",
                "sandbox": sandbox,
                "environment": "sandbox" if sandbox else "production",
                "account_label": str(acct.get("display_label") or "").strip() or None,
                "has_account": bool(str(acct.get("account_id_key") or "").strip()),
            },
            "practice_mode": {
                "long_dry_run": bool(lw.get("dry_run", False)),
                "short_dry_run": bool(sw.get("dry_run", True)),
                "independent": True,
            },
        }


def build_features_for_phone() -> dict[str, Any]:
    """Feature/data catalog so the E*TRADE phone app can stay current."""
    snap = _shared_api_for_phone()
    return {
        "ok": True,
        "version": BRIDGE_VERSION,
        "updated_at": time.time(),
        "features": [
            {
                "id": "shared_etrade_api",
                "title": "Shared E*TRADE API",
                "summary": (
                    "Long and short sleeves use one API: keys, sandbox/production, "
                    "OAuth tokens, and selected account from etrade_config.json."
                ),
                "enabled": True,
            },
            {
                "id": "independent_practice_mode",
                "title": "Independent practice mode",
                "summary": (
                    "Practice (dry_run) can be ON/OFF per sleeve. "
                    "Long can be LIVE while short stays PRACTICE."
                ),
                "enabled": True,
            },
            {
                "id": "shared_capital_sleeves",
                "title": "Shared capital, isolated books",
                "summary": "One account equity pool; long never shorts, short never buys longs.",
                "enabled": True,
            },
        ],
        "shared_api": snap,
        "data_hints": {
            "dashboard": "/api/dashboard includes shared_api, long/short dry_run, single env",
            "controls": "POST /api/controls side=long|short|all with dry_run independently",
            "accounts": "Selected account is shared; pick once for both sleeves",
        },
    }


def build_dashboard(force_refresh: bool = False, *, publish: bool = True) -> dict[str, Any]:
    """Build phone dashboard. force_refresh=True -> live full PC portfolio pull.

    publish=False skips writing Oxygen-OS work/phone/etrade-dashboard.json
    (used by the desktop unified GUI so an empty PC session cannot clobber
    the last good phone pack).
    """
    _pull_ctx.meta = {
        "force_refresh": bool(force_refresh),
        "live": False,
        "source": "building",
    }
    long_raw = _read_json(LONG_CONFIG)
    short_raw = _read_json(SHORT_CONFIG)
    lw = dict(long_raw.get("background_worker") or {})
    sw = dict(short_raw.get("background_worker") or {})
    shared = _shared_api_for_phone()
    api = shared.get("api") if isinstance(shared.get("api"), dict) else {}
    shared_label = str(api.get("account_label") or "").strip()
    long_acct = (
        shared_label
        or (long_raw.get("selected_account") or {}).get("display_label")
        or "Not set"
    )
    short_acct = (
        shared_label
        or (short_raw.get("selected_account") or {}).get("display_label")
        or long_acct
        or "Not set"
    )
    both_paused = bool(lw.get("paused")) or bool(sw.get("paused"))
    lm = _mode(bool(lw.get("dry_run")), bool(lw.get("auto_execute", True)), both_paused)
    sm = _mode(bool(sw.get("dry_run", True)), bool(sw.get("auto_execute")), both_paused)
    # Single shared API environment for both sleeves
    env = str(api.get("environment") or ("sandbox" if long_raw.get("sandbox", True) else "production"))
    env_disp = "Sandbox" if env.lower() == "sandbox" else "Production"
    env_l = env_disp
    env_s = env_disp

    long_pct: Any = "-"
    short_pct: Any = "-"
    joint = 0.0
    exp_long = 0.0
    exp_short = 0.0
    tops_l: list[str] = []
    tops_s: list[str] = []
    long_rows: list[str] = []
    short_rows: list[str] = []
    guidance = ""
    coord_ok = True
    coord_error = ""

    try:
        from sleeve_coordinator import coordinate_sleeves

        coord = coordinate_sleeves()
        deploy = coord.get("deploy") or {}
        exp = coord.get("expected_profit") or {}
        long_pct = deploy.get("long_max_deploy_pct", "-")
        short_pct = deploy.get("short_max_deploy_pct", "-")
        joint = float(exp.get("expected_profit_usd_joint") or 0)
        exp_long = float(exp.get("expected_profit_usd_long") or 0)
        exp_short = float(exp.get("expected_profit_usd_short") or 0)
        tops_l = list(exp.get("top_long") or [])
        tops_s = list(exp.get("top_short") or [])
        assignment = coord.get("symbol_assignment") or {}
        for i, sym in enumerate(tops_l[:12], 1):
            long_rows.append(f"{i:>2}. {sym}")
        for i, sym in enumerate(tops_s[:12], 1):
            short_rows.append(f"{i:>2}. {sym}")
        if not long_rows:
            long_rows = [s for s, side in sorted(assignment.items()) if side == "long"][:12]
        if not short_rows:
            short_rows = [s for s, side in sorted(assignment.items()) if side == "short"][:12]
        g = coord.get("guidance") or {}
        guidance = str(g.get("joint") or "Dashboard ready.")
    except Exception as exc:
        coord_ok = False
        coord_error = str(exc)
        guidance = f"Could not load coordination: {exc}"

    snapshot = [
        {"item": "Mode", "long": lm, "short": sm},
        {"item": "API env", "long": env_l, "short": env_s},
        {"item": "Account", "long": _shorten(long_acct, 28), "short": _shorten(short_acct, 28)},
        {
            "item": "Practice",
            "long": "ON" if lw.get("dry_run") else "OFF",
            "short": "ON" if sw.get("dry_run", True) else "OFF",
        },
        {
            "item": "Auto-trade",
            "long": "ON" if lw.get("auto_execute", True) else "OFF",
            "short": "ON" if sw.get("auto_execute") else "OFF",
        },
        {"item": "Budget %", "long": f"{long_pct}%", "short": f"{short_pct}%"},
        {
            "item": "Exp. profit $",
            "long": f"${exp_long:,.0f}",
            "short": f"${exp_short:,.0f}",
        },
        {
            "item": "Top idea",
            "long": tops_l[0] if tops_l else "-",
            "short": tops_s[0] if tops_s else "-",
        },
        {"item": "# ideas", "long": str(len(long_rows)), "short": str(len(short_rows))},
        {"item": "Isolation", "long": "Longs only", "short": "Shorts only"},
        {"item": "Shared API", "long": "Yes (one)", "short": "Yes (same)"},
        {"item": "Shared capital", "long": "Yes", "short": "Yes"},
    ]

    # Live equity/lots first when phone asks for refresh — account summary must not
    # run against an empty snapshot and then stick balance=0 forever.
    if force_refresh:
        try:
            try_refresh_account_snapshot(max_age_sec=0.0, force=True)
        except Exception as exc:
            _log(f"pre-dashboard live snapshot pull failed: {exc}")

    account = build_account_summary()
    positions = build_positions(force_refresh=force_refresh)
    # Re-merge account from snapshot after positions refresh (snapshot may be newer).
    snap_after = _load_account_snapshot()
    if isinstance(snap_after, dict) and snap_after:
        _overlay_live_broker_account(account, snap_after)
    # Mark known transfer lots (cost-only deposit capital; never MTM).
    transfer_symbols = _load_transfer_deposit_symbols()
    transfer_deposit = 0.0
    learned: set[str] = set()
    for p in positions:
        sym = str(p.get("symbol") or "").upper()
        role = str(p.get("role") or "").lower()
        rat = str(p.get("rationale") or "").lower()
        why = str(p.get("why_chosen") or "").lower()
        # Never drop an already-flagged transfer (cost overrides / build_positions)
        is_xfer = (
            bool(p.get("transfer_as_deposit"))
            or sym in transfer_symbols
            or "transfer" in role
            or "acats" in role
            or "deposit" in role
            or "acats" in rat
            or "inbound transfer" in rat
            or "transfer as deposit" in rat
            or "acats" in why
            or "inbound transfer" in why
            or "transfer as deposit" in why
        )
        p["transfer_as_deposit"] = bool(is_xfer)
        p["usable_as_capital"] = True  # cash deposits + every open lot count as capital
        if is_xfer:
            if sym:
                learned.add(sym)
            cost = _f(p.get("cost_total"))
            # Cost basis for deposit tracking - market value still usable capital in equity.
            if cost is not None and cost > 0:
                transfer_deposit += abs(cost)
            p["open_pl_for_total"] = 0.0  # transfer book-in is capital, not P/L
            # Keep plan proposed_action (SELL/BUY) - transfer lots are tradeable capital
            p["unrealized_pl"] = 0.0
            p["unrealized_pl_pct"] = 0.0
            if not p.get("role"):
                p["role"] = "transfer/deposit"
            disp = p.get("display") if isinstance(p.get("display"), dict) else {}
            disp = dict(disp)
            disp["unrealized_pl"] = "Capital"
            disp["unrealized_pl_pct"] = "-"
            prop_a = str(p.get("proposed_action") or "HOLD").upper()
            is_trade = prop_a in ("BUY", "SELL", "SELL_SHORT", "BUY_TO_COVER")
            if not is_trade:
                # No plan trade - label as capital (not locked)
                if not disp.get("proposed_action") or "HOLD" in str(disp.get("proposed_action") or "").upper():
                    disp["proposed_action"] = "HOLD  |  capital"
                if not p.get("proposed_status"):
                    p["proposed_status"] = "deposit_capital"
            # else: leave proposed_action / display from build_positions (plan trade)
            p["display"] = disp
        else:
            # Trading lots only contribute to portfolio open P/L
            p["open_pl_for_total"] = _f(p.get("unrealized_pl"))

    if learned:
        remember_transfer_deposit_symbols(learned)

    held_positions = [
        p
        for p in positions
        if str(p.get("side") or "").upper() != "TARGET"
        and (_f(p.get("quantity")) or 0) != 0
    ]
    # Portfolio open P/L = held trading lots only (not TARGET ideas; transfer lots $0 book-in)
    pos_pl = sum(
        _f(p.get("unrealized_pl"))
        for p in held_positions
        if not p.get("transfer_as_deposit") and p.get("unrealized_pl") is not None
    )
    # Book MV from held lots only (exclude TARGET idea rows)
    pos_mv = sum(abs(_f(p.get("market_value")) or 0.0) for p in held_positions)

    # Transfer MTM (mv - cost) for diagnostics only. Do NOT subtract from total P/L:
    # invested_capital already includes deposit/ACATS at book-in, and latest equity
    # already marks those lots to market - so capital_pl = latest - invested is the
    # true deposit-aware total. Subtracting transfer_open_mtm when it is negative
    # *adds back* transfer losses as fake profit (~+$1.1k bug).
    transfer_open_mtm = 0.0
    for p in held_positions:
        if not p.get("transfer_as_deposit"):
            continue
        mv = _f(p.get("market_value"))
        cost = _f(p.get("cost_total"))
        if mv is not None and cost is not None:
            transfer_open_mtm += mv - cost
    bal_pl = _f(account.get("balance"))
    inv_pl = _f(account.get("invested_capital"))
    if bal_pl is not None and inv_pl is not None and inv_pl > 0:
        capital_pl = round(bal_pl - inv_pl, 2)
        account["total_pl"] = capital_pl
        account["total_pl_pct"] = round(capital_pl / inv_pl * 100.0, 2)
        account["trend"] = "up" if capital_pl >= 0 else "down"
        account["transfer_open_mtm"] = round(transfer_open_mtm, 4)
        # Total P/L includes post-book-in MTM on transfer lots (real equity change).
        account["pl_excludes_transfer_mtm"] = False
        adisp = account.get("display") if isinstance(account.get("display"), dict) else {}
        adisp = dict(adisp)
        adisp["total_pl"] = _money(capital_pl)
        adisp["total_pl_pct"] = _pct(account["total_pl_pct"])
        account["display"] = adisp

    dep = _f(account.get("deposits_total"))
    dep_note = ""
    if dep is not None and abs(dep) >= 0.01:
        dep_note = (
            f"  |  deposits/transfers {_money(dep)} are capital "
            f"(usable; not counted as P/L at book-in)"
        )
    status = f"Connected to E*TRADE{dep_note}" if not guidance.startswith("Could not") else guidance
    if guidance and "Could not" not in guidance and guidance != "Dashboard ready.":
        status = f"{guidance}{dep_note}"

    acct_key = str(account.get("account_id_key") or "")
    try:
        performance = build_performance_series(acct_key)
        # Prefer calculation-start-rebased total for phone total/avg cards
        since_pl = performance.get("total_pl_since_start")
        if since_pl is not None and isinstance(account, dict):
            inv_pl = _f(account.get("invested_capital"))
            account["total_pl"] = round(float(since_pl), 2)
            if inv_pl and inv_pl > 0:
                account["total_pl_pct"] = round(float(since_pl) / inv_pl * 100.0, 2)
            account["trend"] = "up" if float(since_pl) >= 0 else "down"
            account["pl_from_calculation_start"] = True
            account["calculation_start"] = CALCULATION_START_ISO
            adisp = account.get("display") if isinstance(account.get("display"), dict) else {}
            adisp = dict(adisp)
            adisp["total_pl"] = _money(float(since_pl))
            if account.get("total_pl_pct") is not None:
                adisp["total_pl_pct"] = _pct(account["total_pl_pct"])
            account["display"] = adisp
    except Exception as exc:
        _log(f"performance series failed: {exc}")
        performance = {
            "points": [],
            "ranges": {},
            "pl_excludes_deposits": True,
            "transfer_deposit": round(transfer_deposit, 2),
            "point_count": 0,
            "error": str(exc),
        }

    ui_info = phone_ui_info_enabled()
    # When phone UI info is off: keep balances/positions/controls; strip ideas & analysis rows.
    if not ui_info:
        long_rows = []
        short_rows = []
        tops_l = []
        tops_s = []
        # Rebuild snapshot without idea-count noise
        for row in snapshot:
            if isinstance(row, dict) and row.get("item") in ("Top idea", "# ideas", "Exp. profit $"):
                row["long"] = "-"
                row["short"] = "-"
        status = f"{status}  |  phone UI info OFF" if status else "phone UI info OFF"

    pull_meta = dict(_last_pull_meta())
    if not pull_meta.get("position_count"):
        pull_meta["position_count"] = len(held_positions)
    if pull_meta.get("source") in (None, "", "building"):
        pull_meta["source"] = "account_snapshot" if held_positions else "empty"
    pull_meta["force_refresh"] = bool(force_refresh)
    pull_meta["held_position_count"] = len(held_positions)
    pull_meta["row_count"] = len(positions)
    pull_meta["full_pc_pull"] = True

    payload = {
        "ok": True,
        "version": BRIDGE_VERSION,
        "phone_ui_info_enabled": ui_info,
        "updated_at": time.time(),
        "paused": both_paused,
        "status_line": status,
        "coord_ok": coord_ok,
        "coord_error": coord_error,
        "data_pull": pull_meta,
        "account": account,
        "positions": positions,
        "performance": performance,
        "portfolio": {
            # Held broker lots (not TARGET idea rows)
            "position_count": len(held_positions),
            "held_position_count": len(held_positions),
            "target_idea_count": max(0, len(positions) - len(held_positions)),
            "row_count": len(positions),
            "market_value": pos_mv,
            "unrealized_pl": pos_pl,
            "transfer_deposit": round(transfer_deposit, 2),
            "deposits_total": account.get("deposits_total"),
            # Full book MV is deployable/sellable capital (includes transfer lots).
            "usable_capital_positions": pos_mv,
            "deposits_are_capital": True,
            "transfer_positions_are_capital": True,
            "display": {
                "market_value": _money(pos_mv),
                "unrealized_pl": _money(pos_pl),
                "position_count": str(len(held_positions)),
            },
        },
        "pl_excludes_deposits": True,
        "pl_excludes_transfer_mtm": False,
        "deposits_are_capital": True,
        "transfer_positions_are_capital": True,
        "pl_from_calculation_start": True,
        "calculation_start": CALCULATION_START_ISO,
        "transfer_open_mtm": round(transfer_open_mtm, 4),
        "deposits_total": account.get("deposits_total"),
        # Shared API + independent practice - phone app feature/data contract
        "shared_api": shared,
        "api_environment": env_disp,
        "practice_independent": True,
        "metrics": {
            "long_mode": lm,
            "short_mode": sm,
            "long_account": _shorten(long_acct, 28),
            "short_account": _shorten(short_acct, 28),
            "api_environment": env_disp,
            "shared_api": True,
            "practice_independent": True,
            "capital_split": f"L {long_pct}% / S {short_pct}%",
            "joint_edge": f"${joint:,.0f}" if joint else "-",
            "joint_edge_usd": joint,
            "balance": account.get("display", {}).get("balance", "-"),
            "day_pl": account.get("display", {}).get("day_pl", "-"),
            "total_pl": account.get("display", {}).get("total_pl", "-"),
            "invested": account.get("display", {}).get("invested", "-"),
            "deposits": account.get("display", {}).get("deposits", "-"),
        },
        "long": {
            "mode": lm,
            "account": long_acct,
            "env": env_l,
            "dry_run": bool(lw.get("dry_run")),
            "auto_execute": bool(lw.get("auto_execute", True)),
            "paused": bool(lw.get("paused")),
            "ideas": long_rows,
            "practice_independent": True,
        },
        "short": {
            "mode": sm,
            "account": short_acct,
            "env": env_s,
            "dry_run": bool(sw.get("dry_run", True)),
            "auto_execute": bool(sw.get("auto_execute")),
            "paused": bool(sw.get("paused")),
            "ideas": short_rows,
            "practice_independent": True,
        },
        "snapshot": snapshot,
    }
    if publish:
        try:
            _publish_dashboard_to_oxygen(payload)
        except Exception as exc:
            _log(f"publish dashboard note: {exc}")
    return payload


def build_performance_series(account_id_key: str = "") -> dict[str, Any]:
    """Equity + deposit-excluded P/L history for the phone performance chart.

    Shape matches phone BridgeApi.parsePerformance:
      performance.points[]: {at, value, profit_amount, profit_pct}
      performance.ranges: {all,1w,1m,3m,6m,1y}

    Rules:
      - deposits/transfers book capital only from their event timestamps
        (profit_at_point uses net flows before each point)
      - all series clipped + rebased to CALCULATION_START_ISO (P/L at start = 0)
      - post-book-in MTM on transfer lots stays in P/L (real equity change);
        never subtract transfer_open_mtm from profit (that flipped losses into profit)
    """
    from datetime import datetime, timedelta, timezone

    from account_growth_chart import points_for_account
    from account_profit import (
        collapse_to_transitions,
        profit_at_point,
        profit_metrics_for_account,
    )
    from analysis_history import get_account_growth

    growth = get_account_growth() or {}
    key = str(account_id_key or "").strip()
    metrics = profit_metrics_for_account(growth, key)
    events = list(metrics.get("external_flow_events") or [])
    opening = metrics.get("opening_balance")
    if opening is None:
        opening = _f(growth.get("baseline_value"))
    opening_f = float(opening) if opening is not None else 0.0

    raw_points = list(growth.get("points") or [])
    if key:
        scoped = points_for_account(raw_points, key)
        if scoped:
            raw_points = scoped
    transitions = collapse_to_transitions(raw_points)

    points: list[dict[str, Any]] = []
    for row in transitions:
        if not isinstance(row, dict):
            continue
        value = _f(row.get("total_account_value"))
        at = str(row.get("at") or "").strip()
        if value is None or not at:
            continue
        # Prefer broker/real snapshots for a cleaner chart; keep plan only if sparse
        src = str(row.get("source") or "")
        if src == "plan" and len(transitions) > 80:
            if points:
                last_v = points[-1].get("value")
                if last_v is not None and abs(value - float(last_v)) < 0.50:
                    continue
        # Time-aware: deposits/transfers only affect capital from event date forward
        pl_amt, pl_pct = profit_at_point(value, opening_f, events, at)
        points.append(
            {
                "at": at,
                "value": round(value, 2),
                "total_account_value": round(value, 2),
                "profit_amount": round(pl_amt, 2),
                "profit_pct": round(pl_pct, 2),
                "source": src or None,
            }
        )

    # Cap density for phone (keep ~200 points evenly if huge)
    if len(points) > 220:
        step = max(1, len(points) // 200)
        thinned = points[::step]
        if thinned[-1] is not points[-1]:
            thinned.append(points[-1])
        points = thinned

    def _parse_at(at: str) -> datetime | None:
        try:
            return datetime.fromisoformat(at.replace("Z", "+00:00"))
        except ValueError:
            return None

    # Transfer MTM diagnostic only (not subtracted from series).
    transfer_open_mtm = 0.0
    try:
        positions = build_positions()
        for p in positions:
            if not p.get("transfer_as_deposit"):
                continue
            mv = _f(p.get("market_value"))
            cost = _f(p.get("cost_total"))
            if mv is not None and cost is not None:
                transfer_open_mtm += mv - cost
    except Exception:
        transfer_open_mtm = 0.0

    # --- Clip + rebase to calculation start (P/L at start = 0) ---
    start_day = CALCULATION_START_ISO

    def _on_or_after_start(at: str) -> bool:
        day = (at or "")[:10]
        return len(day) == 10 and day >= start_day

    clipped = [p for p in points if _on_or_after_start(str(p.get("at") or ""))]
    if not clipped:
        clipped = list(points)
    start_pl = _f(clipped[0].get("profit_amount")) if clipped else 0.0
    if start_pl is None:
        start_pl = 0.0
    if abs(start_pl) >= 0.0005:
        for p in clipped:
            pl = _f(p.get("profit_amount"))
            if pl is None:
                continue
            new_pl = round(pl - start_pl, 2)
            p["profit_amount"] = new_pl
            inv = _f(metrics.get("invested_capital"))
            val = _f(p.get("value"))
            if inv and inv > 0:
                p["profit_pct"] = round(new_pl / inv * 100.0, 2)
            elif val and val > 0:
                p["profit_pct"] = round(new_pl / val * 100.0, 2)
    points = clipped

    now = datetime.now(timezone.utc)
    windows = {
        "1w": timedelta(days=7),
        "1m": timedelta(days=30),
        "3m": timedelta(days=90),
        "6m": timedelta(days=182),
        "1y": timedelta(days=365),
    }
    ranges: dict[str, list[dict[str, Any]]] = {"all": points, "open": points}
    for name, delta in windows.items():
        start = now - delta
        ranges[name] = [
            p
            for p in points
            if (_parse_at(str(p.get("at") or "")) or now) >= start
        ] or points[-min(20, len(points)) :]

    transfer_deposit = 0.0
    deposit_events: list[dict[str, Any]] = []
    for ev in events:
        if str(ev.get("kind") or "") == "deposit":
            amt = abs(_f(ev.get("amount")) or 0.0)
            transfer_deposit += amt
            deposit_events.append(
                {
                    "at": ev.get("at"),
                    "amount": round(amt, 2),
                    "source": ev.get("source"),
                    "kind": "deposit",
                }
            )

    last_pl = _f(points[-1].get("profit_amount")) if points else None

    return {
        "points": points,
        "ranges": ranges,
        "pl_excludes_deposits": True,
        "pl_excludes_transfer_mtm": False,
        "pl_from_calculation_start": True,
        "calculation_start": CALCULATION_START_ISO,
        "transfer_deposit": round(transfer_deposit, 2),
        "transfer_open_mtm": round(transfer_open_mtm, 4),
        "deposit_events": deposit_events,
        "point_count": len(points),
        "opening_balance": opening_f if opening is not None else None,
        "invested_capital": metrics.get("invested_capital"),
        "total_pl_since_start": last_pl,
    }


def _selected_account_entry(raw: dict[str, Any], role: str) -> dict[str, Any] | None:
    sel = raw.get("selected_account") if isinstance(raw.get("selected_account"), dict) else {}
    id_key = str(sel.get("account_id_key") or "").strip()
    if not id_key:
        return None
    label = str(sel.get("display_label") or id_key).strip()
    return {
        "account_id_key": id_key,
        "display_label": label,
        "account_id": str(sel.get("account_id") or ""),
        "account_status": str(sel.get("account_status") or "OPEN"),
        "role": role,
        "source": "config",
    }


def list_accounts_for_phone() -> dict[str, Any]:
    """Accounts the phone can pick. Prefer live E*TRADE list; fall back to PC config."""
    long_raw = _read_json(LONG_CONFIG)
    short_raw = _read_json(SHORT_CONFIG)
    selected_long = str((long_raw.get("selected_account") or {}).get("account_id_key") or "")
    selected_short = str((short_raw.get("selected_account") or {}).get("account_id_key") or "")
    selected = selected_long or selected_short

    accounts: list[dict[str, Any]] = []
    live_ok = False
    live_error = ""
    try:
        from etrade_api.accounts import parse_accounts
        from etrade_api.client import ETradeClient
        from etrade_api.config import load_config
        from etrade_api.oauth import is_expired_for_day, load_tokens

        cfg = load_config(LONG_CONFIG)
        tokens = load_tokens(cfg.token_path, sandbox=None)
        if tokens and not is_expired_for_day(tokens):
            client = ETradeClient(cfg, tokens)
            payload = client._request("GET", "/v1/accounts/list.json")  # noqa: SLF001
            parsed = parse_accounts(payload)
            for row in parsed:
                if not isinstance(row, dict):
                    continue
                id_key = str(row.get("account_id_key") or row.get("accountIdKey") or "").strip()
                if not id_key:
                    continue
                label = str(
                    row.get("display_label")
                    or row.get("account_name")
                    or row.get("accountName")
                    or id_key
                )
                status = str(row.get("account_status") or row.get("accountStatus") or "")
                accounts.append(
                    {
                        "account_id_key": id_key,
                        "display_label": label,
                        "account_id": str(row.get("account_id") or row.get("accountId") or ""),
                        "account_status": status,
                        "role": "brokerage",
                        "source": "live",
                        "selected": id_key == selected,
                    }
                )
            live_ok = True
        else:
            live_error = "PC E*TRADE session missing or expired - showing saved accounts"
    except Exception as exc:
        live_error = str(exc)

    if not accounts:
        # Config fallback (at least the account the desktop trader uses)
        seen: set[str] = set()
        for role, raw in (("long", long_raw), ("short", short_raw)):
            entry = _selected_account_entry(raw, role)
            if entry is None:
                continue
            key = entry["account_id_key"]
            if key in seen:
                # Same account on long+short - keep one row, mark dual role
                for a in accounts:
                    if a["account_id_key"] == key:
                        a["role"] = "long+short"
                continue
            seen.add(key)
            entry["selected"] = key == selected
            accounts.append(entry)

    # Ensure selected flag
    if selected and accounts and not any(a.get("selected") for a in accounts):
        accounts[0]["selected"] = True

    return {
        "ok": True,
        "live": live_ok,
        "message": "Live account list" if live_ok else (live_error or "Saved accounts only"),
        "selected_account_id_key": selected or (accounts[0]["account_id_key"] if accounts else None),
        "accounts": accounts,
        "count": len(accounts),
    }


def select_account_for_phone(account_id_key: str, display_label: str | None = None) -> dict[str, Any]:
    """Persist selected brokerage account on the shared API (long config) + mirror short."""
    key = str(account_id_key or "").strip()
    if not key:
        raise ValueError("account_id_key is required")
    label = (display_label or "").strip()
    if not label:
        # Prefer label from live/config list
        listed = list_accounts_for_phone().get("accounts") or []
        for row in listed:
            if str(row.get("account_id_key")) == key:
                label = str(row.get("display_label") or key)
                break
        if not label:
            label = key

    try:
        from shared_etrade_api import save_shared_selected_account

        save_shared_selected_account(key, display_label=label)
        updated = [LONG_CONFIG.name, SHORT_CONFIG.name]
    except Exception:
        from datetime import datetime, timezone

        stamp = datetime.now(timezone.utc).isoformat()
        updated = []
        for path in (LONG_CONFIG, SHORT_CONFIG):
            raw = _read_json(path)
            if not raw and path == SHORT_CONFIG:
                raw = {"background_worker": {"dry_run": True}}
            if not raw and path != LONG_CONFIG:
                continue
            if not raw:
                raw = {}
            sel = dict(raw.get("selected_account") or {})
            sel["account_id_key"] = key
            sel["display_label"] = label
            sel["confirmed_at"] = stamp
            raw["selected_account"] = sel
            _write_json(path, raw)
            updated.append(path.name)

    _log(f"Phone selected account {key} ({label}) -> shared API {', '.join(updated)}")
    return {
        "ok": True,
        "account_id_key": key,
        "display_label": label,
        "shared_api": True,
        "updated_configs": updated,
        "message": f"Account selected (shared API): {label}",
    }


def auth_status() -> dict[str, Any]:
    from etrade_api.config import load_config
    from etrade_api.oauth import is_expired_for_day, load_tokens, needs_renewal

    cfg = load_config(LONG_CONFIG)
    tokens = load_tokens(cfg.token_path, sandbox=None)
    long_raw = _read_json(LONG_CONFIG)
    short_raw = _read_json(SHORT_CONFIG)
    shared = _shared_api_for_phone()
    api = shared.get("api") if isinstance(shared.get("api"), dict) else {}
    shared_label = str(api.get("account_label") or "").strip() or None
    long_label = shared_label or (long_raw.get("selected_account") or {}).get("display_label")
    short_label = shared_label or (short_raw.get("selected_account") or {}).get("display_label") or long_label
    sandbox = bool(api.get("sandbox", long_raw.get("sandbox", True)))
    if not tokens:
        return {
            "ok": True,
            "connected": False,
            "message": "Not connected - use phone login to authorize the desktop app",
            "sandbox": sandbox,
            "shared_api": True,
            "api_environment": "sandbox" if sandbox else "production",
            "account": shared_label,
            "long_account": long_label,
            "short_account": short_label,
        }
    expired = is_expired_for_day(tokens)
    idle = needs_renewal(tokens)
    age_min = (time.time() - tokens.created_at) / 60 if tokens.created_at else None
    return {
        "ok": True,
        "connected": not expired,
        "needs_full_login": expired,
        "needs_renewal": idle and not expired,
        "sandbox": tokens.sandbox,
        "shared_api": True,
        "api_environment": "sandbox" if tokens.sandbox else "production",
        "account": shared_label,
        "message": (
            "Session expired at midnight ET - full Connect required"
            if expired
            else ("Token idle - renew soon" if idle else "Connected to E*TRADE (shared API)")
        ),
        "age_minutes": round(age_min, 1) if age_min is not None else None,
        "long_account": long_label,
        "short_account": short_label,
    }


def oauth_start() -> dict[str, Any]:
    from etrade_api.config import load_config
    from etrade_api.oauth import session_is_live, start_authorization

    cfg = load_config(LONG_CONFIG)
    if not cfg.consumer_key or not cfg.consumer_secret:
        raise RuntimeError("Missing consumer key/secret in etrade_config.json on the PC")
    # CRITICAL: phone + PC share one E*TRADE access token. Starting a new OAuth
    # from the phone and Accept-ing invalidates the PC worker session (token_rejected).
    live_ok, detail = session_is_live(cfg)
    if live_ok:
        return {
            "ok": True,
            "already_connected": True,
            "authorize_url": None,
            "sandbox": cfg.sandbox,
            "message": (
                "PC already has a live E*TRADE session — no new login needed. "
                "Use Refresh for account data. Starting OAuth here would disconnect the PC."
            ),
            "detail": detail,
        }
    pending = start_authorization(cfg)
    oauth = pending.oauth
    token = getattr(oauth, "resource_owner_key", None) or oauth.token.get("oauth_token", "")
    secret = getattr(oauth, "resource_owner_secret", None) or oauth.token.get(
        "oauth_token_secret", ""
    )
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(
        json.dumps(
            {
                "request_token": token,
                "request_token_secret": secret,
                "authorize_url": pending.authorize_url,
                "sandbox": cfg.sandbox,
                "use_oob": cfg.use_oob,
                "consumer_key": cfg.consumer_key,
                "consumer_secret": cfg.consumer_secret,
                "callback_url": cfg.callback_url,
                "token_path": str(cfg.token_path),
                "source": "phone_bridge",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "ok": True,
        "authorize_url": pending.authorize_url,
        "sandbox": cfg.sandbox,
        "use_oob": cfg.use_oob,
        "message": (
            "Open the link, sign in to E*TRADE, Accept, then paste the verification code."
        ),
    }


def oauth_finish(verifier: str) -> dict[str, Any]:
    from pathlib import Path as P

    from requests_oauthlib import OAuth1Session

    from etrade_api.config import ETradeConfig, build_config
    from etrade_api.oauth import OAuthPending, finish_authorization, normalize_verifier

    if not PENDING_FILE.exists():
        raise RuntimeError("No pending login. Tap Connect first.")
    raw = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    code = normalize_verifier(verifier)
    if not code:
        raise ValueError("Verification code is empty")
    cfg = build_config(
        raw["consumer_key"],
        raw["consumer_secret"],
        sandbox=bool(raw.get("sandbox", True)),
        callback_url=raw.get("callback_url", ETradeConfig.callback_url),
        use_oob=bool(raw.get("use_oob", True)),
        token_path=P(raw.get("token_path", "etrade_tokens.json")),
    )
    oauth = OAuth1Session(
        client_key=cfg.consumer_key,
        client_secret=cfg.consumer_secret,
        resource_owner_key=raw["request_token"],
        resource_owner_secret=raw["request_token_secret"],
        callback_uri="oob" if cfg.use_oob else cfg.callback_url,
        signature_method="HMAC-SHA1",
    )
    pending = OAuthPending(config=cfg, oauth=oauth, authorize_url=raw.get("authorize_url", ""))
    tokens = finish_authorization(pending, code)
    PENDING_FILE.unlink(missing_ok=True)
    env = "sandbox" if tokens.sandbox else "production"
    return {
        "ok": True,
        "sandbox": tokens.sandbox,
        "message": f"Logged in ({env}). Tokens saved for the desktop app.",
        "token_path": str(cfg.token_path),
    }


def _set_worker_flags(path: Path, **flags: Any) -> dict[str, Any]:
    raw = _read_json(path)
    worker = dict(raw.get("background_worker") or {})
    worker.update(flags)
    if flags.get("dry_run"):
        worker["live_trading"] = False
    elif "dry_run" in flags and not flags["dry_run"] and worker.get("auto_execute"):
        worker["live_trading"] = True
    raw["background_worker"] = worker
    _write_json(path, raw)
    return worker


def apply_controls(body: dict[str, Any]) -> dict[str, Any]:
    side = str(body.get("side") or "all").lower().strip()
    patch: dict[str, Any] = {}
    for key in ("dry_run", "auto_execute", "paused"):
        if key in body:
            patch[key] = bool(body[key])
    if not patch:
        raise ValueError("No control fields (dry_run, auto_execute, paused)")
    out: dict[str, Any] = {"ok": True, "side": side}
    if side in ("long", "all"):
        out["long"] = _set_worker_flags(LONG_CONFIG, **patch)
    if side in ("short", "all"):
        out["short"] = _set_worker_flags(SHORT_CONFIG, **patch)
    if side not in ("long", "short", "all"):
        raise ValueError("side must be long, short, or all")
    return out


def stop_all() -> dict[str, Any]:
    _set_worker_flags(LONG_CONFIG, paused=True, auto_execute=False)
    _set_worker_flags(SHORT_CONFIG, paused=True, auto_execute=False)
    return {"ok": True, "message": "Both sleeves stopped", "paused": True}


def resume_all() -> dict[str, Any]:
    _set_worker_flags(LONG_CONFIG, paused=False)
    _set_worker_flags(SHORT_CONFIG, paused=False)
    return {"ok": True, "message": "Both sleeves resumed", "paused": False}


def _sort_lan_ips(found: list[str]) -> list[str]:
    """Wi-Fi LAN first. APIPA / WSL last so phone_hint is the address the phone can use."""

    def rank(ip: str) -> tuple[int, str]:
        if ip.startswith("192.168."):
            return (0, ip)
        if ip.startswith("10."):
            return (1, ip)
        if ip.startswith("172."):
            return (2, ip)
        if ip.startswith("169.254."):
            return (9, ip)
        return (5, ip)

    uniq: list[str] = []
    for ip in found:
        if ip and ip not in uniq and not ip.startswith("127."):
            uniq.append(ip)
    return sorted(uniq, key=rank)


def lan_ips() -> list[str]:
    found: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in found:
                found.append(ip)
    except OSError:
        pass
    return _sort_lan_ips(found)


def build_agents_for_phone() -> dict[str, Any]:
    """Compact agent list + analysis/findings/projections for phone Agents window.

    Prefers regenerating from Finance/output via Oxygen-OS helper script when present;
    falls back to reading the published work/phone/etrade-agents.json snapshot.
    """
    if not phone_ui_info_enabled():
        return {
            "ok": True,
            "disabled": True,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "agent_count": 0,
            "agents": [],
            "source": "disabled",
            "message": (
                "Phone UI info disabled on PC "
                "(phone_bridge_config.json phone_ui_info_enabled=false). "
                "Set true and restart phone_bridge to re-enable agents feed."
            ),
        }
    oxygen = Path.home() / "Documents" / "GitHub" / "Oxygen-OS"
    helper = oxygen / "scripts" / "build-etrade-agents-json.py"
    snapshot = oxygen / "work" / "phone" / "etrade-agents.json"
    # Try live rebuild so phone sees latest agent runs
    if helper.is_file():
        try:
            import subprocess

            subprocess.run(
                [sys.executable, str(helper)],
                check=False,
                capture_output=True,
                text=True,
                timeout=90,
            )
        except Exception as exc:
            _log(f"agents rebuild helper failed: {exc}")
    if snapshot.is_file():
        try:
            data = json.loads(snapshot.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("agents"), list):
                data.setdefault("ok", True)
                data.setdefault("source", "finance_output")
                return data
        except (OSError, json.JSONDecodeError) as exc:
            _log(f"agents snapshot read failed: {exc}")
    # Minimal empty payload - phone can still show empty state
    return {
        "ok": True,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent_count": 0,
        "agents": [],
        "source": "empty",
        "message": "No agent snapshot yet - run agents on PC / publish etrade-agents.json",
    }


def build_orders_for_phone() -> dict[str, Any]:
    """Best-effort broker orders for the phone Orders window (PC tokens required).

    Fetches OPEN plus recent history (same as the old phone-native list) and
    flattens nested E*TRADE OrderDetail/Instrument payloads so cards have
    symbol/action/status.
    """
    try:
        from etrade_api.client import ETradeClient
        from etrade_api.config import ETradeConfig

        cfg = None
        if hasattr(ETradeConfig, "load"):
            try:
                cfg = ETradeConfig.load(LONG_CONFIG)
            except Exception:
                cfg = None
        if cfg is None:
            try:
                from etrade_api.config import load_config

                cfg = load_config(LONG_CONFIG)
            except Exception:
                cfg = None
        if cfg is None:
            return {
                "ok": True,
                "orders": [],
                "source": "none",
                "message": "No E*TRADE config on PC",
            }
        client = ETradeClient(cfg)
        key = ""
        snap = _load_account_snapshot()
        if isinstance(snap, dict):
            key = str(snap.get("account_id_key") or "")
        if not key and hasattr(client, "list_accounts"):
            try:
                accounts = client.list_accounts() or []
                if accounts and isinstance(accounts[0], dict):
                    key = str(accounts[0].get("account_id_key") or "")
            except Exception:
                key = ""
        if not key:
            return {
                "ok": True,
                "orders": [],
                "source": "none",
                "message": "No account id on PC",
            }
        collected: list[Any] = []
        errors: list[str] = []
        for status in ("OPEN", None):
            try:
                chunk = _call_list_orders(client, key, status)
                if isinstance(chunk, list):
                    collected.extend(chunk)
            except Exception as exc:
                errors.append(str(exc))
        if not collected and errors:
            return {
                "ok": True,
                "orders": [],
                "source": "error",
                "message": errors[0],
            }
        orders = flatten_etrade_orders(collected)
        open_n = sum(
            1
            for row in orders
            if "OPEN" in str(row.get("status") or "").upper()
            or str(row.get("status") or "").upper() in {"PARTIAL", "CANCEL_REQUESTED"}
        )
        return {
            "ok": True,
            "orders": orders,
            "count": len(orders),
            "open_count": open_n,
            "source": "pc_live" if orders else "pc_empty",
            "message": f"{len(orders)} orders from PC",
        }
    except Exception as exc:
        return {
            "ok": True,
            "orders": [],
            "source": "error",
            "message": str(exc),
        }


def build_full_for_phone(force_refresh: bool = True) -> dict[str, Any]:
    """One-shot full data pack for the phone: dashboard + agents + accounts + orders.

    Re-publishes the Oxygen-OS GitHub bus file with orders embedded so the
    phone can refresh on cellular / other Wi‑Fi (no LAN bridge required).
    """
    dash = build_dashboard(force_refresh=force_refresh, publish=False)
    agents = build_agents_for_phone()
    accounts = list_accounts_for_phone()
    orders = build_orders_for_phone()
    if isinstance(dash, dict):
        packed = dict(dash)
        packed["orders"] = orders if isinstance(orders, dict) else {"ok": True, "orders": []}
        packed["bus"] = "github"
        try:
            _publish_dashboard_to_oxygen(packed)
        except Exception as exc:
            _log(f"github bus full publish note: {exc}")
    return {
        "ok": True,
        "version": BRIDGE_VERSION,
        "updated_at": time.time(),
        "force_refresh": bool(force_refresh),
        "data_pull": dash.get("data_pull") or {},
        "dashboard": dash,
        "agents": agents,
        "accounts": accounts,
        "orders": orders,
    }


def _wants_force_refresh(query: dict[str, list[str]]) -> bool:
    """True when phone requests a full/live PC pull (?refresh=1 or ?full=1)."""
    for key in ("refresh", "full", "force"):
        vals = query.get(key) or []
        for v in vals:
            s = str(v).strip().lower()
            if s in ("1", "true", "yes", "full", "force"):
                return True
    return False


class BridgeHandler(BaseHTTPRequestHandler):
    bridge_token: str = ""

    def log_message(self, fmt: str, *args: Any) -> None:
        _log(f"{self.address_string()} {fmt % args}")

    def _send(self, code: int, payload: dict[str, Any] | list[Any]) -> None:
        safe = _sanitize_phone_payload(payload)
        body = json.dumps(safe, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Bridge-Token, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}

    def _authorized(self) -> bool:
        expected = (self.bridge_token or "").strip()
        if not expected:
            return False
        header = (self.headers.get("X-Bridge-Token") or "").strip()
        if header and secrets.compare_digest(header, expected):
            return True
        auth = (self.headers.get("Authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            if token and secrets.compare_digest(token, expected):
                return True
        return False

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Bridge-Token, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def _send_file(self, path: Path, content_type: str, download_name: str) -> None:
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query or "")
        force = _wants_force_refresh(query)
        try:
            if path == "/health":
                ips = lan_ips()
                quality = _data_quality_report()
                cfg = load_bridge_config()
                try:
                    rmin = float(
                        cfg.get("phone_refresh_interval_minutes") or DEFAULT_PHONE_REFRESH_INTERVAL_MIN
                    )
                except (TypeError, ValueError):
                    rmin = float(DEFAULT_PHONE_REFRESH_INTERVAL_MIN)
                last = _read_json(ROOT / "output" / "phone_refresh_last.json")
                self._send(
                    200,
                    {
                        "ok": True,
                        "service": "finance-phone-bridge",
                        "version": BRIDGE_VERSION,
                        "port": self.server.server_address[1],
                        "lan_ips": ips,
                        "phone_hint": f"http://{ips[0]}:{self.server.server_address[1]}" if ips else None,
                        "phone_ui_info_enabled": phone_ui_info_enabled(),
                        "shared_api": True,
                        "practice_independent": True,
                        "features_path": "/api/features",
                        "full_path": "/api/full",
                        "orders_path": "/api/orders",
                        "data_quality": quality,
                        "data_strong": bool(quality.get("strong")),
                        "data_current": bool(quality.get("data_current")),
                        "phone_refresh_enabled": bool(cfg.get("phone_refresh_enabled", True)),
                        "phone_refresh_interval_minutes": rmin,
                        "phone_refresh_market_hours_only": bool(
                            cfg.get("phone_refresh_market_hours_only", DEFAULT_PHONE_REFRESH_MARKET_HOURS_ONLY)
                        ),
                        "phone_refresh_last_at": last.get("at") if isinstance(last, dict) else None,
                    },
                )
                return
            if not self._authorized():
                self._send(401, {"ok": False, "error": "Unauthorized - set bridge token in the phone app"})
                return
            if path == "/api/dashboard":
                self._send(200, build_dashboard(force_refresh=force))
                return
            if path == "/api/full":
                # Full data pack for phone Refresh - always attempt live PC portfolio pull
                self._send(200, build_full_for_phone(force_refresh=True))
                return
            if path == "/api/orders":
                self._send(200, build_orders_for_phone())
                return
            if path == "/api/features":
                self._send(200, build_features_for_phone())
                return
            if path == "/api/agents":
                self._send(200, build_agents_for_phone())
                return
            if path == "/api/accounts":
                self._send(200, list_accounts_for_phone())
                return
            if path == "/api/auth/status":
                self._send(200, auth_status())
                return
            if path in ("/api/app_update", "/api/apk"):
                # Prefer latest published APK: Oxygen-OS (update channel), then Moto, Desktop, runtime.
                candidates = [
                    Path.home() / "Documents" / "GitHub" / "Oxygen-OS" / "etrade-app" / "dist" / "ETradeTrader.apk",
                    Path.home() / "Documents" / "GitHub" / "Moto" / "etrade-app" / "dist" / "ETradeTrader.apk",
                    Path.home() / "Desktop" / "ETradeTrader.apk",
                    ROOT / "ETradeTrader.apk",
                ]
                apk_path = next((p for p in candidates if p.is_file() and p.stat().st_size > 50_000), None)
                if apk_path is None:
                    self._send(
                        404,
                        {
                            "ok": False,
                            "error": "APK not found on PC - build etrade-app/dist/ETradeTrader.apk first",
                        },
                    )
                    return
                _log(f"Serving app update from {apk_path} ({apk_path.stat().st_size} bytes)")
                self._send_file(
                    apk_path,
                    "application/vnd.android.package-archive",
                    "ETradeTrader.apk",
                )
                return
            self._send(404, {"ok": False, "error": f"Unknown path {path}"})
        except Exception as exc:
            _log(traceback.format_exc())
            self._send(500, {"ok": False, "error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        try:
            if not self._authorized():
                self._send(401, {"ok": False, "error": "Unauthorized - set bridge token in the phone app"})
                return
            body = self._read_body()
            if path == "/api/oauth/start":
                self._send(200, oauth_start())
                return
            if path == "/api/oauth/finish":
                verifier = (
                    body.get("verifier")
                    or body.get("oauth_verifier")
                    or body.get("code")
                    or body.get("verification_code")
                    or ""
                )
                self._send(200, oauth_finish(str(verifier)))
                return
            if path in ("/api/accounts/select", "/api/select_account"):
                self._send(
                    200,
                    select_account_for_phone(
                        str(body.get("account_id_key") or body.get("accountIdKey") or ""),
                        str(body.get("display_label") or body.get("displayLabel") or "") or None,
                    ),
                )
                return
            if path == "/api/controls":
                self._send(200, apply_controls(body))
                return
            if path == "/api/stop_all":
                self._send(200, stop_all())
                return
            if path == "/api/resume_all":
                self._send(200, resume_all())
                return
            self._send(404, {"ok": False, "error": f"Unknown path {path}"})
        except Exception as exc:
            _log(traceback.format_exc())
            self._send(400, {"ok": False, "error": str(exc)})


def _acquire_instance_lock() -> Any:
    """Keep a single phone_bridge. Must use use_last_error or GetLastError is stale."""
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.CreateMutexW(None, True, "Local\\FinancePhoneBridge")
    err = ctypes.get_last_error()
    already = 183  # ERROR_ALREADY_EXISTS
    if not handle:
        _log(f"phone_bridge mutex create failed err={err} - continuing")
        return "no-mutex"
    if err == already:
        kernel32.CloseHandle(handle)
        _log("phone_bridge already running (mutex) - exit")
        return None
    lock_path = ROOT / "output" / "phone_bridge.lock"
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass
    return handle


def main() -> int:
    lock = _acquire_instance_lock()
    if lock is None:
        return 0
    cfg = load_bridge_config()
    host = str(cfg.get("host") or DEFAULT_HOST)
    port = int(cfg.get("port") or DEFAULT_PORT)
    token = str(cfg.get("bridge_token") or "")
    BridgeHandler.bridge_token = token

    class BridgeServer(ThreadingHTTPServer):
        allow_reuse_address = False

    try:
        httpd = BridgeServer((host, port), BridgeHandler)
    except OSError as exc:
        _log(f"phone_bridge bind failed on {host}:{port}: {exc}")
        return 1
    ips = lan_ips()
    _log(f"Phone bridge v{BRIDGE_VERSION} listening on {host}:{port}")
    for ip in ips:
        _log(f"  Phone base URL: http://{ip}:{port}")
    _log(f"  Bridge token (enter in phone app): {token}")
    _log("  GET /health  (no auth)  |  GET /api/dashboard  |  POST /api/oauth/start")
    try:
        rmin = float(cfg.get("phone_refresh_interval_minutes") or DEFAULT_PHONE_REFRESH_INTERVAL_MIN)
    except (TypeError, ValueError):
        rmin = float(DEFAULT_PHONE_REFRESH_INTERVAL_MIN)
    market_only = bool(cfg.get("phone_refresh_market_hours_only", DEFAULT_PHONE_REFRESH_MARKET_HOURS_ONLY))
    hours_note = "during market hours" if market_only else "all hours"
    _log(
        f"  Phone data refresh: every {rmin:g} min {hours_note} "
        f"(enabled={bool(cfg.get('phone_refresh_enabled', True))})"
    )

    # Print a compact pairing card for first-run
    print("")
    print("=" * 56)
    print("  E*TRADE Phone Bridge")
    print("=" * 56)
    if ips:
        print(f"  Base URL:  http://{ips[0]}:{port}")
    print(f"  Token:     {token}")
    print(f"  Auto-refresh: every {rmin:g} min ({'market hours' if market_only else 'all hours'})")
    print("  Enter both in the phone app Setup screen.")
    print("=" * 56)
    print("")

    start_phone_refresh_thread(cfg)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        _log("Stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
