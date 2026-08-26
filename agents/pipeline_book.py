"""Live book the *pipeline* opened — not a human watchlist.

Held lots (e.g. BRVE, SOFI) are whatever the fused plan bought. Research
agents should look at those names first, then a small canned benchmark set.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_NON_EQUITY_HINTS = ("PRB", "TAI", "PHY", "ETM", "FPX")

# Known listed names for pipeline lots / common holders (CIK for EDGAR agents).
TICKER_META: dict[str, dict[str, Any]] = {
    "SOFI": {"company": "SoFi Technologies", "cik": 1818874, "sector": "Financials"},
    "BRVE": {"company": "Braveheart Bio", "cik": 2131524, "sector": "Healthcare"},
}


def _snapshot_paths() -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    return [
        Path.home() / "Finance" / "output" / "account_snapshot.json",
        root / "output" / "account_snapshot.json",
    ]


def pipeline_held_positions() -> list[dict[str, Any]]:
    """Equities the pipeline currently holds (qty != 0)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for snap in _snapshot_paths():
        if not snap.is_file():
            continue
        try:
            data = json.loads(snap.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for row in data.get("positions") or []:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").upper().strip()
            if not sym or sym in seen:
                continue
            if any(h in sym for h in _NON_EQUITY_HINTS):
                continue
            if len(sym) == 5 and sym.endswith("X") and sym.isalpha():
                continue
            try:
                if abs(float(row.get("quantity") or 0)) == 0:
                    continue
            except (TypeError, ValueError):
                continue
            seen.add(sym)
            meta = TICKER_META.get(sym) or {}
            company = str(
                row.get("company_name")
                or row.get("description")
                or meta.get("company")
                or sym
            )
            out.append(
                {
                    "symbol": sym,
                    "quantity": row.get("quantity"),
                    "company": company,
                    "cik": meta.get("cik"),
                    "sector": meta.get("sector") or "default",
                    "source": "pipeline_book",
                }
            )
        if out:
            break
    return out


def held_symbols() -> list[str]:
    return [str(r["symbol"]) for r in pipeline_held_positions()]


def held_first_watchlist(
    canned: dict[str, str],
    *,
    extra: list[str] | None = None,
    max_canned: int = 4,
    include_benchmark: str = "SPY",
) -> dict[str, str]:
    """Pipeline lots first, then a few canned names (benchmarks, not a mega-cap dump)."""
    ordered: dict[str, str] = {}
    for row in pipeline_held_positions():
        ordered[row["symbol"]] = f"Pipeline holding — {row.get('company') or row['symbol']}"
    if include_benchmark and include_benchmark not in ordered:
        ordered[include_benchmark] = canned.get(include_benchmark) or "Benchmark"
    n = 0
    for sym, label in canned.items():
        if sym in ordered:
            continue
        if n >= max_canned:
            break
        ordered[sym] = label
        n += 1
    for raw in extra or []:
        sym = str(raw or "").upper().strip()
        if sym and sym not in ordered:
            ordered[sym] = canned.get(sym) or f"Watch — {sym}"
    return ordered
