"""Agent personality traits — config-driven style modifiers for signals and fusion."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"
PERSONALITIES_FILE = CONFIG_DIR / "agent_personalities.json"
PERSONALITIES_LOCAL_FILE = CONFIG_DIR / "agent_personalities.local.json"
PERSONALITIES_LEARNED_FILE = CONFIG_DIR / "agent_personalities.learned.json"
PERSONALITIES_EXAMPLE_FILE = CONFIG_DIR / "agent_personalities.example.json"

LEARN_BLEND = 0.35
MAX_TRAIT_DELTA = 0.22

TRAIT_KEYS = (
    "risk_appetite",
    "conviction",
    "patience",
    "contrarian",
    "defensive_bias",
    "volatility_tolerance",
)

BIAS_ORDER = ("BEARISH", "NEUTRAL", "BULLISH")
BIAS_SCORES = {"BEARISH": -1.0, "NEUTRAL": 0.0, "BULLISH": 1.0}
SCORE_BIAS_THRESHOLDS = (-0.35, 0.35)

DEFAULT_TRAITS: dict[str, float] = {
    "risk_appetite": 0.5,
    "conviction": 0.5,
    "patience": 0.5,
    "contrarian": 0.5,
    "defensive_bias": 0.5,
    "volatility_tolerance": 0.5,
}

_PLATFORM_DEFAULTS: dict[str, dict[str, Any]] = {
    "markets": {"label": "The Momentum Hawk", "risk_appetite": 0.82, "conviction": 0.72, "patience": 0.35, "contrarian": 0.18, "defensive_bias": 0.22, "volatility_tolerance": 0.70},
    "finance": {"label": "The Opportunity Scout", "risk_appetite": 0.78, "conviction": 0.68, "patience": 0.40, "contrarian": 0.25, "defensive_bias": 0.20, "volatility_tolerance": 0.65},
    "financial-data": {"label": "The Statistician", "risk_appetite": 0.55, "conviction": 0.80, "patience": 0.62, "contrarian": 0.45, "defensive_bias": 0.35, "volatility_tolerance": 0.55},
    "datascience": {"label": "The Quant", "risk_appetite": 0.58, "conviction": 0.76, "patience": 0.58, "contrarian": 0.40, "defensive_bias": 0.30, "volatility_tolerance": 0.60},
    "sales-analytics": {"label": "The Retail Reader", "risk_appetite": 0.64, "conviction": 0.66, "patience": 0.48, "contrarian": 0.30, "defensive_bias": 0.28, "volatility_tolerance": 0.52},
    "geopolitics": {"label": "The Risk Sentinel", "risk_appetite": 0.28, "conviction": 0.74, "patience": 0.70, "contrarian": 0.55, "defensive_bias": 0.78, "volatility_tolerance": 0.35},
    "events": {"label": "The Headline Watch", "risk_appetite": 0.32, "conviction": 0.62, "patience": 0.45, "contrarian": 0.48, "defensive_bias": 0.62, "volatility_tolerance": 0.38},
    "agriculture": {"label": "The Crop Watcher", "risk_appetite": 0.44, "conviction": 0.66, "patience": 0.74, "contrarian": 0.36, "defensive_bias": 0.52, "volatility_tolerance": 0.46},
    "census": {"label": "The Demographer", "risk_appetite": 0.42, "conviction": 0.70, "patience": 0.76, "contrarian": 0.32, "defensive_bias": 0.48, "volatility_tolerance": 0.44},
    "sec-filings": {"label": "The Disclosure Analyst", "risk_appetite": 0.38, "conviction": 0.78, "patience": 0.68, "contrarian": 0.42, "defensive_bias": 0.56, "volatility_tolerance": 0.40},
    "migration": {"label": "The Flow Tracker", "risk_appetite": 0.40, "conviction": 0.72, "patience": 0.70, "contrarian": 0.44, "defensive_bias": 0.50, "volatility_tolerance": 0.42},
    "trading-economics": {"label": "The Macro Reader", "risk_appetite": 0.46, "conviction": 0.74, "patience": 0.64, "contrarian": 0.40, "defensive_bias": 0.46, "volatility_tolerance": 0.48},
    "corporate-credit": {"label": "The Credit Desk", "risk_appetite": 0.40, "conviction": 0.78, "patience": 0.66, "contrarian": 0.38, "defensive_bias": 0.62, "volatility_tolerance": 0.44},
    "patents": {"label": "The Innovation Scout", "risk_appetite": 0.70, "conviction": 0.60, "patience": 0.80, "contrarian": 0.35, "defensive_bias": 0.25, "volatility_tolerance": 0.58},
    "electricity": {"label": "The Grid Steward", "risk_appetite": 0.38, "conviction": 0.68, "patience": 0.72, "contrarian": 0.22, "defensive_bias": 0.70, "volatility_tolerance": 0.42},
    "grid": {"label": "The Cautious Engineer", "risk_appetite": 0.36, "conviction": 0.70, "patience": 0.74, "contrarian": 0.20, "defensive_bias": 0.72, "volatility_tolerance": 0.40},
    "meteorology": {"label": "The Weather Watch", "risk_appetite": 0.34, "conviction": 0.64, "patience": 0.55, "contrarian": 0.28, "defensive_bias": 0.68, "volatility_tolerance": 0.45},
    "transportation": {"label": "The Infrastructure Analyst", "risk_appetite": 0.46, "conviction": 0.62, "patience": 0.68, "contrarian": 0.30, "defensive_bias": 0.55, "volatility_tolerance": 0.48},
    "logistics": {"label": "The Freight Tracker", "risk_appetite": 0.50, "conviction": 0.60, "patience": 0.60, "contrarian": 0.38, "defensive_bias": 0.48, "volatility_tolerance": 0.50},
    "theoretical-probability": {"label": "The Theorist", "risk_appetite": 0.48, "conviction": 0.82, "patience": 0.75, "contrarian": 0.52, "defensive_bias": 0.40, "volatility_tolerance": 0.55},
    "empirical-probability": {"label": "The Experimentalist", "risk_appetite": 0.52, "conviction": 0.78, "patience": 0.70, "contrarian": 0.46, "defensive_bias": 0.38, "volatility_tolerance": 0.58},
    "combined-conditional": {"label": "The Conditional Thinker", "risk_appetite": 0.50, "conviction": 0.80, "patience": 0.72, "contrarian": 0.50, "defensive_bias": 0.36, "volatility_tolerance": 0.54},
    "research-statistics": {"label": "The Research Scientist", "risk_appetite": 0.45, "conviction": 0.84, "patience": 0.78, "contrarian": 0.48, "defensive_bias": 0.34, "volatility_tolerance": 0.50},
    "order-execution": {"label": "The Execution Purist", "risk_appetite": 0.30, "conviction": 0.90, "patience": 0.40, "contrarian": 0.15, "defensive_bias": 0.60, "volatility_tolerance": 0.25},
    "data-steward": {"label": "The Steward", "risk_appetite": 0.40, "conviction": 0.88, "patience": 0.85, "contrarian": 0.20, "defensive_bias": 0.50, "volatility_tolerance": 0.30},
    "records-management": {"label": "The Archivist", "risk_appetite": 0.35, "conviction": 0.86, "patience": 0.90, "contrarian": 0.18, "defensive_bias": 0.55, "volatility_tolerance": 0.28},
    "market-predictor": {"label": "The Ensemble Conductor", "risk_appetite": 0.50, "conviction": 0.75, "patience": 0.55, "contrarian": 0.35, "defensive_bias": 0.45, "volatility_tolerance": 0.50},
}


@dataclass(frozen=True)
class PersonalityTraits:
    agent_id: str
    label: str
    risk_appetite: float
    conviction: float
    patience: float
    contrarian: float
    defensive_bias: float
    volatility_tolerance: float
    voice: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "label": self.label,
            "traits": {
                "risk_appetite": self.risk_appetite,
                "conviction": self.conviction,
                "patience": self.patience,
                "contrarian": self.contrarian,
                "defensive_bias": self.defensive_bias,
                "volatility_tolerance": self.volatility_tolerance,
            },
            "voice": self.voice,
        }


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _merge_entry(agent_id: str, raw: dict[str, Any] | None) -> PersonalityTraits:
    base = dict(_PLATFORM_DEFAULTS.get(agent_id, {}))
    if raw:
        base.update(raw)
    traits = {key: _clamp(base.get(key, DEFAULT_TRAITS[key])) for key in TRAIT_KEYS}
    return PersonalityTraits(
        agent_id=agent_id,
        label=str(base.get("label") or agent_id.replace("-", " ").title()),
        voice=str(base.get("voice") or ""),
        **traits,
    )


def _config_store() -> dict[str, Any]:
    merged: dict[str, Any] = {"agents": {}}
    for agent_id, entry in _PLATFORM_DEFAULTS.items():
        merged["agents"][agent_id] = dict(entry)

    file_data = _load_json(PERSONALITIES_FILE)
    if file_data and isinstance(file_data.get("agents"), dict):
        for aid, entry in file_data["agents"].items():
            if isinstance(entry, dict):
                merged["agents"].setdefault(aid, {})
                merged["agents"][aid].update(entry)

    learned_data = _load_json(PERSONALITIES_LEARNED_FILE)
    if learned_data and isinstance(learned_data.get("agents"), dict):
        for aid, entry in learned_data["agents"].items():
            if isinstance(entry, dict):
                merged["agents"].setdefault(aid, {})
                merged["agents"][aid].update(entry)

    local_data = _load_json(PERSONALITIES_LOCAL_FILE)
    if local_data and isinstance(local_data.get("agents"), dict):
        for aid, entry in local_data["agents"].items():
            if isinstance(entry, dict):
                merged["agents"].setdefault(aid, {})
                merged["agents"][aid].update(entry)

    return merged


def _base_personality(agent_id: str) -> PersonalityTraits:
    """Platform defaults only — no learned or local overlays."""
    return _merge_entry(agent_id, _PLATFORM_DEFAULTS.get(agent_id))


def _trait_deltas(base: PersonalityTraits, tuned: dict[str, float]) -> dict[str, float]:
    return {
        key: round(tuned.get(key, getattr(base, key)) - getattr(base, key), 3)
        for key in TRAIT_KEYS
    }


def compute_learned_trait_targets(agent_id: str, learning: Any) -> dict[str, float]:
    """Map learning outcomes to target personality trait values."""
    base = _base_personality(agent_id)
    traits = {key: getattr(base, key) for key in TRAIT_KEYS}
    acc = float(learning.accuracy_pct) if learning.accuracy_pct is not None else 50.0

    if acc < 35:
        traits["conviction"] -= 0.14
        traits["risk_appetite"] -= 0.12
        traits["defensive_bias"] += 0.14
        traits["volatility_tolerance"] -= 0.08
    elif acc < 42:
        traits["conviction"] -= 0.08
        traits["risk_appetite"] -= 0.06
        traits["defensive_bias"] += 0.08
    elif acc >= 55:
        traits["conviction"] += 0.06
        if not learning.bullish_miss_rate or learning.bullish_miss_rate < 0.5:
            traits["risk_appetite"] += 0.04

    if learning.bullish_miss_rate is not None and learning.bullish_miss_rate >= 0.55:
        traits["risk_appetite"] -= min(0.16, (learning.bullish_miss_rate - 0.5) * 0.35)
        traits["contrarian"] += min(0.14, (learning.bullish_miss_rate - 0.5) * 0.28)
        traits["defensive_bias"] += 0.06

    if learning.bearish_miss_rate is not None and learning.bearish_miss_rate >= 0.55:
        traits["defensive_bias"] -= min(0.10, (learning.bearish_miss_rate - 0.5) * 0.2)
        traits["risk_appetite"] += 0.05

    blame = float(getattr(learning, "blame_score", 0.0) or 0.0)
    if blame >= 0.15:
        traits["defensive_bias"] += min(0.16, blame * 0.45)
        traits["risk_appetite"] -= min(0.14, blame * 0.4)
        traits["conviction"] -= min(0.10, blame * 0.25)

    horizon = str(getattr(learning, "preferred_horizon", "24h") or "24h")
    if horizon == "1mo":
        traits["patience"] += 0.14
    elif horizon == "1wk":
        traits["patience"] += 0.08
    elif horizon == "24h" and traits["patience"] > 0.45:
        traits["patience"] -= 0.06

    posture = str(getattr(learning, "posture", "") or "")
    if posture == "cautious":
        traits["conviction"] -= 0.05
        traits["defensive_bias"] += 0.05
    elif posture == "confident":
        traits["conviction"] += 0.04

    for key in TRAIT_KEYS:
        base_val = getattr(base, key)
        delta = traits[key] - base_val
        traits[key] = _clamp(base_val + max(-MAX_TRAIT_DELTA, min(MAX_TRAIT_DELTA, delta)))
    return traits


def sync_personality_from_learning() -> dict[str, Any]:
    """Auto-tune personality traits from agent learning outcomes."""
    from agent_learning import get_agent_learning

    learned_store = _load_json(PERSONALITIES_LEARNED_FILE) or {
        "description": "Auto-tuned personality traits from agent learning (system-managed).",
        "agents": {},
    }
    if not isinstance(learned_store.get("agents"), dict):
        learned_store["agents"] = {}

    from agents.platform_catalog import active_agent_sources

    updated = 0
    for src in active_agent_sources(check_remote=False):
        aid = src["id"]
        if aid in {"data-steward", "records-management"}:
            continue
        learning = get_agent_learning(aid)
        if learning is None:
            continue

        base = _base_personality(aid)
        targets = compute_learned_trait_targets(aid, learning)
        prior = learned_store["agents"].get(aid)
        if not isinstance(prior, dict):
            prior = {}

        blended: dict[str, Any] = {"label": base.label, "learned_from": learning.updated_at}
        changed = False
        for key in TRAIT_KEYS:
            prior_val = prior.get(key, getattr(base, key))
            target = targets[key]
            new_val = _clamp(prior_val * (1.0 - LEARN_BLEND) + target * LEARN_BLEND)
            blended[key] = round(new_val, 3)
            if abs(new_val - getattr(base, key)) >= 0.02:
                changed = True

        blended["trait_deltas"] = _trait_deltas(base, blended)
        blended["learning_posture"] = learning.posture
        blended["accuracy_pct"] = learning.accuracy_pct
        if changed or aid not in learned_store["agents"]:
            learned_store["agents"][aid] = blended
            updated += 1

    from datetime import datetime, timezone

    learned_store["updated_at"] = datetime.now(timezone.utc).isoformat()
    learned_store["agents_tuned"] = updated
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PERSONALITIES_LEARNED_FILE.write_text(json.dumps(learned_store, indent=2), encoding="utf-8")
    return learned_store


def personality_is_tuned(agent_id: str) -> bool:
    learned = _load_json(PERSONALITIES_LEARNED_FILE)
    if not isinstance(learned, dict):
        return False
    entry = (learned.get("agents") or {}).get(agent_id)
    if not isinstance(entry, dict):
        return False
    base = _base_personality(agent_id)
    deltas = _trait_deltas(base, entry)
    return any(abs(delta) >= 0.02 for delta in deltas.values())


def personality_tune_summary(agent_id: str) -> str:
    learned = _load_json(PERSONALITIES_LEARNED_FILE)
    if not isinstance(learned, dict):
        return ""
    entry = (learned.get("agents") or {}).get(agent_id)
    if not isinstance(entry, dict):
        return ""
    bits: list[str] = []
    deltas = entry.get("trait_deltas") if isinstance(entry.get("trait_deltas"), dict) else {}
    for key in ("risk_appetite", "conviction", "defensive_bias", "patience"):
        delta = deltas.get(key)
        if delta is None or abs(float(delta)) < 0.02:
            continue
        bits.append(f"{key.replace('_', ' ')} {float(delta):+.2f}")
    posture = entry.get("learning_posture")
    if posture:
        bits.append(str(posture))
    return ", ".join(bits[:4])


def get_agent_personality(agent_id: str) -> PersonalityTraits:
    store = _config_store()
    agents = store.get("agents") if isinstance(store.get("agents"), dict) else {}
    entry = agents.get(str(agent_id or "").strip())
    return _merge_entry(str(agent_id or "").strip(), entry if isinstance(entry, dict) else None)


def personality_label(agent_id: str) -> str:
    label = get_agent_personality(agent_id).label
    if personality_is_tuned(agent_id):
        return f"{label} · tuned"
    return label


def personality_summary(agent_id: str) -> str:
    traits = get_agent_personality(agent_id)
    bits = [
        f"risk {traits.risk_appetite:.0%}",
        f"conviction {traits.conviction:.0%}",
        f"patience {traits.patience:.0%}",
    ]
    if traits.contrarian >= 0.6:
        bits.append("contrarian")
    if traits.defensive_bias >= 0.6:
        bits.append("defensive")
    tune = personality_tune_summary(agent_id)
    if tune:
        bits.append(f"tuned ({tune})")
    return f"{traits.label} · " + ", ".join(bits)


def _score_to_bias(score: float) -> str:
    if score <= SCORE_BIAS_THRESHOLDS[0]:
        return "BEARISH"
    if score >= SCORE_BIAS_THRESHOLDS[1]:
        return "BULLISH"
    return "NEUTRAL"


def adjust_bias(bias: str, traits: PersonalityTraits, *, reason: str = "") -> str:
    text = str(bias or "NEUTRAL").upper()
    score = BIAS_SCORES.get(text, 0.0)
    score += (traits.risk_appetite - 0.5) * 0.45
    score -= (traits.defensive_bias - 0.5) * 0.25
    reason_l = str(reason or "").lower()
    if traits.contrarian >= 0.55 and text == "BULLISH":
        if any(word in reason_l for word in ("gainer", "momentum", "trending", "risk-on", "breadth")):
            score -= traits.contrarian * 0.35
    if traits.contrarian >= 0.55 and text == "BEARISH":
        if any(word in reason_l for word in ("loser", "oversold", "mean reversion")):
            score += traits.contrarian * 0.25
    if traits.defensive_bias >= 0.6 and "growth" in reason_l and text == "BULLISH":
        score -= 0.12
    return _score_to_bias(score)


def adjust_confidence(
    confidence: float,
    traits: PersonalityTraits,
    *,
    temperature: int | None = None,
) -> float:
    try:
        conf = float(confidence)
    except (TypeError, ValueError):
        conf = 0.5
    mult = 0.72 + 0.56 * traits.conviction
    if temperature is not None:
        mult *= 0.92 + (int(temperature) / 8.0) * 0.16
    return _clamp(conf * mult, 0.05, 0.99)


def personality_horizon_preference(agent_id: str) -> str:
    traits = get_agent_personality(agent_id)
    if traits.patience >= 0.72:
        return "1mo"
    if traits.patience >= 0.58:
        return "1wk"
    return "24h"


def personality_fusion_factor(agent_id: str, *, regime_posture: str = "neutral") -> float:
    traits = get_agent_personality(agent_id)
    posture = str(regime_posture or "neutral").lower()
    if posture == "risk-on":
        return _clamp(0.82 + 0.28 * traits.risk_appetite + 0.08 * traits.volatility_tolerance, 0.75, 1.25)
    if posture == "risk-off":
        return _clamp(0.82 + 0.28 * traits.defensive_bias + 0.06 * (1.0 - traits.risk_appetite), 0.75, 1.25)
    return _clamp(0.9 + 0.12 * traits.conviction, 0.85, 1.15)


def _patch_signal_row(row: dict[str, Any], traits: PersonalityTraits, temperature: int | None) -> None:
    if not isinstance(row, dict):
        return
    reason = str(row.get("reason") or row.get("sector") or "")
    row["bias"] = adjust_bias(str(row.get("bias", "NEUTRAL")), traits, reason=reason)
    if "confidence" in row:
        row["confidence"] = round(adjust_confidence(row.get("confidence", 0.5), traits, temperature=temperature), 3)


def _patch_predictions_block(data: dict[str, Any], traits: PersonalityTraits, temperature: int | None) -> None:
    preds = data.get("predictions")
    if not isinstance(preds, dict):
        return
    for rows in preds.values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            direction = str(row.get("predicted_direction", "flat")).lower()
            mapped = "BULLISH" if direction == "up" else "BEARISH" if direction == "down" else "NEUTRAL"
            adjusted = adjust_bias(mapped, traits, reason=str(row.get("symbol") or ""))
            row["predicted_direction"] = "up" if adjusted == "BULLISH" else "down" if adjusted == "BEARISH" else "flat"
            if "confidence" in row:
                row["confidence"] = round(adjust_confidence(row.get("confidence", 0.5), traits, temperature=temperature), 3)


def _patch_lists(data: dict[str, Any], traits: PersonalityTraits, temperature: int | None) -> None:
    for key in ("trading_opportunities", "top_picks"):
        rows = data.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            if "opportunity_score" in row:
                try:
                    score = float(row["opportunity_score"])
                except (TypeError, ValueError):
                    score = 0.0
                row["opportunity_score"] = round(_clamp(score * (0.85 + 0.3 * traits.risk_appetite), 0.0, 1.0), 3)
            if "confidence" in row:
                row["confidence"] = round(adjust_confidence(row.get("confidence", 0.5), traits, temperature=temperature), 3)


def patch_agent_output_personality(path: Path, agent_id: str) -> bool:
    """Apply personality traits to a saved agent JSON report."""
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False

    traits = get_agent_personality(agent_id)
    meta = data.setdefault("meta", {})
    if not isinstance(meta, dict):
        meta = {}
        data["meta"] = meta
    temperature = meta.get("temperature")
    try:
        temperature_i = int(temperature) if temperature is not None else None
    except (TypeError, ValueError):
        temperature_i = None

    for sig in data.get("market_signals", []) or []:
        _patch_signal_row(sig, traits, temperature_i)
    _patch_predictions_block(data, traits, temperature_i)
    _patch_lists(data, traits, temperature_i)

    meta["personality"] = traits.as_dict()
    meta["personality"]["temperature"] = temperature_i
    meta["personality"]["tuned"] = personality_is_tuned(agent_id)
    tune_summary = personality_tune_summary(agent_id)
    if tune_summary:
        meta["personality"]["tune_summary"] = tune_summary
    meta["preferred_horizon"] = personality_horizon_preference(agent_id)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True


def ensure_default_config_files() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not PERSONALITIES_EXAMPLE_FILE.exists():
        payload = {
            "description": "Default agent personality traits (0.0-1.0). Copy to agent_personalities.local.json to override.",
            "agents": _PLATFORM_DEFAULTS,
        }
        PERSONALITIES_EXAMPLE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if not PERSONALITIES_FILE.exists():
        PERSONALITIES_FILE.write_text(
            json.dumps({"agents": _PLATFORM_DEFAULTS}, indent=2),
            encoding="utf-8",
        )


ensure_default_config_files()