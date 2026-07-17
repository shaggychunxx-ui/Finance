#!/usr/bin/env python3
"""Agent groups, roles, and conduct rules — single source of organizational truth.

Groups control:
  - UI category labels
  - fusion clusters
  - preferred horizons
  - trading posture (long-lean / short-lean / risk / neutral / platform)
  - default personality traits
  - whether directional accuracy scoring applies
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Group definitions
# ---------------------------------------------------------------------------

AGENT_GROUPS: dict[str, dict[str, Any]] = {
    "markets_core": {
        "label": "Markets & Core Trading",
        "cluster": "macro",
        "category": "Markets & Finance",
        "horizon": "24h",
        "posture": "long_lean",
        "generalist": True,
        "directional": True,
        "trading_role": "alpha",
        "conduct": (
            "Trade liquid equities/ETFs. Prefer clear momentum and opportunity signals. "
            "Emit BULLISH/BEARISH/NEUTRAL with ticker lists. Bias to growth when evidence is strong; "
            "do not force shorts."
        ),
        "traits": {
            "risk_appetite": 0.72,
            "conviction": 0.70,
            "patience": 0.40,
            "contrarian": 0.28,
            "defensive_bias": 0.28,
            "volatility_tolerance": 0.62,
        },
    },
    "quant_stats": {
        "label": "Quant & Statistics",
        "cluster": "quant",
        "category": "Probability & Stats",
        "horizon": "1wk",
        "posture": "neutral",
        "generalist": True,
        "directional": True,
        "trading_role": "alpha",
        "conduct": (
            "Be statistically rigorous. Prefer calibrated probabilities over narratives. "
            "Only take directional stands when edge exceeds noise; otherwise NEUTRAL."
        ),
        "traits": {
            "risk_appetite": 0.50,
            "conviction": 0.80,
            "patience": 0.72,
            "contrarian": 0.48,
            "defensive_bias": 0.38,
            "volatility_tolerance": 0.55,
        },
    },
    "macro_index": {
        "label": "Macro & Global Indices",
        "cluster": "macro",
        "category": "Macro & Indices",
        "horizon": "1mo",
        "posture": "neutral",
        "generalist": True,
        "directional": True,
        "trading_role": "regime",
        "conduct": (
            "Frame regime (risk-on/off), rates, inflation, and global indices. "
            "Signals should map to index/sector ETFs and macro proxies, not random single names."
        ),
        "traits": {
            "risk_appetite": 0.48,
            "conviction": 0.72,
            "patience": 0.70,
            "contrarian": 0.40,
            "defensive_bias": 0.48,
            "volatility_tolerance": 0.46,
        },
    },
    "intelligence": {
        "label": "Intelligence & Events",
        "cluster": "intelligence",
        "category": "Intelligence",
        "horizon": "1wk",
        "posture": "defensive",
        "generalist": True,
        "directional": True,
        "trading_role": "risk_overlay",
        "conduct": (
            "Surface event and disclosure risk. Prefer BEARISH/defensive when severity is high. "
            "Do not chase momentum; protect capital when headlines are adverse."
        ),
        "traits": {
            "risk_appetite": 0.34,
            "conviction": 0.70,
            "patience": 0.58,
            "contrarian": 0.48,
            "defensive_bias": 0.68,
            "volatility_tolerance": 0.40,
        },
    },
    "infrastructure": {
        "label": "Energy, Grid & Infrastructure",
        "cluster": "energy_grid",
        "category": "Energy & Infrastructure",
        "horizon": "1wk",
        "posture": "domain_specialist",
        "generalist": False,
        "directional": True,
        "trading_role": "sector_specialist",
        "conduct": (
            "Stay in energy/utilities/ag/infra universe. Domain-first signals only. "
            "Map physical stress (grid, weather, crops, freight) to listed sector tickers."
        ),
        "traits": {
            "risk_appetite": 0.40,
            "conviction": 0.68,
            "patience": 0.72,
            "contrarian": 0.28,
            "defensive_bias": 0.62,
            "volatility_tolerance": 0.45,
        },
    },
    "transport_logistics": {
        "label": "Transport & Logistics",
        "cluster": "transport_logistics",
        "category": "Energy & Infrastructure",
        "horizon": "1wk",
        "posture": "domain_specialist",
        "generalist": False,
        "directional": True,
        "trading_role": "sector_specialist",
        "conduct": (
            "Focus on freight, shipping, rails, airlines. Stress = BEARISH for transport beta; "
            "easing congestion = BULLISH for logistics names."
        ),
        "traits": {
            "risk_appetite": 0.48,
            "conviction": 0.62,
            "patience": 0.64,
            "contrarian": 0.34,
            "defensive_bias": 0.50,
            "volatility_tolerance": 0.50,
        },
    },
    "consumer": {
        "label": "Consumer & Retail",
        "cluster": "consumer",
        "category": "Markets & Finance",
        "horizon": "1wk",
        "posture": "long_lean",
        "generalist": False,
        "directional": True,
        "trading_role": "sector_specialist",
        "conduct": (
            "Track retail sales, sentiment, and consumer staples/discretionary. "
            "Weakening demand → BEARISH retailers; resilient spend → BULLISH leaders."
        ),
        "traits": {
            "risk_appetite": 0.55,
            "conviction": 0.64,
            "patience": 0.52,
            "contrarian": 0.32,
            "defensive_bias": 0.40,
            "volatility_tolerance": 0.48,
        },
    },
    "day_trading": {
        "label": "Day Trading & Microstructure",
        "cluster": "execution",
        "category": "Day Trading",
        "horizon": "24h",
        "posture": "intraday",
        "generalist": True,
        "directional": True,
        "trading_role": "intraday",
        "conduct": (
            "Optimize same-session edge. High urgency, low patience. Favor liquid names. "
            "Flatten risk before close. Do not promote multi-week swing holds."
        ),
        "traits": {
            "risk_appetite": 0.76,
            "conviction": 0.58,
            "patience": 0.22,
            "contrarian": 0.28,
            "defensive_bias": 0.28,
            "volatility_tolerance": 0.74,
        },
    },
    "short_mechanics": {
        "label": "Short-Selling Mechanics",
        "cluster": "short_mechanics",
        "category": "Short Selling",
        "horizon": "1wk",
        "posture": "short_lean",
        "generalist": True,
        "directional": True,
        "trading_role": "short_alpha",
        "conduct": (
            "Hunt short candidates: HTB stress, FTD/RegSHO, squeeze risk, structural bear theses. "
            "Default posture is skeptical of crowded longs. Prefer BEARISH or NEUTRAL over thin BULLISH. "
            "Flag squeeze risk that should *block* aggressive shorts."
        ),
        "traits": {
            "risk_appetite": 0.42,
            "conviction": 0.80,
            "patience": 0.58,
            "contrarian": 0.62,
            "defensive_bias": 0.55,
            "volatility_tolerance": 0.48,
        },
    },
    "risk_protection": {
        "label": "Risk & Capital Protection",
        "cluster": "risk",
        "category": "Risk & Protection",
        "horizon": "24h",
        "posture": "defensive",
        "generalist": True,
        "directional": True,
        "trading_role": "risk_gate",
        "conduct": (
            "Protect capital first. Raise defensive_bias on drawdowns, volatility spikes, or crowded risk. "
            "Emit BEARISH/reduce-risk signals freely; BULLISH only when risk is clearly compensated."
        ),
        "traits": {
            "risk_appetite": 0.20,
            "conviction": 0.84,
            "patience": 0.72,
            "contrarian": 0.22,
            "defensive_bias": 0.86,
            "volatility_tolerance": 0.22,
        },
    },
    "fundamental_tech": {
        "label": "Fundamental & Technical Analysis",
        "cluster": "fundamental",
        "category": "Fundamental & Technical",
        "horizon": "1mo",
        "posture": "neutral",
        "generalist": True,
        "directional": True,
        "trading_role": "alpha",
        "conduct": (
            "Combine fundamentals, patterns, regime, and adversarial debate. "
            "Multi-horizon views OK; prefer 1wk–1mo. Challenge consensus when evidence conflicts."
        ),
        "traits": {
            "risk_appetite": 0.55,
            "conviction": 0.74,
            "patience": 0.68,
            "contrarian": 0.45,
            "defensive_bias": 0.42,
            "volatility_tolerance": 0.52,
        },
    },
    "portfolio_alloc": {
        "label": "Portfolio Construction",
        "cluster": "portfolio",
        "category": "Portfolio",
        "horizon": "1mo",
        "posture": "neutral",
        "generalist": True,
        "directional": True,
        "trading_role": "allocator",
        "conduct": (
            "Think in weights, diversifiers, and frameworks — not single-name excitement. "
            "Balance growth vs defense; discourage concentration and over-trading."
        ),
        "traits": {
            "risk_appetite": 0.45,
            "conviction": 0.82,
            "patience": 0.85,
            "contrarian": 0.30,
            "defensive_bias": 0.42,
            "volatility_tolerance": 0.40,
        },
    },
    "data_platform": {
        "label": "Data Platform",
        "cluster": "data_platform",
        "category": "Data Platform",
        "horizon": "1wk",
        "posture": "platform",
        "generalist": True,
        "directional": False,
        "trading_role": "platform",
        "conduct": (
            "Do not emit directional price bets. Focus on data quality, lineage, archives, and freshness. "
            "Support other agents; never dominate fusion scores."
        ),
        "traits": {
            "risk_appetite": 0.38,
            "conviction": 0.88,
            "patience": 0.88,
            "contrarian": 0.18,
            "defensive_bias": 0.52,
            "volatility_tolerance": 0.28,
        },
    },
    "execution": {
        "label": "Order Execution",
        "cluster": "execution",
        "category": "Markets & Finance",
        "horizon": "24h",
        "posture": "execution",
        "generalist": True,
        "directional": False,
        "trading_role": "execution",
        "conduct": (
            "Optimize fill quality, slippage, and order type — not directional alpha. "
            "Warn when market impact or poor liquidity would destroy edge."
        ),
        "traits": {
            "risk_appetite": 0.30,
            "conviction": 0.90,
            "patience": 0.40,
            "contrarian": 0.15,
            "defensive_bias": 0.60,
            "volatility_tolerance": 0.25,
        },
    },
    "fusion": {
        "label": "Ensemble Fusion",
        "cluster": "fusion",
        "category": "Markets & Finance",
        "horizon": "24h",
        "posture": "neutral",
        "generalist": True,
        "directional": False,
        "trading_role": "fusion",
        "conduct": (
            "Blend other agents fairly. Do not double-count your own directional accuracy as alpha."
        ),
        "traits": {
            "risk_appetite": 0.50,
            "conviction": 0.75,
            "patience": 0.55,
            "contrarian": 0.35,
            "defensive_bias": 0.45,
            "volatility_tolerance": 0.50,
        },
    },
}

# agent_id (CLI form with hyphens) -> group_id
AGENT_TO_GROUP: dict[str, str] = {
    # Markets core
    "markets": "markets_core",
    "finance": "markets_core",
    "financial-data": "markets_core",
    "google-finance": "markets_core",
    "yahoo-finance": "markets_core",
    # Quant
    "datascience": "quant_stats",
    "theoretical-probability": "quant_stats",
    "empirical-probability": "quant_stats",
    "combined-conditional": "quant_stats",
    "research-statistics": "quant_stats",
    # Macro / indices
    "trading-economics": "macro_index",
    "census": "macro_index",
    "economy": "macro_index",
    "fred": "macro_index",
    "cpi": "macro_index",
    "ftse100": "macro_index",
    "nikkei": "macro_index",
    "consumer-sentiment": "macro_index",
    # Intelligence
    "events": "intelligence",
    "geopolitics": "intelligence",
    "patents": "intelligence",
    "sec-filings": "intelligence",
    "migration": "intelligence",
    "earthdata": "intelligence",
    # Infrastructure
    "electricity": "infrastructure",
    "grid": "infrastructure",
    "meteorology": "infrastructure",
    "agriculture": "infrastructure",
    # Transport
    "transportation": "transport_logistics",
    "logistics": "transport_logistics",
    # Consumer
    "sales-analytics": "consumer",
    # Day trading
    "day-trading-microstructure": "day_trading",
    "long-squeeze-synergy": "day_trading",
    # Short mechanics
    "bear-thesis": "short_mechanics",
    "htb-dynamics": "short_mechanics",
    "squeeze-mechanics": "short_mechanics",
    "ftd-regsho": "short_mechanics",
    "risk-mitigation": "short_mechanics",
    # Risk
    "risk-protection": "risk_protection",
    "risk-guardrail": "risk_protection",
    # Fundamental / technical
    "fundamental-analyst": "fundamental_tech",
    "technical-pattern": "fundamental_tech",
    "adversarial-debate": "fundamental_tech",
    "market-regime": "fundamental_tech",
    "sentiment-alt-data": "fundamental_tech",
    # Portfolio
    "portfolio-frameworks": "portfolio_alloc",
    "equity-structuring": "portfolio_alloc",
    "capital-return": "portfolio_alloc",
    # Platform
    "data-steward": "data_platform",
    "records-management": "data_platform",
    "content-integrity": "data_platform",
    # Execution / fusion
    "order-execution": "execution",
    "market-predictor": "fusion",
    # Factor / quant extensions (from GitHub copilot agent branches)
    "correlation-breakdown": "quant_stats",
    "momentum-reversion": "quant_stats",
    "quality-factor": "quant_stats",
    "crowding-quality": "quant_stats",
    "etf-mechanics": "quant_stats",
    # Macro extensions
    "fed-policy": "macro_index",
    "china-em-divergence": "macro_index",
    "corporate-credit": "macro_index",
    "sector-rotation": "markets_core",
    # Day-trading microstructure extensions
    "dark-pool-volume-profile": "day_trading",
    "options-flow": "day_trading",
    "market-makers": "day_trading",
    # Short / borrow extensions
    "borrow-fees": "short_mechanics",
    "margin-stress": "short_mechanics",
    # Fundamental / event extensions
    "earnings-calendar": "fundamental_tech",
    "estimate-revisions": "fundamental_tech",
    "insider-clusters": "intelligence",
}

# Optional sector/ticker domains for specialists (merged into agent_fusion.AGENT_DOMAINS)
GROUP_DOMAIN_HINTS: dict[str, dict[str, frozenset[str]]] = {
    "fred": {
        "tickers": frozenset({"SPY", "TLT", "IEF", "GLD", "UUP", "HYG", "LQD"}),
        "sectors": frozenset({"macro", "rates", "inflation", "fred", "bonds"}),
    },
    "cpi": {
        "tickers": frozenset({"TIP", "TLT", "XLP", "XLY", "GLD", "SPY"}),
        "sectors": frozenset({"inflation", "cpi", "consumer", "staples"}),
    },
    "economy": {
        "tickers": frozenset({"SPY", "QQQ", "IWM", "EEM", "TLT", "UUP"}),
        "sectors": frozenset({"macro", "economy", "global", "growth"}),
    },
    "ftse100": {
        "tickers": frozenset({"EWU", "FXB", "EFA", "IEV"}),
        "sectors": frozenset({"uk", "europe", "international", "ftse"}),
    },
    "nikkei": {
        "tickers": frozenset({"EWJ", "DXJ", "FXY"}),
        "sectors": frozenset({"japan", "asia", "nikkei", "international"}),
    },
    "consumer-sentiment": {
        "tickers": frozenset({"XLY", "XRT", "WMT", "AMZN", "MCD"}),
        "sectors": frozenset({"consumer", "retail", "sentiment"}),
    },
    "earthdata": {
        "tickers": frozenset({"DBA", "WEAT", "CORN", "XLE", "UNG", "WOOD"}),
        "sectors": frozenset({"agriculture", "climate", "energy", "commodity"}),
    },
}


def normalize_agent_id(agent_id: str) -> str:
    return str(agent_id or "").strip().replace("_", "-").lower()


def agent_group_id(agent_id: str) -> str:
    aid = normalize_agent_id(agent_id)
    return AGENT_TO_GROUP.get(aid, "markets_core")


def agent_group(agent_id: str) -> dict[str, Any]:
    gid = agent_group_id(agent_id)
    group = dict(AGENT_GROUPS.get(gid, AGENT_GROUPS["markets_core"]))
    group["id"] = gid
    return group


def agent_category(agent_id: str) -> str:
    return str(agent_group(agent_id).get("category") or "Platform")


def agent_cluster_for(agent_id: str) -> str:
    return str(agent_group(agent_id).get("cluster") or "other")


def agent_horizon(agent_id: str) -> str:
    return str(agent_group(agent_id).get("horizon") or "24h")


def agent_posture(agent_id: str) -> str:
    return str(agent_group(agent_id).get("posture") or "neutral")


def agent_trading_role(agent_id: str) -> str:
    return str(agent_group(agent_id).get("trading_role") or "alpha")


def agent_conduct(agent_id: str) -> str:
    return str(agent_group(agent_id).get("conduct") or "")


def is_generalist(agent_id: str) -> bool:
    return bool(agent_group(agent_id).get("generalist", True))


def uses_directional_scoring(agent_id: str) -> bool:
    return bool(agent_group(agent_id).get("directional", True))


def group_trait_defaults(agent_id: str) -> dict[str, float]:
    traits = agent_group(agent_id).get("traits") or {}
    return {k: float(v) for k, v in traits.items()}


def group_personality_seed(agent_id: str, *, label: str | None = None) -> dict[str, Any]:
    """Default personality entry for an agent based on its group."""
    g = agent_group(agent_id)
    traits = dict(g.get("traits") or {})
    seed = {
        "label": label or normalize_agent_id(agent_id).replace("-", " ").title(),
        "group": g.get("id"),
        "group_label": g.get("label"),
        "posture": g.get("posture"),
        "trading_role": g.get("trading_role"),
        "preferred_horizon": g.get("horizon"),
        "conduct": g.get("conduct"),
        **traits,
    }
    return seed


def agents_in_group(group_id: str) -> list[str]:
    return sorted(aid for aid, gid in AGENT_TO_GROUP.items() if gid == group_id)


def all_groups_summary() -> list[dict[str, Any]]:
    rows = []
    for gid, meta in AGENT_GROUPS.items():
        members = agents_in_group(gid)
        rows.append(
            {
                "id": gid,
                "label": meta["label"],
                "category": meta["category"],
                "cluster": meta["cluster"],
                "horizon": meta["horizon"],
                "posture": meta["posture"],
                "trading_role": meta["trading_role"],
                "member_count": len(members),
                "members": members,
                "conduct": meta["conduct"],
            }
        )
    rows.sort(key=lambda r: r["label"])
    return rows


def apply_group_conduct_to_report(data: dict[str, Any], agent_id: str) -> dict[str, Any]:
    """Stamp group metadata and soft-nudge signal biases toward group posture."""
    if not isinstance(data, dict):
        return data
    g = agent_group(agent_id)
    meta = dict(data.get("meta") or {})
    meta["agent_group"] = g.get("id")
    meta["agent_group_label"] = g.get("label")
    meta["agent_posture"] = g.get("posture")
    meta["agent_trading_role"] = g.get("trading_role")
    meta["preferred_horizon"] = g.get("horizon")
    meta["conduct"] = g.get("conduct")
    data["meta"] = meta

    posture = str(g.get("posture") or "neutral")
    if posture in {"platform", "execution", "fusion"}:
        return data

    signals = data.get("market_signals")
    if not isinstance(signals, list):
        return data

    nudged: list[dict[str, Any]] = []
    for sig in signals:
        if not isinstance(sig, dict):
            continue
        row = dict(sig)
        bias = str(row.get("bias") or "NEUTRAL").upper()
        # Normalize nonstandard biases toward NEUTRAL unless already BULLISH/BEARISH
        if bias not in {"BULLISH", "BEARISH", "NEUTRAL"}:
            if posture == "short_lean":
                bias = "BEARISH"
            elif posture == "defensive":
                bias = "BEARISH" if "risk" in bias.lower() or "stress" in bias.lower() else "NEUTRAL"
            else:
                bias = "NEUTRAL"
            row["bias"] = bias
        # Soft conduct: short-lean agents never upgrade weak bullish without high conf
        if posture == "short_lean" and bias == "BULLISH":
            conf = float(row.get("confidence") or row.get("conviction") or 0.5)
            if conf < 0.72:
                row["bias"] = "NEUTRAL"
                row["reason"] = (
                    str(row.get("reason") or "")
                    + " [group conduct: short-mechanics downgraded thin bullish]"
                ).strip()
        if posture == "defensive" and bias == "BULLISH":
            conf = float(row.get("confidence") or 0.5)
            if conf < 0.68:
                row["bias"] = "NEUTRAL"
                row["reason"] = (
                    str(row.get("reason") or "")
                    + " [group conduct: risk group requires higher bar for bullish]"
                ).strip()
        if posture == "intraday":
            row.setdefault("preferred_horizon", "24h")
        else:
            row.setdefault("preferred_horizon", g.get("horizon"))
        nudged.append(row)
    data["market_signals"] = nudged
    return data


def register_groups_into_fusion() -> None:
    """Push group membership into agent_fusion maps (call at import or pipeline start)."""
    try:
        import agent_fusion as fusion
    except Exception:
        return

    for aid, gid in AGENT_TO_GROUP.items():
        g = AGENT_GROUPS[gid]
        fusion.AGENT_CLUSTERS[aid] = str(g["cluster"])
        fusion.AGENT_DEFAULT_HORIZON[aid] = str(g["horizon"])
        if g.get("generalist"):
            # mutate frozenset via rebuild
            pass
        if not g.get("directional", True):
            # ensure skip set includes
            pass

    # Rebuild GENERALIST and DIRECTIONAL_SCORING_SKIP from groups
    generalists = {aid for aid, gid in AGENT_TO_GROUP.items() if AGENT_GROUPS[gid].get("generalist")}
    # keep legacy aliases
    generalists |= {"google-finance", "yahoo-finance"}
    fusion.GENERALIST_AGENTS = frozenset(generalists)

    skip = {
        aid
        for aid, gid in AGENT_TO_GROUP.items()
        if not AGENT_GROUPS[gid].get("directional", True)
    }
    skip |= {"etrade", "history"}
    fusion.DIRECTIONAL_SCORING_SKIP = frozenset(skip)

    # Merge domain hints
    for aid, domain in GROUP_DOMAIN_HINTS.items():
        fusion.AGENT_DOMAINS.setdefault(aid, domain)


# Auto-register on import so pipeline/fusion stay consistent
try:
    register_groups_into_fusion()
except Exception:
    pass
