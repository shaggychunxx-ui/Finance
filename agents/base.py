"""Shared base class for Finance intelligence agents.

Every agent Expert/Analyst class should inherit from ``BaseExpert`` (and call
``super().__init__()``) so that new agents automatically pick up shared,
repo-wide agent behavior — most notably per-run ``temperature`` stabilized
by learning posture and accuracy during pipeline runs (typically 2–4).

When adding a new agent, scan this file and inherit from ``BaseExpert``
instead of re-implementing this behavior by hand.

Personality traits (risk appetite, conviction, patience, etc.) are applied
centrally after each run via ``agent_personality.patch_agent_output_personality``;
configure them in ``config/agent_personalities.json``.
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

    def __init__(
        self,
        *,
        pipeline_context: dict[str, Any] | None = None,
        agent_id: str = "",
    ) -> None:
        self.agent_id = str(agent_id or "")
        self.pipeline_context: dict[str, Any] = dict(pipeline_context or {})
        if not self.pipeline_context and self.agent_id:
            try:
                from agents.pipeline_memory import memory_bundle_for_agent

                self.pipeline_context = memory_bundle_for_agent(self.agent_id)
            except Exception:
                pass
        self._enhance_requests: list[dict[str, Any]] = []
        self.temperature: int = self._resolve_temperature()

    def _resolve_temperature(self) -> int:
        if self.agent_id:
            try:
                from agent_temperature import resolve_agent_temperature

                return int(
                    resolve_agent_temperature(
                        self.agent_id,
                        pipeline_context=self.pipeline_context,
                    )["temperature"]
                )
            except Exception:
                pass
        return random.randint(MIN_TEMPERATURE, MAX_TEMPERATURE)

    def pipeline_memory_notes(self) -> list[str]:
        return list(self.pipeline_context.get("lessons") or [])

    def pipeline_should_skip_symbol(self, symbol: str) -> bool:
        sym = str(symbol or "").upper()
        avoid = {str(s).upper() for s in (self.pipeline_context.get("avoid_symbols") or [])}
        return sym in avoid

    def pipeline_symbol_confidence_factor(self, symbol: str) -> float:
        sym = str(symbol or "").upper()
        trust = {str(s).upper() for s in (self.pipeline_context.get("trust_symbols") or [])}
        avoid = {str(s).upper() for s in (self.pipeline_context.get("avoid_symbols") or [])}
        if sym in avoid:
            return 0.75
        if sym in trust:
            return 1.08
        return 1.0

    def append_memory_recommendations(self, recommendations: list[str]) -> list[str]:
        from agents.pipeline_memory import _prepend_memory_recommendations

        return _prepend_memory_recommendations(recommendations, self.pipeline_context)

    def domain_allows_symbol(self, symbol: str, *, sector_hint: str = "") -> bool:
        if not self.agent_id:
            return True
        try:
            from agent_constraints import domain_allows_symbol

            return domain_allows_symbol(self.agent_id, symbol, sector_hint=sector_hint)
        except Exception:
            return True

    def preferred_horizon(self) -> str:
        if self.pipeline_context.get("preferred_horizon"):
            return str(self.pipeline_context["preferred_horizon"])
        if not self.agent_id:
            return "24h"
        try:
            from agent_constraints import agent_preferred_horizon

            return agent_preferred_horizon(self.agent_id)
        except Exception:
            return "24h"

    def live_quote(self, symbol: str) -> dict[str, Any] | None:
        """Read a proactive/post-agent E*TRADE quote cached for this pipeline run."""
        from agents.enhancement import load_enhanced_quotes, normalize_tradeable_symbol

        trade = normalize_tradeable_symbol(symbol)
        if not trade:
            return None
        return load_enhanced_quotes().get(trade)

    def live_price(self, symbol: str) -> float | None:
        quote = self.live_quote(symbol)
        if not quote:
            return None
        last = quote.get("last_trade")
        try:
            return float(last) if last is not None else None
        except (TypeError, ValueError):
            return None

    def pipeline_watchlist_symbols(
        self,
        base: list[str] | None = None,
        *,
        limit: int = 32,
    ) -> list[str]:
        """Merge static watchlist with live quotes, memory trust, and bullish tickers."""
        seen: set[str] = set()
        ordered: list[str] = []
        candidates = list(base or [])
        candidates.extend(self.pipeline_context.get("live_quote_symbols") or [])
        candidates.extend(self.pipeline_context.get("persistent_bullish_tickers") or [])
        candidates.extend(self.pipeline_context.get("trust_symbols") or [])
        for raw in candidates:
            sym = str(raw or "").strip().upper()
            if not sym or sym in seen or self.pipeline_should_skip_symbol(sym):
                continue
            if not self.domain_allows_symbol(sym):
                continue
            seen.add(sym)
            ordered.append(sym)
            if len(ordered) >= limit:
                break
        return ordered

    def cross_agent_bias_votes(self) -> dict[str, dict[str, Any]]:
        cached = self.pipeline_context.get("cross_agent_votes")
        if isinstance(cached, dict):
            return cached
        try:
            from agent_disagreement import collect_agent_bias_votes

            same_cycle = self.pipeline_context.get("same_cycle_outputs")
            if isinstance(same_cycle, dict) and same_cycle:
                return collect_agent_bias_votes(
                    agent_outputs=same_cycle,
                    exclude_agent=self.agent_id,
                )
            return collect_agent_bias_votes(exclude_agent=self.agent_id)
        except Exception:
            return {}

    def adjust_signal_confidence(self, symbol: str, bias: str, base_confidence: float) -> float:
        """Apply memory trust/avoid and cross-agent disagreement to a raw confidence."""
        try:
            conf = float(base_confidence)
        except (TypeError, ValueError):
            conf = 0.5
        conf *= self.pipeline_symbol_confidence_factor(symbol)
        try:
            from agent_disagreement import disagreement_confidence_factor

            conf *= disagreement_confidence_factor(symbol, bias, self.cross_agent_bias_votes())
        except Exception:
            pass
        return round(max(0.08, min(0.99, conf)), 3)

    def fetch_yahoo_closes(
        self,
        symbol: str,
        *,
        range_: str = "6mo",
        interval: str = "1d",
    ) -> list[float]:
        from agents.market_data.yahoo import fetch_closes

        delay = float(getattr(self, "delay_seconds", 0.35))
        return fetch_closes(
            symbol,
            range_=range_,
            interval=interval,
            delay_seconds=delay,
            client_tag=self.agent_id or type(self).__name__,
        )

    def fetch_yahoo_ohlcv(
        self,
        symbol: str,
        *,
        range_: str = "3mo",
        interval: str = "1d",
    ) -> dict[str, list[float]]:
        from agents.market_data.yahoo import fetch_ohlcv

        delay = float(getattr(self, "delay_seconds", 0.35))
        return fetch_ohlcv(
            symbol,
            range_=range_,
            interval=interval,
            delay_seconds=delay,
            client_tag=self.agent_id or type(self).__name__,
        )

    def fetch_yahoo_chart_meta(
        self,
        symbol: str,
        *,
        range_: str = "1mo",
        interval: str = "1d",
    ) -> dict[str, Any] | None:
        from agents.market_data.yahoo import fetch_chart_meta

        delay = float(getattr(self, "delay_seconds", 0.35))
        return fetch_chart_meta(
            symbol,
            range_=range_,
            interval=interval,
            delay_seconds=delay,
            client_tag=self.agent_id or type(self).__name__,
        )

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

    def personality_meta(self, agent_id: str) -> dict[str, Any]:
        """Traits for this agent id (used when writing report meta)."""
        from agent_personality import get_agent_personality, personality_horizon_preference

        traits = get_agent_personality(agent_id)
        payload = traits.as_dict()
        payload["temperature"] = self.temperature
        if self.agent_id:
            payload["preferred_horizon"] = self.preferred_horizon()
        else:
            payload["preferred_horizon"] = personality_horizon_preference(agent_id)
        return payload