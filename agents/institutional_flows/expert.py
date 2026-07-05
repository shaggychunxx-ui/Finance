"""
Institutional & Mechanical Flows Tracker Agent
===============================================
Tracks the mechanical, formula-driven flows that move markets independent of
fundamentals: leveraged ETF end-of-day rebalancing, pension fund quarter-end
asset-allocation drift, passive index reconstitution calendars, and
systematic macro / volatility-target trigger levels.

Data: Yahoo Finance chart API (public, unauthenticated).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests

CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Finance-Institutional-Flows/1.0 (shaggychunxx@gmail.com)"}

# Illustrative AUM figures (USD) for the largest daily-reset leveraged ETFs.
# These are periodically refreshed estimates, not live fund data.
LEVERAGED_ETFS: list[dict[str, Any]] = [
    {"symbol": "TQQQ", "name": "ProShares UltraPro QQQ (3x Nasdaq 100 Bull)",
     "underlying": "^IXIC", "leverage": 3, "aum_usd": 22_000_000_000},
    {"symbol": "SQQQ", "name": "ProShares UltraPro Short QQQ (3x Nasdaq 100 Bear)",
     "underlying": "^IXIC", "leverage": -3, "aum_usd": 6_000_000_000},
    {"symbol": "SPXL", "name": "Direxion Daily S&P 500 Bull 3x",
     "underlying": "^GSPC", "leverage": 3, "aum_usd": 4_000_000_000},
    {"symbol": "SPXS", "name": "Direxion Daily S&P 500 Bear 3x",
     "underlying": "^GSPC", "leverage": -3, "aum_usd": 1_500_000_000},
    {"symbol": "SSO", "name": "ProShares Ultra S&P 500 (2x Bull)",
     "underlying": "^GSPC", "leverage": 2, "aum_usd": 5_000_000_000},
    {"symbol": "SDS", "name": "ProShares UltraShort S&P 500 (2x Bear)",
     "underlying": "^GSPC", "leverage": -2, "aum_usd": 1_000_000_000},
]

# Pension / balanced-fund proxy assumptions for the quarter-end drift model.
PENSION_TARGET_EQUITY_WEIGHT = 0.60
PENSION_TARGET_BOND_WEIGHT = 0.40
PENSION_DRIFT_TOLERANCE_PCT = 0.25  # percentage-point band before a formal rebalance triggers
PENSION_PROXY_TOTAL_AUM_USD = 9_000_000_000_000  # US DB pensions + balanced funds (illustrative)
EQUITY_PROXY = "SPY"
BOND_PROXY = "AGG"

VIX_SYMBOL = "^VIX"
BROAD_INDEX = "^GSPC"

VIX_FLOOR = 12.0
VIX_CEILINGS = [15.0, 20.0, 25.0]
SMA_WINDOWS = (50, 100, 200)


@dataclass
class LeveragedETFFlow:
    symbol: str
    name: str
    leverage: int
    aum_usd: float
    underlying_daily_return_pct: float
    rebalance_flow_usd: float
    direction: str  # "BUY" or "SELL"


@dataclass
class PensionDriftEstimate:
    equity_total_return_pct: float
    bond_total_return_pct: float
    baseline_equity_weight: float
    current_equity_weight_pct: float
    drift_pct: float
    rebalance_amount_usd: float
    action: str  # "SELL EQUITIES / BUY BONDS", "SELL BONDS / BUY EQUITIES", or "NO ACTION"
    quarter_start: str


@dataclass
class ReconstitutionEvent:
    name: str
    event_date: str
    days_until: int
    description: str


@dataclass
class SystematicTrigger:
    indicator: str
    level: float | None
    status: str
    note: str


@dataclass
class InstitutionalFlowsReport:
    leveraged_etf_flows: list[LeveragedETFFlow]
    pension_drift: PensionDriftEstimate | None
    reconstitution_calendar: list[ReconstitutionEvent]
    systematic_triggers: list[SystematicTrigger]
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class InstitutionalFlowsExpert:
    """Tracks mechanical ETF, pension, index-reconstitution, and CTA/vol-target flows."""

    def _fetch_history(self, symbol: str, rng: str = "1y") -> dict[str, Any] | None:
        try:
            resp = requests.get(
                CHART_API.format(symbol=symbol),
                params={"interval": "1d", "range": rng},
                headers=HEADERS,
                timeout=25,
            )
            if resp.status_code == 429:
                time.sleep(3)
                resp = requests.get(
                    CHART_API.format(symbol=symbol),
                    params={"interval": "1d", "range": rng},
                    headers=HEADERS,
                    timeout=25,
                )
            resp.raise_for_status()
            result = resp.json()["chart"]["result"][0]
            meta = result["meta"]
            timestamps = result.get("timestamp", []) or []
            closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", []) or []
            series = [
                (ts, float(c))
                for ts, c in zip(timestamps, closes)
                if c is not None
            ]
            if not series:
                return None
            return {"meta": meta, "series": series}
        except Exception:
            return None

    @staticmethod
    def _daily_return_pct(series: list[tuple[int, float]]) -> float | None:
        if len(series) < 2:
            return None
        prev, last = series[-2][1], series[-1][1]
        if prev == 0:
            return None
        return round(((last - prev) / prev) * 100, 4)

    @staticmethod
    def _sma(series: list[tuple[int, float]], window: int) -> float | None:
        closes = [c for _, c in series]
        if len(closes) < window:
            return None
        return round(sum(closes[-window:]) / window, 2)

    def calculate_leveraged_etf_flow(
        self, symbol: str, name: str, leverage: int, aum_usd: float, underlying_daily_return_pct: float,
    ) -> LeveragedETFFlow:
        """Rebalance Flow = AUM x L x (L - 1) x Daily Return of Underlying Index.

        Note: for inverse funds (negative L), L*(L-1) is positive (e.g. -3 * -4 = 12),
        which correctly reflects daily-reset mechanics — inverse ETFs must cover part of
        their short notional when the index rises (and add to it when the index falls),
        so both bull and bear leveraged ETFs trade procyclically in the same direction.
        """
        l = leverage
        daily_return = underlying_daily_return_pct / 100.0
        flow_usd = aum_usd * l * (l - 1) * daily_return
        direction = "BUY" if flow_usd > 0 else "SELL" if flow_usd < 0 else "NONE"
        return LeveragedETFFlow(
            symbol=symbol,
            name=name,
            leverage=leverage,
            aum_usd=aum_usd,
            underlying_daily_return_pct=underlying_daily_return_pct,
            rebalance_flow_usd=round(abs(flow_usd), 2),
            direction=direction,
        )

    def _track_leveraged_etfs(self, underlying_returns: dict[str, float]) -> list[LeveragedETFFlow]:
        flows: list[LeveragedETFFlow] = []
        for spec in LEVERAGED_ETFS:
            daily_return = underlying_returns.get(spec["underlying"])
            if daily_return is None:
                continue
            flows.append(
                self.calculate_leveraged_etf_flow(
                    symbol=spec["symbol"],
                    name=spec["name"],
                    leverage=spec["leverage"],
                    aum_usd=spec["aum_usd"],
                    underlying_daily_return_pct=daily_return,
                )
            )
        return flows

    @staticmethod
    def _quarter_start(today: date) -> date:
        quarter_start_month = ((today.month - 1) // 3) * 3 + 1
        return date(today.year, quarter_start_month, 1)

    def calculate_pension_drift(
        self, equity_return_pct: float, bond_return_pct: float, total_aum_usd: float = PENSION_PROXY_TOTAL_AUM_USD,
    ) -> PensionDriftEstimate:
        """New Equity Weight = (0.60*(1+Re)) / (0.60*(1+Re) + 0.40*(1+Rb))."""
        re = equity_return_pct / 100.0
        rb = bond_return_pct / 100.0
        equity_component = PENSION_TARGET_EQUITY_WEIGHT * (1 + re)
        bond_component = PENSION_TARGET_BOND_WEIGHT * (1 + rb)
        denom = equity_component + bond_component
        new_weight = equity_component / denom if denom else PENSION_TARGET_EQUITY_WEIGHT
        drift_pct = round((new_weight - PENSION_TARGET_EQUITY_WEIGHT) * 100, 2)
        rebalance_amount = round(abs(drift_pct) / 100.0 * total_aum_usd, 2)
        # Pensions typically tolerate a small drift band before triggering a
        # formal rebalance back to the target allocation.
        if drift_pct > PENSION_DRIFT_TOLERANCE_PCT:
            action = "SELL EQUITIES / BUY BONDS"
        elif drift_pct < -PENSION_DRIFT_TOLERANCE_PCT:
            action = "SELL BONDS / BUY EQUITIES"
        else:
            action = "NO ACTION"
        return PensionDriftEstimate(
            equity_total_return_pct=round(equity_return_pct, 2),
            bond_total_return_pct=round(bond_return_pct, 2),
            baseline_equity_weight=PENSION_TARGET_EQUITY_WEIGHT,
            current_equity_weight_pct=round(new_weight * 100, 2),
            drift_pct=drift_pct,
            rebalance_amount_usd=rebalance_amount,
            action=action,
            quarter_start=self._quarter_start(datetime.now(timezone.utc).date()).isoformat(),
        )

    def _pension_drift_from_history(self) -> PensionDriftEstimate | None:
        equity_hist = self._fetch_history(EQUITY_PROXY, rng="6mo")
        bond_hist = self._fetch_history(BOND_PROXY, rng="6mo")
        if not equity_hist or not bond_hist:
            return None

        qstart = self._quarter_start(datetime.now(timezone.utc).date())
        qstart_ts = int(datetime(qstart.year, qstart.month, qstart.day, tzinfo=timezone.utc).timestamp())

        def total_return_since(series: list[tuple[int, float]]) -> float | None:
            baseline = next((c for ts, c in series if ts >= qstart_ts), None)
            if baseline is None or not series:
                return None
            last = series[-1][1]
            if baseline == 0:
                return None
            return ((last - baseline) / baseline) * 100

        re = total_return_since(equity_hist["series"])
        rb = total_return_since(bond_hist["series"])
        if re is None or rb is None:
            return None
        return self.calculate_pension_drift(re, rb)

    @staticmethod
    def _third_friday(year: int, month: int) -> date:
        d = date(year, month, 1)
        weekday = d.weekday()  # Monday=0 ... Friday=4
        first_friday = 1 + ((4 - weekday) % 7)
        return date(year, month, first_friday + 14)

    @staticmethod
    def _fourth_friday(year: int, month: int) -> date:
        d = date(year, month, 1)
        weekday = d.weekday()
        first_friday = 1 + ((4 - weekday) % 7)
        return date(year, month, first_friday + 21)

    def _reconstitution_calendar(self) -> list[ReconstitutionEvent]:
        today = datetime.now(timezone.utc).date()
        events: list[ReconstitutionEvent] = []

        for month in (3, 6, 9, 12):
            sp_date = self._third_friday(today.year, month)
            if sp_date < today:
                sp_date = self._third_friday(today.year + 1, month)
            events.append(
                ReconstitutionEvent(
                    name=f"S&P 500 Quarterly Rebalance ({sp_date.strftime('%B')})",
                    event_date=sp_date.isoformat(),
                    days_until=(sp_date - today).days,
                    description="S&P Dow Jones Indices rebalances constituents at the close.",
                )
            )

        russell_date = self._fourth_friday(today.year, 6)
        if russell_date < today:
            russell_date = self._fourth_friday(today.year + 1, 6)
        events.append(
            ReconstitutionEvent(
                name="FTSE Russell Annual Reconstitution",
                event_date=russell_date.isoformat(),
                days_until=(russell_date - today).days,
                description="Largest single passive-flow liquidity event of the year; executes at the closing bell.",
            )
        )

        # Rollover logic above guarantees every event is today or in the future,
        # so a plain ascending sort by days_until is sufficient.
        events.sort(key=lambda e: e.days_until)
        return events

    def _systematic_triggers(self) -> tuple[list[SystematicTrigger], list[str]]:
        triggers: list[SystematicTrigger] = []
        sources: list[str] = []

        vix_hist = self._fetch_history(VIX_SYMBOL, rng="1mo")
        if vix_hist:
            sources.append("Yahoo Finance (^VIX)")
            vix_level = vix_hist["meta"].get("regularMarketPrice")
            if vix_level is not None:
                vix_level = round(float(vix_level), 2)
                if vix_level < VIX_FLOOR:
                    status = "BELOW FLOOR"
                    note = f"VIX {vix_level} is below the {VIX_FLOOR} floor — vol-target funds likely at max equity exposure."
                elif vix_level >= VIX_CEILINGS[-1]:
                    status = "ABOVE CEILING"
                    note = f"VIX {vix_level} is at/above {VIX_CEILINGS[-1]} — mechanical, cascading sell programs likely triggered."
                elif any(vix_level >= c for c in VIX_CEILINGS):
                    crossed = max(c for c in VIX_CEILINGS if vix_level >= c)
                    status = "CEILING CROSSED"
                    note = f"VIX {vix_level} has crossed the {crossed} trigger level — automated de-risking likely underway."
                else:
                    status = "NEUTRAL"
                    note = f"VIX {vix_level} is between the {VIX_FLOOR} floor and {VIX_CEILINGS[0]} first ceiling."
                triggers.append(SystematicTrigger(indicator="VIX", level=vix_level, status=status, note=note))

        index_hist = self._fetch_history(BROAD_INDEX, rng="1y")
        if index_hist:
            sources.append("Yahoo Finance (^GSPC)")
            series = index_hist["series"]
            price = index_hist["meta"].get("regularMarketPrice")
            price = round(float(price), 2) if price is not None else (series[-1][1] if series else None)
            for window in SMA_WINDOWS:
                sma = self._sma(series, window)
                if sma is None or price is None:
                    continue
                if price < sma:
                    status = "BELOW SMA"
                    note = f"S&P 500 {price} is below its {window}-day SMA ({sma}) — mechanical CTA sell trigger."
                else:
                    status = "ABOVE SMA"
                    note = f"S&P 500 {price} is above its {window}-day SMA ({sma}) — trend-following buy bias."
                triggers.append(
                    SystematicTrigger(indicator=f"{window}-day SMA", level=sma, status=status, note=note)
                )

        return triggers, sources

    def analyze(self) -> InstitutionalFlowsReport:
        sources: list[str] = []
        underlying_returns: dict[str, float] = {}

        for underlying in {spec["underlying"] for spec in LEVERAGED_ETFS}:
            hist = self._fetch_history(underlying, rng="1mo")
            if hist is None:
                continue
            sources.append(f"Yahoo Finance ({underlying})")
            ret = self._daily_return_pct(hist["series"])
            if ret is not None:
                underlying_returns[underlying] = ret

        if not underlying_returns:
            raise RuntimeError("Unable to fetch index data for institutional flows analysis")

        leveraged_flows = self._track_leveraged_etfs(underlying_returns)

        pension_drift = self._pension_drift_from_history()
        if pension_drift is not None:
            sources.append(f"Yahoo Finance ({EQUITY_PROXY}, {BOND_PROXY})")

        recon_calendar = self._reconstitution_calendar()
        triggers, trigger_sources = self._systematic_triggers()
        sources.extend(trigger_sources)

        dedup_sources = list(dict.fromkeys(sources))

        total_buy = sum(f.rebalance_flow_usd for f in leveraged_flows if f.direction == "BUY")
        total_sell = sum(f.rebalance_flow_usd for f in leveraged_flows if f.direction == "SELL")
        net_leveraged_flow = total_buy - total_sell

        summary_parts = [
            f"Leveraged ETF EOD rebalance: ~${net_leveraged_flow / 1e9:.2f}B net "
            f"({'BUY' if net_leveraged_flow >= 0 else 'SELL'}) across {len(leveraged_flows)} funds."
        ]
        if pension_drift:
            summary_parts.append(
                f"Pension drift: {pension_drift.drift_pct:+.2f}pp vs 60/40 target "
                f"({pension_drift.action}, ~${pension_drift.rebalance_amount_usd / 1e9:.1f}B)."
            )
        upcoming = recon_calendar[0] if recon_calendar else None
        if upcoming:
            summary_parts.append(f"Next reconstitution: {upcoming.name} in {upcoming.days_until} days.")
        trigger_hits = [t for t in triggers if t.status not in ("NEUTRAL",)]
        if trigger_hits:
            summary_parts.append(f"{len(trigger_hits)} systematic trigger(s) active.")
        summary = " ".join(summary_parts)

        signals: list[dict[str, Any]] = []
        if abs(net_leveraged_flow) > 0:
            top = sorted(leveraged_flows, key=lambda f: -f.rebalance_flow_usd)[:3]
            signals.append({
                "sector": "Leveraged ETF Rebalancing",
                "tickers": [f.symbol for f in top],
                "bias": "BULLISH" if net_leveraged_flow > 0 else "BEARISH",
                "reason": f"EOD mechanical flow ~${abs(net_leveraged_flow) / 1e9:.2f}B "
                          f"{'buying' if net_leveraged_flow > 0 else 'selling'} into the close.",
            })
        if pension_drift and pension_drift.action != "NO ACTION":
            signals.append({
                "sector": "Pension Rebalancing",
                "tickers": ["SPY", "AGG", "TLT"],
                "bias": "BEARISH" if "SELL EQUITIES" in pension_drift.action else "BULLISH",
                "reason": f"{pension_drift.drift_pct:+.2f}pp drift from 60/40 target — {pension_drift.action}.",
            })
        for t in triggers:
            if t.status in ("ABOVE CEILING", "CEILING CROSSED", "BELOW SMA"):
                signals.append({
                    "sector": "Systematic / Vol-Target",
                    "tickers": ["SPY", "VIX"],
                    "bias": "BEARISH",
                    "reason": t.note,
                })
            elif t.status == "BELOW FLOOR":
                signals.append({
                    "sector": "Systematic / Vol-Target",
                    "tickers": ["SPY"],
                    "bias": "BULLISH",
                    "reason": t.note,
                })
        if not signals:
            signals.append({
                "sector": "Broad Market",
                "tickers": ["SPY"],
                "bias": "NEUTRAL",
                "reason": "No acute mechanical flow imbalance detected.",
            })

        recs = [summary]
        for f in sorted(leveraged_flows, key=lambda x: -x.rebalance_flow_usd)[:5]:
            recs.append(
                f"{f.symbol} ({f.leverage}x): ~${f.rebalance_flow_usd / 1e9:.2f}B to {f.direction} at the close."
            )
        if pension_drift:
            recs.append(
                f"Pension proxy: equity weight drifted to {pension_drift.current_equity_weight_pct:.2f}% "
                f"(target {pension_drift.baseline_equity_weight * 100:.0f}%) since {pension_drift.quarter_start}."
            )
        for ev in recon_calendar[:2]:
            recs.append(f"{ev.name}: {ev.event_date} ({ev.days_until} days out).")
        for t in triggers:
            recs.append(f"{t.indicator}: {t.level} — {t.status}.")
        recs.append("Monitor 3:30-3:50pm EST MOC imbalance feeds and JPM Flows & Liquidity / GS flow desk notes.")

        return InstitutionalFlowsReport(
            leveraged_etf_flows=leveraged_flows,
            pension_drift=pension_drift,
            reconstitution_calendar=recon_calendar,
            systematic_triggers=triggers,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_sources=dedup_sources,
        )

    def to_dict(self, report: InstitutionalFlowsReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Institutional & Mechanical Flows Tracker",
                "analyzed_at": report.analyzed_at,
                "data_sources": report.data_sources,
                "expert_summary": report.expert_summary,
            },
            "leveraged_etf_flows": [
                {
                    "symbol": f.symbol,
                    "name": f.name,
                    "leverage": f.leverage,
                    "aum_usd": f.aum_usd,
                    "underlying_daily_return_pct": f.underlying_daily_return_pct,
                    "rebalance_flow_usd": f.rebalance_flow_usd,
                    "direction": f.direction,
                }
                for f in report.leveraged_etf_flows
            ],
            "pension_drift": (
                {
                    "equity_total_return_pct": report.pension_drift.equity_total_return_pct,
                    "bond_total_return_pct": report.pension_drift.bond_total_return_pct,
                    "baseline_equity_weight": report.pension_drift.baseline_equity_weight,
                    "current_equity_weight_pct": report.pension_drift.current_equity_weight_pct,
                    "drift_pct": report.pension_drift.drift_pct,
                    "rebalance_amount_usd": report.pension_drift.rebalance_amount_usd,
                    "action": report.pension_drift.action,
                    "quarter_start": report.pension_drift.quarter_start,
                }
                if report.pension_drift
                else None
            ),
            "reconstitution_calendar": [
                {
                    "name": ev.name,
                    "event_date": ev.event_date,
                    "days_until": ev.days_until,
                    "description": ev.description,
                }
                for ev in report.reconstitution_calendar
            ],
            "systematic_triggers": [
                {
                    "indicator": t.indicator,
                    "level": t.level,
                    "status": t.status,
                    "note": t.note,
                }
                for t in report.systematic_triggers
            ],
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "institutional_flow_playbook.json"
            catalog.write_text(
                json.dumps(
                    {
                        "leveraged_etf_formula": "Rebalance Flow = AUM x L x (L - 1) x Daily Return",
                        "pension_drift_formula": (
                            "New Equity Weight = (0.60*(1+Re)) / (0.60*(1+Re) + 0.40*(1+Rb))"
                        ),
                        "tracked_leveraged_etfs": LEVERAGED_ETFS,
                        "reconstitution_rules": [
                            "S&P 500 quarterly rebalance: third Friday of Mar/Jun/Sep/Dec",
                            "FTSE Russell annual reconstitution: fourth Friday of June",
                        ],
                        "systematic_trigger_levels": {
                            "vix_floor": VIX_FLOOR,
                            "vix_ceilings": VIX_CEILINGS,
                            "sma_windows": list(SMA_WINDOWS),
                        },
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        return result


def run_institutional_flows_analysis(output: Path | None = None) -> dict[str, Any]:
    return InstitutionalFlowsExpert().run(output=output)
