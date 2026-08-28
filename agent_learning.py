"""Agent learning from scored misses and benchmark outcomes — adaptive bias and confidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app_paths import OUTPUT

HISTORY_ROOT = OUTPUT / "history"
LEARNING_FILE = HISTORY_ROOT / "agent_learning.json"
ACCURACY_FILE = HISTORY_ROOT / "prediction_accuracy.json"
BENCHMARK_FILE = HISTORY_ROOT / "accuracy_benchmark.json"
SIM_FILE = HISTORY_ROOT / "historical_simulation.json"
PENALTIES_FILE = HISTORY_ROOT / "balance_penalties.json"
BRIEF_FILE = HISTORY_ROOT / "next_session_brief.json"
LEARNING_POLICY_FILE = HISTORY_ROOT / "learning_policy.json"

MIN_SYMBOL_SAMPLES = 5
MIN_AGENT_SAMPLES = 8
MAX_LESSONS = 4
MAX_SYMBOL_NOTES = 12


@dataclass(frozen=True)
class AgentLearning:
    agent_id: str
    accuracy_pct: float | None
    bias_drift: float
    confidence_scale: float
    fusion_multiplier: float
    preferred_horizon: str
    posture: str
    lessons: tuple[str, ...]
    avoid_symbols: frozenset[str]
    trust_symbols: frozenset[str]
    bullish_miss_rate: float | None
    bearish_miss_rate: float | None
    blame_score: float
    updated_at: str
    # Enriched from walk-forward trial journal / benchmark
    edge_score: float = 0.0
    sample_trials: int = 0
    horizon_weights: tuple[tuple[str, float], ...] = ()
    min_confidence_to_emit: float = 0.35
    source: str = "mixed"
    live_accuracy_pct: float | None = None
    proxy_accuracy_pct: float | None = None
    replay_accuracy_pct: float | None = None
    proxy_edge_score: float = 0.0
    family: str = ""
    avg_net_return_pct: float | None = None
    live_sample_trials: int = 0
    proxy_sample_trials: int = 0
    replay_sample_trials: int = 0
    by_regime: tuple[tuple[str, float], ...] = ()
    brier_score: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "accuracy_pct": self.accuracy_pct,
            "bias_drift": round(self.bias_drift, 4),
            "confidence_scale": round(self.confidence_scale, 4),
            "fusion_multiplier": round(self.fusion_multiplier, 4),
            "preferred_horizon": self.preferred_horizon,
            "posture": self.posture,
            "lessons": list(self.lessons),
            "avoid_symbols": sorted(self.avoid_symbols),
            "trust_symbols": sorted(self.trust_symbols),
            "bullish_miss_rate": self.bullish_miss_rate,
            "bearish_miss_rate": self.bearish_miss_rate,
            "blame_score": round(self.blame_score, 4),
            "edge_score": round(self.edge_score, 4),
            "sample_trials": int(self.sample_trials),
            "horizon_weights": {h: round(w, 4) for h, w in self.horizon_weights},
            "min_confidence_to_emit": round(self.min_confidence_to_emit, 4),
            "source": self.source,
            "live_accuracy_pct": self.live_accuracy_pct,
            "proxy_accuracy_pct": self.proxy_accuracy_pct,
            "replay_accuracy_pct": self.replay_accuracy_pct,
            "proxy_edge_score": round(self.proxy_edge_score, 4),
            "family": self.family,
            "avg_net_return_pct": self.avg_net_return_pct,
            "live_sample_trials": int(self.live_sample_trials),
            "proxy_sample_trials": int(self.proxy_sample_trials),
            "replay_sample_trials": int(self.replay_sample_trials),
            "by_regime": {k: round(v, 4) for k, v in self.by_regime},
            "brier_score": self.brier_score,
            "updated_at": self.updated_at,
        }


def _load_json(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _default_learning(agent_id: str) -> AgentLearning:
    return AgentLearning(
        agent_id=agent_id,
        accuracy_pct=None,
        bias_drift=0.0,
        confidence_scale=1.0,
        fusion_multiplier=1.0,
        preferred_horizon="24h",
        posture="neutral",
        lessons=(),
        avoid_symbols=frozenset(),
        trust_symbols=frozenset(),
        bullish_miss_rate=None,
        bearish_miss_rate=None,
        blame_score=0.0,
        updated_at=_now_iso(),
        edge_score=0.0,
        sample_trials=0,
        horizon_weights=(),
        min_confidence_to_emit=0.35,
        source="default",
    )


def _horizon_weights_from_rows(rows: list[dict[str, Any]]) -> tuple[tuple[str, float], ...]:
    by_h: dict[str, dict[str, int]] = {}
    for row in rows:
        h = str(row.get("horizon") or "")
        if not h:
            continue
        bucket = by_h.setdefault(h, {"total": 0, "hits": 0})
        bucket["total"] += 1
        bucket["hits"] += 1 if row.get("hit") else 0
    weights: list[tuple[str, float]] = []
    for h, bucket in by_h.items():
        total = bucket["total"]
        if total < 4:
            continue
        acc = bucket["hits"] / total
        # Map accuracy to a relative weight centered near 0.45 coin-ish baseline.
        w = _clamp(0.55 + (acc - 0.30) * 1.4, 0.45, 1.35)
        weights.append((h, w))
    weights.sort(key=lambda item: item[1], reverse=True)
    return tuple(weights[:6])


def _edge_score(accuracy_pct: float | None, samples: int) -> float:
    if accuracy_pct is None or samples < MIN_AGENT_SAMPLES:
        return 0.0
    # Shrink toward 25% prior until samples grow.
    prior = 25.0
    n = min(200, max(0, samples))
    shrink = n / (n + 40.0)
    blended = prior * (1.0 - shrink) + float(accuracy_pct) * shrink
    # Edge vs 30% soft floor used for ranking (not trading guarantee).
    return round((blended - 30.0) / 20.0, 4)


def _learning_store() -> dict[str, Any]:
    data = _load_json(LEARNING_FILE)
    if isinstance(data, dict):
        data.setdefault("agents", {})
        return data
    return {"agents": {}, "updated_at": _now_iso()}


def _direction_stats(rows: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    bull_total = bull_miss = bear_total = bear_miss = 0
    for row in rows:
        predicted = str(row.get("predicted_direction", "flat")).lower()
        hit = bool(row.get("hit"))
        if predicted == "up":
            bull_total += 1
            bull_miss += 0 if hit else 1
        elif predicted == "down":
            bear_total += 1
            bear_miss += 0 if hit else 1
    bull_rate = round(bull_miss / bull_total, 3) if bull_total >= 4 else None
    bear_rate = round(bear_miss / bear_total, 3) if bear_total >= 4 else None
    return bull_rate, bear_rate


def _symbol_stats(rows: list[dict[str, Any]]) -> tuple[frozenset[str], frozenset[str]]:
    by_symbol: dict[str, dict[str, int]] = {}
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if not sym:
            continue
        bucket = by_symbol.setdefault(sym, {"total": 0, "hits": 0})
        bucket["total"] += 1
        bucket["hits"] += 1 if row.get("hit") else 0
    avoid: set[str] = set()
    trust: set[str] = set()
    for sym, bucket in by_symbol.items():
        total = bucket["total"]
        if total < MIN_SYMBOL_SAMPLES:
            continue
        acc = bucket["hits"] / total
        if acc < 0.35:
            avoid.add(sym)
        elif acc >= 0.55:
            trust.add(sym)
    return frozenset(sorted(avoid)[:MAX_SYMBOL_NOTES]), frozenset(sorted(trust)[:MAX_SYMBOL_NOTES])


def _best_horizon(by_horizon: dict[str, Any] | None) -> str:
    if not isinstance(by_horizon, dict):
        return "24h"
    best_h = "24h"
    best_acc = -1.0
    for horizon, row in by_horizon.items():
        if not isinstance(row, dict):
            continue
        total = int(row.get("total") or 0)
        if total < 4:
            continue
        hits = int(row.get("hits") or 0)
        acc = hits / total
        if acc > best_acc:
            best_acc = acc
            best_h = str(horizon)
    return best_h


def _posture_for(accuracy_pct: float | None, *, recent_miss_rate: float | None) -> str:
    acc = accuracy_pct if accuracy_pct is not None else 50.0
    if acc >= 55 and (recent_miss_rate is None or recent_miss_rate <= 0.45):
        return "confident"
    if acc >= 42 and (recent_miss_rate is None or recent_miss_rate <= 0.55):
        return "calibrated"
    if acc < 35 or (recent_miss_rate is not None and recent_miss_rate >= 0.65):
        return "cautious"
    return "learning"


def _lessons_for(
    agent_id: str,
    *,
    accuracy_pct: float | None,
    bull_miss: float | None,
    bear_miss: float | None,
    preferred_horizon: str,
    avoid_symbols: frozenset[str],
    blame: float,
) -> tuple[str, ...]:
    lessons: list[str] = []
    if accuracy_pct is not None and accuracy_pct < 40:
        lessons.append(f"Overall accuracy {accuracy_pct:.0f}% — reduce conviction on weak calls.")
    if bull_miss is not None and bull_miss >= 0.6:
        lessons.append("Too bullish: missed upward calls often; favor neutral/down on momentum.")
    if bear_miss is not None and bear_miss >= 0.6:
        lessons.append("Too bearish: missed downward calls often; avoid over-defensive bias.")
    if preferred_horizon != "24h":
        lessons.append(f"Best results on {preferred_horizon} horizon — weight longer view.")
    if avoid_symbols:
        preview = ", ".join(sorted(avoid_symbols)[:4])
        suffix = "…" if len(avoid_symbols) > 4 else ""
        lessons.append(f"Weak on {preview}{suffix} — lower confidence there.")
    if blame >= 0.2:
        lessons.append("Account drawdown partly attributed here — defensive posture applied.")
    if not lessons:
        lessons.append("Track record stable — keep calibrated signals.")
    return tuple(lessons[:MAX_LESSONS])


def _build_learning(
    agent_id: str,
    *,
    accuracy_entry: dict[str, Any] | None,
    scored_rows: list[dict[str, Any]],
    blame: float = 0.0,
    source: str = "mixed",
) -> AgentLearning:
    accuracy_pct = None
    by_horizon: dict[str, Any] | None = None
    sample_trials = 0
    if isinstance(accuracy_entry, dict):
        accuracy_pct = (
            accuracy_entry.get("combined_accuracy_pct")
            or accuracy_entry.get("weighted_accuracy_pct")
            or accuracy_entry.get("accuracy_pct")
        )
        if accuracy_pct is not None:
            accuracy_pct = float(accuracy_pct)
        by_horizon = accuracy_entry.get("by_horizon")
        sample_trials = int(
            accuracy_entry.get("total_scored")
            or accuracy_entry.get("total_trials")
            or accuracy_entry.get("total")
            or 0
        )

    recent = scored_rows[-200:] if scored_rows else []
    if not sample_trials:
        sample_trials = len(scored_rows)
    recent_miss = None
    if recent:
        misses = sum(1 for row in recent if not row.get("hit"))
        recent_miss = misses / len(recent)

    bull_miss, bear_miss = _direction_stats(recent)
    bias_drift = 0.0
    if bull_miss is not None and bull_miss >= 0.55:
        bias_drift -= min(0.35, (bull_miss - 0.5) * 0.5)
    if bear_miss is not None and bear_miss >= 0.55:
        bias_drift += min(0.35, (bear_miss - 0.5) * 0.5)
    if blame >= 0.15:
        bias_drift -= min(0.2, blame * 0.25)

    acc = accuracy_pct if accuracy_pct is not None else 50.0
    confidence_scale = _clamp(0.55 + acc / 100.0 * 0.55, 0.55, 1.12)
    if recent_miss is not None and recent_miss > 0.55:
        confidence_scale *= _clamp(1.0 - (recent_miss - 0.5) * 0.45, 0.7, 1.0)
    if blame >= 0.2:
        confidence_scale *= _clamp(1.0 - blame * 0.35, 0.65, 1.0)

    fusion_multiplier = _clamp(0.55 + acc / 100.0 * 0.75, 0.55, 1.25)
    if recent_miss is not None:
        fusion_multiplier *= _clamp(1.0 - max(0.0, recent_miss - 0.5) * 0.5, 0.65, 1.0)
    fusion_multiplier *= _clamp(1.0 - blame * 0.4, 0.6, 1.0)
    edge = _edge_score(accuracy_pct, sample_trials)
    # Nudge fusion with edge so night walk-forward leaders gain a bit more weight.
    fusion_multiplier *= _clamp(1.0 + edge * 0.12, 0.85, 1.15)

    avoid_symbols, trust_symbols = _symbol_stats(recent)
    preferred_horizon = _best_horizon(by_horizon)
    # Prefer trial-derived horizon when available
    hz_weights = _horizon_weights_from_rows(recent)
    if hz_weights:
        preferred_horizon = hz_weights[0][0]
    posture = _posture_for(accuracy_pct, recent_miss_rate=recent_miss)
    lessons = list(
        _lessons_for(
            agent_id,
            accuracy_pct=accuracy_pct,
            bull_miss=bull_miss,
            bear_miss=bear_miss,
            preferred_horizon=preferred_horizon,
            avoid_symbols=avoid_symbols,
            blame=blame,
        )
    )
    if edge <= -0.25:
        lessons.insert(0, "Walk-forward edge weak — require cluster agreement / lower size.")
    elif edge >= 0.35:
        lessons.insert(0, "Walk-forward edge positive — eligible for higher fusion weight.")
    lessons = lessons[:MAX_LESSONS]

    min_conf = 0.35
    if accuracy_pct is not None and accuracy_pct < 28:
        min_conf = 0.48
    elif accuracy_pct is not None and accuracy_pct >= 40:
        min_conf = 0.30

    return AgentLearning(
        agent_id=agent_id,
        accuracy_pct=accuracy_pct,
        bias_drift=bias_drift,
        confidence_scale=confidence_scale,
        fusion_multiplier=fusion_multiplier,
        preferred_horizon=preferred_horizon,
        posture=posture,
        lessons=tuple(lessons),
        avoid_symbols=avoid_symbols,
        trust_symbols=trust_symbols,
        bullish_miss_rate=bull_miss,
        bearish_miss_rate=bear_miss,
        blame_score=round(blame, 4),
        updated_at=_now_iso(),
        edge_score=edge,
        sample_trials=sample_trials,
        horizon_weights=hz_weights,
        min_confidence_to_emit=min_conf,
        source=source,
    )


def rebuild_agent_learning() -> dict[str, Any]:
    """Rebuild per-agent learning from live accuracy, walk-forward journal, and blame."""
    from agents.platform_catalog import active_agent_sources

    accuracy = _load_json(ACCURACY_FILE) or {}
    benchmark = _load_json(BENCHMARK_FILE) or _load_json(SIM_FILE) or {}
    penalties = _load_json(PENALTIES_FILE) or {}

    scored_rows = list(accuracy.get("scored") or []) if isinstance(accuracy, dict) else []
    # Merge durable backtest trials (night continuous full-day loop).
    try:
        from backtest_trial_store import load_recent_trials

        trial_rows = load_recent_trials(max_rows=25_000)
    except Exception:
        trial_rows = []

    accuracy_agents = accuracy.get("agents") if isinstance(accuracy.get("agents"), dict) else {}
    benchmark_agents = benchmark.get("agents") if isinstance(benchmark.get("agents"), dict) else {}
    blame_map = {
        str(aid): float((row or {}).get("blame_score") or 0.0)
        for aid, row in ((penalties.get("agents") or {}).items() if isinstance(penalties, dict) else [])
        if isinstance(row, dict)
    }

    by_agent_scored: dict[str, list[dict[str, Any]]] = {}
    for row in scored_rows:
        if not isinstance(row, dict):
            continue
        aid = str(row.get("agent_id") or "")
        if aid:
            by_agent_scored.setdefault(aid, []).append(row)
    for row in trial_rows:
        if not isinstance(row, dict):
            continue
        aid = str(row.get("agent_id") or "")
        if aid:
            by_agent_scored.setdefault(aid, []).append(row)

    agents_out: dict[str, Any] = {}
    for src in active_agent_sources(check_remote=False):
        aid = src["id"]
        if aid in {"market-predictor", "data-steward", "records-management"}:
            continue
        from agent_fusion import agent_uses_directional_accuracy

        source = "live"
        entry = accuracy_agents.get(aid) if agent_uses_directional_accuracy(aid) else None
        if not isinstance(entry, dict) and aid in benchmark_agents:
            bench_row = benchmark_agents[aid]
            if isinstance(bench_row, dict):
                source = "walk_forward"
                entry = {
                    "combined_accuracy_pct": bench_row.get("accuracy_pct"),
                    "accuracy_pct": bench_row.get("accuracy_pct"),
                    "by_horizon": bench_row.get("by_horizon"),
                    "total_scored": bench_row.get("total_trials"),
                    "total_trials": bench_row.get("total_trials"),
                }
        elif isinstance(entry, dict) and aid in benchmark_agents:
            # Blend: prefer live entry but fill horizon gaps from benchmark.
            source = "live+walk_forward"
            bench_row = benchmark_agents[aid]
            if isinstance(bench_row, dict):
                if not entry.get("by_horizon") and bench_row.get("by_horizon"):
                    entry = dict(entry)
                    entry["by_horizon"] = bench_row.get("by_horizon")
                if not entry.get("total_scored") and bench_row.get("total_trials"):
                    entry = dict(entry)
                    entry["total_scored"] = bench_row.get("total_trials")

        agent_rows = by_agent_scored.get(aid, [])
        learning = _build_learning(
            aid,
            accuracy_entry=entry if isinstance(entry, dict) else None,
            scored_rows=agent_rows,
            blame=blame_map.get(aid, 0.0),
            source=source if agent_rows or entry else "default",
        )
        total = int((entry or {}).get("total_scored") or (entry or {}).get("total") or 0)
        if total >= MIN_AGENT_SAMPLES or agent_rows or aid in benchmark_agents:
            agents_out[aid] = learning.as_dict()

    try:
        from backtest_trial_store import load_latest_cycle_meta

        trial_meta = load_latest_cycle_meta()
    except Exception:
        trial_meta = {}

    payload = {
        "meta": {
            "description": (
                "Adaptive learning from live misses, night walk-forward trials, "
                "benchmark accuracy, and account attribution."
            ),
            "updated_at": _now_iso(),
            "agents_tracked": len(agents_out),
            "trial_journal": trial_meta,
            "live_scored_rows": len(scored_rows),
            "backtest_trial_rows_merged": len(trial_rows),
        },
        "agents": agents_out,
    }
    _write_json(LEARNING_FILE, payload)
    _write_learning_policy(agents_out, trial_meta=trial_meta)
    try:
        from agent_personality import sync_personality_from_learning

        sync_personality_from_learning()
    except Exception:
        pass
    return payload


def _write_learning_policy(agents_out: dict[str, Any], *, trial_meta: dict[str, Any]) -> None:
    """Compact machine-readable policy for fusion / sleeves."""
    ranked = sorted(
        (
            (aid, float(row.get("edge_score") or 0.0), float(row.get("accuracy_pct") or 0.0))
            for aid, row in agents_out.items()
            if isinstance(row, dict)
        ),
        key=lambda item: (item[1], item[2]),
        reverse=True,
    )
    boost = [aid for aid, edge, _ in ranked[:8] if edge > 0]
    cut = [aid for aid, edge, _ in ranked if edge <= -0.2][:12]
    policy = {
        "updated_at": _now_iso(),
        "source_cycle": trial_meta.get("cycle_id"),
        "global": {
            "min_accuracy_pct": 28.0,
            "min_trials": MIN_AGENT_SAMPLES,
            "description": "Derived from latest agent_learning rebuild.",
        },
        "boost_agents": boost,
        "cut_agents": cut,
        "agents": {
            aid: {
                "preferred_horizon": row.get("preferred_horizon"),
                "fusion_multiplier": row.get("fusion_multiplier"),
                "edge_score": row.get("edge_score"),
                "min_confidence_to_emit": row.get("min_confidence_to_emit"),
                "avoid_symbols": row.get("avoid_symbols") or [],
                "trust_symbols": row.get("trust_symbols") or [],
            }
            for aid, row in agents_out.items()
            if isinstance(row, dict)
        },
    }
    _write_json(LEARNING_POLICY_FILE, policy)


def write_next_session_brief(*, benchmark: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write a compact brief for the next RTH pipeline open."""
    store = _learning_store()
    agents = store.get("agents") if isinstance(store.get("agents"), dict) else {}
    if not agents:
        store = rebuild_agent_learning()
        agents = store.get("agents") if isinstance(store.get("agents"), dict) else {}

    ranked = sorted(
        (
            {
                "agent_id": aid,
                "accuracy_pct": row.get("accuracy_pct"),
                "edge_score": row.get("edge_score"),
                "posture": row.get("posture"),
                "preferred_horizon": row.get("preferred_horizon"),
                "fusion_multiplier": row.get("fusion_multiplier"),
                "lessons": (row.get("lessons") or [])[:2],
            }
            for aid, row in agents.items()
            if isinstance(row, dict)
        ),
        key=lambda r: (float(r.get("edge_score") or -9), float(r.get("accuracy_pct") or 0)),
        reverse=True,
    )
    top = ranked[:8]
    bottom = list(reversed(ranked[-8:])) if len(ranked) > 8 else list(reversed(ranked))

    avoid: set[str] = set()
    trust: set[str] = set()
    for row in agents.values():
        if not isinstance(row, dict):
            continue
        for s in row.get("avoid_symbols") or []:
            avoid.add(str(s).upper())
        for s in row.get("trust_symbols") or []:
            trust.add(str(s).upper())

    bench = benchmark if isinstance(benchmark, dict) else (_load_json(BENCHMARK_FILE) or {})
    bench_meta = (bench.get("meta") or {}) if isinstance(bench, dict) else {}
    actions = [
        "Prefer boost_agents in fusion; down-weight cut_agents until edge recovers.",
        "Respect avoid_symbols on new entries; lean into trust_symbols when clusters agree.",
        "Use each agent's preferred_horizon when scoring multi-horizon ideas.",
    ]
    if top:
        actions.insert(
            0,
            f"Lead walk-forward edge: {top[0]['agent_id']} "
            f"(edge={top[0].get('edge_score')}, acc={top[0].get('accuracy_pct')}%).",
        )
    if bottom:
        actions.append(
            f"Weakest: {bottom[0]['agent_id']} — require higher confidence / cluster agreement."
        )

    try:
        from backtest_trial_store import load_latest_cycle_meta

        trial_meta = load_latest_cycle_meta()
    except Exception:
        trial_meta = {}

    policy = _load_json(LEARNING_POLICY_FILE) if LEARNING_POLICY_FILE.exists() else {}
    brief = {
        "updated_at": _now_iso(),
        "for_session": "next_RTH",
        "benchmark_summary": bench_meta.get("expert_summary"),
        "trial_cycle_id": trial_meta.get("cycle_id") or bench_meta.get("trial_cycle_id"),
        "top_agents": top,
        "weak_agents": bottom,
        "boost_agents": (policy or {}).get("boost_agents") if isinstance(policy, dict) else [t["agent_id"] for t in top[:5]],
        "cut_agents": (policy or {}).get("cut_agents") if isinstance(policy, dict) else [b["agent_id"] for b in bottom[:5]],
        "avoid_symbols": sorted(avoid)[:40],
        "trust_symbols": sorted(trust - avoid)[:40],
        "actions": actions[:8],
        "notes": [
            "Generated after walk-forward / learning rebuild.",
            "Pipeline should load this at first market-hours cycle.",
        ],
    }
    _write_json(BRIEF_FILE, brief)
    return brief


def load_next_session_brief() -> dict[str, Any]:
    data = _load_json(BRIEF_FILE)
    return data if isinstance(data, dict) else {}


def get_agent_learning(agent_id: str) -> AgentLearning | None:
    store = _learning_store()
    row = (store.get("agents") or {}).get(str(agent_id or ""))
    if not isinstance(row, dict):
        return None
    hz = row.get("horizon_weights") or {}
    if isinstance(hz, dict):
        hz_t = tuple((str(k), float(v)) for k, v in hz.items())
    else:
        hz_t = ()
    return AgentLearning(
        agent_id=str(agent_id),
        accuracy_pct=float(row["accuracy_pct"]) if row.get("accuracy_pct") is not None else None,
        bias_drift=float(row.get("bias_drift") or 0.0),
        confidence_scale=float(row.get("confidence_scale") or 1.0),
        fusion_multiplier=float(row.get("fusion_multiplier") or 1.0),
        preferred_horizon=str(row.get("preferred_horizon") or "24h"),
        posture=str(row.get("posture") or "neutral"),
        lessons=tuple(row.get("lessons") or ()),
        avoid_symbols=frozenset(row.get("avoid_symbols") or []),
        trust_symbols=frozenset(row.get("trust_symbols") or []),
        bullish_miss_rate=row.get("bullish_miss_rate"),
        bearish_miss_rate=row.get("bearish_miss_rate"),
        blame_score=float(row.get("blame_score") or 0.0),
        updated_at=str(row.get("updated_at") or ""),
        edge_score=float(row.get("edge_score") or 0.0),
        sample_trials=int(row.get("sample_trials") or 0),
        horizon_weights=hz_t,
        min_confidence_to_emit=float(row.get("min_confidence_to_emit") or 0.35),
        source=str(row.get("source") or "mixed"),
    )


def learning_label(agent_id: str) -> str:
    learning = get_agent_learning(agent_id)
    if not learning:
        return ""
    titles = {
        "cautious": "Cautious learner",
        "calibrated": "Calibrated learner",
        "confident": "Confident learner",
        "learning": "Active learner",
        "neutral": "Learner",
    }
    return titles.get(learning.posture, "Learner")


def learning_fusion_factor(agent_id: str) -> float:
    learning = get_agent_learning(agent_id)
    if not learning:
        return 1.0
    return _clamp(learning.fusion_multiplier, 0.55, 1.25)


def _score_to_bias(score: float) -> str:
    if score <= -0.35:
        return "BEARISH"
    if score >= 0.35:
        return "BULLISH"
    return "NEUTRAL"


def adjust_bias_with_learning(
    bias: str,
    learning: AgentLearning | None,
    *,
    symbol: str = "",
) -> str:
    if learning is None:
        return str(bias or "NEUTRAL").upper()
    text = str(bias or "NEUTRAL").upper()
    from agent_personality import BIAS_SCORES

    score = BIAS_SCORES.get(text, 0.0)
    score += learning.bias_drift
    sym = str(symbol or "").upper()
    if sym and sym in learning.avoid_symbols:
        score *= 0.82
        if text == "BULLISH":
            score -= 0.08
    if sym and sym in learning.trust_symbols:
        score *= 1.05
    return _score_to_bias(score)


def adjust_confidence_with_learning(
    confidence: float,
    learning: AgentLearning | None,
    *,
    symbol: str = "",
) -> float:
    try:
        conf = float(confidence)
    except (TypeError, ValueError):
        conf = 0.5
    if learning is None:
        return _clamp(conf, 0.05, 0.99)
    conf *= learning.confidence_scale
    sym = str(symbol or "").upper()
    if sym and sym in learning.avoid_symbols:
        conf *= 0.78
    if sym and sym in learning.trust_symbols:
        conf *= 1.08
    return _clamp(conf, 0.05, 0.99)


def patch_agent_output_learning(path: Path, agent_id: str) -> bool:
    """Apply learned corrections to a saved agent JSON report."""
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False

    learning = get_agent_learning(agent_id)
    if learning is None:
        rebuild_agent_learning()
        learning = get_agent_learning(agent_id)
    if learning is None:
        return False

    meta = data.setdefault("meta", {})
    if not isinstance(meta, dict):
        meta = {}
        data["meta"] = meta

    min_conf = float(learning.min_confidence_to_emit or 0.35)
    suppressed = 0

    def _apply_dir_conf(bias: str, conf: float, symbol: str) -> tuple[str, float, bool]:
        nonlocal suppressed
        b = adjust_bias_with_learning(bias, learning, symbol=symbol)
        c = adjust_confidence_with_learning(conf, learning, symbol=symbol)
        gate = False
        if c < min_conf and b != "NEUTRAL":
            b = "NEUTRAL"
            gate = True
            suppressed += 1
        return b, c, gate

    for sig in data.get("market_signals", []) or []:
        if not isinstance(sig, dict):
            continue
        tickers = sig.get("tickers") or []
        symbol = str(tickers[0]) if tickers else ""
        bias, conf, gated = _apply_dir_conf(
            str(sig.get("bias", "NEUTRAL")),
            float(sig.get("confidence") or 0.5),
            symbol,
        )
        sig["bias"] = bias
        if "confidence" in sig or gated:
            sig["confidence"] = round(conf, 3)
        if gated:
            sig["learning_suppressed"] = True

    preds = data.get("predictions")
    if isinstance(preds, dict):
        for rows in preds.values():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                sym = str(row.get("symbol") or "")
                direction = str(row.get("predicted_direction", "flat")).lower()
                mapped = "BULLISH" if direction == "up" else "BEARISH" if direction == "down" else "NEUTRAL"
                adjusted, conf, gated = _apply_dir_conf(mapped, float(row.get("confidence") or 0.5), sym)
                row["predicted_direction"] = (
                    "up" if adjusted == "BULLISH" else "down" if adjusted == "BEARISH" else "flat"
                )
                if "confidence" in row or gated:
                    row["confidence"] = round(conf, 3)
                if gated:
                    row["learning_suppressed"] = True

    for key in ("trading_opportunities", "top_picks"):
        rows = data.get(key)
        if not isinstance(rows, list):
            continue
        kept: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").upper()
            if sym and sym in learning.avoid_symbols:
                suppressed += 1
                continue
            if "confidence" in row:
                conf = adjust_confidence_with_learning(row.get("confidence", 0.5), learning, symbol=sym)
                if conf < min_conf:
                    suppressed += 1
                    continue
                row["confidence"] = round(conf, 3)
            if "opportunity_score" in row:
                try:
                    score = float(row["opportunity_score"])
                except (TypeError, ValueError):
                    score = 0.0
                row["opportunity_score"] = round(_clamp(score * learning.confidence_scale, 0.0, 1.0), 3)
            kept.append(row)
        data[key] = kept

    meta["learning"] = learning.as_dict()
    meta["preferred_horizon"] = learning.preferred_horizon
    meta["learning_applied"] = True
    meta["learning_suppressed_signals"] = suppressed
    meta["learning_edge_score"] = learning.edge_score
    try:
        from agent_temperature import apply_temperature_to_result

        data = apply_temperature_to_result(
            data,
            agent_id,
            pipeline_context={
                "posture": learning.posture,
                "accuracy_pct": learning.accuracy_pct,
            },
        )
    except Exception:
        pass
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True


def load_learning_policy() -> dict[str, Any]:
    data = _load_json(LEARNING_POLICY_FILE)
    return data if isinstance(data, dict) else {}


def learning_avoid_trust_symbols() -> tuple[set[str], set[str]]:
    """Union avoid/trust across agents + next_session_brief for sleeve filters."""
    avoid: set[str] = set()
    trust: set[str] = set()
    store = _learning_store()
    agents = store.get("agents") if isinstance(store.get("agents"), dict) else {}
    for row in agents.values():
        if not isinstance(row, dict):
            continue
        for s in row.get("avoid_symbols") or []:
            avoid.add(str(s).upper())
        for s in row.get("trust_symbols") or []:
            trust.add(str(s).upper())
    brief = load_next_session_brief()
    for s in brief.get("avoid_symbols") or []:
        avoid.add(str(s).upper())
    for s in brief.get("trust_symbols") or []:
        trust.add(str(s).upper())
    trust -= avoid
    return avoid, trust


def policy_fusion_multiplier(agent_id: str, *, for_trading: bool = False) -> float:
    """Hard gates from learning_policy: boost leaders, cut weak walk-forward agents."""
    policy = load_learning_policy()
    aid = str(agent_id or "")
    if not aid:
        return 1.0
    boost = {str(x) for x in (policy.get("boost_agents") or [])}
    cut = {str(x) for x in (policy.get("cut_agents") or [])}
    agents = policy.get("agents") if isinstance(policy.get("agents"), dict) else {}
    row = agents.get(aid) if isinstance(agents.get(aid), dict) else {}
    mult = 1.0
    if aid in boost:
        mult *= 1.12
    if aid in cut:
        # Trading paths are stricter so weak backtest agents don't drive orders.
        mult *= 0.35 if for_trading else 0.55
    edge = row.get("edge_score")
    try:
        if edge is not None and float(edge) <= -0.35:
            mult *= 0.5 if for_trading else 0.7
    except (TypeError, ValueError):
        pass
    return _clamp(mult, 0.0, 1.35)