#!/usr/bin/env python3
"""Generate per-agent backtest command files.

Each agent's random ``BaseExpert.temperature`` (see ``agents/base.py``) is
re-rolled only when a *new process* instantiates the agent. To build a
1000-run backtest database with genuinely independent, randomly distributed
temperatures per run, each backtest must be its own ``run.bat <agent>``
invocation — never a single process looping 1000 times internally.

This script writes one ``.bat`` file per agent under ``backtest_commands/``,
containing 1000 individual, non-looping command lines. Each line runs the
agent once and saves its report to a uniquely numbered JSON file under
``output/backtest_db/<agent>/``, building up a database of independent runs
that can later be aggregated to study result variance across temperatures.

Usage:
    python generate_backtest_commands.py [--runs 1000] [--out backtest_commands]
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Keep in sync with main.py RUNNERS.
AGENTS = [
    "combined-conditional",
    "data-steward",
    "datascience",
    "electricity",
    "empirical-probability",
    "events",
    "financial-data",
    "finance",
    "geopolitics",
    "grid",
    "logistics",
    "markets",
    "meteorology",
    "patents",
    "records-management",
    "research-statistics",
    "sales-analytics",
    "theoretical-probability",
    "transportation",
]

DEFAULT_RUNS = 1000


def _command_lines(agent: str, runs: int) -> list[str]:
    lines = [
        "@echo off",
        f"REM {runs} individual backtest commands for the {agent} agent.",
        "REM Each line is its own run.bat invocation (no loop) so every",
        "REM process draws a fresh, independent BaseExpert.temperature.",
        "cd /d \"%~dp0..\"",
        "",
    ]
    width = len(str(runs))
    for i in range(1, runs + 1):
        run_id = str(i).zfill(width)
        out_path = f"output\\backtest_db\\{agent}\\run_{run_id}.json"
        lines.append(f'call run.bat {agent} -o "{out_path}"')
    lines.append("")
    return lines


def generate(out_dir: Path, runs: int) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for agent in AGENTS:
        path = out_dir / f"{agent}.bat"
        path.write_text("\r\n".join(_command_lines(agent, runs)), encoding="utf-8")
        written.append(path)

    runner_lines = [
        "@echo off",
        "REM Runs every agent's backtest command file in sequence.",
        "cd /d \"%~dp0\"",
        "",
    ]
    for agent in AGENTS:
        runner_lines.append(f"call {agent}.bat")
    runner_lines.append("")
    runner_path = out_dir / "run_all_backtests.bat"
    runner_path.write_text("\r\n".join(runner_lines), encoding="utf-8")
    written.append(runner_path)

    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate per-agent backtest command files")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS, help="Backtest commands per agent (default: 1000)")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "backtest_commands",
        help="Output directory for generated command files (default: backtest_commands/)",
    )
    args = parser.parse_args()

    if args.runs < 1:
        parser.error("--runs must be a positive integer")

    written = generate(args.out, args.runs)
    print(f"Wrote {len(written)} command files to {args.out}")
    for agent in AGENTS:
        print(f"  • {agent}: {args.runs} individual backtest commands")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
