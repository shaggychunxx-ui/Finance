"""Post-process agent outputs for fusion-ready signals and E*TRADE enhancement.

Applied after every agent run so all specialists emit consistent BULLISH/BEARISH
biases, preferred horizons, and enhancement requests without rewriting each expert.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BIAS_MAP = {
    "bullish": "BULLISH",
    "bear": "BEARISH",
    "bearish": "BEARISH",
    "long": "BULLISH",
    "short": "BEARISH",
    "buy": "BULLISH",
    "sell": "BEARISH",
    "risk-on": "BULLISH",
    "risk_on": "BULLISH",
    "risk-off": "BEARISH",
    "risk_off": "BEARISH",
    "up": "BULLISH",
    "down": "BEARISH",
    "positive": "BULLISH",
    "negative": "BEARISH",
    "golden-sweep": "BULLISH",
    "golden_sweep": "BULLISH",
    "defensive": "BEARISH",
    "offensive": "BULLISH",
    "neutral": "NEUTRAL",
    "mixed": "NEUTRAL",
    "flat": "NEUTRAL",
}


def normalize_bias(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return "NEUTRAL"
    upper = text.upper().replace(" ", "_")
    if upper in {"BULLISH", "BEARISH", "NEUTRAL"}:
        return upper
    lower = text.lower().strip()
    if lower in BIAS_MAP:
        return BIAS_MAP[lower]
    for key, mapped in BIAS_MAP.items():
        if lower.startswith(key) or key in lower:
            return mapped
    if "bull" in lower:
        return "BULLISH"
    if "bear" in lower or "short" in lower:
        return "BEARISH"
    return "NEUTRAL"


def _load(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def optimize_agent_output(path: Path, agent_id: str = "") -> dict[str, Any] | None:
    """Normalize market_signals, inject horizon, queue E*TRADE enhancement."""
    data = _load(path)
    if not data:
        return None

    aid = str(agent_id or "").replace("_", "-")
    horizon = "24h"
    try:
        from agent_groups import agent_horizon

        horizon = agent_horizon(aid) if aid else "24h"
    except Exception:
        pass

    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    if not isinstance(meta, dict):
        meta = {}
    meta.setdefault("preferred_horizon", horizon)
    if aid:
        meta.setdefault("agent_id", aid)
    data["meta"] = meta

    signals = data.get("market_signals")
    if not isinstance(signals, list):
        signals = []
    enhanced: list[dict[str, Any]] = list(data.get("enhance_symbols") or [])
    seen_enhance: set[str] = set()
    for row in enhanced:
        if isinstance(row, dict) and row.get("symbol"):
            seen_enhance.add(str(row["symbol"]).upper())

    optimized: list[dict[str, Any]] = []
    for sig in signals:
        if not isinstance(sig, dict):
            continue
        row = dict(sig)
        row["bias"] = normalize_bias(row.get("bias"))
        row.setdefault("preferred_horizon", horizon)
        conf = row.get("confidence")
        if conf is None:
            # Mild default conviction so fusion can weight specialists
            if row["bias"] == "NEUTRAL":
                row.setdefault("confidence", 0.45)
            else:
                row.setdefault("confidence", 0.58)
        tickers = row.get("tickers") or row.get("symbols") or []
        if isinstance(tickers, str):
            tickers = [tickers]
        clean: list[str] = []
        for t in tickers:
            sym = str(t or "").strip().upper()
            if not sym or sym.startswith("^"):
                continue
            clean.append(sym)
            if row["bias"] in {"BULLISH", "BEARISH"} and sym not in seen_enhance:
                seen_enhance.add(sym)
                enhanced.append(
                    {
                        "symbol": sym,
                        "priority": 0.72 if row["bias"] == "BULLISH" else 0.68,
                        "reason": f"{aid or 'agent'} {row['bias']} signal",
                        "source": aid or "optimize_output",
                    }
                )
        if clean:
            row["tickers"] = clean
        optimized.append(row)

    data["market_signals"] = optimized
    if enhanced:
        data["enhance_symbols"] = enhanced

    # Opportunities / trading_opportunities ticker enhancement
    for key in ("trading_opportunities", "opportunities"):
        rows = data.get(key)
        if not isinstance(rows, list):
            continue
        for opp in rows:
            if not isinstance(opp, dict):
                continue
            sym = str(opp.get("symbol") or "").strip().upper()
            if not sym or sym in seen_enhance:
                continue
            seen_enhance.add(sym)
            score = float(opp.get("opportunity_score") or opp.get("score") or 0.5)
            enhanced.append(
                {
                    "symbol": sym,
                    "priority": min(0.9, 0.65 + score * 0.2),
                    "reason": f"{aid or 'agent'} opportunity",
                    "source": aid or "optimize_output",
                }
            )
        if enhanced:
            data["enhance_symbols"] = enhanced

    _write(path, data)
    return data
