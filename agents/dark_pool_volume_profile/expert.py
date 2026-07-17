"""
Dark Pool & Volume Profile Expert Agent
========================================
Reverse-engineers institutional order flow using Auction Market Theory.
Builds a price-based Volume Profile (Point of Control, Value Area High/Low,
High/Low Volume Nodes) from daily OHLCV bars and cross-references it against
public-tape proxies for FINRA Trade Reporting Facility (TRF) dark-pool /
internalizer activity — quiet, high-volume "accumulation" sessions and
outlier "signature print" volume spikes that revisit a prior structural
level.

Data: Yahoo Finance chart API (6-month daily OHLCV). Real-time Level 2 /
tick-level TRF tape data (exchange code "D"/ADF, multi-venue sweep
timestamps) is not available from this public endpoint, so the dark-pool
signals below are disclosed, calibrated *proxies* derived from public daily
bars — not a live FINRA TRF/ADF feed.
"""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base import BaseExpert

BENCHMARK = "SPY"

# Shared watchlist mix of liquidity tiers (deep mega-caps through thinner,
# retail-driven names) so dark-pool proxy concentration is meaningful.
WATCHLIST: dict[str, str] = {
    "SPY": "S&P 500 (deep liquidity proxy)",
    "AAPL": "Mega-cap tech (deep liquidity)",
    "MSFT": "Mega-cap tech (deep liquidity)",
    "QQQ": "Nasdaq 100 (deep liquidity)",
    "IWM": "Russell 2000 (moderate liquidity)",
    "GME": "Retail-driven small/mid cap (volatile)",
    "COIN": "Crypto-adjacent equity (volatile)",
    "PLTR": "High-beta growth name (moderate-thin liquidity)",
}

NUM_BINS = 24
VALUE_AREA_PCT = 0.70
QUIET_VOLUME_MULTIPLIER = 1.3   # volume >= 1.3x average on a "quiet accumulation" day
QUIET_RANGE_FACTOR = 0.70       # ...while daily range stays below 70% of the median range
SIGNATURE_ZSCORE_THRESHOLD = 2.5
SIGNATURE_LEVEL_TOLERANCE_PCT = 1.0  # signature print price must sit within 1% of a prior HVN/POC

METHODOLOGY_PLAYBOOK: list[dict[str, Any]] = [
    {
        "id": "volume_profile",
        "name": "Volume Profile (Auction Market Theory)",
        "summary": (
            "Bins traded volume by price (not time) to reveal the Point of Control (POC), "
            "the 70% Value Area (VAH/VAL), and High/Low Volume Nodes (HVN/LVN)."
        ),
        "balanced_read": "POC centered, price rotates between VAH and VAL (bell-curve auction).",
        "imbalanced_read": (
            "Price breaks outside the Value Area and slices through LVNs (no resting inventory) "
            "until it reaches the next historical HVN, where a new auction can form."
        ),
    },
    {
        "id": "trf_concentration_proxy",
        "name": "FINRA TRF Volume Concentration Proxy",
        "summary": (
            "Flags sessions with above-average volume but a compressed daily range as a proxy "
            "for off-exchange (dark pool / internalizer) accumulation, since real TRF tape "
            "prints (exchange code 'D'/ADF) are not exposed by this public data source."
        ),
        "behavioral_read": (
            "A rising share of period volume concentrated in quiet, tight-range sessions "
            "suggests passive institutional accumulation without lifting the visible offer."
        ),
    },
    {
        "id": "signature_print_proxy",
        "name": "Signature / Late Print Proxy",
        "summary": (
            "Flags statistical volume outliers (z-score >= 2.5) whose closing price revisits a "
            "prior Point of Control or High Volume Node, proxying a late-reported block print "
            "defending a pre-negotiated institutional level."
        ),
        "strategy": (
            "Treat the revisited level as a structural line in the sand — approach from above "
            "expects passive defense (support); a clean break invalidates the thesis."
        ),
    },
    {
        "id": "sweep_block_disclosure",
        "name": "Sweep vs. Block Execution (Disclosure)",
        "summary": (
            "Distinguishing single-venue block prints from multi-exchange Intermarket Sweep "
            "Orders (ISOs) requires microsecond-timestamped, multi-venue tick data. This agent "
            "only has daily OHLCV, so sweep/block classification is out of scope here and is "
            "surfaced as a data-gap disclosure rather than a fabricated signal."
        ),
    },
]


@dataclass
class SymbolVolumeProfile:
    symbol: str
    name: str
    last_close: float
    poc: float
    vah: float
    val: float
    hvns: list[float]
    lvns: list[float]
    auction_state: str
    trf_proxy_ratio_pct: float
    quiet_volume_sessions: int
    signature_prints: list[dict[str, Any]]
    rationale: str


@dataclass
class DarkPoolAssessment:
    breadth_signal: str
    trf_concentration_signal: str
    signature_print_signal: str
    auction_state_signal: str
    conclusion: str


@dataclass
class DarkPoolVolumeProfileReport:
    symbols: list[SymbolVolumeProfile]
    assessment: DarkPoolAssessment
    accumulation_score: float
    imbalance_score: float
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DarkPoolVolumeProfileExpert(BaseExpert):
    """Expert market analyst — Volume Profile structure + FINRA TRF dark-pool proxies."""

    def __init__(
        self,
        delay_seconds: float = 0.35,
        *,
        pipeline_context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="dark-pool-volume-profile")
        self.delay_seconds = delay_seconds

    @staticmethod
    def _volume_profile(
        highs: list[float], lows: list[float], volumes: list[float]
    ) -> tuple[list[float], list[float]] | None:
        lo, hi = min(lows), max(highs)
        if hi <= lo:
            return None
        bin_width = (hi - lo) / NUM_BINS
        bin_volumes = [0.0] * NUM_BINS
        for h, l, v in zip(highs, lows, volumes):
            start_bin = max(0, min(NUM_BINS - 1, int((l - lo) / bin_width)))
            end_bin = max(0, min(NUM_BINS - 1, int((h - lo) / bin_width)))
            if end_bin < start_bin:
                start_bin, end_bin = end_bin, start_bin
            span = end_bin - start_bin + 1
            share = v / span
            for b in range(start_bin, end_bin + 1):
                bin_volumes[b] += share
        bin_prices = [lo + (i + 0.5) * bin_width for i in range(NUM_BINS)]
        return bin_prices, bin_volumes

    @staticmethod
    def _value_area(bin_prices: list[float], bin_volumes: list[float]) -> tuple[float, float, float]:
        poc_idx = max(range(len(bin_volumes)), key=lambda i: bin_volumes[i])
        total_vol = sum(bin_volumes)
        target = total_vol * VALUE_AREA_PCT
        va_indices = {poc_idx}
        cum = bin_volumes[poc_idx]
        left, right = poc_idx - 1, poc_idx + 1
        n = len(bin_volumes)
        while cum < target and (left >= 0 or right < n):
            left_vol = bin_volumes[left] if left >= 0 else -1.0
            right_vol = bin_volumes[right] if right < n else -1.0
            if right_vol >= left_vol and right < n:
                cum += bin_volumes[right]
                va_indices.add(right)
                right += 1
            elif left >= 0:
                cum += bin_volumes[left]
                va_indices.add(left)
                left -= 1
            else:
                break
        poc = bin_prices[poc_idx]
        vah = bin_prices[max(va_indices)]
        val = bin_prices[min(va_indices)]
        return poc, vah, val

    @staticmethod
    def _hvns_lvns(bin_prices: list[float], bin_volumes: list[float]) -> tuple[list[float], list[float]]:
        ranked = sorted(range(len(bin_volumes)), key=lambda i: -bin_volumes[i])
        hvns = [round(bin_prices[i], 2) for i in ranked[:3] if bin_volumes[i] > 0]
        mean_vol = statistics.mean(bin_volumes) if bin_volumes else 0.0
        lvns = [
            round(bin_prices[i], 2)
            for i in range(len(bin_volumes))
            if 0 < bin_volumes[i] < mean_vol * 0.35
        ][:3]
        return hvns, lvns

    @staticmethod
    def _auction_state(last_close: float, vah: float, val: float) -> str:
        if last_close > vah:
            return "Imbalanced — price above Value Area (bullish expansion, LVNs below act as thin support)"
        if last_close < val:
            return "Imbalanced — price below Value Area (bearish expansion, LVNs above act as thin resistance)"
        return "Balanced — price rotating inside the Value Area (two-way auction)"

    @staticmethod
    def _trf_proxy(
        highs: list[float], lows: list[float], closes: list[float], volumes: list[float]
    ) -> tuple[float, int]:
        ranges_pct = [
            (h - l) / c * 100 for h, l, c in zip(highs, lows, closes) if c
        ]
        if not ranges_pct or not volumes:
            return 0.0, 0
        median_range = statistics.median(ranges_pct)
        avg_volume = statistics.mean(volumes)
        total_volume = sum(volumes)
        quiet_volume = 0.0
        quiet_sessions = 0
        for r, v in zip(ranges_pct, volumes):
            if v >= avg_volume * QUIET_VOLUME_MULTIPLIER and r <= median_range * QUIET_RANGE_FACTOR:
                quiet_volume += v
                quiet_sessions += 1
        ratio_pct = round(quiet_volume / total_volume * 100, 2) if total_volume else 0.0
        return ratio_pct, quiet_sessions

    @staticmethod
    def _signature_prints(
        closes: list[float], volumes: list[float], structural_levels: list[float]
    ) -> list[dict[str, Any]]:
        if len(volumes) < 5 or not structural_levels:
            return []
        mean_vol = statistics.mean(volumes)
        stdev_vol = statistics.pstdev(volumes) or 1.0
        prints: list[dict[str, Any]] = []
        for offset, (price, vol) in enumerate(zip(closes, volumes)):
            z = (vol - mean_vol) / stdev_vol
            if z < SIGNATURE_ZSCORE_THRESHOLD:
                continue
            for level in structural_levels:
                if level and abs(price - level) / level * 100 <= SIGNATURE_LEVEL_TOLERANCE_PCT:
                    sessions_ago = len(closes) - 1 - offset
                    prints.append(
                        {
                            "sessions_ago": sessions_ago,
                            "price": round(price, 2),
                            "volume_zscore": round(z, 2),
                            "revisited_level": round(level, 2),
                        }
                    )
                    break
        prints.sort(key=lambda p: p["sessions_ago"])
        return prints[:5]

    def _analyze_symbol(self, symbol: str, name: str) -> SymbolVolumeProfile | None:
        data = self.fetch_yahoo_ohlcv(symbol, range_="6mo", interval="1d")
        closes = data["close"]
        if len(closes) < 20:
            return None
        highs, lows, volumes = data["high"], data["low"], data["volume"]
        last_close = closes[-1]

        profile = self._volume_profile(highs, lows, volumes)
        if profile is None:
            return None
        bin_prices, bin_volumes = profile
        poc, vah, val = self._value_area(bin_prices, bin_volumes)
        hvns, lvns = self._hvns_lvns(bin_prices, bin_volumes)
        auction_state = self._auction_state(last_close, vah, val)

        trf_ratio_pct, quiet_sessions = self._trf_proxy(highs, lows, closes, volumes)
        signature_prints = self._signature_prints(closes, volumes, [poc, *hvns])

        if trf_ratio_pct >= 40:
            trf_read = (
                f"Elevated quiet-volume concentration ({trf_ratio_pct:.1f}% of period volume) — "
                "proxy for dark accumulation feeding off-exchange rather than lifting the offer."
            )
        elif trf_ratio_pct >= 20:
            trf_read = f"Moderate quiet-volume concentration ({trf_ratio_pct:.1f}%) — watch for continuation."
        else:
            trf_read = f"Low quiet-volume concentration ({trf_ratio_pct:.1f}%) — no strong dark-pool proxy signal."

        rationale = (
            f"POC ${poc:.2f} | Value Area ${val:.2f}-${vah:.2f}. {auction_state}. {trf_read}"
        )
        if signature_prints:
            rationale += (
                f" {len(signature_prints)} signature-print candidate(s) revisiting prior HVN/POC levels."
            )

        return SymbolVolumeProfile(
            symbol=symbol,
            name=name,
            last_close=round(last_close, 2),
            poc=round(poc, 2),
            vah=round(vah, 2),
            val=round(val, 2),
            hvns=hvns,
            lvns=lvns,
            auction_state=auction_state,
            trf_proxy_ratio_pct=trf_ratio_pct,
            quiet_volume_sessions=quiet_sessions,
            signature_prints=signature_prints,
            rationale=rationale,
        )

    def _assessment(self, symbols: list[SymbolVolumeProfile]) -> DarkPoolAssessment:
        imbalanced = [s for s in symbols if s.auction_state.startswith("Imbalanced")]
        high_trf = [s for s in symbols if s.trf_proxy_ratio_pct >= 40]
        with_prints = [s for s in symbols if s.signature_prints]

        breadth_signal = (
            f"{len(imbalanced)}/{len(symbols)} symbols are trading outside their Value Area "
            "(imbalanced auctions likely to travel toward the next HVN)."
        )
        trf_concentration_signal = (
            f"{len(high_trf)}/{len(symbols)} symbols show elevated quiet-volume (dark-pool proxy) "
            "concentration above 40% of period volume."
        )
        signature_print_signal = (
            f"{len(with_prints)}/{len(symbols)} symbols flagged signature-print candidates "
            "revisiting a prior POC/HVN level."
        )
        auction_state_signal = (
            f"{len(symbols) - len(imbalanced)}/{len(symbols)} symbols remain balanced, rotating "
            "between Value Area High and Low."
        )

        if high_trf and imbalanced:
            conclusion = (
                "Dark-pool proxy concentration is elevated on names already breaking their Value "
                "Area — favor trading in the direction of the breakout toward the next HVN, with "
                "stops just beyond the nearest LVN."
            )
        elif high_trf:
            conclusion = (
                "Elevated quiet-volume concentration while price stays inside the Value Area "
                "suggests passive institutional accumulation — watch for a structural break once "
                "the resting supply/demand is absorbed."
            )
        else:
            conclusion = (
                "No strong dark-pool proxy signal across the watchlist — treat Volume Profile "
                "levels (POC/VAH/VAL) as the primary structural reference."
            )

        return DarkPoolAssessment(
            breadth_signal=breadth_signal,
            trf_concentration_signal=trf_concentration_signal,
            signature_print_signal=signature_print_signal,
            auction_state_signal=auction_state_signal,
            conclusion=conclusion,
        )

    def _expert_summary(self, assessment: DarkPoolAssessment) -> str:
        return (
            f"Dark pool & volume profile scan: {assessment.breadth_signal} "
            f"{assessment.trf_concentration_signal} {assessment.signature_print_signal} "
            f"{assessment.conclusion}"
        )

    def _market_signals(self, symbols: list[SymbolVolumeProfile]) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        def _keep(symbol: str) -> bool:
            return not self.pipeline_should_skip_symbol(symbol)

        accumulating = [
            s.symbol
            for s in symbols
            if s.trf_proxy_ratio_pct >= 40
            and s.auction_state.startswith("Balanced")
            and _keep(s.symbol)
        ]
        if accumulating:
            signals.append(
                {
                    "sector": "Dark Pool Proxy",
                    "bias": "bullish",
                    "tickers": accumulating,
                    "reason": "Elevated quiet-volume concentration inside the Value Area — proxy for passive dark accumulation.",
                }
            )
        bullish_breakout = [
            s.symbol
            for s in symbols
            if s.auction_state.startswith("Imbalanced") and s.last_close > s.vah and _keep(s.symbol)
        ]
        if bullish_breakout:
            signals.append(
                {
                    "sector": "Volume Profile",
                    "bias": "bullish",
                    "tickers": bullish_breakout,
                    "reason": "Price has broken above the Value Area High — imbalanced auction targeting the next HVN.",
                }
            )
        bearish_breakdown = [
            s.symbol
            for s in symbols
            if s.auction_state.startswith("Imbalanced") and s.last_close < s.val and _keep(s.symbol)
        ]
        if bearish_breakdown:
            signals.append(
                {
                    "sector": "Volume Profile",
                    "bias": "bearish",
                    "tickers": bearish_breakdown,
                    "reason": "Price has broken below the Value Area Low — imbalanced auction targeting the next HVN below.",
                }
            )
        signature = [s.symbol for s in symbols if s.signature_prints and _keep(s.symbol)]
        if signature:
            signals.append(
                {
                    "sector": "Dark Pool Proxy",
                    "bias": "watch",
                    "tickers": signature,
                    "reason": "Signature-print candidate revisiting a prior POC/HVN — potential institutional defense level.",
                }
            )
        return signals

    def _recommendations(
        self, symbols: list[SymbolVolumeProfile], assessment: DarkPoolAssessment
    ) -> list[str]:
        recs = [assessment.conclusion]
        for s in sorted(symbols, key=lambda x: -x.trf_proxy_ratio_pct)[:6]:
            recs.append(f"{s.symbol}: {s.rationale}")
        return recs

    def analyze(self) -> DarkPoolVolumeProfileReport:
        symbols: list[SymbolVolumeProfile] = []
        for symbol, name in WATCHLIST.items():
            row = self._analyze_symbol(symbol, name)
            if row:
                symbols.append(row)
            time.sleep(self.delay_seconds)

        if not any(s.symbol == BENCHMARK for s in symbols):
            raise RuntimeError("Unable to fetch SPY data for dark pool volume profile analysis")

        assessment = self._assessment(symbols)
        expert_summary = self._expert_summary(assessment)

        accumulation_score = round(
            statistics.mean([s.trf_proxy_ratio_pct for s in symbols]) / 10, 1
        )
        imbalance_score = round(
            sum(1 for s in symbols if s.auction_state.startswith("Imbalanced")) / len(symbols) * 10,
            1,
        )

        return DarkPoolVolumeProfileReport(
            symbols=symbols,
            assessment=assessment,
            accumulation_score=accumulation_score,
            imbalance_score=imbalance_score,
            expert_summary=expert_summary,
            market_signals=self._market_signals(symbols),
            recommendations=self.append_memory_recommendations(
                self._recommendations(symbols, assessment)
            ),
            data_source="Yahoo Finance Chart API (6mo daily OHLCV) — dark-pool/TRF signals are proxies, not a live FINRA TRF/ADF feed",
        )

    def to_dict(self, report: DarkPoolVolumeProfileReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Dark Pool & Volume Profile Expert",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
                "temperature": self.temperature,
                "pipeline_memory": {
                    "posture": self.pipeline_context.get("posture"),
                    "lessons": self.pipeline_memory_notes(),
                    "preferred_horizon": self.pipeline_context.get("preferred_horizon"),
                },
            },
            "methodology_playbook": METHODOLOGY_PLAYBOOK,
            "symbol_volume_profiles": [
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "last_close": s.last_close,
                    "poc": s.poc,
                    "vah": s.vah,
                    "val": s.val,
                    "hvns": s.hvns,
                    "lvns": s.lvns,
                    "auction_state": s.auction_state,
                    "trf_proxy_ratio_pct": s.trf_proxy_ratio_pct,
                    "quiet_volume_sessions": s.quiet_volume_sessions,
                    "signature_prints": s.signature_prints,
                    "rationale": s.rationale,
                }
                for s in report.symbols
            ],
            "dark_pool_assessment": {
                "breadth_signal": a.breadth_signal,
                "trf_concentration_signal": a.trf_concentration_signal,
                "signature_print_signal": a.signature_print_signal,
                "auction_state_signal": a.auction_state_signal,
                "conclusion": a.conclusion,
            },
            "metrics": {
                "accumulation_score": report.accumulation_score,
                "imbalance_score": report.imbalance_score,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "volume_profile_methodology.json"
            catalog.write_text(
                json.dumps(METHODOLOGY_PLAYBOOK, indent=2),
                encoding="utf-8",
            )
        return result


def run_dark_pool_volume_profile_analysis(
    output: Path | None = None,
    pipeline_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return DarkPoolVolumeProfileExpert(pipeline_context=pipeline_context).run(output=output)
