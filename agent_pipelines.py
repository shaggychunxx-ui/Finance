"""Named multi-pipeline layout for Finance agents.

Four lanes with different SLAs and isolation:

  critical  — risk gates + day microstructure + execution (runs first, serial)
  quant     — markets, macro, factors, fundamentals (Yahoo/stats bulk)
  flow      — options / dark pool / short-mechanics (Yahoo-heavy, kill-happy)
  research  — intelligence, infra, platform, capital structure (proxy-friendly)

Unlisted agents fall into *quant* so new specialists still run.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Explicit membership (CLI agent ids with hyphens)
# ---------------------------------------------------------------------------

CRITICAL_AGENTS: frozenset[str] = frozenset(
    {
        "risk-guardrail",
        "risk-protection",
        "risk-mitigation",
        "day-trading-microstructure",
        "order-execution",
    }
)

FLOW_AGENTS: frozenset[str] = frozenset(
    {
        "options-flow",
        "market-makers",
        "long-squeeze-synergy",
        "margin-stress",
    }
)

RESEARCH_AGENTS: frozenset[str] = frozenset(
    {
        "events",
        "geopolitics",
        "patents",
        "migration",
        "earthdata",
        "electricity",
        "grid",
        "meteorology",
        "agriculture",
        "transportation",
        "data-steward",
        "records-management",
        "content-integrity",
        "capital-return",
        "portfolio-frameworks",
        "equity-structuring",
        "ipo-monitor",
        "ipo-debut",
    }
)

# Everything else → quant (markets, macro, probability, technical, etc.)

PIPELINE_SPECS: dict[str, dict[str, Any]] = {
    "critical": {
        "id": "critical",
        "label": "Critical Risk & Execution",
        "description": "Risk gates, day microstructure, order execution — must finish first.",
        "priority": 0,
        "parallel_ok": False,
        "timeout_sec": 360,
        "stall_sec": 50,
        "agent_timeout_sec": 40,
        "agents": CRITICAL_AGENTS,
        # How often this lane should refresh (minutes). Tuned for data quality:
        # critical stays hot in RTH for day-trading safety.
        "interval_market_minutes": 5,
        "interval_off_hours_minutes": 30,
    },
    "quant": {
        "id": "quant",
        "label": "Quant & Markets",
        "description": "Markets, macro, stats, factors, technicals.",
        "priority": 1,
        "parallel_ok": True,
        "timeout_sec": 700,
        "stall_sec": 55,
        "agent_timeout_sec": 50,
        "agents": frozenset(),  # filled dynamically = residual
        # Slightly less frequent than critical → fewer Yahoo collisions, better bars.
        "interval_market_minutes": 10,
        "interval_off_hours_minutes": 45,
    },
    "flow": {
        "id": "flow",
        "label": "Flow & Short Mechanics",
        "description": "Options flow, MM, squeeze synergy, margin stress — Yahoo-heavy.",
        "priority": 1,
        "parallel_ok": True,
        "timeout_sec": 480,
        "stall_sec": 50,
        "agent_timeout_sec": 45,
        "agents": FLOW_AGENTS,
        # Options chains rate-limit hard; fewer runs = more complete chains.
        "interval_market_minutes": 15,
        "interval_off_hours_minutes": 90,
    },
    "research": {
        "id": "research",
        "label": "Research & Platform",
        "description": "Intel, infra, steward, capital structure — fail-open preferred.",
        "priority": 1,
        "parallel_ok": True,
        "timeout_sec": 600,
        "stall_sec": 55,
        # Keep research agents short — meteorology/earthdata can hang Yahoo/HTTP.
        "agent_timeout_sec": 40,
        "agents": RESEARCH_AGENTS,
        # Slow-moving sources; still refresh at least a few times per day.
        "interval_market_minutes": 90,
        "interval_off_hours_minutes": 120,
    },
}


# Default schedule block for background_worker config (minutes).
DEFAULT_LANE_SCHEDULE: dict[str, dict[str, int]] = {
    "critical": {"market": 5, "off_hours": 30},
    "quant": {"market": 10, "off_hours": 45},
    "flow": {"market": 15, "off_hours": 90},
    "research": {"market": 60, "off_hours": 90},
}


def normalize_agent_id(agent_id: str) -> str:
    return str(agent_id or "").strip().replace("_", "-").lower()


def pipeline_id_for_agent(agent_id: str) -> str:
    aid = normalize_agent_id(agent_id)
    if aid in CRITICAL_AGENTS:
        return "critical"
    if aid in FLOW_AGENTS:
        return "flow"
    if aid in RESEARCH_AGENTS:
        return "research"
    # Fusion/predictor handled post-lanes, not a lane member
    if aid in {"market-predictor", "accuracy-benchmark", "historical-sim"}:
        return "post"
    return "quant"


def agents_for_pipeline(pipeline_id: str, all_agent_ids: list[str] | None = None) -> list[str]:
    """Return ordered agent ids for a lane.

    If all_agent_ids is provided, filter to those present (catalog order preserved).
    """
    pid = str(pipeline_id or "").strip().lower()
    if pid == "critical":
        wanted = CRITICAL_AGENTS
    elif pid == "flow":
        wanted = FLOW_AGENTS
    elif pid == "research":
        wanted = RESEARCH_AGENTS
    elif pid == "quant":
        if not all_agent_ids:
            return []
        return [a for a in all_agent_ids if pipeline_id_for_agent(a) == "quant"]
    else:
        return []

    if all_agent_ids is None:
        return sorted(wanted)
    return [a for a in all_agent_ids if normalize_agent_id(a) in wanted]


def pipeline_spec(pipeline_id: str) -> dict[str, Any]:
    pid = str(pipeline_id or "").strip().lower()
    base = dict(PIPELINE_SPECS.get(pid) or PIPELINE_SPECS["quant"])
    base["id"] = pid if pid in PIPELINE_SPECS else "quant"
    return base


def ordered_pipeline_ids(*, parallel_phase: bool = False) -> list[str]:
    """critical first; then quant/flow/research (priority 1)."""
    if not parallel_phase:
        return ["critical", "quant", "flow", "research"]
    return ["quant", "flow", "research"]


def summarize_membership(all_agent_ids: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {k: [] for k in PIPELINE_SPECS}
    out["post"] = []
    for aid in all_agent_ids:
        pid = pipeline_id_for_agent(aid)
        out.setdefault(pid, []).append(normalize_agent_id(aid))
    return out


def lane_interval_minutes(
    pipeline_id: str,
    *,
    market_open: bool,
    settings: dict[str, Any] | None = None,
) -> int:
    """Resolve how often a lane should run given market session + optional config override."""
    pid = str(pipeline_id or "").strip().lower()
    spec = PIPELINE_SPECS.get(pid) or {}
    default_m = int(spec.get("interval_market_minutes") or DEFAULT_LANE_SCHEDULE.get(pid, {}).get("market", 15))
    default_o = int(
        spec.get("interval_off_hours_minutes") or DEFAULT_LANE_SCHEDULE.get(pid, {}).get("off_hours", 60)
    )
    cfg = {}
    if isinstance(settings, dict):
        raw = settings.get("pipeline_lanes") or settings.get("lane_schedule") or {}
        if isinstance(raw, dict):
            cfg = raw.get(pid) if isinstance(raw.get(pid), dict) else {}
    if market_open:
        return max(1, int(cfg.get("market") or cfg.get("interval_market_minutes") or default_m))
    return max(5, int(cfg.get("off_hours") or cfg.get("interval_off_hours_minutes") or default_o))
