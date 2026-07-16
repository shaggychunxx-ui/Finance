"""Shared signal-quality helpers — statistical thresholds, decay, and confidence."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app_paths import OUTPUT


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def bias_from_edge(
    edge: float,
    *,
    bullish_threshold: float = 0.55,
    bearish_threshold: float = 0.45,
) -> str:
    if edge >= bullish_threshold:
        return "BULLISH"
    if edge <= bearish_threshold:
        return "BEARISH"
    return "NEUTRAL"


def confidence_from_edge(
    edge: float,
    *,
    samples: int = 0,
    min_samples: int = 20,
    neutral: float = 0.5,
) -> float:
    """Map probability edge + sample depth to signal confidence."""
    sample_factor = _clamp(samples / max(min_samples, 1), 0.35, 1.0)
    edge_strength = _clamp(abs(edge - neutral) * 2.0, 0.0, 1.0)
    return round(_clamp(0.42 + edge_strength * 0.45 * sample_factor, 0.35, 0.92), 3)


def wilson_edge_valid(
    prob: float,
    *,
    ci_low: float,
    ci_high: float,
    samples: int,
    min_samples: int = 30,
    min_edge: float = 0.05,
) -> bool:
    """True when Wilson interval clears 50% with enough samples."""
    if samples < min_samples:
        return False
    if prob >= 0.5 + min_edge:
        return ci_low > 0.5
    if prob <= 0.5 - min_edge:
        return ci_high < 0.5
    return False


def event_recency_weight(
    timestamp: str | None,
    *,
    half_life_hours: float = 48.0,
) -> float:
    """Exponential decay for dated headlines/events (1.0 = fresh)."""
    if not timestamp:
        return 0.55
    try:
        when = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        age_hours = max(0.0, (datetime.now(timezone.utc) - when).total_seconds() / 3600.0)
    except ValueError:
        return 0.55
    if half_life_hours <= 0:
        return 1.0
    return round(math.exp(-0.693147 * age_hours / half_life_hours), 3)


def weighted_event_score(events: list[dict[str, Any]], *, impact_weights: dict[str, float] | None = None) -> float:
    weights = impact_weights or {
        "critical": 1.0,
        "high": 0.72,
        "medium": 0.4,
        "low": 0.2,
    }
    total = 0.0
    for event in events:
        impact = str(event.get("impact") or "medium").lower()
        base = weights.get(impact, 0.3)
        recency = event_recency_weight(
            str(event.get("date") or event.get("pub_date") or event.get("recorded_at") or ""),
        )
        total += base * recency
    return round(total, 3)


MARKET_IMPACT_TICKERS = frozenset({
    "SPY", "QQQ", "IWM", "DIA", "VOO",
    "XLI", "XLF", "XLY", "XLP", "XLK", "XLV", "XLB", "XLC", "XLRE", "XLU",
    "TLT", "HYG", "GLD", "SLV", "VIXY",
    "UNG", "USO", "XLE",
    "EEM", "FXI",
})


def build_market_signal(
    *,
    sector: str,
    tickers: list[str],
    bias: str,
    reason: str,
    confidence: float | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "sector": sector,
        "tickers": [str(t).upper() for t in tickers if t],
        "bias": str(bias or "NEUTRAL").upper(),
        "reason": reason,
    }
    if confidence is not None:
        row["confidence"] = round(_clamp(confidence, 0.05, 0.99), 3)
    if evidence:
        row["evidence"] = evidence
    return row


def build_market_impact_signal(
    *,
    sector: str,
    tickers: list[str],
    bias: str,
    reason: str,
    confidence: float | None = None,
    evidence: dict[str, Any] | None = None,
    domain_context: str = "",
) -> dict[str, Any]:
    """Domain reading translated into a market-facing trade expression (not a sector buy)."""
    row = build_market_signal(
        sector=sector,
        tickers=[t for t in tickers if str(t).upper() in MARKET_IMPACT_TICKERS],
        bias=bias,
        reason=reason,
        confidence=confidence,
        evidence=evidence,
    )
    row["impact_scope"] = "market"
    if domain_context:
        row["domain_context"] = domain_context
    return row


def power_grid_market_impact_signals(
    *,
    grid_stress: float,
    stress_label: str = "",
    renewable_pct: float = 0.0,
    gas_pct: float | None = None,
    avg_lmp: float | None = None,
    weather_energy: float | None = None,
    peak_load_mw: float | None = None,
    source: str = "grid",
) -> list[dict[str, Any]]:
    """Translate ISO / LMP / fuel-mix readings into broad market picks (events-style)."""
    signals: list[dict[str, Any]] = []
    stress = float(grid_stress or 0.0)
    label = str(stress_label or "").strip()
    evidence_base: dict[str, Any] = {
        "grid_stress": round(stress, 1),
        "renewable_pct": round(float(renewable_pct or 0.0), 1),
        "source": source,
    }
    if gas_pct is not None:
        evidence_base["gas_pct"] = round(float(gas_pct), 1)
    if avg_lmp is not None:
        evidence_base["avg_lmp"] = round(float(avg_lmp), 2)
    if weather_energy is not None:
        evidence_base["weather_energy"] = round(float(weather_energy), 3)
    if peak_load_mw is not None:
        evidence_base["peak_load_mw"] = round(float(peak_load_mw), 0)

    high_stress = stress >= 65.0 or (avg_lmp is not None and float(avg_lmp) >= 55.0)
    low_power_cost = stress < 40.0 and avg_lmp is not None and float(avg_lmp) <= 22.0
    clean_low_stress = float(renewable_pct or 0.0) >= 38.0 and stress < 50.0
    gas_inflation = (
        gas_pct is not None
        and float(gas_pct) >= 45.0
        and (
            weather_energy is None
            or float(weather_energy) >= 0.55
        )
    )
    strong_load = peak_load_mw is not None and float(peak_load_mw) >= 75_000.0

    if high_stress:
        lmp_note = f" avg LMP ${float(avg_lmp):.2f}/MWh" if avg_lmp is not None else ""
        conf = grid_power_confidence(
            renewable_pct=renewable_pct,
            gas_pct=gas_pct,
            lmp=avg_lmp,
            grid_stress=stress,
        )
        signals.append(
            build_market_impact_signal(
                sector="Broad Market / Industrials",
                tickers=["SPY", "XLI", "IWM"],
                bias="BEARISH",
                reason=(
                    f"Wholesale power stress ({label or 'elevated'}{lmp_note}) — "
                    "input-cost headwind for cyclicals and industrials"
                ),
                confidence=conf,
                evidence=evidence_base,
                domain_context="grid_stress",
            )
        )
        signals.append(
            build_market_impact_signal(
                sector="Defensive / Rates Hedge",
                tickers=["TLT", "GLD"],
                bias="BULLISH" if stress >= 70.0 else "NEUTRAL",
                reason=(
                    "Elevated grid stress raises inflation and margin-risk — "
                    "favor duration and defensive hedges"
                ),
                confidence=min(0.82, conf + 0.06),
                evidence=evidence_base,
                domain_context="grid_stress",
            )
        )

    if low_power_cost:
        conf = grid_power_confidence(renewable_pct=renewable_pct, lmp=avg_lmp, grid_stress=stress)
        signals.append(
            build_market_impact_signal(
                sector="Broad Market",
                tickers=["SPY", "IWM"],
                bias="BULLISH",
                reason=(
                    f"Subdued wholesale power costs (LMP ${float(avg_lmp):.2f}/MWh) "
                    "support corporate margins and cyclical risk appetite"
                ),
                confidence=conf,
                evidence=evidence_base,
                domain_context="low_lmp",
            )
        )

    if clean_low_stress and not high_stress:
        conf = grid_power_confidence(renewable_pct=renewable_pct, grid_stress=stress)
        signals.append(
            build_market_impact_signal(
                sector="Growth / Broad Market",
                tickers=["QQQ", "SPY"],
                bias="BULLISH" if float(renewable_pct) >= 42.0 else "NEUTRAL",
                reason=(
                    f"High renewable penetration ({float(renewable_pct):.0f}%) with "
                    f"manageable grid stress ({label or 'normal'}) — lower power-cost drag"
                ),
                confidence=conf,
                evidence=evidence_base,
                domain_context="renewables",
            )
        )

    if gas_inflation and not high_stress:
        conf = grid_power_confidence(
            gas_pct=gas_pct,
            grid_stress=weather_energy and weather_energy * 100,
        )
        weather_note = (
            f"; weather-energy {float(weather_energy):.2f}"
            if weather_energy is not None
            else ""
        )
        signals.append(
            build_market_impact_signal(
                sector="Growth / Small Cap",
                tickers=["SPY", "IWM"],
                bias="BEARISH" if float(gas_pct or 0) >= 50.0 else "NEUTRAL",
                reason=(
                    f"Gas-heavy generation stack ({float(gas_pct):.0f}% gas){weather_note} — "
                    "energy inflation risk to growth and margins"
                ),
                confidence=conf,
                evidence=evidence_base,
                domain_context="gas_inflation",
            )
        )
        signals.append(
            build_market_impact_signal(
                sector="Energy Inflation Transmission",
                tickers=["UNG", "XLE"],
                bias="BULLISH" if float(gas_pct or 0) >= 50.0 else "NEUTRAL",
                reason="Wholesale fuel-mix tilt — energy prices as inflation transmission, not utility beta",
                confidence=max(0.45, conf - 0.05),
                evidence=evidence_base,
                domain_context="gas_inflation",
            )
        )

    if strong_load and not high_stress:
        signals.append(
            build_market_impact_signal(
                sector="Cyclicals / Economic Activity",
                tickers=["SPY", "XLI"],
                bias="BULLISH",
                reason=(
                    f"Peak monitored grid load {float(peak_load_mw):,.0f} MW — "
                    "strong real-economy power draw"
                ),
                confidence=grid_power_confidence(grid_stress=stress),
                evidence=evidence_base,
                domain_context="peak_load",
            )
        )

    if 40.0 <= stress < 65.0 and not signals:
        signals.append(
            build_market_impact_signal(
                sector="Broad Market",
                tickers=["SPY"],
                bias="NEUTRAL",
                reason=f"Moderate grid conditions ({label or 'moderate stress'}) — no strong macro tilt",
                confidence=grid_power_confidence(
                    renewable_pct=renewable_pct,
                    gas_pct=gas_pct,
                    lmp=avg_lmp,
                    grid_stress=stress,
                ),
                evidence=evidence_base,
                domain_context="baseline",
            )
        )

    if not signals:
        signals.append(
            build_market_impact_signal(
                sector="Broad Market",
                tickers=["SPY"],
                bias="NEUTRAL",
                reason="ISO feeds show no acute wholesale-power tilt for macro positioning",
                confidence=0.42,
                evidence=evidence_base,
                domain_context="baseline",
            )
        )

    return signals


def weather_disruption_confidence(
    *,
    disruption: float,
    heat: float | None = None,
    cold: float | None = None,
    severe: float | None = None,
    energy: float | None = None,
) -> float:
    """National weather disruption strength for market-impact signals."""
    disruption_factor = _clamp(float(disruption or 0.0) / 0.75, 0.0, 1.0)
    heat_factor = _clamp((float(heat or 0.0) - 0.45) / 0.35, 0.0, 1.0) if heat is not None else 0.3
    cold_factor = _clamp((float(cold or 0.0) - 0.35) / 0.35, 0.0, 1.0) if cold is not None else 0.25
    severe_factor = _clamp(float(severe or 0.0) / 0.5, 0.0, 1.0) if severe is not None else 0.25
    energy_factor = _clamp((float(energy or 0.0) - 0.45) / 0.35, 0.0, 1.0) if energy is not None else 0.25
    return round(
        _clamp(
            0.38
            + 0.3 * disruption_factor
            + 0.14 * heat_factor
            + 0.08 * cold_factor
            + 0.06 * severe_factor
            + 0.04 * energy_factor
        ),
        3,
    )


def transportation_market_impact_signals(
    *,
    infrastructure_stress: float,
    stress_label: str = "",
    freight_score: float = 50.0,
    truck_chg_avg_pct: float = 0.0,
    passenger_chg_avg_pct: float | None = None,
    unknown_bridge_design_pct: float | None = None,
    source: str = "transportation",
) -> list[dict[str, Any]]:
    """Translate DOT freight / infrastructure readings into broad market picks."""
    signals: list[dict[str, Any]] = []
    stress = float(infrastructure_stress or 0.0)
    label = str(stress_label or "").strip()
    truck_avg = float(truck_chg_avg_pct or 0.0)
    passenger_avg = float(passenger_chg_avg_pct) if passenger_chg_avg_pct is not None else None
    evidence_base: dict[str, Any] = {
        "infrastructure_stress": round(stress, 1),
        "freight_score": round(float(freight_score or 0.0), 1),
        "truck_chg_avg_pct": round(truck_avg, 2),
        "source": source,
    }
    if passenger_avg is not None:
        evidence_base["passenger_chg_avg_pct"] = round(passenger_avg, 2)
    if unknown_bridge_design_pct is not None:
        evidence_base["unknown_bridge_design_pct"] = round(float(unknown_bridge_design_pct), 1)

    freight_proxy = 0.5 + min(max(truck_avg / 8.0, -0.15), 0.25)
    conf = freight_logistics_confidence(freight_proxy, stress=stress / 100.0)

    strong_freight = truck_avg >= 3.0
    weak_freight = truck_avg <= -2.0
    high_infra_stress = stress >= 65.0
    freight_led = (
        passenger_avg is not None
        and truck_avg > passenger_avg + 2.0
        and truck_avg > 0.0
    )
    commute_led = (
        passenger_avg is not None
        and passenger_avg > truck_avg + 2.0
        and passenger_avg > 0.0
    )

    if strong_freight:
        signals.append(
            build_market_impact_signal(
                sector="Cyclicals / Economic Activity",
                tickers=["SPY", "XLI", "IWM"],
                bias="BULLISH",
                reason=(
                    f"Freight-led traffic momentum (truck volumes {truck_avg:+.1f}% avg) — "
                    "industrial and logistics demand supports cyclical risk appetite"
                ),
                confidence=conf,
                evidence=evidence_base,
                domain_context="freight_expansion",
            )
        )

    if weak_freight:
        signals.append(
            build_market_impact_signal(
                sector="Broad Market / Industrials",
                tickers=["SPY", "XLI", "IWM"],
                bias="BEARISH",
                reason=(
                    f"Softening truck freight volumes ({truck_avg:+.1f}% avg) — "
                    "logistics slowdown signal for cyclicals and small caps"
                ),
                confidence=conf,
                evidence=evidence_base,
                domain_context="freight_contraction",
            )
        )

    if high_infra_stress:
        signals.append(
            build_market_impact_signal(
                sector="Supply Chain / Industrials",
                tickers=["SPY", "XLI"],
                bias="BEARISH",
                reason=(
                    f"Infrastructure stress ({label or 'elevated'}) — "
                    "bridge inventory uncertainty and corridor risk weigh on industrials"
                ),
                confidence=freight_logistics_confidence(
                    freight_proxy,
                    stress=stress / 100.0,
                    congestion=0.7,
                ),
                evidence=evidence_base,
                domain_context="infrastructure_stress",
            )
        )
        signals.append(
            build_market_impact_signal(
                sector="Defensive / Credit Caution",
                tickers=["TLT", "HYG"],
                bias="NEUTRAL",
                reason="Elevated civil-infrastructure stress raises supply-chain and credit tail risk",
                confidence=max(0.45, conf - 0.04),
                evidence=evidence_base,
                domain_context="infrastructure_stress",
            )
        )

    if freight_led and not weak_freight:
        signals.append(
            build_market_impact_signal(
                sector="Industrials / Production",
                tickers=["XLI", "SPY"],
                bias="BULLISH" if truck_avg >= 1.5 else "NEUTRAL",
                reason=(
                    f"Freight traffic outpacing passenger volumes — "
                    f"trucks {truck_avg:+.1f}% vs all vehicles {passenger_avg:+.1f}%"
                ),
                confidence=conf,
                evidence=evidence_base,
                domain_context="freight_led_mode",
            )
        )

    if commute_led and not strong_freight:
        signals.append(
            build_market_impact_signal(
                sector="Consumer / Broad Market",
                tickers=["XLY", "SPY"],
                bias="BULLISH" if passenger_avg >= 2.0 else "NEUTRAL",
                reason=(
                    f"Passenger traffic outpacing freight — "
                    f"all vehicles {passenger_avg:+.1f}% vs trucks {truck_avg:+.1f}%"
                ),
                confidence=max(0.45, conf - 0.03),
                evidence=evidence_base,
                domain_context="commute_led_mode",
            )
        )

    if 40.0 <= stress < 65.0 and not signals:
        signals.append(
            build_market_impact_signal(
                sector="Broad Market",
                tickers=["SPY"],
                bias="NEUTRAL",
                reason=f"Moderate infrastructure conditions ({label or 'stable'}) — no strong macro tilt",
                confidence=conf,
                evidence=evidence_base,
                domain_context="baseline",
            )
        )

    if not signals:
        signals.append(
            build_market_impact_signal(
                sector="Broad Market",
                tickers=["SPY"],
                bias="NEUTRAL",
                reason="DOT freight and bridge data show no acute macro directional tilt",
                confidence=0.42,
                evidence=evidence_base,
                domain_context="baseline",
            )
        )

    return signals


def meteorology_market_impact_signals(
    *,
    heat_stress: float = 0.0,
    cold_stress: float = 0.0,
    severe_stress: float = 0.0,
    flood_stress: float = 0.0,
    energy_stress: float = 0.0,
    disruption_score: float = 0.0,
    disruption_label: str = "",
    tropical_activity: str = "",
    agricultural_risk: str = "",
    heat_alerts: int = 0,
    cold_alerts: int = 0,
    severe_alerts: int = 0,
    source: str = "meteorology",
) -> list[dict[str, Any]]:
    """Translate NWS weather stress into broad market picks (not utility/energy beta)."""
    signals: list[dict[str, Any]] = []
    heat = float(heat_stress or 0.0)
    cold = float(cold_stress or 0.0)
    severe = float(severe_stress or 0.0)
    flood = float(flood_stress or 0.0)
    energy = float(energy_stress or 0.0)
    disruption = float(disruption_score or 0.0)
    label = str(disruption_label or "").strip()
    tropical = str(tropical_activity or "").lower()
    ag_risk = str(agricultural_risk or "").lower()
    evidence_base: dict[str, Any] = {
        "heat_stress": round(heat, 3),
        "cold_stress": round(cold, 3),
        "severe_stress": round(severe, 3),
        "flood_stress": round(flood, 3),
        "energy_stress": round(energy, 3),
        "disruption_score": round(disruption, 3),
        "source": source,
    }
    conf = weather_disruption_confidence(
        disruption=disruption,
        heat=heat,
        cold=cold,
        severe=severe,
        energy=energy,
    )

    critical_disruption = disruption >= 0.75
    elevated_disruption = disruption >= 0.55
    energy_demand = energy >= 0.55 or heat >= 0.52 or cold >= 0.45
    active_tropical = "hurricane" in tropical or "active tropical" in tropical
    ag_pressure = (
        "drought" in ag_risk
        or "flood" in ag_risk
        or "heat/drought" in ag_risk
    )

    if critical_disruption or elevated_disruption:
        signals.append(
            build_market_impact_signal(
                sector="Broad Market / Cyclicals",
                tickers=["SPY", "IWM", "XLI"],
                bias="BEARISH" if critical_disruption else "NEUTRAL",
                reason=(
                    f"National weather disruption {label or ('critical' if critical_disruption else 'elevated')} "
                    f"(score {disruption:.2f}) — outage, logistics, and activity headwinds"
                ),
                confidence=conf,
                evidence={**evidence_base, "severe_alerts": severe_alerts},
                domain_context="disruption",
            )
        )
        signals.append(
            build_market_impact_signal(
                sector="Safe Haven / Defensive",
                tickers=["GLD", "TLT", "XLU"],
                bias="BULLISH" if critical_disruption else "NEUTRAL",
                reason="Weather shock raises volatility and defensive hedging demand",
                confidence=min(0.84, conf + 0.05),
                evidence=evidence_base,
                domain_context="disruption",
            )
        )

    if energy_demand and not critical_disruption:
        bias = "BEARISH" if energy >= 0.72 or heat >= 0.68 or cold >= 0.65 else "NEUTRAL"
        signals.append(
            build_market_impact_signal(
                sector="Growth / Margins",
                tickers=["SPY", "IWM"],
                bias=bias,
                reason=(
                    f"Weather-driven energy demand (score {energy:.2f}; "
                    f"{heat_alerts} heat / {cold_alerts} cold alerts) — "
                    "input-cost pressure on corporate margins"
                ),
                confidence=conf,
                evidence={**evidence_base, "heat_alerts": heat_alerts, "cold_alerts": cold_alerts},
                domain_context="energy_demand",
            )
        )
        signals.append(
            build_market_impact_signal(
                sector="Energy Inflation Transmission",
                tickers=["UNG", "XLE", "USO"],
                bias="BULLISH" if energy >= 0.72 else "NEUTRAL",
                reason="Heating/cooling stress transmitted through energy prices, not utility beta",
                confidence=max(0.45, conf - 0.04),
                evidence=evidence_base,
                domain_context="energy_demand",
            )
        )

    if severe >= 0.35 and not critical_disruption:
        signals.append(
            build_market_impact_signal(
                sector="Industrials / Activity",
                tickers=["SPY", "XLI"],
                bias="BEARISH" if severe >= 0.5 else "NEUTRAL",
                reason=(
                    f"Severe weather stress {severe:.2f} ({severe_alerts} alerts) — "
                    "near-term industrial and transport disruption"
                ),
                confidence=conf,
                evidence={**evidence_base, "severe_alerts": severe_alerts},
                domain_context="severe_weather",
            )
        )

    if active_tropical:
        signals.append(
            build_market_impact_signal(
                sector="Risk-Off / Volatility",
                tickers=["SPY", "GLD"],
                bias="BEARISH" if "hurricane" in tropical else "NEUTRAL",
                reason=f"Tropical activity: {tropical_activity} — Gulf supply-chain and volatility risk",
                confidence=conf,
                evidence=evidence_base,
                domain_context="tropical",
            )
        )
        signals.append(
            build_market_impact_signal(
                sector="Energy Supply Transmission",
                tickers=["USO", "XLE"],
                bias="NEUTRAL",
                reason="Storm risk to Gulf energy infrastructure — commodity transmission channel",
                confidence=max(0.44, conf - 0.06),
                evidence=evidence_base,
                domain_context="tropical",
            )
        )

    if ag_pressure:
        drought = "drought" in ag_risk or "heat/drought" in ag_risk
        signals.append(
            build_market_impact_signal(
                sector="Consumer / Staples",
                tickers=["XLP", "SPY"] if drought else ["SPY", "XLI"],
                bias="BEARISH" if drought else "NEUTRAL",
                reason=(
                    f"Agricultural weather risk: {agricultural_risk} — "
                    + ("crop-cost pressure on discretionary demand" if drought else "flood-related activity drag")
                ),
                confidence=max(0.45, conf - 0.03),
                evidence={**evidence_base, "flood_stress": round(flood, 3)},
                domain_context="agriculture",
            )
        )

    if flood >= 0.4 and not ag_pressure and not critical_disruption:
        signals.append(
            build_market_impact_signal(
                sector="Industrials / Regional Activity",
                tickers=["SPY", "XLI"],
                bias="NEUTRAL",
                reason=f"Flood risk score {flood:.2f} — localized construction and transport delays",
                confidence=max(0.43, conf - 0.05),
                evidence=evidence_base,
                domain_context="flood",
            )
        )

    if disruption < 0.35 and not signals:
        signals.append(
            build_market_impact_signal(
                sector="Broad Market",
                tickers=["SPY"],
                bias="NEUTRAL",
                reason="No significant national weather stress for macro positioning",
                confidence=0.42,
                evidence=evidence_base,
                domain_context="baseline",
            )
        )

    if not signals:
        signals.append(
            build_market_impact_signal(
                sector="Broad Market",
                tickers=["SPY"],
                bias="NEUTRAL",
                reason="Weather backdrop balanced — no acute market tilt from NWS feeds",
                confidence=0.42,
                evidence=evidence_base,
                domain_context="baseline",
            )
        )

    return signals


PATENT_SECTOR_MARKET_MAP: dict[str, tuple[list[str], str]] = {
    "semiconductor": (
        ["XLK", "QQQ"],
        "Semiconductor patent cluster — innovation-led tech risk appetite",
    ),
    "artificial-intelligence": (
        ["QQQ", "XLK"],
        "AI patent velocity — growth and capex cycle signal",
    ),
    "biotechnology": (
        ["XLV", "QQQ"],
        "Biotech filing cluster — healthcare innovation backdrop",
    ),
    "energy": (
        ["XLE", "XLK"],
        "Energy/storage IP — transition theme with commodity transmission",
    ),
    "automotive": (
        ["XLI", "SPY"],
        "Mobility patent activity — industrial and auto-cycle signal",
    ),
    "telecom": (
        ["XLC", "SPY"],
        "Telecom IP cluster — communications sector macro tilt",
    ),
}


def innovation_velocity_confidence(
    *,
    innovation_score: float,
    filing_count: int = 0,
    high_impact_count: int = 0,
) -> float:
    score_factor = _clamp((float(innovation_score or 0.0) - 40.0) / 45.0, 0.0, 1.0)
    filing_factor = _clamp(int(filing_count) / 8.0, 0.0, 1.0)
    impact_factor = _clamp(int(high_impact_count) / 4.0, 0.0, 1.0)
    return round(_clamp(0.38 + 0.28 * score_factor + 0.2 * filing_factor + 0.14 * impact_factor), 3)


def logistics_market_impact_signals(
    *,
    supply_chain_stress: float,
    stress_label: str = "",
    freight_momentum: float = 0.5,
    congestion_score: float = 0.5,
    us_west_coast_congestion: float | None = None,
    tanker_flow_active: bool = False,
    retail_lead_time_stressed: bool = False,
    source: str = "logistics",
) -> list[dict[str, Any]]:
    """Translate marine/shipping corridor stress into broad market picks."""
    signals: list[dict[str, Any]] = []
    stress = float(supply_chain_stress or 0.0)
    freight = float(freight_momentum or 0.0)
    congestion = float(congestion_score or 0.0)
    label = str(stress_label or "").strip()
    evidence_base: dict[str, Any] = {
        "supply_chain_stress": round(stress, 3),
        "freight_momentum": round(freight, 3),
        "congestion_score": round(congestion, 3),
        "source": source,
    }
    if us_west_coast_congestion is not None:
        evidence_base["us_west_coast_congestion"] = round(float(us_west_coast_congestion), 3)

    conf = freight_logistics_confidence(freight, stress=stress, congestion=congestion)
    critical_stress = stress >= 0.75
    elevated_stress = stress >= 0.55
    strong_freight = freight >= 0.58
    import_congestion = (
        us_west_coast_congestion is not None and float(us_west_coast_congestion) >= 0.58
    ) or retail_lead_time_stressed

    if critical_stress or elevated_stress:
        signals.append(
            build_market_impact_signal(
                sector="Broad Market / Industrials",
                tickers=["SPY", "XLI", "IWM"],
                bias="BEARISH" if critical_stress else "NEUTRAL",
                reason=(
                    f"Global logistics stress {label or ('critical' if critical_stress else 'elevated')} "
                    f"(score {stress:.2f}) — supply-chain friction for cyclicals"
                ),
                confidence=conf,
                evidence=evidence_base,
                domain_context="supply_chain_stress",
            )
        )
        signals.append(
            build_market_impact_signal(
                sector="Credit / Defensive",
                tickers=["HYG", "TLT"],
                bias="NEUTRAL",
                reason="Shipping chokepoints raise margin and credit tail risk across trade-sensitive sectors",
                confidence=max(0.44, conf - 0.04),
                evidence=evidence_base,
                domain_context="supply_chain_stress",
            )
        )

    if strong_freight and not critical_stress:
        signals.append(
            build_market_impact_signal(
                sector="Global Trade / Cyclicals",
                tickers=["SPY", "XLI", "EEM"],
                bias="BULLISH" if freight >= 0.70 else "NEUTRAL",
                reason=(
                    f"Freight momentum {freight:.2f} — active shipping lanes support "
                    "trade and industrial activity"
                ),
                confidence=conf,
                evidence=evidence_base,
                domain_context="freight_expansion",
            )
        )

    if import_congestion:
        wc = float(us_west_coast_congestion or congestion)
        signals.append(
            build_market_impact_signal(
                sector="Consumer / Import Delays",
                tickers=["XLY", "SPY"],
                bias="BEARISH" if wc >= 0.72 else "NEUTRAL",
                reason=(
                    f"West-coast import congestion {wc:.2f} — retail lead-time pressure "
                    "on discretionary demand"
                ),
                confidence=freight_logistics_confidence(freight, congestion=wc, stress=stress),
                evidence=evidence_base,
                domain_context="import_congestion",
            )
        )

    if tanker_flow_active and freight >= 0.5:
        signals.append(
            build_market_impact_signal(
                sector="Energy Supply Transmission",
                tickers=["USO", "XLE"],
                bias="BULLISH" if freight >= 0.65 else "NEUTRAL",
                reason="Active tanker corridors — commodity flow transmission, not shipping beta",
                confidence=max(0.45, conf - 0.03),
                evidence=evidence_base,
                domain_context="tanker_flow",
            )
        )

    if stress < 0.35 and not signals:
        signals.append(
            build_market_impact_signal(
                sector="Broad Market",
                tickers=["SPY"],
                bias="NEUTRAL",
                reason="Marine logistics backdrop balanced — no acute macro tilt",
                confidence=0.42,
                evidence=evidence_base,
                domain_context="baseline",
            )
        )

    if not signals:
        signals.append(
            build_market_impact_signal(
                sector="Broad Market",
                tickers=["SPY"],
                bias="NEUTRAL",
                reason="No significant global logistics stress for macro positioning",
                confidence=0.42,
                evidence=evidence_base,
                domain_context="baseline",
            )
        )

    return signals


def patents_market_impact_signals(
    *,
    innovation_score: float,
    landscape_label: str = "",
    by_sector: dict[str, int] | None = None,
    high_impact_count: int = 0,
    top_sector: str = "",
    source: str = "patents",
) -> list[dict[str, Any]]:
    """Translate patent-sector clusters into innovation-led market expressions."""
    signals: list[dict[str, Any]] = []
    score = float(innovation_score or 0.0)
    label = str(landscape_label or "").strip()
    sectors = dict(by_sector or {})
    total_filings = sum(int(v) for v in sectors.values())
    evidence_base: dict[str, Any] = {
        "innovation_score": round(score, 1),
        "high_impact_count": int(high_impact_count),
        "total_filings": total_filings,
        "source": source,
    }
    conf = innovation_velocity_confidence(
        innovation_score=score,
        filing_count=total_filings,
        high_impact_count=high_impact_count,
    )

    if score >= 70.0:
        signals.append(
            build_market_impact_signal(
                sector="Innovation / Growth",
                tickers=["QQQ", "SPY", "XLK"],
                bias="BULLISH",
                reason=f"High innovation velocity ({label or 'elevated'}) — patent activity supports growth risk-on",
                confidence=conf,
                evidence=evidence_base,
                domain_context="innovation_velocity",
            )
        )

    ranked = sorted(sectors.items(), key=lambda x: -x[1])
    for sector, count in ranked[:3]:
        if sector == "general" or count < 2:
            continue
        tickers, base_note = PATENT_SECTOR_MARKET_MAP.get(
            sector,
            (["SPY", "QQQ"], "Patent activity cluster — broad innovation backdrop"),
        )
        signals.append(
            build_market_impact_signal(
                sector=f"Innovation Theme — {sector.replace('-', ' ').title()}",
                tickers=tickers,
                bias="BULLISH" if count >= 4 else "NEUTRAL",
                reason=f"{count} tracked filings in {sector.replace('-', ' ')}; {base_note}",
                confidence=conf,
                evidence={**evidence_base, "sector": sector, "sector_count": count},
                domain_context="sector_cluster",
            )
        )

    if high_impact_count >= 2 and score < 70.0:
        signals.append(
            build_market_impact_signal(
                sector="IP Catalyst / Growth",
                tickers=["QQQ", "SPY"],
                bias="NEUTRAL",
                reason=f"{high_impact_count} high-impact patent signals — innovation catalyst watch",
                confidence=conf,
                evidence=evidence_base,
                domain_context="high_impact_ip",
            )
        )

    if score < 45.0 and not signals:
        signals.append(
            build_market_impact_signal(
                sector="Broad Market",
                tickers=["SPY"],
                bias="NEUTRAL",
                reason=f"Quiet patent landscape ({label or 'low velocity'}) — no innovation-led macro tilt",
                confidence=max(0.4, conf - 0.05),
                evidence=evidence_base,
                domain_context="baseline",
            )
        )

    if not signals:
        top = str(top_sector or "").replace("-", " ")
        signals.append(
            build_market_impact_signal(
                sector="Broad Market",
                tickers=["SPY"],
                bias="NEUTRAL",
                reason=f"No concentrated patent cluster — leading theme: {top or 'mixed'}",
                confidence=0.42,
                evidence=evidence_base,
                domain_context="baseline",
            )
        )

    return signals


def agricultural_supply_confidence(
    *,
    production_trend_score: float,
    drought_risk_score: float | None = None,
    forecast_confidence: float | None = None,
) -> float:
    """USDA NASS production trend / drought stress signal strength."""
    trend_factor = _clamp(abs(float(production_trend_score or 0.5) - 0.5) * 2.0, 0.0, 1.0)
    drought_factor = (
        _clamp((float(drought_risk_score or 0.0) - 0.4) / 0.4, 0.0, 1.0)
        if drought_risk_score is not None
        else 0.3
    )
    forecast_factor = (
        _clamp(float(forecast_confidence or 0.0), 0.0, 1.0)
        if forecast_confidence is not None
        else 0.35
    )
    return round(
        _clamp(0.38 + 0.26 * trend_factor + 0.18 * drought_factor + 0.1 * forecast_factor),
        3,
    )


def agriculture_market_impact_signals(
    *,
    production_trend_score: float,
    trend_label: str = "",
    drought_risk_score: float = 0.4,
    forecast_confidence: float | None = None,
    grain_output_strong: bool = False,
    livestock_output_strong: bool = False,
    food_inflation_pressure: bool = False,
    source: str = "agriculture",
) -> list[dict[str, Any]]:
    """Translate USDA NASS production trend / forecast readings into broad market picks."""
    signals: list[dict[str, Any]] = []
    trend = float(production_trend_score or 0.5)
    drought = float(drought_risk_score or 0.0)
    label = str(trend_label or "").strip()
    evidence_base: dict[str, Any] = {
        "production_trend_score": round(trend, 3),
        "drought_risk_score": round(drought, 3),
        "source": source,
    }
    if forecast_confidence is not None:
        evidence_base["forecast_confidence"] = round(float(forecast_confidence), 3)

    conf = agricultural_supply_confidence(
        production_trend_score=trend,
        drought_risk_score=drought,
        forecast_confidence=forecast_confidence,
    )

    supply_shortfall = trend <= 0.4 and drought >= 0.55
    supply_expansion = trend >= 0.62 and drought <= 0.4

    if supply_shortfall or food_inflation_pressure:
        signals.append(
            build_market_impact_signal(
                sector="Staples / Food Inflation",
                tickers=["XLP", "GLD"],
                bias="BULLISH" if drought >= 0.65 else "NEUTRAL",
                reason=(
                    f"Production trend {label.lower() or 'weak'} (score {trend:.2f}) with "
                    f"drought risk {drought:.2f} — crop/livestock supply tightness supports "
                    "food prices and inflation hedges"
                ),
                confidence=conf,
                evidence=evidence_base,
                domain_context="supply_shortfall",
            )
        )
        signals.append(
            build_market_impact_signal(
                sector="Rates / Inflation Sensitivity",
                tickers=["TLT"],
                bias="BEARISH" if drought >= 0.65 else "NEUTRAL",
                reason="Elevated agricultural drought stress raises food-inflation pass-through risk",
                confidence=max(0.44, conf - 0.04),
                evidence=evidence_base,
                domain_context="supply_shortfall",
            )
        )

    if supply_expansion:
        signals.append(
            build_market_impact_signal(
                sector="Agribusiness / Materials",
                tickers=["XLB", "SPY"],
                bias="BULLISH" if trend >= 0.72 else "NEUTRAL",
                reason=(
                    f"Production trend strong (score {trend:.2f}) with contained drought risk "
                    f"({drought:.2f}) — favorable input/output flow for fertilizer and equipment"
                ),
                confidence=conf,
                evidence=evidence_base,
                domain_context="supply_expansion",
            )
        )

    if grain_output_strong and not supply_shortfall:
        signals.append(
            build_market_impact_signal(
                sector="Grain Belt / Emerging Markets Trade",
                tickers=["EEM", "SPY"],
                bias="NEUTRAL",
                reason="Strong grain output supports export volume and EM agri-trade flow",
                confidence=max(0.42, conf - 0.05),
                evidence=evidence_base,
                domain_context="grain_export",
            )
        )

    if livestock_output_strong and not supply_shortfall:
        signals.append(
            build_market_impact_signal(
                sector="Staples / Protein Supply",
                tickers=["XLP"],
                bias="NEUTRAL",
                reason="Strong livestock output keeps protein supply chains well-stocked",
                confidence=max(0.42, conf - 0.05),
                evidence=evidence_base,
                domain_context="livestock_supply",
            )
        )

    if not signals:
        signals.append(
            build_market_impact_signal(
                sector="Broad Market",
                tickers=["SPY"],
                bias="NEUTRAL",
                reason=(
                    f"USDA NASS production trend balanced ({label.lower() or 'neutral'}) — "
                    "no acute macro tilt"
                ),
                confidence=conf,
                evidence=evidence_base,
                domain_context="baseline",
            )
        )

    return signals


def sales_consumer_market_impact_signals(
    *,
    consumer_strength: float,
    breadth_pct: float,
    momentum_index: float,
    discretionary_premium_pct: float | None = None,
    strength_label: str = "",
    leading_category: str = "",
    category_momentum: float | None = None,
    e_commerce_weak: bool = False,
    source: str = "sales-analytics",
) -> list[dict[str, Any]]:
    """Translate retail/consumer BI readings into broad market picks."""
    signals: list[dict[str, Any]] = []
    strength = float(consumer_strength or 0.0)
    breadth = float(breadth_pct or 50.0)
    momentum = float(momentum_index or 0.0)
    label = str(strength_label or "").strip()
    evidence_base: dict[str, Any] = {
        "consumer_strength": round(strength, 3),
        "breadth_pct": round(breadth, 1),
        "momentum_index": round(momentum, 3),
        "source": source,
    }
    if discretionary_premium_pct is not None:
        evidence_base["discretionary_premium_pct"] = round(float(discretionary_premium_pct), 2)

    conf = retail_signal_confidence(
        momentum=max(strength, momentum),
        return_20d_pct=None,
        breadth_pct=breadth,
        consumer_strength=strength,
    )

    risk_on_consumer = strength >= 0.62 and breadth >= 55.0
    risk_off_consumer = strength <= 0.38 and breadth <= 45.0
    discretionary_leading = (
        discretionary_premium_pct is not None and float(discretionary_premium_pct) > 0.8
    )
    staples_leading = (
        discretionary_premium_pct is not None and float(discretionary_premium_pct) < -0.8
    )

    if risk_on_consumer:
        signals.append(
            build_market_impact_signal(
                sector="Consumer Discretionary / Broad Market",
                tickers=["SPY", "XLY", "IWM"],
                bias="BULLISH",
                reason=(
                    f"Strong consumer backdrop ({label or 'risk-on'}) — "
                    f"strength {strength:.2f}, breadth {breadth:.0f}%"
                ),
                confidence=conf,
                evidence=evidence_base,
                domain_context="consumer_strength",
            )
        )

    if risk_off_consumer:
        signals.append(
            build_market_impact_signal(
                sector="Consumer / Cyclicals",
                tickers=["SPY", "XLY", "IWM"],
                bias="BEARISH",
                reason=(
                    f"Weak consumer demand signal — strength {strength:.2f}, "
                    f"breadth {breadth:.0f}%"
                ),
                confidence=conf,
                evidence=evidence_base,
                domain_context="consumer_weakness",
            )
        )
        signals.append(
            build_market_impact_signal(
                sector="Defensive Rotation",
                tickers=["XLP", "TLT"],
                bias="BULLISH" if strength <= 0.32 else "NEUTRAL",
                reason="Soft retail breadth favors staples and defensive duration",
                confidence=max(0.45, conf - 0.03),
                evidence=evidence_base,
                domain_context="consumer_weakness",
            )
        )

    if leading_category and category_momentum is not None and category_momentum >= 0.58:
        signals.append(
            build_market_impact_signal(
                sector=f"Category Momentum — {leading_category}",
                tickers=["XLY", "SPY"],
                bias="BULLISH",
                reason=f"Leading retail category momentum {category_momentum:.2f} — discretionary tilt",
                confidence=conf,
                evidence={**evidence_base, "leading_category": leading_category},
                domain_context="category_leader",
            )
        )

    if discretionary_leading and not risk_off_consumer:
        signals.append(
            build_market_impact_signal(
                sector="Discretionary vs Staples",
                tickers=["XLY", "SPY"],
                bias="BULLISH",
                reason=(
                    f"Discretionary premium {float(discretionary_premium_pct):+.2f}% — "
                    "consumer risk appetite improving"
                ),
                confidence=conf,
                evidence=evidence_base,
                domain_context="discretionary_rotation",
            )
        )

    if staples_leading:
        signals.append(
            build_market_impact_signal(
                sector="Staples Rotation",
                tickers=["XLP", "SPY"],
                bias="NEUTRAL",
                reason=(
                    f"Discretionary premium {float(discretionary_premium_pct):+.2f}% — "
                    "defensive consumer rotation"
                ),
                confidence=max(0.44, conf - 0.04),
                evidence=evidence_base,
                domain_context="staples_rotation",
            )
        )

    if e_commerce_weak:
        signals.append(
            build_market_impact_signal(
                sector="Growth / E-Commerce",
                tickers=["QQQ", "XLY", "SPY"],
                bias="BEARISH",
                reason="E-commerce momentum deterioration — drag on growth and discretionary beta",
                confidence=max(0.48, conf - 0.02),
                evidence=evidence_base,
                domain_context="ecommerce_weakness",
            )
        )

    if not risk_on_consumer and not risk_off_consumer and not signals:
        signals.append(
            build_market_impact_signal(
                sector="Broad Market",
                tickers=["SPY"],
                bias="NEUTRAL",
                reason=f"Balanced consumer backdrop ({label or 'neutral'}) — no strong macro tilt",
                confidence=conf,
                evidence=evidence_base,
                domain_context="baseline",
            )
        )

    if not signals:
        signals.append(
            build_market_impact_signal(
                sector="Broad Market",
                tickers=["SPY"],
                bias="NEUTRAL",
                reason="Retail sales proxies show no acute directional consumer signal",
                confidence=0.42,
                evidence=evidence_base,
                domain_context="baseline",
            )
        )

    return signals


def load_peer_agent_output(filename: str) -> dict[str, Any] | None:
    path = OUTPUT / filename
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def meteorology_agricultural_risk_score() -> float | None:
    """Read prior-cycle meteorology assessment for crop/drought risk alignment."""
    data = load_peer_agent_output("meteorology.json")
    if not data:
        return None
    metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
    for key in ("drought_risk_score", "agricultural_stress_score", "heat_stress_score"):
        if metrics.get(key) is not None:
            try:
                return float(metrics[key])
            except (TypeError, ValueError):
                continue
    assessment = data.get("assessment") if isinstance(data.get("assessment"), dict) else {}
    text = " ".join(str(v) for v in assessment.values()).lower()
    if "drought" in text or "heat/drought" in text:
        return 0.72
    if "flood" in text or "severe" in text:
        return 0.58
    if "moderate" in text:
        return 0.5
    return 0.4


def migration_market_impact_signals(
    *,
    pressure_score: float,
    pressure_label: str,
    avg_remit_pct: float,
    dependency_score: float,
    top_remit: list[dict[str, Any]],
    most_dependent: dict[str, Any] | None,
    corridor_tickers: list[str],
    source: str = "migration",
) -> list[dict[str, Any]]:
    """Translate World Bank / MPI migration metrics into market-facing signals."""
    signals: list[dict[str, Any]] = []
    pressure = float(pressure_score or 0.0)
    avg_pct = float(avg_remit_pct or 0.0)
    dependency = float(dependency_score or 0.0)
    evidence_base: dict[str, Any] = {
        "migration_pressure_score": round(pressure, 1),
        "avg_remittance_pct_gdp": round(avg_pct, 1),
        "remittance_dependency_score": round(dependency, 1),
        "pressure_label": pressure_label,
        "source": source,
    }

    leader = top_remit[0] if top_remit else {}
    leader_name = str(leader.get("name") or "")
    leader_usd = float(leader.get("remittances_usd") or 0.0)
    pay_tickers = corridor_tickers[:6] or ["WU", "PYPL"]
    conf = round(_clamp(0.42 + pressure / 200.0 + avg_pct / 50.0), 3)

    if leader_name:
        signals.append(
            build_market_signal(
                sector="Remittances & Cross-Border Payments",
                tickers=pay_tickers,
                bias="NEUTRAL",
                reason=(
                    f"Top remittance corridor {leader_name} "
                    f"(${leader_usd / 1e9:.1f}B/yr) — {pressure_label.lower()}"
                ),
                confidence=conf,
                evidence={**evidence_base, "leader_country": leader_name},
            )
        )

    em_bias = "BEARISH" if avg_pct >= 10 else "BULLISH" if avg_pct <= 3 and pressure < 35 else "NEUTRAL"
    signals.append(
        build_market_impact_signal(
            sector="Emerging Market Currencies (Remittance-Linked)",
            tickers=["EEM", "EWW", "INDA", "EWZ"],
            bias=em_bias,
            reason=f"Average remittance dependency {avg_pct:.1f}% of GDP across tracked corridors",
            confidence=round(_clamp(0.4 + avg_pct / 25.0), 3),
            evidence=evidence_base,
            domain_context="remittance_dependency",
        )
    )

    if pressure >= 55:
        signals.append(
            build_market_signal(
                sector="US Labor Supply (Staffing, Agriculture, Construction)",
                tickers=["ASGN", "RHI", "MAN", "LEN", "DHI"],
                bias="BULLISH" if pressure >= 65 else "NEUTRAL",
                reason=(
                    f"Migration pressure score {pressure:.0f} — sustained corridor outflows "
                    "support elastic US labor supply"
                ),
                confidence=round(_clamp(0.38 + pressure / 250.0), 3),
                evidence=evidence_base,
            )
        )

    if most_dependent:
        dep_pct = float(most_dependent.get("remittances_pct_gdp") or 0.0)
        dep_name = str(most_dependent.get("name") or "")
        dep_tickers = list(most_dependent.get("tickers") or ["WU"])
        if dep_pct >= 8:
            signals.append(
                build_market_signal(
                    sector="Single-Corridor Remittance Risk",
                    tickers=dep_tickers[:4],
                    bias="BEARISH" if dep_pct >= 15 else "NEUTRAL",
                    reason=(
                        f"{dep_name} remittances equal {dep_pct:.1f}% of GDP — "
                        "high sensitivity to US/Gulf hiring cycles"
                    ),
                    confidence=round(_clamp(0.4 + dep_pct / 30.0), 3),
                    evidence={
                        **evidence_base,
                        "country": dep_name,
                        "remittances_pct_gdp": round(dep_pct, 1),
                    },
                )
            )

    if not signals:
        signals.append(
            build_market_impact_signal(
                sector="Broad Market",
                tickers=["SPY"],
                bias="NEUTRAL",
                reason=f"Migration metrics balanced — {pressure_label.lower()}",
                confidence=0.42,
                evidence=evidence_base,
                domain_context="baseline",
            )
        )
    return signals


def meteorology_energy_score() -> float | None:
    """Read prior-cycle meteorology stress for energy-grid alignment."""
    data = load_peer_agent_output("meteorology.json")
    if not data:
        return None
    metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
    for key in ("energy_demand_score", "weather_energy_score", "energy_stress_score", "energy_score"):
        if metrics.get(key) is not None:
            try:
                return float(metrics[key])
            except (TypeError, ValueError):
                continue
    assessment = data.get("assessment") if isinstance(data.get("assessment"), dict) else {}
    text = " ".join(str(v) for v in assessment.values()).lower()
    if "elevated" in text or "high demand" in text:
        return 0.72
    if "moderate" in text:
        return 0.55
    return 0.4


def retail_signal_confidence(
    *,
    momentum: float,
    return_20d_pct: float | None,
    breadth_pct: float,
    consumer_strength: float,
) -> float:
    momentum_factor = _clamp((momentum - 0.45) / 0.35, 0.0, 1.0)
    return_factor = _clamp((float(return_20d_pct or 0.0)) / 8.0, 0.0, 1.0) if return_20d_pct else 0.35
    breadth_factor = _clamp(breadth_pct / 100.0, 0.0, 1.0)
    strength_factor = _clamp((consumer_strength - 0.4) / 0.35, 0.0, 1.0)
    return round(
        _clamp(0.38 + 0.22 * momentum_factor + 0.18 * return_factor + 0.12 * breadth_factor + 0.1 * strength_factor),
        3,
    )


def breadth_risk_signal_confidence(
    breadth: float | None,
    risk_on: float,
    *,
    momentum: float | None = None,
) -> float:
    """Tape breadth + risk posture for macro market agents."""
    breadth_factor = _clamp(abs(float(breadth or 0.0)) / 0.8, 0.0, 1.0)
    risk_factor = _clamp(abs(risk_on - 0.5) * 2.0, 0.0, 1.0)
    mom_factor = _clamp((float(momentum or 0.5) - 0.45) / 0.35, 0.0, 1.0) if momentum is not None else 0.4
    return round(_clamp(0.38 + 0.28 * breadth_factor + 0.22 * risk_factor + 0.12 * mom_factor), 3)


def quant_signal_confidence(
    *,
    momentum: float,
    mc_prob_up: float | None = None,
    z_score: float | None = None,
    stress: float | None = None,
) -> float:
    """Monte Carlo / z-score confidence for quant cluster agents."""
    mom_factor = _clamp((momentum - 0.45) / 0.35, 0.0, 1.0)
    mc_factor = _clamp((float(mc_prob_up or 0.5) - 0.48) / 0.12, 0.0, 1.0) if mc_prob_up is not None else 0.35
    z_factor = _clamp(abs(float(z_score or 0.0)) / 2.0, 0.0, 1.0) if z_score is not None else 0.3
    stress_factor = _clamp(float(stress or 0.0) / 0.6, 0.0, 1.0) if stress is not None else 0.25
    return round(
        _clamp(0.36 + 0.24 * mom_factor + 0.2 * mc_factor + 0.12 * z_factor + 0.08 * stress_factor),
        3,
    )


def sector_rotation_confidence(
    day_chg_pct: float | None,
    *,
    week_chg_pct: float | None = None,
    risk_reward: float | None = None,
) -> float:
    """Sector rotation move strength from live quote deltas."""
    day_factor = _clamp(abs(float(day_chg_pct or 0.0)) / 1.5, 0.0, 1.0)
    week_factor = _clamp(abs(float(week_chg_pct or 0.0)) / 3.0, 0.0, 1.0) if week_chg_pct is not None else 0.35
    rr_factor = _clamp((float(risk_reward or 0.5) - 0.45) / 0.25, 0.0, 1.0) if risk_reward is not None else 0.35
    return round(_clamp(0.4 + 0.32 * day_factor + 0.16 * week_factor + 0.12 * rr_factor), 3)


def grid_power_confidence(
    *,
    renewable_pct: float | None = None,
    gas_pct: float | None = None,
    lmp: float | None = None,
    grid_stress: float | None = None,
) -> float:
    """ISO fuel mix / wholesale price signal strength."""
    ren_factor = _clamp((float(renewable_pct or 0.0) - 25.0) / 25.0, 0.0, 1.0) if renewable_pct is not None else 0.35
    gas_factor = _clamp((float(gas_pct or 0.0) - 30.0) / 25.0, 0.0, 1.0) if gas_pct is not None else 0.3
    lmp_factor = _clamp(abs(float(lmp or 35.0) - 35.0) / 25.0, 0.0, 1.0) if lmp is not None else 0.35
    stress_factor = _clamp(float(grid_stress or 0.0) / 70.0, 0.0, 1.0) if grid_stress is not None else 0.25
    return round(
        _clamp(0.38 + 0.22 * ren_factor + 0.18 * gas_factor + 0.14 * lmp_factor + 0.08 * stress_factor),
        3,
    )


def freight_logistics_confidence(
    freight: float,
    *,
    congestion: float | None = None,
    stress: float | None = None,
    lane_density: float | None = None,
) -> float:
    """Shipping corridor / freight momentum confidence."""
    freight_factor = _clamp((freight - 0.4) / 0.35, 0.0, 1.0)
    cong_factor = _clamp(abs(float(congestion or 0.0) - 0.5) * 2.0, 0.0, 1.0) if congestion is not None else 0.3
    stress_factor = _clamp(float(stress or 0.0) / 0.65, 0.0, 1.0) if stress is not None else 0.25
    density_factor = _clamp((float(lane_density or 0.0) - 0.5) / 0.3, 0.0, 1.0) if lane_density is not None else 0.3
    return round(
        _clamp(0.38 + 0.28 * freight_factor + 0.16 * cong_factor + 0.1 * stress_factor + 0.08 * density_factor),
        3,
    )


def hypothesis_test_confidence(
    *,
    p_value: float,
    significant: bool,
    statistic: float | None = None,
    alpha: float = 0.05,
) -> float:
    """Statistical inference — low confidence unless test clears alpha."""
    if not significant or p_value >= alpha:
        return round(_clamp(0.38 + (alpha - min(p_value, alpha)) / alpha * 0.12, 0.35, 0.5), 3)
    sig_strength = _clamp((alpha - p_value) / alpha, 0.0, 1.0)
    stat_strength = _clamp(abs(float(statistic or 0.0)) / 2.5, 0.0, 1.0) if statistic is not None else 0.4
    return round(_clamp(0.52 + 0.28 * sig_strength + 0.12 * stat_strength, 0.45, 0.9), 3)


def cross_section_confidence(
    statistical_score: float,
    *,
    breadth_pct: float | None = None,
    z_score: float | None = None,
) -> float:
    """Cross-sectional breadth / z-score confidence for statistical agents."""
    score_factor = _clamp(abs(statistical_score - 0.5) * 2.0, 0.0, 1.0)
    breadth_factor = _clamp(abs(float(breadth_pct or 50.0) - 50.0) / 30.0, 0.0, 1.0) if breadth_pct is not None else 0.35
    z_factor = _clamp(abs(float(z_score or 0.0)) / 2.0, 0.0, 1.0) if z_score is not None else 0.3
    return round(_clamp(0.4 + 0.3 * score_factor + 0.18 * breadth_factor + 0.12 * z_factor), 3)


def conditional_prob_confidence(
    prob: float,
    *,
    sample_size: int = 0,
    min_samples: int = 60,
) -> float:
    """Empirical conditional probability confidence."""
    return confidence_from_edge(prob, samples=sample_size, min_samples=min_samples)