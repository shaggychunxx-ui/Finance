"""
Cash Account Builder Expert Agent
=================================
Cash-account trading strategist analysis for scaling a sub-$25,000 account
toward the Pattern Day Trader (PDT) threshold: T+1 settlement capital
splitting, a phase-based compounding ladder, fractional-risk position
sizing, mega-cap options-suitability screening, and 15-minute
opening-range breakout signals.

Data: Yahoo Finance chart API (daily quotes + 15-minute intraday range).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Finance-Cash-Account-Builder/1.0 (shaggychunxx@gmail.com)"}

BENCHMARK = "SPY"
SETTLEMENT_DAYS = 1  # T+1 for equities, ETFs, and listed options
DEFAULT_ACCOUNT_BALANCE = 5_000.0
DEFAULT_RISK_PCT = 0.03  # 3% of the daily tranche risked per trade
PDT_THRESHOLD = 25_000.0
NY_TZ = ZoneInfo("America/New_York")

WATCHLIST = {
    "NVDA": "NVIDIA",
    "AAPL": "Apple",
    "AMD": "Advanced Micro Devices",
    "TSLA": "Tesla",
    "MSFT": "Microsoft",
}

MIN_OPTIONABLE_PRICE = 50.0
MIN_LIQUID_AVG_VOLUME = 5_000_000

PHASE_LADDER: list[dict[str, Any]] = [
    {
        "phase": "Phase 1 — The Foundation",
        "floor": 0.0,
        "ceiling": 5_000.0,
        "trades_per_day": 1,
        "risk_pct": 0.03,
        "focus": "Routine and survival",
        "execution": "1 trade per day using Tranche A or Tranche B",
        "rule": "Keep total losses under $50 per trade; prioritize clean executions over frequency",
    },
    {
        "phase": "Phase 2 — The Core Scale",
        "floor": 5_000.0,
        "ceiling": 15_000.0,
        "trades_per_day": 1,
        "risk_pct": 0.03,
        "focus": "Compounding dollar amounts",
        "execution": "Scale contract size on your single best setup as the daily tranche grows",
        "rule": "Do not add more trades per day; scale size, not frequency",
    },
    {
        "phase": "Phase 3 — The Velocity Push",
        "floor": 15_000.0,
        "ceiling": PDT_THRESHOLD,
        "trades_per_day": 2,
        "risk_pct": 0.03,
        "focus": "The final sprint",
        "execution": "Split the daily tranche into two trades (e.g. AM + PM) when two perfect setups occur",
        "rule": "The moment net cash crosses $25,001, stop trading for 48 hours and request a margin account conversion",
    },
]

BROKER_STRUCTURAL_CHECKLIST: list[dict[str, Any]] = [
    {
        "id": "cash_account_type",
        "name": "Confirm Cash Account Type",
        "description": (
            "Ensure the account is explicitly set to Cash, not 'Limited Margin' or "
            "'Instant Cash', which treats the account as margin and exposes it to PDT restrictions."
        ),
    },
    {
        "id": "disable_share_lending",
        "name": "Disable Fully Paid Lending",
        "description": (
            "Opt out of fully paid securities lending programs, which can occasionally "
            "lock up settlement timing on lent shares."
        ),
    },
    {
        "id": "options_settlement",
        "name": "Verify T+1 Options Settlement",
        "description": "Confirm the broker processes options settlement overnight so funds clear by the next session.",
    },
    {
        "id": "raw_data_feed",
        "name": "Raw Data & Execution Quality",
        "description": "Prefer brokers with raw order routing and real-time Level 1/2 data to minimize slippage on fast-moving contracts.",
    },
]


@dataclass
class SettlementTranche:
    total_balance: float
    tranche_a: float
    tranche_b: float
    max_daily_exposure: float
    settlement_days: int


@dataclass
class PhaseAssessment:
    phase: str
    floor: float
    ceiling: float
    daily_tranche: float
    max_risk_per_trade: float
    trades_per_day: int
    focus: str
    execution: str
    rule: str


@dataclass
class AssetSuitability:
    symbol: str
    name: str
    last_price: float | None
    avg_volume: float | None
    suitable: bool
    reason: str


@dataclass
class PositionSizingPlan:
    tranche_size: float
    risk_pct: float
    max_risk_dollars: float
    example_symbol: str
    example_premium: float
    example_stop: float
    example_risk_per_contract: float
    example_contracts: int
    example_capital_deployed: float


@dataclass
class OpeningRangeSignal:
    symbol: str
    or_high: float | None
    or_low: float | None
    last_price: float | None
    signal: str
    note: str


@dataclass
class CashAccountAssessment:
    settlement_signal: str
    phase_signal: str
    market_regime_signal: str
    screening_signal: str
    opening_range_signal: str
    conclusion: str
    structural_edge: str


@dataclass
class CashAccountReport:
    tranche: SettlementTranche
    phase: PhaseAssessment
    screened_assets: list[AssetSuitability]
    position_plan: PositionSizingPlan
    opening_range_signals: list[OpeningRangeSignal]
    assessment: CashAccountAssessment
    market_regime: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CashAccountBuilderExpert:
    """Cash-account strategist — T+1 settlement math and PDT-ladder compounding."""

    def __init__(
        self,
        delay_seconds: float = 0.3,
        account_balance: float = DEFAULT_ACCOUNT_BALANCE,
        risk_pct: float = DEFAULT_RISK_PCT,
    ) -> None:
        self.delay_seconds = delay_seconds
        self.account_balance = max(0.0, account_balance)
        self.risk_pct = risk_pct

    def _fetch_json(self, symbol: str, params: dict[str, str]) -> dict[str, Any] | None:
        try:
            resp = requests.get(
                CHART_API.format(symbol=symbol),
                params=params,
                headers=HEADERS,
                timeout=25,
            )
            if resp.status_code == 429:
                time.sleep(3)
                resp = requests.get(
                    CHART_API.format(symbol=symbol),
                    params=params,
                    headers=HEADERS,
                    timeout=25,
                )
            resp.raise_for_status()
            result = resp.json()["chart"]["result"]
            if not result:
                return None
            return result[0]
        except Exception:
            return None

    def _fetch_daily_series(self, symbol: str) -> dict[str, list[float]]:
        result = self._fetch_json(symbol, {"interval": "1d", "range": "1mo"})
        if not result:
            return {"closes": [], "volumes": []}
        quote = result.get("indicators", {}).get("quote", [{}])[0]
        closes = [float(c) for c in quote.get("close", []) if c is not None]
        volumes = [float(v) for v in quote.get("volume", []) if v is not None]
        return {"closes": closes, "volumes": volumes}

    def _fetch_opening_range(self, symbol: str) -> OpeningRangeSignal:
        result = self._fetch_json(symbol, {"interval": "15m", "range": "1d"})
        if not result:
            return OpeningRangeSignal(
                symbol=symbol,
                or_high=None,
                or_low=None,
                last_price=None,
                signal="no_data",
                note="Intraday 15-minute data unavailable",
            )

        timestamps = result.get("timestamp") or []
        quote = result.get("indicators", {}).get("quote", [{}])[0]
        highs = quote.get("high", [])
        lows = quote.get("low", [])
        closes = quote.get("close", [])
        volumes = quote.get("volume", [])

        if not timestamps or not highs or not closes:
            return OpeningRangeSignal(
                symbol=symbol,
                or_high=None,
                or_low=None,
                last_price=None,
                signal="no_data",
                note="Intraday 15-minute data unavailable",
            )

        # First bar of the trading day is the 9:30-9:45 ET opening range.
        first_day = datetime.fromtimestamp(timestamps[0], tz=NY_TZ).date()
        or_bars = [
            i
            for i, ts in enumerate(timestamps)
            if datetime.fromtimestamp(ts, tz=NY_TZ).date() == first_day
        ]
        if not or_bars:
            return OpeningRangeSignal(
                symbol=symbol,
                or_high=None,
                or_low=None,
                last_price=None,
                signal="no_data",
                note="Could not isolate the opening 15-minute candle",
            )

        or_idx = or_bars[0]
        or_high = highs[or_idx]
        or_low = lows[or_idx]
        if or_high is None or or_low is None:
            return OpeningRangeSignal(
                symbol=symbol,
                or_high=None,
                or_low=None,
                last_price=None,
                signal="no_data",
                note="Opening candle high/low missing",
            )

        last_price = next((c for c in reversed(closes) if c is not None), None)
        or_volume = volumes[or_idx] if or_idx < len(volumes) and volumes[or_idx] else 0
        latest_volume = next((v for v in reversed(volumes) if v), 0)
        volume_confirmed = bool(latest_volume and or_volume and latest_volume > or_volume)

        if last_price is None:
            signal = "no_data"
            note = "No completed price bar yet"
        elif last_price > or_high:
            signal = "breakout_long" if volume_confirmed else "breakout_long_unconfirmed"
            note = f"Price {last_price:.2f} broke above the opening range high {or_high:.2f}"
        elif last_price < or_low:
            signal = "breakout_short" if volume_confirmed else "breakout_short_unconfirmed"
            note = f"Price {last_price:.2f} broke below the opening range low {or_low:.2f}"
        else:
            signal = "inside_range"
            note = f"Price {last_price:.2f} is still between {or_low:.2f} and {or_high:.2f} — wait"

        return OpeningRangeSignal(
            symbol=symbol,
            or_high=round(or_high, 2),
            or_low=round(or_low, 2),
            last_price=round(last_price, 2) if last_price is not None else None,
            signal=signal,
            note=note,
        )

    @staticmethod
    def _settlement_tranche(balance: float) -> SettlementTranche:
        half = balance / 2.0
        return SettlementTranche(
            total_balance=round(balance, 2),
            tranche_a=round(half, 2),
            tranche_b=round(half, 2),
            max_daily_exposure=round(half, 2),
            settlement_days=SETTLEMENT_DAYS,
        )

    @staticmethod
    def _phase_for_balance(balance: float, tranche_size: float) -> PhaseAssessment:
        if balance >= PDT_THRESHOLD:
            return PhaseAssessment(
                phase="PDT Threshold Reached",
                floor=PDT_THRESHOLD,
                ceiling=float("inf"),
                daily_tranche=tranche_size,
                max_risk_per_trade=round(tranche_size * DEFAULT_RISK_PCT, 2),
                trades_per_day=0,
                focus="Transition to margin",
                execution="Stop trading for 48 hours and request conversion to a margin account",
                rule="Once approved, PDT restrictions drop and 4x intraday buying power unlocks",
            )
        for stage in PHASE_LADDER:
            if stage["floor"] <= balance < stage["ceiling"]:
                return PhaseAssessment(
                    phase=stage["phase"],
                    floor=stage["floor"],
                    ceiling=stage["ceiling"],
                    daily_tranche=round(tranche_size, 2),
                    max_risk_per_trade=round(tranche_size * stage["risk_pct"], 2),
                    trades_per_day=stage["trades_per_day"],
                    focus=stage["focus"],
                    execution=stage["execution"],
                    rule=stage["rule"],
                )
        stage = PHASE_LADDER[-1]
        return PhaseAssessment(
            phase=stage["phase"],
            floor=stage["floor"],
            ceiling=stage["ceiling"],
            daily_tranche=round(tranche_size, 2),
            max_risk_per_trade=round(tranche_size * stage["risk_pct"], 2),
            trades_per_day=stage["trades_per_day"],
            focus=stage["focus"],
            execution=stage["execution"],
            rule=stage["rule"],
        )

    def _screen_asset(self, symbol: str, name: str) -> AssetSuitability:
        series = self._fetch_daily_series(symbol)
        closes = series["closes"]
        volumes = series["volumes"]
        if not closes:
            return AssetSuitability(
                symbol=symbol,
                name=name,
                last_price=None,
                avg_volume=None,
                suitable=False,
                reason="No price data available",
            )
        last_price = closes[-1]
        avg_volume = sum(volumes) / len(volumes) if volumes else 0.0
        price_ok = last_price >= MIN_OPTIONABLE_PRICE
        liquidity_ok = avg_volume >= MIN_LIQUID_AVG_VOLUME
        suitable = price_ok and liquidity_ok
        if suitable:
            reason = f"${last_price:.2f} with {avg_volume:,.0f} avg volume — liquid enough for tight option spreads"
        elif not price_ok:
            reason = f"${last_price:.2f} is below the ${MIN_OPTIONABLE_PRICE:.0f} threshold for capital-efficient leverage"
        else:
            reason = f"Average volume {avg_volume:,.0f} is below the {MIN_LIQUID_AVG_VOLUME:,.0f} liquidity floor"
        return AssetSuitability(
            symbol=symbol,
            name=name,
            last_price=round(last_price, 2),
            avg_volume=round(avg_volume, 0),
            suitable=suitable,
            reason=reason,
        )

    @staticmethod
    def _position_sizing(tranche: SettlementTranche, risk_pct: float, screened: list[AssetSuitability]) -> PositionSizingPlan:
        max_risk_dollars = round(tranche.max_daily_exposure * risk_pct, 2)
        example = next((a for a in screened if a.suitable and a.last_price), None)
        if example and example.last_price:
            example_premium = round(example.last_price * 0.03, 2) or 1.0
        else:
            example_premium = 3.0
        example_stop = round(example_premium * 0.75, 2)
        risk_per_contract = round((example_premium - example_stop) * 100, 2)
        contracts = int(max_risk_dollars // risk_per_contract) if risk_per_contract > 0 else 0
        contracts = max(contracts, 1) if max_risk_dollars > 0 else 0
        capital_deployed = round(contracts * example_premium * 100, 2)
        return PositionSizingPlan(
            tranche_size=tranche.max_daily_exposure,
            risk_pct=risk_pct,
            max_risk_dollars=max_risk_dollars,
            example_symbol=example.symbol if example else BENCHMARK,
            example_premium=example_premium,
            example_stop=example_stop,
            example_risk_per_contract=risk_per_contract,
            example_contracts=contracts,
            example_capital_deployed=capital_deployed,
        )

    @staticmethod
    def _market_regime(spy_closes: list[float]) -> str:
        if len(spy_closes) < 21:
            return "insufficient_data"
        sma20 = sum(spy_closes[-20:]) / 20.0
        last = spy_closes[-1]
        day_change = (spy_closes[-1] - spy_closes[-2]) / spy_closes[-2] if len(spy_closes) >= 2 else 0.0
        if last > sma20 and day_change >= 0:
            return "risk_on"
        if last < sma20 and day_change <= 0:
            return "risk_off"
        return "choppy"

    def _assessment(
        self,
        tranche: SettlementTranche,
        phase: PhaseAssessment,
        market_regime: str,
        screened: list[AssetSuitability],
        or_signals: list[OpeningRangeSignal],
    ) -> CashAccountAssessment:
        settlement_signal = (
            f"Rotate Tranche A/B of ${tranche.max_daily_exposure:,.2f} on a T+{tranche.settlement_days} cycle"
        )
        phase_signal = f"{phase.phase}: max risk/trade ${phase.max_risk_per_trade:,.2f}, {phase.trades_per_day} trade(s)/day"
        suitable_count = sum(1 for a in screened if a.suitable)
        screening_signal = f"{suitable_count}/{len(screened)} watchlist tickers suitable for options leverage"
        breakouts = [s for s in or_signals if s.signal.startswith("breakout")]
        opening_range_signal = (
            f"{len(breakouts)} opening-range breakout(s) detected" if breakouts else "No confirmed opening-range breakouts yet"
        )
        if market_regime == "risk_on":
            conclusion = "Market regime favors long-call breakout setups; hold discipline on tranche rotation"
        elif market_regime == "risk_off":
            conclusion = "Market regime favors put breakout setups; reduce size and respect the 3% risk cap"
        elif market_regime == "choppy":
            conclusion = "Choppy regime — wait for confirmed 15-minute breakout volume before committing a tranche"
        else:
            conclusion = "Insufficient benchmark data to score market regime — trade the plan mechanically"
        structural_edge = (
            "Capital-splitting turns T+1 settlement from a constraint into a repeatable daily rotation, "
            "while fixed fractional risk keeps a losing streak from breaching the next tranche."
        )
        return CashAccountAssessment(
            settlement_signal=settlement_signal,
            phase_signal=phase_signal,
            market_regime_signal=f"SPY regime: {market_regime}",
            screening_signal=screening_signal,
            opening_range_signal=opening_range_signal,
            conclusion=conclusion,
            structural_edge=structural_edge,
        )

    @staticmethod
    def _market_signals(
        phase: PhaseAssessment,
        screened: list[AssetSuitability],
        or_signals: list[OpeningRangeSignal],
        market_regime: str,
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        bias = "BULLISH" if market_regime == "risk_on" else "BEARISH" if market_regime == "risk_off" else "NEUTRAL"
        signals.append({
            "sector": "Cash Account / PDT Ladder",
            "tickers": [a.symbol for a in screened if a.suitable],
            "bias": bias,
            "reason": f"{phase.phase} — daily tranche ${phase.daily_tranche:,.2f}, SPY regime {market_regime}",
        })
        for s in or_signals:
            if s.signal.startswith("breakout"):
                signals.append({
                    "sector": "Opening Range Breakout",
                    "tickers": [s.symbol],
                    "bias": "BULLISH" if "long" in s.signal else "BEARISH",
                    "reason": s.note,
                })
        return signals

    @staticmethod
    def _recommendations(
        tranche: SettlementTranche,
        phase: PhaseAssessment,
        screened: list[AssetSuitability],
    ) -> list[str]:
        recs = [
            f"Deploy at most ${tranche.max_daily_exposure:,.2f} (half your ${tranche.total_balance:,.2f} balance) "
            "per day, rotating Tranche A and Tranche B so settled cash is always available.",
            f"Cap risk per trade at ${phase.max_risk_per_trade:,.2f} ({phase.rule}).",
            "Buy long calls/puts only — never sell naked options in a cash account with limited settled funds.",
            "Wait for the 9:30-9:45 AM ET opening range to form before taking any trade.",
        ]
        suitable = [a.symbol for a in screened if a.suitable]
        if suitable:
            recs.append(f"Focus the watchlist on: {', '.join(suitable)} — liquid enough to keep option spreads tight.")
        if phase.phase.startswith("PDT"):
            recs.append("Halt trading for 48 hours and submit the cash-to-margin conversion request to your broker.")
        for item in BROKER_STRUCTURAL_CHECKLIST:
            recs.append(f"{item['name']}: {item['description']}")
        return recs

    def analyze(self) -> CashAccountReport:
        spy_series = self._fetch_daily_series(BENCHMARK)
        if not spy_series["closes"]:
            raise RuntimeError("Unable to fetch SPY data for cash account builder analysis")
        market_regime = self._market_regime(spy_series["closes"])

        tranche = self._settlement_tranche(self.account_balance)
        phase = self._phase_for_balance(self.account_balance, tranche.max_daily_exposure)

        screened: list[AssetSuitability] = []
        for symbol, name in WATCHLIST.items():
            screened.append(self._screen_asset(symbol, name))
            time.sleep(self.delay_seconds)

        position_plan = self._position_sizing(tranche, self.risk_pct, screened)

        or_signals: list[OpeningRangeSignal] = []
        for symbol in WATCHLIST:
            or_signals.append(self._fetch_opening_range(symbol))
            time.sleep(self.delay_seconds)

        assessment = self._assessment(tranche, phase, market_regime, screened, or_signals)
        signals = self._market_signals(phase, screened, or_signals, market_regime)
        recommendations = self._recommendations(tranche, phase, screened)

        expert_summary = (
            f"${tranche.total_balance:,.2f} balance → {phase.phase} → daily tranche "
            f"${tranche.max_daily_exposure:,.2f} (T+{tranche.settlement_days} rotation), "
            f"max risk/trade ${phase.max_risk_per_trade:,.2f}. {assessment.conclusion}"
        )

        return CashAccountReport(
            tranche=tranche,
            phase=phase,
            screened_assets=screened,
            position_plan=position_plan,
            opening_range_signals=or_signals,
            assessment=assessment,
            market_regime=market_regime,
            expert_summary=expert_summary,
            market_signals=signals,
            recommendations=recommendations,
            data_source="Yahoo Finance chart API (daily + 15-minute intraday)",
        )

    @staticmethod
    def to_dict(report: CashAccountReport) -> dict[str, Any]:
        t = report.tranche
        p = report.phase
        pp = report.position_plan
        a = report.assessment
        return {
            "meta": {
                "agent": "Cash Account Builder Expert",
                "data_source": report.data_source,
                "settlement_days": t.settlement_days,
                "expert_summary": report.expert_summary,
                "analyzed_at": report.analyzed_at,
            },
            "settlement_tranche": {
                "total_balance": t.total_balance,
                "tranche_a": t.tranche_a,
                "tranche_b": t.tranche_b,
                "max_daily_exposure": t.max_daily_exposure,
                "settlement_days": t.settlement_days,
            },
            "phase": {
                "phase": p.phase,
                "floor": p.floor,
                "ceiling": p.ceiling,
                "daily_tranche": p.daily_tranche,
                "max_risk_per_trade": p.max_risk_per_trade,
                "trades_per_day": p.trades_per_day,
                "focus": p.focus,
                "execution": p.execution,
                "rule": p.rule,
            },
            "screened_assets": [
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "last_price": s.last_price,
                    "avg_volume": s.avg_volume,
                    "suitable": s.suitable,
                    "reason": s.reason,
                }
                for s in report.screened_assets
            ],
            "position_sizing_plan": {
                "tranche_size": pp.tranche_size,
                "risk_pct": pp.risk_pct,
                "max_risk_dollars": pp.max_risk_dollars,
                "example_symbol": pp.example_symbol,
                "example_premium": pp.example_premium,
                "example_stop": pp.example_stop,
                "example_risk_per_contract": pp.example_risk_per_contract,
                "example_contracts": pp.example_contracts,
                "example_capital_deployed": pp.example_capital_deployed,
            },
            "opening_range_signals": [
                {
                    "symbol": o.symbol,
                    "or_high": o.or_high,
                    "or_low": o.or_low,
                    "last_price": o.last_price,
                    "signal": o.signal,
                    "note": o.note,
                }
                for o in report.opening_range_signals
            ],
            "assessment": {
                "settlement_signal": a.settlement_signal,
                "phase_signal": a.phase_signal,
                "market_regime_signal": a.market_regime_signal,
                "screening_signal": a.screening_signal,
                "opening_range_signal": a.opening_range_signal,
                "conclusion": a.conclusion,
                "structural_edge": a.structural_edge,
            },
            "market_regime": report.market_regime,
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "cash_account_playbook.json"
            catalog.write_text(
                json.dumps(
                    {"phase_ladder": PHASE_LADDER, "broker_structural_checklist": BROKER_STRUCTURAL_CHECKLIST},
                    indent=2,
                ),
                encoding="utf-8",
            )
        return result


def run_cash_account_builder_analysis(
    output: Path | None = None,
    account_balance: float = DEFAULT_ACCOUNT_BALANCE,
    risk_pct: float = DEFAULT_RISK_PCT,
) -> dict[str, Any]:
    return CashAccountBuilderExpert(account_balance=account_balance, risk_pct=risk_pct).run(output=output)
