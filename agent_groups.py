#!/usr/bin/env python3
"""Agent groups, roles, conduct rules, and per-group scoring systems.

Groups control:
  - UI category labels
  - fusion clusters
  - preferred horizons
  - trading posture (long-lean / short-lean / risk / neutral / platform)
  - default personality traits
  - whether directional accuracy scoring applies
  - **scoring system** — how each group is graded based on its function
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Group definitions (each includes a function-specific scoring system)
# ---------------------------------------------------------------------------
#
# scoring schema:
#   mode              — scoring family (drives which KPIs matter)
#   primary_metric    — main grade key for labels / fusion preference
#   summary           — human-readable grading purpose
#   direction_weight  — share of combined score from direction hits (0–1)
#   magnitude_weight  — share from magnitude / sizing quality (0–1)
#   score_horizon     — preferred evaluation horizon (may match group horizon)
#   metrics           — weighted KPI list (weights should sum ≈ 1.0)
#   success_criteria  — short done-well description
#

def _scoring(
    *,
    mode: str,
    primary_metric: str,
    summary: str,
    metrics: list[dict[str, Any]],
    direction_weight: float = 0.6,
    magnitude_weight: float = 0.4,
    score_horizon: str = "24h",
    success_criteria: str = "",
) -> dict[str, Any]:
    """Build a normalized scoring-system dict for one group."""
    cleaned: list[dict[str, Any]] = []
    weight_sum = 0.0
    for m in metrics:
        w = float(m.get("weight") or 0.0)
        weight_sum += w
        cleaned.append(
            {
                "id": str(m["id"]),
                "weight": w,
                "label": str(m.get("label") or m["id"]),
                "description": str(m.get("description") or ""),
            }
        )
    if weight_sum > 0 and abs(weight_sum - 1.0) > 1e-6:
        for row in cleaned:
            row["weight"] = round(float(row["weight"]) / weight_sum, 4)
    dw = float(direction_weight)
    mw = float(magnitude_weight)
    total = dw + mw
    if total > 0:
        dw, mw = dw / total, mw / total
    return {
        "mode": mode,
        "primary_metric": primary_metric,
        "summary": summary,
        "direction_weight": round(dw, 4),
        "magnitude_weight": round(mw, 4),
        "score_horizon": score_horizon,
        "metrics": cleaned,
        "success_criteria": success_criteria,
    }


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
        "scoring": _scoring(
            mode="directional_alpha",
            primary_metric="opportunity_hit_rate",
            summary="Grade core market agents on liquid directional edge and opportunity capture.",
            score_horizon="24h",
            direction_weight=0.65,
            magnitude_weight=0.35,
            metrics=[
                {
                    "id": "direction_hit",
                    "weight": 0.55,
                    "label": "Direction hit rate",
                    "description": "BULLISH/BEARISH calls that match realized moves on liquid names.",
                },
                {
                    "id": "magnitude_capture",
                    "weight": 0.25,
                    "label": "Magnitude capture",
                    "description": "Whether predicted move size aligns with realized return bands.",
                },
                {
                    "id": "liquid_coverage",
                    "weight": 0.20,
                    "label": "Liquid coverage",
                    "description": "Share of signals on tradeable, liquid equities/ETFs.",
                },
            ],
            success_criteria="High hit rate on liquid opportunities without forcing thin shorts.",
        ),
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
        "scoring": _scoring(
            mode="calibration",
            primary_metric="probability_calibration",
            summary="Grade quant agents on calibration and edge-vs-noise discipline, not storytelling.",
            score_horizon="1wk",
            direction_weight=0.50,
            magnitude_weight=0.50,
            metrics=[
                {
                    "id": "direction_hit",
                    "weight": 0.40,
                    "label": "Direction hit rate",
                    "description": "Directional accuracy when a non-NEUTRAL stand is taken.",
                },
                {
                    "id": "confidence_calibration",
                    "weight": 0.35,
                    "label": "Confidence calibration",
                    "description": "High-confidence calls should hit more often than low-confidence ones.",
                },
                {
                    "id": "edge_vs_noise",
                    "weight": 0.25,
                    "label": "Edge vs noise",
                    "description": "Reward abstaining (NEUTRAL) when statistical edge is weak.",
                },
            ],
            success_criteria="Calibrated probabilities; directional only when edge exceeds noise.",
        ),
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
        "scoring": _scoring(
            mode="regime_timing",
            primary_metric="regime_alignment",
            summary="Grade macro agents on regime framing and index/ETF proxy accuracy.",
            score_horizon="1mo",
            direction_weight=0.55,
            magnitude_weight=0.45,
            metrics=[
                {
                    "id": "index_etf_direction",
                    "weight": 0.45,
                    "label": "Index/ETF direction",
                    "description": "Hits on SPY/TLT/sector and regional ETF proxies.",
                },
                {
                    "id": "regime_label_accuracy",
                    "weight": 0.35,
                    "label": "Regime label accuracy",
                    "description": "Risk-on/off and rates/inflation regime labels that match outcomes.",
                },
                {
                    "id": "proxy_discipline",
                    "weight": 0.20,
                    "label": "Macro proxy discipline",
                    "description": "Signals stay on macro/index proxies, not random single names.",
                },
            ],
            success_criteria="Correct regime map with investable index/sector ETF signals.",
        ),
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
        "scoring": _scoring(
            mode="risk_overlay",
            primary_metric="early_warning_quality",
            summary="Grade intel agents on early warning of adverse events, not momentum chasing.",
            score_horizon="1wk",
            direction_weight=0.45,
            magnitude_weight=0.55,
            metrics=[
                {
                    "id": "adverse_event_recall",
                    "weight": 0.40,
                    "label": "Adverse event recall",
                    "description": "Share of material adverse moves preceded by a defensive/BEARISH flag.",
                },
                {
                    "id": "false_alarm_control",
                    "weight": 0.30,
                    "label": "False-alarm control",
                    "description": "Penalize constant BEARISH noise when markets remain calm.",
                },
                {
                    "id": "defensive_timing",
                    "weight": 0.30,
                    "label": "Defensive timing",
                    "description": "Defensive bias rises before stress and relaxes after resolution.",
                },
            ],
            success_criteria="Catch real event risk early with controlled false-alarm rate.",
        ),
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
        "scoring": _scoring(
            mode="domain_specialist",
            primary_metric="domain_hit_rate",
            summary="Grade energy/grid/ag specialists on domain hit rate and universe adherence.",
            score_horizon="1wk",
            direction_weight=0.60,
            magnitude_weight=0.40,
            metrics=[
                {
                    "id": "domain_direction_hit",
                    "weight": 0.50,
                    "label": "Domain direction hit",
                    "description": "Directional accuracy inside energy/utilities/ag/infra tickers.",
                },
                {
                    "id": "universe_adherence",
                    "weight": 0.30,
                    "label": "Universe adherence",
                    "description": "Share of signals that stay inside the declared domain universe.",
                },
                {
                    "id": "physical_to_ticker_map",
                    "weight": 0.20,
                    "label": "Physical→ticker map",
                    "description": "Stress (grid/weather/crops) correctly maps to listed proxies.",
                },
            ],
            success_criteria="Domain-first signals with high in-universe hit rate.",
        ),
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
        "scoring": _scoring(
            mode="domain_specialist",
            primary_metric="domain_hit_rate",
            summary="Grade transport/logistics specialists on freight beta and congestion signals.",
            score_horizon="1wk",
            direction_weight=0.60,
            magnitude_weight=0.40,
            metrics=[
                {
                    "id": "domain_direction_hit",
                    "weight": 0.50,
                    "label": "Domain direction hit",
                    "description": "Hits on rails, shipping, airlines, and logistics names.",
                },
                {
                    "id": "universe_adherence",
                    "weight": 0.30,
                    "label": "Universe adherence",
                    "description": "Signals stay in transport/logistics universe.",
                },
                {
                    "id": "stress_map",
                    "weight": 0.20,
                    "label": "Stress/easing map",
                    "description": "Congestion stress → BEARISH; easing → BULLISH logistics.",
                },
            ],
            success_criteria="Correct transport beta reads tied to freight/congestion evidence.",
        ),
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
        "scoring": _scoring(
            mode="domain_specialist",
            primary_metric="domain_hit_rate",
            summary="Grade consumer/retail agents on demand reads for staples and discretionary.",
            score_horizon="1wk",
            direction_weight=0.60,
            magnitude_weight=0.40,
            metrics=[
                {
                    "id": "domain_direction_hit",
                    "weight": 0.50,
                    "label": "Retail direction hit",
                    "description": "Hits on retailers and consumer sector proxies.",
                },
                {
                    "id": "demand_signal_quality",
                    "weight": 0.30,
                    "label": "Demand signal quality",
                    "description": "Sales/sentiment evidence supports the bias.",
                },
                {
                    "id": "universe_adherence",
                    "weight": 0.20,
                    "label": "Universe adherence",
                    "description": "Signals stay in consumer/retail names.",
                },
            ],
            success_criteria="Demand-linked retail signals with solid in-sector hit rate.",
        ),
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
        "scoring": _scoring(
            mode="intraday",
            primary_metric="session_hit_rate",
            summary="Grade day-trading agents on same-session edge and liquid, flatten-by-close discipline.",
            score_horizon="24h",
            direction_weight=0.70,
            magnitude_weight=0.30,
            metrics=[
                {
                    "id": "session_direction_hit",
                    "weight": 0.50,
                    "label": "Same-session hit rate",
                    "description": "Direction accuracy on 24h / same-session horizons only.",
                },
                {
                    "id": "liquid_only_discipline",
                    "weight": 0.25,
                    "label": "Liquid-only discipline",
                    "description": "Prefer highly liquid names; penalize illiquid microstructure noise.",
                },
                {
                    "id": "session_risk_control",
                    "weight": 0.25,
                    "label": "Session risk control",
                    "description": "Does not promote multi-week holds; flatten/urgency posture holds.",
                },
            ],
            success_criteria="Same-session edge on liquid names without swing-hold leakage.",
        ),
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
        "scoring": _scoring(
            mode="short_alpha",
            primary_metric="short_candidate_quality",
            summary="Grade short-mechanics agents on bearish hit rate and squeeze-block precision.",
            score_horizon="1wk",
            direction_weight=0.50,
            magnitude_weight=0.50,
            metrics=[
                {
                    "id": "bearish_hit_rate",
                    "weight": 0.40,
                    "label": "Bearish hit rate",
                    "description": "BEARISH short theses that correctly anticipate downside.",
                },
                {
                    "id": "squeeze_block_precision",
                    "weight": 0.30,
                    "label": "Squeeze-block precision",
                    "description": "Correctly flag names where shorting is dangerous (squeeze/HTB).",
                },
                {
                    "id": "thin_bullish_control",
                    "weight": 0.30,
                    "label": "Thin-bullish control",
                    "description": "Avoid weak BULLISH upgrades; prefer NEUTRAL when thesis is thin.",
                },
            ],
            success_criteria="Quality short candidates with effective squeeze avoidance.",
        ),
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
        "scoring": _scoring(
            mode="risk_gate",
            primary_metric="capital_protection",
            summary="Grade risk agents on capital protection and drawdown avoidance, not alpha chase.",
            score_horizon="24h",
            direction_weight=0.40,
            magnitude_weight=0.60,
            metrics=[
                {
                    "id": "drawdown_avoidance",
                    "weight": 0.45,
                    "label": "Drawdown avoidance",
                    "description": "Risk-off / reduce signals that precede material portfolio drawdowns.",
                },
                {
                    "id": "risk_signal_precision",
                    "weight": 0.30,
                    "label": "Risk signal precision",
                    "description": "BEARISH/reduce calls that correspond to real stress, not noise.",
                },
                {
                    "id": "false_bullish_penalty",
                    "weight": 0.25,
                    "label": "False-bullish penalty",
                    "description": "Heavy penalty when BULLISH is emitted into elevated risk.",
                },
            ],
            success_criteria="Protect capital first; high bar for any bullish risk-on call.",
        ),
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
        "scoring": _scoring(
            mode="multi_horizon",
            primary_metric="thesis_accuracy",
            summary="Grade fundamental/technical agents on multi-horizon thesis accuracy and robustness.",
            score_horizon="1mo",
            direction_weight=0.55,
            magnitude_weight=0.45,
            metrics=[
                {
                    "id": "direction_hit",
                    "weight": 0.45,
                    "label": "Direction hit rate",
                    "description": "Hits at preferred 1wk–1mo horizons.",
                },
                {
                    "id": "multi_horizon_consistency",
                    "weight": 0.30,
                    "label": "Multi-horizon consistency",
                    "description": "Agreement quality across horizons without conflicting noise.",
                },
                {
                    "id": "adversarial_robustness",
                    "weight": 0.25,
                    "label": "Adversarial robustness",
                    "description": "Theses that survive bull/bear challenge and conflicting evidence.",
                },
            ],
            success_criteria="Robust multi-horizon theses with solid directional accuracy.",
        ),
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
        "scoring": _scoring(
            mode="allocation",
            primary_metric="portfolio_quality",
            summary="Grade allocators on diversification and risk-adjusted portfolio quality, not single-name alpha.",
            score_horizon="1mo",
            direction_weight=0.35,
            magnitude_weight=0.65,
            metrics=[
                {
                    "id": "risk_adjusted_return",
                    "weight": 0.40,
                    "label": "Risk-adjusted return",
                    "description": "Allocation frameworks that improve risk-adjusted outcomes.",
                },
                {
                    "id": "diversification",
                    "weight": 0.30,
                    "label": "Diversification",
                    "description": "Healthy weight dispersion across factors/sectors/assets.",
                },
                {
                    "id": "concentration_control",
                    "weight": 0.30,
                    "label": "Concentration control",
                    "description": "Penalize over-concentration and excessive turnover advice.",
                },
            ],
            success_criteria="Balanced weights with better risk-adjusted portfolio outcomes.",
        ),
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
        "scoring": _scoring(
            mode="platform_quality",
            primary_metric="data_health",
            summary="Grade platform agents on data freshness, completeness, and integrity — not price direction.",
            score_horizon="1wk",
            direction_weight=0.0,
            magnitude_weight=1.0,
            metrics=[
                {
                    "id": "freshness",
                    "weight": 0.35,
                    "label": "Data freshness",
                    "description": "Feeds and archives stay current within SLA.",
                },
                {
                    "id": "completeness",
                    "weight": 0.30,
                    "label": "Completeness",
                    "description": "Coverage of expected sources without silent gaps.",
                },
                {
                    "id": "integrity",
                    "weight": 0.35,
                    "label": "Integrity",
                    "description": "Lineage, validation, and content integrity checks pass.",
                },
            ],
            success_criteria="Fresh, complete, integrity-checked data that supports other agents.",
        ),
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
        "scoring": _scoring(
            mode="execution_quality",
            primary_metric="fill_quality",
            summary="Grade execution agents on fill quality, slippage, and impact awareness — not direction.",
            score_horizon="24h",
            direction_weight=0.0,
            magnitude_weight=1.0,
            metrics=[
                {
                    "id": "slippage_control",
                    "weight": 0.40,
                    "label": "Slippage control",
                    "description": "Realized slippage vs expected for chosen order type.",
                },
                {
                    "id": "fill_rate",
                    "weight": 0.30,
                    "label": "Fill rate",
                    "description": "Successful fills without unnecessary cancel churn.",
                },
                {
                    "id": "impact_awareness",
                    "weight": 0.30,
                    "label": "Impact awareness",
                    "description": "Warns/blocks when liquidity would destroy edge.",
                },
            ],
            success_criteria="High-quality fills with controlled slippage and impact.",
        ),
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
        "scoring": _scoring(
            mode="ensemble",
            primary_metric="blend_calibration",
            summary="Grade fusion on ensemble blend quality and fairness — not self-scored directional alpha.",
            score_horizon="24h",
            direction_weight=0.40,
            magnitude_weight=0.60,
            metrics=[
                {
                    "id": "consensus_hit_rate",
                    "weight": 0.40,
                    "label": "Consensus hit rate",
                    "description": "Fused output directional quality vs realized market.",
                },
                {
                    "id": "weight_fairness",
                    "weight": 0.30,
                    "label": "Weight fairness",
                    "description": "Does not double-count self; weights reflect peer evidence.",
                },
                {
                    "id": "overconfidence_control",
                    "weight": 0.30,
                    "label": "Overconfidence control",
                    "description": "Blend confidence stays calibrated under disagreement.",
                },
            ],
            success_criteria="Fair, calibrated blends that improve on single-agent noise.",
        ),
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
    # Extended specialist domains (optimal investable proxies)
    "fed-policy": {
        "tickers": frozenset({"SPY", "TLT", "IEF", "TIP", "UUP", "XLF", "KRE"}),
        "sectors": frozenset({"rates", "fed", "policy", "banks", "bonds", "macro"}),
    },
    "corporate-credit": {
        "tickers": frozenset({"HYG", "LQD", "JNK", "TLT", "XLF", "SPY"}),
        "sectors": frozenset({"credit", "bonds", "high yield", "investment grade", "banks"}),
    },
    "china-em-divergence": {
        "tickers": frozenset({"FXI", "MCHI", "EEM", "ASHR", "KWEB", "SPY", "UUP"}),
        "sectors": frozenset({"china", "emerging", "asia", "em", "international"}),
    },
    "agriculture": {
        "tickers": frozenset({"DBA", "WEAT", "CORN", "SOYB", "MOO", "ADM", "DE"}),
        "sectors": frozenset({"agriculture", "farm", "grain", "fertilizer", "ag"}),
    },
    "options-flow": {
        "tickers": frozenset({"SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "TSLA", "AMD"}),
        "sectors": frozenset({"options", "flow", "derivatives", "equity"}),
    },
    "day-trading-microstructure": {
        "tickers": frozenset({"SPY", "QQQ", "IWM", "AAPL", "TSLA", "NVDA", "AMD"}),
        "sectors": frozenset({"microstructure", "intraday", "liquidity", "momentum"}),
    },
    "dark-pool-volume-profile": {
        "tickers": frozenset({"SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA"}),
        "sectors": frozenset({"dark pool", "volume", "accumulation", "block"}),
    },
    "market-makers": {
        "tickers": frozenset({"SPY", "QQQ", "IWM", "VIX", "VXX", "UVXY"}),
        "sectors": frozenset({"market maker", "liquidity", "volatility", "hedging"}),
    },
    "borrow-fees": {
        "tickers": frozenset({"GME", "AMC", "PLTR", "CVNA", "UPST", "BYND"}),
        "sectors": frozenset({"short", "borrow", "hard to borrow", "squeeze"}),
    },
    "squeeze-mechanics": {
        "tickers": frozenset({"GME", "AMC", "PLTR", "TSLA", "CVNA"}),
        "sectors": frozenset({"squeeze", "short interest", "gamma", "retail"}),
    },
    "htb-dynamics": {
        "tickers": frozenset({"GME", "AMC", "BYND", "UPST", "CVNA"}),
        "sectors": frozenset({"hard to borrow", "short", "borrow fee", "locates"}),
    },
    "ftd-regsho": {
        "tickers": frozenset({"GME", "AMC", "SPY", "IWM"}),
        "sectors": frozenset({"ftd", "regsho", "fails to deliver", "settlement"}),
    },
    "bear-thesis": {
        "tickers": frozenset({"SPY", "QQQ", "IWM", "HYG", "XLF"}),
        "sectors": frozenset({"bear", "short", "forensic", "credit", "accounting"}),
    },
    "margin-stress": {
        "tickers": frozenset({"SPY", "QQQ", "IWM", "XLF", "KRE", "VIX"}),
        "sectors": frozenset({"margin", "leverage", "broker", "risk", "volatility"}),
    },
    "earnings-calendar": {
        "tickers": frozenset({"SPY", "QQQ", "XLK", "XLF", "XLE"}),
        "sectors": frozenset({"earnings", "event", "calendar", "guidance"}),
    },
    "estimate-revisions": {
        "tickers": frozenset({"SPY", "QQQ", "XLK", "XLI", "XLY"}),
        "sectors": frozenset({"estimates", "revisions", "analyst", "eps"}),
    },
    "insider-clusters": {
        "tickers": frozenset({"SPY", "IWM", "XBI", "ARKK"}),
        "sectors": frozenset({"insider", "form 4", "ownership", "cluster"}),
    },
    "sector-rotation": {
        "tickers": frozenset({"XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLRE", "XLB", "SPY"}),
        "sectors": frozenset({"sector", "rotation", "cyclical", "defensive"}),
    },
    "quality-factor": {
        "tickers": frozenset({"QUAL", "SPHQ", "JQUA", "SPY", "QQQ"}),
        "sectors": frozenset({"quality", "factor", "roe", "profitability"}),
    },
    "momentum-reversion": {
        "tickers": frozenset({"MTUM", "SPMO", "SPY", "QQQ", "IWM"}),
        "sectors": frozenset({"momentum", "mean reversion", "factor"}),
    },
    "correlation-breakdown": {
        "tickers": frozenset({"SPY", "TLT", "GLD", "UUP", "EEM", "HYG"}),
        "sectors": frozenset({"correlation", "regime", "diversification", "macro"}),
    },
    "etf-mechanics": {
        "tickers": frozenset({"SPY", "QQQ", "IWM", "TLT", "HYG", "GLD"}),
        "sectors": frozenset({"etf", "nav", "creation", "arbitrage", "flows"}),
    },
    "capital-return": {
        "tickers": frozenset({"SCHD", "VIG", "DVY", "SPY", "XLP", "XLU"}),
        "sectors": frozenset({"dividend", "buyback", "capital return", "income"}),
    },
    "equity-structuring": {
        "tickers": frozenset({"SPY", "QQQ", "IWM", "XLF"}),
        "sectors": frozenset({"structure", "capital structure", "equity", "leverage"}),
    },
    "portfolio-frameworks": {
        "tickers": frozenset({"SPY", "AGG", "TLT", "GLD", "EFA", "EEM"}),
        "sectors": frozenset({"allocation", "portfolio", "asset class", "risk parity"}),
    },
    "long-squeeze-synergy": {
        "tickers": frozenset({"GME", "AMC", "PLTR", "TSLA", "NVDA"}),
        "sectors": frozenset({"squeeze", "gamma", "momentum", "short"}),
    },
    "risk-protection": {
        "tickers": frozenset({"SPY", "TLT", "GLD", "SH", "PSQ", "VIX"}),
        "sectors": frozenset({"hedge", "protection", "defensive", "volatility"}),
    },
    "risk-guardrail": {
        "tickers": frozenset({"SPY", "QQQ", "IWM", "TLT", "SH"}),
        "sectors": frozenset({"risk", "guardrail", "drawdown", "limits"}),
    },
    "risk-mitigation": {
        "tickers": frozenset({"SPY", "TLT", "GLD", "XLP", "XLU"}),
        "sectors": frozenset({"risk", "mitigation", "hedge", "defensive"}),
    },
    "census": {
        "tickers": frozenset({"XHB", "ITB", "XRT", "XLY", "SPY", "IYR"}),
        "sectors": frozenset({"housing", "retail", "demographics", "construction"}),
    },
    "migration": {
        "tickers": frozenset({"IYR", "VNQ", "XHB", "ITB", "SPY"}),
        "sectors": frozenset({"migration", "housing", "real estate", "demographics"}),
    },
    "trading-economics": {
        "tickers": frozenset({"SPY", "TLT", "UUP", "EEM", "GLD"}),
        "sectors": frozenset({"macro", "economics", "global", "indicators"}),
    },
    "sec-filings": {
        "tickers": frozenset({"SPY", "QQQ", "XLF", "XLE"}),
        "sectors": frozenset({"sec", "filing", "disclosure", "10-k", "8-k"}),
    },
    "patents": {
        "tickers": frozenset({"XBI", "IBB", "XLK", "QQQ", "ARKK"}),
        "sectors": frozenset({"patent", "innovation", "biotech", "technology"}),
    },
    "events": {
        "tickers": frozenset({"SPY", "GLD", "TLT", "UUP", "VIX"}),
        "sectors": frozenset({"event", "news", "geopolitics", "risk"}),
    },
    "geopolitics": {
        "tickers": frozenset({"SPY", "GLD", "USO", "XLE", "UUP", "EWU"}),
        "sectors": frozenset({"geopolitics", "oil", "defense", "gold", "risk"}),
    },
    "content-integrity": {
        "tickers": frozenset({"SPY", "QQQ"}),
        "sectors": frozenset({"data quality", "integrity", "platform"}),
    },
    "crowding-quality": {
        "tickers": frozenset({"SPY", "QQQ", "IWM", "ARKK", "TSLA"}),
        "sectors": frozenset({"crowding", "positioning", "quality", "factor"}),
    },
    "market-regime": {
        "tickers": frozenset({"SPY", "QQQ", "IWM", "TLT", "HYG", "GLD", "UUP"}),
        "sectors": frozenset({"regime", "risk-on", "risk-off", "macro"}),
    },
    "fundamental-analyst": {
        "tickers": frozenset({"SPY", "QQQ", "XLF", "XLE", "XLK"}),
        "sectors": frozenset({"fundamental", "value", "earnings", "balance sheet"}),
    },
    "technical-pattern": {
        "tickers": frozenset({"SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA"}),
        "sectors": frozenset({"technical", "pattern", "chart", "momentum"}),
    },
    "sentiment-alt-data": {
        "tickers": frozenset({"SPY", "QQQ", "XLY", "ARKK"}),
        "sectors": frozenset({"sentiment", "alternative data", "retail", "positioning"}),
    },
    "adversarial-debate": {
        "tickers": frozenset({"SPY", "QQQ", "IWM"}),
        "sectors": frozenset({"debate", "bull bear", "thesis", "adversarial"}),
    },
    "electricity": {
        "tickers": frozenset({"UNG", "USO", "XLE", "XLU", "VST", "NEE"}),
        "sectors": frozenset({"utilities", "energy", "power", "gas", "electric", "grid"}),
    },
    "grid": {
        "tickers": frozenset({"XLU", "VST", "NEE", "D", "SO", "AES"}),
        "sectors": frozenset({"utilities", "grid", "power", "electric"}),
    },
    "meteorology": {
        "tickers": frozenset({"UNG", "USO", "XLE", "WEAT", "DBA"}),
        "sectors": frozenset({"energy", "agriculture", "weather", "gas", "oil"}),
    },
    "transportation": {
        "tickers": frozenset({"UPS", "FDX", "UNP", "CSX", "DAL", "JETS"}),
        "sectors": frozenset({"transport", "rail", "airline", "freight"}),
    },
    "logistics": {
        "tickers": frozenset({"UPS", "FDX", "ZIM", "MATX", "UNP"}),
        "sectors": frozenset({"logistics", "shipping", "freight", "supply chain"}),
    },
    "sales-analytics": {
        "tickers": frozenset({"XRT", "WMT", "TGT", "COST", "HD", "AMZN"}),
        "sectors": frozenset({"retail", "consumer", "sales", "staples"}),
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


# ---------------------------------------------------------------------------
# Total P/L points — per full 1.0% increase, weighted by group function
# ---------------------------------------------------------------------------
#
# Goal: raise daily and total average P/L. When total account profit_pct rises,
# each completed 1.0% awards points scaled by how directly the group drives P/L.
# Alpha / intraday get the most; platform / execution get support-level credit.
#
ROLE_PL_POINTS_PER_PCT: dict[str, float] = {
    "alpha": 10.0,
    "intraday": 12.0,  # daily P/L focus
    "short_alpha": 10.0,
    "sector_specialist": 9.0,
    "allocator": 9.0,
    "regime": 8.0,
    "fusion": 8.0,
    "risk_overlay": 6.0,
    "risk_gate": 5.0,
    "execution": 4.0,
    "platform": 2.0,
}

DEFAULT_PL_POINTS_PER_PCT = 6.0


def pl_points_per_pct_for_role(trading_role: str | None) -> float:
    """Points awarded to a role for each full 1.0% of total account P/L."""
    role = str(trading_role or "alpha").strip().lower()
    if role in ROLE_PL_POINTS_PER_PCT:
        return float(ROLE_PL_POINTS_PER_PCT[role])
    return float(DEFAULT_PL_POINTS_PER_PCT)


def group_pl_points_per_pct(group_id: str) -> float:
    """Points-per-1%-total-P/L for a group id (from trading_role)."""
    g = AGENT_GROUPS.get(group_id) or {}
    # Optional explicit override on group meta
    if g.get("pl_points_per_pct") is not None:
        try:
            return max(0.0, float(g["pl_points_per_pct"]))
        except (TypeError, ValueError):
            pass
    return pl_points_per_pct_for_role(str(g.get("trading_role") or "alpha"))


def agent_pl_points_per_pct(agent_id: str) -> float:
    """Points-per-1%-total-P/L for an agent's group."""
    return group_pl_points_per_pct(agent_group_id(agent_id))


def pl_points_for_total_gain(
    agent_or_group_id: str,
    total_pl_pct: float | None,
    *,
    attribution: float = 1.0,
    daily_pl_pct: float | None = None,
    is_group_id: bool = False,
) -> dict[str, Any]:
    """Award group-appropriate points for total (and optional daily) P/L gains.

    - **Total:** each full 1.0% of total account profit_pct → ``pl_points_per_pct``
      points (role-scaled). Fractional % below a full unit does not count.
    - **Daily:** when daily_pl_pct > 0, award the same per-1% schedule at 0.5×
      weight so daily average P/L is incentivized without double-counting total.
    - Only **positive** gains score. Losses → 0 points (no negative points here).
    - ``attribution`` (0..1) scales agent share when picks sit in the book.
    """
    if is_group_id:
        gid = agent_or_group_id if agent_or_group_id in AGENT_GROUPS else agent_group_id(agent_or_group_id)
        role = str((AGENT_GROUPS.get(gid) or {}).get("trading_role") or "alpha")
        per_pct = group_pl_points_per_pct(gid)
        aid = None
    else:
        aid = normalize_agent_id(agent_or_group_id)
        gid = agent_group_id(aid)
        role = agent_trading_role(aid)
        per_pct = agent_pl_points_per_pct(aid)

    attr = max(0.0, min(1.0, float(attribution if attribution is not None else 1.0)))
    total_units = 0
    daily_units = 0
    try:
        tp = float(total_pl_pct) if total_pl_pct is not None else None
    except (TypeError, ValueError):
        tp = None
    try:
        dp = float(daily_pl_pct) if daily_pl_pct is not None else None
    except (TypeError, ValueError):
        dp = None

    if tp is not None and tp > 0:
        total_units = int(tp)  # full 1.0% steps only
    if dp is not None and dp > 0:
        daily_units = int(dp)

    total_points = round(total_units * per_pct * attr, 2)
    # Daily half-weight: each full 1% daily gain adds 0.5 × role points
    daily_points = round(daily_units * per_pct * 0.5 * attr, 2)
    points = round(total_points + daily_points, 2)

    return {
        "agent_id": aid,
        "group_id": gid,
        "trading_role": role,
        "pl_points_per_pct": per_pct,
        "total_pl_pct": round(tp, 4) if tp is not None else None,
        "daily_pl_pct": round(dp, 4) if dp is not None else None,
        "total_pct_units": total_units,
        "daily_pct_units": daily_units,
        "total_points": total_points,
        "daily_points": daily_points,
        "points": points,
        "attribution": round(attr, 4),
        "eligible": attr > 0 and points > 0,
    }


def all_group_pl_point_rates() -> list[dict[str, Any]]:
    """Catalog: each group’s points awarded per 1.0% total P/L."""
    rows: list[dict[str, Any]] = []
    for gid, meta in AGENT_GROUPS.items():
        role = str(meta.get("trading_role") or "alpha")
        rows.append(
            {
                "group_id": gid,
                "group_label": meta.get("label"),
                "trading_role": role,
                "pl_points_per_pct": group_pl_points_per_pct(gid),
                "member_count": len(agents_in_group(gid)),
            }
        )
    rows.sort(key=lambda r: (-float(r["pl_points_per_pct"]), str(r.get("group_label") or "")))
    return rows


def group_scoring_for(group_id: str) -> dict[str, Any]:
    """Return the scoring system for a group id (copy; never empty for known groups)."""
    g = AGENT_GROUPS.get(group_id) or AGENT_GROUPS["markets_core"]
    scoring = g.get("scoring")
    resolved_gid = group_id if group_id in AGENT_GROUPS else "markets_core"
    role = g.get("trading_role")
    pl_pts = group_pl_points_per_pct(resolved_gid)
    if isinstance(scoring, dict) and scoring:
        out = dict(scoring)
        out["group_id"] = resolved_gid
        out["group_label"] = g.get("label")
        out["directional"] = bool(g.get("directional", True))
        out["trading_role"] = role
        out["pl_points_per_pct"] = pl_pts
        return out
    # Fallback for any group missing an explicit system
    return _scoring(
        mode="directional_alpha",
        primary_metric="opportunity_hit_rate",
        summary="Default directional scoring.",
        metrics=[{"id": "direction_hit", "weight": 1.0, "label": "Direction hit rate"}],
    ) | {
        "group_id": resolved_gid,
        "group_label": g.get("label"),
        "directional": bool(g.get("directional", True)),
        "trading_role": role,
        "pl_points_per_pct": pl_pts,
    }


def agent_scoring_system(agent_id: str) -> dict[str, Any]:
    """Scoring system for an agent based on its group function."""
    gid = agent_group_id(agent_id)
    scoring = group_scoring_for(gid)
    scoring["agent_id"] = normalize_agent_id(agent_id)
    return scoring


def agent_scoring_mode(agent_id: str) -> str:
    return str(agent_scoring_system(agent_id).get("mode") or "directional_alpha")


def agent_primary_metric(agent_id: str) -> str:
    return str(agent_scoring_system(agent_id).get("primary_metric") or "direction_hit")


def group_accuracy_weights(agent_id: str) -> tuple[float, float]:
    """Direction/magnitude weights for combined accuracy (from group scoring)."""
    s = agent_scoring_system(agent_id)
    dw = float(s.get("direction_weight") if s.get("direction_weight") is not None else 0.6)
    mw = float(s.get("magnitude_weight") if s.get("magnitude_weight") is not None else 0.4)
    total = dw + mw
    if total <= 0:
        return 0.6, 0.4
    return dw / total, mw / total


def score_horizon_for_agent(agent_id: str) -> str:
    """Preferred evaluation horizon from the group's scoring system (falls back to group horizon)."""
    s = agent_scoring_system(agent_id)
    return str(s.get("score_horizon") or agent_horizon(agent_id) or "24h")


def composite_group_score(
    agent_id: str,
    metric_values: dict[str, float],
    *,
    scale: float = 100.0,
) -> dict[str, Any]:
    """Compute a 0–scale composite score from named metric values using group weights.

    metric_values keys should match scoring.metrics[].id; missing keys are skipped
    and remaining weights are renormalized.
    """
    scoring = agent_scoring_system(agent_id)
    metrics = list(scoring.get("metrics") or [])
    used: list[dict[str, Any]] = []
    weight_sum = 0.0
    for m in metrics:
        mid = str(m.get("id") or "")
        if mid not in metric_values:
            continue
        try:
            val = float(metric_values[mid])
        except (TypeError, ValueError):
            continue
        w = float(m.get("weight") or 0.0)
        used.append({"id": mid, "weight": w, "value": val, "label": m.get("label")})
        weight_sum += w
    if not used or weight_sum <= 0:
        return {
            "agent_id": normalize_agent_id(agent_id),
            "group_id": scoring.get("group_id"),
            "mode": scoring.get("mode"),
            "primary_metric": scoring.get("primary_metric"),
            "score": None,
            "scale": scale,
            "components": [],
            "coverage": 0.0,
        }
    total = 0.0
    components: list[dict[str, Any]] = []
    for row in used:
        nw = float(row["weight"]) / weight_sum
        contrib = nw * float(row["value"])
        total += contrib
        components.append(
            {
                "id": row["id"],
                "label": row.get("label"),
                "weight": round(nw, 4),
                "value": round(float(row["value"]), 4),
                "contribution": round(contrib, 4),
            }
        )
    # Values are assumed already on 0–scale (e.g. accuracy pct). Clamp.
    score = max(0.0, min(float(scale), total))
    n_defined = len(metrics) or 1
    return {
        "agent_id": normalize_agent_id(agent_id),
        "group_id": scoring.get("group_id"),
        "mode": scoring.get("mode"),
        "primary_metric": scoring.get("primary_metric"),
        "score": round(score, 2),
        "scale": scale,
        "components": components,
        "coverage": round(len(used) / n_defined, 3),
        "summary": scoring.get("summary"),
    }


def all_scoring_systems() -> list[dict[str, Any]]:
    """One row per group with scoring mode, primary metric, and KPI weights."""
    rows: list[dict[str, Any]] = []
    for gid in AGENT_GROUPS:
        s = group_scoring_for(gid)
        rows.append(
            {
                "group_id": gid,
                "group_label": s.get("group_label"),
                "mode": s.get("mode"),
                "primary_metric": s.get("primary_metric"),
                "score_horizon": s.get("score_horizon"),
                "direction_weight": s.get("direction_weight"),
                "magnitude_weight": s.get("magnitude_weight"),
                "directional": s.get("directional"),
                "trading_role": s.get("trading_role"),
                "pl_points_per_pct": s.get("pl_points_per_pct"),
                "summary": s.get("summary"),
                "success_criteria": s.get("success_criteria"),
                "metrics": s.get("metrics"),
                "member_count": len(agents_in_group(gid)),
            }
        )
    rows.sort(key=lambda r: str(r.get("group_label") or r.get("group_id")))
    return rows


def group_trait_defaults(agent_id: str) -> dict[str, float]:
    traits = agent_group(agent_id).get("traits") or {}
    return {k: float(v) for k, v in traits.items()}


def group_personality_seed(agent_id: str, *, label: str | None = None) -> dict[str, Any]:
    """Default personality entry for an agent based on its group."""
    g = agent_group(agent_id)
    traits = dict(g.get("traits") or {})
    scoring = g.get("scoring") if isinstance(g.get("scoring"), dict) else {}
    seed = {
        "label": label or normalize_agent_id(agent_id).replace("-", " ").title(),
        "group": g.get("id"),
        "group_label": g.get("label"),
        "posture": g.get("posture"),
        "trading_role": g.get("trading_role"),
        "preferred_horizon": g.get("horizon"),
        "conduct": g.get("conduct"),
        "scoring_mode": scoring.get("mode"),
        "primary_metric": scoring.get("primary_metric"),
        **traits,
    }
    return seed


def agents_in_group(group_id: str) -> list[str]:
    return sorted(aid for aid, gid in AGENT_TO_GROUP.items() if gid == group_id)


def all_groups_summary() -> list[dict[str, Any]]:
    rows = []
    for gid, meta in AGENT_GROUPS.items():
        members = agents_in_group(gid)
        scoring = meta.get("scoring") if isinstance(meta.get("scoring"), dict) else {}
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
                "scoring_mode": scoring.get("mode"),
                "primary_metric": scoring.get("primary_metric"),
                "scoring_summary": scoring.get("summary"),
                "score_horizon": scoring.get("score_horizon"),
                "direction_weight": scoring.get("direction_weight"),
                "magnitude_weight": scoring.get("magnitude_weight"),
            }
        )
    rows.sort(key=lambda r: r["label"])
    return rows


def apply_group_conduct_to_report(data: dict[str, Any], agent_id: str) -> dict[str, Any]:
    """Stamp group metadata and soft-nudge signal biases toward group posture."""
    if not isinstance(data, dict):
        return data
    g = agent_group(agent_id)
    scoring = agent_scoring_system(agent_id)
    meta = dict(data.get("meta") or {})
    meta["agent_group"] = g.get("id")
    meta["agent_group_label"] = g.get("label")
    meta["agent_posture"] = g.get("posture")
    meta["agent_trading_role"] = g.get("trading_role")
    meta["preferred_horizon"] = g.get("horizon")
    meta["conduct"] = g.get("conduct")
    meta["scoring_mode"] = scoring.get("mode")
    meta["primary_metric"] = scoring.get("primary_metric")
    meta["scoring_summary"] = scoring.get("summary")
    meta["score_horizon"] = scoring.get("score_horizon")
    meta["pl_points_per_pct"] = scoring.get("pl_points_per_pct")
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
