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
    print(f"backtest_trial_rows_merged: {learning.get('meta', {}).get('backtest_trial_rows_merged')}")
    print(f"policy boost/cut: {policy.get('boost_agents')} / {policy.get('cut_agents')}")
    print(f"fusion_weights present: {bool(fusion)} size_bytes: "
          f"{(HISTORY / 'fusion_weights.json').stat().st_size if (HISTORY / 'fusion_weights.json').exists() else 0}")

    poisoned = 0
    unique_sim = set()
    live_proxy_deltas = []
    for aid, row in agents_learn.items():
        if not isinstance(row, dict):
            continue
        live_pct = row.get("live_accuracy_pct")
        proxy_pct = row.get("proxy_accuracy_pct")
        live_n = int(row.get("live_sample_trials") or 0)
        if live_pct is not None and proxy_pct is not None and live_n >= 8:
            delta = float(proxy_pct) - float(live_pct)
            live_proxy_deltas.append((aid, round(delta, 1), live_pct, proxy_pct))
            if aid in (policy.get("boost_agents") or []) and delta >= 12:
                poisoned += 1
    if live_proxy_deltas:
        live_proxy_deltas.sort(key=lambda x: abs(x[1]), reverse=True)
        print("live vs proxy accuracy (top 8 |delta|):")
        for aid, delta, live_pct, proxy_pct in live_proxy_deltas[:8]:
            print(f"  {aid}: live={live_pct}% proxy={proxy_pct}% delta={delta}")
    print(f"boost-vs-proxy poison flags: {poisoned}")
    try:
        from backtest_trial_store import JSONL_FILE, load_latest_cycle_meta, load_recent_trials

        meta = load_latest_cycle_meta()
        print(f"latest trial cycle: {meta.get('cycle_id')} window_end={ (meta.get('meta') or {}).get('window_end') }")
        for row in load_recent_trials(max_rows=4000)[:4000]:
            unique_sim.add(str(row.get("simulated_at") or "")[:10])
        print(f"unique simulated_at dates in recent journal: {len(unique_sim)}")
    except Exception as exc:
        print(f"trial journal: unavailable ({exc})")
    full_day = HISTORY / "full_day_backtest.json"
    print(f"full_day_2000 report present: {full_day.exists()}")

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
