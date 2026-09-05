#!/usr/bin/env python3
"""Build the live E*TRADE trader summary and email it to self.

Reads the GROMIT live runtime (%USERPROFILE%\\Finance), never the git clone.
Always writes a detailed weekly PDF (daily rows included), then sends:
  1) Gmail API if ~/.gmail-link token has gmail.send (with PDF attached)
  2) Chrome Default Gmail compose (CDP if Chrome was started with 9222,
     else compose URL with body= + clipboard paste + attach PDF + Ctrl+Enter)

Never click Send on an empty compose. A prior run showed Gmail
"Message sent" with only the subject filled (Gemini "Help me write"
placeholder). Body ink-ratio must pass before Send.

Usage (live venv):
  python tools/send_etrade_trader_summary_email.py
  python tools/send_etrade_trader_summary_email.py --print-only
  python tools/send_etrade_trader_summary_email.py --pdf-only
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import json
import os
import socket
import struct
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from email.message import EmailMessage
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_TO = "shaggychunxx@gmail.com"
CDP_PORT = 9222
LINK_DIR = Path.home() / ".gmail-link"
SEND_SCOPES = (
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _f(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _usd(v: Any) -> str:
    n = _f(v)
    if n is None:
        return "-"
    return f"${n:,.2f}"


def _pct(v: Any) -> str:
    n = _f(v)
    if n is None:
        return "-"
    return f"{n:+.2f}%"


def _dt(raw: Any) -> str:
    if raw is None or raw == "":
        return "-"
    if isinstance(raw, (int, float)) and raw > 1e11:
        try:
            return datetime.fromtimestamp(raw / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        except (OSError, OverflowError, ValueError):
            return str(raw)
    s = str(raw)
    if s.replace(".", "", 1).isdigit():
        try:
            n = float(s)
            if n > 1e12:
                n = n / 1000.0
            if n > 1e9:
                return datetime.fromtimestamp(n, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        except (OSError, OverflowError, ValueError):
            pass
    return s.replace("T", " ").replace("+00:00", " UTC")[:22]


def live_root() -> Path:
    from etrade_runtime import resolve_live_root

    return resolve_live_root().root


ET = ZoneInfo("America/New_York")


def _weekday_window(today: datetime, sessions: int = 5) -> set[str]:
    days: set[str] = set()
    d = today.astimezone(ET).date() if today.tzinfo else today.date()
    while len(days) < sessions:
        if d.weekday() < 5:
            days.add(d.isoformat())
        d -= timedelta(days=1)
    return days


def _to_et(raw: Any) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        ts = raw
    else:
        try:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(ET)


def daily_closes_from_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Last equity per America/New_York calendar date. No account_id_key."""
    by: dict[str, dict[str, Any]] = {}
    for row in points:
        if not isinstance(row, dict):
            continue
        ts = _to_et(row.get("at") or row.get("ts") or row.get("timestamp"))
        val = _f(row.get("total_account_value") or row.get("value") or row.get("equity"))
        if ts is None or val is None:
            continue
        day = ts.date().isoformat()
        prev = by.get(day)
        if prev is None or ts >= prev["_ts"]:
            by[day] = {
                "date": day,
                "close": val,
                "source": str(row.get("source") or "history"),
                "_ts": ts,
            }
    return [by[d] for d in sorted(by)]


def week_bounds(now: datetime) -> tuple[date, date]:
    today = now.astimezone(ET).date() if now.tzinfo else now.date()
    monday = today - timedelta(days=today.weekday())
    return monday, today


def last_marks_by_et_day(points_by_symbol: dict[str, list[Any]]) -> dict[str, dict[str, float]]:
    """Last traded price per America/New_York date from history/prices points."""
    out: dict[str, dict[str, float]] = {}
    for sym, rows in points_by_symbol.items():
        name = str(sym or "").upper()
        if not name or not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            ts = _to_et(row.get("at") or row.get("ts") or row.get("timestamp"))
            px = _f(row.get("price") or row.get("close"))
            if ts is None or px is None:
                continue
            out.setdefault(ts.date().isoformat(), {})[name] = px
    return out


def trade_dates_et(trades: list[Any]) -> set[str]:
    days: set[str] = set()
    for row in trades:
        if not isinstance(row, dict):
            continue
        ts = _to_et(row.get("executed_at") or row.get("at") or row.get("ts"))
        if ts is not None:
            days.add(ts.date().isoformat())
    return days


def implied_non_equity(equity: float | None, lots: list[dict[str, Any]]) -> float | None:
    """Equity minus long market value (margin/cash/other). Stable when lots do not trade."""
    if equity is None:
        return None
    mv = 0.0
    for row in lots:
        mv_one = _f(row.get("market_value"))
        if mv_one is None:
            qty = _f(row.get("quantity")) or 0.0
            px = _f(row.get("price"))
            mv_one = (px * qty) if px is not None else None
        if mv_one is None:
            return None
        mv += mv_one
    return float(equity) - mv


def reconstruct_equity(
    lots: list[dict[str, Any]],
    px_map: dict[str, float],
    non_equity: float | None,
) -> float | None:
    """Same lots × that day's marks + unchanged non-equity. None if any lot lacks a mark."""
    if non_equity is None or not lots:
        return None
    total = float(non_equity)
    for row in lots:
        sym = str(row.get("symbol") or "").upper()
        qty = _f(row.get("quantity"))
        px = px_map.get(sym)
        if not sym or qty is None or px is None:
            return None
        total += qty * px
    return round(total, 2)


def _persist_close(
    root: Path,
    *,
    day: str,
    close: float,
    source: str,
    at: str,
) -> None:
    """Append one daily close onto this root's account_values.json (live tree)."""
    path = root / "output" / "history" / "account_values.json"
    data = _load_json(path)
    if not isinstance(data, dict):
        data = {"points": []}
    points = [p for p in (data.get("points") or []) if isinstance(p, dict)]
    for row in points:
        ts = _to_et(row.get("at") or row.get("ts") or row.get("timestamp"))
        if ts is None or ts.date().isoformat() != day:
            continue
        existing = str(row.get("source") or "")
        if source == "marks" and existing not in {"", "marks", "missing"}:
            return
        if existing == source:
            return
    points.append(
        {
            "at": at,
            "total_account_value": round(float(close), 2),
            "source": source,
        }
    )
    data["points"] = points[-500:]
    data["latest_value"] = round(float(close), 2)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def fill_missing_closes(
    closes: list[dict[str, Any]],
    *,
    monday: date,
    today: date,
    lots: list[dict[str, Any]],
    marks_by_day: dict[str, dict[str, float]],
    non_equity: float | None,
    trade_dates: set[str],
) -> list[dict[str, Any]]:
    """Fill weekday gaps from marks when that session had no trades (qty unchanged)."""
    have = {str(c.get("date")) for c in closes if c.get("date")}
    extra: list[dict[str, Any]] = []
    d = monday
    while d <= today:
        if d.weekday() < 5:
            iso = d.isoformat()
            if iso not in have and iso not in trade_dates:
                eq = reconstruct_equity(lots, marks_by_day.get(iso) or {}, non_equity)
                if eq is not None:
                    extra.append({"date": iso, "close": eq, "source": "marks"})
        d += timedelta(days=1)
    if not extra:
        return closes
    merged = list(closes) + extra
    merged.sort(key=lambda c: str(c.get("date") or ""))
    return merged


def week_daily_rows(
    closes: list[dict[str, Any]],
    *,
    now: datetime,
    pdt_by_date: dict[str, Any] | None = None,
    pdt_symbols_by_date: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Weekday rows Monday through today (ET). Day P/L vs prior close."""
    monday, today = week_bounds(now)
    close_map = {str(c.get("date")): c for c in closes if c.get("date")}
    last_close: float | None = None
    for c in closes:
        try:
            d = date.fromisoformat(str(c.get("date")))
        except ValueError:
            continue
        if d < monday:
            last_close = _f(c.get("close"))
    rows: list[dict[str, Any]] = []
    d = monday
    while d <= today:
        if d.weekday() < 5:
            iso = d.isoformat()
            hit = close_map.get(iso)
            close = _f((hit or {}).get("close")) if hit else None
            pl = None
            pct = None
            if close is not None and last_close:
                pl = close - last_close
                pct = (pl / last_close) * 100.0
            rows.append(
                {
                    "date": iso,
                    "weekday": d.strftime("%a"),
                    "close": close,
                    "pl": pl,
                    "pl_pct": pct,
                    "source": (hit or {}).get("source") or "missing",
                    "pdt": int((pdt_by_date or {}).get(iso) or 0),
                    "pdt_symbols": list((pdt_symbols_by_date or {}).get(iso) or []),
                }
            )
            if close is not None:
                last_close = close
        d += timedelta(days=1)
    return rows


def gather_summary(root: Path, *, include_orders: bool = True) -> dict[str, Any]:
    out = root / "output"
    snap = _load_json(out / "account_snapshot.json")
    goals = _load_json(out / "account_goals_status.json")
    refresh = _load_json(out / "phone_refresh_last.json")
    wstate = _load_json(out / "etrade_worker_state.json")
    pdt = _load_json(out / "pdt_tracker.json")
    plan = _load_json(out / "strategy_plan.json")
    brief = _load_json(out / "history" / "next_session_brief.json")
    values = _load_json(out / "history" / "account_values.json")
    tracker = _load_json(out / "equity_tracker.json")
    cfg = _load_json(root / "etrade_config.json")
    bg = cfg.get("background_worker") if isinstance(cfg.get("background_worker"), dict) else {}
    bal = snap.get("balance") if isinstance(snap.get("balance"), dict) else {}
    positions = [p for p in (snap.get("positions") or []) if isinstance(p, dict)]

    lots: list[dict[str, Any]] = []
    mv_total = 0.0
    upl_total = 0.0
    for row in positions:
        qty = _f(row.get("quantity")) or 0.0
        px = _f(row.get("price"))
        mv = _f(row.get("market_value"))
        cb = _f(row.get("cost_basis"))
        if mv is None and px is not None:
            mv = px * qty
        upl = None
        if px is not None and cb is not None and qty:
            # Snapshot cost_basis is per-share on this account.
            upl = (px - cb) * qty
        if mv is not None:
            mv_total += mv
        if upl is not None:
            upl_total += upl
        lots.append(
            {
                "symbol": str(row.get("symbol") or "").upper(),
                "quantity": qty,
                "price": px,
                "market_value": mv,
                "cost_basis": cb,
                "unrealized_pl": upl,
            }
        )
    lots.sort(key=lambda r: abs(float(r.get("market_value") or 0)), reverse=True)
    if mv_total:
        for row in lots:
            mv = _f(row.get("market_value"))
            row["weight_pct"] = (100.0 * mv / mv_total) if mv is not None else None

    now = datetime.now(timezone.utc)
    window = _weekday_window(now, 5)
    day_trades = [d for d in (pdt.get("day_trades") or []) if isinstance(d, dict)]
    pdt_in_window = [d for d in day_trades if str(d.get("date") or "") in window]
    pdt_by_date = Counter(str(d.get("date")) for d in pdt_in_window)
    pdt_symbols_by_date: dict[str, list[str]] = {}
    for d in pdt_in_window:
        day = str(d.get("date") or "")
        sym = str(d.get("symbol") or "").upper()
        if day and sym and sym not in pdt_symbols_by_date.setdefault(day, []):
            pdt_symbols_by_date[day].append(sym)

    value_points = [p for p in (values.get("points") or []) if isinstance(p, dict)]
    extra = {
        "at": snap.get("fetched_at") or now.isoformat(),
        "total_account_value": _f(bal.get("total_account_value")) or _f(goals.get("latest_value")),
        "source": "snapshot",
    }
    if extra.get("total_account_value") is not None:
        value_points = value_points + [extra]
    monday, today = week_bounds(now)
    trades = _load_json(out / "history" / "trade_history.json")
    trade_days = trade_dates_et([t for t in (trades.get("trades") or []) if isinstance(t, dict)])
    px_by_sym: dict[str, list[Any]] = {}
    prices_dir = out / "history" / "prices"
    for lot in lots:
        sym = str(lot.get("symbol") or "").upper()
        if not sym or sym in px_by_sym:
            continue
        px_by_sym[sym] = list((_load_json(prices_dir / f"{sym}.json").get("points") or []))
    marks_by_day = last_marks_by_et_day(px_by_sym)
    equity_now = _f(bal.get("total_account_value")) or _f(goals.get("latest_value"))
    non_eq = implied_non_equity(equity_now, lots)
    closes = fill_missing_closes(
        daily_closes_from_points(value_points),
        monday=monday,
        today=today,
        lots=lots,
        marks_by_day=marks_by_day,
        non_equity=non_eq,
        trade_dates=trade_days,
    )
    daily_rows = week_daily_rows(
        closes,
        now=now,
        pdt_by_date=dict(pdt_by_date),
        pdt_symbols_by_date=pdt_symbols_by_date,
    )
    for row in daily_rows:
        if row.get("source") != "marks" or row.get("close") is None:
            continue
        day = date.fromisoformat(str(row["date"]))
        stamp = datetime(day.year, day.month, day.day, 16, 5, tzinfo=ET).isoformat()
        _persist_close(
            root,
            day=str(row["date"]),
            close=float(row["close"]),
            source="marks",
            at=stamp,
        )
    if extra.get("total_account_value") is not None:
        snap_day = None
        ts = _to_et(extra.get("at"))
        if ts is not None:
            snap_day = ts.date().isoformat()
        if snap_day:
            _persist_close(
                root,
                day=snap_day,
                close=float(extra["total_account_value"]),
                source="snapshot",
                at=str(extra.get("at") or now.isoformat()),
            )
    holding_daily: list[dict[str, Any]] = []
    for eq in tracker.get("equities") or []:
        if not isinstance(eq, dict) or not eq.get("held"):
            continue
        holding_daily.append(
            {
                "symbol": str(eq.get("symbol") or "").upper(),
                "last": _f(eq.get("last") or eq.get("price")),
                "day_chg_pct": _f(eq.get("day_chg_pct")),
                "week_chg_pct": _f(eq.get("week_chg_pct")),
            }
        )
    holding_daily.sort(key=lambda r: abs(float(r.get("day_chg_pct") or 0)), reverse=True)

    orders_pack: dict[str, Any] = {}
    if include_orders:
        try:
            sys.path.insert(0, str(root))
            from phone_bridge import build_orders_for_phone  # noqa: WPS433

            orders_pack = build_orders_for_phone() or {}
        except Exception as exc:
            orders_pack = {"ok": False, "orders": [], "message": str(exc), "source": "error"}

    raw_orders = [o for o in (orders_pack.get("orders") or []) if isinstance(o, dict)]
    open_orders = [
        o
        for o in raw_orders
        if "OPEN" in str(o.get("status") or "").upper()
        or str(o.get("status") or "").upper() in {"PARTIAL", "CANCEL_REQUESTED"}
    ]
    grouped: Counter[tuple[str, ...]] = Counter()
    for o in open_orders:
        grouped[
            (
                str(o.get("symbol") or "-").upper(),
                str(o.get("action") or "-").upper(),
                str(o.get("price_type") or o.get("order_type") or "-"),
                str(o.get("stop_price") or "-"),
                str(o.get("limit_price") or "-"),
                str(int(_f(o.get("quantity")) or 0)),
            )
        ] += 1
    open_groups = [
        {
            "symbol": k[0],
            "action": k[1],
            "price_type": k[2],
            "stop_price": k[3],
            "limit_price": k[4],
            "quantity": k[5],
            "count": n,
        }
        for k, n in grouped.most_common()
    ]

    regime = plan.get("regime") if isinstance(plan.get("regime"), dict) else {}
    daily = goals.get("daily") if isinstance(goals.get("daily"), dict) else {}
    weekly = goals.get("weekly") if isinstance(goals.get("weekly"), dict) else {}
    monthly = goals.get("monthly") if isinstance(goals.get("monthly"), dict) else {}

    return {
        "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"),
        "host": os.environ.get("COMPUTERNAME") or "GROMIT",
        "account_name": str(snap.get("display_label") or "Individual Brokerage"),
        "fetched_at": snap.get("fetched_at"),
        "source": snap.get("source"),
        "sandbox": bool(snap.get("sandbox")),
        "equity": _f(bal.get("total_account_value")) or _f(goals.get("latest_value")),
        "cash_bp": _f(bal.get("cash_buying_power")) or _f(bal.get("cash")),
        "market_value": mv_total,
        "unrealized_pl": upl_total,
        "position_count": len(lots),
        "positions": lots,
        "total_pl": _f(goals.get("total_pl_amount")),
        "total_pl_pct": _f(goals.get("total_pl_pct")),
        "total_avg_pl_pct": _f(goals.get("total_avg_pl_pct")),
        "baseline_value": _f(goals.get("baseline_value")),
        "daily": daily,
        "weekly": weekly,
        "monthly": monthly,
        "net_external_flows": _f(goals.get("net_external_flows")),
        "week_start": monday.isoformat(),
        "week_end": today.isoformat(),
        "daily_rows": daily_rows,
        "holding_daily": holding_daily[:16],
        "flags": {
            "dry_run": bool(bg.get("dry_run", True)),
            "auto_execute": bool(bg.get("auto_execute", False)),
            "live_trading": bool(bg.get("live_trading", False)),
            "day_trading": bool(bg.get("day_trading", False)),
            "paused": bool(bg.get("paused", False)),
            "sandbox": bool(cfg.get("sandbox", True)),
        },
        "long_mode": refresh.get("long_mode"),
        "market_open": refresh.get("market_open"),
        "agent_count": refresh.get("agent_count"),
        "refresh_at": refresh.get("at") or (refresh.get("data_pull") or {}).get("fetched_at"),
        "plan_generated_at": plan.get("generated_at"),
        "plan_error": wstate.get("last_plan_error"),
        "regime_label": regime.get("label"),
        "regime_summary": str(regime.get("summary") or "")[:280],
        "pdt_window_days": sorted(window),
        "pdt_count": len(pdt_in_window),
        "pdt_by_date": dict(pdt_by_date),
        "orders_source": orders_pack.get("source"),
        "orders_message": orders_pack.get("message"),
        "open_order_count": len(open_orders),
        "order_count": orders_pack.get("count") if orders_pack else len(raw_orders),
        "open_groups": open_groups,
        "brief_for": brief.get("for_session"),
        "brief_actions": list(brief.get("actions") or [])[:8],
        "brief_benchmark": str(brief.get("benchmark_summary") or "")[:400],
        "top_agents": [
            {
                "agent_id": str(a.get("agent_id") or ""),
                "accuracy_pct": a.get("accuracy_pct"),
                "edge_score": a.get("edge_score"),
                "posture": a.get("posture"),
                "preferred_horizon": a.get("preferred_horizon"),
            }
            for a in (brief.get("top_agents") or [])[:8]
            if isinstance(a, dict)
        ],
        "worker_updated_at": wstate.get("updated_at"),
    }


def format_text(data: dict[str, Any]) -> str:
    flags = data.get("flags") or {}
    mode = "LIVE AUTO" if (flags.get("live_trading") and flags.get("auto_execute") and not flags.get("dry_run")) else "not live"
    if flags.get("paused"):
        mode += " (paused)"
    if flags.get("sandbox"):
        mode += " SANDBOX"
    week_label = f"{data.get('week_start') or '-'} to {data.get('week_end') or '-'}"
    lines = [
        f"E*TRADE weekly summary — {data.get('generated_at')}",
        f"Host {data.get('host')}  Account {data.get('account_name')}",
        f"Week (ET) {week_label}",
        f"Snapshot { _dt(data.get('fetched_at')) }  source={data.get('source') or '-'}",
        "",
        "== Account ==",
        f"Equity {_usd(data.get('equity'))}   Cash/BP {_usd(data.get('cash_bp'))}",
        f"Positions {data.get('position_count')}   Market value {_usd(data.get('market_value'))}   Unrealized {_usd(data.get('unrealized_pl'))}",
        f"Total P/L {_usd(data.get('total_pl'))} ({_pct(data.get('total_pl_pct'))}) vs baseline {_usd(data.get('baseline_value'))}",
        f"Total avg P/L {_pct(data.get('total_avg_pl_pct'))}",
        (
            "Daily "
            f"{_pct((data.get('daily') or {}).get('actual_pct'))} "
            f"(target {_pct((data.get('daily') or {}).get('target_pct'))}, "
            f"{(data.get('daily') or {}).get('status') or '-'})"
        ),
        (
            "Weekly "
            f"{_pct((data.get('weekly') or {}).get('actual_pct'))}  "
            "Monthly "
            f"{_pct((data.get('monthly') or {}).get('actual_pct'))}"
        ),
        "",
        "== Daily this week (ET) ==",
    ]
    daily_rows = data.get("daily_rows") or []
    if not daily_rows:
        lines.append("(no daily closes)")
    for row in daily_rows:
        close = _usd(row.get("close")) if row.get("close") is not None else "-"
        pl = _usd(row.get("pl")) if row.get("pl") is not None else "-"
        pct = _pct(row.get("pl_pct")) if row.get("pl_pct") is not None else "-"
        pdt_n = int(row.get("pdt") or 0)
        pdt_bit = f"  PDT {pdt_n}"
        if row.get("pdt_symbols"):
            pdt_bit += f" ({', '.join(str(s) for s in row.get('pdt_symbols')[:6])})"
        elif pdt_n == 0:
            pdt_bit = ""
        src = row.get("source") or ""
        src_bit = f"  [{src}]" if src and src not in {"history", "plan"} else ""
        lines.append(
            f"{row.get('weekday') or '-'} {row.get('date')}  close {close:>10}  "
            f"day {pl:>10} ({pct}){pdt_bit}{src_bit}"
        )
    marked = [r for r in daily_rows if r.get("source") == "marks"]
    missing_days = [r for r in daily_rows if r.get("close") is None]
    if marked:
        days = ", ".join(f"{r.get('weekday')} {r.get('date')}" for r in marked)
        lines.append(
            f"Note: {days} filled from same lots x that day's marks. "
            "Broker equity history skipped while plan rebuild failed and quote publish was off."
        )
    if missing_days:
        days = ", ".join(f"{r.get('weekday')} {r.get('date')}" for r in missing_days)
        lines.append(f"Note: {days} still has no close (no marks / lots changed that session).")
    highlights = week_highlights(data)
    if highlights:
        lines += ["", "== Week highlights =="]
        lines.extend(highlights)
    daily_rows = data.get("daily_rows") or []
    lines += ["", "== Charts (character) =="]
    lines.extend(ascii_equity_chart(daily_rows))
    lines.append("")
    lines.extend(ascii_pl_chart(daily_rows))
    hold_chart = ascii_holdings_chart(data.get("holding_daily") or [])
    if hold_chart:
        lines.append("")
        lines.extend(hold_chart)
    holdings = data.get("holding_daily") or []
    if holdings:
        lines += ["", "== Holdings daily =="]
        for row in holdings:
            lines.append(
                f"{row.get('symbol'):<6}  last {_usd(row.get('last')):>10}  "
                f"day {_pct(row.get('day_chg_pct'))}  week {_pct(row.get('week_chg_pct'))}"
            )
    lines += [
        "",
        "== Worker ==",
        f"Mode {data.get('long_mode') or mode}   market_open={data.get('market_open')}",
        f"dry_run={flags.get('dry_run')} live_trading={flags.get('live_trading')} "
        f"auto_execute={flags.get('auto_execute')} day_trading={flags.get('day_trading')}",
        f"Agents {data.get('agent_count') or '-'}   worker { _dt(data.get('worker_updated_at')) }",
        f"Plan { _dt(data.get('plan_generated_at')) }  regime={data.get('regime_label') or '-'}",
        f"Plan note: {data.get('plan_error') or '-'}",
        f"PDT {data.get('pdt_count')} day trades in last 5 sessions {', '.join(data.get('pdt_window_days') or [])}",
        "",
        "== Positions ==",
    ]
    mv_total = _f(data.get("market_value"))
    for row in data.get("positions") or []:
        w = _weight_of(row, mv_total)
        wtxt = f"{w:5.1f}%" if w is not None else "    -"
        lines.append(
            f"{row.get('symbol'):<6}  qty {row.get('quantity'):>7}  "
            f"px {_usd(row.get('price')):>10}  mv {_usd(row.get('market_value')):>10}  "
            f"uPL {_usd(row.get('unrealized_pl')):>10}  wt {wtxt}"
        )
    lines += [
        "",
        f"== Open orders ({data.get('open_order_count') or 0} of {data.get('order_count') or 0} listed) ==",
        f"source={data.get('orders_source') or '-'}  {data.get('orders_message') or ''}".rstrip(),
    ]
    groups = data.get("open_groups") or []
    if not groups:
        lines.append("(none)")
    for g in groups[:24]:
        extra = f" x{g['count']}" if int(g.get("count") or 1) > 1 else ""
        lines.append(
            f"{g.get('symbol'):<6} {g.get('action'):<5} {g.get('price_type'):<12} "
            f"qty {g.get('quantity')}  stop {g.get('stop_price')} / limit {g.get('limit_price')}{extra}"
        )
    actions = data.get("brief_actions") or []
    if actions:
        lines += ["", "== Next session =="]
        for a in actions:
            lines.append(f"- {a}")
    summary = data.get("regime_summary")
    if summary:
        lines += ["", f"Regime: {summary}"]
    lines += ["", *term_key_lines()]
    lines += [
        "",
        "No tokens / account_id_key in this mail. Generated on GROMIT live runtime.",
    ]
    return "\n".join(lines) + "\n"


def format_subject(data: dict[str, Any]) -> str:
    eq = _usd(data.get("equity"))
    wpl = _pct((data.get("weekly") or {}).get("actual_pct"))
    dpl = _pct((data.get("daily") or {}).get("actual_pct"))
    return (
        f"E*TRADE weekly summary PDF {data.get('generated_at', '')}  "
        f"equity {eq}  week {wpl}  day {dpl}"
    )


def format_email_body(data: dict[str, Any], pdf_name: str) -> str:
    header = (
        f"Detailed weekly PDF attached: {pdf_name}\n"
        "Charts + daily rows + holdings + term key below if the attachment is stripped.\n\n"
    )
    return header + format_text(data)


TERM_KEY: list[tuple[str, str]] = [
    ("Equity", "Broker total account value (cash + longs, minus any debit/margin)."),
    ("Cash / BP", "Cash buying power. Not the same as equity."),
    ("Market value", "Sum of open lot market values at last marks."),
    ("Unrealized P/L (uPL)", "Mark minus per-share cost basis, times quantity. Not booked."),
    ("Baseline", "Starting equity after deposit/withdrawal adjustments. Total P/L is vs this."),
    ("Total P/L", "Equity minus baseline (external flows excluded when that flag is on)."),
    ("Total avg P/L", "Average percent P/L used by the primary goal, not one-day change."),
    ("Daily / Weekly / Monthly %", "Change vs the period target (+2% day / +12% week / +48% month)."),
    ("Day P/L", "That America/New_York calendar day's equity close minus the prior close."),
    ("Source: history / plan", "Live worker wrote a close (usually after a successful plan rebuild)."),
    ("Source: snapshot", "Latest broker snapshot used as that day's close."),
    ("Source: marks", "Gap fill: same lots times that day's last marks. Qty assumed unchanged."),
    ("Source: missing", "No close (no marks, or lots changed that session so fill was skipped)."),
    ("PDT", "House Pattern Day Trader-style cap (our software, not current FINRA/E*TRADE): day trades in the last 5 sessions. 3/3 blocks the day sleeve. Cash still T+1 / GFV."),
    ("Stop / Limit", "Protective sell prices on open orders (stop triggers; limit is the cap)."),
    ("dry_run", "Worker may propose tickets but will not submit them."),
    ("live_trading + auto_execute", "Live tickets allowed when dry_run is off and the worker is not paused."),
    ("Regime", "Fusion market-regime label (bull/bear/neutral) from the strategy plan."),
    ("Acc", "Walk-forward hit rate for an agent. Not live 24h scored accuracy."),
    ("Weight %", "That lot's market value as a share of total position market value."),
]


def _bar(frac: float, width: int = 16) -> str:
    n = int(round(max(0.0, min(1.0, float(frac))) * width))
    return "#" * n + "." * (width - n)


def _weight_of(row: dict[str, Any], mv_total: float | None) -> float | None:
    w = _f(row.get("weight_pct"))
    if w is not None:
        return w
    mv = _f(row.get("market_value"))
    if mv is None or not mv_total:
        return None
    return 100.0 * mv / mv_total


def week_highlights(data: dict[str, Any]) -> list[str]:
    """One-line facts derived from daily rows / holdings / lots."""
    lines: list[str] = []
    daily = [r for r in (data.get("daily_rows") or []) if isinstance(r, dict)]
    scored = [r for r in daily if _f(r.get("pl_pct")) is not None]
    if scored:
        best = max(scored, key=lambda r: float(r.get("pl_pct") or 0))
        worst = min(scored, key=lambda r: float(r.get("pl_pct") or 0))
        lines.append(
            f"Best day  {best.get('weekday')} {_pct(best.get('pl_pct'))}  close {_usd(best.get('close'))}"
        )
        lines.append(
            f"Worst day {worst.get('weekday')} {_pct(worst.get('pl_pct'))}  close {_usd(worst.get('close'))}"
        )
        first = next((r for r in daily if r.get("close") is not None), None)
        last = None
        for r in daily:
            if r.get("close") is not None:
                last = r
        if first and last and first.get("close") and last is not first:
            chg = float(last["close"]) - float(first["close"])
            pct = (chg / float(first["close"])) * 100.0
            lines.append(
                f"Week path {first.get('weekday')} {_usd(first.get('close'))} -> "
                f"{last.get('weekday')} {_usd(last.get('close'))}  ({_pct(pct)})"
            )
    holds = [h for h in (data.get("holding_daily") or []) if _f(h.get("week_chg_pct")) is not None]
    if holds:
        gainer = max(holds, key=lambda r: float(r.get("week_chg_pct") or 0))
        loser = min(holds, key=lambda r: float(r.get("week_chg_pct") or 0))
        lines.append(f"Best holding  {gainer.get('symbol')} week {_pct(gainer.get('week_chg_pct'))}")
        lines.append(f"Worst holding {loser.get('symbol')} week {_pct(loser.get('week_chg_pct'))}")
    pos = [p for p in (data.get("positions") or []) if isinstance(p, dict)]
    mv_total = _f(data.get("market_value"))
    if pos:
        top = max(pos, key=lambda r: abs(float(r.get("market_value") or 0)))
        w = _weight_of(top, mv_total)
        wtxt = f"{w:.1f}%" if w is not None else "-"
        lines.append(f"Largest lot {top.get('symbol')} {_usd(top.get('market_value'))} ({wtxt} of market value)")
        green = sum(1 for p in pos if (p.get("unrealized_pl") or 0) > 0)
        red = sum(1 for p in pos if (p.get("unrealized_pl") or 0) < 0)
        lines.append(f"Open lots {green} green / {red} red of {len(pos)}")
    eq = _f(data.get("equity"))
    if eq and mv_total:
        lines.append(
            f"Longs {_usd(mv_total)} vs equity {_usd(eq)}  "
            f"(implied cash/debit {_usd(eq - mv_total)})"
        )
    pdt = int(data.get("pdt_count") or 0)
    extra = " — day-trade sleeve blocked" if pdt >= 3 else ""
    lines.append(f"PDT used {pdt}/3 in last 5 sessions{extra}")
    daily_g = data.get("daily") or {}
    weekly_g = data.get("weekly") or {}
    if daily_g.get("target_pct") is not None:
        lines.append(
            f"Daily target {_pct(daily_g.get('target_pct'))}  remaining "
            f"{_pct(daily_g.get('remaining_pct'))}  status {daily_g.get('status') or '-'}"
        )
    if weekly_g.get("target_pct") is not None:
        lines.append(
            f"Weekly target {_pct(weekly_g.get('target_pct'))}  remaining "
            f"{_pct(weekly_g.get('remaining_pct'))}"
        )
    flows = _f(data.get("net_external_flows"))
    if flows is not None:
        lines.append(f"Net external flows {_usd(flows)} (deposits/withdrawals, not P/L)")
    return lines


def ascii_equity_chart(daily_rows: list[dict[str, Any]]) -> list[str]:
    vals = [_f(r.get("close")) for r in daily_rows]
    have = [v for v in vals if v is not None]
    if not have:
        return ["(no equity points)"]
    lo, hi = min(have), max(have)
    span = (hi - lo) or 1.0
    lines = [f"Equity close  min {_usd(lo)}  max {_usd(hi)}  (# = vs week range)"]
    for r, v in zip(daily_rows, vals):
        wd = str(r.get("weekday") or "-")
        if v is None:
            lines.append(f"{wd}  {'-':>10}  {'.' * 16}")
            continue
        lines.append(f"{wd}  {_usd(v):>10}  {_bar((v - lo) / span)}")
    return lines


def ascii_pl_chart(daily_rows: list[dict[str, Any]]) -> list[str]:
    pcts = [_f(r.get("pl_pct")) for r in daily_rows]
    peak = max((abs(p) for p in pcts if p is not None), default=0.0) or 1.0
    lines = ["Day P/L %  (# = size vs biggest |day| this week; + up / - down)"]
    for r, p in zip(daily_rows, pcts):
        wd = str(r.get("weekday") or "-")
        if p is None:
            lines.append(f"{wd}  {'-':>8}")
            continue
        sign = "+" if p >= 0 else "-"
        lines.append(f"{wd}  {_pct(p):>8}  {sign}{_bar(abs(p) / peak)}")
    return lines


def ascii_holdings_chart(holdings: list[dict[str, Any]], *, limit: int = 8) -> list[str]:
    rows = [h for h in holdings if _f(h.get("week_chg_pct")) is not None][:limit]
    if not rows:
        return []
    peak = max((abs(_f(r.get("week_chg_pct")) or 0.0) for r in rows), default=0.0) or 1.0
    lines = ["Holdings week %  (top movers; + up / - down)"]
    for r in rows:
        p = float(_f(r.get("week_chg_pct")) or 0.0)
        sign = "+" if p >= 0 else "-"
        lines.append(
            f"{str(r.get('symbol') or '-'):<6} {_pct(p):>8}  {sign}{_bar(abs(p) / peak)}"
        )
    return lines


def term_key_lines() -> list[str]:
    lines = ["== Key / definitions =="]
    for term, meaning in TERM_KEY:
        lines.append(f"{term}: {meaning}")
    return lines


def _drawing_equity_line(daily_rows: list[dict[str, Any]], width: float, height: float):
    from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, Rect, String
    from reportlab.lib import colors

    d = Drawing(width, height)
    d.add(
        Rect(
            0,
            0,
            width,
            height,
            fillColor=colors.HexColor("#f8fafc"),
            strokeColor=colors.HexColor("#cbd5e1"),
            strokeWidth=0.4,
        )
    )
    pts: list[tuple[int, float]] = []
    for i, r in enumerate(daily_rows):
        c = _f(r.get("close"))
        if c is not None:
            pts.append((i, c))
    if not pts:
        d.add(
            String(
                width / 2,
                height / 2,
                "no equity points",
                textAnchor="middle",
                fontSize=8,
                fillColor=colors.HexColor("#64748b"),
            )
        )
        return d
    vals = [v for _, v in pts]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.12 if hi != lo else max(abs(hi) * 0.01, 1.0)
    lo -= pad
    hi += pad
    left, right, bottom, top = 50, width - 10, 22, height - 16
    n = max(len(daily_rows) - 1, 1)

    def xy(i: int, v: float) -> tuple[float, float]:
        x = left + (i / n) * (right - left)
        y = bottom + ((v - lo) / (hi - lo)) * (top - bottom)
        return x, y

    for k in range(4):
        frac = k / 3.0
        y = bottom + frac * (top - bottom)
        v = lo + frac * (hi - lo)
        d.add(Line(left, y, right, y, strokeColor=colors.HexColor("#e2e8f0"), strokeWidth=0.3))
        d.add(String(4, y - 3, f"${v:,.0f}", fontSize=6.5, fillColor=colors.HexColor("#64748b")))
    flat: list[float] = []
    for i, v in pts:
        x, y = xy(i, v)
        flat.extend([x, y])
    if len(pts) >= 2:
        d.add(PolyLine(flat, strokeColor=colors.HexColor("#1e3a5f"), strokeWidth=1.6))
    for i, v in pts:
        x, y = xy(i, v)
        d.add(
            Circle(
                x,
                y,
                3,
                fillColor=colors.HexColor("#2563eb"),
                strokeColor=colors.white,
                strokeWidth=0.6,
            )
        )
    for i, r in enumerate(daily_rows):
        x, _ = xy(i, lo)
        d.add(
            String(
                x,
                6,
                str(r.get("weekday") or ""),
                textAnchor="middle",
                fontSize=7,
                fillColor=colors.HexColor("#334155"),
            )
        )
    d.add(
        String(
            left,
            height - 12,
            "Equity close (ET)",
            fontSize=7.5,
            fillColor=colors.HexColor("#1e3a5f"),
        )
    )
    return d


def _drawing_pl_bars(daily_rows: list[dict[str, Any]], width: float, height: float):
    from reportlab.graphics.shapes import Drawing, Line, Rect, String
    from reportlab.lib import colors

    d = Drawing(width, height)
    d.add(
        Rect(
            0,
            0,
            width,
            height,
            fillColor=colors.HexColor("#f8fafc"),
            strokeColor=colors.HexColor("#cbd5e1"),
            strokeWidth=0.4,
        )
    )
    pcts = [_f(r.get("pl_pct")) for r in daily_rows]
    have = [p for p in pcts if p is not None]
    left, right, bottom, top = 50, width - 10, 22, height - 16
    if not have:
        d.add(
            String(
                width / 2,
                height / 2,
                "no day P/L",
                textAnchor="middle",
                fontSize=8,
                fillColor=colors.HexColor("#64748b"),
            )
        )
        return d
    mn, mx = min(have), max(have)
    if mn > 0:
        mn = 0.0
    if mx < 0:
        mx = 0.0
    pad = max(abs(mx), abs(mn), 0.2) * 0.18
    mn -= pad
    mx += pad
    span = mx - mn or 1.0

    def y_of(p: float) -> float:
        return bottom + ((p - mn) / span) * (top - bottom)

    zero = y_of(0.0)
    d.add(Line(left, zero, right, zero, strokeColor=colors.HexColor("#94a3b8"), strokeWidth=0.5))
    count = max(len(daily_rows), 1)
    bar_w = (right - left) / count * 0.5
    for i, r in enumerate(daily_rows):
        p = pcts[i]
        x = left + (i + 0.5) / count * (right - left)
        d.add(
            String(
                x,
                6,
                str(r.get("weekday") or ""),
                textAnchor="middle",
                fontSize=7,
                fillColor=colors.HexColor("#334155"),
            )
        )
        if p is None:
            continue
        y1 = y_of(p)
        top_y = max(zero, y1)
        bot_y = min(zero, y1)
        color = colors.HexColor("#16a34a") if p >= 0 else colors.HexColor("#dc2626")
        d.add(
            Rect(
                x - bar_w / 2,
                bot_y,
                bar_w,
                max(top_y - bot_y, 1.2),
                fillColor=color,
                strokeColor=None,
            )
        )
        label_y = top_y + 3 if p >= 0 else bot_y - 9
        d.add(
            String(
                x,
                label_y,
                f"{p:+.2f}%",
                textAnchor="middle",
                fontSize=6.5,
                fillColor=color,
            )
        )
    d.add(
        String(
            left,
            height - 12,
            "Day P/L %",
            fontSize=7.5,
            fillColor=colors.HexColor("#1e3a5f"),
        )
    )
    return d


def _drawing_holdings(holdings: list[dict[str, Any]], width: float, height: float, *, limit: int = 8):
    from reportlab.graphics.shapes import Drawing, Line, Rect, String
    from reportlab.lib import colors

    rows = [h for h in holdings if _f(h.get("week_chg_pct")) is not None][:limit]
    d = Drawing(width, height)
    d.add(
        Rect(
            0,
            0,
            width,
            height,
            fillColor=colors.HexColor("#f8fafc"),
            strokeColor=colors.HexColor("#cbd5e1"),
            strokeWidth=0.4,
        )
    )
    left, right, top = 58, width - 12, height - 16
    if not rows:
        d.add(
            String(
                width / 2,
                height / 2,
                "no holdings",
                textAnchor="middle",
                fontSize=8,
                fillColor=colors.HexColor("#64748b"),
            )
        )
        return d
    peak = max((abs(float(_f(r.get("week_chg_pct")) or 0.0)) for r in rows), default=1.0) or 1.0
    row_h = min(18.0, (top - 10) / max(len(rows), 1))
    mid = (left + right) / 2
    d.add(Line(mid, 8, mid, top - 4, strokeColor=colors.HexColor("#94a3b8"), strokeWidth=0.4))
    for i, r in enumerate(rows):
        p = float(_f(r.get("week_chg_pct")) or 0.0)
        y = top - 8 - (i + 1) * row_h
        bar_max = (right - left) / 2 * 0.92
        bw = bar_max * (abs(p) / peak)
        color = colors.HexColor("#16a34a") if p >= 0 else colors.HexColor("#dc2626")
        if p >= 0:
            d.add(Rect(mid, y, bw, row_h * 0.55, fillColor=color, strokeColor=None))
        else:
            d.add(Rect(mid - bw, y, bw, row_h * 0.55, fillColor=color, strokeColor=None))
        d.add(
            String(
                6,
                y + 1,
                str(r.get("symbol") or "-"),
                fontSize=7,
                fillColor=colors.HexColor("#334155"),
            )
        )
        d.add(
            String(
                right,
                y + 1,
                _pct(p),
                textAnchor="end",
                fontSize=6.5,
                fillColor=color,
            )
        )
    d.add(
        String(
            left,
            height - 12,
            "Holdings week %",
            fontSize=7.5,
            fillColor=colors.HexColor("#1e3a5f"),
        )
    )
    return d


def _xml(s: Any) -> str:
    return (
        str(s if s is not None else "-")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_summary_pdf(data: dict[str, Any], path: Path) -> Path:
    """Detailed trader summary PDF (reportlab). No tokens / account_id_key."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        HRFlowable,
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    base = getSampleStyleSheet()
    title = ParagraphStyle("T", parent=base["Title"], fontSize=16, leading=20, spaceAfter=6)
    h = ParagraphStyle(
        "H",
        parent=base["Heading2"],
        fontSize=11,
        leading=14,
        spaceBefore=10,
        spaceAfter=4,
        textColor=colors.HexColor("#1e3a5f"),
    )
    body = ParagraphStyle("B", parent=base["Normal"], fontSize=8.5, leading=11, spaceAfter=3)
    td = ParagraphStyle("TD", parent=base["Normal"], fontSize=7.5, leading=9.5)
    th = ParagraphStyle(
        "TH",
        parent=base["Normal"],
        fontSize=7.5,
        leading=9.5,
        textColor=colors.white,
        fontName="Helvetica-Bold",
    )
    note = ParagraphStyle(
        "N", parent=base["Normal"], fontSize=8, leading=10, textColor=colors.HexColor("#64748b")
    )

    def cell(text: Any, header: bool = False) -> Paragraph:
        return Paragraph(_xml(text), th if header else td)

    def grid(rows: list[list[Any]], widths: list[float]) -> Table:
        data_rows: list[list[Paragraph]] = []
        for i, row in enumerate(rows):
            data_rows.append([cell(c, header=(i == 0)) for c in row])
        t = Table(data_rows, colWidths=widths, repeatRows=1)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.HexColor("#eef2ff")]),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        return t

    flags = data.get("flags") or {}
    daily = data.get("daily") or {}
    week_label = f"{data.get('week_start') or '-'} to {data.get('week_end') or '-'}"
    story: list[Any] = [
        Paragraph("E*TRADE weekly summary", title),
        Paragraph(
            f"{_xml(data.get('generated_at'))} · {_xml(data.get('host'))} · {_xml(data.get('account_name'))}",
            note,
        ),
        Paragraph(f"Week (ET) {_xml(week_label)}", note),
        Paragraph(
            f"Snapshot {_xml(_dt(data.get('fetched_at')))} · source={_xml(data.get('source') or '-')}",
            note,
        ),
        HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#cbd5e1"), spaceBefore=4, spaceAfter=8),
        Paragraph("Account", h),
        grid(
            [
                ["Metric", "Value"],
                ["Equity", _usd(data.get("equity"))],
                ["Cash / BP", _usd(data.get("cash_bp"))],
                ["Positions", data.get("position_count")],
                ["Market value", _usd(data.get("market_value"))],
                ["Unrealized P/L", _usd(data.get("unrealized_pl"))],
                ["Total P/L", f"{_usd(data.get('total_pl'))} ({_pct(data.get('total_pl_pct'))})"],
                ["Total avg P/L", _pct(data.get("total_avg_pl_pct"))],
                ["Baseline", _usd(data.get("baseline_value"))],
                ["Daily", f"{_pct(daily.get('actual_pct'))}  target {_pct(daily.get('target_pct'))}  {daily.get('status') or '-'}"],
                ["Weekly", _pct((data.get("weekly") or {}).get("actual_pct"))],
                ["Monthly", _pct((data.get("monthly") or {}).get("actual_pct"))],
            ],
            [2.2 * inch, 5.0 * inch],
        ),
        Paragraph("Daily this week (ET)", h),
    ]
    day_rows = [["Day", "Date", "Close", "Day P/L", "Day %", "PDT", "Source"]]
    for row in data.get("daily_rows") or []:
        pdt_n = int(row.get("pdt") or 0)
        pdt_txt = str(pdt_n)
        if row.get("pdt_symbols"):
            pdt_txt += " " + ",".join(str(s) for s in row.get("pdt_symbols")[:4])
        day_rows.append(
            [
                row.get("weekday"),
                row.get("date"),
                _usd(row.get("close")) if row.get("close") is not None else "-",
                _usd(row.get("pl")) if row.get("pl") is not None else "-",
                _pct(row.get("pl_pct")) if row.get("pl_pct") is not None else "-",
                pdt_txt,
                row.get("source") or "-",
            ]
        )
    if len(day_rows) == 1:
        day_rows.append(["(none)", "-", "-", "-", "-", "-", "-"])
    story.append(
        grid(day_rows, [0.7 * inch, 1.1 * inch, 1.1 * inch, 1.1 * inch, 0.9 * inch, 1.3 * inch, 1.0 * inch])
    )
    highlights = week_highlights(data)
    if highlights:
        story.append(Paragraph("Week highlights", h))
        for line in highlights:
            story.append(Paragraph(_xml(line), body))
    daily_for_charts = [r for r in (data.get("daily_rows") or []) if isinstance(r, dict)]
    chart_w = 7.2 * inch
    chart_bits: list[Any] = [
        Paragraph("Charts", h),
        Paragraph(
            "Equity close line, day P/L bars, holdings week %. Character versions of the same "
            "charts are in the email body.",
            note,
        ),
        _drawing_equity_line(daily_for_charts, chart_w, 2.05 * inch),
        Spacer(1, 8),
        _drawing_pl_bars(daily_for_charts, chart_w, 1.85 * inch),
    ]
    holdings = data.get("holding_daily") or []
    if holdings:
        chart_bits += [
            Spacer(1, 8),
            _drawing_holdings(holdings, chart_w, 2.15 * inch),
        ]
    story.append(KeepTogether(chart_bits))
    if holdings:
        story.append(Paragraph("Holdings daily", h))
        h_rows = [["Symbol", "Last", "Day %", "Week %"]]
        for row in holdings:
            h_rows.append(
                [
                    row.get("symbol"),
                    _usd(row.get("last")),
                    _pct(row.get("day_chg_pct")),
                    _pct(row.get("week_chg_pct")),
                ]
            )
        story.append(grid(h_rows, [1.4 * inch, 1.6 * inch, 1.6 * inch, 1.6 * inch]))
    story += [
        Paragraph("Worker", h),
        Paragraph(
            f"Mode {_xml(data.get('long_mode') or '-')} · market_open={_xml(data.get('market_open'))} · "
            f"dry_run={flags.get('dry_run')} live_trading={flags.get('live_trading')} "
            f"auto_execute={flags.get('auto_execute')} day_trading={flags.get('day_trading')}",
            body,
        ),
        Paragraph(
            f"Agents {_xml(data.get('agent_count') or '-')} · worker {_xml(_dt(data.get('worker_updated_at')))} · "
            f"plan {_xml(_dt(data.get('plan_generated_at')))} · regime={_xml(data.get('regime_label') or '-')}",
            body,
        ),
        Paragraph(f"Plan note: {_xml(data.get('plan_error') or '-')}", body),
        Paragraph(
            f"PDT {data.get('pdt_count')} day trades in last 5 sessions "
            f"{_xml(', '.join(data.get('pdt_window_days') or []))}",
            body,
        ),
    ]
    pdt_map = data.get("pdt_by_date") or {}
    if pdt_map:
        pdt_rows = [["Date", "Day trades"]]
        for day in sorted(str(k) for k in pdt_map):
            pdt_rows.append([day, pdt_map.get(day)])
        story.append(grid(pdt_rows, [3.6 * inch, 3.6 * inch]))
    story.append(Paragraph("Positions", h))
    mv_total = _f(data.get("market_value"))
    pos_rows = [["Symbol", "Qty", "Price", "Mkt value", "Wt %", "Cost", "Unrealized"]]
    for row in data.get("positions") or []:
        w = _weight_of(row, mv_total)
        pos_rows.append(
            [
                row.get("symbol"),
                row.get("quantity"),
                _usd(row.get("price")),
                _usd(row.get("market_value")),
                f"{w:.1f}%" if w is not None else "-",
                _usd(row.get("cost_basis")),
                _usd(row.get("unrealized_pl")),
            ]
        )
    if len(pos_rows) == 1:
        pos_rows.append(["(none)", "-", "-", "-", "-", "-", "-"])
    story.append(
        grid(pos_rows, [0.85 * inch, 0.7 * inch, 0.95 * inch, 1.15 * inch, 0.7 * inch, 0.95 * inch, 1.15 * inch])
    )
    story.append(
        Paragraph(
            f"Open orders ({data.get('open_order_count') or 0} of {data.get('order_count') or 0} listed) · "
            f"source={_xml(data.get('orders_source') or '-')} {_xml(data.get('orders_message') or '')}",
            h,
        )
    )
    ord_rows = [["Symbol", "Action", "Type", "Qty", "Stop", "Limit", "x"]]
    for g in data.get("open_groups") or []:
        ord_rows.append(
            [
                g.get("symbol"),
                g.get("action"),
                g.get("price_type"),
                g.get("quantity"),
                g.get("stop_price"),
                g.get("limit_price"),
                g.get("count") or 1,
            ]
        )
    if len(ord_rows) == 1:
        ord_rows.append(["(none)", "-", "-", "-", "-", "-", "-"])
    story.append(
        grid(ord_rows, [0.9 * inch, 0.8 * inch, 1.2 * inch, 0.7 * inch, 1.0 * inch, 1.0 * inch, 0.5 * inch])
    )
    actions = data.get("brief_actions") or []
    if actions or data.get("brief_benchmark") or data.get("top_agents"):
        story.append(Paragraph("Next session", h))
        if data.get("brief_for"):
            story.append(Paragraph(f"For {_xml(data.get('brief_for'))}", body))
        if data.get("brief_benchmark"):
            story.append(Paragraph(_xml(data.get("brief_benchmark")), body))
        for a in actions:
            story.append(Paragraph(f"• {_xml(a)}", body))
        agents = data.get("top_agents") or []
        if agents:
            ag_rows = [["Agent", "Acc %", "Edge", "Posture", "Horizon"]]
            for a in agents:
                ag_rows.append(
                    [
                        a.get("agent_id"),
                        a.get("accuracy_pct"),
                        a.get("edge_score"),
                        a.get("posture"),
                        a.get("preferred_horizon"),
                    ]
                )
            story.append(
                grid(ag_rows, [1.8 * inch, 0.9 * inch, 0.9 * inch, 1.2 * inch, 1.2 * inch])
            )
    if data.get("regime_summary"):
        story.append(Paragraph("Regime", h))
        story.append(Paragraph(_xml(data.get("regime_summary")), body))
    story.append(Paragraph("Key / definitions", h))
    key_rows = [["Term", "Meaning"]]
    for term, meaning in TERM_KEY:
        key_rows.append([term, meaning])
    story.append(grid(key_rows, [2.0 * inch, 5.2 * inch]))
    story += [
        Spacer(1, 10),
        Paragraph("No tokens / account_id_key in this PDF. Generated on GROMIT live runtime.", note),
    ]
    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        title="E*TRADE weekly summary",
        author="GROMIT Finance",
        pageCompression=0,
    )
    doc.build(story)
    return path


MAX_COMPOSE_URL = 6500
BODY_INK_MIN = 0.12


def compose_url(to: str, subject: str, body: str) -> str:
    """Gmail compose deep-link. Include body= when the URL stays short enough."""
    base = (
        "https://mail.google.com/mail/u/0/?view=cm&fs=1&tf=1&to="
        + urllib.parse.quote(to)
        + "&su="
        + urllib.parse.quote(subject[:120])
    )
    encoded_body = urllib.parse.quote(body)
    candidate = base + "&body=" + encoded_body
    if len(candidate) <= MAX_COMPOSE_URL:
        return candidate
    return base


def body_ink_ratio(image: Any, *, y0_frac: float = 0.30, y1_frac: float = 0.78) -> float:
    """Fraction of non-near-white pixels in the compose body band."""
    try:
        w, h = image.size
    except Exception:
        return 0.0
    y0 = max(0, int(h * y0_frac))
    y1 = min(h, int(h * y1_frac))
    if w < 10 or y1 <= y0:
        return 0.0
    x0, x1 = int(w * 0.08), int(w * 0.92)
    if x1 <= x0:
        return 0.0
    band = image.crop((x0, y0, x1, y1)).resize((80, 48))
    ink = 0
    total = 0
    for px in band.getdata():
        r, g, b = px[:3]
        total += 1
        if r < 235 or g < 235 or b < 235:
            ink += 1
    return ink / total if total else 0.0


def body_looks_filled(image: Any) -> bool:
    # Empty Gmail compose (placeholder "Help me write") measured ~0.03 ink.
    return body_ink_ratio(image) >= BODY_INK_MIN


def _tap_escape() -> None:
    user32 = ctypes.windll.user32
    vk = 0x1B
    keyup = 0x0002
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.04)
    user32.keybd_event(vk, 0, keyup, 0)


def _token_has_send(path: Path) -> bool:
    raw = _load_json(path)
    scopes = raw.get("scopes") or []
    if isinstance(scopes, str):
        scopes = scopes.split()
    blob = " ".join(str(s) for s in scopes) + " " + json.dumps(raw)
    return "gmail.send" in blob or "mail.google.com" in blob


def send_via_gmail_api(
    to: str, subject: str, body: str, pdf_path: Path | None = None
) -> dict[str, Any]:
    token_path = LINK_DIR / "token.json"
    if not token_path.is_file() or not _token_has_send(token_path):
        return {"ok": False, "error": "gmail.send scope missing (readonly token only)"}
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except Exception as exc:
        return {"ok": False, "error": f"gmail libs: {exc}"}
    try:
        creds = Credentials.from_authorized_user_file(str(token_path), list(SEND_SCOPES))
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        if not creds or not creds.valid:
            return {"ok": False, "error": "gmail token not valid"}
        msg = EmailMessage()
        msg["To"] = to
        msg["From"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        if pdf_path and Path(pdf_path).is_file():
            msg.add_attachment(
                Path(pdf_path).read_bytes(),
                maintype="application",
                subtype="pdf",
                filename=Path(pdf_path).name,
            )
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip("=")
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {
            "ok": True,
            "method": "gmail_api",
            "id": sent.get("id"),
            "attached": bool(pdf_path and Path(pdf_path).is_file()),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:400]}


# --- Chrome DevTools (optional; used when we launched Chrome with 9222) ---


def _ws_connect(url: str, timeout: float = 15.0) -> socket.socket:
    from urllib.parse import urlparse

    u = urlparse(url)
    host = u.hostname or "127.0.0.1"
    port = int(u.port or 80)
    path = u.path or "/"
    if u.query:
        path += "?" + u.query
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.sendall(
        (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).encode("ascii")
    )
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    if b"101" not in buf.split(b"\r\n", 1)[0]:
        sock.close()
        raise RuntimeError("CDP websocket upgrade failed")
    return sock


def _ws_send(sock: socket.socket, text: str) -> None:
    data = text.encode("utf-8")
    header = bytearray()
    header.append(0x81)
    n = len(data)
    mask = os.urandom(4)
    if n < 126:
        header.append(0x80 | n)
    elif n < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack(">H", n))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack(">Q", n))
    header.extend(mask)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    sock.sendall(header + masked)


def _ws_recv(sock: socket.socket) -> str:
    def read_exact(n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise RuntimeError("CDP websocket closed")
            buf += chunk
        return buf

    while True:
        hdr = read_exact(2)
        opcode = hdr[0] & 0x0F
        length = hdr[1] & 0x7F
        masked = bool(hdr[1] & 0x80)
        if length == 126:
            length = struct.unpack(">H", read_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", read_exact(8))[0]
        mask = read_exact(4) if masked else b""
        payload = read_exact(length)
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        if opcode == 0x9:
            # ping -> pong
            pong = bytearray([0x8A, 0x80 | min(len(payload), 125)])
            if len(payload) < 126:
                m = os.urandom(4)
                pong.extend(m)
                pong.extend(bytes(b ^ m[i % 4] for i, b in enumerate(payload)))
                sock.sendall(pong)
            continue
        if opcode == 0x8:
            raise RuntimeError("CDP websocket close")
        if opcode == 0x1:
            return payload.decode("utf-8", errors="replace")
        if opcode == 0xA:
            continue
        return payload.decode("utf-8", errors="replace")


class _Cdp:
    def __init__(self, ws_url: str) -> None:
        self.sock = _ws_connect(ws_url)
        self.sock.settimeout(20)
        self._n = 0

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._n += 1
        msg_id = self._n
        payload: dict[str, Any] = {"id": msg_id, "method": method}
        if params:
            payload["params"] = params
        _ws_send(self.sock, json.dumps(payload))
        deadline = time.time() + 20
        while time.time() < deadline:
            raw = _ws_recv(self.sock)
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if data.get("id") == msg_id:
                if data.get("error"):
                    raise RuntimeError(str(data["error"])[:300])
                result = data.get("result")
                return result if isinstance(result, dict) else {}
        raise TimeoutError(method)

    def eval(self, expression: str) -> Any:
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        inner = result.get("result") if isinstance(result.get("result"), dict) else {}
        return inner.get("value")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def _cdp_available() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def _chrome_exe() -> Path | None:
    from open_chrome_url import chrome_exe

    return chrome_exe()


def _start_chrome_cdp(url: str) -> None:
    chrome = _chrome_exe()
    if chrome is None:
        raise RuntimeError("chrome.exe not found")
    subprocess.Popen(
        [str(chrome), f"--remote-debugging-port={CDP_PORT}", "--profile-directory=Default", url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_cdp(timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _cdp_available():
            return True
        time.sleep(0.4)
    return False


def _cdp_pages() -> list[dict[str, Any]]:
    with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data if isinstance(data, list) else []


def send_via_chrome_cdp(
    to: str, subject: str, body: str, pdf_path: Path | None = None
) -> dict[str, Any]:
    compose = compose_url(to, subject, body)
    started = False
    from open_chrome_url import chrome_running

    if not _cdp_available():
        if chrome_running():
            return {"ok": False, "error": "chrome running without CDP 9222"}
        _start_chrome_cdp(compose)
        started = True
        if not _wait_cdp():
            return {"ok": False, "error": "Chrome CDP 9222 did not come up"}
    else:
        try:
            urllib.request.urlopen(
                "http://127.0.0.1:%d/json/new?%s" % (CDP_PORT, urllib.parse.quote(compose, safe="")),
                timeout=8,
            ).read()
        except Exception:
            pass

    page = None
    for _ in range(25):
        pages = _cdp_pages()
        for p in pages:
            ws = str(p.get("webSocketDebuggerUrl") or "")
            u = str(p.get("url") or "")
            t = str(p.get("title") or "")
            if not ws:
                continue
            if "mail.google.com" in u or "compose" in u.lower() or "gmail" in t.lower():
                page = p
                break
        if page:
            break
        time.sleep(0.4)
    if page is None:
        return {"ok": False, "error": "no Gmail tab on CDP", "started": started}

    cdp = _Cdp(str(page["webSocketDebuggerUrl"]))
    try:
        cdp.call("Runtime.enable")
        js_body = json.dumps(body)
        fill = f"""
(async () => {{
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const text = {js_body};
  for (let i = 0; i < 40; i++) {{
    const t = (document.body && document.body.innerText) || '';
    if (/sign in|couldn't sign you in/i.test(t) && !/inbox|compose|message body/i.test(t)) {{
      return 'need-login';
    }}
    const box = document.querySelector('div[aria-label="Message Body"]')
      || document.querySelector('div[role="textbox"][aria-label*="Message Body"]')
      || document.querySelector('div[contenteditable="true"][g_editable="true"]')
      || document.querySelector('div[aria-label*="Body"][contenteditable="true"]');
    if (box) {{
      box.focus();
      box.innerText = text;
      return 'filled';
    }}
    await sleep(400);
  }}
  return 'no-body';
}})()
"""
        result = cdp.eval(fill)
        if result != "filled":
            return {"ok": False, "error": str(result), "started": started}
        attached = False
        if pdf_path and Path(pdf_path).is_file():
            click_attach = """
(() => {
  const btn = document.querySelector('[aria-label="Attach files"]')
    || document.querySelector('[data-tooltip="Attach files"]')
    || document.querySelector('div[command="Files"]');
  if (!btn) return 'no-attach';
  btn.click();
  return 'clicked-attach';
})()
"""
            att = cdp.eval(click_attach)
            if att == "clicked-attach":
                attached = _fill_open_dialog(str(Path(pdf_path).resolve()), timeout=10.0)
            if not attached:
                try:
                    cdp.call("DOM.enable")
                    doc = cdp.call("DOM.getDocument", {"depth": 0})
                    root_id = ((doc.get("root") or {}).get("nodeId"))
                    if root_id:
                        found = cdp.call(
                            "DOM.querySelector",
                            {"nodeId": root_id, "selector": "input[type=file]"},
                        )
                        node_id = found.get("nodeId") if isinstance(found, dict) else 0
                        if node_id:
                            cdp.call(
                                "DOM.setFileInputFiles",
                                {"nodeId": node_id, "files": [str(Path(pdf_path).resolve())]},
                            )
                            attached = True
                except Exception:
                    attached = False
            time.sleep(1.2)
        send_js = """
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const buttons = [...document.querySelectorAll('div[role="button"]')];
  const send = buttons.find((el) => {
    const a = ((el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('data-tooltip') || '')).toLowerCase();
    return a.startsWith('send') && !a.includes('schedule');
  });
  if (!send) return 'no-send';
  send.click();
  await sleep(800);
  const after = (document.body && document.body.innerText) || '';
  if (/message sent|sending/i.test(after)) return 'sent';
  return 'clicked-send';
})()
"""
        sent = cdp.eval(send_js)
        if sent in {"sent", "clicked-send"}:
            return {
                "ok": True,
                "method": "chrome_cdp",
                "result": sent,
                "started": started,
                "attached": attached,
            }
        return {"ok": False, "error": str(sent), "started": started, "attached": attached}
    finally:
        cdp.close()


def _gmail_windows():
    from chrome_oauth_ui import list_chrome_windows

    compose = []
    gmail = []
    for w in list_chrome_windows():
        title = (w.title or "").lower()
        if "compose" in title:
            compose.append(w)
        elif "gmail" in title or "inbox" in title:
            gmail.append(w)
    return compose, gmail


def _find_gmail_send_button(image) -> Any:
    from chrome_oauth_ui import _horizontal_runs, _merge_band

    def pred(r: int, g: int, b: int) -> bool:
        # Gmail Send pill is saturated Google blue.
        return b >= 180 and g >= 70 and r <= 90 and (b - r) >= 100

    w, h = image.size
    runs = _horizontal_runs(
        image,
        pred,
        min_width=max(48, w // 18),
        max_width=max(220, w // 4),
        y0=int(h * 0.72),
        y1=h,
        step=1,
    )
    return _merge_band(runs, min_rows=12, max_gap=3)


def _fill_open_dialog(path: str, timeout: float = 8.0) -> bool:
    """Put an absolute path into the Chrome/Windows Open file dialog and confirm."""
    user32 = ctypes.windll.user32
    user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.FindWindowExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
    user32.FindWindowExW.restype = ctypes.c_void_p
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_void_p]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    WM_SETTEXT = 0x000C
    BM_CLICK = 0x00F5
    deadline = time.time() + timeout
    hwnd = None
    while time.time() < deadline:
        for title in ("Open", "Open File", "Open files"):
            hwnd = user32.FindWindowW("#32770", title)
            if hwnd:
                break
        if hwnd:
            break
        time.sleep(0.2)
    if not hwnd:
        return False
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.15)
    comboex = user32.FindWindowExW(hwnd, None, "ComboBoxEx32", None)
    combo = user32.FindWindowExW(comboex, None, "ComboBox", None) if comboex else None
    edit = user32.FindWindowExW(combo, None, "Edit", None) if combo else None
    if not edit:
        combo = user32.FindWindowExW(hwnd, None, "ComboBox", None)
        edit = user32.FindWindowExW(combo, None, "Edit", None) if combo else None
    if not edit:
        edit = user32.FindWindowExW(hwnd, None, "Edit", None)
    if not edit:
        return False
    buf = ctypes.create_unicode_buffer(path)
    user32.SendMessageW(edit, WM_SETTEXT, 0, ctypes.cast(buf, ctypes.c_void_p))
    time.sleep(0.12)
    btn = user32.FindWindowExW(hwnd, None, "Button", "&Open")
    if not btn:
        btn = user32.FindWindowExW(hwnd, None, "Button", "Open")
    if btn:
        user32.SendMessageW(btn, BM_CLICK, 0, 0)
    else:
        from chrome_oauth_ui import tap_enter

        tap_enter()
    time.sleep(0.8)
    still = user32.FindWindowW("#32770", "Open")
    return not bool(still)


def _click_gmail_attach(win: Any, image: Any) -> bool:
    from chrome_oauth_ui import click_window

    box = _find_gmail_send_button(image)
    if box is None:
        click_window(win, 118, max(win.height - 52, 40))
        return True
    # Paperclip sits on the compose toolbar to the right of Send / Aa.
    click_window(win, box.x1 + 108, box.cy)
    return True


def _open_dialog_hwnd() -> int:
    user32 = ctypes.windll.user32
    user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    user32.FindWindowW.restype = ctypes.c_void_p
    for title in ("Open", "Open File", "Open files"):
        hwnd = user32.FindWindowW("#32770", title)
        if hwnd:
            return int(hwnd)
    return 0


def write_clipboard_files(paths: list[Path]) -> bool:
    """Put files on the Windows clipboard as a file drop list (STA PowerShell)."""
    abs_paths = [str(Path(p).resolve()) for p in paths if Path(p).is_file()]
    if not abs_paths:
        return False
    quoted = ",".join("'" + p.replace("'", "''") + "'" for p in abs_paths)
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$col = New-Object System.Collections.Specialized.StringCollection; "
        f"foreach ($p in @({quoted})) {{ [void]$col.Add($p) }}; "
        "[System.Windows.Forms.Clipboard]::SetFileDropList($col); "
        "if ([System.Windows.Forms.Clipboard]::ContainsFileDropList()) { 'OK' } else { 'FAIL' }"
    )
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception:
        return False
    return "OK" in (proc.stdout or "")


def _uia_click_attach() -> bool:
    """Invoke Gmail 'Attach files' via UI Automation if Chrome exposes it."""
    script = (
        "Add-Type -AssemblyName UIAutomationClient; "
        "$root = [System.Windows.Automation.AutomationElement]::RootElement; "
        "$trueCond = [System.Windows.Automation.Condition]::TrueCondition; "
        "$windows = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $trueCond); "
        "$names = @('Attach files','Attach Files','Attach'); "
        "foreach ($w in $windows) { "
        "  $title = $w.Current.Name; "
        "  if ($title -notmatch 'Gmail|Compose Mail|Chrome') { continue } "
        "  foreach ($n in $names) { "
        "    $cond = New-Object System.Windows.Automation.PropertyCondition("
        "      [System.Windows.Automation.AutomationElement]::NameProperty, $n); "
        "    $el = $w.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond); "
        "    if ($el) { "
        "      try { "
        "        $pat = $el.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern); "
        "        $pat.Invoke(); 'CLICKED'; exit 0 "
        "      } catch { } "
        "    } "
        "  } "
        "}; "
        "'NOTFOUND'"
    )
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            timeout=25,
        )
    except Exception:
        return False
    return "CLICKED" in (proc.stdout or "")


def attach_pdf_via_chrome(win: Any, image: Any, pdf_path: Path) -> dict[str, Any]:
    """Attach a PDF to the open Gmail compose. Tries UIA, file-drop paste, then paperclip."""
    from chrome_oauth_ui import VK_V, click_window, tap_ctrl_key

    pdf = Path(pdf_path).resolve()
    if not pdf.is_file():
        return {"ok": False, "method": "missing-pdf"}

    if _uia_click_attach():
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if _open_dialog_hwnd():
                if _fill_open_dialog(str(pdf), timeout=10.0):
                    return {"ok": True, "method": "uia"}
                break
            time.sleep(0.15)

    if write_clipboard_files([pdf]):
        click_window(win, max(win.width // 2, 80), int(win.height * 0.55))
        time.sleep(0.25)
        tap_ctrl_key(VK_V)
        time.sleep(1.6)
        if not _open_dialog_hwnd():
            return {"ok": True, "method": "clipboard_hdrop"}
        _fill_open_dialog(str(pdf), timeout=8.0)

    box = _find_gmail_send_button(image)
    offsets = (56, 72, 88, 104, 120, 40, 136, 160)
    ys = [box.cy] if box is not None else [max(win.height - 48, 40), max(win.height - 36, 40)]
    x0 = box.x1 if box is not None else 96
    for y in ys:
        for dx in offsets:
            click_window(win, x0 + dx, y)
            deadline = time.time() + 1.2
            while time.time() < deadline:
                if _open_dialog_hwnd():
                    ok = _fill_open_dialog(str(pdf), timeout=10.0)
                    return {"ok": ok, "method": "attach_click", "dx": dx}
                time.sleep(0.15)
    return {"ok": False, "method": "none"}


def send_via_chrome_keys(
    to: str,
    subject: str,
    body: str,
    debug_dir: Path,
    pdf_path: Path | None = None,
) -> dict[str, Any]:
    from chrome_oauth_ui import (
        VK_RETURN,
        VK_V,
        click_window,
        foreground,
        screenshot_window,
        tap_ctrl_key,
        write_clipboard_text,
    )
    from open_chrome_url import open_url_chrome

    debug_dir.mkdir(parents=True, exist_ok=True)
    # Always open a fresh compose with body= so we do not reuse an empty tab.
    url = compose_url(to, subject, body)
    opened = open_url_chrome(url)
    if not opened.get("ok"):
        return {"ok": False, "error": f"open chrome: {opened}"}
    win = None
    for _ in range(40):
        compose_wins, gmail_wins = _gmail_windows()
        win = (compose_wins or gmail_wins or [None])[0]
        if win is not None:
            break
        time.sleep(0.4)
    if win is None:
        return {"ok": False, "error": "no Chrome Gmail window"}
    foreground(win)
    time.sleep(2.4)
    _tap_escape()
    time.sleep(0.2)
    img = screenshot_window(win)
    ink = body_ink_ratio(img)
    if not body_looks_filled(img):
        if not write_clipboard_text(body):
            return {"ok": False, "error": "clipboard write failed", "ink": ink}
        # Click deep in the white body, below Gemini "Press / for Help me write".
        click_window(win, max(win.width // 2, 80), int(win.height * 0.58))
        time.sleep(0.35)
        tap_ctrl_key(VK_V)
        time.sleep(0.9)
        img = screenshot_window(win)
        ink = body_ink_ratio(img)
    before = debug_dir / "gmail_trader_summary_before_send.png"
    img.save(before)
    if not body_looks_filled(img):
        return {
            "ok": False,
            "error": "compose body empty (refusing to send subject-only mail)",
            "window": win.title,
            "screenshot": str(before),
            "ink": ink,
            "opened": opened,
        }
    attached = {"ok": False, "method": "skipped"}
    if pdf_path and Path(pdf_path).is_file():
        attached = attach_pdf_via_chrome(win, img, Path(pdf_path))
        time.sleep(1.4)
        try:
            img = screenshot_window(win)
            ink = body_ink_ratio(img)
            img.save(debug_dir / "gmail_trader_summary_after_attach.png")
        except Exception:
            pass
        if not attached.get("ok"):
            return {
                "ok": False,
                "error": f"pdf attach failed ({attached.get('method')})",
                "window": win.title,
                "screenshot": str(before),
                "ink": ink,
                "opened": opened,
                "attached": attached,
            }
    tap_ctrl_key(VK_RETURN)
    time.sleep(1.4)
    after_path = debug_dir / "gmail_trader_summary_send.png"
    try:
        after = screenshot_window(win)
        still = _find_gmail_send_button(after)
        if still is not None:
            click_window(win, still.cx, still.cy)
            time.sleep(2.2)
            after = screenshot_window(win)
            still = _find_gmail_send_button(after)
        after.save(after_path)
    except Exception:
        still = None
        after_path = None
    compose_after, _ = _gmail_windows()
    sent = still is None or not compose_after
    return {
        "ok": bool(sent),
        "method": "chrome_keys",
        "window": win.title,
        "screenshot": str(after_path) if after_path else str(before),
        "before": str(before),
        "ink": ink,
        "opened": opened,
        "attached": attached,
        "error": None if sent else "compose still open after Send",
    }


def send_summary(
    to: str,
    subject: str,
    body: str,
    debug_dir: Path,
    pdf_path: Path | None = None,
) -> dict[str, Any]:
    api = send_via_gmail_api(to, subject, body, pdf_path)
    if api.get("ok"):
        return api
    cdp = send_via_chrome_cdp(to, subject, body, pdf_path)
    if cdp.get("ok"):
        cdp["gmail_api"] = api.get("error")
        return cdp
    keys = send_via_chrome_keys(to, subject, body, debug_dir, pdf_path)
    keys["gmail_api"] = api.get("error")
    keys["cdp"] = cdp.get("error")
    return keys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Email the live E*TRADE weekly summary to self")
    parser.add_argument("--to", default=DEFAULT_TO)
    parser.add_argument("--print-only", action="store_true")
    parser.add_argument("--pdf-only", action="store_true")
    parser.add_argument("--skip-orders", action="store_true")
    args = parser.parse_args(argv)

    root = live_root()
    data = gather_summary(root, include_orders=not args.skip_orders)
    subject = format_subject(data)
    pdf_path = root / "output" / "etrade_weekly_summary.pdf"
    build_summary_pdf(data, pdf_path)
    body = format_email_body(data, pdf_path.name)
    out_path = root / "output" / "etrade_trader_summary_last.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    print(f"LIVE root: {root}")
    print(f"Subject: {subject}")
    print(f"Wrote {out_path}")
    print(f"Wrote {pdf_path} ({pdf_path.stat().st_size} bytes)")
    if args.print_only or args.pdf_only:
        print(body)
        return 0
    result = send_summary(
        args.to,
        subject,
        body,
        root / "output" / "chrome-oauth-debug",
        pdf_path,
    )
    result["pdf"] = str(pdf_path)
    result["pdf_bytes"] = pdf_path.stat().st_size
    safe = {k: v for k, v in result.items() if k != "opened"}
    print(json.dumps(safe, default=str))
    result_path = root / "output" / "etrade_trader_summary_send.json"
    result_path.write_text(json.dumps(safe, indent=2, default=str) + "\n", encoding="utf-8")
    if not result.get("ok"):
        print("SEND FAIL", result.get("error"), file=sys.stderr)
        return 1
    print(f"SENT via {result.get('method')} to {args.to} pdf={pdf_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
