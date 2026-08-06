#!/usr/bin/env python3
"""Finance learning loop health check (live root: C:\\Users\\shagg\\Finance).

Reports pending vs scored predictions, agent_learning population, and fusion wiring.
Usage (from Finance root, venv):
  python tools/learning_health.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app_paths import OUTPUT  # noqa: E402

HISTORY = OUTPUT / "history"


def _load(name: str) -> dict:
    path = HISTORY / name
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def main() -> int:
    pending = _load("prediction_pending.json")
    accuracy = _load("prediction_accuracy.json")
    learning = _load("agent_learning.json")
    policy = _load("learning_policy.json")
    fusion = _load("fusion_weights.json")

    preds = pending.get("predictions") or []
    scored = accuracy.get("scored") or []
    agents_learn = learning.get("agents") or {}
    null_px = sum(1 for p in preds if isinstance(p, dict) and p.get("price_at_prediction") is None)
    horizons = Counter(str(p.get("horizon") or "?") for p in preds if isinstance(p, dict))

    now = datetime.now(timezone.utc)
    ages = []
    for p in preds:
        if not isinstance(p, dict):
            continue
        raw = p.get("recorded_at")
        if not raw:
            continue
        try:
            t = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            ages.append((now - t).total_seconds() / 3600.0)
        except ValueError:
            pass

    print("=== Finance learning health ===")
    print(f"history: {HISTORY}")
    print(f"pending: {len(preds)}  null_price: {null_px}  horizons: {dict(horizons)}")
    if ages:
        ages_sorted = sorted(ages)
        print(
            f"pending age hours: min={ages_sorted[0]:.2f} "
            f"med={ages_sorted[len(ages_sorted)//2]:.2f} max={ages_sorted[-1]:.2f}"
        )
    print(f"scored rows: {len(scored)}  pending_count field: {accuracy.get('pending_count')}")
    print(f"live_accuracy: {accuracy.get('live_accuracy')}")
    print(f"agent_learning agents_tracked: {learning.get('meta', {}).get('agents_tracked')} "
          f"live_scored_rows: {learning.get('meta', {}).get('live_scored_rows')}")
    print(f"learning agents keys: {len(agents_learn)}")
    print(f"policy boost/cut: {policy.get('boost_agents')} / {policy.get('cut_agents')}")
    print(f"fusion_weights present: {bool(fusion)} size_bytes: "
          f"{(HISTORY / 'fusion_weights.json').stat().st_size if (HISTORY / 'fusion_weights.json').exists() else 0}")

    # Wiring smoke (imports)
    try:
        from agent_fusion import fusion_weight
        from agent_learning import learning_fusion_factor, get_agent_learning
        from agent_personality import sync_personality_from_learning

        factor = learning_fusion_factor("markets")
        fw = fusion_weight("markets", horizon="24h", regime_posture="neutral")
        print(f"wiring OK: learning_fusion_factor('markets')={factor} fusion_weight={fw}")
        print(f"get_agent_learning('markets')={get_agent_learning('markets')}")
        sync_personality_from_learning()
        print("wiring OK: fusion + personality consume agent_learning")
    except Exception as e:
        print(f"WIRING ERROR: {e}")
        return 1

    print()
    if len(scored) == 0 and ages and max(ages) < 24:
        print("STATUS: WAITING — predictions not mature yet (need ~24h for 24h horizon).")
        print("        Prices backfilled / fusion wiring present. Learning fills after scoring.")
    elif len(scored) == 0:
        print("STATUS: STUCK — mature pending but 0 scored. Run score_matured_predictions.")
    elif not agents_learn:
        print("STATUS: SCORED but learning empty — run rebuild_agent_learning().")
    else:
        print("STATUS: HEALTHY — learning agents populated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
