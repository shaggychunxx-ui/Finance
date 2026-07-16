"""Shared Yahoo + E*TRADE market data loading for Probability & Stats agents."""

from __future__ import annotations

from typing import Any

from agents.base import BaseExpert
from agents.enhancement import enhance_symbols_from_report
from agents.market_data.etrade import merge_live_return_into_series, tradeable_symbol


class ProbabilityMarketData:
    """Load historical series from Yahoo and align the latest bar with E*TRADE."""

    def __init__(self, expert: BaseExpert) -> None:
        self.expert = expert
        self.snapshots: dict[str, dict[str, Any]] = {}
        self._watchlist: dict[str, str] = {}

    def prepare_watchlist(self, base: dict[str, str], *, extra_limit: int = 8) -> dict[str, str]:
        merged = dict(base)
        extras = self.expert.pipeline_watchlist_symbols(
            base=list(base.keys()),
            limit=len(base) + extra_limit,
        )
        for sym in extras:
            key = str(sym).upper()
            if key in merged:
                continue
            if not self.expert.domain_allows_symbol(key):
                continue
            merged[key] = key
        self._watchlist = merged
        return merged

    def request_enhancement(self, watchlist: dict[str, str] | None = None) -> None:
        symbols = watchlist or self._watchlist
        for symbol in symbols:
            self.expert.request_enhanced_data(
                symbol,
                reason="Probability & Stats watchlist",
                priority=0.72,
            )

    def load_series(
        self,
        symbol: str,
        *,
        range_: str = "1y",
    ) -> tuple[list[float], list[float]]:
        closes = self.expert.fetch_yahoo_closes(symbol, range_=range_, interval="1d")
        if not closes:
            return [], []

        returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
        quote = self.expert.live_quote(symbol)
        if quote:
            returns, snap = merge_live_return_into_series(returns, quote, symbol=symbol)
            self.snapshots[str(symbol).upper()] = snap
        return closes, returns

    def live_market_signals(self) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal, sector_rotation_confidence

        signals: list[dict[str, Any]] = []
        for symbol, snap in self.snapshots.items():
            change_pct = snap.get("change_pct")
            session_ret = snap.get("session_return")
            trade_sym = snap.get("tradeable_symbol") or tradeable_symbol(symbol) or symbol
            try:
                day_pct = float(change_pct) if change_pct is not None else float(session_ret or 0) * 100.0
            except (TypeError, ValueError):
                continue
            if abs(day_pct) < 1.0:
                continue
            bias = "BULLISH" if day_pct > 0 else "BEARISH"
            spread = snap.get("bid_ask_spread_pct")
            conf = self.expert.adjust_signal_confidence(
                trade_sym,
                bias,
                sector_rotation_confidence(day_pct),
            )
            reason = f"E*TRADE live {day_pct:+.2f}% session move"
            if spread is not None and float(spread) >= 0.35:
                reason += f"; bid-ask spread {float(spread):.2f}%"
            signals.append(
                build_market_signal(
                    sector="E*TRADE Live Move",
                    tickers=[trade_sym],
                    bias=bias,
                    reason=reason,
                    confidence=conf,
                    evidence={
                        "data_source": "etrade",
                        "change_pct": change_pct,
                        "session_return": session_ret,
                        "bid_ask_spread_pct": spread,
                    },
                )
            )
        return signals

    def etrade_coverage_summary(self) -> dict[str, Any]:
        watch = self._watchlist or {}
        covered = [sym for sym in watch if sym in self.snapshots]
        return {
            "watchlist_size": len(watch),
            "etrade_quotes_used": len(covered),
            "symbols_with_live_return": sum(
                1 for snap in self.snapshots.values() if snap.get("live_return_applied")
            ),
            "symbols": sorted(self.snapshots.keys()),
        }

    def attach_to_result(self, result: dict[str, Any], *, market_signals: list[dict[str, Any]] | None = None) -> None:
        if self.snapshots:
            result["etrade_market_data"] = {
                "coverage": self.etrade_coverage_summary(),
                "quotes": self.snapshots,
            }
        sigs = market_signals if market_signals is not None else result.get("market_signals")
        extras = enhance_symbols_from_report(
            market_signals=sigs if isinstance(sigs, list) else None,
            extra_items=[
                (sym, 0.72, "Probability & Stats watchlist")
                for sym in (self._watchlist or {})
            ],
            agent_requests=self.expert.enhance_symbols_payload(),
            limit=16,
        )
        if extras:
            result["enhance_symbols"] = extras
        meta = result.setdefault("meta", {})
        sources = meta.get("sources")
        if isinstance(sources, list):
            if "E*TRADE live quotes" not in sources:
                sources.append("E*TRADE live quotes")
        else:
            meta["sources"] = ["Yahoo Finance Chart API", "E*TRADE live quotes"]