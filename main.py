#!/usr/bin/env python3
"""Finance repo — run intelligence agents from the command line."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from agents.geopolitics import run_geopolitics_analysis
from agents.logistics import run_logistics_analysis
from agents.markets import run_markets_analysis
from agents.meteorology import run_meteorology_analysis


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
    "geopolitics": _print_geopolitics,
    "markets": _print_markets,
    "meteorology": _print_meteorology,
    "logistics": _print_logistics,
}

RUNNERS: dict[str, Callable[..., dict[str, Any]]] = {
    "geopolitics": run_geopolitics_analysis,
    "markets": run_markets_analysis,
    "meteorology": run_meteorology_analysis,
    "logistics": run_logistics_analysis,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Finance intelligence agents")
    parser.add_argument(
        "agent",
        nargs="?",
        default="markets",
        choices=sorted(RUNNERS.keys()),
        help="Agent to run (default: logistics)",
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
            print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())