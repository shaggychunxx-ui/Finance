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
        "etrade-ipo-mail",
    }
)

# Explicit quant-lane core (always scheduled when present in runners).
# Order = run priority within quant (asset-class trackers first).
QUANT_CORE_AGENTS: tuple[str, ...] = (
    "equity-tracker",
    "bond-markets",
    "etf-tracker",
    "markets",
    "massive-market",
    "finance",
    "financial-data",
    "sector-rotation",
    "etf-mechanics",
    "corporate-credit",
    "fed-policy",
    "market-regime",
    "technical-pattern",
    "fundamental-analyst",
    "momentum-reversion",
    "quality-factor",
)

# Membership set (everything else not in critical/flow/research still → quant).
QUANT_AGENTS: frozenset[str] = frozenset(QUANT_CORE_AGENTS)

# Unlisted agents still fall into *quant* so new specialists run.

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
        "description": "Markets, macro, stats, factors, technicals, equity/bond/ETF trackers.",
        "priority": 1,
        "parallel_ok": True,
        "timeout_sec": 700,
        "stall_sec": 55,
        "agent_timeout_sec": 50,
        "agents": QUANT_AGENTS,  # core listed; residual still filled dynamically
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

# ---------------------------------------------------------------------------
# Off-hours ECO mode — sparse lanes, core agents only, long intervals
# ---------------------------------------------------------------------------
# When pipeline_eco_mode_off_hours is on (default), nights/weekends still run
# a light pipeline instead of a full RTH roster (saves CPU, Yahoo, disk).

ECO_LANE_SCHEDULE: dict[str, dict[str, int]] = {
    # 0 off_hours = lane disabled in eco session
    "critical": {"off_hours": 90},
    "quant": {"off_hours": 120},
    "flow": {"off_hours": 0},
    "research": {"off_hours": 240},
}

ECO_LANES: frozenset[str] = frozenset({"critical", "quant", "research"})

# Minimal critical set (skip day microstructure overnight)
ECO_CRITICAL_AGENTS: tuple[str, ...] = (
    "risk-guardrail",
    "risk-protection",
    "order-execution",
)

# Asset-class trackers + thin market core
ECO_QUANT_AGENTS: tuple[str, ...] = (
    "equity-tracker",
    "bond-markets",
    "etf-tracker",
    "markets",
    "massive-market",
    "market-regime",
    "finance",
)

ECO_RESEARCH_AGENTS: tuple[str, ...] = (
    "data-steward",
    "records-management",
)

ECO_AGENT_TIMEOUT_SEC = 35
ECO_PIPELINE_TIMEOUT_SEC = 600
ECO_PIPELINE_STALL_SEC = 120


def pipeline_eco_mode_enabled(settings: dict[str, Any] | None = None) -> bool:
    """Config default True — off-hours use eco roster/schedule."""
    if isinstance(settings, dict) and "pipeline_eco_mode_off_hours" in settings:
        return bool(settings.get("pipeline_eco_mode_off_hours"))
    import os

    env = str(os.environ.get("FINANCE_PIPELINE_ECO_MODE", "1")).strip().lower()
    return env not in {"0", "false", "no", "off"}


def is_eco_session(
    settings: dict[str, Any] | None = None,
    *,
    market_open: bool,
    pre_open: bool = False,
) -> bool:
    """True outside RTH and pre-open when eco mode is enabled."""
    if market_open or pre_open:
        return False
    return pipeline_eco_mode_enabled(settings)


def eco_session_from_env() -> bool:
    """Child processes inherit eco via FINANCE_PIPELINE_ECO=1."""
    import os

    return str(os.environ.get("FINANCE_PIPELINE_ECO", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def eco_lanes_allowed() -> frozenset[str]:
    return ECO_LANES


def filter_lanes_for_eco(lanes: list[str]) -> list[str]:
    """Drop flow + any lane with eco off_hours=0."""
    allowed = eco_lanes_allowed()
    out: list[str] = []
    for pid in lanes:
        p = str(pid).strip().lower()
        if p not in allowed:
            continue
        iv = int(ECO_LANE_SCHEDULE.get(p, {}).get("off_hours", 0) or 0)
        if iv <= 0:
            continue
        out.append(p)
    return out


def eco_agents_for_lane(pipeline_id: str) -> tuple[str, ...]:
    pid = str(pipeline_id or "").strip().lower()
    if pid == "critical":
        return ECO_CRITICAL_AGENTS
    if pid == "quant":
        return ECO_QUANT_AGENTS
    if pid == "research":
        return ECO_RESEARCH_AGENTS
    return ()


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
    # QUANT_CORE_AGENTS and all other unlisted specialists → quant
    return "quant"


def _order_quant_agents(residual: list[str]) -> list[str]:
    """Put QUANT_CORE_AGENTS first (asset-class trackers), then remaining quant ids."""
    residual_norm = [normalize_agent_id(a) for a in residual]
    present = set(residual_norm)
    ordered: list[str] = []
    for aid in QUANT_CORE_AGENTS:
        if aid in present and aid not in ordered:
            ordered.append(aid)
    for aid in residual_norm:
        if aid not in ordered:
            ordered.append(aid)
    return ordered


def agents_for_pipeline(
    pipeline_id: str,
    all_agent_ids: list[str] | None = None,
    *,
    eco_mode: bool | None = None,
) -> list[str]:
    """Return ordered agent ids for a lane.

    If all_agent_ids is provided, filter to those present (catalog order preserved,
    except quant which prioritizes QUANT_CORE_AGENTS).

    eco_mode:
        When True (or FINANCE_PIPELINE_ECO=1), only the eco roster runs per lane.
    """
    if eco_mode is None:
        eco_mode = eco_session_from_env()
    pid = str(pipeline_id or "").strip().lower()

    if eco_mode:
        eco_wanted = {normalize_agent_id(a) for a in eco_agents_for_lane(pid)}
        if not eco_wanted:
            return []
        if all_agent_ids is None:
            return list(eco_agents_for_lane(pid))
        present = {normalize_agent_id(a) for a in all_agent_ids}
        return [a for a in eco_agents_for_lane(pid) if a in present]

    if pid == "critical":
        wanted = CRITICAL_AGENTS
    elif pid == "flow":
        wanted = FLOW_AGENTS
    elif pid == "research":
        wanted = RESEARCH_AGENTS
    elif pid == "quant":
        if not all_agent_ids:
            # Core list only when no catalog provided (still explicit membership)
            return list(QUANT_CORE_AGENTS)
        residual = [a for a in all_agent_ids if pipeline_id_for_agent(a) == "quant"]
        return _order_quant_agents(residual)
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
    eco_mode: bool | None = None,
) -> int:
    """Resolve how often a lane should run given market session + optional config override.

    Returns 0 when eco mode disables the lane (caller should skip it).
    """
    pid = str(pipeline_id or "").strip().lower()
    if eco_mode is None and not market_open:
        eco_mode = is_eco_session(settings, market_open=False, pre_open=False)
    if eco_mode and not market_open:
        # Prefer explicit eco block in config, else ECO_LANE_SCHEDULE
        cfg_eco: dict[str, Any] = {}
        if isinstance(settings, dict):
            raw_eco = settings.get("pipeline_lanes_eco") or settings.get("eco_lane_schedule") or {}
            if isinstance(raw_eco, dict) and isinstance(raw_eco.get(pid), dict):
                cfg_eco = raw_eco[pid]
            # Also allow pipeline_lanes[pid].eco_off_hours
            raw = settings.get("pipeline_lanes") or {}
            if isinstance(raw, dict) and isinstance(raw.get(pid), dict):
                lane_cfg = raw[pid]
                if "eco_off_hours" in lane_cfg:
                    cfg_eco = {**cfg_eco, "off_hours": lane_cfg.get("eco_off_hours")}
        eco_default = int(ECO_LANE_SCHEDULE.get(pid, {}).get("off_hours", 120) or 0)
        val = cfg_eco.get("off_hours") if "off_hours" in cfg_eco else eco_default
        try:
            minutes = int(val)
        except (TypeError, ValueError):
            minutes = eco_default
        return max(0, minutes)

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
