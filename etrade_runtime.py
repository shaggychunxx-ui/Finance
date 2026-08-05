"""Canonical live Finance runtime — never confuse git clones with the broker host.

Money-path rule
---------------
The headless worker, OAuth tokens, and live order path run from the **live
runtime root**, normally::

    %USERPROFILE%\\Finance
    (override with env FINANCE_RUNTIME)

Git clones under ``Documents\\GitHub\\Finance`` (or any non-live tree) are for
code review / bus work. Logging in or reporting "connected / live" from a
clone alone has already caused a false green: tokens saved where the worker
does not read them.

Every broker OAuth / live-status tool must call :func:`resolve_live_root`.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


LIVE_MARKERS = ("etrade_worker.py", "etrade_api")
GITHUB_CLONE_MARKERS = (
    Path("Documents") / "GitHub" / "Finance",
    Path("Documents") / "GitHub" / "finance",
)


def _env_runtime() -> Path | None:
    raw = (os.environ.get("FINANCE_RUNTIME") or os.environ.get("FINANCE_ROOT") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def default_live_candidate() -> Path:
    return (Path.home() / "Finance").resolve()


def looks_like_finance_tree(root: Path) -> bool:
    try:
        root = root.resolve()
    except OSError:
        return False
    if not root.is_dir():
        return False
    return all((root / name).exists() for name in LIVE_MARKERS)


def is_github_clone_path(root: Path) -> bool:
    try:
        resolved = root.resolve()
    except OSError:
        return False
    parts = resolved.parts
    # .../Documents/GitHub/Finance
    for i in range(len(parts) - 2):
        if (
            parts[i].lower() == "documents"
            and parts[i + 1].lower() == "github"
            and parts[i + 2].lower() == "finance"
        ):
            return True
    text = str(resolved).replace("/", "\\").lower()
    return "\\documents\\github\\finance" in text


def script_or_cwd_root() -> Path:
    """Best-effort tree root for the process (script dir when available)."""

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # Prefer caller package layout: etrade_runtime lives at finance root.
    here = Path(__file__).resolve().parent
    if looks_like_finance_tree(here):
        return here
    cwd = Path.cwd().resolve()
    if looks_like_finance_tree(cwd):
        return cwd
    return here


@dataclass(frozen=True)
class LiveRootDecision:
    root: Path
    source: str  # env | home_finance | explicit | self
    is_live: bool
    is_github_clone: bool
    redirected_from: Path | None = None

    @property
    def token_path(self) -> Path:
        return self.root / "etrade_tokens.json"

    @property
    def config_path(self) -> Path:
        return self.root / "etrade_config.json"

    @property
    def pending_oauth_path(self) -> Path:
        return self.root / "output" / "oauth_pending.json"

    @property
    def worker_log_path(self) -> Path:
        return self.root / "output" / "etrade_worker.log"


def resolve_live_root(
    *,
    allow_non_live: bool = False,
    prefer: Path | None = None,
) -> LiveRootDecision:
    """Return the root that owns broker tokens and the headless worker.

    Priority:
      1. ``prefer`` if it looks like a finance tree and is not a github clone
         (or allow_non_live)
      2. ``FINANCE_RUNTIME`` / ``FINANCE_ROOT``
      3. ``%USERPROFILE%\\Finance`` when it looks like the live tree
      4. Current script/cwd tree only if live-looking and not a github clone,
         or ``allow_non_live``
    """

    self_root = script_or_cwd_root()

    candidates: list[tuple[str, Path]] = []
    if prefer is not None:
        candidates.append(("explicit", Path(prefer).expanduser().resolve()))
    env = _env_runtime()
    if env is not None:
        candidates.append(("env", env))
    home = default_live_candidate()
    candidates.append(("home_finance", home))
    candidates.append(("self", self_root))

    seen: set[Path] = set()
    for source, root in candidates:
        try:
            root = root.resolve()
        except OSError:
            continue
        if root in seen:
            continue
        seen.add(root)
        if not looks_like_finance_tree(root):
            continue
        clone = is_github_clone_path(root)
        # Prefer non-clone live trees.
        if clone and source != "explicit" and not allow_non_live:
            continue
        if clone and not allow_non_live:
            continue
        redirected = None if root == self_root else self_root
        is_live = (not clone) and (
            source in {"env", "home_finance", "explicit"}
            or root == home
            or (env is not None and root == env)
        )
        # home Finance or env is always "live" when it exists
        if source in {"env", "home_finance"} or (env is not None and root == env):
            is_live = True
        if source == "home_finance" or (env is not None and root == env):
            is_live = True
        # Explicit non-clone preferred root counts as live.
        if source == "explicit" and not clone:
            is_live = True
        # Self only counts as live when it is the home Finance tree (or env).
        if source == "self":
            is_live = (not clone) and (
                root == home or (env is not None and root == env)
            )
            if not is_live and not allow_non_live:
                continue
        return LiveRootDecision(
            root=root,
            source=source,
            is_live=is_live or (allow_non_live and not clone),
            is_github_clone=clone,
            redirected_from=redirected if redirected != root else None,
        )

    # Last resort: self, even if clone — only with allow_non_live.
    if allow_non_live and looks_like_finance_tree(self_root):
        return LiveRootDecision(
            root=self_root,
            source="self",
            is_live=False,
            is_github_clone=is_github_clone_path(self_root),
            redirected_from=None,
        )

    raise FileNotFoundError(
        "No live Finance runtime found.\n"
        f"  Expected: {home} (with etrade_worker.py)\n"
        "  Or set FINANCE_RUNTIME to the folder where the headless worker runs.\n"
        "  Refusing to use a Documents\\GitHub\\Finance clone for broker OAuth."
    )


def ensure_sys_path(root: Path) -> None:
    s = str(root.resolve())
    if s not in sys.path:
        sys.path.insert(0, s)


def print_live_banner(decision: LiveRootDecision) -> None:
    print("=" * 60)
    print("E*TRADE LIVE RUNTIME (broker / tokens / worker)")
    print(f"  root:   {decision.root}")
    print(f"  source: {decision.source}")
    print(f"  live:   {decision.is_live}")
    if decision.redirected_from and decision.redirected_from != decision.root:
        print(f"  NOTE: script/cwd was {decision.redirected_from}")
        print("        OAuth will write tokens ONLY under the live root above.")
    if decision.is_github_clone:
        print("  WARNING: this path looks like a GitHub clone — not the worker host.")
    print("=" * 60)


def assert_live_for_broker_action(decision: LiveRootDecision) -> None:
    if decision.is_live and not decision.is_github_clone:
        return
    raise RuntimeError(
        "Refusing broker OAuth / live status on a non-live tree.\n"
        f"  current: {decision.root}\n"
        f"  expected live: {default_live_candidate()} or FINANCE_RUNTIME\n"
        "  Pass allow_non_live only for sandbox unit tests — never for production login."
    )


_CONNECTED_RE = re.compile(
    r"Connected to E\*TRADE \((production|sandbox)\)",
    re.IGNORECASE,
)
_EXPIRED_RE = re.compile(
    r"token expired \(past midnight ET\)|No saved E\*TRADE token|not connected to E\*TRADE|"
    r"Broker waiting for E\*TRADE connection",
    re.IGNORECASE,
)


def worker_log_connection_state(log_path: Path, *, tail_bytes: int = 256_000) -> tuple[str, str]:
    """Return (state, detail) from the end of etrade_worker.log.

    state: connected_production | connected_sandbox | expired | waiting | unknown | missing
    """

    if not log_path.exists():
        return "missing", f"no worker log at {log_path}"
    try:
        size = log_path.stat().st_size
        with log_path.open("rb") as handle:
            if size > tail_bytes:
                handle.seek(-tail_bytes, os.SEEK_END)
            raw = handle.read().decode("utf-8", errors="replace")
    except OSError as exc:
        return "unknown", str(exc)

    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    # Scan from end for the most recent decisive line.
    for line in reversed(lines[-400:]):
        m = _CONNECTED_RE.search(line)
        if m:
            env = m.group(1).lower()
            state = "connected_production" if env == "production" else "connected_sandbox"
            return state, line
        if _EXPIRED_RE.search(line):
            return "expired", line
    return "unknown", lines[-1] if lines else "(empty log)"
