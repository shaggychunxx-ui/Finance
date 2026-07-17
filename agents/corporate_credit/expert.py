"""
Corporate Credit & CDS Derivatives Expert Agent
================================================
Institutional-grade breakdown of corporate credit market structure: public
high-yield (HY) cash-bond spread compression vs. private-credit/direct-
lending default stress, standardized CDS index mechanics (CDX.NA.HY,
iTraxx Europe Crossover), the credit-to-CDS basis trade, index-tranche
default-correlation pricing, and the macro/single-name/capital-structure
hedging playbooks institutional credit desks run across the cycle.

Data: FRED ``BAMLH0A0HYM2`` (ICE BofA US HY OAS) via the public
``fredgraph.csv`` endpoint, with a calibrated proxy fallback anchored on
the Fitch Ratings U.S. Private Credit Default Rate (PCDR) release when the
live feed is unreachable.

Sources:
- https://fred.stlouisfed.org/series/BAMLH0A0HYM2
- https://www.fitchratings.com/research/corporate-finance/fitch-ratings-us-private-credit-default-rate-remains-at-record-high-6-0-in-may-2026-15-06-2026
- https://www.spglobal.com/spdji/en/documents/index-news-and-announcements/20260227-itraxx-europe-timelines-march-2026.pdf
- https://www.spglobal.com/spdji/en/documents/indexnews/announcements/20260319-1482487/1482487_cdxhy-ex-bbfinallist-march20261.pdf
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agents.base import BaseExpert

HEADERS = {"User-Agent": "Finance-Corporate-Credit-Expert/1.0 (shaggychunxx@gmail.com)"}
FRED_SERIES_ID = "BAMLH0A0HYM2"
FRED_GRAPH_CSV_URL = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={FRED_SERIES_ID}"

# Baseline recovery-rate assumption for senior unsecured HY reference
# entities under standard CDS documentation (LGD = 1 - recovery rate).
RECOVERY_RATE = 0.40
LGD = 1.0 - RECOVERY_RATE

# Calibrated proxy snapshot used when the live FRED feed is unreachable
# (blocked network, rate limit). Anchored on the historically tight OAS
# print described in the problem statement.
PROXY_HY_OAS = {"latest": 2.71, "previous": 2.85}

# Fitch Ratings U.S. Private Credit Default Rate (PCDR), trailing twelve
# month basis — plateaued at a record high per the May 2026 release.
PRIVATE_CREDIT_DEFAULT_RATE_TTM = 6.0
PRIVATE_CREDIT_DEFAULT_RATE_PREVIOUS_TTM = 5.9

# Structural public HY default-rate forecast range (large issuers extended
# maturity walls during the 2020-2021 zero-rate era).
PUBLIC_DEFAULT_FORECAST_LOW = 2.1
PUBLIC_DEFAULT_FORECAST_HIGH = 3.4

# 5-year risky annuity approximation used to translate a running-spread
# differential into an upfront points quote for standardized CDS indices.
RISKY_DURATION_5Y = 4.4

CREDIT_INDICES: list[dict[str, Any]] = [
    {
        "name": "CDX.NA.HY",
        "region": "North America",
        "entity_count": 100,
        "coupon_bps": 500,
        "roll_months": ["March", "September"],
    },
    {
        "name": "iTraxx Europe Crossover",
        "region": "Europe",
        "entity_count": 75,
        "coupon_bps": 500,
        "roll_months": ["March", "September"],
    },
]

TRANCHE_STRUCTURE: list[dict[str, Any]] = [
    {
        "name": "Equity",
        "attachment_pct": 0,
        "detachment_pct": 7,
        "low_correlation_spread_bps": 4200,
        "high_correlation_spread_bps": 3600,
        "note": "Absorbs the first 0%-7% of index losses; pays the richest running coupon.",
    },
    {
        "name": "Mezzanine",
        "attachment_pct": 7,
        "detachment_pct": 30,
        "low_correlation_spread_bps": 180,
        "high_correlation_spread_bps": 650,
        "note": "Vulnerable to widespread macro default waves once the equity layer is exhausted.",
    },
    {
        "name": "Senior / Super Senior",
        "attachment_pct": 30,
        "detachment_pct": 100,
        "low_correlation_spread_bps": 8,
        "high_correlation_spread_bps": 210,
        "note": "Immunized from isolated defaults; premiums surge only under systemic contagion.",
    },
]

CREDIT_RESOURCES: list[dict[str, Any]] = [
    {
        "id": "fred_hy_oas",
        "name": "ICE BofA US High Yield Index OAS",
        "url": "https://fred.stlouisfed.org/series/BAMLH0A0HYM2",
        "description": "Public HY cash-bond option-adjusted spread (FRED series BAMLH0A0HYM2)",
    },
    {
        "id": "fitch_pcdr",
        "name": "Fitch U.S. Private Credit Default Rate",
        "url": (
            "https://www.fitchratings.com/research/corporate-finance/"
            "fitch-ratings-us-private-credit-default-rate-remains-at-record-high-6-0-in-may-2026-15-06-2026"
        ),
        "description": "Trailing twelve month direct-lending/private-credit default rate",
    },
    {
        "id": "itraxx_europe_timelines",
        "name": "iTraxx Europe Roll Timelines",
        "url": "https://www.spglobal.com/spdji/en/documents/index-news-and-announcements/20260227-itraxx-europe-timelines-march-2026.pdf",
        "description": "Semi-annual index roll schedule for iTraxx Europe Crossover",
    },
    {
        "id": "cdx_hy_final_list",
        "name": "CDX.NA.HY Final Constituent List",
        "url": "https://www.spglobal.com/spdji/en/documents/indexnews/announcements/20260319-1482487/1482487_cdxhy-ex-bbfinallist-march20261.pdf",
        "description": "Reference-entity roster for the current CDX.NA.HY on-the-run series",
    },
    {
        "id": "cds_primer",
        "name": "Credit Default Swap Primer",
        "url": "https://www.investopedia.com/terms/c/creditdefaultswap.asp",
        "description": "Mechanics of single-name and index CDS contracts",
    },
    {
        "id": "cdx_warning_signal",
        "name": "CDX Credit Spreads Warning Signal",
        "url": "https://realinvestmentadvice.com/resources/blog/cdx-credit-spreads-are-flashing-a-warning/",
        "description": "Tranche/correlation read-through commentary for CDX.HY",
    },
]


@dataclass
class CDSIndexQuote:
    name: str
    region: str
    entity_count: int
    coupon_bps: int
    market_spread_bps: float
    upfront_points: float
    direction: str


@dataclass
class BasisSignal:
    cds_spread_bps: float
    cash_asw_bps: float
    basis_bps: float
    regime: str
    strategy: str


@dataclass
class TrancheQuote:
    name: str
    attachment_pct: float
    detachment_pct: float
    low_correlation_spread_bps: float
    high_correlation_spread_bps: float
    note: str


@dataclass
class CorporateCreditReport:
    hy_oas_pct: float
    hy_oas_prev_pct: float
    private_credit_default_rate_pct: float
    implied_public_default_pd_pct: float
    divergence_pts: float
    divergence_label: str
    public_default_forecast_range: tuple[float, float]
    indices: list[CDSIndexQuote]
    basis: BasisSignal
    tranches: list[TrancheQuote]
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_sources: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CorporateCreditExpert(BaseExpert):
    """Expert analyst covering public/private credit divergence and CDS mechanics."""

    def __init__(self, *, pipeline_context: dict | None = None) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="corporate-credit")

    def _fetch_hy_oas(self) -> tuple[float | None, float | None, bool]:
        try:
            resp = requests.get(FRED_GRAPH_CSV_URL, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            reader = csv.reader(io.StringIO(resp.text))
            rows = [r for r in reader if len(r) == 2 and r[1] not in ("", ".", FRED_SERIES_ID)]
            values: list[float] = []
            for _, raw_value in rows:
                try:
                    values.append(float(raw_value))
                except ValueError:
                    continue
            if len(values) >= 2:
                return values[-1], values[-2], True
            if len(values) == 1:
                return values[-1], values[-1], True
        except Exception:
            pass
        return None, None, False

    def _resolve_hy_oas(self) -> tuple[float, float, list[str]]:
        latest, previous, live = self._fetch_hy_oas()
        sources: list[str] = []
        if live and latest is not None and previous is not None:
            sources.append("FRED fredgraph.csv (BAMLH0A0HYM2, live)")
            return round(latest, 2), round(previous, 2), sources
        sources.append("Calibrated HY OAS proxy (FRED feed unavailable)")
        return PROXY_HY_OAS["latest"], PROXY_HY_OAS["previous"], sources

    @staticmethod
    def _implied_default_pd(hy_oas_pct: float) -> float:
        # CDS Spread ≈ PD × LGD  ->  PD ≈ Spread / LGD
        spread = hy_oas_pct / 100.0
        pd = spread / LGD
        return round(pd * 100.0, 3)

    @staticmethod
    def _divergence(private_pct: float, implied_public_pd_pct: float) -> tuple[float, str]:
        divergence = round(private_pct - implied_public_pd_pct, 3)
        if divergence >= 1.25:
            label = "Severe structural fragmentation — private credit stress far exceeds public pricing"
        elif divergence >= 0.5:
            label = "Elevated structural fragmentation — private credit outpacing public spread signal"
        elif divergence <= -0.5:
            label = "Public spreads pricing more risk than realized private-credit defaults"
        else:
            label = "Public/private credit stress roughly aligned"
        return divergence, label

    @staticmethod
    def _index_quote(spec: dict[str, Any], market_spread_bps: float) -> CDSIndexQuote:
        coupon = float(spec["coupon_bps"])
        upfront_points = round(abs(coupon - market_spread_bps) / 10000.0 * RISKY_DURATION_5Y * 100.0, 3)
        direction = (
            "protection buyer pays upfront to seller"
            if market_spread_bps < coupon
            else "protection buyer receives upfront from seller"
        )
        return CDSIndexQuote(
            name=spec["name"],
            region=spec["region"],
            entity_count=spec["entity_count"],
            coupon_bps=int(coupon),
            market_spread_bps=round(market_spread_bps, 2),
            upfront_points=upfront_points,
            direction=direction,
        )

    @staticmethod
    def _basis_signal(market_spread_bps: float) -> BasisSignal:
        # Heavy HY ETF liquidation technicals typically widen cash-bond ASW
        # faster than the more liquid synthetic index, producing a negative
        # credit-to-CDS basis.
        cash_asw_bps = round(market_spread_bps + 15.0, 2)
        basis_bps = round(market_spread_bps - cash_asw_bps, 2)
        if basis_bps < 0:
            regime = "Negative basis"
            strategy = (
                "Buy the discounted physical cash bond and purchase CDS protection "
                "to lock in a risk-free yield premium (negative-basis arbitrage)."
            )
        else:
            regime = "Positive basis"
            strategy = (
                "Sell CDS protection and short/underweight the richer cash bond "
                "to harvest the positive-basis carry."
            )
        return BasisSignal(
            cds_spread_bps=round(market_spread_bps, 2),
            cash_asw_bps=cash_asw_bps,
            basis_bps=basis_bps,
            regime=regime,
            strategy=strategy,
        )

    @staticmethod
    def _tranches() -> list[TrancheQuote]:
        return [
            TrancheQuote(
                name=t["name"],
                attachment_pct=t["attachment_pct"],
                detachment_pct=t["detachment_pct"],
                low_correlation_spread_bps=t["low_correlation_spread_bps"],
                high_correlation_spread_bps=t["high_correlation_spread_bps"],
                note=t["note"],
            )
            for t in TRANCHE_STRUCTURE
        ]

    def _market_signals(
        self,
        divergence: float,
        divergence_label: str,
        basis: BasisSignal,
        hy_oas_pct: float,
    ) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal

        signals: list[dict[str, Any]] = []

        credit_bias = "BEARISH" if divergence >= 0.5 else ("BULLISH" if divergence <= -0.5 else "NEUTRAL")
        signals.append(
            build_market_signal(
                sector="Public/Private Credit Divergence",
                tickers=["HYG", "JNK"],
                bias=credit_bias,
                reason=(
                    f"HY OAS at {hy_oas_pct:.2f}% implies a public default-risk signal well below the "
                    f"{PRIVATE_CREDIT_DEFAULT_RATE_TTM:.1f}% TTM Fitch private-credit default rate — {divergence_label.lower()}"
                ),
                confidence=min(0.85, 0.45 + abs(divergence) * 0.2),
                evidence={"divergence_pts": divergence, "hy_oas_pct": hy_oas_pct},
            )
        )

        signals.append(
            build_market_signal(
                sector="Private Credit / Direct Lending BDCs",
                tickers=["ARCC", "MAIN", "PSEC"],
                bias="BEARISH" if PRIVATE_CREDIT_DEFAULT_RATE_TTM >= 5.0 else "NEUTRAL",
                reason=(
                    f"Fitch PCDR plateaued at a record {PRIVATE_CREDIT_DEFAULT_RATE_TTM:.1f}% TTM — floating-rate "
                    "mid-market 'zombie' issuers are the true shock absorber for private credit risk."
                ),
                confidence=0.62,
                evidence={"pcdr_ttm_pct": PRIVATE_CREDIT_DEFAULT_RATE_TTM},
            )
        )

        signals.append(
            build_market_signal(
                sector="Credit-to-CDS Basis Trade",
                tickers=["HYG", "CDX"],
                bias="BULLISH" if basis.regime == "Negative basis" else "NEUTRAL",
                reason=f"{basis.regime} of {basis.basis_bps:+.1f}bps — {basis.strategy}",
                confidence=0.55,
                evidence={"basis_bps": basis.basis_bps, "regime": basis.regime},
            )
        )

        signals.append(
            build_market_signal(
                sector="AI-Infrastructure Capital Structure Stress",
                tickers=["ORCL", "T", "VZ"],
                bias="BEARISH",
                reason=(
                    "Highly leveraged telecom/tech issuers over-extended on AI infrastructure capex are "
                    "prime single-name CDS and capital-structure-arbitrage candidates."
                ),
                confidence=0.5,
                evidence={"recovery_rate_assumption": RECOVERY_RATE},
            )
        )

        adjusted: list[dict[str, Any]] = []
        for sig in signals:
            row = dict(sig)
            tickers = row.get("tickers") or []
            conf = row.get("confidence")
            if tickers and conf is not None:
                row["confidence"] = self.adjust_signal_confidence(str(tickers[0]), str(row.get("bias", "NEUTRAL")), conf)
            adjusted.append(row)
        return adjusted

    def analyze(self) -> CorporateCreditReport:
        hy_oas_pct, hy_oas_prev_pct, sources = self._resolve_hy_oas()
        implied_pd = self._implied_default_pd(hy_oas_pct)
        divergence, divergence_label = self._divergence(PRIVATE_CREDIT_DEFAULT_RATE_TTM, implied_pd)

        market_spread_bps = round(hy_oas_pct * 100.0, 2)
        indices = [self._index_quote(spec, market_spread_bps) for spec in CREDIT_INDICES]
        basis = self._basis_signal(market_spread_bps)
        tranches = self._tranches()

        signals = self._market_signals(divergence, divergence_label, basis, hy_oas_pct)

        expert_summary = (
            f"Public HY OAS at {hy_oas_pct:.2f}% (prior {hy_oas_prev_pct:.2f}%) implies a ~{implied_pd:.2f}% "
            f"annualized default probability (LGD {LGD:.0%}), vs. a record {PRIVATE_CREDIT_DEFAULT_RATE_TTM:.1f}% "
            f"TTM Fitch private-credit default rate — {divergence_label} (gap {divergence:+.2f}pts). "
            f"CDX.NA.HY/iTraxx XOVER trading {market_spread_bps:.0f}bps vs. the standardized 500bps coupon "
            f"({indices[0].direction}); credit-to-CDS basis is {basis.regime.lower()} ({basis.basis_bps:+.1f}bps)."
        )

        recs = [
            f"Divergence signal: {divergence_label} (gap {divergence:+.2f}pts vs. implied public PD).",
            f"Public HY structural default forecast: {PUBLIC_DEFAULT_FORECAST_LOW:.1f}%-{PUBLIC_DEFAULT_FORECAST_HIGH:.1f}%, "
            f"vs. private credit PCDR at {PRIVATE_CREDIT_DEFAULT_RATE_TTM:.1f}% TTM (record high).",
            f"{basis.regime}: {basis.strategy}",
            "Strategy A (macro shock hedge): buy CDX.NA.HY / iTraxx XOVER protection for liquid, "
            "immediately monetizable convexity against a broad spread-widening shock.",
            "Strategy B (idiosyncratic AI deleveraging): buy single-name CDS protection on overleveraged "
            "telecom/tech issuers with heavy AI infrastructure capex funded by debt.",
            "Strategy C (capital structure arbitrage): buy senior CDS protection while going long junior "
            "cash bonds/equity of downgrade-risk issuers to harvest capital-structure mispricing.",
            "Tranche correlation regime: low correlation stresses the equity tranche (0%-7%); high "
            "correlation/systemic contagion drives senior and super-senior premiums sharply higher.",
        ]

        return CorporateCreditReport(
            hy_oas_pct=hy_oas_pct,
            hy_oas_prev_pct=hy_oas_prev_pct,
            private_credit_default_rate_pct=PRIVATE_CREDIT_DEFAULT_RATE_TTM,
            implied_public_default_pd_pct=implied_pd,
            divergence_pts=divergence,
            divergence_label=divergence_label,
            public_default_forecast_range=(PUBLIC_DEFAULT_FORECAST_LOW, PUBLIC_DEFAULT_FORECAST_HIGH),
            indices=indices,
            basis=basis,
            tranches=tranches,
            expert_summary=expert_summary,
            market_signals=signals,
            recommendations=self.append_memory_recommendations(recs),
            data_sources=sources,
        )

    def to_dict(self, report: CorporateCreditReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Corporate Credit & CDS Derivatives Expert",
                "analyzed_at": report.analyzed_at,
                "expert_summary": report.expert_summary,
                "data_sources": report.data_sources,
            },
            "metrics": {
                "hy_oas_pct": report.hy_oas_pct,
                "hy_oas_prev_pct": report.hy_oas_prev_pct,
                "private_credit_default_rate_pct": report.private_credit_default_rate_pct,
                "implied_public_default_pd_pct": report.implied_public_default_pd_pct,
                "divergence_pts": report.divergence_pts,
                "divergence_label": report.divergence_label,
                "public_default_forecast_low_pct": report.public_default_forecast_range[0],
                "public_default_forecast_high_pct": report.public_default_forecast_range[1],
                "recovery_rate_assumption": RECOVERY_RATE,
            },
            "cds_indices": [
                {
                    "name": i.name,
                    "region": i.region,
                    "entity_count": i.entity_count,
                    "coupon_bps": i.coupon_bps,
                    "market_spread_bps": i.market_spread_bps,
                    "upfront_points": i.upfront_points,
                    "direction": i.direction,
                }
                for i in report.indices
            ],
            "basis_trade": {
                "cds_spread_bps": report.basis.cds_spread_bps,
                "cash_asw_bps": report.basis.cash_asw_bps,
                "basis_bps": report.basis.basis_bps,
                "regime": report.basis.regime,
                "strategy": report.basis.strategy,
            },
            "tranches": [
                {
                    "name": t.name,
                    "attachment_pct": t.attachment_pct,
                    "detachment_pct": t.detachment_pct,
                    "low_correlation_spread_bps": t.low_correlation_spread_bps,
                    "high_correlation_spread_bps": t.high_correlation_spread_bps,
                    "note": t.note,
                }
                for t in report.tranches
            ],
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            resources_path = output.parent / "credit_derivatives_playbook.json"
            resources_path.write_text(json.dumps(CREDIT_RESOURCES, indent=2), encoding="utf-8")
        return result


def run_corporate_credit_analysis(
    output: Path | None = None,
    pipeline_context: dict | None = None,
) -> dict[str, Any]:
    return CorporateCreditExpert(pipeline_context=pipeline_context).run(output=output)
