"""Live regime for entry gates must not freeze on a stale portfolio snapshot."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import agent_fusion as af  # noqa: E402


def test_current_regime_prefers_live_markets_over_stale_portfolio() -> None:
    old = af.OUTPUT
    try:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "markets.json").write_text(
                json.dumps(
                    {
                        "assessment": {"regime": "neutral — mixed risk appetite"},
                        "metrics": {"risk_on_score": 0.5633, "trend_label": "Neutral"},
                    }
                ),
                encoding="utf-8",
            )
            (out / "portfolio.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-08-20T14:47:25.936161+00:00",
                        "regime": {
                            "label": "Risk-Off",
                            "posture": "risk-off",
                            "risk_on_score": 0.2143,
                        },
                    }
                ),
                encoding="utf-8",
            )
            af.OUTPUT = out
            regime = af.current_regime()
            assert regime["posture"] == "neutral"
            assert abs(float(regime["risk_on_score"]) - 0.5633) < 1e-6
    finally:
        af.OUTPUT = old


def test_current_regime_reads_risk_off_from_markets_metrics() -> None:
    old = af.OUTPUT
    try:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "markets.json").write_text(
                json.dumps(
                    {
                        "assessment": {"regime": "risk-off — defensives bid"},
                        "metrics": {"risk_on_score": 0.21, "trend_label": "Risk-Off"},
                    }
                ),
                encoding="utf-8",
            )
            af.OUTPUT = out
            regime = af.current_regime()
            assert regime["posture"] == "risk-off"
            assert abs(float(regime["risk_on_score"]) - 0.21) < 1e-6
    finally:
        af.OUTPUT = old


if __name__ == "__main__":
    test_current_regime_prefers_live_markets_over_stale_portfolio()
    test_current_regime_reads_risk_off_from_markets_metrics()
    print("ALL_OK")
