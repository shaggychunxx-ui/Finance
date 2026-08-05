"""Unit tests for live-runtime resolution (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from etrade_runtime import (  # noqa: E402
    is_github_clone_path,
    looks_like_finance_tree,
    resolve_live_root,
)


def test_github_clone_detection() -> None:
    fake = Path(r"C:\Users\Someone\Documents\GitHub\Finance")
    assert is_github_clone_path(fake)
    assert not is_github_clone_path(Path(r"C:\Users\Someone\Finance"))


def test_looks_like_finance_tree_requires_markers(tmp_path: Path) -> None:
    assert not looks_like_finance_tree(tmp_path)
    (tmp_path / "etrade_worker.py").write_text("# stub\n", encoding="utf-8")
    assert not looks_like_finance_tree(tmp_path)
    (tmp_path / "etrade_api").mkdir()
    assert looks_like_finance_tree(tmp_path)


def test_resolve_prefers_live_over_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = tmp_path / "live_Finance"
    live.mkdir()
    (live / "etrade_worker.py").write_text("#\n", encoding="utf-8")
    (live / "etrade_api").mkdir()

    clone = tmp_path / "Documents" / "GitHub" / "Finance"
    clone.mkdir(parents=True)
    (clone / "etrade_worker.py").write_text("#\n", encoding="utf-8")
    (clone / "etrade_api").mkdir()

    import etrade_runtime as er

    monkeypatch.delenv("FINANCE_RUNTIME", raising=False)
    monkeypatch.delenv("FINANCE_ROOT", raising=False)
    monkeypatch.setattr(er, "default_live_candidate", lambda: live.resolve())
    monkeypatch.setattr(er, "script_or_cwd_root", lambda: clone.resolve())

    decision = resolve_live_root(allow_non_live=False)
    assert decision.root == live.resolve()
    assert decision.is_live
    assert not decision.is_github_clone
    assert decision.redirected_from == clone.resolve()


def test_refuse_clone_only_without_allow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    clone = tmp_path / "Documents" / "GitHub" / "Finance"
    clone.mkdir(parents=True)
    (clone / "etrade_worker.py").write_text("#\n", encoding="utf-8")
    (clone / "etrade_api").mkdir()
    missing_live = tmp_path / "nope_Finance"

    import etrade_runtime as er

    monkeypatch.delenv("FINANCE_RUNTIME", raising=False)
    monkeypatch.delenv("FINANCE_ROOT", raising=False)
    monkeypatch.setattr(er, "default_live_candidate", lambda: missing_live.resolve())
    monkeypatch.setattr(er, "script_or_cwd_root", lambda: clone.resolve())

    with pytest.raises(FileNotFoundError):
        resolve_live_root(allow_non_live=False)
