"""Local HTTP server for the Market Predictor predictions dashboard."""

from __future__ import annotations

import socket
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

DEFAULT_PORT = 8777

_server: ThreadingHTTPServer | None = None
_server_root: Path | None = None


def _pick_port(host: str, port: int) -> int:
    for candidate in range(port, port + 20):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind((host, candidate))
                return candidate
        except OSError:
            continue
    return port


def _make_handler(root: Path) -> type[SimpleHTTPRequestHandler]:
    root_str = str(root.resolve())

    class DashboardHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=root_str, **kwargs)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

    return DashboardHandler


def ensure_predictions_dashboard_server(root: Path, *, port: int = DEFAULT_PORT) -> int:
    """Start (or reuse) a background server that serves Finance static files."""
    global _server, _server_root

    root = root.resolve()
    if _server is not None and _server_root == root:
        return int(_server.server_address[1])

    host = "127.0.0.1"
    chosen = _pick_port(host, port)
    handler = _make_handler(root)
    httpd = ThreadingHTTPServer((host, chosen), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    _server = httpd
    _server_root = root
    return chosen


def open_predictions_dashboard(root: Path, *, port: int = DEFAULT_PORT) -> str:
    """Open the predictions dashboard in the default browser."""
    chosen = ensure_predictions_dashboard_server(root, port=port)
    url = f"http://127.0.0.1:{chosen}/predictions_dashboard.html"
    webbrowser.open(url)
    return url