#!/usr/bin/env python3
"""Finance repo — run intelligence agents from the command line."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from agents.datascience import run_datascience_analysis
from agents.electricity import run_electricity_analysis
from agents.events import run_events_analysis
from agents.geopolitics import run_geopolitics_analysis
from agents.grid import run_grid_analysis
from agents.logistics import run_logistics_analysis
from agents.markets import run_markets_analysis
from agents.meteorology import run_meteorology_analysis
from agents.patents import run_patents_analysis
from agents.transportation import run_transportation_analysis


def _print_signals(signals: list[dict[str, Any]]) -> None:
    if not signals:
        return
    print("  Market signals:")
    for sig in signals:
        tickers = ", ".join(sig.get("tickers", []))
        print(f"    • {sig.get('sector')} [{sig.get('bias')}] — {tickers}")
        print(f"      {sig.get('reason')}")
    print()


def _print_recs(recs: list[str], limit: int = 10) -> None:
    if not recs:
        return
    print("  Recommendations:")
    for r in recs[:limit]:
        print(f"    • {r}")
    print()


def _print_meteorology(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')} — {meta.get('region_name', '')}")
    print("=" * 60)
    print(f"  {meta.get('national_headline', '')}")
    print()
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(f"  Disruption: {metrics.get('disruption_label')} ({metrics.get('disruption_score')})")
    print(f"  Heat: {metrics.get('heat_stress_score')}  |  Cold: {metrics.get('cold_stress_score')}")
    print(f"  Severe: {metrics.get('severe_weather_score')}  |  Flood: {metrics.get('flood_risk_score')}")
    print(f"  Energy demand: {metrics.get('energy_demand_score')}")
    print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_markets(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')}")
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(f"  Regime: {metrics.get('trend_label')} (risk-on {metrics.get('risk_on_score')})")
    print(f"  Breadth: {metrics.get('breadth_score')}  |  Momentum: {metrics.get('momentum_score')}")
    print()
    for q in data.get("indices", [])[:5]:
        wk = f" / 1w {q.get('week_chg_pct'):+.2f}%" if q.get("week_chg_pct") is not None else ""
        print(f"  • {q.get('symbol')}: {q.get('day_chg_pct'):+.2f}%{wk}")
    print()
    print("  Sector leaders:")
    for s in data.get("sectors", [])[:5]:
        print(f"    #{s.get('rank')} {s.get('sector')} ({s.get('etf')}): {s.get('day_chg_pct'):+.2f}%")
    print()
    gainers = data.get("top_gainers", [])[:5]
    if gainers:
        print("  Top gainers: " + ", ".join(
            f"{g.get('symbol')} {g.get('day_chg_pct'):+.2f}%" for g in gainers
        ))
        print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_geopolitics(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')} — {meta.get('headlines_analyzed', 0)} headlines")
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(f"  Risk: {metrics.get('risk_label')} ({metrics.get('global_risk_score')})")
    print(f"  Escalation index: {metrics.get('escalation_index')}")
    print(f"  Sources: {', '.join(meta.get('data_sources', []))}")
    print()
    for t in data.get("theaters", []):
        if t.get("article_count", 0) > 0:
            print(
                f"  • {t.get('name')}: risk {t.get('risk_score')} "
                f"({t.get('article_count')} articles)"
            )
    print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_datascience(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    mc = meta.get("monte_carlo", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')} — {meta.get('tickers_analyzed', 0)} tickers")
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(f"  Regime: {metrics.get('stress_label')} (stress {metrics.get('quant_stress_score')})")
    print(f"  Opportunity score: {metrics.get('opportunity_score')}")
    if mc:
        print(f"  Monte Carlo: {mc.get('simulations')} sims × {mc.get('horizon_days')} days")
    print()
    print("  Factor rankings (momentum):")
    for t in sorted(data.get("tickers", []), key=lambda x: x.get("momentum_score", 0), reverse=True)[:6]:
        print(
            f"    • {t.get('symbol')}: mom {t.get('momentum_score')} | "
            f"z {t.get('z_score_20d'):+.2f} | 20d {t.get('return_20d_pct'):+.2f}% | "
            f"MC P(up) {t.get('mc_prob_up_5d'):.0%}"
        )
    print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_events(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    summary = data.get("summary", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')} — {meta.get('events_tracked', 0)} events")
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(f"  Critical: {summary.get('critical_count', 0)}")
    by_imp = summary.get("by_impact", {})
    print(
        f"  Impact mix: "
        f"critical {by_imp.get('critical', 0)}, high {by_imp.get('high', 0)}, "
        f"medium {by_imp.get('medium', 0)}, low {by_imp.get('low', 0)}"
    )
    print(f"  Sources: {', '.join(meta.get('data_sources', []))}")
    print()
    print("  Recent events:")
    for e in data.get("events", [])[:8]:
        print(
            f"    • [{e.get('impact', '?').upper()}] {e.get('title', '')[:70]} "
            f"— {e.get('region', '')}"
        )
    print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_grid(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    assessment = data.get("electrical_assessment", {})
    print()
    print("=" * 60)
    print(
        f"  {meta.get('agent', 'Agent')} — "
        f"{meta.get('markets_monitored', 0)} ISO/RTO markets"
    )
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(
        f"  Stress: {metrics.get('stress_label')} "
        f"({metrics.get('grid_stress_score')})"
    )
    print(
        f"  Renewable index: {metrics.get('renewable_index')} | "
        f"CAISO net demand: {metrics.get('caiso_net_demand_mw', 'n/a')} MW"
    )
    print(f"  Sources: {', '.join(meta.get('data_sources', []))}")
    print()
    print("  Live fuel mix:")
    for f in data.get("fuel_mix", []):
        print(
            f"    • {f.get('market')}: {f.get('total_mw', 0):,.0f} MW | "
            f"renewable {f.get('renewable_pct')}% | gas {f.get('gas_pct')}% | "
            f"wind {f.get('wind_mw', 0):,.0f} | solar {f.get('solar_mw', 0):,.0f}"
        )
    print()
    print("  ISO demand (EIA hourly):")
    for d in sorted(data.get("iso_demand", []), key=lambda x: -x.get("demand_mw", 0))[:5]:
        print(f"    • {d.get('name')}: {d.get('demand_mw', 0):,.0f} MW ({d.get('period')})")
    print()
    prices = data.get("hub_prices", [])
    if prices:
        print("  ERCOT hub LMP:")
        for p in prices:
            print(f"    • {p.get('hub')}: ${p.get('lmp', 0):.2f}/MWh")
        print()
    if assessment:
        print("  Electrical assessment:")
        for key in ("generation_mix", "wholesale_pricing", "storage_dispatch"):
            if assessment.get(key):
                print(f"    • {assessment[key]}")
        print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_electricity(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    assessment = data.get("electrical_assessment", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')} — US48 Electric Overview")
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(
        f"  Balance: {metrics.get('stress_label')} "
        f"({metrics.get('grid_balance_score')})"
    )
    print(
        f"  Demand: {metrics.get('total_demand_mw', 0):,.0f} MW | "
        f"Net gen: {metrics.get('net_generation_mw', 0):,.0f} MW | "
        f"Gap: {metrics.get('supply_demand_gap_mw', 0):+,.0f} MW"
    )
    print(
        f"  Fuel mix: gas {metrics.get('gas_pct')}% | "
        f"coal {metrics.get('coal_pct')}% | "
        f"renewables {metrics.get('renewable_pct')}%"
    )
    print(f"  Sources: {', '.join(meta.get('data_sources', []))}")
    print()
    print("  Hourly fuel mix:")
    for f in data.get("fuel_mix", [])[:8]:
        print(
            f"    • {f.get('fuel_name')}: {f.get('generation_mwh', 0):,.0f} MWh "
            f"({f.get('share_pct')}%) — {f.get('period')}"
        )
    print()
    print("  ISO demand breakdown:")
    for d in sorted(data.get("iso_breakdown", []), key=lambda x: -x.get("demand_mw", 0))[:6]:
        print(
            f"    • {d.get('region_name')}: {d.get('demand_mw', 0):,.0f} MW "
            f"({d.get('period')})"
        )
    print()
    if assessment:
        print("  Electrical assessment:")
        for key in (
            "supply_demand_balance",
            "fuel_dominance",
            "renewable_penetration",
            "regional_load",
            "gas_reliance",
            "dashboard_note",
        ):
            if assessment.get(key):
                print(f"    • {assessment[key]}")
        print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_transportation(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    civil = data.get("civil_assessment", {})
    print()
    print("=" * 60)
    print(
        f"  {meta.get('agent', 'Agent')} — "
        f"{meta.get('resources_cataloged', 0)} DOT resources"
    )
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(
        f"  Stress: {metrics.get('stress_label')} "
        f"({metrics.get('infrastructure_stress_score')})"
    )
    print(
        f"  Freight momentum: {metrics.get('freight_momentum_score')} | "
        f"Unknown bridge designs: {metrics.get('unknown_design_pct')}%"
    )
    print(f"  Sources: {', '.join(meta.get('data_sources', []))}")
    print()
    print("  Top railroad bridge states:")
    for s in data.get("bridge_inventory", {}).get("top_states", [])[:6]:
        print(
            f"    #{s.get('rank')} {s.get('state')}: "
            f"{s.get('bridge_count', 0):,} bridges ({s.get('share_pct')}%)"
        )
    print()
    print("  Recent traffic (week / all / truck %):")
    for w in data.get("traffic", [])[:4]:
        print(
            f"    • {w.get('year')}-W{w.get('week')}: "
            f"all {w.get('all_vehicles_chg_pct'):+.0f}% | "
            f"truck {w.get('truck_chg_pct'):+.0f}%"
        )
    print()
    if civil:
        print("  Civil assessment:")
        for key in ("bridge_condition", "traffic_demand", "freight_corridor"):
            if civil.get(key):
                print(f"    • {civil[key]}")
        print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_patents(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    summary = data.get("summary", {})
    print()
    print("=" * 60)
    print(
        f"  {meta.get('agent', 'Agent')} — "
        f"{meta.get('resources_tracked', 0)} resources, "
        f"{meta.get('findings_count', 0)} findings"
    )
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(
        f"  Landscape: {summary.get('landscape_label')} "
        f"(score {summary.get('innovation_score')})"
    )
    print(
        f"  Resources online: {summary.get('resources_online', 0)}/"
        f"{meta.get('resources_tracked', 0)}"
    )
    print(f"  Sources: {', '.join(meta.get('data_sources', []))}")
    print()
    print("  Top sectors:")
    for sector, count in sorted(
        summary.get("by_sector", {}).items(), key=lambda x: -x[1]
    )[:5]:
        print(f"    • {sector.replace('-', ' ').title()}: {count}")
    print()
    print("  Recent findings:")
    for f in data.get("findings", [])[:8]:
        print(
            f"    • [{f.get('sector', '?')}] {f.get('title', '')[:68]} "
            f"— {f.get('source', '')}"
        )
    print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


def _print_logistics(data: dict[str, Any]) -> None:
    meta = data.get("meta", {})
    metrics = data.get("metrics", {})
    print()
    print("=" * 60)
    print(f"  {meta.get('agent', 'Agent')} — {meta.get('corridors_monitored', 0)} corridors")
    print("=" * 60)
    if meta.get("expert_summary"):
        print("  Expert summary:")
        print(f"  {meta['expert_summary']}")
        print()
    print(f"  Stress: {metrics.get('stress_label')} ({metrics.get('supply_chain_stress_score')})")
    print(f"  Freight momentum: {metrics.get('freight_momentum_score')}")
    print(f"  Peak congestion: {metrics.get('congestion_score')}")
    print()
    for c in data.get("corridors", []):
        m = c.get("metrics", {})
        print(
            f"  • {c.get('name')}: {c.get('total_vessels')} vessels | "
            f"density {m.get('lane_density_score')} | congestion {m.get('congestion_score')}"
        )
    print()
    _print_signals(data.get("market_signals", []))
    _print_recs(data.get("recommendations", []))


PRINTERS: dict[str, Callable[[dict[str, Any]], None]] = {
    "datascience": _print_datascience,
    "electricity": _print_electricity,
    "events": _print_events,
    "geopolitics": _print_geopolitics,
    "grid": _print_grid,
    "logistics": _print_logistics,
    "markets": _print_markets,
    "meteorology": _print_meteorology,
    "patents": _print_patents,
    "transportation": _print_transportation,
}

RUNNERS: dict[str, Callable[..., dict[str, Any]]] = {
    "datascience": run_datascience_analysis,
    "electricity": run_electricity_analysis,
    "events": run_events_analysis,
    "geopolitics": run_geopolitics_analysis,
    "grid": run_grid_analysis,
    "logistics": run_logistics_analysis,
    "markets": run_markets_analysis,
    "meteorology": run_meteorology_analysis,
    "patents": run_patents_analysis,
    "transportation": run_transportation_analysis,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Finance intelligence agents")
    parser.add_argument(
        "agent",
        nargs="?",
        default="events",
        choices=sorted(RUNNERS.keys()),
        help="Agent to run (default: events)",
    )
    parser.add_argument("-o", "--output", type=Path, help="Write JSON report to this file")
    parser.add_argument("--json", action="store_true", help="Print full JSON to stdout")
    args = parser.parse_args()

    try:
        result = RUNNERS[args.agent](output=args.output)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        PRINTERS[args.agent](result)
        if args.output:
            print(f"  Full report saved to {args.output}")
            if args.agent == "events":
                tracker = args.output.parent / "world_events_tracker.json"
                if tracker.exists():
                    print(f"  Web tracker import file: {tracker}")
            if args.agent == "patents":
                catalog = args.output.parent / "patent_resources.json"
                if catalog.exists():
                    print(f"  Resource catalog: {catalog}")
            if args.agent == "transportation":
                catalog = args.output.parent / "dot_resources.json"
                if catalog.exists():
                    print(f"  DOT resource catalog: {catalog}")
            if args.agent == "grid":
                catalog = args.output.parent / "grid_markets.json"
                if catalog.exists():
                    print(f"  Grid markets catalog: {catalog}")
            if args.agent == "electricity":
                catalog = args.output.parent / "eia_grid_monitor_views.json"
                if catalog.exists():
                    print(f"  EIA Grid Monitor views: {catalog}")
            print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())