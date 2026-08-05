#!/usr/bin/env python3
"""Headless E*TRADE worker — agents, strategy plan, and orders without the GUI."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime, time as dt_time, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from etrade_api.client import ETradeClient
from etrade_api.config import get_selected_account, load_config
from etrade_api.oauth import is_expired_for_day, load_tokens, needs_renewal, renew_access_token
from strategy_engine import (
    PLAN_FILE,
    StrategyPlan,
    build_strategy_plan,
    execute_orders,
    preview_orders,
    run_agent_pipeline,
    save_strategy_plan,
)

OUTPUT = ROOT / "output"
LOG_FILE = OUTPUT / "etrade_worker.log"
STATE_FILE = OUTPUT / "etrade_worker_state.json"
LOCK_FILE = OUTPUT / "etrade_worker.lock"
CONFIG_PATH = ROOT / "etrade_config.json"
SHORT_CONFIG_PATH = ROOT / "short_etrade_config.json"
SERVICE_CHECK_SECONDS = 60
SERVICE_MUTEX_NAME = "Local\\FinanceETradeWorkerService"
_service_mutex_handle: int | None = None
_STATE_LOCK = threading.RLock()
_LOG_LOCK = threading.RLock()

DEFAULT_WORKER = {
    "auto_execute": True,
    "live_trading": True,
    "day_trading": True,
    "dry_run": False,
    "paused": False,
    # Legacy "full cycle" cadence (used as fallback / sleep baseline).
    # Per-lane cadences in pipeline_lanes control what actually runs.
    "pipeline_interval_minutes": 5,
    "pipeline_off_hours_interval_minutes": 30,
    "accuracy_interval_minutes": 15,
    "accuracy_off_hours_interval_minutes": 60,
    # RTH: full lanes. Off-hours: eco mode (sparse agents / long intervals) unless disabled.
    "pipeline_market_hours_only": True,
    "pipeline_eco_mode_off_hours": True,
    "pre_open_research_enabled": True,
    "plan_interval_minutes": 20,
    "execute_min_interval_minutes": 15,
    "day_trading_interval_minutes": 5,
    "allow_off_hours_trading": False,
    "gui_defer_to_worker": True,
    "ui_poll_ms": 500,
    "day_panel_refresh_minutes": 5,
    "worker_status_poll_ms": 60000,
    # Per-lane minutes: market hours vs off-hours.
    # Tuned so critical/day risk stays hot, Yahoo-heavy flow is less frequent
    # (better option-chain quality), research is slow-moving.
    "pipeline_lanes": {
        "critical": {"market": 5, "off_hours": 30, "eco_off_hours": 90},
        "quant": {"market": 10, "off_hours": 45, "eco_off_hours": 120},
        "flow": {"market": 15, "off_hours": 90, "eco_off_hours": 0},
        "research": {"market": 60, "off_hours": 90, "eco_off_hours": 240},
    },
}


def automation_paused(config_path: Path = CONFIG_PATH) -> bool:
    return bool(worker_settings(config_path).get("paused", False))


def _is_short_config(config_path: Path) -> bool:
    name = config_path.name.lower()
    return "short" in name


def _day_config_keys(config_path: Path) -> tuple[str, ...]:
    if _is_short_config(config_path):
        return ("short_day_trading", "day_trading")
    return ("day_trading",)


def _apply_pause_to_config(config_path: Path, paused: bool) -> dict[str, Any]:
    """Pause or resume one sleeve config (long or short)."""
    from etrade_api.config import read_config_raw, write_config_raw

    if not config_path.exists():
        return {
            "path": str(config_path.name),
            "skipped": True,
            "paused": paused,
            "message": f"{config_path.name} not found",
        }

    raw = read_config_raw(config_path)
    worker = dict(raw.get("background_worker", {}))
    is_short = _is_short_config(config_path)

    if paused:
        # Preserve prior flags so Resume restores each sleeve correctly
        if not worker.get("paused"):
            worker["pause_snapshot"] = {
                "auto_execute": bool(worker.get("auto_execute", not is_short)),
                "day_trading": bool(worker.get("day_trading", True)),
                "live_trading": bool(worker.get("live_trading", False)),
            }
        worker["paused"] = True
        worker["auto_execute"] = False
        worker["day_trading"] = False
        worker["live_trading"] = False
    else:
        snap = worker.get("pause_snapshot") if isinstance(worker.get("pause_snapshot"), dict) else {}
        worker["paused"] = False
        if snap:
            worker["auto_execute"] = bool(snap.get("auto_execute", not is_short))
            worker["day_trading"] = bool(snap.get("day_trading", True))
            dry = bool(worker.get("dry_run", is_short))
            live = snap.get("live_trading")
            if live is None:
                worker["live_trading"] = bool(worker["auto_execute"]) and not dry
            else:
                worker["live_trading"] = bool(live) and not dry
            worker.pop("pause_snapshot", None)
        else:
            # Legacy resume (no snapshot): long defaults on; short keeps dry-run-friendly defaults
            if is_short:
                worker["auto_execute"] = bool(worker.get("auto_execute", False))
                worker["day_trading"] = True
                dry = bool(worker.get("dry_run", True))
                worker["live_trading"] = bool(worker["auto_execute"]) and not dry
            else:
                worker["auto_execute"] = True
                worker["day_trading"] = True
                dry = bool(worker.get("dry_run", False))
                worker["live_trading"] = not dry

    raw["background_worker"] = worker
    day_enabled = (not paused) and bool(worker.get("day_trading", True))
    for key in _day_config_keys(config_path):
        if key in raw or key == _day_config_keys(config_path)[0]:
            day_cfg = dict(raw.get(key) or {})
            day_cfg["enabled"] = day_enabled
            raw[key] = day_cfg
    write_config_raw(config_path, raw)

    return {
        "path": config_path.name,
        "paused": paused,
        "auto_execute": bool(worker.get("auto_execute")),
        "day_trading": bool(worker.get("day_trading")),
        "dry_run": bool(worker.get("dry_run")),
        "live_trading": bool(worker.get("live_trading")),
        "skipped": False,
    }


def set_automation_paused(
    paused: bool,
    config_path: Path | None = None,
    *,
    both_sleeves: bool = True,
) -> dict[str, Any]:
    """Pause or resume **trading** only (desktop Stop all / Resume all).

    Stops swing auto-execute, day trading, and live order submission on both
    sleeves. Agent **pipeline** on a dual-PC pipeline host keeps running
    (BOXONE always-on); only the broker host honors this for order placement.
    """
    long_path = CONFIG_PATH
    short_path = SHORT_CONFIG_PATH

    if both_sleeves:
        targets = [long_path, short_path]
    else:
        targets = [Path(config_path) if config_path is not None else long_path]

    sleeve_results: list[dict[str, Any]] = []
    for path in targets:
        try:
            sleeve_results.append(_apply_pause_to_config(path, paused))
        except Exception as exc:
            sleeve_results.append(
                {
                    "path": getattr(path, "name", str(path)),
                    "paused": paused,
                    "error": str(exc),
                    "skipped": True,
                }
            )

    msg = (
        "Trading stopped on buy + short apps (pipeline keeps running if remote)."
        if paused
        else "Trading resumed on buy + short apps."
    )
    if not both_sleeves:
        msg = "Trading stopped." if paused else "Trading resumed."
    _log(msg)

    # Prefer long-sleeve flags; include both sleeve results.
    primary = next((r for r in sleeve_results if r.get("path") == long_path.name and not r.get("skipped")), None)
    if primary is None and sleeve_results:
        primary = next((r for r in sleeve_results if not r.get("skipped")), sleeve_results[0])
    primary = primary or {}

    return {
        "paused": paused,
        "both_sleeves": both_sleeves,
        "auto_execute": bool(primary.get("auto_execute", False)),
        "day_trading": bool(primary.get("day_trading", False)),
        "dry_run": bool(primary.get("dry_run", False)),
        "live_trading": bool(primary.get("live_trading", False)),
        "sleeves": sleeve_results,
        "message": msg,
    }


def gui_should_defer_to_worker(config_path: Path = CONFIG_PATH) -> bool:
    """When True, the GUI should not duplicate headless agent/trading loops."""
    settings = worker_settings(config_path)
    if "gui_defer_to_worker" in settings:
        return bool(settings["gui_defer_to_worker"])
    if LOG_FILE.exists():
        return (time.time() - LOG_FILE.stat().st_mtime) < 900
    return False


def _pipeline_runs_off_hours(settings: dict[str, Any]) -> bool:
    """True when agent lanes may run outside RTH/pre-open.

    Eco mode (default) allows a *reduced* off-hours pipeline even when
    pipeline_market_hours_only is True. Full off-hours roster only when
    market_hours_only is False and eco is off.
    """
    try:
        from agent_pipelines import pipeline_eco_mode_enabled

        if pipeline_eco_mode_enabled(settings):
            return True
    except Exception:
        if bool(settings.get("pipeline_eco_mode_off_hours", True)):
            return True
    return not bool(settings.get("pipeline_market_hours_only", True))


def _effective_pipeline_interval_minutes(
    settings: dict[str, Any],
    *,
    market_open: bool,
) -> int:
    """Soonest lane cadence — used for service sleep baseline."""
    try:
        from agent_pipelines import DEFAULT_LANE_SCHEDULE, lane_interval_minutes

        mins = [
            lane_interval_minutes(pid, market_open=market_open, settings=settings)
            for pid in DEFAULT_LANE_SCHEDULE
        ]
        if mins:
            return max(1, min(mins))
    except Exception:
        pass
    if market_open:
        return max(1, int(settings.get("pipeline_interval_minutes", 5)))
    return max(15, int(settings.get("pipeline_off_hours_interval_minutes", 30)))


def _effective_accuracy_interval_minutes(
    settings: dict[str, Any],
    *,
    market_open: bool,
) -> int:
    if market_open:
        return max(5, int(settings.get("accuracy_interval_minutes", 15)))
    return max(15, int(settings.get("accuracy_off_hours_interval_minutes", 60)))


def _lanes_due(
    state: dict[str, Any],
    settings: dict[str, Any],
    *,
    market_open: bool,
    force: bool = False,
    eco_mode: bool = False,
) -> list[str]:
    """Return pipeline lane ids that should run now."""
    from agent_pipelines import lane_interval_minutes

    lane_times = state.get("last_pipeline_lane_at")
    if not isinstance(lane_times, dict):
        lane_times = {}
    due: list[str] = []
    for pid in ("critical", "quant", "flow", "research"):
        interval = lane_interval_minutes(
            pid,
            market_open=market_open,
            settings=settings,
            eco_mode=eco_mode if not market_open else False,
        )
        if interval <= 0:
            continue  # eco-disabled lane
        if force:
            due.append(pid)
            continue
        # Only trust *per-lane* timestamps. Falling back to last_pipeline_at
        # starves lanes that never completed (research was stuck for days while
        # critical/quant/flow kept refreshing the global stamp).
        if pid not in lane_times:
            due.append(pid)
            continue
        last = lane_times.get(pid)
        if _interval_due(last, interval, force=False):
            due.append(pid)
    # Preserve preferred order
    order = ["critical", "quant", "flow", "research"]
    due = [p for p in order if p in due]
    if eco_mode and not market_open:
        try:
            from agent_pipelines import filter_lanes_for_eco

            due = filter_lanes_for_eco(due)
        except Exception:
            due = [p for p in due if p != "flow"]
    return due


def _next_service_sleep_seconds(config_path: Path = CONFIG_PATH) -> float:
    """Sleep until the next task is due instead of waking every minute."""
    settings = worker_settings(config_path)
    state = load_worker_state()
    now = time.time()
    market_open = is_us_market_open()
    waits: list[float] = [30.0]
    # Per-lane sleep targets
    try:
        from agent_pipelines import DEFAULT_LANE_SCHEDULE, lane_interval_minutes

        lane_times = state.get("last_pipeline_lane_at")
        if not isinstance(lane_times, dict):
            lane_times = {}
        for pid in DEFAULT_LANE_SCHEDULE:
            interval_min = lane_interval_minutes(pid, market_open=market_open, settings=settings)
            # No last_pipeline_at fallback — missing lane key means due now.
            last = lane_times.get(pid)
            interval = max(60.0, interval_min * 60)
            if last:
                waits.append(max(0.0, interval - (now - float(last))))
            else:
                waits.append(0.0)
    except Exception:
        waits.append(
            max(
                60.0,
                _effective_pipeline_interval_minutes(settings, market_open=market_open) * 60,
            )
        )
    interval_overrides = {
        "last_accuracy_at": _effective_accuracy_interval_minutes(settings, market_open=market_open),
    }
    for last_key, interval_key, default_min in (
        ("last_accuracy_at", "accuracy_interval_minutes", 15),
        ("last_plan_at", "plan_interval_minutes", 20),
        ("last_execute_at", "execute_min_interval_minutes", 15),
        ("last_day_trade_at", "day_trading_interval_minutes", 5),
    ):
        last = state.get(last_key)
        interval_min = interval_overrides.get(last_key, int(settings.get(interval_key, default_min)))
        interval = max(60.0, interval_min * 60)
        if last:
            waits.append(max(0.0, interval - (now - float(last))))
        else:
            waits.append(0.0)
    return min(max(min(waits), 15.0), 300.0)


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Keep logs ASCII-safe for broken Windows consoles; full text still goes to UTF-8 file.
    text = str(msg)
    line = f"[{stamp}] {text}"
    try:
        with _LOG_LOCK:
            with LOG_FILE.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
    except OSError:
        pass
    try:
        # Never raise — print can throw UnicodeEncodeError under pythonw/cp1252
        print(line.encode("ascii", "replace").decode("ascii"), flush=True)
    except Exception:
        pass


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def worker_settings(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    raw = _read_json(config_path)
    settings = dict(DEFAULT_WORKER)
    legacy = raw.get("background_worker", {})
    if not isinstance(legacy, dict):
        legacy = {}
    lane_defaults = {
        k: dict(v) for k, v in (DEFAULT_WORKER.get("pipeline_lanes") or {}).items() if isinstance(v, dict)
    }
    settings.update(legacy)
    # Deep-merge per-lane schedule so partial config keeps other lane defaults.
    raw_lanes = legacy.get("pipeline_lanes") if isinstance(legacy.get("pipeline_lanes"), dict) else {}
    merged_lanes = {k: dict(v) for k, v in lane_defaults.items()}
    for pid, block in raw_lanes.items():
        if not isinstance(block, dict):
            continue
        key = str(pid).strip().lower()
        merged_lanes.setdefault(key, {})
        for field in ("market", "off_hours", "interval_market_minutes", "interval_off_hours_minutes"):
            if field in block and block[field] is not None:
                merged_lanes[key][field] = block[field]
    if merged_lanes:
        settings["pipeline_lanes"] = merged_lanes
    if "pipeline_interval_minutes" not in legacy and "full_cycle_interval_minutes" in legacy:
        settings["pipeline_interval_minutes"] = int(legacy["full_cycle_interval_minutes"])
    day_cfg = raw.get("day_trading", {})
    if isinstance(day_cfg, dict):
        if "enabled" in day_cfg and "day_trading" not in legacy:
            settings["day_trading"] = bool(day_cfg["enabled"])
        if "interval_minutes" in day_cfg:
            settings["day_trading_interval_minutes"] = int(day_cfg["interval_minutes"])
    return settings


def load_worker_state() -> dict[str, Any]:
    with _STATE_LOCK:
        return _read_json(STATE_FILE)


def save_worker_state(state: dict[str, Any]) -> None:
    with _STATE_LOCK:
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(STATE_FILE, state)


def plan_order_signature(plan: StrategyPlan) -> str:
    items = tuple(
        (o.symbol.upper(), o.action.upper(), int(o.quantity))
        for o in plan.orders
        if o.quantity > 0
    )
    return repr(sorted(items))


def _service_mutex_available() -> bool:
    if os.name != "nt":
        return not service_already_running()
    import ctypes

    ERROR_ALREADY_EXISTS = 183
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, SERVICE_MUTEX_NAME)
    if not handle:
        return False
    already = ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS
    ctypes.windll.kernel32.CloseHandle(handle)
    return not already


def acquire_worker_lock(max_age_seconds: int = 7200) -> bool:
    """One-shot worker lock — defers to the long-running service when it is active."""
    del max_age_seconds  # PID-based; age only used for stale lock recovery below.
    if service_already_running():
        _log("Background service already running — skipping one-shot worker cycle.")
        return False
    pid = _read_service_lock_pid()
    if _pid_is_running(pid) and pid != os.getpid():
        _log(f"Worker already running (pid {pid}) — skipping this run.")
        return False
    OUTPUT.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    return True


def release_worker_lock() -> None:
    try:
        if LOCK_FILE.exists() and _read_service_lock_pid() == os.getpid():
            LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _pid_is_running(pid: int) -> bool:
    """True if pid is a live process. Never shell out to tasklist (console flash)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        # Prefer shared helper (OpenProcess — no console window).
        try:
            from process_guard import pid_is_python

            return bool(pid_is_python(pid))
        except Exception:
            pass
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
            )
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_service_lock_pid() -> int:
    if not LOCK_FILE.exists():
        return 0
    try:
        parts = LOCK_FILE.read_text(encoding="utf-8").strip().split()
        if not parts:
            return 0
        return int(parts[0])
    except (OSError, ValueError, IndexError):
        return 0


def _clear_stale_worker_lock() -> None:
    """Remove lock file left behind when a prior worker process died."""
    pid = _read_service_lock_pid()
    if pid > 0 and _pid_is_running(pid):
        return
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def service_already_running() -> bool:
    """True when another headless worker service process holds the lock."""
    _clear_stale_worker_lock()
    return _pid_is_running(_read_service_lock_pid())


def acquire_service_lock() -> bool:
    global _service_mutex_handle
    _clear_stale_worker_lock()
    if os.name == "nt":
        import ctypes

        ERROR_ALREADY_EXISTS = 183
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, SERVICE_MUTEX_NAME)
        if not handle:
            return False
        if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            ctypes.windll.kernel32.CloseHandle(handle)
            live_pid = _read_service_lock_pid()
            if _pid_is_running(live_pid):
                return False
            _clear_stale_worker_lock()
            handle = ctypes.windll.kernel32.CreateMutexW(None, False, SERVICE_MUTEX_NAME)
            if not handle or ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                return False
        _service_mutex_handle = int(handle)
    pid = _read_service_lock_pid()
    if _pid_is_running(pid) and pid != os.getpid():
        return False
    OUTPUT.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    return True


def release_service_lock() -> None:
    global _service_mutex_handle
    release_worker_lock()
    if os.name == "nt" and _service_mutex_handle:
        import ctypes

        ctypes.windll.kernel32.CloseHandle(_service_mutex_handle)
        _service_mutex_handle = None


def _touch_service_lock() -> None:
    if LOCK_FILE.exists() and _read_service_lock_pid() == os.getpid():
        try:
            LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
        except OSError:
            pass


def _parse_log_stamp(line: str) -> float | None:
    if not line.startswith("["):
        return None
    end = line.find("]")
    if end <= 1:
        return None
    stamp = line[1:end]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%H:%M:%S"):
        try:
            dt = datetime.strptime(stamp, fmt)
            if fmt == "%H:%M:%S":
                now = datetime.now()
                dt = dt.replace(year=now.year, month=now.month, day=now.day)
            return dt.timestamp()
        except ValueError:
            continue
    return None


def worker_pipeline_status(*, stuck_after_sec: int = 600) -> dict[str, Any]:
    """Infer whether the headless worker pipeline is running, stuck, or idle.

    Auto-heals orphaned pipeline_active when the worker process is dead so the
    GUI does not show stuck for hours after a crash.
    """
    state = load_worker_state()
    lines: list[str] = []
    log_mtime = 0.0
    if LOG_FILE.exists():
        try:
            lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
            log_mtime = LOG_FILE.stat().st_mtime
        except OSError:
            pass

    # Auto-clear: worker lock/heartbeat dead but UI flag still set.
    if state.get("pipeline_active"):
        lock_pid = _read_service_lock_pid()
        lock_dead = not (lock_pid and _pid_is_running(lock_pid))
        hb_age = 9_999.0
        try:
            hb = OUTPUT / "etrade_worker_heartbeat.txt"
            if hb.exists():
                parts = hb.read_text(encoding="utf-8").strip().splitlines()
                if len(parts) >= 2:
                    hb_age = time.time() - float(parts[1])
        except Exception:
            pass
        progress_at = float(state.get("pipeline_progress_at") or 0)
        progress_age = (time.time() - progress_at) if progress_at else 9_999.0
        if lock_dead or hb_age > 120 or progress_age > max(stuck_after_sec, 180):
            if lock_dead or hb_age > 90:
                state.pop("pipeline_active", None)
                state.pop("pipeline_progress", None)
                state.pop("pipeline_progress_at", None)
                try:
                    save_worker_state(state)
                except Exception:
                    pass
                state = load_worker_state()

    tail = lines[-200:]
    complete_idx: int | None = None
    start_idx: int | None = None
    last_agent_line = ""
    for index in range(len(tail) - 1, -1, -1):
        line = tail[index]
        if complete_idx is None and "Pipeline complete" in line:
            complete_idx = index
        if start_idx is None and "Running Finance agent pipeline" in line:
            start_idx = index
        if not last_agent_line and "Agent " in line and "/" in line and ": " in line:
            last_agent_line = line

    progress = ""
    if last_agent_line:
        progress = last_agent_line.split("] ", 1)[-1] if "] " in last_agent_line else last_agent_line

    active = False
    if start_idx is not None and (complete_idx is None or start_idx > complete_idx):
        active = True

    if state.get("pipeline_active"):
        active = True
        progress = str(state.get("pipeline_progress") or progress)

    log_age = (time.time() - log_mtime) if log_mtime else None
    progress_at = float(state.get("pipeline_progress_at") or 0)
    progress_age = (time.time() - progress_at) if progress_at else None
    stale_for = max(
        log_age or 0.0,
        progress_age or 0.0,
    )
    stuck = bool(active and stale_for >= stuck_after_sec)
    if stuck:
        active = False

    return {
        "active": active,
        "stuck": stuck,
        "progress": progress,
        "log_age_sec": log_age,
        "progress_age_sec": progress_age,
    }


def _interval_due(last_at: Any, interval_minutes: int, *, force: bool = False) -> bool:
    if force:
        return True
    if not last_at:
        return True
    interval = max(1, int(interval_minutes)) * 60
    return (time.time() - float(last_at)) >= interval


def is_pre_open_research_window(now: datetime | None = None) -> bool:
    """Mon–Fri 06:30–09:30 America/New_York — warm pipeline before the open.

    Controlled by background_worker.pre_open_research_enabled (default True).
    """
    settings = worker_settings()
    if not bool(settings.get("pre_open_research_enabled", True)):
        return False
    et = ZoneInfo("America/New_York")
    now = now or datetime.now(et)
    if now.tzinfo is None:
        now = now.replace(tzinfo=et)
    else:
        now = now.astimezone(et)
    if now.weekday() >= 5:
        return False
    start = now.replace(hour=6, minute=30, second=0, microsecond=0)
    end = now.replace(hour=9, minute=30, second=0, microsecond=0)
    return start <= now < end


def is_us_market_open(now: datetime | None = None) -> bool:
    """US equity regular session (Mon-Fri 9:30-16:00 Eastern)."""
    now = now or datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    return dt_time(9, 30) <= now.time() <= dt_time(16, 0)


def live_trading_enabled(settings: dict[str, Any], *, sandbox: bool) -> bool:
    if not settings.get("auto_execute", True):
        return False
    if not settings.get("live_trading", True):
        return False
    if settings.get("dry_run", False):
        return False
    if sandbox and not settings.get("live_trading_sandbox", False):
        return False
    return True


def day_trading_enabled(settings: dict[str, Any], day_settings: dict[str, Any] | None = None) -> bool:
    """Day trading runs on its own schedule — not tied to swing auto-execute."""
    if not settings.get("day_trading", True):
        return False
    if day_settings is not None and not day_settings.get("enabled", True):
        return False
    return True


def day_trading_can_execute(settings: dict[str, Any], *, sandbox: bool) -> bool:
    """True when day orders may be submitted (live or dry-run simulation)."""
    if settings.get("dry_run", False):
        return True
    if sandbox and not settings.get("live_trading_sandbox", settings.get("live_trading", True)):
        return False
    return True


def _execute_due(state: dict[str, Any], settings: dict[str, Any], sig: str) -> bool:
    if not settings.get("auto_execute", True):
        return False
    if sig and sig == state.get("last_executed_plan_sig"):
        return False
    last = state.get("last_execute_at")
    if not last:
        return True
    interval = int(settings.get("execute_min_interval_minutes", 15)) * 60
    return (time.time() - float(last)) >= interval


def _connect_client(config_path: Path = CONFIG_PATH) -> ETradeClient | None:
    try:
        config = load_config(config_path)
    except Exception as exc:
        _log(f"Config error: {exc}")
        return None

    tokens = load_tokens(config.token_path, config.sandbox)
    if not tokens:
        _log("No saved E*TRADE token - connect via the GUI once.")
        return None

    if is_expired_for_day(tokens):
        _log("E*TRADE token expired (past midnight ET). Reconnect in the GUI.")
        return None

    if needs_renewal(tokens):
        try:
            tokens = renew_access_token(config, tokens)
        except Exception as exc:
            _log(f"Token renewal skipped ({exc}); using existing token.")

    try:
        client = ETradeClient(config, tokens)
        client.list_accounts()
        _log(f"Connected to E*TRADE ({'sandbox' if config.sandbox else 'production'}).")
        return client
    except Exception as exc:
        _log(f"E*TRADE connection failed: {exc}")
        return None


def _resolve_account(client: ETradeClient, config_path: Path = CONFIG_PATH) -> dict[str, Any] | None:
    accounts = client.list_accounts()
    if not accounts:
        return None

    selected = get_selected_account(config_path)
    if not selected:
        _log("No confirmed account saved - open the GUI, pick an account, and confirm.")
        return None

    key = selected["account_id_key"]
    for acct in accounts:
        if acct.get("account_id_key") == key:
            label = acct.get("display_label") or selected.get("display_label") or acct.get("account_name") or key
            _log(f"Using saved account: {label}")
            return acct

    _log(f"Saved account {key} not found at E*TRADE - confirm an account in the GUI.")
    return None


def _pipeline_benchmark_settings(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    try:
        from historical_simulation import pipeline_benchmark_config

        return pipeline_benchmark_config()
    except Exception:
        return {"enabled": True, "run_during_market_hours": False}


def _daily_calibration_due(
    state: dict[str, Any],
    *,
    config_path: Path = CONFIG_PATH,
    now: datetime | None = None,
) -> bool:
    settings = _pipeline_benchmark_settings(config_path)
    daily = settings.get("daily_calibration") if isinstance(settings.get("daily_calibration"), dict) else {}
    if not daily.get("enabled", True):
        return False
    tz = ZoneInfo(str(daily.get("timezone") or "America/New_York"))
    now = now or datetime.now(tz)
    target_hour = int(daily.get("hour", 6) or 6)
    target_minute = int(daily.get("minute", 0) or 0)
    today = now.date().isoformat()
    if state.get("last_daily_calibration_date") == today:
        return False
    target = dt_time(target_hour, target_minute)
    return now.time() >= target


def _pipeline_benchmark_profile(
    *,
    config_path: Path = CONFIG_PATH,
    state: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> str:
    state = state or load_worker_state()
    if _daily_calibration_due(state, config_path=config_path, now=now):
        return "daily"
    settings = _pipeline_benchmark_settings(config_path)
    if not settings.get("enabled", True):
        return "skip"
    if is_us_market_open(now):
        if not settings.get("run_during_market_hours", False):
            return "skip"
        return "routine"
    return "off_hours"


def _run_live_scoring(*, force: bool = False, config_path: Path = CONFIG_PATH) -> bool:
    """Score matured predictions between full pipeline runs."""
    settings = worker_settings(config_path)
    market_open = is_us_market_open()
    try:
        from live_accuracy import load_live_accuracy_settings

        live_settings = load_live_accuracy_settings(config_path)
        if market_open:
            interval = int(
                live_settings.get(
                    "accuracy_interval_minutes",
                    settings.get("accuracy_interval_minutes", 15),
                )
            )
        else:
            interval = int(
                live_settings.get(
                    "accuracy_off_hours_interval_minutes",
                    settings.get("accuracy_off_hours_interval_minutes", 30),
                )
            )
    except Exception:
        interval = _effective_accuracy_interval_minutes(settings, market_open=market_open)

    state = load_worker_state()
    if not _interval_due(state.get("last_accuracy_at"), interval, force=force):
        return False

    try:
        from prediction_accuracy import run_live_scoring_cycle

        stats = run_live_scoring_cycle(rebuild_learning=True)
        state["last_accuracy_at"] = time.time()
        state["live_scoring"] = stats
        save_worker_state(state)
        _log(
            "Live scoring — "
            f"{stats.get('scored', 0)} matured, "
            f"{stats.get('pruned', 0)} pruned, "
            f"{stats.get('pending', 0)} pending, "
            f"{stats.get('live_primary_agents', 0)} agents on live weights, "
            f"{stats.get('blended_agents', 0)} blended."
        )
        return True
    except Exception as exc:
        _log(f"Live scoring skipped: {exc}")
        return False


# Full pipeline wall-clock (seconds). Service never blocks longer than this.
# Full cycle hard kill. Stall kill is separate (no stdout for ~100s).
PIPELINE_CYCLE_TIMEOUT_SEC = max(300, int(os.environ.get("FINANCE_PIPELINE_TIMEOUT_SEC", "1200")))
PIPELINE_STALL_SEC = max(60, int(os.environ.get("FINANCE_PIPELINE_STALL_SEC", "100")))


def _pipeline_child_alive() -> bool:
    """True only when an isolated pipeline child from THIS process is still running."""
    for pid in list(_PIPELINE_CHILD_PIDS):
        if pid and _pid_is_running(pid):
            return True
    try:
        from agents.agent_process_runner import LAST_PIPELINE_CHILD_PID

        pid = int(LAST_PIPELINE_CHILD_PID or 0)
        if pid and _pid_is_running(pid):
            return True
    except Exception:
        pass
    return False


def _agent_report_marker_age_sec() -> float:
    """Age of the *oldest* core agent marker (seconds). Missing file → huge.

    Uses oldest so a fresh critical report does not hide a multi-day-old markets.json.
    """
    markers = (
        "risk_guardrail.json",
        "day_trading_microstructure.json",
        "order_execution.json",
        "markets.json",
        "options_flow.json",
    )
    oldest_mtime = None
    for name in markers:
        path = OUTPUT / name
        try:
            if not path.is_file():
                return 9_999_999.0
            mt = float(path.stat().st_mtime)
            oldest_mtime = mt if oldest_mtime is None else min(oldest_mtime, mt)
        except OSError:
            return 9_999_999.0
    if oldest_mtime is None:
        return 9_999_999.0
    return max(0.0, time.time() - oldest_mtime)


def _agent_reports_stale(*, max_age_sec: float = 6 * 3600) -> bool:
    """True when any core agent output is older than max_age (or missing)."""
    return _agent_report_marker_age_sec() >= float(max_age_sec)


def _run_pipeline(
    *,
    force: bool = False,
    config_path: Path = CONFIG_PATH,
    only_lanes: list[str] | None = None,
) -> bool:
    """Run agents in an isolated child process so the service loop cannot freeze."""
    # Aggressive stale clear — orphaned flags were blocking new cycles forever.
    _clear_stale_pipeline_state(max_progress_age_sec=90)
    state = load_worker_state()
    settings = worker_settings(config_path)
    if state.get("pipeline_active"):
        progress_at = float(state.get("pipeline_progress_at") or 0)
        age = (time.time() - progress_at) if progress_at else 9_999.0
        # Only skip when THIS process actually has a live pipeline child.
        # Holding the service lock alone is not enough (prior child can die and
        # leave pipeline_active true with a recent progress timestamp).
        if _pipeline_child_alive() and age < max(PIPELINE_STALL_SEC + 30, 150):
            _log(f"Pipeline already in progress: {state.get('pipeline_progress') or '…'}")
            return False
        _log(
            f"Clearing orphaned pipeline flag "
            f"({state.get('pipeline_progress') or '…'}, age {age:.0f}s, no live child)"
        )
        state.pop("pipeline_active", None)
        state.pop("pipeline_progress", None)
        state.pop("pipeline_progress_at", None)
        save_worker_state(state)

    calibration_due = _daily_calibration_due(state, config_path=config_path)
    market_open = is_us_market_open()
    pre_open = is_pre_open_research_window()
    research_session = bool(market_open or pre_open)
    off_hours_ok = _pipeline_runs_off_hours(settings)
    try:
        from agent_pipelines import is_eco_session

        eco_mode = is_eco_session(
            settings, market_open=market_open, pre_open=pre_open
        )
    except Exception:
        eco_mode = (not research_session) and bool(
            settings.get("pipeline_eco_mode_off_hours", True)
        )
    # When pipeline_market_hours_only is on and eco is off, never run agent lanes
    # overnight — except pre-open warm window (06:30–09:30 ET) and true RTH.
    # Eco mode (default) still runs a sparse off-hours roster.
    if not force and not research_session and not off_hours_ok:
        if calibration_due:
            _log(
                "Daily calibration deferred — outside RTH/pre-open "
                "(pipeline_market_hours_only); will run in pre-open or after open."
            )
        else:
            _log("Pipeline skipped - US market closed (off-hours pipeline disabled).")
        return False

    session = "market" if market_open else ("pre_open" if pre_open else "off_hours")
    if eco_mode:
        session = "off_hours_eco"
    # Per-lane due: market_open flag true for RTH *or* pre-open uses market-ish cadence
    # except pure eco off-hours uses eco intervals.
    due_lanes = _lanes_due(
        state,
        settings,
        market_open=bool(research_session and not eco_mode),
        force=force or (calibration_due and research_session),
        eco_mode=eco_mode,
    )
    if only_lanes is not None:
        wanted = {str(x).strip().lower() for x in only_lanes}
        due_lanes = [p for p in due_lanes if p in wanted]
    # Research is SEC/Yahoo-heavy; runs in the isolated pipeline child so a
    # crash cannot kill the service. Default ON. Disable with FINANCE_RUN_RESEARCH=0.
    run_research = str(os.environ.get("FINANCE_RUN_RESEARCH", "1")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    if not run_research and "research" in due_lanes:
        due_lanes = [x for x in due_lanes if x != "research"]
        _log("Skipping research lane (FINANCE_RUN_RESEARCH=0).")
    # If research is due with other lanes, prefer research-only this cycle so
    # the 20 slow agents get a full timeout budget without blocking critical.
    elif (
        run_research
        and "research" in due_lanes
        and len(due_lanes) > 1
        and str(os.environ.get("FINANCE_RESEARCH_DEDICATED", "1")).strip().lower()
        not in {"0", "false", "no", "off"}
    ):
        # Alternate: if research is the stalest lane, run it alone.
        lane_times = state.get("last_pipeline_lane_at")
        if not isinstance(lane_times, dict):
            lane_times = {}
        research_last = float(lane_times.get("research") or 0)
        others_last = max(
            (float(lane_times.get(p) or 0) for p in due_lanes if p != "research"),
            default=0.0,
        )
        # Research never run, or much older than peers → dedicated cycle
        if research_last <= 0 or (others_last > 0 and research_last < others_last - 1800):
            _log(
                "Research-dedicated cycle "
                f"(research last={research_last:.0f}, peers fresher) — "
                "deferring other due lanes one cycle."
            )
            due_lanes = ["research"]
    if not due_lanes:
        _log("Pipeline skipped - no lanes due yet (per-lane schedule).")
        return False

    # Off-hours / routine: never run multi-hour walk-forward inside the schedule.
    benchmark_profile = "skip"
    lane_open_flag = bool(research_session and not eco_mode)
    if calibration_due:
        _log("Daily calibration due - running due lanes without long backtest.")
    else:
        mode_tag = " ECO" if eco_mode else ""
        _log(
            f"{session} cycle{mode_tag} - lanes due: {', '.join(due_lanes)} "
            f"(critical={_lane_iv(settings, 'critical', lane_open_flag)}m "
            f"quant={_lane_iv(settings, 'quant', lane_open_flag)}m "
            f"flow={_lane_iv(settings, 'flow', lane_open_flag)}m "
            f"research={_lane_iv(settings, 'research', lane_open_flag)}m)"
        )

    use_split = str(os.environ.get("FINANCE_SPLIT_PIPELINES", "1")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    state["pipeline_active"] = True
    state["pipeline_progress"] = f"Starting lanes: {', '.join(due_lanes)}"
    state["pipeline_progress_at"] = time.time()
    # Load night walk-forward learning brief for RTH (agents/fusion consume via learning files).
    if market_open:
        try:
            from agent_learning import load_next_session_brief, write_next_session_brief

            brief = load_next_session_brief()
            if not brief.get("updated_at"):
                brief = write_next_session_brief()
            state["next_session_brief_at"] = brief.get("updated_at")
            state["learning_boost_agents"] = list(brief.get("boost_agents") or [])[:12]
            state["learning_cut_agents"] = list(brief.get("cut_agents") or [])[:12]
            _log(
                "Loaded next_session_brief — "
                f"boost={','.join(state['learning_boost_agents'][:5]) or '—'} "
                f"cut={','.join(state['learning_cut_agents'][:5]) or '—'}"
            )
        except Exception as exc:
            _log(f"next_session_brief load note: {exc}")
    save_worker_state(state)

    ok = 0
    ran_lanes = list(due_lanes)
    # Outer pipeline child: if this process tree dies, the *service* loop lives on
    # and clears flags. Previously in-process runs killed the whole worker.
    pipeline_timeout = max(300, int(os.environ.get("FINANCE_PIPELINE_TIMEOUT_SEC", "1500")))
    # Stall must exceed Market Predictor / enhance timeouts (else post-fusion is
    # killed mid-"Fusing Market Predictor" with no progress lines).
    pipeline_stall = max(150, int(os.environ.get("FINANCE_PIPELINE_STALL_SEC", "200")))
    if eco_mode:
        try:
            from agent_pipelines import ECO_PIPELINE_STALL_SEC, ECO_PIPELINE_TIMEOUT_SEC

            pipeline_timeout = min(pipeline_timeout, int(ECO_PIPELINE_TIMEOUT_SEC))
            pipeline_stall = min(pipeline_stall, int(ECO_PIPELINE_STALL_SEC))
        except Exception:
            pipeline_timeout = min(pipeline_timeout, 600)
            pipeline_stall = min(pipeline_stall, 120)
        os.environ["FINANCE_PIPELINE_ECO"] = "1"
        _log(
            f"Eco mode: reduced agents/lanes, timeout {pipeline_timeout}s, "
            f"stall {pipeline_stall}s, FINANCE_PIPELINE_ECO=1"
        )
    else:
        os.environ.pop("FINANCE_PIPELINE_ECO", None)
    try:
        from agents.agent_process_runner import run_pipeline_subprocess

        def _on_progress(line: str) -> None:
            text = (line or "").strip()
            if not text:
                return
            _log(text)
            if (
                text.startswith("Agent ")
                or text.startswith("[")
                or text.startswith(">")
                or text.startswith("Pipeline ")
                or text.startswith("Lane ")
                or text.startswith("Split ")
                or text.startswith("E*TRADE")
                or text.startswith("Skipping ")
                or text.startswith("Fusing ")
                or "PIPELINE_OK" in text
                or "timed out" in text.lower()
                or "enhancement" in text.lower()
            ):
                live = load_worker_state()
                live["pipeline_active"] = True
                live["pipeline_progress"] = text[:200]
                live["pipeline_progress_at"] = time.time()
                save_worker_state(live)

        _log(
            f"Launching isolated pipeline child "
            f"(timeout {pipeline_timeout}s, stall {pipeline_stall}s, lanes={','.join(due_lanes)})"
        )
        result = run_pipeline_subprocess(
            root=ROOT,
            timeout_sec=pipeline_timeout,
            stall_sec=pipeline_stall,
            benchmark_profile=benchmark_profile,
            on_line=_on_progress,
            split_pipelines=use_split,
            only_lanes=due_lanes if use_split else None,
            parallel_lanes=False,
            agent_subprocess=True,
        )
        if result.get("timed_out"):
            _log(
                f"Pipeline child timed out/stalled — "
                f"{result.get('error') or 'killed'}; service continues"
            )
        elif not result.get("ok"):
            _log(f"Pipeline child failed: {result.get('error') or 'unknown'}")
        # Count PIPELINE_OK from stdout if present
        for line in reversed((result.get("stdout") or "").splitlines()):
            if line.startswith("PIPELINE_OK"):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        ok = int(parts[1])
                    except ValueError:
                        ok = 1 if result.get("ok") else 0
                break
        else:
            ok = 1 if result.get("ok") else 0
        if not use_split:
            ran_lanes = ["critical", "quant", "flow", "research"]
        _log(f"Pipeline finished - {ok} agent reports updated (lanes={','.join(ran_lanes)}).")
    except Exception as exc:
        _log(f"Pipeline error: {exc}")
        _log(traceback.format_exc())
    finally:
        # Always clear active flags — a hang after lanes (e.g. Market Predictor)
        # used to leave the UI stuck for hours after the process died.
        try:
            state = load_worker_state()
            state.pop("pipeline_active", None)
            state.pop("pipeline_progress", None)
            state.pop("pipeline_progress_at", None)
            now_ts = time.time()
            state["last_pipeline_at"] = now_ts
            lane_times = state.get("last_pipeline_lane_at")
            if not isinstance(lane_times, dict):
                lane_times = {}
            for pid in ran_lanes:
                lane_times[pid] = now_ts
            state["last_pipeline_lane_at"] = lane_times
            if calibration_due:
                tz = ZoneInfo(
                    str(
                        (_pipeline_benchmark_settings(config_path).get("daily_calibration") or {}).get(
                            "timezone"
                        )
                        or "America/New_York"
                    )
                )
                state["last_daily_calibration_date"] = datetime.now(tz).date().isoformat()
            state["last_benchmark_profile"] = benchmark_profile
            save_worker_state(state)
        except Exception as exc:
            _log(f"Pipeline cleanup note: {exc}")

    _log(f"Pipeline complete - {ok} agent reports updated.")
    return True


def _lane_iv(settings: dict[str, Any], pid: str, market_open: bool) -> int:
    try:
        from agent_pipelines import lane_interval_minutes

        return lane_interval_minutes(pid, market_open=market_open, settings=settings)
    except Exception:
        return 15


def _submit_plan_orders(
    client: ETradeClient,
    plan: StrategyPlan,
    settings: dict[str, Any],
    state: dict[str, Any],
    *,
    force: bool = False,
) -> bool:
    sig = plan_order_signature(plan)
    if not plan.orders:
        _log("Strategy plan has no orders.")
        return False
    if not force and not _execute_due(state, settings, sig):
        _log("Live trading not due yet or plan unchanged since last execution.")
        return False
    if not live_trading_enabled(settings, sandbox=client.config.sandbox):
        _log("Live trading disabled (dry run, sandbox, or auto_execute off).")
        return False
    if not is_us_market_open() and not settings.get("allow_off_hours_trading", False):
        _log("US market closed - live trading task will retry during market hours.")
        return False

    mode = "LIVE PRODUCTION" if not client.config.sandbox else "LIVE SANDBOX"
    dry_run = bool(settings.get("dry_run", False))
    proposed = len(plan.orders)
    _log(f"=== {mode} TRADING TASK: {proposed} orders ===")
    preview_orders(client, plan)
    blocked = sum(1 for o in plan.orders if o.status == "blocked")
    if blocked:
        guards = (plan.meta or {}).get("trade_guards", {})
        bp = guards.get("available_usd")
        pdt = guards.get("day_trades_5d")
        extra = []
        if bp is not None:
            extra.append(f"${bp:,.2f} buying power available")
        if pdt is not None and guards.get("pdt_applies"):
            extra.append(f"{pdt}/{guards.get('max_day_trades_5d', 3)} day trades in 5d")
        suffix = f" ({'; '.join(extra)})" if extra else ""
        _log(f"Trade guards blocked {blocked}/{proposed} order(s) before E*TRADE preview{suffix}.")
    previewed = sum(1 for o in plan.orders if o.status == "previewed")
    if previewed == 0:
        _log("No orders passed E*TRADE preview.")
        return False

    execute_orders(client, plan, dry_run=dry_run)
    save_strategy_plan(plan)
    placed = sum(1 for o in plan.orders if o.status in {"placed", "dry_run"})
    state["last_executed_plan_sig"] = sig
    state["last_execute_at"] = time.time()
    if dry_run:
        _log(f"Dry run complete - simulated {placed} orders.")
    else:
        _log(f"LIVE orders submitted to E*TRADE: {placed}")
    return True


def _run_plan_build(client: ETradeClient, *, force: bool = False, config_path: Path = CONFIG_PATH) -> StrategyPlan | None:
    state = load_worker_state()
    settings = worker_settings(config_path)
    if not _interval_due(state.get("last_plan_at"), settings["plan_interval_minutes"], force=force):
        _log("Plan skipped - not due yet.")
        return None

    acct = _resolve_account(client, config_path)
    if not acct:
        return None

    _log(
        f"Building strategy plan for "
        f"{acct.get('display_label') or acct.get('account_name') or acct.get('account_id')}..."
    )
    from portfolio_generator import generate_portfolio, save_portfolio
    from strategy_engine import PORTFOLIO_FILE

    balance = client.get_balance(acct["account_id_key"])
    notional = balance.get("total_account_value") or None
    try:
        portfolio = generate_portfolio(OUTPUT, notional_usd=notional)
    except ValueError as exc:
        _log(f"Strategy plan skipped — {exc}")
        return None
    save_portfolio(portfolio, PORTFOLIO_FILE)
    plan = build_strategy_plan(
        client,
        acct["account_id_key"],
        acct.get("account_name", ""),
        portfolio=portfolio,
    )
    save_strategy_plan(plan)
    state["last_plan_at"] = time.time()
    save_worker_state(state)
    _log(f"Strategy plan ready - {len(plan.orders)} proposed orders.")
    return plan


def _run_day_trading(
    client: ETradeClient,
    *,
    force: bool = False,
    config_path: Path = CONFIG_PATH,
) -> bool:
    from day_trader import (
        apply_day_trade_executions,
        build_day_trade_plan,
        is_day_trading_session,
        load_day_state,
        load_day_trade_settings,
        minutes_to_market_close,
    )

    state = load_worker_state()
    settings = worker_settings(config_path)
    day_settings = load_day_trade_settings(config_path)

    if not day_trading_enabled(settings, day_settings):
        return False
    if not day_trading_can_execute(settings, sandbox=client.config.sandbox):
        _log("Day trading disabled for this environment (sandbox live off).")
        return False

    interval = int(settings.get("day_trading_interval_minutes", day_settings.get("interval_minutes", 5)))
    if not _interval_due(state.get("last_day_trade_at"), interval, force=force):
        return False

    minutes_left = minutes_to_market_close()
    if minutes_left is None or (minutes_left <= 0 and not is_day_trading_session()):
        if not force:
            return False

    acct = _resolve_account(client, config_path)
    if not acct:
        return False

    day_state = load_day_state()
    _log(
        f"Day trading scan — {len(day_state.get('positions', []))} open intraday position(s)…"
    )
    plan = build_day_trade_plan(
        client,
        acct["account_id_key"],
        acct.get("account_name", ""),
        settings=day_settings,
        state=day_state,
    )
    if not plan.orders:
        state["last_day_trade_at"] = time.time()
        save_worker_state(state)
        _log("Day trading: no intraday orders this cycle.")
        return False

    if not is_us_market_open() and not settings.get("allow_off_hours_trading", False):
        _log("US market closed — day trading orders deferred.")
        return False

    mode = "LIVE PRODUCTION" if not client.config.sandbox else "LIVE SANDBOX"
    dry_run = bool(settings.get("dry_run", False))
    proposed = len(plan.orders)
    _log(f"=== DAY TRADE {mode}: {proposed} orders ===")
    preview_orders(client, plan)
    blocked = sum(1 for o in plan.orders if o.status == "blocked")
    if blocked:
        guards = (plan.meta or {}).get("trade_guards", {})
        bp = guards.get("available_usd")
        pdt = guards.get("day_trades_5d")
        extra = []
        if bp is not None:
            extra.append(f"${bp:,.2f} buying power available")
        if pdt is not None and guards.get("pdt_applies"):
            extra.append(f"{pdt}/{guards.get('max_day_trades_5d', 3)} day trades in 5d")
        suffix = f" ({'; '.join(extra)})" if extra else ""
        _log(f"Day trade guards blocked {blocked}/{proposed} order(s) before E*TRADE preview{suffix}.")
    previewed = sum(1 for o in plan.orders if o.status == "previewed")
    if previewed == 0:
        _log("Day trading: no orders passed E*TRADE preview.")
        state["last_day_trade_at"] = time.time()
        save_worker_state(state)
        return False

    execute_orders(client, plan, dry_run=dry_run)
    apply_day_trade_executions(plan, state=day_state, settings=day_settings)
    placed = sum(1 for o in plan.orders if o.status in {"placed", "dry_run"})
    state["last_day_trade_at"] = time.time()
    save_worker_state(state)
    if dry_run:
        _log(f"Day trading dry run — simulated {placed} order(s).")
    else:
        _log(f"Day trading LIVE — submitted {placed} order(s).")
    return True


def _run_live_execute(
    client: ETradeClient,
    *,
    force: bool = False,
    config_path: Path = CONFIG_PATH,
) -> bool:
    from strategy_engine import load_strategy_plan, plan_from_dict

    state = load_worker_state()
    settings = worker_settings(config_path)
    data = load_strategy_plan(PLAN_FILE)
    if not data:
        _log("No saved strategy plan - run plan task first.")
        return False
    plan = plan_from_dict(data)
    executed = _submit_plan_orders(client, plan, settings, state, force=force)
    save_worker_state(state)
    return executed


def _run_plan_and_orders(client: ETradeClient, *, force: bool = False, config_path: Path = CONFIG_PATH) -> bool:
    plan = _run_plan_build(client, force=force, config_path=config_path)
    if plan and plan.orders:
        state = load_worker_state()
        settings = worker_settings(config_path)
        _submit_plan_orders(client, plan, settings, state, force=force)
        save_worker_state(state)
        return True
    if plan:
        _log("No trades needed - portfolio already aligned.")
        return True
    return _run_live_execute(client, force=force, config_path=config_path)


def _deployment_role(config_path: Path = CONFIG_PATH) -> str:
    try:
        from deployment import role as deploy_role

        return str(deploy_role(config_path))
    except Exception:
        return "all"


def _sync_shared(config_path: Path = CONFIG_PATH, *, phase: str = "") -> None:
    """Best-effort dual-PC SMB sync; never raises into the service loop."""
    try:
        from deployment import load_deployment
        from sync_shared_data import sync_for_role

        dep = load_deployment(config_path)
        r = str(dep.get("role") or "all")
        if r == "all" and not str(dep.get("shared_root") or "").strip():
            return
        result = sync_for_role(r, config_path=config_path)
        copied = 0
        for key, val in result.items():
            if isinstance(val, dict):
                copied += int(val.get("copied") or 0)
        if phase:
            _log(f"Shared sync ({phase}): role={r} files_touched≈{copied}")
    except Exception as exc:
        _log(f"Shared sync note: {exc}")


def _publish_broker_market_data(
    client: ETradeClient,
    *,
    config_path: Path = CONFIG_PATH,
) -> None:
    """Fetch live quotes + account snapshot; push to SMB for the pipeline host."""
    try:
        from deployment import load_deployment

        dep = load_deployment(config_path)
        if not dep.get("publish_quotes", True):
            return
        if _deployment_role(config_path) == "pipeline":
            return
    except Exception:
        dep = {}

    try:
        from etrade_market_enhancer import (
            enhancement_settings,
            fetch_etrade_quotes,
            _load_quotes_payload,
            _merge_quote_maps,
            _write_quotes_payload,
        )
        from agents.enhancement import (
            ENHANCED_QUOTES_FILE,
            collect_enhancement_candidates,
            collect_proactive_enhancement_candidates,
            select_symbols,
        )
    except Exception as exc:
        _log(f"Quote publish import note: {exc}")
        return

    settings = enhancement_settings(config_path)
    if not settings.get("enabled", True):
        return

    out = OUTPUT
    out.mkdir(parents=True, exist_ok=True)
    candidates = collect_enhancement_candidates(out, include_proactive=True)
    if not candidates:
        candidates = collect_proactive_enhancement_candidates(out)
    symbols = select_symbols(
        candidates,
        max_symbols=int(settings.get("max_symbols", 50)),
        min_priority=float(settings.get("min_priority", 0.4)),
    )
    quotes: dict[str, Any] = {}
    if symbols and not (settings.get("require_production", True) and client.config.sandbox):
        try:
            quotes = fetch_etrade_quotes(
                client,
                symbols,
                detail_flag=str(settings.get("detail_flag", "ALL")),
            )
        except Exception as exc:
            _log(f"Quote fetch note: {exc}")
        if quotes:
            quotes_path = out / ENHANCED_QUOTES_FILE
            prior = (
                _load_quotes_payload(quotes_path)
                if settings.get("merge_existing_quotes", True)
                else {}
            )
            merged = _merge_quote_maps(
                prior.get("quotes") if isinstance(prior.get("quotes"), dict) else {},
                quotes,
            )
            _write_quotes_payload(
                out,
                quotes=merged,
                requested=symbols,
                candidates=candidates if isinstance(candidates, list) else [],
                phase="broker_publish",
                prior=prior,
            )
            _log(f"Published {len(quotes)} live quote(s) for pipeline share.")

    # Account snapshot so pipeline / UI peers can size without broker secrets
    try:
        acct = _resolve_account(client, config_path)
        if acct:
            key = acct["account_id_key"]
            balance = client.get_balance(key) or {}
            positions = client.get_portfolio(key) or []
            snap = {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "account_id_key": key,
                "display_label": acct.get("display_label") or acct.get("account_name"),
                "balance": {
                    "total_account_value": balance.get("total_account_value"),
                    "cash_buying_power": balance.get("cash_buying_power")
                    or balance.get("buying_power"),
                    "cash": balance.get("cash"),
                },
                "positions": positions if isinstance(positions, list) else [],
                "sandbox": bool(client.config.sandbox),
            }
            (out / "account_snapshot.json").write_text(
                json.dumps(snap, indent=2, default=str), encoding="utf-8"
            )
            # Always snapshot equity+cash into history so future deposits are
            # detected and excluded from profit/goals (never counted as gains).
            try:
                total_v = float(
                    balance.get("total_account_value")
                    or balance.get("NetAccountValue")
                    or 0
                )
            except (TypeError, ValueError):
                total_v = 0.0
            cash_v = (
                balance.get("cash_buying_power")
                or balance.get("buying_power")
                or balance.get("cash")
                or balance.get("cash_available_for_investment")
            )
            try:
                cash_f = float(cash_v) if cash_v is not None else None
            except (TypeError, ValueError):
                cash_f = None
            if total_v > 0:
                try:
                    from analysis_history import record_account_value

                    record_account_value(
                        total_v,
                        account_id_key=str(key or ""),
                        cash_buying_power=cash_f,
                        source="broker_snapshot",
                    )
                except Exception as rec_exc:
                    _log(f"Account history note: {rec_exc}")
    except Exception as exc:
        _log(f"Account snapshot note: {exc}")

    try:
        from sync_shared_data import push_broker_feed

        push_broker_feed(config_path=config_path)
    except Exception as exc:
        _log(f"Broker feed push note: {exc}")


def run_full_cycle(*, force: bool = False, config_path: Path = CONFIG_PATH) -> int:
    role = _deployment_role(config_path)
    trading_paused = automation_paused(config_path)
    # Dual-PC: pause stops trading only. Pipeline host keeps researching.
    if trading_paused and role == "broker":
        _log("Trading paused — broker cycle will sync + quotes only (no orders).")
    if not acquire_worker_lock():
        return 0

    exit_code = 0
    try:
        _log(f"=== E*TRADE background worker started (role={role}) ===")
        _sync_shared(config_path, phase="pre")

        pipeline_ran = False
        if role in {"pipeline", "all"}:
            pipeline_ran = _run_pipeline(force=force, config_path=config_path)
            if role == "pipeline":
                try:
                    from sync_shared_data import push_pipeline_artifacts

                    push_pipeline_artifacts(config_path=config_path)
                except Exception as exc:
                    _log(f"Pipeline push note: {exc}")

        plan_ran = False
        client = None
        if role in {"broker", "all"}:
            client = _connect_client(config_path)
            if client:
                try:
                    _publish_broker_market_data(client, config_path=config_path)
                except Exception as exc:
                    _log(f"Broker market data note: {exc}")
                if not trading_paused:
                    plan_ran = _run_plan_and_orders(client, force=force, config_path=config_path)
                    _run_day_trading(client, force=force, config_path=config_path)
                else:
                    _log("Skipping plan/orders — trading paused.")
            else:
                _log("Skipping plan/orders - not connected to E*TRADE.")
        else:
            _log("Pipeline role — skipping E*TRADE plan/orders on this host.")

        _sync_shared(config_path, phase="post")
        if not pipeline_ran and not plan_ran and client:
            _log("Nothing due this cycle.")
        _log("=== Worker cycle finished ===")
    except Exception as exc:
        exit_code = 1
        _log(f"Worker failed: {exc}")
        _log(traceback.format_exc())
    finally:
        release_worker_lock()

    return exit_code


def run_day_trading_for_client(
    client: ETradeClient,
    *,
    force: bool = False,
    config_path: Path = CONFIG_PATH,
) -> bool:
    """Run one day-trading cycle using an existing connected client (GUI or service)."""
    return _run_day_trading(client, force=force, config_path=config_path)


def run_day_trading_cycle(*, force: bool = False, config_path: Path = CONFIG_PATH) -> int:
    if _deployment_role(config_path) == "pipeline":
        _log("Pipeline role — day trading not run on this host.")
        return 0
    if automation_paused(config_path):
        _log("Trading paused — day trading skipped.")
        return 0
    if not acquire_worker_lock(max_age_seconds=900):
        return 0

    exit_code = 0
    try:
        _log("=== Day trading task started ===")
        _sync_shared(config_path, phase="pre-day")
        client = _connect_client(config_path)
        if not client:
            return 1
        _run_day_trading(client, force=force, config_path=config_path)
        _log("=== Day trading task finished ===")
    except Exception as exc:
        exit_code = 1
        _log(f"Day trading task failed: {exc}")
        _log(traceback.format_exc())
    finally:
        release_worker_lock()
    return exit_code


def run_live_trading_cycle(*, force: bool = False, config_path: Path = CONFIG_PATH) -> int:
    """Scheduled task entry: submit live orders from the saved strategy plan."""
    if _deployment_role(config_path) == "pipeline":
        _log("Pipeline role — live trading not run on this host.")
        return 0
    if automation_paused(config_path):
        _log("Trading paused — live trading skipped.")
        return 0
    if not acquire_worker_lock(max_age_seconds=900):
        return 0

    exit_code = 0
    try:
        settings = worker_settings(config_path)
        _log("=== Live trading task started ===")
        if not settings.get("live_trading", True):
            _log("Live trading disabled in background_worker config.")
            return 0

        _sync_shared(config_path, phase="pre-live")
        client = _connect_client(config_path)
        if not client:
            return 1
        _run_live_execute(client, force=force, config_path=config_path)
        _log("=== Live trading task finished ===")
    except Exception as exc:
        exit_code = 1
        _log(f"Live trading task failed: {exc}")
        _log(traceback.format_exc())
    finally:
        release_worker_lock()
    return exit_code


def _clear_stale_pipeline_state(*, max_progress_age_sec: float = 900.0) -> None:
    """Drop orphaned in-progress flags when a prior worker died or hung mid-pipeline.

    A live pipeline must have either a live service lock with recent progress OR
    a live isolated pipeline child. Flags alone are never enough — that left the
    UI stuck at Agent N for hours after the child process died.
    """
    _clear_stale_worker_lock()
    state = load_worker_state()
    if not state.get("pipeline_active"):
        return

    progress_at = float(state.get("pipeline_progress_at") or 0)
    age = (time.time() - progress_at) if progress_at else 9_999.0
    lock_pid = _read_service_lock_pid()
    lock_alive = bool(lock_pid and _pid_is_running(lock_pid))

    # Dead lock owner always wins: process crashed mid-pipeline.
    if not lock_alive:
        _log(
            f"Clearing stale pipeline state — worker lock dead "
            f"(last: {state.get('pipeline_progress') or 'unknown'}, age {age:.0f}s)"
        )
        state.pop("pipeline_active", None)
        state.pop("pipeline_progress", None)
        state.pop("pipeline_progress_at", None)
        state["last_pipeline_at"] = 0
        save_worker_state(state)
        _clear_stale_worker_lock()
        return

    # Healthy: this machine still has a running service + recent progress updates
    if lock_alive and age < max_progress_age_sec:
        if age < max(60.0, float(max_progress_age_sec)):
            return

    # Brand-new start (no progress stamp yet) give a short grace period
    if age < 45 and lock_alive:
        return

    status = worker_pipeline_status(stuck_after_sec=int(max_progress_age_sec))
    _log(
        f"Clearing stale pipeline state — last progress: "
        f"{status.get('progress') or state.get('pipeline_progress') or 'unknown'}"
        f" (age {age:.0f}s"
        + ("; worker lock dead" if not lock_alive else "")
        + ")"
    )
    state.pop("pipeline_active", None)
    state.pop("pipeline_progress", None)
    state.pop("pipeline_progress_at", None)
    state["last_pipeline_at"] = 0
    save_worker_state(state)
    _clear_stale_worker_lock()


# Set by pipeline runner so a daemon watchdog can kill hung children even if
# the main thread is blocked inside communicate/wait.
_PIPELINE_CHILD_PIDS: list[int] = []


def _register_pipeline_child(pid: int) -> None:
    if pid > 0 and pid not in _PIPELINE_CHILD_PIDS:
        _PIPELINE_CHILD_PIDS.append(pid)


def _clear_pipeline_children() -> None:
    _PIPELINE_CHILD_PIDS.clear()


def _watchdog_kill_stale_pipeline(*, stall_sec: float = 100.0) -> None:
    """Daemon: if progress is stale, force-kill pipeline children + clear state.

    In-process pipelines (FINANCE_AGENT_SUBPROCESS=0) have no child PIDs — a hang
    on HTTP blocks the main thread forever. After clearing flags, re-spawn a quiet
    worker and hard-exit so the stuck process cannot hold the service lock.
    """
    import subprocess as _sp
    import sys

    while True:
        try:
            time.sleep(12)
            state = load_worker_state()
            if not state.get("pipeline_active"):
                continue
            progress_at = float(state.get("pipeline_progress_at") or 0)
            if not progress_at:
                continue
            age = time.time() - progress_at
            if age < stall_sec:
                continue
            _log(
                f"WATCHDOG: pipeline stalled {age:.0f}s at "
                f"{state.get('pipeline_progress') or 'unknown'} — recovering"
            )
            pids = list(_PIPELINE_CHILD_PIDS)
            try:
                from agents.agent_process_runner import (
                    ACTIVE_CHILD_PIDS,
                    LAST_PIPELINE_CHILD_PID,
                    _kill_process_tree,
                )

                if LAST_PIPELINE_CHILD_PID:
                    pids.append(int(LAST_PIPELINE_CHILD_PID))
                pids.extend(int(p) for p in list(ACTIVE_CHILD_PIDS) if p)
                for pid in {p for p in pids if p and p != os.getpid()}:
                    _kill_process_tree(pid)
                ACTIVE_CHILD_PIDS.clear()
            except Exception:
                for pid in pids:
                    try:
                        if os.name == "nt":
                            # Always CREATE_NO_WINDOW — bare taskkill flashes a console.
                            try:
                                from process_guard import kill_tree

                                kill_tree(int(pid))
                            except Exception:
                                si = _sp.STARTUPINFO()
                                si.dwFlags |= _sp.STARTF_USESHOWWINDOW
                                si.wShowWindow = 0
                                _sp.run(
                                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                                    capture_output=True,
                                    timeout=15,
                                    check=False,
                                    creationflags=0x08000000,
                                    startupinfo=si,
                                )
                    except Exception:
                        pass
            _PIPELINE_CHILD_PIDS.clear()
            state = load_worker_state()
            state.pop("pipeline_active", None)
            state.pop("pipeline_progress", None)
            state.pop("pipeline_progress_at", None)
            state["last_pipeline_at"] = 0
            save_worker_state(state)

            # Do not auto-respawn here: multiple workers thrash and leave the UI
            # stuck. Clear flags so the next manual/VBS start can recover cleanly.
            # If the main thread is wedged, the process may still need a manual restart.
            try:
                release_service_lock()
            except Exception:
                pass
            _log(
                "WATCHDOG: stall recovered (flags cleared). "
                "If the service stays frozen, re-run Start Silent Worker Only.vbs"
            )
        except Exception:
            pass


def _worker_heartbeat_loop() -> None:
    """Always-on heartbeat so external watchdog can detect a frozen worker."""
    try:
        from process_guard import WORKER_HEARTBEAT, write_heartbeat
    except Exception:
        WORKER_HEARTBEAT = OUTPUT / "etrade_worker_heartbeat.txt"

        def write_heartbeat(path, *, pid=None, extra=""):  # type: ignore[misc]
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"{os.getpid()}\n{time.time():.3f}\n", encoding="utf-8")
            except OSError:
                pass

    while True:
        try:
            write_heartbeat(WORKER_HEARTBEAT, pid=os.getpid(), extra="service")
            _touch_service_lock()
        except Exception:
            pass
        time.sleep(12)


def run_service_loop(config_path: Path = CONFIG_PATH) -> int:
    """Immortal service loop — never exits except KeyboardInterrupt / lock held."""
    if not acquire_service_lock():
        _log(f"Worker service already running (pid {_read_service_lock_pid()}).")
        return 0

    _clear_stale_pipeline_state()
    settings = worker_settings(config_path)
    role = _deployment_role(config_path)
    pipeline_min = int(settings.get("pipeline_interval_minutes", 5))
    off_hours_min = int(settings.get("pipeline_off_hours_interval_minutes", 45))
    plan_min = int(settings.get("plan_interval_minutes", 30))
    execute_min = int(settings.get("execute_min_interval_minutes", 15))
    day_min = int(settings.get("day_trading_interval_minutes", 5))
    live = "ON" if settings.get("live_trading", True) and not settings.get("dry_run") else "OFF"
    day_on = "ON" if settings.get("day_trading", True) else "OFF"
    off_hours = "ON" if _pipeline_runs_off_hours(settings) else "OFF"
    try:
        from deployment import deployment_summary

        _log(f"Deployment: {deployment_summary(config_path)}")
    except Exception:
        _log(f"Deployment role={role}")
    _log(
        f"Background service started (role={role}) - agents every {pipeline_min} min (market) / "
        f"{off_hours_min} min off-hours ({off_hours}), "
        f"plan every {plan_min} min, live trading every {execute_min} min ({live}), "
        f"day trading every {day_min} min ({day_on}). "
        f"Stop-all pauses trading only; pipeline host stays always-on."
    )
    _log(f"Log file: {LOG_FILE}")
    _log(f"Immortal service loop active (pid {os.getpid()}).")

    import threading

    if role in {"pipeline", "all"}:
        threading.Thread(
            target=_watchdog_kill_stale_pipeline,
            kwargs={"stall_sec": float(PIPELINE_STALL_SEC)},
            daemon=True,
            name="pipeline-watchdog",
        ).start()
        _log(f"Pipeline watchdog armed (stall {PIPELINE_STALL_SEC}s).")
    threading.Thread(
        target=_worker_heartbeat_loop,
        daemon=True,
        name="worker-heartbeat",
    ).start()
    _log("Heartbeat thread armed.")

    client: ETradeClient | None = None
    client_refreshed_at = 0.0
    last_quote_publish = 0.0
    try:
        from deployment import load_deployment

        quote_every = float(load_deployment(config_path).get("quote_publish_interval_seconds") or 60)
    except Exception:
        quote_every = 60.0

    try:
        while True:
            try:
                trading_paused = automation_paused(config_path)

                # Recover hung cycles (no progress for 2 minutes)
                if role in {"pipeline", "all"}:
                    _clear_stale_pipeline_state(max_progress_age_sec=120)

                # Shared data: pull peer artifacts every cycle
                _sync_shared(config_path, phase="loop")

                # --- PIPELINE HOST (BOXONE) or all ---
                if role in {"pipeline", "all"}:
                    try:
                        # Prefer shared live quotes before agents (market hours)
                        try:
                            from sync_shared_data import pull_broker_feed

                            if role == "pipeline":
                                pull_broker_feed(config_path=config_path)
                        except Exception:
                            pass
                        _run_pipeline(config_path=config_path)
                        if role == "pipeline":
                            try:
                                from sync_shared_data import push_pipeline_artifacts

                                push_pipeline_artifacts(config_path=config_path)
                            except Exception as exc:
                                _log(f"Pipeline push note: {exc}")
                    except Exception as exc:
                        _log(f"Pipeline cycle error (continuing): {exc}")
                        _log(traceback.format_exc()[-800:])
                        _clear_stale_pipeline_state(max_progress_age_sec=0)

                    try:
                        _run_live_scoring(config_path=config_path)
                    except Exception as exc:
                        _log(f"Live scoring error (continuing): {exc}")

                # --- BROKER HOST (AI-CODING) or all ---
                # Dual-PC: pipeline normally runs on BOXONE. If agent JSONs go
                # stale (share empty / helper down), broker runs a lean fallback
                # so the UI and strategy plan are not stuck on multi-day reports.
                if role == "broker":
                    try:
                        state_fb = load_worker_state()
                        last_fb = float(state_fb.get("last_broker_pipeline_fallback_at") or 0)
                        # At most every 30 min; only when markers are > 6h old.
                        if _agent_reports_stale(max_age_sec=6 * 3600) and (
                            time.time() - last_fb
                        ) >= 1800:
                            age_h = _agent_report_marker_age_sec() / 3600.0
                            _log(
                                f"Agent reports stale on broker ({age_h:.1f}h) — "
                                "fallback pipeline critical+quant"
                            )
                            ran = _run_pipeline(
                                force=True,
                                config_path=config_path,
                                only_lanes=["critical", "quant"],
                            )
                            st2 = load_worker_state()
                            st2["last_broker_pipeline_fallback_at"] = time.time()
                            save_worker_state(st2)
                            if ran:
                                _log("Broker pipeline fallback finished.")
                    except Exception as exc:
                        _log(f"Broker pipeline fallback note: {exc}")

                if role in {"broker", "all"}:
                    if not client or (time.time() - client_refreshed_at) > 1800:
                        try:
                            client = _connect_client(config_path)
                            client_refreshed_at = time.time()
                        except Exception as exc:
                            _log(f"E*TRADE connect failed (will retry): {exc}")
                            client = None

                    if client:
                        if (time.time() - last_quote_publish) >= max(15.0, quote_every):
                            try:
                                _publish_broker_market_data(client, config_path=config_path)
                                last_quote_publish = time.time()
                            except Exception as exc:
                                _log(f"Quote publish error (continuing): {exc}")

                        if trading_paused:
                            _log("Trading paused — orders skipped (pipeline/UI data still sync).")
                        else:
                            for label, fn in (
                                ("plan", lambda: _run_plan_build(client, config_path=config_path)),
                                (
                                    "live execute",
                                    lambda: _run_live_execute(client, config_path=config_path),
                                ),
                                (
                                    "day trading",
                                    lambda: _run_day_trading(client, config_path=config_path),
                                ),
                            ):
                                try:
                                    fn()
                                except Exception as exc:
                                    _log(f"{label} error (continuing): {exc}")
                    else:
                        _log("Broker waiting for E*TRADE connection (GUI OAuth once).")
                elif trading_paused:
                    # pipeline-only host: pause is a no-op for research
                    pass

            except KeyboardInterrupt:
                raise
            except BaseException as exc:
                # Catch everything including unexpected SystemExit from libs
                _log(f"Service loop critical error (will NOT exit): {exc}")
                _log(traceback.format_exc()[-1200:])
                client = None
                try:
                    _clear_stale_pipeline_state(max_progress_age_sec=0)
                except Exception:
                    pass
                time.sleep(5)

            try:
                _touch_service_lock()
            except Exception:
                pass
            try:
                sleep_sec = _next_service_sleep_seconds(config_path)
            except Exception:
                sleep_sec = 60.0
            # Broker-only can sleep a bit longer when trading paused
            if role == "broker" and automation_paused(config_path):
                sleep_sec = max(float(sleep_sec), 30.0)
            _log(f"Service heartbeat — sleeping {sleep_sec:.0f}s (pid {os.getpid()}, role={role}).")
            time.sleep(max(15.0, float(sleep_sec)))
    except KeyboardInterrupt:
        _log(f"Background service KeyboardInterrupt (pid {os.getpid()}).")
    finally:
        _log(f"Background service stopping (pid {os.getpid()}).")
        try:
            release_service_lock()
        except Exception:
            pass
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="E*TRADE headless background worker")
    parser.add_argument("--force", action="store_true", help="Run pipeline and plan even if not due")
    parser.add_argument("--service", action="store_true", help="Run continuously in a loop")
    parser.add_argument("--live-trading", action="store_true", help="Run live trading task only")
    parser.add_argument("--day-trading", action="store_true", help="Run day trading task only")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args()

    if args.service:
        return run_service_loop(args.config)
    if args.day_trading:
        return run_day_trading_cycle(force=args.force, config_path=args.config)
    if args.live_trading:
        return run_live_trading_cycle(force=args.force, config_path=args.config)
    return run_full_cycle(force=args.force, config_path=args.config)


if __name__ == "__main__":
    # Service mode: if the process would exit for any reason other than a clean
    # "already running" signal, log and re-enter so OS/supervisor can keep us up.
    import sys as _sys

    if "--service" in _sys.argv:
        while True:
            try:
                code = main()
                # 0 with lock held by another instance → stay down
                if code == 0:
                    break
                _log(f"Service main returned {code} — restarting in 5s")
                time.sleep(5)
            except KeyboardInterrupt:
                break
            except BaseException as exc:
                try:
                    _log(f"Service process crash: {exc} — restarting in 5s")
                    _log(traceback.format_exc()[-800:])
                except Exception:
                    pass
                time.sleep(5)
        raise SystemExit(0)
    raise SystemExit(main())