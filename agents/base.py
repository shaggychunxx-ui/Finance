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
