#!/usr/bin/env python3
"""Ensure main.py imports + RUNNERS cover every agents/*/run_*_analysis package."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from agents.platform_catalog import (
        _folder_to_id,
        _runner_from_package,
        discover_local_packages,
    )

    main_path = ROOT / "main.py"
    text = main_path.read_text(encoding="utf-8")
    to_add: list[tuple[str, str, str]] = []
    for pkg in discover_local_packages():
        runner = _runner_from_package(pkg)
        if runner is None:
            continue
        if f"from agents.{pkg} import" not in text:
            to_add.append((pkg, _folder_to_id(pkg), runner.__name__))

    if not to_add:
        print("main.py already lists all agent package runners.")
        return 0

    lines = text.splitlines(keepends=True)
    last_import_idx = 0
    for i, line in enumerate(lines):
        if line.startswith("from agents."):
            last_import_idx = i
    new_import_lines = [f"from agents.{pkg} import {fn}\n" for pkg, _aid, fn in sorted(to_add)]
    lines = lines[: last_import_idx + 1] + new_import_lines + lines[last_import_idx + 1 :]
    text2 = "".join(lines)

    runners_match = re.search(
        r"RUNNERS: dict\[str, Callable\[\.\.\., dict\[str, Any\]\]\] = \{([^}]*)\}",
        text2,
        re.S,
    )
    if runners_match is None:
        runners_match = re.search(
            r"RUNNERS: dict\[str, Callable.*?\] = \{([^}]*)\}",
            text2,
            re.S,
        )
    if runners_match is None:
        print("ERROR: RUNNERS block not found in main.py", file=sys.stderr)
        return 1

    body = runners_match.group(1)
    for _pkg, aid, fn in sorted(to_add):
        if f'"{aid}"' not in body and f"'{aid}'" not in body:
            body = body.rstrip() + f'\n    "{aid}": {fn},\n'
    new_runners = f"RUNNERS: dict[str, Callable[..., dict[str, Any]]] = {{{body}}}"
    text3 = text2[: runners_match.start()] + new_runners + text2[runners_match.end() :]
    main_path.write_text(text3, encoding="utf-8")
    print(f"Added {len(to_add)} agent runner(s) to main.py:")
    for pkg, aid, fn in sorted(to_add):
        print(f"  {aid} ({pkg}) -> {fn}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
