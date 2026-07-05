"""
Short Squeeze / Failure-to-Deliver Expert Agent
================================================
Tracks structural short "failures" from two angles:

1. Macro / regulatory — SEC Failure-to-Deliver (FTD) net-balance files and the
   Reg SHO Threshold List (5 consecutive settlement days of >=10,000 FTD shares
   *and* >=0.5% of shares outstanding).
2. Micro / real-time — FINRA daily off-exchange short volume, Days-to-Cover,
   Short Float %, and a Cost-to-Borrow (CTB) capital-burn estimate that flags
   when borrow fees are high enough to force short capitulation.

Data: Yahoo Finance quoteSummary API (key statistics), FINRA daily short sale
volume files, and SEC Fails-to-Deliver data files.
"""

from __future__ import annotations

import io
import json
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

QUOTE_SUMMARY_API = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
FINRA_SHORT_VOLUME_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvolYYYYMMDD.txt"
SEC_FTD_URL = "https://www.sec.gov/files/data/fails-deliver-data/cnsfails{year}{month}{half}.zip"
HEADERS = {"User-Agent": "Finance-Short-Squeeze/1.0 (shaggychunxx@gmail.com)"}

REG_SHO_MIN_SHARES = 10_000
REG_SHO_MIN_PCT_OUTSTANDING = 0.5
REG_SHO_CONSECUTIVE_DAYS = 5
DAILY_SHORT_RATIO_WARNING_PCT = 60.0
DAYS_TO_COVER_HIGH_RISK = 5.0

WATCHLIST = {
    "GME": "GameStop Corp",
    "AMC": "AMC Entertainment",
    "SOUN": "SoundHound AI",
    "RIOT": "Riot Platforms",
    "IONQ": "IonQ Inc",
    "CVNA": "Carvana Co",
    "UPST": "Upstart Holdings",
    "LCID": "Lucid Group",
    "BYND": "Beyond Meat",
    "RILY": "B. Riley Financial",
}

SQUEEZE_MODELS: list[dict[str, Any]] = [
    {
        "id": "days_to_cover",
        "name": "Days-to-Cover (DTC)",
        "description": "Theoretical sessions required for shorts to buy back shares at current volume",
        "formula": "DTC = Total Shares Shorted / Average Daily Trading Volume",
    },
    {
        "id": "short_float_pct",
        "name": "Short Float %",
        "description": "Shorted shares as a percentage of the tradable float",
        "formula": "Short Float % = (Total Shares Shorted / Total Floating Shares) × 100",
    },
    {
        "id": "risk_multiplier",
        "name": "Squeeze Risk Multiplier",
        "description": "Composite of float scarcity, liquidity bottleneck, and raw short interest",
        "formula": "0.45·ShortFloat% + 0.35·min(DTC,20)·5 + 0.20·ShortInterest%O/S",
    },
    {
        "id": "daily_short_ratio",
        "name": "Daily Short Ratio (FINRA)",
        "description": "Off-exchange short volume share of total off-exchange volume for the session",
        "formula": "Daily Short Ratio = Daily Off-Exchange Short Volume / Daily Total Off-Exchange Volume",
    },
    {
        "id": "daily_borrow_fee_capital_charge",
        "name": "Daily Borrow Fee Capital Charge",
        "description": "Daily capital burn paid by short sellers to hold a hard-to-borrow position",
        "formula": "(Shares Shorted × Price × Annualized CTB Rate) / 360",
    },
    {
        "id": "reg_sho_threshold_test",
        "name": "Reg SHO Threshold List Test",
        "description": "5 consecutive settlement days of >=10,000 FTD shares and >=0.5% of shares outstanding",
        "formula": "qualifies(day) = (FTD_balance >= 10,000) AND (FTD_balance / SharesOutstanding >= 0.005)",
    },
]


@dataclass
class FTDRecord:
    settlement_date: str
    cusip: str
    ticker: str
    quantity: int
    description: str
    price: float


@dataclass
class RegShoStatus:
    ticker: str
    latest_ftd_balance: int
    latest_pct_of_shares_outstanding: float
    consecutive_qualifying_days: int
    on_threshold_list: bool
    rationale: str


@dataclass
class DailyShortVolumeRecord:
    symbol: str
    date: str
    short_volume: int
    total_volume: int
    daily_short_ratio_pct: float
    market_maker_warning: bool


@dataclass
class CostToBorrowEstimate:
    symbol: str
    price: float
    estimated_annualized_ctb_pct: float
    shares_shorted: int
    daily_borrow_fee_capital_charge: float
    fee_per_share: float
    tier: str
    escalation_flag: bool


@dataclass
class SqueezeMetrics:
    symbol: str
    name: str
    price: float
    shares_short: int
    shares_float: int
    shares_outstanding: int
    avg_daily_volume: int
    days_to_cover: float
    short_float_pct: float
    short_interest_pct_outstanding: float
    risk_multiplier: float
    squeeze_risk_label: str


@dataclass
class SqueezeAssessment:
    structural_signal: str
    liquidity_signal: str
    capital_burn_signal: str
    conclusion: str


@dataclass
class ShortSqueezeReport:
    squeeze_metrics: list[SqueezeMetrics]
    ctb_estimates: list[CostToBorrowEstimate]
    daily_short_volume: list[DailyShortVolumeRecord]
    reg_sho_status: list[RegShoStatus]
    assessment: SqueezeAssessment
    composite_risk_score: float
    regime_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def parse_ftd_file(text: str) -> list[FTDRecord]:
    """Parse a pipe-delimited SEC FTD text file into FTDRecord rows.

    Layout: Settlement Date | CUSIP | Ticker | FTD Quantity | Description | Price
    The reported quantity is a cumulative *net balance*, not a daily delta.
    """
    records: list[FTDRecord] = []
    for raw_line in text.strip().splitlines():
        line = raw_line.strip()
        if not line or line.upper().startswith("SETTLEMENT"):
            continue
        parts = line.split("|")
        if len(parts) < 6:
            continue
        settlement_date, cusip, ticker, quantity, description, price = parts[:6]
        try:
            records.append(
                FTDRecord(
                    settlement_date=settlement_date.strip(),
                    cusip=cusip.strip(),
                    ticker=ticker.strip().upper(),
                    quantity=int(quantity.strip().replace(",", "")),
                    description=description.strip(),
                    price=float(price.strip().replace(",", "")),
                )
            )
        except ValueError:
            continue
    return records


def parse_finra_short_volume_file(text: str) -> list[dict[str, str]]:
    """Parse a pipe-delimited FINRA daily short sale volume file (header + rows)."""
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    if len(lines) < 2:
        return []
    headers = [h.strip() for h in lines[0].split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[1:]:
        parts = line.split("|")
        if len(parts) != len(headers):
            continue
        rows.append(dict(zip(headers, [p.strip() for p in parts])))
    return rows


def compute_daily_short_ratio(short_volume: int, total_volume: int) -> tuple[float, bool]:
    if total_volume <= 0:
        return 0.0, False
    ratio = round(short_volume / total_volume * 100, 2)
    return ratio, ratio > DAILY_SHORT_RATIO_WARNING_PCT


def evaluate_reg_sho_threshold(
    ticker: str,
    daily_ftd_balances: list[tuple[str, int]],
    shares_outstanding: int,
) -> RegShoStatus:
    """Evaluate the Reg SHO Threshold List test from chronological net-balance history.

    Counts the *trailing* run of qualifying settlement days ending on the most
    recent date in ``daily_ftd_balances`` (i.e. whether the security qualifies
    for the list as of today), not the longest qualifying run anywhere in the
    history — a qualifying streak that ended in the past is no longer relevant
    to the security's current threshold-list status.
    """
    ordered = sorted(daily_ftd_balances, key=lambda pair: pair[0])
    consecutive = 0
    for _, balance in reversed(ordered):
        pct = (balance / shares_outstanding * 100) if shares_outstanding else 0.0
        qualifies = balance >= REG_SHO_MIN_SHARES and pct >= REG_SHO_MIN_PCT_OUTSTANDING
        if qualifies:
            consecutive += 1
        else:
            break

    latest_balance = ordered[-1][1] if ordered else 0
    latest_pct = round((latest_balance / shares_outstanding * 100) if shares_outstanding else 0.0, 4)
    on_list = consecutive >= REG_SHO_CONSECUTIVE_DAYS
    rationale = (
        f"{consecutive} consecutive qualifying settlement day(s) "
        f"(balance>=10,000 shares & >=0.5% of shares outstanding); "
        f"{'meets' if on_list else 'below'} the Reg SHO {REG_SHO_CONSECUTIVE_DAYS}-day threshold"
    )
    return RegShoStatus(
        ticker=ticker.upper(),
        latest_ftd_balance=latest_balance,
        latest_pct_of_shares_outstanding=latest_pct,
        consecutive_qualifying_days=consecutive,
        on_threshold_list=on_list,
        rationale=rationale,
    )


def compute_days_to_cover(shares_short: float, avg_daily_volume: float) -> float:
    if avg_daily_volume <= 0:
        return 0.0
    return round(shares_short / avg_daily_volume, 2)


def compute_short_float_pct(shares_short: float, shares_float: float) -> float:
    if shares_float <= 0:
        return 0.0
    return round(shares_short / shares_float * 100, 2)


def compute_short_interest_pct_outstanding(shares_short: float, shares_outstanding: float) -> float:
    if shares_outstanding <= 0:
        return 0.0
    return round(shares_short / shares_outstanding * 100, 2)


def compute_risk_multiplier(
    short_float_pct: float,
    days_to_cover: float,
    short_pct_outstanding: float,
) -> tuple[float, str]:
    """Composite squeeze-risk score. Float scarcity is weighted heaviest, since a
    tiny float can make a "moderate" short interest far more explosive than a
    high short interest on a stock with abundant float liquidity."""
    risk = round(
        0.45 * short_float_pct
        + 0.35 * min(days_to_cover, 20.0) * 5.0
        + 0.20 * short_pct_outstanding,
        2,
    )
    if risk >= 80:
        label = "Extreme Squeeze Risk"
    elif risk >= 50:
        label = "Elevated Squeeze Risk"
    elif risk >= 25:
        label = "Moderate Squeeze Risk"
    else:
        label = "Low Squeeze Risk"
    return risk, label


CTB_BASELINE_PCT = 1.0
CTB_SCARCITY_FLOAT_THRESHOLD_PCT = 15.0
CTB_SCARCITY_MULTIPLIER = 3.0
CTB_BOTTLENECK_DTC_THRESHOLD_DAYS = 2.0
CTB_BOTTLENECK_MULTIPLIER = 8.0
CTB_MAX_PCT = 500.0


def estimate_annualized_ctb_pct(short_float_pct: float, days_to_cover: float) -> float:
    """Model an implied Cost-to-Borrow rate from float scarcity and the liquidity
    bottleneck (DTC) when no live prime-broker borrow feed is available. This is
    a heuristic proxy, not a desk-quoted rate — treat as directional only.

    - Below CTB_SCARCITY_FLOAT_THRESHOLD_PCT short float, no scarcity premium applies.
    - Above it, each extra point of short float adds CTB_SCARCITY_MULTIPLIER points of CTB.
    - Below CTB_BOTTLENECK_DTC_THRESHOLD_DAYS days-to-cover, no bottleneck premium applies.
    - Above it, each extra day of DTC adds CTB_BOTTLENECK_MULTIPLIER points of CTB.
    """
    scarcity_premium = max(0.0, short_float_pct - CTB_SCARCITY_FLOAT_THRESHOLD_PCT) * CTB_SCARCITY_MULTIPLIER
    bottleneck_premium = max(0.0, days_to_cover - CTB_BOTTLENECK_DTC_THRESHOLD_DAYS) * CTB_BOTTLENECK_MULTIPLIER
    return round(min(CTB_BASELINE_PCT + scarcity_premium + bottleneck_premium, CTB_MAX_PCT), 2)


def classify_ctb_tier(annualized_ctb_pct: float) -> str:
    if annualized_ctb_pct >= 100:
        return "Squeeze-Tier (>100% CTB)"
    if annualized_ctb_pct >= 50:
        return "Hard-to-Borrow"
    if annualized_ctb_pct >= 10:
        return "Warm"
    return "Easy-to-Borrow"


def compute_daily_borrow_fee_capital_charge(
    shares_shorted: float,
    price: float,
    annualized_ctb_pct: float,
) -> float:
    return round(shares_shorted * price * (annualized_ctb_pct / 100.0) / 360.0, 2)


class ShortSqueezeExpert:
    """Short-fail / squeeze-risk analyst — combines lag-heavy regulatory FTD data
    with real-time short volume and cost-to-borrow signals."""

    def __init__(self, delay_seconds: float = 0.3) -> None:
        self.delay_seconds = delay_seconds

    @staticmethod
    def _raw(mod: dict[str, Any], field_name: str) -> Any:
        value = mod.get(field_name)
        if isinstance(value, dict):
            return value.get("raw")
        return value

    def _fetch_key_stats(self, symbol: str) -> dict[str, Any]:
        try:
            resp = requests.get(
                QUOTE_SUMMARY_API.format(symbol=symbol),
                params={"modules": "defaultKeyStatistics,price"},
                headers=HEADERS,
                timeout=25,
            )
            if resp.status_code == 429:
                time.sleep(3)
                resp = requests.get(
                    QUOTE_SUMMARY_API.format(symbol=symbol),
                    params={"modules": "defaultKeyStatistics,price"},
                    headers=HEADERS,
                    timeout=25,
                )
            resp.raise_for_status()
            result = resp.json().get("quoteSummary", {}).get("result") or []
            if not result:
                return {}
            data = result[0]
            stats = data.get("defaultKeyStatistics", {}) or {}
            price_mod = data.get("price", {}) or {}
            return {
                "shares_short": self._raw(stats, "sharesShort") or 0,
                "shares_float": self._raw(stats, "floatShares") or 0,
                "shares_outstanding": self._raw(stats, "sharesOutstanding") or 0,
                "price": self._raw(price_mod, "regularMarketPrice") or 0.0,
                "avg_daily_volume": (
                    self._raw(price_mod, "averageDailyVolume10Day")
                    or self._raw(stats, "averageDailyVolume10Day")
                    or self._raw(stats, "averageVolume10days")
                    or 0
                ),
            }
        except Exception:
            return {}

    @staticmethod
    def _latest_trading_day() -> str:
        day = datetime.now(timezone.utc) - timedelta(days=1)
        while day.weekday() >= 5:
            day -= timedelta(days=1)
        return day.strftime("%Y%m%d")

    def _fetch_finra_short_volume(self, symbol: str) -> DailyShortVolumeRecord | None:
        date_str = self._latest_trading_day()
        url = FINRA_SHORT_VOLUME_URL.replace("YYYYMMDD", date_str)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                return None
            rows = parse_finra_short_volume_file(resp.text)
            for row in rows:
                if row.get("Symbol", "").upper() == symbol.upper():
                    short_vol = int(row.get("ShortVolume") or 0)
                    total_vol = int(row.get("TotalVolume") or 0)
                    ratio, warning = compute_daily_short_ratio(short_vol, total_vol)
                    return DailyShortVolumeRecord(
                        symbol=symbol.upper(),
                        date=date_str,
                        short_volume=short_vol,
                        total_volume=total_vol,
                        daily_short_ratio_pct=ratio,
                        market_maker_warning=warning,
                    )
            return None
        except Exception:
            return None

    @staticmethod
    def _latest_ftd_cycle_url() -> str:
        """SEC FTD files publish twice monthly with a lag: the 1st-15th cycle
        ('a') is released end of month, the 16th-end cycle ('b') mid the
        following month. Approximate the most recently published cycle."""
        today = datetime.now(timezone.utc)
        if today.day <= 15:
            if today.month == 1:
                month, year = 12, today.year - 1
            else:
                month, year = today.month - 1, today.year
            half = "b"
        else:
            month, year = today.month, today.year
            half = "a"
        return SEC_FTD_URL.format(year=year, month=f"{month:02d}", half=half)

    def _fetch_ftd_records(self, symbol: str) -> list[FTDRecord]:
        try:
            resp = requests.get(self._latest_ftd_cycle_url(), headers=HEADERS, timeout=30)
            if resp.status_code != 200:
                return []
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                name = next((n for n in zf.namelist() if n.lower().endswith(".txt")), None)
                if not name:
                    return []
                text = zf.read(name).decode("utf-8", errors="ignore")
            return [r for r in parse_ftd_file(text) if r.ticker == symbol.upper()]
        except Exception:
            return []

    def analyze(self) -> ShortSqueezeReport:
        squeeze_metrics: list[SqueezeMetrics] = []
        ctb_estimates: list[CostToBorrowEstimate] = []
        daily_short_volume: list[DailyShortVolumeRecord] = []
        reg_sho_status: list[RegShoStatus] = []

        for symbol, name in WATCHLIST.items():
            stats = self._fetch_key_stats(symbol)
            time.sleep(self.delay_seconds)
            if not stats or not stats.get("price") or not stats.get("shares_outstanding"):
                continue

            dtc = compute_days_to_cover(stats["shares_short"], stats["avg_daily_volume"])
            sfp = compute_short_float_pct(stats["shares_short"], stats["shares_float"])
            sipo = compute_short_interest_pct_outstanding(stats["shares_short"], stats["shares_outstanding"])
            risk_mult, risk_label = compute_risk_multiplier(sfp, dtc, sipo)

            squeeze_metrics.append(
                SqueezeMetrics(
                    symbol=symbol,
                    name=name,
                    price=stats["price"],
                    shares_short=int(stats["shares_short"]),
                    shares_float=int(stats["shares_float"]),
                    shares_outstanding=int(stats["shares_outstanding"]),
                    avg_daily_volume=int(stats["avg_daily_volume"]),
                    days_to_cover=dtc,
                    short_float_pct=sfp,
                    short_interest_pct_outstanding=sipo,
                    risk_multiplier=risk_mult,
                    squeeze_risk_label=risk_label,
                )
            )

            ctb_rate = estimate_annualized_ctb_pct(sfp, dtc)
            shares_shorted = int(stats["shares_short"])
            capital_charge = compute_daily_borrow_fee_capital_charge(shares_shorted, stats["price"], ctb_rate)
            fee_per_share = round(stats["price"] * ctb_rate / 100.0 / 360.0, 4)
            ctb_estimates.append(
                CostToBorrowEstimate(
                    symbol=symbol,
                    price=stats["price"],
                    estimated_annualized_ctb_pct=ctb_rate,
                    shares_shorted=shares_shorted,
                    daily_borrow_fee_capital_charge=capital_charge,
                    fee_per_share=fee_per_share,
                    tier=classify_ctb_tier(ctb_rate),
                    escalation_flag=ctb_rate >= 50.0,
                )
            )

            dsv = self._fetch_finra_short_volume(symbol)
            if dsv:
                daily_short_volume.append(dsv)

            ftd_records = self._fetch_ftd_records(symbol)
            if ftd_records:
                balances = [(r.settlement_date, r.quantity) for r in ftd_records]
                reg_sho_status.append(
                    evaluate_reg_sho_threshold(symbol, balances, int(stats["shares_outstanding"]))
                )

        if not squeeze_metrics:
            raise RuntimeError("Unable to fetch short interest data for short-squeeze analysis")

        assessment = self._assessment(squeeze_metrics, ctb_estimates, daily_short_volume, reg_sho_status)
        composite_risk_score = round(
            sum(m.risk_multiplier for m in squeeze_metrics) / max(len(squeeze_metrics), 1),
            2,
        )
        if composite_risk_score >= 60:
            regime_label = "Systemic Short-Fail Risk"
        elif composite_risk_score >= 35:
            regime_label = "Elevated Short-Fail Risk"
        else:
            regime_label = "Contained Short-Fail Risk"

        summary = self._expert_summary(assessment, regime_label, squeeze_metrics, reg_sho_status)
        signals = self._market_signals(squeeze_metrics, ctb_estimates, reg_sho_status)
        recs = self._recommendations(squeeze_metrics, ctb_estimates, daily_short_volume, reg_sho_status)

        return ShortSqueezeReport(
            squeeze_metrics=squeeze_metrics,
            ctb_estimates=ctb_estimates,
            daily_short_volume=daily_short_volume,
            reg_sho_status=reg_sho_status,
            assessment=assessment,
            composite_risk_score=composite_risk_score,
            regime_label=regime_label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source="Yahoo Finance quoteSummary + FINRA short volume + SEC FTD data",
        )

    @staticmethod
    def _assessment(
        squeeze_metrics: list[SqueezeMetrics],
        ctb_estimates: list[CostToBorrowEstimate],
        daily_short_volume: list[DailyShortVolumeRecord],
        reg_sho_status: list[RegShoStatus],
    ) -> SqueezeAssessment:
        on_list = [r for r in reg_sho_status if r.on_threshold_list]
        structural_signal = (
            f"{len(on_list)} of {len(reg_sho_status)} tracked tickers meet the Reg SHO "
            f"5-day threshold test" if reg_sho_status else "No FTD cycle data available this run"
        )

        high_dtc = [m for m in squeeze_metrics if m.days_to_cover >= DAYS_TO_COVER_HIGH_RISK]
        liquidity_signal = (
            f"{len(high_dtc)} of {len(squeeze_metrics)} tickers show DTC >= "
            f"{DAYS_TO_COVER_HIGH_RISK:.1f} sessions (liquidity bottleneck)"
        )

        escalating = [c for c in ctb_estimates if c.escalation_flag]
        capital_burn_signal = (
            f"{len(escalating)} of {len(ctb_estimates)} tickers modeled in Hard-to-Borrow "
            f"or Squeeze-Tier CTB territory"
        )

        top = max(squeeze_metrics, key=lambda m: m.risk_multiplier)
        conclusion = (
            f"{top.symbol} carries the highest composite squeeze risk "
            f"({top.risk_multiplier}, {top.squeeze_risk_label}): "
            f"{top.short_float_pct:.1f}% short float, {top.days_to_cover:.1f}d to cover"
        )

        return SqueezeAssessment(
            structural_signal=structural_signal,
            liquidity_signal=liquidity_signal,
            capital_burn_signal=capital_burn_signal,
            conclusion=conclusion,
        )

    @staticmethod
    def _expert_summary(
        assessment: SqueezeAssessment,
        regime_label: str,
        squeeze_metrics: list[SqueezeMetrics],
        reg_sho_status: list[RegShoStatus],
    ) -> str:
        return (
            f"Regime: {regime_label}. {assessment.conclusion}. {assessment.structural_signal}. "
            f"{assessment.liquidity_signal}. {assessment.capital_burn_signal}."
        )

    @staticmethod
    def _market_signals(
        squeeze_metrics: list[SqueezeMetrics],
        ctb_estimates: list[CostToBorrowEstimate],
        reg_sho_status: list[RegShoStatus],
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        ctb_by_symbol = {c.symbol: c for c in ctb_estimates}
        reg_sho_by_symbol = {r.ticker: r for r in reg_sho_status}

        for m in sorted(squeeze_metrics, key=lambda x: -x.risk_multiplier)[:5]:
            if m.squeeze_risk_label in ("Extreme Squeeze Risk", "Elevated Squeeze Risk"):
                ctb = ctb_by_symbol.get(m.symbol)
                reason = (
                    f"Short float {m.short_float_pct:.1f}%, DTC {m.days_to_cover:.1f}d, "
                    f"risk score {m.risk_multiplier}"
                )
                if ctb:
                    reason += f", est. CTB {ctb.estimated_annualized_ctb_pct:.0f}% ({ctb.tier})"
                signals.append({
                    "sector": f"Squeeze Watch — {m.name}",
                    "tickers": [m.symbol],
                    "bias": "BULLISH",
                    "reason": reason,
                })

        for r in reg_sho_status:
            if r.on_threshold_list:
                signals.append({
                    "sector": "Reg SHO Threshold List",
                    "tickers": [r.ticker],
                    "bias": "BULLISH",
                    "reason": r.rationale,
                })

        if not signals:
            signals.append({
                "sector": "Short-Fail Neutral",
                "tickers": list(WATCHLIST.keys())[:1],
                "bias": "NEUTRAL",
                "reason": "No tracked ticker crosses elevated squeeze-risk thresholds this run",
            })
        return signals

    @staticmethod
    def _recommendations(
        squeeze_metrics: list[SqueezeMetrics],
        ctb_estimates: list[CostToBorrowEstimate],
        daily_short_volume: list[DailyShortVolumeRecord],
        reg_sho_status: list[RegShoStatus],
    ) -> list[str]:
        recs: list[str] = []
        for m in sorted(squeeze_metrics, key=lambda x: -x.risk_multiplier)[:6]:
            recs.append(
                f"{m.symbol}: {m.squeeze_risk_label} (score {m.risk_multiplier}) — "
                f"{m.short_float_pct:.1f}% short float, {m.days_to_cover:.1f}d to cover, "
                f"{m.short_interest_pct_outstanding:.1f}% of shares outstanding"
            )
        for c in sorted(ctb_estimates, key=lambda x: -x.estimated_annualized_ctb_pct)[:5]:
            if c.tier in ("Hard-to-Borrow", "Squeeze-Tier (>100% CTB)"):
                recs.append(
                    f"{c.symbol}: est. CTB {c.estimated_annualized_ctb_pct:.0f}% ({c.tier}) — "
                    f"${c.daily_borrow_fee_capital_charge:,.0f}/day capital burn on shorts"
                )
        for d in daily_short_volume:
            if d.market_maker_warning:
                recs.append(
                    f"{d.symbol}: Daily Short Ratio {d.daily_short_ratio_pct:.1f}% on {d.date} — "
                    f"largely market-maker inventory balancing, not new short interest"
                )
        for r in reg_sho_status:
            if r.on_threshold_list:
                recs.append(f"{r.ticker}: {r.rationale}")
        return recs

    def to_dict(self, report: ShortSqueezeReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Short Squeeze / Failure-to-Deliver Expert",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
                "methods_applied": [m["id"] for m in SQUEEZE_MODELS],
            },
            "squeeze_metrics": [
                {
                    "symbol": m.symbol,
                    "name": m.name,
                    "price": m.price,
                    "shares_short": m.shares_short,
                    "shares_float": m.shares_float,
                    "shares_outstanding": m.shares_outstanding,
                    "avg_daily_volume": m.avg_daily_volume,
                    "days_to_cover": m.days_to_cover,
                    "short_float_pct": m.short_float_pct,
                    "short_interest_pct_outstanding": m.short_interest_pct_outstanding,
                    "risk_multiplier": m.risk_multiplier,
                    "squeeze_risk_label": m.squeeze_risk_label,
                }
                for m in report.squeeze_metrics
            ],
            "ctb_estimates": [
                {
                    "symbol": c.symbol,
                    "price": c.price,
                    "estimated_annualized_ctb_pct": c.estimated_annualized_ctb_pct,
                    "shares_shorted": c.shares_shorted,
                    "daily_borrow_fee_capital_charge": c.daily_borrow_fee_capital_charge,
                    "fee_per_share": c.fee_per_share,
                    "tier": c.tier,
                    "escalation_flag": c.escalation_flag,
                }
                for c in report.ctb_estimates
            ],
            "daily_short_volume": [
                {
                    "symbol": d.symbol,
                    "date": d.date,
                    "short_volume": d.short_volume,
                    "total_volume": d.total_volume,
                    "daily_short_ratio_pct": d.daily_short_ratio_pct,
                    "market_maker_warning": d.market_maker_warning,
                }
                for d in report.daily_short_volume
            ],
            "reg_sho_status": [
                {
                    "ticker": r.ticker,
                    "latest_ftd_balance": r.latest_ftd_balance,
                    "latest_pct_of_shares_outstanding": r.latest_pct_of_shares_outstanding,
                    "consecutive_qualifying_days": r.consecutive_qualifying_days,
                    "on_threshold_list": r.on_threshold_list,
                    "rationale": r.rationale,
                }
                for r in report.reg_sho_status
            ],
            "squeeze_assessment": {
                "structural_signal": a.structural_signal,
                "liquidity_signal": a.liquidity_signal,
                "capital_burn_signal": a.capital_burn_signal,
                "conclusion": a.conclusion,
            },
            "metrics": {
                "composite_risk_score": report.composite_risk_score,
                "regime_label": report.regime_label,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "squeeze_models.json"
            catalog.write_text(json.dumps(SQUEEZE_MODELS, indent=2), encoding="utf-8")
        return result


def run_short_squeeze_analysis(output: Path | None = None) -> dict[str, Any]:
    return ShortSqueezeExpert().run(output=output)
