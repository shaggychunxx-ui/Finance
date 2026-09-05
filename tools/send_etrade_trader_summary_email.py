#!/usr/bin/env python3
"""Build the live E*TRADE trader summary and email it to self.

Reads the GROMIT live runtime (%USERPROFILE%\\Finance), never the git clone.
Send order:
  1) Gmail API if ~/.gmail-link token has gmail.send
  2) Chrome Default Gmail compose (CDP if Chrome was started with 9222,
     else clipboard + Ctrl+Enter)

Usage (live venv):
  python tools/send_etrade_trader_summary_email.py
  python tools/send_etrade_trader_summary_email.py --print-only
"""
from __future__ import annotations

import argparse
import base64
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
from datetime import datetime, timedelta, timezone
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


def _weekday_window(today: datetime, sessions: int = 5) -> set[str]:
    days: set[str] = set()
    d = today.date()
    while len(days) < sessions:
        if d.weekday() < 5:
            days.add(d.isoformat())
        d -= timedelta(days=1)
    return days


def gather_summary(root: Path, *, include_orders: bool = True) -> dict[str, Any]:
    out = root / "output"
    snap = _load_json(out / "account_snapshot.json")
    goals = _load_json(out / "account_goals_status.json")
    refresh = _load_json(out / "phone_refresh_last.json")
    wstate = _load_json(out / "etrade_worker_state.json")
    pdt = _load_json(out / "pdt_tracker.json")
    plan = _load_json(out / "strategy_plan.json")
    brief = _load_json(out / "history" / "next_session_brief.json")
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

    now = datetime.now(timezone.utc)
    window = _weekday_window(now, 5)
    day_trades = [d for d in (pdt.get("day_trades") or []) if isinstance(d, dict)]
    pdt_in_window = [d for d in day_trades if str(d.get("date") or "") in window]
    pdt_by_date = Counter(str(d.get("date")) for d in pdt_in_window)

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
        "brief_actions": list(brief.get("actions") or [])[:5],
        "worker_updated_at": wstate.get("updated_at"),
    }


def format_text(data: dict[str, Any]) -> str:
    flags = data.get("flags") or {}
    mode = "LIVE AUTO" if (flags.get("live_trading") and flags.get("auto_execute") and not flags.get("dry_run")) else "not live"
    if flags.get("paused"):
        mode += " (paused)"
    if flags.get("sandbox"):
        mode += " SANDBOX"
    lines = [
        f"E*TRADE trader summary — {data.get('generated_at')}",
        f"Host {data.get('host')}  Account {data.get('account_name')}",
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
    for row in data.get("positions") or []:
        lines.append(
            f"{row.get('symbol'):<6}  qty {row.get('quantity'):>7}  "
            f"px {_usd(row.get('price')):>10}  mv {_usd(row.get('market_value')):>10}  "
            f"uPL {_usd(row.get('unrealized_pl')):>10}"
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
    lines += [
        "",
        "No tokens / account_id_key in this mail. Generated on GROMIT live runtime.",
    ]
    return "\n".join(lines) + "\n"


def format_subject(data: dict[str, Any]) -> str:
    eq = _usd(data.get("equity"))
    dpl = _pct((data.get("daily") or {}).get("actual_pct"))
    return f"E*TRADE trader summary {data.get('generated_at', '')}  equity {eq}  day {dpl}"


def _token_has_send(path: Path) -> bool:
    raw = _load_json(path)
    scopes = raw.get("scopes") or []
    if isinstance(scopes, str):
        scopes = scopes.split()
    blob = " ".join(str(s) for s in scopes) + " " + json.dumps(raw)
    return "gmail.send" in blob or "mail.google.com" in blob


def send_via_gmail_api(to: str, subject: str, body: str) -> dict[str, Any]:
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
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip("=")
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"ok": True, "method": "gmail_api", "id": sent.get("id")}
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


def send_via_chrome_cdp(to: str, subject: str, body: str) -> dict[str, Any]:
    compose = (
        "https://mail.google.com/mail/u/0/?view=cm&fs=1&tf=1&to="
        + urllib.parse.quote(to)
        + "&su="
        + urllib.parse.quote(subject[:120])
    )
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
        script = f"""
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
      await sleep(200);
      const buttons = [...document.querySelectorAll('div[role="button"]')];
      const send = buttons.find((el) => {{
        const a = ((el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('data-tooltip') || '')).toLowerCase();
        return a.startsWith('send') && !a.includes('schedule');
      }});
      if (!send) return 'no-send';
      send.click();
      await sleep(800);
      const after = (document.body && document.body.innerText) || '';
      if (/message sent|sending/i.test(after)) return 'sent';
      return 'clicked-send';
    }}
    await sleep(400);
  }}
  return 'no-body';
}})()
"""
        result = cdp.eval(script)
        if result in {"sent", "clicked-send"}:
            return {"ok": True, "method": "chrome_cdp", "result": result, "started": started}
        return {"ok": False, "error": str(result), "started": started}
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


def send_via_chrome_keys(to: str, subject: str, body: str, debug_dir: Path) -> dict[str, Any]:
    from chrome_oauth_ui import (
        VK_V,
        click_window,
        foreground,
        screenshot_window,
        tap_ctrl_key,
        write_clipboard_text,
    )
    from open_chrome_url import open_url_chrome

    debug_dir.mkdir(parents=True, exist_ok=True)
    compose_wins, gmail_wins = _gmail_windows()
    opened = {"ok": True, "reused": True}
    if not compose_wins:
        compose = (
            "https://mail.google.com/mail/u/0/?view=cm&fs=1&tf=1&to="
            + urllib.parse.quote(to)
            + "&su="
            + urllib.parse.quote(subject[:120])
        )
        opened = open_url_chrome(compose)
        if not opened.get("ok"):
            return {"ok": False, "error": f"open chrome: {opened}"}
        for _ in range(40):
            compose_wins, gmail_wins = _gmail_windows()
            if compose_wins or gmail_wins:
                break
            time.sleep(0.4)
    win = (compose_wins or gmail_wins or [None])[0]
    if win is None:
        return {"ok": False, "error": "no Chrome Gmail window"}
    if not write_clipboard_text(body):
        return {"ok": False, "error": "clipboard write failed"}
    foreground(win)
    time.sleep(1.2)
    # Body is the large white area under To/Subject, above the Send pill.
    click_window(win, max(win.width // 2, 80), int(win.height * 0.48))
    time.sleep(0.25)
    tap_ctrl_key(ord("A"))
    time.sleep(0.12)
    tap_ctrl_key(VK_V)
    time.sleep(0.6)
    img = screenshot_window(win)
    before = debug_dir / "gmail_trader_summary_before_send.png"
    img.save(before)
    box = _find_gmail_send_button(img)
    if box is None:
        return {
            "ok": False,
            "error": "Send button not found",
            "window": win.title,
            "screenshot": str(before),
        }
    click_window(win, box.cx, box.cy)
    time.sleep(2.8)
    after_path = debug_dir / "gmail_trader_summary_send.png"
    try:
        after = screenshot_window(win)
        after.save(after_path)
        still = _find_gmail_send_button(after)
    except Exception:
        still = None
        after_path = None
    # Sent if the compose pill is gone or the window title dropped Compose.
    compose_after, _ = _gmail_windows()
    sent = still is None or not compose_after
    return {
        "ok": bool(sent),
        "method": "chrome_keys",
        "window": win.title,
        "screenshot": str(after_path) if after_path else str(before),
        "before": str(before),
        "opened": opened,
        "error": None if sent else "compose still open after Send click",
    }


def send_summary(to: str, subject: str, body: str, debug_dir: Path) -> dict[str, Any]:
    api = send_via_gmail_api(to, subject, body)
    if api.get("ok"):
        return api
    cdp = send_via_chrome_cdp(to, subject, body)
    if cdp.get("ok"):
        cdp["gmail_api"] = api.get("error")
        return cdp
    keys = send_via_chrome_keys(to, subject, body, debug_dir)
    keys["gmail_api"] = api.get("error")
    keys["cdp"] = cdp.get("error")
    return keys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Email the live E*TRADE trader summary to self")
    parser.add_argument("--to", default=DEFAULT_TO)
    parser.add_argument("--print-only", action="store_true")
    parser.add_argument("--skip-orders", action="store_true")
    args = parser.parse_args(argv)

    root = live_root()
    data = gather_summary(root, include_orders=not args.skip_orders)
    subject = format_subject(data)
    body = format_text(data)
    out_path = root / "output" / "etrade_trader_summary_last.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    print(f"LIVE root: {root}")
    print(f"Subject: {subject}")
    print(f"Wrote {out_path}")
    if args.print_only:
        print(body)
        return 0
    result = send_summary(args.to, subject, body, root / "output" / "chrome-oauth-debug")
    print(json.dumps({k: v for k, v in result.items() if k != "opened"}, default=str))
    if not result.get("ok"):
        print("SEND FAIL", result.get("error"), file=sys.stderr)
        return 1
    print(f"SENT via {result.get('method')} to {args.to}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
