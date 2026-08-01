#!/usr/bin/env python3
"""Macro / earnings-style event calendar flags for prediction quality.

Combines:
  - agent event feeds (world_events / geopolitics)
  - static high-impact US macro dates (FOMC, CPI windows, NFP first Fridays)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any


# Approximate 2026 FOMC decision days (public calendar — update yearly).
FOMC_DATES_2026 = {
    date(2026, 1, 28),
    date(2026, 3, 18),
    date(2026, 4, 29),
    date(2026, 6, 17),
    date(2026, 7, 29),
    date(2026, 9, 16),
    date(2026, 11, 4),
    date(2026, 12, 16),
}


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None


def first_friday(year: int, month: int) -> date:
    d = date(year, month, 1)
    while d.weekday() != 4:  # Friday
        d += timedelta(days=1)
    return d


def is_nfp_week(day: date) -> bool:
    ff = first_friday(day.year, day.month)
    return abs((day - ff).days) <= 1


def is_fomc_window(day: date, *, pad_days: int = 1) -> bool:
    for fd in FOMC_DATES_2026:
        if abs((day - fd).days) <= pad_days:
            return True
    return False


def event_flags(*, when: str | datetime | None = None) -> dict[str, Any]:
    """Return structured flags for today (UTC date unless ISO provided)."""
    if isinstance(when, datetime):
        day = when.astimezone(timezone.utc).date()
        when_s = when.isoformat()
    elif isinstance(when, str) and when:
        day = _parse_day(when) or datetime.now(timezone.utc).date()
        when_s = when
    else:
        day = datetime.now(timezone.utc).date()
        when_s = day.isoformat()

    flags = {
        "date": day.isoformat(),
        "as_of": when_s,
        "fomc_window": is_fomc_window(day),
        "nfp_window": is_nfp_week(day),
        "weekday": day.weekday(),
        "is_weekend": day.weekday() >= 5,
        "agent_high_impact": False,
        "labels": [],
    }
    try:
        from agent_fusion import is_event_day

        flags["agent_high_impact"] = bool(is_event_day(recorded_at=when_s))
    except Exception:
        pass

    if flags["fomc_window"]:
        flags["labels"].append("FOMC")
    if flags["nfp_window"]:
        flags["labels"].append("NFP")
    if flags["agent_high_impact"]:
        flags["labels"].append("AGENT_HIGH_IMPACT")

    flags["high_impact"] = bool(
        flags["fomc_window"] or flags["nfp_window"] or flags["agent_high_impact"]
    )
    return flags
