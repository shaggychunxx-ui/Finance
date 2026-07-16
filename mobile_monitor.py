#!/usr/bin/env python3
"""Mobile monitor API + dashboard for E*TRADE Trader (LAN or remote tunnel)."""

from __future__ import annotations

import argparse
import json
import secrets
import ssl
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from agent_report_formatter import format_report_summary
from agent_report_status import agent_age_info, agent_status, fresh_report_counts
from app_paths import OUTPUT, ROOT, ensure_app_path
from mobile_tls import collect_lan_ips, ensure_tls_material, load_ssl_context
from strategy_engine import PLAN_FILE, load_strategy_plan

ensure_app_path()

CONFIG_PATH = ROOT / "etrade_config.json"
DASHBOARD_HTML = ROOT / "mobile_dashboard.html"
MANIFEST_JSON = ROOT / "mobile_manifest.json"
SERVICE_WORKER = ROOT / "mobile_sw.js"
ICON_DIR = ROOT / "mobile_icons"
TRADER_LOG = OUTPUT / "etrade_trader.log"
WORKER_LOG = OUTPUT / "etrade_worker.log"
WORKER_STATE = OUTPUT / "etrade_worker_state.json"
DAY_STATE = OUTPUT / "day_trade_state.json"
DEFAULT_PORT = 8766


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


def _tail_lines(path: Path, *, limit: int = 80) -> list[str]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-max(1, limit) :]


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


def _recent_log_lines(*, limit: int = 100) -> list[str]:
    """Merge trader + worker tails and return newest activity first."""
    lines = _tail_lines(TRADER_LOG, limit=limit) + _tail_lines(WORKER_LOG, limit=limit)
    if not lines:
        return []
    ranked: list[tuple[float, int, str]] = []
    for index, line in enumerate(lines):
        stamp = _parse_log_stamp(line)
        ranked.append((stamp if stamp is not None else float("-inf"), index, line))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [line for _, _, line in ranked[:limit]]


def _iso_age(ts: float | None) -> str | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return None


class MobileMonitorConfig:
    def __init__(self, raw: dict[str, Any] | None = None) -> None:
        raw = raw or {}
        block = raw.get("mobile_monitor") if isinstance(raw.get("mobile_monitor"), dict) else {}
        self.enabled: bool = bool(block.get("enabled", True))
        self.host: str = str(block.get("host", "0.0.0.0"))
        self.port: int = int(block.get("port", DEFAULT_PORT))
        self.https_port: int = int(block.get("https_port", DEFAULT_PORT + 1))
        self.pwa_https: bool = bool(block.get("pwa_https", True))
        self.token: str = str(block.get("token") or "").strip()
        self.allow_lan_without_auth: bool = bool(block.get("allow_lan_without_auth", False))

    def ensure_token(self, config_path: Path = CONFIG_PATH) -> str:
        if self.token:
            return self.token
        data = _read_json(config_path)
        block = data.setdefault("mobile_monitor", {})
        if not isinstance(block, dict):
            block = {}
            data["mobile_monitor"] = block
        token = secrets.token_urlsafe(24)
        block["enabled"] = True
        block["port"] = self.port
        block["host"] = self.host
        block["token"] = token
        block["allow_lan_without_auth"] = self.allow_lan_without_auth
        _write_json(config_path, data)
        self.token = token
        return token


def load_monitor_config(config_path: Path = CONFIG_PATH) -> MobileMonitorConfig:
    return MobileMonitorConfig(_read_json(config_path))


def _lan_access_url(port: int, token: str) -> str | None:
    if not token:
        return None
    try:
        import socket

        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith("127."):
                continue
            if ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172."):
                return f"http://{ip}:{port}/?token={token}"
    except OSError:
        pass
    return None


def collect_status() -> dict[str, Any]:
    from agents.platform_catalog import full_agent_catalog
    from etrade_worker import automation_paused, load_worker_state, worker_settings

    config_raw = _read_json(CONFIG_PATH)
    monitor_cfg = load_monitor_config()
    worker_cfg = worker_settings(CONFIG_PATH)
    worker_state = load_worker_state()
    paused = automation_paused(CONFIG_PATH)

    connected = False
    env = "not_configured"
    account_label = ""
    try:
        from etrade_api.config import get_selected_account, load_config
        from etrade_api.oauth import is_expired_for_day, load_tokens

        cfg = load_config(CONFIG_PATH)
        env = "sandbox" if cfg.sandbox else "production"
        tokens = load_tokens(cfg.token_path, cfg.sandbox)
        connected = tokens is not None and not is_expired_for_day(tokens)
        acct = get_selected_account(CONFIG_PATH)
        if acct:
            account_label = acct.get("display_label") or acct.get("account_id_key") or ""
    except Exception as exc:
        env = f"error: {exc}"

    fresh, total = fresh_report_counts(full_agent_catalog(check_remote=False))
    plan_data = load_strategy_plan(PLAN_FILE)
    plan_summary: dict[str, Any] = {}
    holdings: list[dict[str, Any]] = []
    orders: list[dict[str, Any]] = []
    if plan_data:
        plan_summary = {
            "account_value": plan_data.get("total_account_value"),
            "order_count": len(plan_data.get("orders") or []),
            "generated_at": plan_data.get("generated_at"),
        }
        pos_map = {p["symbol"].upper(): p for p in plan_data.get("current_positions") or []}
        tgt_map = {h["symbol"].upper(): h for h in plan_data.get("target_holdings") or []}
        total_val = float(plan_data.get("total_account_value") or 1)
        for sym in sorted(set(pos_map) | set(tgt_map)):
            cur = pos_map.get(sym, {})
            tgt = tgt_map.get(sym, {})
            cur_usd = float(cur.get("market_value", 0))
            tgt_pct = float(tgt.get("weight_pct", 0))
            holdings.append(
                {
                    "symbol": sym,
                    "current_pct": round(cur_usd / total_val * 100, 1),
                    "target_pct": round(tgt_pct, 1),
                    "drift": round(tgt_pct - cur_usd / total_val * 100, 1),
                    "rationale": (tgt.get("rationale") or "")[:120],
                }
            )
        for order in plan_data.get("orders") or []:
            orders.append(
                {
                    "symbol": order.get("symbol"),
                    "action": order.get("action"),
                    "qty": order.get("quantity"),
                    "status": order.get("status"),
                    "message": (order.get("message") or order.get("rationale") or "")[:100],
                }
            )

    day_raw = _read_json(DAY_STATE)
    day_positions = day_raw.get("positions") or []
    day_pnl = float(day_raw.get("realized_pnl") or 0)

    return {
        "app": "E*TRADE Trader",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "connection": {
            "connected": connected,
            "environment": env,
            "account": account_label,
        },
        "automation": {
            "paused": paused,
            "auto_execute": bool(worker_cfg.get("auto_execute", True)),
            "day_trading": bool(worker_cfg.get("day_trading", True)),
            "dry_run": bool(worker_cfg.get("dry_run", False)),
            "live_trading": bool(worker_cfg.get("live_trading", True)),
        },
        "agents": {"fresh": fresh, "total": total},
        "worker": {
            "last_pipeline_at": _iso_age(worker_state.get("last_pipeline_at")),
            "last_plan_at": _iso_age(worker_state.get("last_plan_at")),
            "last_execute_at": _iso_age(worker_state.get("last_execute_at")),
            "last_day_trading_at": _iso_age(worker_state.get("last_day_trading_at")),
        },
        "portfolio": plan_summary,
        "holdings": holdings[:40],
        "orders": orders[:30],
        "day_trading": {
            "open_positions": len(day_positions),
            "realized_pnl": round(day_pnl, 2),
            "positions": day_positions[:20],
        },
        "log": _recent_log_lines(limit=100),
        "access": {
            "lan_url": _lan_access_url(monitor_cfg.port, monitor_cfg.token),
            "tunnel_note": "If you see Cloudflare error 1033, open the new URL from output/mobile_phone_url.txt on your PC.",
        },
    }


def collect_agents() -> list[dict[str, Any]]:
    from agents.platform_catalog import full_agent_catalog

    rows: list[dict[str, Any]] = []
    for agent in full_agent_catalog(check_remote=False):
        from agent_report_status import agent_accuracy_label, agent_accuracy_pct

        _, age_label, age_tag = agent_age_info(agent)
        rows.append(
            {
                "id": agent["id"],
                "label": agent["label"],
                "category": agent.get("category", ""),
                "status": agent_status(agent),
                "updated": age_label,
                "age_tag": age_tag,
                "accuracy": agent_accuracy_label(agent),
                "accuracy_pct": agent_accuracy_pct(agent),
            }
        )
    rows.sort(key=lambda row: row["updated"] != "—", reverse=True)
    return rows


def set_automation_paused(paused: bool) -> dict[str, Any]:
    from etrade_worker import set_automation_paused as apply_pause

    return apply_pause(paused, CONFIG_PATH)


def collect_agent_report(agent_id: str) -> dict[str, Any]:
    from agents.platform_catalog import full_agent_catalog

    agent = next((a for a in full_agent_catalog(check_remote=False) if a["id"] == agent_id), None)
    if not agent:
        return {"error": "Agent not found"}
    path = OUTPUT / agent["output"]
    if not path.exists():
        return {"id": agent_id, "label": agent["label"], "text": "No report yet."}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "id": agent_id,
            "label": agent["label"],
            "text": format_report_summary(data),
        }
    except Exception as exc:
        return {"id": agent_id, "label": agent["label"], "text": f"Could not read report: {exc}"}


class MobileMonitorHandler(BaseHTTPRequestHandler):
    server_version = "FinanceMobileMonitor/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    @property
    def monitor_config(self) -> MobileMonitorConfig:
        return self.server.monitor_config  # type: ignore[attr-defined]

    def _client_ip(self) -> str:
        return self.client_address[0] if self.client_address else ""

    def _is_private_ip(self, ip: str) -> bool:
        return (
            ip.startswith("127.")
            or ip.startswith("10.")
            or ip.startswith("192.168.")
            or ip.startswith("172.16.")
            or ip.startswith("172.17.")
            or ip.startswith("172.18.")
            or ip.startswith("172.19.")
            or ip.startswith("172.2")
            or ip == "::1"
        )

    def _authorized(self) -> bool:
        cfg = self.monitor_config
        if cfg.allow_lan_without_auth and self._is_private_ip(self._client_ip()):
            return True
        expected = cfg.token
        if not expected:
            return False
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return secrets.compare_digest(auth[7:].strip(), expected)
        query = parse_qs(urlparse(self.path).query)
        token = (query.get("token") or [""])[0]
        return bool(token) and secrets.compare_digest(token, expected)

    def _send_json(self, payload: Any, *, status: int = 200) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(
        self,
        body: bytes,
        *,
        content_type: str,
        cache_control: str = "no-store",
        status: int = 200,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.wfile.write(body)

    def _request_origin(self) -> str:
        host = self.headers.get("Host", "").strip()
        if not host:
            host = f"localhost:{self.server.server_port}"
        proto = "https" if getattr(self.server, "use_tls", False) else "http"
        return f"{proto}://{host}"

    def _build_manifest(self) -> dict[str, Any]:
        origin = self._request_origin()
        query = parse_qs(urlparse(self.path).query)
        token = (query.get("token") or [""])[0] or self.monitor_config.token
        start_params: dict[str, str] = {"source": "pwa"}
        if token:
            start_params["token"] = token
        start_url = f"{origin}/?{urlencode(start_params)}"
        app_id = f"{origin}/?source=pwa"
        return {
            "id": app_id,
            "name": "E*TRADE Trader",
            "short_name": "E*TRADE",
            "description": "Monitor agents, trades, and automation from your phone.",
            "start_url": start_url,
            "scope": "/",
            "display": "standalone",
            "display_override": ["standalone", "fullscreen"],
            "orientation": "portrait",
            "background_color": "#0a0e17",
            "theme_color": "#6c5ce7",
            "icons": [
                {
                    "src": f"{origin}/mobile_icons/icon-192.png",
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any",
                },
                {
                    "src": f"{origin}/mobile_icons/icon-512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any",
                },
                {
                    "src": f"{origin}/mobile_icons/icon-192.png",
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "maskable",
                },
                {
                    "src": f"{origin}/mobile_icons/icon-512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "maskable",
                },
            ],
        }

    def _send_manifest(self) -> None:
        body = json.dumps(self._build_manifest(), indent=2).encode("utf-8")
        self._send_bytes(body, content_type="application/manifest+json")

    def _dashboard_token_for_request(self) -> str:
        query = parse_qs(urlparse(self.path).query)
        url_token = (query.get("token") or [""])[0]
        expected = self.monitor_config.token
        if url_token and expected and secrets.compare_digest(url_token, expected):
            return expected
        if expected and self._is_private_ip(self._client_ip()):
            return expected
        return ""

    def _send_html(self, path: Path) -> None:
        if not path.exists():
            self.send_error(404, "Dashboard not found")
            return
        body = path.read_bytes()
        token = self._dashboard_token_for_request()
        if token:
            inject = (
                f"<script>window.__MOBILE_TOKEN__={json.dumps(token)};</script>"
            ).encode("utf-8")
            body = body.replace(b"</head>", inject + b"</head>", 1)
        self._send_bytes(body, content_type="text/html; charset=utf-8")

    def _send_file(self, path: Path, *, content_type: str, cache_control: str = "no-store") -> None:
        if not path.exists():
            self.send_error(404, "File not found")
            return
        self._send_bytes(path.read_bytes(), content_type=content_type, cache_control=cache_control)

    def _unauthorized(self) -> None:
        self._send_json({"error": "Unauthorized — set token in mobile_monitor config"}, status=401)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        try:
            raw = self.rfile.read(length)
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return {}

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.end_headers()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if not path.startswith("/api/"):
            return self.send_error(404)

        if not self._authorized():
            return self._unauthorized()

        if path == "/api/automation/pause":
            body = self._read_json_body()
            if "paused" not in body:
                return self._send_json({"error": "Missing paused field"}, status=400)
            paused = bool(body.get("paused"))
            try:
                result = set_automation_paused(paused)
                payload = {"ok": True, "automation": result, "status": collect_status()}
                return self._send_json(payload)
            except OSError as exc:
                return self._send_json({"error": f"Could not update config: {exc}"}, status=500)

        self.send_error(404)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path in ("/", "/mobile", "/mobile_dashboard.html"):
            return self._send_html(DASHBOARD_HTML)
        if path == "/mobile_manifest.json":
            return self._send_manifest()
        if path == "/mobile_sw.js":
            return self._send_file(SERVICE_WORKER, content_type="application/javascript")
        if path.startswith("/mobile_icons/"):
            icon_name = Path(path).name
            if icon_name.endswith(".png"):
                return self._send_file(ICON_DIR / icon_name, content_type="image/png", cache_control="public, max-age=86400")

        if not path.startswith("/api/"):
            return self.send_error(404)

        if not self._authorized():
            return self._unauthorized()

        if path == "/api/status":
            return self._send_json(collect_status())
        if path == "/api/agents":
            return self._send_json({"agents": collect_agents()})

        if path.startswith("/api/agents/"):
            agent_id = path.split("/api/agents/", 1)[1].strip("/")
            if agent_id:
                return self._send_json(collect_agent_report(agent_id))

        self.send_error(404)


def run_server(
    *,
    host: str,
    port: int,
    config: MobileMonitorConfig,
    use_tls: bool = False,
    ssl_context: ssl.SSLContext | None = None,
) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), MobileMonitorHandler)
    httpd.monitor_config = config  # type: ignore[attr-defined]
    httpd.use_tls = use_tls  # type: ignore[attr-defined]
    if use_tls and ssl_context is not None:
        httpd.socket = ssl_context.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def build_phone_app_url(*, ip: str, port: int, token: str, secure: bool = True) -> str:
    scheme = "https" if secure else "http"
    params = urlencode({"source": "pwa", "token": token})
    return f"{scheme}://{ip}:{port}/?{params}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E*TRADE Trader mobile monitor")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--no-token-setup", action="store_true")
    args = parser.parse_args(argv)

    config = load_monitor_config()
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port

    if not args.no_token_setup:
        token = config.ensure_token()
    else:
        token = config.token

    if not DASHBOARD_HTML.exists():
        print(f"Missing {DASHBOARD_HTML.name} — reinstall or restore Finance folder.")
        return 1

    httpd = run_server(host=config.host, port=config.port, config=config)
    httpsd: ThreadingHTTPServer | None = None
    if config.pwa_https and config.https_port != config.port:
        cert_dir = OUTPUT / "mobile_tls"
        cert_pem, key_pem = ensure_tls_material(cert_dir)
        ssl_context = load_ssl_context(cert_pem, key_pem)
        httpsd = run_server(
            host=config.host,
            port=config.https_port,
            config=config,
            use_tls=True,
            ssl_context=ssl_context,
        )

    lan_ips = [ip for ip in collect_lan_ips() if not ip.startswith("127.")]

    print("E*TRADE Trader — mobile monitor running")
    print(f"  Dashboard: http://127.0.0.1:{config.port}/")
    if httpsd:
        print(f"  Phone app (HTTPS): https://127.0.0.1:{config.https_port}/")
        for ip in lan_ips[:4]:
            if token:
                print(f"  Install on phone: {build_phone_app_url(ip=ip, port=config.https_port, token=token)}")
            else:
                print(f"  On your Wi-Fi (HTTPS): https://{ip}:{config.https_port}/")
        print("  First visit: accept the certificate warning, then tap Install app.")
    else:
        for ip in lan_ips[:4]:
            print(f"  On your Wi-Fi: http://{ip}:{config.port}/")
    if token:
        print(f"  API token: {token}")
        print("  Phone bookmark: add ?token=... to the URL (saved in the app)")
    print("")
    print("Install as app: run Fix Phone Home Screen.bat (same Wi-Fi).")
    print("Away from home? Run Start Mobile Remote Access.bat for a Cloudflare tunnel URL.")
    print("Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping mobile monitor...")
        httpd.shutdown()
        if httpsd is not None:
            httpsd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())