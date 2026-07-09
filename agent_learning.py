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

MIN_SYMBOL_SAMPLES = 5
MIN_AGENT_SAMPLES = 8
MAX_LESSONS = 3
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
    )


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
) -> AgentLearning:
    accuracy_pct = None
    by_horizon: dict[str, Any] | None = None
    if isinstance(accuracy_entry, dict):
        accuracy_pct = (
            accuracy_entry.get("combined_accuracy_pct")
            or accuracy_entry.get("weighted_accuracy_pct")
            or accuracy_entry.get("accuracy_pct")
        )
        if accuracy_pct is not None:
            accuracy_pct = float(accuracy_pct)
        by_horizon = accuracy_entry.get("by_horizon")

    recent = scored_rows[-80:]
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

    avoid_symbols, trust_symbols = _symbol_stats(recent)
    preferred_horizon = _best_horizon(by_horizon)
    posture = _posture_for(accuracy_pct, recent_miss_rate=recent_miss)
    lessons = _lessons_for(
        agent_id,
        accuracy_pct=accuracy_pct,
        bull_miss=bull_miss,
        bear_miss=bear_miss,
        preferred_horizon=preferred_horizon,
        avoid_symbols=avoid_symbols,
        blame=blame,
    )

    return AgentLearning(
        agent_id=agent_id,
        accuracy_pct=accuracy_pct,
        bias_drift=bias_drift,
        confidence_scale=confidence_scale,
        fusion_multiplier=fusion_multiplier,
        preferred_horizon=preferred_horizon,
        posture=posture,
        lessons=lessons,
        avoid_symbols=avoid_symbols,
        trust_symbols=trust_symbols,
        bullish_miss_rate=bull_miss,
        bearish_miss_rate=bear_miss,
        blame_score=round(blame, 4),
        updated_at=_now_iso(),
    )


def rebuild_agent_learning() -> dict[str, Any]:
    """Rebuild per-agent learning profiles from accuracy, benchmark, and balance blame."""
    from agents.platform_catalog import active_agent_sources

    accuracy = _load_json(ACCURACY_FILE) or {}
    benchmark = _load_json(BENCHMARK_FILE) or _load_json(SIM_FILE) or {}
    penalties = _load_json(PENALTIES_FILE) or {}

    scored_rows = list(accuracy.get("scored") or []) if isinstance(accuracy, dict) else []
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

    agents_out: dict[str, Any] = {}
    for src in active_agent_sources(check_remote=False):
        aid = src["id"]
        if aid in {"market-predictor", "data-steward", "records-management"}:
            continue
        entry = accuracy_agents.get(aid)
        if not isinstance(entry, dict) and aid in benchmark_agents:
            bench_row = benchmark_agents[aid]
            if isinstance(bench_row, dict):
                entry = {
                    "combined_accuracy_pct": bench_row.get("accuracy_pct"),
                    "accuracy_pct": bench_row.get("accuracy_pct"),
                    "by_horizon": bench_row.get("by_horizon"),
                    "total_scored": bench_row.get("total_trials"),
                }
        learning = _build_learning(
            aid,
            accuracy_entry=entry if isinstance(entry, dict) else None,
            scored_rows=by_agent_scored.get(aid, []),
            blame=blame_map.get(aid, 0.0),
        )
        total = int((entry or {}).get("total_scored") or (entry or {}).get("total") or 0)
        if total >= MIN_AGENT_SAMPLES or by_agent_scored.get(aid) or aid in benchmark_agents:
            agents_out[aid] = learning.as_dict()

    payload = {
        "meta": {
            "description": "Adaptive learning from misses, benchmark accuracy, and account attribution.",
            "updated_at": _now_iso(),
            "agents_tracked": len(agents_out),
        },
        "agents": agents_out,
    }
    _write_json(LEARNING_FILE, payload)
    try:
        from agent_personality import sync_personality_from_learning

        sync_personality_from_learning()
    except Exception:
        pass
    return payload


def get_agent_learning(agent_id: str) -> AgentLearning | None:
    store = _learning_store()
    row = (store.get("agents") or {}).get(str(agent_id or ""))
    if not isinstance(row, dict):
        return None
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

    for sig in data.get("market_signals", []) or []:
        if not isinstance(sig, dict):
            continue
        tickers = sig.get("tickers") or []
        symbol = str(tickers[0]) if tickers else ""
        sig["bias"] = adjust_bias_with_learning(str(sig.get("bias", "NEUTRAL")), learning, symbol=symbol)
        if "confidence" in sig:
            sig["confidence"] = round(
                adjust_confidence_with_learning(sig.get("confidence", 0.5), learning, symbol=symbol),
                3,
            )

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
                adjusted = adjust_bias_with_learning(mapped, learning, symbol=sym)
                row["predicted_direction"] = (
                    "up" if adjusted == "BULLISH" else "down" if adjusted == "BEARISH" else "flat"
                )
                if "confidence" in row:
                    row["confidence"] = round(
                        adjust_confidence_with_learning(row.get("confidence", 0.5), learning, symbol=sym),
                        3,
                    )

    for key in ("trading_opportunities", "top_picks"):
        rows = data.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "")
            if "confidence" in row:
                row["confidence"] = round(
                    adjust_confidence_with_learning(row.get("confidence", 0.5), learning, symbol=sym),
                    3,
                )
            if "opportunity_score" in row:
                try:
                    score = float(row["opportunity_score"])
                except (TypeError, ValueError):
                    score = 0.0
                row["opportunity_score"] = round(_clamp(score * learning.confidence_scale, 0.0, 1.0), 3)

    meta["learning"] = learning.as_dict()
    meta["preferred_horizon"] = learning.preferred_horizon
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True