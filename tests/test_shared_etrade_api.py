"""Shared E*TRADE API — long + short use one API; practice mode independent."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def isolated_configs(tmp_path, monkeypatch):
    long_path = tmp_path / "etrade_config.json"
    short_path = tmp_path / "short_etrade_config.json"
    long_path.write_text(
        json.dumps(
            {
                "consumer_key": "TESTKEY123456",
                "consumer_secret": "TESTSECRET123456",
                "sandbox": False,
                "token_path": "etrade_tokens.json",
                "callback_url": "http://127.0.0.1:8765/callback",
                "use_oob": True,
                "selected_account": {
                    "account_id_key": "acct-shared",
                    "display_label": "Joint Margin",
                },
                "background_worker": {
                    "dry_run": False,
                    "auto_execute": True,
                    "live_trading": True,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    short_path.write_text(
        json.dumps(
            {
                "consumer_key": "STALE_SHORT_KEY",
                "consumer_secret": "STALE_SHORT_SECRET",
                "sandbox": True,
                "selected_account": {"account_id_key": "wrong", "display_label": "Wrong"},
                "background_worker": {
                    "dry_run": True,
                    "auto_execute": False,
                    "live_trading": False,
                },
                "short_strategy": {"max_positions": 3},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    import shared_etrade_api as shared

    monkeypatch.setattr(shared, "LONG_CONFIG_PATH", long_path)
    monkeypatch.setattr(shared, "SHORT_CONFIG_PATH", short_path)
    monkeypatch.setattr(shared, "DEFAULT_CONFIG_PATH", long_path)
    return shared, long_path, short_path


def test_mirror_overwrites_stale_short_api_fields(isolated_configs):
    shared, _long_path, short_path = isolated_configs
    out = shared.mirror_shared_api_into_short()
    assert out["consumer_key"] == "TESTKEY123456"
    assert out["sandbox"] is False
    assert out["selected_account"]["account_id_key"] == "acct-shared"
    assert out["shared_api_from"] == "etrade_config.json"
    # Short-only strategy preserved
    assert out["short_strategy"]["max_positions"] == 3
    # Practice mode on short left alone
    assert out["background_worker"]["dry_run"] is True
    disk = json.loads(short_path.read_text(encoding="utf-8"))
    assert disk["consumer_key"] == "TESTKEY123456"
    assert disk["background_worker"]["dry_run"] is True


def test_practice_mode_independent(isolated_configs):
    shared, long_path, short_path = isolated_configs
    assert shared.sleeve_practice_mode("long") is False
    assert shared.sleeve_practice_mode("short") is True

    shared.set_sleeve_practice_mode("short", False)
    assert shared.sleeve_practice_mode("short") is False
    assert shared.sleeve_practice_mode("long") is False

    long_raw = json.loads(long_path.read_text(encoding="utf-8"))
    short_raw = json.loads(short_path.read_text(encoding="utf-8"))
    assert long_raw["background_worker"]["dry_run"] is False
    assert short_raw["background_worker"]["dry_run"] is False
    # Setting short practice still mirrors shared API keys
    assert short_raw["consumer_key"] == "TESTKEY123456"
    assert short_raw["sandbox"] is False

    shared.set_sleeve_practice_mode("long", True)
    assert shared.sleeve_practice_mode("long") is True
    assert shared.sleeve_practice_mode("short") is False


def test_feature_snapshot_marks_shared_api(isolated_configs):
    shared, _long_path, _short_path = isolated_configs
    snap = shared.feature_snapshot()
    assert snap["feature"] == "shared_etrade_api"
    assert snap["api"]["source"] == "etrade_config.json"
    assert snap["api"]["environment"] == "production"
    assert snap["api"]["has_account"] is True
    assert snap["practice_mode"]["independent"] is True
    assert snap["practice_mode"]["long_dry_run"] is False
    assert snap["practice_mode"]["short_dry_run"] is True
    md = shared.feature_snapshot_markdown()
    assert "Shared E*TRADE API" in md
    assert "independent" in md.lower() or "Practice" in md
