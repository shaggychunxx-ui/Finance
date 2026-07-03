#!/usr/bin/env python3
"""Finance repo — run intelligence agents from the command line."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agents.meteorology import run_meteorology_analysis


def _print_summary(data: dict) -> None:
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
    signals = data.get("market_signals", [])
    if signals:
        print("  Market signals:")
        for sig in signals:
            tickers = ", ".join(sig.get("tickers", []))
            print(f"    • {sig.get('sector')} [{sig.get('bias')}] — {tickers}")
            print(f"      {sig.get('reason')}")
    print()
    recs = data.get("recommendations", [])
    if recs:
        print("  Recommendations:")
        for r in recs[:8]:
            print(f"    • {r}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Finance intelligence agents")
    parser.add_argument(
        "agent",
        nargs="?",
        default="meteorology",
        choices=["meteorology"],
        help="Agent to run (default: meteorology)",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        help="Write JSON report to this file",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON to stdout",
    )
    args = parser.parse_args()

    try:
        if args.agent == "meteorology":
            result = run_meteorology_analysis(output=args.output)
        else:
            parser.error(f"Unknown agent: {args.agent}")
            return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _print_summary(result)
        if args.output:
            print(f"  Full report saved to {args.output}")
            print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())