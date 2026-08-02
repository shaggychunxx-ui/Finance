#!/usr/bin/env python3
"""LAN bridge so the phone E*TRADE app mirrors the desktop UI and can complete OAuth.

Runs on the broker PC (AI-CODING). Phone connects over Wiâ€‘Fi / LAN.

Endpoints (all JSON; require X-Bridge-Token except /health):
  GET  /health
  GET  /api/dashboard      # ?refresh=1|full=1 forces live broker snapshot pull
  GET  /api/full           # full phone pack: dashboard + agents + accounts + orders
  GET  /api/orders         # broker orders when PC tokens available
  GET  /api/features       # shared API + independent practice flags (phone feature catalog)
  GET  /api/agents         # specialist agents + analysis/findings/projections
  GET  /api/auth/status
  POST /api/oauth/start
  POST /api/oauth/finish   body: {"verifier": "..."}
  POST /api/controls       body: {"side":"long|short|all", "dry_run"?, "auto_execute"?, "paused"?}
  POST /api/stop_all
  POST /api/resume_all

Secrets (consumer keys, access tokens) never leave this machine.
"""

from __future__ import annotations

import json
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
BRIDGE_VERSION = "1.5.3"

# Phone "full data pull" flag for the current request (thread-local).
_pull_ctx = threading.local()

# Human rule (PHONE 2026-07-31): all P/L / chart / average calcs start here.
# Transfer/deposit capital only enters P/L math from each event's date forward.
CALCULATION_START_ISO = "2026-07-24"

# Snapshot quality: never clobber a fuller book with a thin live pull / publish.
_MIN_POS_KEEP_RICHER = 3  # if prior has ≥ this many lots and new has fewer → keep prior


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
    if changed:
        _write_json(BRIDGE_CONFIG, raw)
        _log(f"Wrote {BRIDGE_CONFIG.name} (new bridge token generated)")
    return raw


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


def _snapshot_quality(snap: dict[str, Any] | None) -> tuple[int, float]:
    """Higher is better: (position_count, -age_seconds). Missing age → treat as old."""
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


def _shared_broker_snapshot_paths() -> list[Path]:
    """Possible dual-PC share paths for broker account_snapshot.json."""
    paths: list[Path] = []
    try:
        from deployment import load_deployment

        dep = load_deployment()
        root = str(dep.get("shared_root") or "").strip()
        if root:
            paths.append(Path(root) / "broker" / "account_snapshot.json")
    except Exception:
        pass
    # Common dual-PC layouts (HelperDrop + dedicated FinanceShare)
    for candidate in (
        Path(r"C:\Users\Public\HelperDrop\FinanceShare\broker\account_snapshot.json"),
        Path(r"\\10.10.10.1\HelperDrop\FinanceShare\broker\account_snapshot.json"),
        Path(r"\\10.10.10.1\FinanceShare\broker\account_snapshot.json"),
    ):
        if candidate not in paths:
            paths.append(candidate)
    return paths


def _load_shared_broker_snapshot() -> dict[str, Any]:
    """Best broker snapshot from dual-PC share (BOXONE writer after role flip B)."""
    best: dict[str, Any] = {}
    best_src = ""
    for path in _shared_broker_snapshot_paths():
        try:
            if not path.is_file():
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
                    f"({local_n} → {shared_n} lots)"
                )
            except Exception as exc:
                _log(f"heal local snapshot skipped: {exc}")
    else:
        chosen.setdefault("source", local.get("source") or "local_account_snapshot")
        chosen["_chosen_from"] = "local"
    return chosen


def _data_quality_report() -> dict[str, Any]:
    """Non-secret snapshot quality for /health and ops."""
    local = _read_json(ROOT / "output" / "account_snapshot.json")
    shared = _load_shared_broker_snapshot()
    best = _prefer_snapshot(local, shared)
    role = "all"
    try:
        from deployment import load_deployment

        role = str(load_deployment().get("role") or "all")
    except Exception:
        pass
    return {
        "role": role,
        "local_positions": _snapshot_position_count(local),
        "local_age_sec": _snapshot_age_sec(local),
        "shared_positions": _snapshot_position_count(shared),
        "shared_age_sec": _snapshot_age_sec(shared),
        "serving_positions": _snapshot_position_count(best),
        "serving_age_sec": _snapshot_age_sec(best),
        "serving_source": best.get("_chosen_from")
        or best.get("source")
        or ("none" if not best else "unknown"),
        "strong": _snapshot_position_count(best) >= _MIN_POS_KEEP_RICHER,
    }


def _last_pull_meta() -> dict[str, Any]:
    meta = getattr(_pull_ctx, "meta", None)
    return meta if isinstance(meta, dict) else {}


def _set_pull_meta(**kwargs: Any) -> None:
    cur = dict(_last_pull_meta())
    cur.update(kwargs)
    _pull_ctx.meta = cur


def try_refresh_account_snapshot(
    max_age_sec: float = 300.0,
    force: bool = False,
) -> dict[str, Any]:
    """Best-effort live E*TRADE portfolio pull into output/account_snapshot.json.

    Phone "full data pull from PC" needs real lots + qty, not offline TARGET stubs.
    When force=True (phone Refresh / /api/full?refresh=1), always attempt a live pull.

    Quality gate: never overwrite a fuller snapshot (local or share) with a thinner
    live response — common on pipeline hosts with partial OAuth.
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
                    return prior
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
                message="No local API config — serving best local/share snapshot",
            )
            return prior
        client = ETradeClient(cfg)
        accounts = []
        if hasattr(client, "list_accounts"):
            try:
                accounts = client.list_accounts() or []
            except Exception:
                accounts = []
        key = ""
        label = ""
        if accounts and isinstance(accounts[0], dict):
            key = str(accounts[0].get("account_id_key") or "")
            label = str(
                accounts[0].get("display_label")
                or accounts[0].get("account_name")
                or ""
            )
        if not key:
            key = str(prior.get("account_id_key") or "")
            label = str(prior.get("display_label") or "")
        if not key:
            _set_pull_meta(
                live=False,
                source=str(prior.get("_chosen_from") or "account_snapshot"),
                error="No account id on PC",
                position_count=prior_n,
                fetched_at=prior.get("fetched_at"),
                message="No account id — serving best local/share snapshot",
            )
            return prior
        balance = client.get_balance(key) or {}
        positions = client.get_portfolio(key) or []
        live_n = len(positions) if isinstance(positions, list) else 0
        if live_n == 0 and prior_n > 0:
            _set_pull_meta(
                live=False,
                source=str(prior.get("_chosen_from") or "account_snapshot"),
                error="Live portfolio empty — kept prior/share snapshot",
                position_count=prior_n,
                fetched_at=prior.get("fetched_at"),
                message="Live empty — kept fuller snapshot",
            )
            return prior
        # Quality gate: partial OAuth / wrong account must not clobber full book
        if prior_n >= _MIN_POS_KEEP_RICHER and live_n < prior_n:
            _log(
                f"live pull thinner ({live_n} < prior {prior_n}) — keeping fuller snapshot"
            )
            _set_pull_meta(
                live=False,
                source=str(prior.get("_chosen_from") or "account_snapshot"),
                error=f"Live pull only {live_n} lots vs prior {prior_n}",
                position_count=prior_n,
                fetched_at=prior.get("fetched_at"),
                message=(
                    f"Kept fuller snapshot ({prior_n} lots); "
                    f"live returned {live_n} (re-auth on broker PC if needed)"
                ),
            )
            return prior

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
            message="PC live pull failed — serving best local/share snapshot",
        )
        return prior


def _publish_dashboard_to_oxygen(payload: dict[str, Any]) -> None:
    """Write non-secret dashboard JSON for phone GitHub bus (cellular path).

    Quality gate: never replace a richer published pack with a thinner one
    (e.g. pipeline host 1-lot stub overwriting 14-lot broker publish).
    """
    try:
        oxygen = (
            Path.home()
            / "Documents"
            / "GitHub"
            / "Oxygen-OS"
            / "work"
            / "phone"
            / "etrade-dashboard.json"
        )
        oxygen.parent.mkdir(parents=True, exist_ok=True)
        new_n = len(payload.get("positions") or [])
        if oxygen.is_file():
            try:
                prev = json.loads(oxygen.read_text(encoding="utf-8-sig"))
                if isinstance(prev, dict):
                    old_n = len(prev.get("positions") or [])
                    if old_n >= _MIN_POS_KEEP_RICHER and new_n < old_n:
                        # Allow overwrite only if new pack has real balance and is explicitly live
                        pull = payload.get("data_pull") if isinstance(payload.get("data_pull"), dict) else {}
                        if not pull.get("live"):
                            _log(
                                f"oxygen publish skipped: new {new_n} pos < prior {old_n} "
                                f"(non-live thinner pack)"
                            )
                            return
                        if new_n < max(1, old_n // 2):
                            _log(
                                f"oxygen publish blocked: new {new_n} pos << prior {old_n}"
                            )
                            return
            except (OSError, json.JSONDecodeError, TypeError):
                pass
        # Atomic write so phone/GitHub never reads half a file
        tmp = oxygen.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        tmp.replace(oxygen)
        _log(f"published dashboard -> {oxygen} ({new_n} pos)")
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
                "note": "Auto-learned ACATS/transfer lots â€” treated as deposits with $0 open P/L",
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
                row.setdefault(
                    "reason",
                    "Inbound transfer â€” deposit capital; zero open P/L at book-in",
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
    return t if len(t) <= n else t[: n - 1] + "â€¦"


def _f(val: Any, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _money(n: float | None) -> str:
    if n is None:
        return "â€”"
    return f"${n:,.2f}"


def _pct(n: float | None) -> str:
    if n is None:
        return "â€”"
    sign = "+" if n > 0 else ""
    return f"{sign}{n:.2f}%"


def _is_plausible_day_pl(day_pl: float | None, account_value: float | None) -> bool:
    """Reject day P/L that looks like a deposit-as-profit artifact."""
    if day_pl is None:
        return False
    if account_value is not None and account_value > 0 and abs(day_pl) > account_value * 0.40:
        return False
    return abs(day_pl) < 50_000


def build_account_summary() -> dict[str, Any]:
    """Balance + P/L for phone portfolio UI (best-effort from history + plan).

    Standing rule: deposits never count toward P/L.
      total_pl = latest_value âˆ’ invested_capital
      invested_capital = opening + deposits âˆ’ withdrawals
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
        "opening_balance": None,
        "deposits_total": None,
        "pl_excludes_deposits": True,
        "pl_excludes_transfer_mtm": True,
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
        # Live recompute (capital-event deposit detection) â€” do not trust stale growth profit.
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
        # Canonical formula â€” always latest âˆ’ invested (deposits already in invested).
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
                "opening_balance": _f(opening) if opening is not None else None,
                "deposits_total": deposits_total,
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
            # Prefer higher live equity â€” never let a stale lower figure undercut balance.
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

    # Offline / empty plan must not leave OFFLINE ids — use broker snapshot for phone.
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
        bal_block = snap.get("balance") if isinstance(snap.get("balance"), dict) else {}
        snap_bal = _f(bal_block.get("total_account_value"))
        if snap_bal is not None and out.get("balance") is None:
            out["balance"] = snap_bal
        snap_cash = _f(bal_block.get("cash_buying_power") or bal_block.get("cash"))
        if out.get("cash") is None and snap_cash is not None:
            out["cash"] = snap_cash

    # Re-apply formula after balance merges (stale plan must not invent P/L).
    bal = out.get("balance")
    invested = out.get("invested_capital")
    if bal is not None and invested is not None and invested > 0:
        out["total_pl"] = round(bal - invested, 2)
        out["total_pl_pct"] = round(out["total_pl"] / invested * 100.0, 2)
        out["trend"] = "up" if out["total_pl"] >= 0 else "down"

    day_pl = out.get("day_pl")
    day_pl_pct = out.get("day_pl_pct")
    total_pl = out.get("total_pl")
    total_pl_pct = out.get("total_pl_pct")
    dep = out.get("deposits_total")
    out["display"] = {
        "balance": _money(bal) if bal is not None else "â€”",
        "cash": _money(out.get("cash")) if out.get("cash") is not None else "â€”",
        "day_pl": _money(day_pl) if day_pl is not None else "â€”",
        "day_pl_pct": _pct(day_pl_pct) if day_pl_pct is not None else "â€”",
        "total_pl": _money(total_pl) if total_pl is not None else "â€”",
        "total_pl_pct": _pct(total_pl_pct) if total_pl_pct is not None else "â€”",
        "invested": _money(invested) if invested is not None else "â€”",
        "deposits": _money(dep) if dep is not None else "â€”",
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
            f"{symbol} is treated as an inbound transfer / deposit lot. "
            "Cost basis is capital in (not trading P/L). Price moves after book-in still affect equity."
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
        parts.append(f"Order style: {ot}" + (f" â€” {otr}" if otr else ""))
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
    """Map symbol â†’ proposed action from strategy_plan orders / target holdings."""
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
    # Target holdings without an open order â†’ HOLD signal when currently held
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
            "rationale": row.get("rationale") or "In target portfolio â€” no trade proposed",
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
        snap = _load_account_snapshot()
        snap_pos = snap.get("positions") if isinstance(snap, dict) else None
        if isinstance(snap_pos, list) and snap_pos:
            live = snap_pos
            _log(
                f"positions: full PC pull from account_snapshot "
                f"({len(live)} lots) — plan empty/offline or force_refresh={force_refresh}"
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
        # Transfer/deposit lots: $0 open P/L (capital), but plan SELL/BUY still applies
        if is_xfer:
            role = role or "transfer/deposit"
            if not rationale or "transfer" not in str(rationale).lower():
                rationale = (
                    "Inbound transfer from an outside account (ACATS/broker). "
                    "Cost treated as deposit capital â€” deposits do not count toward P/L. "
                    "Position remains tradeable."
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
                    "Transfer/deposit lot â€” capital for P/L; tradeable when plan has orders"
                    if is_xfer
                    else "No open order in latest strategy plan â€” hold current lot"
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
            prop_display = "HOLD Â· deposit"
        else:
            prop_display = prop_action
        if is_xfer:
            pl_display = "Deposit"
            pl_pct_display = "â€”"
        else:
            pl_display = _money(unreal) if unreal is not None else "â€”"
            pl_pct_display = _pct(unreal_pct) if unreal_pct is not None else "â€”"

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
                "proposed_action": prop_action,
                "proposed_quantity": prop_qty,
                "proposed_price": prop_px,
                "proposed_order_type": prop.get("order_type"),
                "proposed_status": prop.get("status"),
                "proposed_rationale": prop_rationale or None,
                "proposed_target_weight_pct": prop.get("target_weight_pct"),
                "proposed_target_value_usd": prop.get("target_value_usd"),
                "display": {
                    "price": _money(price) if price else "â€”",
                    "market_value": _money(market_value) if market_value is not None else "â€”",
                    "cost_basis": _money(cost_basis) if cost_basis else "â€”",
                    "cost_total": _money(cost_total) if cost_total is not None else "â€”",
                    "unrealized_pl": pl_display,
                    "unrealized_pl_pct": pl_pct_display,
                    "quantity": f"{qty:g}" if qty else "â€”",
                    "proposed_action": prop_display,
                },
            }
        )

    # If no live positions, fall back to portfolio target holdings as ideas-as-positions
    if not positions:
        for row in portfolio.get("holdings") or []:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").upper().strip()
            if not sym:
                continue
            price = _f(row.get("price"))
            alloc = _f(row.get("allocation_usd"))
            positions.append(
                {
                    "symbol": sym,
                    "side": "TARGET",
                    "quantity": None,
                    "price": price,
                    "market_value": alloc or None,
                    "cost_basis": None,
                    "cost_total": None,
                    "unrealized_pl": None,
                    "unrealized_pl_pct": _f(row.get("projected_return_pct"))
                    if row.get("projected_return_pct") is not None
                    else None,
                    "weight_pct": row.get("weight_pct"),
                    "score": row.get("score"),
                    "projected_return_pct": row.get("projected_return_pct"),
                    "projected_return_horizon": row.get("projected_return_horizon"),
                    "confidence": row.get("confidence"),
                    "role": row.get("role"),
                    "rationale": row.get("rationale"),
                    "order_type": row.get("order_type"),
                    "allocation_usd": alloc,
                    "display": {
                        "price": _money(price) if price else "â€”",
                        "market_value": _money(alloc) if alloc else "â€”",
                        "cost_basis": "â€”",
                        "unrealized_pl": "â€”",
                        "unrealized_pl_pct": _pct(_f(row.get("projected_return_pct")))
                        if row.get("projected_return_pct") is not None
                        else "â€”",
                        "quantity": "â€”",
                    },
                }
            )

    # Portfolio weight by market value if missing
    if total_mv > 0:
        for p in positions:
            if p.get("weight_pct") is None and p.get("market_value") is not None:
                p["weight_pct"] = round(abs(_f(p["market_value"])) / total_mv * 100.0, 2)

    positions.sort(key=lambda r: abs(_f(r.get("market_value"))), reverse=True)
    return positions


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
    """Build phone dashboard. force_refresh=True → live full PC portfolio pull.

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

    long_pct: Any = "â€”"
    short_pct: Any = "â€”"
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
        long_pct = deploy.get("long_max_deploy_pct", "â€”")
        short_pct = deploy.get("short_max_deploy_pct", "â€”")
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
            "long": tops_l[0] if tops_l else "—",
            "short": tops_s[0] if tops_s else "—",
        },
        {"item": "# ideas", "long": str(len(long_rows)), "short": str(len(short_rows))},
        {"item": "Isolation", "long": "Longs only", "short": "Shorts only"},
        {"item": "Shared API", "long": "Yes (one)", "short": "Yes (same)"},
        {"item": "Shared capital", "long": "Yes", "short": "Yes"},
    ]

    account = build_account_summary()
    positions = build_positions(force_refresh=force_refresh)
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
        if is_xfer:
            if sym:
                learned.add(sym)
            cost = _f(p.get("cost_total"))
            # Cost basis only â€” never book transfer deposits at market value.
            if cost is not None and cost > 0:
                transfer_deposit += abs(cost)
            p["open_pl_for_total"] = 0.0  # transfer book-in is capital, not P/L
            # Position display: deposit capital, never red/green open P/L
            # Keep plan proposed_action (SELL/BUY) — transfer lots are tradeable
            p["unrealized_pl"] = 0.0
            p["unrealized_pl_pct"] = 0.0
            if not p.get("role"):
                p["role"] = "transfer/deposit"
            disp = p.get("display") if isinstance(p.get("display"), dict) else {}
            disp = dict(disp)
            disp["unrealized_pl"] = "Deposit"
            disp["unrealized_pl_pct"] = "â€”"
            prop_a = str(p.get("proposed_action") or "HOLD").upper()
            is_trade = prop_a in ("BUY", "SELL", "SELL_SHORT", "BUY_TO_COVER")
            if not is_trade:
                # No plan trade — keep deposit HOLD label
                if not disp.get("proposed_action") or "HOLD" in str(disp.get("proposed_action") or "").upper():
                    disp["proposed_action"] = "HOLD Â· deposit"
                if not p.get("proposed_status"):
                    p["proposed_status"] = "deposit"
            # else: leave proposed_action / display from build_positions (plan trade)
            p["display"] = disp
        else:
            # Trading lots only contribute to portfolio open P/L
            p["open_pl_for_total"] = _f(p.get("unrealized_pl"))

    if learned:
        remember_transfer_deposit_symbols(learned)

    # Portfolio open P/L = trading lots only (never transfer MTM / open_pl_for_total leak)
    pos_pl = sum(
        _f(p.get("unrealized_pl"))
        for p in positions
        if not p.get("transfer_as_deposit") and p.get("unrealized_pl") is not None
    )

    # Transfer lot MTM (mv-cost) even when display open is $0 — exclude from total/avg P/L
    transfer_open_mtm = 0.0
    for p in positions:
        if not p.get("transfer_as_deposit"):
            continue
        mv = _f(p.get("market_value"))
        cost = _f(p.get("cost_total"))
        if mv is not None and cost is not None:
            transfer_open_mtm += mv - cost
    bal_pl = _f(account.get("balance"))
    inv_pl = _f(account.get("invested_capital"))
    if bal_pl is not None and inv_pl is not None and inv_pl > 0:
        capital_pl = bal_pl - inv_pl
        total_pl_ex = round(capital_pl - transfer_open_mtm, 2)
        account["total_pl"] = total_pl_ex
        account["total_pl_pct"] = round(total_pl_ex / inv_pl * 100.0, 2)
        account["trend"] = "up" if total_pl_ex >= 0 else "down"
        account["transfer_open_mtm"] = round(transfer_open_mtm, 4)
        account["pl_excludes_transfer_mtm"] = True
        adisp = account.get("display") if isinstance(account.get("display"), dict) else {}
        adisp = dict(adisp)
        adisp["total_pl"] = _money(total_pl_ex)
        adisp["total_pl_pct"] = _pct(account["total_pl_pct"])
        account["display"] = adisp

    pos_mv = sum(abs(_f(p.get("market_value"))) for p in positions)

    dep = _f(account.get("deposits_total"))
    dep_note = ""
    if dep is not None and abs(dep) >= 0.01:
        dep_note = f" Â· P/L excludes deposits Â· deposits {_money(dep)} not in P/L"
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
                row["long"] = "â€”"
                row["short"] = "â€”"
        status = f"{status} Â· phone UI info OFF" if status else "phone UI info OFF"

    pull_meta = dict(_last_pull_meta())
    if not pull_meta.get("position_count"):
        pull_meta["position_count"] = len(positions)
    if pull_meta.get("source") in (None, "", "building"):
        pull_meta["source"] = "account_snapshot" if positions else "empty"
    pull_meta["force_refresh"] = bool(force_refresh)
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
            "position_count": len(positions),
            "market_value": pos_mv,
            "unrealized_pl": pos_pl,
            "transfer_deposit": round(transfer_deposit, 2),
            "deposits_total": account.get("deposits_total"),
            "display": {
                "market_value": _money(pos_mv),
                "unrealized_pl": _money(pos_pl),
                "position_count": str(len(positions)),
            },
        },
        "pl_excludes_deposits": True,
        "pl_excludes_transfer_mtm": True,
        "pl_from_calculation_start": True,
        "calculation_start": CALCULATION_START_ISO,
        "transfer_open_mtm": round(transfer_open_mtm, 4),
        "deposits_total": account.get("deposits_total"),
        # Shared API + independent practice — phone app feature/data contract
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
            "joint_edge": f"${joint:,.0f}" if joint else "—",
            "joint_edge_usd": joint,
            "balance": account.get("display", {}).get("balance", "—"),
            "day_pl": account.get("display", {}).get("day_pl", "—"),
            "total_pl": account.get("display", {}).get("total_pl", "—"),
            "invested": account.get("display", {}).get("invested", "—"),
            "deposits": account.get("display", {}).get("deposits", "—"),
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
      • deposits/transfers book capital only from their event timestamps
        (profit_at_point uses net flows before each point)
      • all series clipped + rebased to CALCULATION_START_ISO (P/L at start = 0)
      • transfer open MTM stripped only after transfer capital lands
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

    # --- Transfer MTM from transfer-land date only ---
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

    # First performance index where bulk transfer capital is visible
    post_xfer_floor = 1500.0
    land_idx = next(
        (i for i, p in enumerate(points) if float(p.get("value") or 0) >= post_xfer_floor),
        len(points),
    )
    if abs(transfer_open_mtm) >= 0.005:
        for i, p in enumerate(points):
            if i < land_idx:
                continue
            pl = _f(p.get("profit_amount"))
            if pl is None:
                continue
            p["profit_amount"] = round(pl - transfer_open_mtm, 2)
            inv = _f(metrics.get("invested_capital"))
            val = _f(p.get("value"))
            if inv and inv > 0:
                p["profit_pct"] = round(p["profit_amount"] / inv * 100.0, 2)
            elif val and val > 0:
                p["profit_pct"] = round(p["profit_amount"] / val * 100.0, 2)

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
        "pl_excludes_transfer_mtm": True,
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
            live_error = "PC E*TRADE session missing or expired â€” showing saved accounts"
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
                # Same account on long+short â€” keep one row, mark dual role
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
            "message": "Not connected — use phone login to authorize the desktop app",
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
            "Session expired at midnight ET — full Connect required"
            if expired
            else ("Token idle — renew soon" if idle else "Connected to E*TRADE (shared API)")
        ),
        "age_minutes": round(age_min, 1) if age_min is not None else None,
        "long_account": long_label,
        "short_account": short_label,
    }


def oauth_start() -> dict[str, Any]:
    from etrade_api.config import load_config
    from etrade_api.oauth import start_authorization

    cfg = load_config(LONG_CONFIG)
    if not cfg.consumer_key or not cfg.consumer_secret:
        raise RuntimeError("Missing consumer key/secret in etrade_config.json on the PC")
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
    # Prefer common dual-PC LAN
    preferred = [ip for ip in found if ip.startswith("10.10.10.")]
    others = [ip for ip in found if ip not in preferred]
    return preferred + others


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
    # Minimal empty payload â€” phone can still show empty state
    return {
        "ok": True,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent_count": 0,
        "agents": [],
        "source": "empty",
        "message": "No agent snapshot yet â€” run agents on PC / publish etrade-agents.json",
    }


def build_orders_for_phone() -> dict[str, Any]:
    """Best-effort broker orders for the phone Orders window (PC tokens required)."""
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
        raw: list[Any] = []
        for meth in ("list_orders", "get_orders", "get_order_list"):
            if hasattr(client, meth):
                try:
                    raw = getattr(client, meth)(key) or []
                    break
                except Exception as exc:
                    return {
                        "ok": True,
                        "orders": [],
                        "source": "error",
                        "message": str(exc),
                    }
        if not isinstance(raw, list):
            raw = []
        orders: list[dict[str, Any]] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            oid = str(
                row.get("order_id")
                or row.get("orderId")
                or row.get("orderNumber")
                or ""
            )
            sym = str(row.get("symbol") or row.get("Symbol") or "—")
            action = str(row.get("action") or row.get("orderAction") or "—")
            status = str(row.get("status") or row.get("orderStatus") or "—")
            qty = _f(row.get("quantity") or row.get("orderedQuantity"))
            filled = _f(row.get("filled_quantity") or row.get("filledQuantity"))
            limit_p = _f(row.get("limit_price") or row.get("limitPrice"))
            stop_p = _f(row.get("stop_price") or row.get("stopPrice"))
            avg_p = _f(row.get("average_fill_price") or row.get("averageExecutionPrice"))
            price_type = row.get("price_type") or row.get("priceType")
            value = None
            if qty is not None and (avg_p is not None or limit_p is not None):
                px = avg_p if avg_p is not None else limit_p
                value = abs(qty) * float(px) if px is not None else None
            orders.append(
                {
                    "order_id": oid or f"{sym}-{status}",
                    "symbol": sym,
                    "action": action,
                    "status": status,
                    "quantity": qty,
                    "filled_quantity": filled,
                    "price_type": price_type,
                    "limit_price": limit_p,
                    "stop_price": stop_p,
                    "average_fill_price": avg_p,
                    "order_value": value,
                    "display": {
                        "quantity": f"{qty:g}" if qty is not None else "—",
                        "filled": f"{filled:g}" if filled is not None else "—",
                        "price": _money(avg_p or limit_p or stop_p)
                        if (avg_p or limit_p or stop_p) is not None
                        else "—",
                        "value": _money(value) if value is not None else "—",
                        "status": status,
                        "action": action,
                        "placed": str(row.get("placed_time") or row.get("placedTime") or "—"),
                    },
                }
            )
        return {
            "ok": True,
            "orders": orders,
            "count": len(orders),
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
    """One-shot full data pack for the phone: dashboard + agents + accounts + orders."""
    dash = build_dashboard(force_refresh=force_refresh)
    agents = build_agents_for_phone()
    accounts = list_accounts_for_phone()
    orders = build_orders_for_phone()
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
        body = json.dumps(payload, indent=2).encode("utf-8")
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
                    },
                )
                return
            if not self._authorized():
                self._send(401, {"ok": False, "error": "Unauthorized â€” set bridge token in the phone app"})
                return
            if path == "/api/dashboard":
                self._send(200, build_dashboard(force_refresh=force))
                return
            if path == "/api/full":
                # Full data pack for phone Refresh — always attempt live PC portfolio pull
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
                # Prefer latest published phone APK next to the Oxygen-OS checkout, then Desktop copy.
                candidates = [
                    Path.home() / "Documents" / "GitHub" / "Oxygen-OS" / "etrade-app" / "dist" / "ETradeTrader.apk",
                    Path.home() / "Desktop" / "ETradeTrader.apk",
                    ROOT / "ETradeTrader.apk",
                ]
                apk_path = next((p for p in candidates if p.is_file() and p.stat().st_size > 50_000), None)
                if apk_path is None:
                    self._send(
                        404,
                        {
                            "ok": False,
                            "error": "APK not found on PC â€” build etrade-app/dist/ETradeTrader.apk first",
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
                self._send(401, {"ok": False, "error": "Unauthorized â€” set bridge token in the phone app"})
                return
            body = self._read_body()
            if path == "/api/oauth/start":
                self._send(200, oauth_start())
                return
            if path == "/api/oauth/finish":
                self._send(200, oauth_finish(str(body.get("verifier") or "")))
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


def main() -> int:
    cfg = load_bridge_config()
    host = str(cfg.get("host") or DEFAULT_HOST)
    port = int(cfg.get("port") or DEFAULT_PORT)
    token = str(cfg.get("bridge_token") or "")
    BridgeHandler.bridge_token = token

    httpd = ThreadingHTTPServer((host, port), BridgeHandler)
    ips = lan_ips()
    _log(f"Phone bridge v{BRIDGE_VERSION} listening on {host}:{port}")
    for ip in ips:
        _log(f"  Phone base URL: http://{ip}:{port}")
    _log(f"  Bridge token (enter in phone app): {token}")
    _log("  GET /health  (no auth)  |  GET /api/dashboard  |  POST /api/oauth/start")

    # Print a compact pairing card for first-run
    print("")
    print("=" * 56)
    print("  E*TRADE Phone Bridge")
    print("=" * 56)
    if ips:
        print(f"  Base URL:  http://{ips[0]}:{port}")
    print(f"  Token:     {token}")
    print("  Enter both in the phone app Setup screen.")
    print("=" * 56)
    print("")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        _log("Stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
