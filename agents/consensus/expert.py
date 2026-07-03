"""
Cross-Agent Consensus Expert
=============================
Runs every intelligence agent in this repo (markets, data science,
geopolitics, grid, electricity, meteorology, logistics, transportation,
patents, and world events) together to determine overall US market
conditions, then produces 24-hour and 1-week direction/return predictions
for the top 15 US market movers.

Data: Yahoo Finance chart API (mover price history) plus each agent's own
live public data sources.
"""

from __future__ import annotations

import json
import math
import random
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

from agents.datascience import run_datascience_analysis
from agents.electricity import run_electricity_analysis
from agents.events import run_events_analysis
from agents.geopolitics import run_geopolitics_analysis
from agents.grid import run_grid_analysis
from agents.logistics import run_logistics_analysis
from agents.markets import run_markets_analysis
from agents.meteorology import run_meteorology_analysis
from agents.patents import run_patents_analysis
from agents.transportation import run_transportation_analysis

CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Finance-Consensus-Expert/1.0 (shaggychunxx@gmail.com)"}

MC_SIMULATIONS = 4000
HORIZONS: dict[str, int] = {"24h": 1, "1w": 5}
MAX_MOVERS = 15
MACRO_DRIFT_PER_DAY = 0.0009  # max daily drift nudge applied at full macro tilt


@dataclass
class HorizonPrediction:
    horizon: str
    trading_days: int
    direction: str
    prob_up: float
    expected_return_pct: float
    low_return_pct: float
    high_return_pct: float


@dataclass
class MoverPrediction:
    symbol: str
    name: str
    day_chg_pct: float | None
    last_price: float | None
    vol_20d_ann_pct: float | None
    z_score_20d: float | None
    momentum_score: float | None
    data_quality: str
    predictions: list[HorizonPrediction]


@dataclass
class AgentBrief:
    agent: str
    status: str
    headline: str


@dataclass
class ConsensusReport:
    market_condition_score: float
    market_condition_label: str
    contributing_factors: list[str]
    agent_briefs: list[AgentBrief]
    movers: list[MoverPrediction]
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    expert_summary: str
    data_sources: list[str]
    agents_consulted: int
    agents_succeeded: int
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ConsensusExpert:
    """Combines every agent in the repo into one US market-conditions read
    and 24h / 1-week predictions for the top 15 market movers."""

    AGENTS: dict[str, Callable[..., dict[str, Any]]] = {
        "markets": run_markets_analysis,
        "datascience": run_datascience_analysis,
        "geopolitics": run_geopolitics_analysis,
        "grid": run_grid_analysis,
        "electricity": run_electricity_analysis,
        "meteorology": run_meteorology_analysis,
        "logistics": run_logistics_analysis,
        "transportation": run_transportation_analysis,
        "patents": run_patents_analysis,
        "events": run_events_analysis,
    }

    def __init__(self, delay_seconds: float = 0.3) -> None:
        self.delay_seconds = delay_seconds

    # ------------------------------------------------------------------
    # Agent orchestration
    # ------------------------------------------------------------------
    def _collect_agents(self) -> dict[str, dict[str, Any] | None]:
        results: dict[str, dict[str, Any] | None] = {}
        for name, runner in self.AGENTS.items():
            try:
                results[name] = runner()
            except Exception:
                results[name] = None
        return results

    @staticmethod
    def _agent_briefs(results: dict[str, dict[str, Any] | None]) -> list[AgentBrief]:
        briefs: list[AgentBrief] = []
        for name, data in results.items():
            if not data:
                briefs.append(AgentBrief(agent=name, status="error", headline="Agent unavailable"))
                continue
            meta = data.get("meta", {})
            headline = meta.get("expert_summary") or meta.get("national_headline") or "No summary available"
            briefs.append(AgentBrief(agent=name, status="ok", headline=headline))
        return briefs

    # ------------------------------------------------------------------
    # Market conditions aggregation
    # ------------------------------------------------------------------
    @staticmethod
    def _norm(score: float | None, invert: bool = False) -> float | None:
        if score is None:
            return None
        s = float(score)
        if s > 1.0:
            s = s / 100.0
        s = max(0.0, min(1.0, s))
        return 1.0 - s if invert else s

    def _market_condition(
        self, results: dict[str, dict[str, Any] | None]
    ) -> tuple[float, str, list[str]]:
        weighted: list[tuple[float, float]] = []
        factors: list[str] = []

        markets = results.get("markets")
        if markets:
            m = markets.get("metrics", {})
            risk_on = m.get("risk_on_score")
            if risk_on is not None:
                weighted.append((risk_on, 3.0))
                factors.append(f"Markets risk-on {risk_on:.2f} ({m.get('trend_label')})")
            for key, w in (("breadth_score", 1.5), ("momentum_score", 1.5)):
                v = m.get(key)
                if v is not None:
                    weighted.append((v, w))

        ds = results.get("datascience")
        if ds:
            m = ds.get("metrics", {})
            stress = m.get("quant_stress_score")
            norm_stress = self._norm(stress, invert=True)
            if norm_stress is not None:
                weighted.append((norm_stress, 2.0))
                factors.append(f"Quant stress {stress:.2f} ({m.get('stress_label')})")
            opp = m.get("opportunity_score")
            if opp is not None:
                weighted.append((opp, 1.0))

        geo = results.get("geopolitics")
        if geo:
            m = geo.get("metrics", {})
            risk = m.get("global_risk_score")
            norm_risk = self._norm(risk, invert=True)
            if norm_risk is not None:
                weighted.append((norm_risk, 2.0))
                factors.append(f"Geopolitical risk {risk:.2f} ({m.get('risk_label')})")

        grid = results.get("grid")
        if grid:
            m = grid.get("metrics", {})
            s = self._norm(m.get("grid_stress_score"), invert=True)
            if s is not None:
                weighted.append((s, 1.0))
                factors.append(
                    f"Grid stress {m.get('grid_stress_score')} ({m.get('stress_label')})"
                )

        elec = results.get("electricity")
        if elec:
            m = elec.get("metrics", {})
            s = self._norm(m.get("grid_balance_score"), invert=True)
            if s is not None:
                weighted.append((s, 1.0))

        meteo = results.get("meteorology")
        if meteo:
            m = meteo.get("metrics", {})
            s = self._norm(m.get("disruption_score"), invert=True)
            if s is not None:
                weighted.append((s, 1.0))
                factors.append(
                    f"Weather disruption {m.get('disruption_score')} ({m.get('disruption_label')})"
                )

        logi = results.get("logistics")
        if logi:
            m = logi.get("metrics", {})
            s = self._norm(m.get("supply_chain_stress_score"), invert=True)
            if s is not None:
                weighted.append((s, 1.0))

        trans = results.get("transportation")
        if trans:
            m = trans.get("metrics", {})
            s = self._norm(m.get("infrastructure_stress_score"), invert=True)
            if s is not None:
                weighted.append((s, 1.0))

        pat = results.get("patents")
        if pat:
            s = self._norm(pat.get("summary", {}).get("innovation_score"))
            if s is not None:
                weighted.append((s, 0.5))

        ev = results.get("events")
        if ev:
            crit = ev.get("summary", {}).get("critical_count")
            if crit is not None:
                ev_score = max(0.0, 1.0 - crit * 0.15)
                weighted.append((ev_score, 1.0))
                if crit:
                    factors.append(f"{crit} critical world events tracked")

        if not weighted:
            return 0.5, "Neutral", factors

        total_w = sum(w for _, w in weighted)
        score = round(sum(s * w for s, w in weighted) / total_w, 4)
        label = "Risk-On" if score >= 0.60 else ("Risk-Off" if score <= 0.40 else "Neutral")
        return score, label, factors

    # ------------------------------------------------------------------
    # Top movers selection
    # ------------------------------------------------------------------
    @staticmethod
    def _select_top_movers(markets_result: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not markets_result:
            return []
        candidates: dict[str, dict[str, Any]] = {}
        for g in markets_result.get("top_gainers", []):
            if g.get("symbol"):
                candidates[g["symbol"]] = g
        for l in markets_result.get("top_losers", []):
            if l.get("symbol") and l["symbol"] not in candidates:
                candidates[l["symbol"]] = l
        ranked = sorted(
            candidates.values(),
            key=lambda q: abs(q.get("day_chg_pct") or 0.0),
            reverse=True,
        )
        return ranked[:MAX_MOVERS]

    # ------------------------------------------------------------------
    # Per-mover quantitative prediction
    # ------------------------------------------------------------------
    def _fetch_closes(self, symbol: str) -> list[float]:
        try:
            resp = requests.get(
                CHART_API.format(symbol=symbol),
                params={"interval": "1d", "range": "3mo"},
                headers=HEADERS,
                timeout=25,
            )
            if resp.status_code == 429:
                time.sleep(3)
                resp = requests.get(
                    CHART_API.format(symbol=symbol),
                    params={"interval": "1d", "range": "3mo"},
                    headers=HEADERS,
                    timeout=25,
                )
            resp.raise_for_status()
            closes = resp.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            return [float(c) for c in closes if c is not None]
        except Exception:
            return []

    @staticmethod
    def _log_returns(prices: list[float]) -> list[float]:
        return [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]

    @staticmethod
    def _volatility_ann(returns: list[float], window: int = 20) -> float:
        if len(returns) < window:
            return 0.0
        recent = returns[-window:]
        daily_std = statistics.stdev(recent) if len(recent) > 1 else 0.0
        return round(daily_std * math.sqrt(252) * 100, 2)

    @staticmethod
    def _z_score(prices: list[float], window: int = 20) -> float:
        if len(prices) < window:
            return 0.0
        recent = prices[-window:]
        mean = statistics.mean(recent)
        std = statistics.stdev(recent) if len(recent) > 1 else 1e-9
        return round((prices[-1] - mean) / std, 2)

    @staticmethod
    def _momentum_score(return_20d: float, vol: float) -> float:
        if vol <= 0:
            return 0.5
        sharpe_like = return_20d / vol
        return round(max(0.0, min(1.0, 0.5 + sharpe_like * 0.15)), 4)

    @staticmethod
    def _pct_return(prices: list[float], days: int) -> float:
        if len(prices) <= days:
            return 0.0
        return round(((prices[-1] - prices[-1 - days]) / prices[-1 - days]) * 100, 2)

    def _monte_carlo(
        self, returns: list[float], last_price: float, horizon_days: int, tilt: float
    ) -> HorizonPrediction:
        recent = returns[-60:]
        mu = statistics.mean(recent) + tilt
        sigma = statistics.stdev(recent) if len(recent) > 1 else 0.01
        ups = 0
        finals: list[float] = []
        for _ in range(MC_SIMULATIONS):
            price = last_price
            for _ in range(horizon_days):
                price *= math.exp(mu + sigma * random.gauss(0, 1))
            ret = (price - last_price) / last_price
            finals.append(ret)
            if ret > 0:
                ups += 1
        prob_up = round(ups / MC_SIMULATIONS, 4)
        finals.sort()
        median_ret = finals[len(finals) // 2]
        low_ret = finals[max(0, int(len(finals) * 0.10) - 1)]
        high_ret = finals[min(len(finals) - 1, int(len(finals) * 0.90))]
        label = "24h" if horizon_days == 1 else "1w"
        return HorizonPrediction(
            horizon=label,
            trading_days=horizon_days,
            direction="UP" if prob_up >= 0.5 else "DOWN",
            prob_up=prob_up,
            expected_return_pct=round(median_ret * 100, 2),
            low_return_pct=round(low_ret * 100, 2),
            high_return_pct=round(high_ret * 100, 2),
        )

    def _naive_prediction(
        self, day_chg_pct: float | None, macro_tilt: float, horizon_days: int
    ) -> HorizonPrediction:
        """Fallback prediction when insufficient price history is available."""
        base_drift = ((day_chg_pct or 0.0) / 100.0) * 0.25 + macro_tilt * MACRO_DRIFT_PER_DAY
        expected = base_drift * horizon_days
        spread = max(abs(expected) * 2, 0.01 * horizon_days)
        prob_up = round(max(0.35, min(0.65, 0.5 + expected * 5)), 4)
        label = "24h" if horizon_days == 1 else "1w"
        return HorizonPrediction(
            horizon=label,
            trading_days=horizon_days,
            direction="UP" if prob_up >= 0.5 else "DOWN",
            prob_up=prob_up,
            expected_return_pct=round(expected * 100, 2),
            low_return_pct=round((expected - spread) * 100, 2),
            high_return_pct=round((expected + spread) * 100, 2),
        )

    def _analyze_mover(self, quote: dict[str, Any], macro_tilt: float) -> MoverPrediction:
        symbol = quote.get("symbol", "")
        name = quote.get("name", symbol)
        day_chg_pct = quote.get("day_chg_pct")
        tilt = macro_tilt * MACRO_DRIFT_PER_DAY

        prices = self._fetch_closes(symbol)
        if len(prices) < 25:
            predictions = [
                self._naive_prediction(day_chg_pct, macro_tilt, days)
                for days in HORIZONS.values()
            ]
            return MoverPrediction(
                symbol=symbol,
                name=name,
                day_chg_pct=day_chg_pct,
                last_price=None,
                vol_20d_ann_pct=None,
                z_score_20d=None,
                momentum_score=None,
                data_quality="limited (insufficient history)",
                predictions=predictions,
            )

        returns = self._log_returns(prices)
        vol = self._volatility_ann(returns)
        z = self._z_score(prices)
        r20 = self._pct_return(prices, 20)
        momentum = self._momentum_score(r20, vol)
        predictions = [
            self._monte_carlo(returns, prices[-1], days, tilt) for days in HORIZONS.values()
        ]
        return MoverPrediction(
            symbol=symbol,
            name=name,
            day_chg_pct=day_chg_pct,
            last_price=round(prices[-1], 2),
            vol_20d_ann_pct=vol,
            z_score_20d=z,
            momentum_score=momentum,
            data_quality="full",
            predictions=predictions,
        )

    # ------------------------------------------------------------------
    # Signals, recommendations, summary
    # ------------------------------------------------------------------
    @staticmethod
    def _market_signals(
        movers: list[MoverPrediction], score: float, label: str
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        signals.append({
            "sector": "US Market Conditions",
            "tickers": [m.symbol for m in movers[:5]],
            "bias": "BULLISH" if score >= 0.60 else ("BEARISH" if score <= 0.40 else "NEUTRAL"),
            "reason": f"Consensus market condition score {score:.2f} ({label})",
        })
        bullish = [
            m for m in movers
            if m.predictions and m.predictions[-1].direction == "UP" and m.predictions[-1].prob_up >= 0.55
        ]
        if bullish:
            signals.append({
                "sector": "Top Movers — 1w Bullish",
                "tickers": [m.symbol for m in bullish[:5]],
                "bias": "BULLISH",
                "reason": "Monte Carlo 1-week P(up) >= 55% among top movers",
            })
        bearish = [
            m for m in movers
            if m.predictions and m.predictions[-1].direction == "DOWN" and m.predictions[-1].prob_up <= 0.45
        ]
        if bearish:
            signals.append({
                "sector": "Top Movers — 1w Bearish",
                "tickers": [m.symbol for m in bearish[:5]],
                "bias": "BEARISH",
                "reason": "Monte Carlo 1-week P(up) <= 45% among top movers",
            })
        return signals

    @staticmethod
    def _recommendations(
        movers: list[MoverPrediction], score: float, label: str, factors: list[str]
    ) -> list[str]:
        recs: list[str] = []
        recs.append(f"Overall US market conditions: {label} (consensus score {score:.2f}).")
        for f in factors[:6]:
            recs.append(f"Factor: {f}")
        for m in movers[:5]:
            if not m.predictions:
                continue
            h24, h1w = m.predictions[0], m.predictions[-1]
            recs.append(
                f"{m.symbol}: 24h {h24.direction} P(up)={h24.prob_up:.0%} "
                f"exp {h24.expected_return_pct:+.2f}% | "
                f"1w {h1w.direction} P(up)={h1w.prob_up:.0%} exp {h1w.expected_return_pct:+.2f}%"
            )
        return recs

    @staticmethod
    def _expert_summary(
        score: float, label: str, movers: list[MoverPrediction], agents_succeeded: int, agents_total: int
    ) -> str:
        top = movers[0] if movers else None
        top_line = (
            f"Top mover {top.symbol}: 1w {top.predictions[-1].direction} "
            f"P(up)={top.predictions[-1].prob_up:.0%}"
            if top and top.predictions
            else "no movers analyzed"
        )
        return (
            f"US market conditions: {label} (consensus score {score:.2f}) synthesized from "
            f"{agents_succeeded}/{agents_total} agents. {top_line}."
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def analyze(self) -> ConsensusReport:
        results = self._collect_agents()
        agents_succeeded = sum(1 for v in results.values() if v)
        briefs = self._agent_briefs(results)
        score, label, factors = self._market_condition(results)
        macro_tilt = round((score - 0.5) * 2, 4)

        top_quotes = self._select_top_movers(results.get("markets"))
        movers: list[MoverPrediction] = []
        for q in top_quotes:
            movers.append(self._analyze_mover(q, macro_tilt))
            time.sleep(self.delay_seconds)

        signals = self._market_signals(movers, score, label)
        recs = self._recommendations(movers, score, label, factors)
        summary = self._expert_summary(score, label, movers, agents_succeeded, len(self.AGENTS))

        return ConsensusReport(
            market_condition_score=score,
            market_condition_label=label,
            contributing_factors=factors,
            agent_briefs=briefs,
            movers=movers,
            market_signals=signals,
            recommendations=recs,
            expert_summary=summary,
            data_sources=sorted(self.AGENTS.keys()),
            agents_consulted=len(self.AGENTS),
            agents_succeeded=agents_succeeded,
        )

    def to_dict(self, report: ConsensusReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Cross-Agent Consensus Expert",
                "expert_summary": report.expert_summary,
                "data_sources": report.data_sources,
                "agents_consulted": report.agents_consulted,
                "agents_succeeded": report.agents_succeeded,
                "analyzed_at": report.analyzed_at,
            },
            "metrics": {
                "market_condition_score": report.market_condition_score,
                "market_condition_label": report.market_condition_label,
            },
            "contributing_factors": report.contributing_factors,
            "agent_briefs": [
                {"agent": b.agent, "status": b.status, "headline": b.headline}
                for b in report.agent_briefs
            ],
            "movers": [
                {
                    "symbol": m.symbol,
                    "name": m.name,
                    "day_chg_pct": m.day_chg_pct,
                    "last_price": m.last_price,
                    "vol_20d_ann_pct": m.vol_20d_ann_pct,
                    "z_score_20d": m.z_score_20d,
                    "momentum_score": m.momentum_score,
                    "data_quality": m.data_quality,
                    "predictions": [
                        {
                            "horizon": p.horizon,
                            "trading_days": p.trading_days,
                            "direction": p.direction,
                            "prob_up": p.prob_up,
                            "expected_return_pct": p.expected_return_pct,
                            "low_return_pct": p.low_return_pct,
                            "high_return_pct": p.high_return_pct,
                        }
                        for p in m.predictions
                    ],
                }
                for m in report.movers
            ],
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result


def run_consensus_analysis(output: Path | None = None) -> dict[str, Any]:
    return ConsensusExpert().run(output=output)
