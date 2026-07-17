"""
Corporate Distress & Bankruptcy Analyst Agent
==============================================
Credit/special-situations analyst covering the financial distress spectrum
(operational friction -> going-concern doubt -> insolvency -> legal default),
liquidation-basis accounting (FASB ASC 205-30), the Altman Z-Score and Merton
Distance-to-Default quantitative distress models, and Chapter 11/Chapter 7
bankruptcy mechanics (automatic stay, DIP financing, cramdown, absolute
priority waterfall).

Data: Yahoo Finance chart API (1yr daily OHLCV) is used to compute a
market-implied distress proxy (realized asset volatility + drawdown/momentum
feeding a Merton-style Distance-to-Default) for a shared equity watchlist.
Real Altman Z-Score / Merton DD calculations require balance-sheet fundamentals
(retained earnings, EBIT, total assets/liabilities, face value of debt) that
are not available from the public chart API used here, so the per-symbol
scores are disclosed as calibrated, price-derived proxies rather than
audited financial-statement figures.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base import BaseExpert

BENCHMARK = "SPY"

# Shared watchlist used across the repo's market-microstructure agents.
WATCHLIST: dict[str, str] = {
    "SPY": "S&P 500 (broad market, low assumed leverage)",
    "AAPL": "Mega-cap tech (low-moderate assumed leverage)",
    "MSFT": "Mega-cap tech (low assumed leverage)",
    "QQQ": "Nasdaq 100 (broad market, low assumed leverage)",
    "IWM": "Russell 2000 (moderate assumed leverage)",
    "GME": "Retail-driven small/mid cap (higher assumed leverage)",
    "COIN": "Crypto-adjacent equity (higher assumed leverage)",
    "PLTR": "High-beta growth name (moderate assumed leverage)",
}

# Illustrative Debt/Asset-value ratios used purely to normalize the Merton
# Distance-to-Default proxy (D / V_A), since real face-value-of-debt figures
# aren't available from the chart API. These are disclosed assumptions, not
# fetched fundamentals.
ASSUMED_DEBT_TO_ASSET_RATIO: dict[str, float] = {
    "SPY": 0.25,
    "QQQ": 0.25,
    "MSFT": 0.30,
    "AAPL": 0.45,
    "IWM": 0.55,
    "PLTR": 0.35,
    "COIN": 0.50,
    "GME": 0.40,
}
DEFAULT_DEBT_TO_ASSET_RATIO = 0.45

MERTON_TIME_HORIZON_YEARS = 1.0
MERTON_DISTRESS_DD_THRESHOLD = 1.5
MERTON_GREY_DD_THRESHOLD = 3.0

# ---------------------------------------------------------------------------
# 1. The Financial Distress Spectrum & Early Warning Indicators
# ---------------------------------------------------------------------------
DISTRESS_PHASES: list[dict[str, Any]] = [
    {
        "phase": 1,
        "name": "Operational Friction",
        "subtitle": "The Incubation Stage",
        "macro_signals": [
            "Structural contraction in industry margins",
            "Technological displacement",
            "Loss of core customer cohorts",
        ],
        "micro_metrics": [
            "Deterioration of Asset Turnover (Sales / Total Assets)",
            "Sequential compression of Gross Margin",
            "Expansion of the Working Capital Cycle (DSO + DIO - DPO)",
        ],
        "capital_behavior": (
            "Management aggressively draws down revolving credit facilities to plug "
            "operational cash deficits; the firm shifts from generating organic free "
            "cash flow to burning capital."
        ),
    },
    {
        "phase": 2,
        "name": "Going-Concern Doubt",
        "subtitle": "The Technical Distress Stage",
        "trigger_conditions": (
            "Substantial doubt regarding the entity's capacity to fulfill its financial "
            "obligations as they fall due within one year from the financial statement "
            "issuance date."
        ),
        "governing_standards": ["AICPA AU-C Section 570", "FASB ASC 205-40"],
        "auditor_assessment_criteria": [
            "Negative trends (recurring operating losses, working capital deficiencies)",
            "Internal matters (work stoppages, uneconomic long-term commitments)",
            "External matters (loss of a principal license, franchise, or patent)",
        ],
        "management_remediation_mitigants": [
            "Borrow money",
            "Restructure debt",
            "Reduce or delay expenditures",
            "Dispose of operations",
        ],
    },
    {
        "phase": 3,
        "name": "Insolvency",
        "subtitle": "The Valuation Crossroads",
        "definitions": [
            {
                "type": "Equity/Cash-Flow Insolvency",
                "description": (
                    "The operational inability of an enterprise to pay its liabilities as "
                    "they mature in the ordinary course of business. A company can be "
                    "balance-sheet solvent (owning valuable non-cash assets) but equity "
                    "insolvent if it lacks immediate liquidity to meet payroll or clear "
                    "short-term accounts payable."
                ),
            },
            {
                "type": "Balance-Sheet Insolvency",
                "description": (
                    "A structural condition where the sum of the entity's debts is greater "
                    "than all of its property, at a fair valuation — a market valuation of "
                    "assets against the nominal face value of total liabilities."
                ),
            },
        ],
    },
    {
        "phase": 4,
        "name": "Legal Default",
        "subtitle": "The Legal Realization Stage",
        "default_types": [
            {
                "type": "Technical Default",
                "description": (
                    "Violation of affirmative or negative financial covenants (e.g., "
                    "crossing a maximum Debt/EBITDA ceiling or dropping below a minimum "
                    "Interest Coverage ratio)."
                ),
            },
            {
                "type": "Payment Default",
                "description": (
                    "The definitive, non-cure failure to make a contractually mandated "
                    "coupon payment, principal repayment, or trade vendor settlement — "
                    "unlocks immediate creditor acceleration and cross-defaults across the "
                    "entire capital stack."
                ),
            },
        ],
    },
]

# ---------------------------------------------------------------------------
# 2. Going-Concern Modifications & Liquidation Accounting (FASB ASC 205-30)
# ---------------------------------------------------------------------------
LIQUIDATION_ACCOUNTING_SHIFTS: list[dict[str, str]] = [
    {
        "id": "asset_measurement",
        "topic": "Asset Measurement",
        "going_concern_basis": "Historical amortized cost, depreciated over useful life.",
        "liquidation_basis": (
            "Written down to Net Realizable Value (NRV) — estimated cash from an "
            "expedited/orderly/forced sale, minus disposal costs."
        ),
    },
    {
        "id": "liability_classification",
        "topic": "Liability Acceleration",
        "going_concern_basis": "Current vs. Non-Current liabilities split by maturity.",
        "liquidation_basis": (
            "The current/non-current distinction disappears; all obligations accelerate "
            "to the current dollar amount legally required to extinguish the debt today."
        ),
    },
    {
        "id": "future_liquidation_costs",
        "topic": "Accrual of Future Liquidation Costs",
        "going_concern_basis": "Not accrued; entity assumed to operate indefinitely.",
        "liquidation_basis": (
            "Firm must accrue estimated wind-down costs: legal fees, restructuring "
            "advisor fees, court costs, asset storage, and employee severance."
        ),
    },
    {
        "id": "intangible_devaluation",
        "topic": "Intangible Devaluation",
        "going_concern_basis": "Goodwill/trademarks/brand equity/capitalized R&D carried at book value.",
        "liquidation_basis": (
            "Written down to zero unless there is a binding, third-party purchase "
            "agreement for those specific assets."
        ),
    },
]

# ---------------------------------------------------------------------------
# 3. Quantitative Risk Modeling Framework
# ---------------------------------------------------------------------------
ALTMAN_ZSCORE_MODEL: dict[str, Any] = {
    "name": "Altman Z-Score",
    "author": "Edward Altman",
    "formula": "Z = 1.2*X1 + 1.4*X2 + 3.3*X3 + 0.6*X4 + 0.999*X5",
    "horizon_months": 24,
    "sub_ratios": [
        {
            "id": "X1",
            "definition": "Working Capital / Total Assets = (Current Assets - Current Liabilities) / Total Assets",
            "measures": "Liquid asset strength relative to total institutional size",
        },
        {
            "id": "X2",
            "definition": "Retained Earnings / Total Assets",
            "measures": "Cumulative profitability over time (younger/highly leveraged firms score lower)",
        },
        {
            "id": "X3",
            "definition": "EBIT / Total Assets",
            "measures": "True productivity of firm assets, unadjusted for tax structure or leverage",
        },
        {
            "id": "X4",
            "definition": "Market Value of Equity / Total Liabilities = Market Capitalization / Total Liabilities",
            "measures": "Leverage capacity plus equity market sentiment on asset values",
        },
        {
            "id": "X5",
            "definition": "Sales / Total Assets",
            "measures": "Asset turnover efficiency and competitive capacity of management",
        },
    ],
    "zones": [
        {"zone": "Safe Zone", "condition": "Z > 2.99", "interpretation": "Robust financial health; negligible 24-month insolvency probability."},
        {"zone": "Grey Zone", "condition": "1.81 <= Z <= 2.99", "interpretation": "Moderate distress risk; requires monitoring, operational adjustments, or debt modification."},
        {"zone": "Distress Zone (Red)", "condition": "Z < 1.81", "interpretation": "Severe insolvency risk; high correlation with bankruptcy filing or out-of-court restructuring."},
    ],
}

MERTON_MODEL: dict[str, Any] = {
    "name": "Merton Structural Model (Distance-to-Default)",
    "basis": "Black-Scholes-Merton option pricing framework",
    "concept": (
        "Firm equity is treated as a European call option on the firm's asset value "
        "(V_A), struck at the face value of outstanding debt (D). If V_A < D at "
        "maturity T, equity holders walk away, equity value goes to $0, and control "
        "passes to creditors."
    ),
    "formula": "DD = (ln(V_A / D) + (mu - sigma_A^2 / 2) * T) / (sigma_A * sqrt(T))",
    "variables": {
        "V_A": "Current market value of the firm's total assets",
        "D": "Face value of the default threshold (typically short-term debt + 0.5 * long-term debt)",
        "mu": "Expected rate of return on firm assets",
        "sigma_A": "Volatility of the firm's asset value",
        "T": "Time horizon (typically modeled at 1.0 year)",
    },
    "distress_threshold": f"DD < {MERTON_DISTRESS_DD_THRESHOLD} indicates modest asset volatility will push asset value below debt obligations, resulting in default.",
}

# ---------------------------------------------------------------------------
# 4-5. Bankruptcy Mechanics (Chapter 11 reorganization, Chapter 7 liquidation)
# ---------------------------------------------------------------------------
CHAPTER11_MECHANICS: dict[str, Any] = {
    "automatic_stay": {
        "statute": "11 U.S.C. Section 362",
        "effect": (
            "Instantly halts all collection activities, foreclosure actions, asset "
            "seizures, and litigation against the debtor upon petition filing — stops "
            "the race to the assets."
        ),
    },
    "debtor_in_possession": {
        "statute": "DIP Governance",
        "effect": (
            "Existing management usually retains operational control; major corporate "
            "actions (asset sales, major lease modifications, executive compensation "
            "changes) require bankruptcy judge approval."
        ),
    },
    "dip_financing": {
        "statute": "11 U.S.C. Section 364",
        "effect": (
            "Can grant DIP lenders 'Super-Priority Claim' status, positioning repayment "
            "ahead of all pre-bankruptcy unsecured claims, and a 'Priming Lien' ahead of "
            "existing secured creditors."
        ),
    },
    "executory_contract_rejection": {
        "statute": "11 U.S.C. Section 365",
        "effect": (
            "Debtor may assume or reject executory contracts/unexpired leases; damages "
            "from rejection downgrade to a pre-petition General Unsecured Claim, often "
            "settled for pennies on the dollar."
        ),
    },
    "plan_confirmation": {
        "voting_threshold": "At least two-thirds in dollar amount and more than half in number of claims allowed within each class",
        "cramdown": {
            "statute": "11 U.S.C. Section 1129(b)",
            "requirements": [
                "Fair and Equitable — Absolute Priority Rule: no class below the dissenting class receives anything, no class above receives more than 100% of its claim.",
                "Not Unfairly Discriminatory — claims with similar legal characteristics must be treated equally within the plan.",
            ],
        },
    },
    "workflow": [
        "Distressed Firm",
        "Chapter 11 Filing",
        "Automatic Stay (Halts Collections) / DIP Financing (Super-Priority Loan)",
        "Debt Restructuring / Executory Leases",
        "Plan Confirmation (Creditor Vote)",
    ],
}

CHAPTER7_WATERFALL: list[dict[str, Any]] = [
    {
        "tier": 1,
        "classification": "Secured Claims",
        "detail": (
            "Claims backed by specific collateral (senior liens on PP&E). Any "
            "unpaid balance after liquidation proceeds downgrades to a Tier 4 "
            "General Unsecured Claim."
        ),
    },
    {
        "tier": 2,
        "classification": "Administrative Expenses",
        "detail": (
            "Post-petition fees: trustee compensation, court fees, legal costs, "
            "forensic accounting fees, and estate-preservation expenses."
        ),
    },
    {
        "tier": 3,
        "classification": "Priority Unsecured Claims",
        "detail": (
            "Unpaid pre-petition employee wages (capped per employee), employee "
            "benefit plan contributions, and standard unsecured tax obligations."
        ),
    },
    {
        "tier": 4,
        "classification": "General Unsecured Claims",
        "detail": "Trade credit, vendor payables, unsecured senior/subordinated bonds, consumer claims.",
    },
    {
        "tier": 5,
        "classification": "Preferred Stockholders",
        "detail": "Fixed dividend preference over common stock; paid only after Tiers 1-4 reach 100% recovery.",
    },
    {
        "tier": 6,
        "classification": "Common Stockholders",
        "detail": "Residual equity owners; typically canceled and written down to $0 once asset value is exhausted in Tier 4.",
    },
]

WORKOUT_VS_BANKRUPTCY: list[dict[str, str]] = [
    {
        "vector": "Direct & Indirect Costs",
        "out_of_court_workout": "Low to Moderate — avoids court fees, statutory trustee expenses, and lengthy public reporting.",
        "chapter_11": "High — substantial legal bills, turnaround consultant retainers, and court costs.",
    },
    {
        "vector": "Execution Speed",
        "out_of_court_workout": "Variable — rapid if creditors are concentrated, can stall on holdouts.",
        "chapter_11": "Structured — governed by statutory timelines, court schedules, voting periods.",
    },
    {
        "vector": "Public Visibility",
        "out_of_court_workout": "Confidential — private negotiations with management, board, major lenders.",
        "chapter_11": "Public Record — every filing, report, salary disclosure, strategic shift is on the docket.",
    },
    {
        "vector": "Creditor Consent Threshold",
        "out_of_court_workout": "Unanimous (typically) — near 100% lender approval to alter core payment terms outside court.",
        "chapter_11": "Statutory Majority — 2/3 dollar amount and >50% claim count per class; cramdown can force compliance.",
    },
    {
        "vector": "Contract / Lease Repudiation",
        "out_of_court_workout": "None — no unilateral mechanism to break uneconomic leases/contracts.",
        "chapter_11": "Statutory Right — Section 365 allows rejection, converting damages to low-priority unsecured claims.",
    },
    {
        "vector": "Operational Continuity Impact",
        "out_of_court_workout": "Minimal — avoids bankruptcy stigma, preserves trade credit and customer confidence.",
        "chapter_11": "Disruptive — can freeze supply chains, force cash-on-delivery terms, cause customer attrition.",
    },
]


@dataclass
class SymbolDistressProxy:
    symbol: str
    name: str
    last_close: float
    realized_vol_annualized_pct: float
    trailing_1y_drawdown_pct: float
    momentum_6m_pct: float
    assumed_debt_to_asset_ratio: float
    distance_to_default: float
    distress_zone: str
    rationale: str


@dataclass
class CorporateDistressReport:
    phases: list[dict[str, Any]]
    liquidation_accounting_shifts: list[dict[str, str]]
    altman_zscore_model: dict[str, Any]
    merton_model: dict[str, Any]
    chapter11_mechanics: dict[str, Any]
    chapter7_waterfall: list[dict[str, Any]]
    workout_vs_bankruptcy: list[dict[str, str]]
    symbols: list[SymbolDistressProxy]
    distress_zone_counts: dict[str, int]
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CorporateDistressExpert(BaseExpert):
    """Credit/special-situations analyst — distress spectrum & bankruptcy mechanics."""

    def __init__(
        self,
        *,
        pipeline_context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(pipeline_context=pipeline_context, agent_id="corporate-distress")
        self.delay_seconds = 0.35

    @staticmethod
    def _distress_zone(dd: float) -> str:
        if dd < MERTON_DISTRESS_DD_THRESHOLD:
            return "Distress Zone (Red)"
        if dd < MERTON_GREY_DD_THRESHOLD:
            return "Grey Zone"
        return "Safe Zone"

    def _analyze_symbol(self, symbol: str, name: str) -> SymbolDistressProxy | None:
        data = self.fetch_yahoo_ohlcv(symbol, range_="1y", interval="1d")
        closes = data.get("close", [])
        if len(closes) < 30:
            return None

        last_close = closes[-1]
        daily_returns = [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes))
            if closes[i - 1]
        ]
        if len(daily_returns) < 20:
            return None

        sigma_daily = statistics.stdev(daily_returns)
        sigma_annualized = sigma_daily * math.sqrt(252)
        mu_annualized = statistics.mean(daily_returns) * 252

        peak = closes[0]
        max_drawdown = 0.0
        for price in closes:
            peak = max(peak, price)
            if peak:
                max_drawdown = max(max_drawdown, (peak - price) / peak)

        window = min(len(closes), 126)
        momentum_6m_pct = (
            (closes[-1] - closes[-window]) / closes[-window] * 100 if closes[-window] else 0.0
        )

        debt_to_asset = ASSUMED_DEBT_TO_ASSET_RATIO.get(symbol, DEFAULT_DEBT_TO_ASSET_RATIO)
        # Normalize V_A = 1.0 so D = debt_to_asset ratio directly.
        v_a = 1.0
        d = max(debt_to_asset, 0.01)
        sigma_a = max(sigma_annualized, 0.01)
        dd = (
            math.log(v_a / d) + (mu_annualized - (sigma_a**2) / 2) * MERTON_TIME_HORIZON_YEARS
        ) / (sigma_a * math.sqrt(MERTON_TIME_HORIZON_YEARS))

        zone = self._distress_zone(dd)
        rationale = (
            f"Assumed D/V_A {debt_to_asset:.2f}, realized asset-vol proxy "
            f"{sigma_annualized * 100:.1f}% ann., drift proxy {mu_annualized * 100:.1f}% ann. "
            f"-> Distance-to-Default {dd:.2f} ({zone})."
        )

        return SymbolDistressProxy(
            symbol=symbol,
            name=name,
            last_close=round(last_close, 2),
            realized_vol_annualized_pct=round(sigma_annualized * 100, 2),
            trailing_1y_drawdown_pct=round(max_drawdown * 100, 2),
            momentum_6m_pct=round(momentum_6m_pct, 2),
            assumed_debt_to_asset_ratio=debt_to_asset,
            distance_to_default=round(dd, 2),
            distress_zone=zone,
            rationale=rationale,
        )

    def _market_signals(self, symbols: list[SymbolDistressProxy]) -> list[dict[str, Any]]:
        from agent_signal_logic import build_market_signal

        signals: list[dict[str, Any]] = []

        def _keep(symbol: str) -> bool:
            return not self.pipeline_should_skip_symbol(symbol)

        distressed = [s for s in symbols if s.distress_zone == "Distress Zone (Red)" and _keep(s.symbol)]
        if distressed:
            signals.append(
                build_market_signal(
                    sector="Corporate Distress",
                    tickers=[s.symbol for s in distressed],
                    bias="BEARISH",
                    reason=(
                        "Merton Distance-to-Default proxy below "
                        f"{MERTON_DISTRESS_DD_THRESHOLD:.1f} — elevated market-implied default risk."
                    ),
                    confidence=self.adjust_signal_confidence(
                        distressed[0].symbol, "BEARISH", 0.55
                    ),
                    evidence={
                        "distance_to_default": {s.symbol: s.distance_to_default for s in distressed},
                    },
                )
            )

        grey = [s for s in symbols if s.distress_zone == "Grey Zone" and _keep(s.symbol)]
        if grey:
            signals.append(
                build_market_signal(
                    sector="Corporate Distress",
                    tickers=[s.symbol for s in grey],
                    bias="NEUTRAL",
                    reason="Grey-zone Distance-to-Default — monitor for deterioration.",
                    confidence=self.adjust_signal_confidence(grey[0].symbol, "NEUTRAL", 0.45),
                    evidence={"distance_to_default": {s.symbol: s.distance_to_default for s in grey}},
                )
            )

        safe = [s for s in symbols if s.distress_zone == "Safe Zone" and _keep(s.symbol)]
        if safe:
            signals.append(
                build_market_signal(
                    sector="Corporate Distress",
                    tickers=[s.symbol for s in safe],
                    bias="BULLISH",
                    reason="Safe-zone Distance-to-Default — negligible market-implied default risk.",
                    confidence=self.adjust_signal_confidence(safe[0].symbol, "BULLISH", 0.5),
                    evidence={"distance_to_default": {s.symbol: s.distance_to_default for s in safe}},
                )
            )
        return signals

    def _recommendations(self, symbols: list[SymbolDistressProxy]) -> list[str]:
        recs = [
            "Distress spectrum: Operational Friction -> Going-Concern Doubt -> Insolvency -> Legal Default.",
            f"Altman Z-Score zones: Safe > 2.99, Grey 1.81-2.99, Distress < 1.81 (real Z requires audited fundamentals).",
            f"Merton Distance-to-Default distress threshold: DD < {MERTON_DISTRESS_DD_THRESHOLD:.1f}.",
        ]
        for s in sorted(symbols, key=lambda x: x.distance_to_default):
            recs.append(
                f"{s.symbol} ({s.name}): DD {s.distance_to_default:.2f} — {s.distress_zone}. {s.rationale}"
            )
        return recs

    def analyze(self) -> CorporateDistressReport:
        symbols: list[SymbolDistressProxy] = []
        for symbol, name in WATCHLIST.items():
            row = self._analyze_symbol(symbol, name)
            if row:
                symbols.append(row)

        if not any(s.symbol == BENCHMARK for s in symbols):
            raise RuntimeError("Unable to fetch SPY data for corporate distress analysis")

        distress_zone_counts: dict[str, int] = {}
        for s in symbols:
            distress_zone_counts[s.distress_zone] = distress_zone_counts.get(s.distress_zone, 0) + 1

        distressed_count = distress_zone_counts.get("Distress Zone (Red)", 0)
        summary = (
            f"Corporate distress scan across {len(symbols)} symbols: "
            f"{distressed_count} in the Distress Zone, "
            f"{distress_zone_counts.get('Grey Zone', 0)} in the Grey Zone, "
            f"{distress_zone_counts.get('Safe Zone', 0)} in the Safe Zone "
            "(market-implied Distance-to-Default proxy)."
        )

        signals = self._market_signals(symbols)
        recs = self._recommendations(symbols)

        return CorporateDistressReport(
            phases=DISTRESS_PHASES,
            liquidation_accounting_shifts=LIQUIDATION_ACCOUNTING_SHIFTS,
            altman_zscore_model=ALTMAN_ZSCORE_MODEL,
            merton_model=MERTON_MODEL,
            chapter11_mechanics=CHAPTER11_MECHANICS,
            chapter7_waterfall=CHAPTER7_WATERFALL,
            workout_vs_bankruptcy=WORKOUT_VS_BANKRUPTCY,
            symbols=symbols,
            distress_zone_counts=distress_zone_counts,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source="Yahoo Finance Chart API (1yr daily OHLCV) — market-implied distress proxy",
        )

    def to_dict(self, report: CorporateDistressReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Corporate Distress & Bankruptcy Analyst",
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
            "distress_spectrum": report.phases,
            "liquidation_accounting": report.liquidation_accounting_shifts,
            "altman_zscore_model": report.altman_zscore_model,
            "merton_model": report.merton_model,
            "chapter11_mechanics": report.chapter11_mechanics,
            "chapter7_waterfall": report.chapter7_waterfall,
            "workout_vs_bankruptcy": report.workout_vs_bankruptcy,
            "symbol_distress_proxy": [
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "last_close": s.last_close,
                    "realized_vol_annualized_pct": s.realized_vol_annualized_pct,
                    "trailing_1y_drawdown_pct": s.trailing_1y_drawdown_pct,
                    "momentum_6m_pct": s.momentum_6m_pct,
                    "assumed_debt_to_asset_ratio": s.assumed_debt_to_asset_ratio,
                    "distance_to_default": s.distance_to_default,
                    "distress_zone": s.distress_zone,
                    "rationale": s.rationale,
                }
                for s in report.symbols
            ],
            "distress_zone_counts": report.distress_zone_counts,
            "market_signals": report.market_signals,
            "recommendations": self.append_memory_recommendations(report.recommendations),
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        report = self.analyze()
        result = self.to_dict(report)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            catalog = output.parent / "distress_bankruptcy_playbook.json"
            catalog.write_text(
                json.dumps(
                    {
                        "distress_spectrum": report.phases,
                        "liquidation_accounting": report.liquidation_accounting_shifts,
                        "altman_zscore_model": report.altman_zscore_model,
                        "merton_model": report.merton_model,
                        "chapter11_mechanics": report.chapter11_mechanics,
                        "chapter7_waterfall": report.chapter7_waterfall,
                        "workout_vs_bankruptcy": report.workout_vs_bankruptcy,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        return result


def run_corporate_distress_analysis(
    output: Path | None = None,
    pipeline_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return CorporateDistressExpert(pipeline_context=pipeline_context).run(output=output)
