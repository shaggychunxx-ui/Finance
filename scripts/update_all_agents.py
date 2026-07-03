"""Run every existing Finance intelligence agent and write fresh reports to data/.

Used by the `.github/workflows/update-agents.yml` scheduled workflow to keep
the committed data (including the web tracker import file consumed by
`index.html`) up to date on an hourly cadence. Can also be run manually:

    python scripts/update_all_agents.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from main import RUNNERS  # noqa: E402  (import after sys.path setup)

DATA_DIR = REPO_ROOT / "data"


def main() -> int:
    DATA_DIR.mkdir(exist_ok=True)

    failures: list[str] = []
    for name, runner in sorted(RUNNERS.items()):
        output_path = DATA_DIR / f"{name}.json"
        try:
            runner(output=output_path)
            print(f"OK    {name} -> {output_path.relative_to(REPO_ROOT)}")
        except Exception as exc:  # noqa: BLE001 - keep refreshing other agents
            failures.append(name)
            print(f"FAILED {name}: {exc}", file=sys.stderr)

    if failures:
        print(
            f"{len(failures)} of {len(RUNNERS)} agent(s) failed: {', '.join(failures)}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
