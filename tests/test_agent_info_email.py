"""Agent-info email formatter — no network, no send."""

from __future__ import annotations

import base64
import json
import re
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from send_agent_info_email import (  # noqa: E402
    build_agent_info_pdf,
    format_email_body,
    format_subject,
    format_text,
    gather_agent_info,
)
from send_etrade_trader_summary_email import compose_url  # noqa: E402


SAMPLE = {
    "generated_at": "2026-09-05 02:10 UTC",
    "host": "GROMIT",
    "catalog_count": 83,
    "learning_count": 73,
    "phone_agent_count": 83,
    "learning_updated_at": "2026-09-05T01:53:32Z",
    "live_scored_rows": 0,
    "backtest_trial_rows_merged": 25000,
    "trial_cycle": "bt20260905T015330Z_e7e74f",
    "pending_predictions": 12,
    "scored_rows": 0,
    "boost_agents": ["dca-strategy", "bond-markets"],
    "cut_agents": [],
    "brief_for": "next_RTH",
    "brief_updated_at": "2026-09-05T01:53:00Z",
    "brief_benchmark": "Accuracy benchmark: 10000/10000 walk-forward trials. Top agent dca-strategy at 43.4%.",
    "brief_actions": ["Lead walk-forward edge: dca-strategy"],
    "top_agents": [
        {
            "agent_id": "dca-strategy",
            "accuracy_pct": 43.4,
            "edge_score": 0.4609,
            "posture": "calibrated",
            "preferred_horizon": "24h",
            "fusion_multiplier": 0.9239,
        }
    ],
    "weak_agents": [
        {
            "agent_id": "equity-tracker",
            "accuracy_pct": 33.2,
            "edge_score": 0.0917,
            "posture": "cautious",
            "fusion_multiplier": 0.8078,
            "lessons": ["Overall accuracy 33% — reduce conviction on weak calls."],
        }
    ],
    "pipeline": {
        "last_at": "2026-09-05T00:27:01Z",
        "last_ok": 3,
        "last_total": 3,
        "last_cycle": "20260905T002646Z",
        "full_at": "2026-09-03T12:50:56Z",
        "full_ok": 43,
        "full_total": 46,
        "full_cycle": "20260903T125040Z",
        "total_runs": 500,
    },
    "groups": [
        {
            "group_id": "dca_invest",
            "label": "DCA",
            "count": 1,
            "avg_accuracy_pct": 43.4,
            "avg_edge": 0.4609,
            "role": "allocator",
            "mode": "allocation",
        },
        {
            "group_id": "markets_core",
            "label": "Markets & Core Trading",
            "count": 8,
            "avg_accuracy_pct": 36.1,
            "avg_edge": 0.2100,
            "role": "alpha",
            "mode": "directional_alpha",
        },
    ],
    "agents": [
        {
            "agent_id": "dca-strategy",
            "accuracy_pct": 43.4,
            "live_accuracy_pct": 43.4,
            "proxy_accuracy_pct": 29.6,
            "edge_score": 0.4609,
            "fusion_multiplier": 0.9239,
            "posture": "calibrated",
            "group_label": "DCA",
            "lessons": ["Walk-forward edge positive — eligible for higher fusion weight."],
            "trust_symbols": ["SPY"],
            "avoid_symbols": [],
        },
        {
            "agent_id": "equity-tracker",
            "accuracy_pct": 33.2,
            "live_accuracy_pct": 33.2,
            "proxy_accuracy_pct": 29.6,
            "edge_score": 0.0917,
            "fusion_multiplier": 0.8078,
            "posture": "cautious",
            "group_label": "Markets & Core Trading",
            "lessons": ["Overall accuracy 33% — reduce conviction on weak calls."],
            "trust_symbols": [],
            "avoid_symbols": [],
        },
    ],
    "directional_calls": [
        {
            "agent_id": "markets",
            "bias": "BULLISH",
            "tickers": ["XLE", "XOM"],
            "reason": "Energy leadership",
            "confidence": 0.55,
        }
    ],
    "account_id_key": "SHOULD_NOT_APPEAR",
}


def _a85(data: bytes) -> bytes:
    payload = data.strip().replace(b"\r", b"").replace(b"\n", b"")
    if payload.startswith(b"<~"):
        payload = payload[2:]
    if payload.endswith(b"~>"):
        payload = payload[:-2]
    return base64.a85decode(payload, adobe=False, foldspaces=False)


def _pdf_text(path: Path) -> str:
    data = path.read_bytes()
    chunks: list[str] = []
    for match in re.finditer(rb"stream\r?\n(.+?)\r?\nendstream", data, re.S):
        chunk = match.group(1)
        decoded = None
        for decoder in (
            lambda x: x,
            _a85,
            lambda x: zlib.decompress(x),
            lambda x: zlib.decompress(_a85(x)),
        ):
            try:
                decoded = decoder(chunk)
                break
            except Exception:
                continue
        if decoded:
            chunks.append(decoded.decode("latin-1", errors="ignore"))
    return "\n".join(chunks)


def test_format_includes_agents_groups_and_calls() -> None:
    text = format_text(SAMPLE)
    assert "dca-strategy" in text
    assert "equity-tracker" in text
    assert "43.4%" in text
    assert "Markets & Core Trading" in text
    assert "BULLISH" in text
    assert "XLE" in text
    assert "live scored rows 0" in text.lower() or "Live scored rows 0" in text
    assert "vote-weight multiplier" in text
    assert "not a percent" in text
    assert "SHOULD_NOT_APPEAR" not in text


def test_subject_has_top_agent_not_secret() -> None:
    sub = format_subject(SAMPLE)
    assert "agent info" in sub.lower()
    assert "dca-strategy" in sub
    assert "43.4%" in sub
    assert "SHOULD_NOT_APPEAR" not in sub


def test_compose_url_includes_body() -> None:
    url = compose_url("shaggychunxx@gmail.com", "E*TRADE agent info", "== All agents ==\ndca-strategy")
    assert "mail.google.com" in url
    assert "view=cm" in url
    assert "body=" in url
    assert "dca-strategy" in url


def test_email_body_mentions_pdf() -> None:
    text = format_email_body(SAMPLE, "etrade_agent_info.pdf")
    assert "etrade_agent_info.pdf" in text
    assert "dca-strategy" in text
    assert "SHOULD_NOT_APPEAR" not in text


def test_pdf_has_agents_and_strips_secrets(tmp_path: Path) -> None:
    path = tmp_path / "etrade_agent_info.pdf"
    built = build_agent_info_pdf(SAMPLE, path)
    assert built.is_file()
    assert built.read_bytes().startswith(b"%PDF")
    assert built.stat().st_size > 1500
    text = _pdf_text(built)
    assert "dca-strategy" in text
    assert "equity-tracker" in text
    assert "SHOULD_NOT_APPEAR" not in text
    assert "walk-forward" in text.lower() or "Walk-forward" in text or "walk-forward" in text
    assert "vote-weight multiplier" in text
    assert "Fus" in text


def test_gather_from_tmp_files(tmp_path: Path) -> None:
    hist = tmp_path / "output" / "history"
    hist.mkdir(parents=True)
    (hist / "agent_learning.json").write_text(
        json.dumps(
            {
                "meta": {"agents_tracked": 1, "live_scored_rows": 0, "backtest_trial_rows_merged": 10},
                "agents": {
                    "markets": {
                        "agent_id": "markets",
                        "accuracy_pct": 40.0,
                        "edge_score": 0.2,
                        "fusion_multiplier": 0.9,
                        "posture": "learning",
                        "preferred_horizon": "24h",
                        "lessons": ["ok"],
                        "trust_symbols": [],
                        "avoid_symbols": [],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (hist / "learning_policy.json").write_text(
        json.dumps({"boost_agents": ["markets"], "cut_agents": []}),
        encoding="utf-8",
    )
    (hist / "next_session_brief.json").write_text(
        json.dumps(
            {
                "for_session": "next_RTH",
                "benchmark_summary": "top markets",
                "top_agents": [{"agent_id": "markets", "accuracy_pct": 40.0, "edge_score": 0.2}],
                "weak_agents": [],
            }
        ),
        encoding="utf-8",
    )
    (hist / "prediction_accuracy.json").write_text(json.dumps({"agents": {}}), encoding="utf-8")
    (hist / "prediction_pending.json").write_text(json.dumps({"predictions": [{}]}), encoding="utf-8")
    (hist / "pipeline_runs.json").write_text(
        json.dumps({"runs": [{"cycle_id": "c1", "at": "2026-09-05T00:00:00Z", "agents_ok": 2, "agents_total": 2}]}),
        encoding="utf-8",
    )
    (tmp_path / "output" / "markets.json").write_text(
        json.dumps(
            {
                "meta": {"analyzed_at": "2026-09-05T00:00:00Z", "expert_summary": "neutral tape"},
                "market_signals": [
                    {"bias": "BULLISH", "tickers": ["SPY"], "reason": "breadth", "confidence": 0.6}
                ],
            }
        ),
        encoding="utf-8",
    )
    data = gather_agent_info(tmp_path)
    assert data["learning_count"] == 1
    assert data["pending_predictions"] == 1
    assert data["boost_agents"] == ["markets"]
    ids = [a["agent_id"] for a in data["agents"]]
    assert "markets" in ids
    text = format_text(data)
    assert "markets" in text
    assert "SHOULD_NOT_APPEAR" not in text
    assert "account_id_key" not in json.dumps(data)
