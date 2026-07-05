"""Shared base class for Finance intelligence agents.

Every agent Expert/Analyst class should inherit from ``BaseExpert`` (and call
``super().__init__()``) so that new agents automatically pick up shared,
repo-wide agent behavior — most notably the per-run randomized
``temperature`` (1-8) that is drawn fresh each time an agent is instantiated
(i.e. each new analysis request) and reported in ``meta.temperature``.

When adding a new agent, scan this file and inherit from ``BaseExpert``
instead of re-implementing this behavior by hand.
"""

from __future__ import annotations

import random
from typing import Any

MIN_TEMPERATURE = 1
MAX_TEMPERATURE = 8


class BaseExpert:
    """Common base for all Finance agent Expert/Analyst classes.

    Subclasses that define their own ``__init__`` must call
    ``super().__init__()`` to ensure ``self.temperature`` is set.
    """

    def __init__(self) -> None:
        # Randomized creativity/variance level for this run's analysis
        # (1=conservative, 8=exploratory). Re-rolled on every new instance,
        # i.e. every new analysis request.
        self.temperature: int = random.randint(MIN_TEMPERATURE, MAX_TEMPERATURE)
        self._enhance_requests: list[dict[str, Any]] = []

    def request_enhanced_data(
        self,
        symbol: str,
        *,
        reason: str = "",
        priority: float = 0.7,
    ) -> None:
        """Ask the pipeline to fetch E*TRADE quotes for this symbol after the agent run."""
        from agents.enhancement import normalize_tradeable_symbol

        trade = normalize_tradeable_symbol(symbol)
        if not trade:
            return
        for req in self._enhance_requests:
            if req.get("symbol") == trade:
                req["priority"] = max(float(req.get("priority", 0)), priority)
                if reason and reason not in req.get("reasons", []):
                    req.setdefault("reasons", []).append(reason)
                return
        self._enhance_requests.append(
            {
                "symbol": trade,
                "priority": priority,
                "reason": reason or "Agent requested enhanced market data",
            }
        )

    def enhance_symbols_payload(self) -> list[dict[str, Any]]:
        return list(self._enhance_requests)