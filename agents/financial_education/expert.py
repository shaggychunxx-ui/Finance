"""
Financial Education Expert Agent
=================================
Personal-finance educator agent that studies the core curriculum popularized
by Khan Academy's Economics & Personal Finance courses (https://www.khanacademy.org/)
— compound interest, dollar-cost averaging vs. lump-sum investing,
diversification, age-based risk/asset-allocation rules, debt payoff
strategies, and the retirement-account contribution ladder — and implements
those lessons as live, data-driven analysis against current market data.

Khan Academy content is not scraped; the curriculum below is a short,
original restatement of widely-taught personal-finance concepts used as a
teaching reference, applied here with real Yahoo Finance market data.

Data: Yahoo Finance chart API (1-year daily history).
"""

from __future__ import annotations

import json
import math
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agents.base import BaseExpert

CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Finance-Financial-Education/1.0 (shaggychunxx@gmail.com)"}

BENCHMARK = "SPY"
WATCHLIST = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "IWM": "Russell 2000",
    "^VIX": "VIX",
    "XLK": "Technology",
    "XLE": "Energy",
    "XLU": "Utilities",
    "XLF": "Financials",
    "GLD": "Gold",
    "TLT": "Treasuries",
}

KHAN_ACADEMY_URL = "https://www.khanacademy.org/economics-finance-domain/core-finance"

CURRICULUM: list[dict[str, Any]] = [
    {
        "id": "compound_interest",
        "name": "Interest and Debt: Compound Interest",
        "description": "Money grows exponentially when returns compound over time — starting early beats contributing more later.",
        "formula": "FV = P(1+r)^n + PMT · [((1+r)^n - 1) / r]",
    },
    {
        "id": "dollar_cost_averaging",
        "name": "Investment Vehicles: Dollar-Cost Averaging",
        "description": "Investing a fixed amount on a regular schedule smooths entry price versus timing a single lump sum.",
        "formula": "avg_cost = Σ(amount_t) / Σ(amount_t / price_t)",
    },
    {
        "id": "diversification",
        "name": "Investment Vehicles: Diversification",
        "description": "Combining assets with low or negative correlation reduces portfolio volatility for the same expected return.",
        "formula": "σ_portfolio² = Σ w_i²σ_i² + ΣΣ w_iw_jσ_iσ_jρ_ij",
    },
    {
        "id": "risk_and_time_horizon",
        "name": "Retirement Plans: Risk & Time Horizon",
        "description": "Longer time horizons can absorb more volatility, so stock/bond allocation is commonly scaled by age.",
        "formula": "stock_alloc_pct ≈ 110 − age",
    },
    {
        "id": "debt_payoff_strategy",
        "name": "Interest and Debt: Avalanche vs. Snowball",
        "description": "Avalanche (highest interest rate first) minimizes total interest paid; snowball (smallest balance first) maximizes psychological momentum.",
        "formula": "total_interest = Σ balance_i · rate_i · time_i",
    },
    {
        "id": "retirement_contribution_ladder",
        "name": "Retirement Plans: Contribution Priority Ladder",
        "description": "A common priority order: emergency fund → employer 401(k) match → HSA → Roth/Traditional IRA → max 401(k) → taxable brokerage.",
        "formula": "priority(account) = employer_match_bonus − tax_drag − liquidity_need",
    },
    {
        "id": "budgeting_emergency_fund",
        "name": "Preparing a Budget: Emergency Fund",
        "description": "A cash buffer of 3-6 months of expenses prevents forced selling of investments during income disruption or market stress.",
        "formula": "target_fund = monthly_expenses × months_buffer",
    },
]


@dataclass
class CompoundInterestProjection:
    scenario: str
    principal: float
    monthly_contribution: float
    annual_rate_pct: float
    years: int
    future_value: float
    total_contributions: float
    total_growth: float


@dataclass
class DollarCostAveragingResult:
    symbol: str
    months_observed: int
    lump_sum_return_pct: float
    dca_return_pct: float
    better_strategy: str
    note: str


@dataclass
class DiversificationPair:
    pair: str
    correlation: float
    label: str


@dataclass
class RiskProfileStep:
    age_example: int
    stock_allocation_pct: float
    bond_allocation_pct: float
    rule: str
    note: str


@dataclass
class DebtPayoffPlan:
    strategy: str
    order: list[str]
    total_interest_paid: float
    months_to_payoff: int
    note: str


@dataclass
class RetirementPriorityStep:
    step: int
    action: str
    rationale: str


@dataclass
class EducationAssessment:
    compounding_takeaway: str
    dca_takeaway: str
    diversification_takeaway: str
    risk_horizon_takeaway: str


@dataclass
class FinancialEducationReport:
    compound_projections: list[CompoundInterestProjection]
    dca_results: list[DollarCostAveragingResult]
    diversification: list[DiversificationPair]
    avg_correlation: float
    diversification_label: str
    risk_profiles: list[RiskProfileStep]
    debt_plans: list[DebtPayoffPlan]
    retirement_ladder: list[RetirementPriorityStep]
    assessment: EducationAssessment
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FinancialEducationExpert(BaseExpert):
    """Applies core Khan Academy personal-finance lessons to live market data."""

    def __init__(self, delay_seconds: float = 0.3) -> None:
        super().__init__()
        self.delay_seconds = delay_seconds

    def _fetch_closes(self, symbol: str) -> list[float]:
        try:
            resp = requests.get(
                CHART_API.format(symbol=symbol),
                params={"interval": "1d", "range": "1y"},
                headers=HEADERS,
                timeout=25,
            )
            if resp.status_code == 429:
                time.sleep(3)
                resp = requests.get(
                    CHART_API.format(symbol=symbol),
                    params={"interval": "1d", "range": "1y"},
                    headers=HEADERS,
                    timeout=25,
                )
            resp.raise_for_status()
            closes = resp.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            return [float(c) for c in closes if c is not None]
        except Exception:
            return []

    @staticmethod
    def _daily_returns(closes: list[float]) -> list[float]:
        return [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]

    @staticmethod
    def _annualized_return(returns: list[float]) -> float:
        if not returns:
            return 0.07
        mean_daily = statistics.mean(returns)
        return (1 + mean_daily) ** 252 - 1

    def _compound_interest_projections(self, market_cagr: float) -> list[CompoundInterestProjection]:
        principal = 1000.0
        monthly_contribution = 200.0
        clamped_market_rate = max(0.02, min(market_cagr, 0.20))
        rates = {
            "conservative (5%)": 0.05,
            f"market-implied SPY CAGR ({clamped_market_rate * 100:.1f}%)": clamped_market_rate,
            "aggressive (10%)": 0.10,
        }
        projections: list[CompoundInterestProjection] = []
        for scenario, annual_rate in rates.items():
            for years in (10, 20, 30):
                monthly_rate = annual_rate / 12
                n = years * 12
                fv_principal = principal * (1 + monthly_rate) ** n
                if monthly_rate > 0:
                    fv_contrib = monthly_contribution * (((1 + monthly_rate) ** n - 1) / monthly_rate)
                else:
                    fv_contrib = monthly_contribution * n
                future_value = fv_principal + fv_contrib
                total_contributions = principal + monthly_contribution * n
                projections.append(CompoundInterestProjection(
                    scenario=scenario,
                    principal=principal,
                    monthly_contribution=monthly_contribution,
                    annual_rate_pct=round(annual_rate * 100, 2),
                    years=years,
                    future_value=round(future_value, 2),
                    total_contributions=round(total_contributions, 2),
                    total_growth=round(future_value - total_contributions, 2),
                ))
        return projections

    @staticmethod
    def _dollar_cost_average(symbol: str, closes: list[float]) -> DollarCostAveragingResult | None:
        if len(closes) < 40:
            return None
        # Sample ~monthly closes over the trailing year (roughly 21 trading days/month).
        monthly_closes = closes[::21] if len(closes) >= 21 else closes
        if len(monthly_closes) < 2:
            return None

        lump_sum_return = (closes[-1] - monthly_closes[0]) / monthly_closes[0]

        amount_per_month = 100.0
        shares_bought = sum(amount_per_month / price for price in monthly_closes if price)
        total_invested = amount_per_month * len(monthly_closes)
        final_value = shares_bought * closes[-1]
        dca_return = (final_value - total_invested) / total_invested if total_invested else 0.0

        if dca_return > lump_sum_return:
            better = "dollar-cost averaging"
            note = "Prices trended lower/volatile early — spreading purchases lowered average cost basis."
        elif lump_sum_return > dca_return:
            better = "lump sum"
            note = "Prices trended higher steadily — investing the full amount immediately captured more upside."
        else:
            better = "tie"
            note = "Both strategies produced comparable outcomes over the observed window."

        return DollarCostAveragingResult(
            symbol=symbol,
            months_observed=len(monthly_closes),
            lump_sum_return_pct=round(lump_sum_return * 100, 2),
            dca_return_pct=round(dca_return * 100, 2),
            better_strategy=better,
            note=note,
        )

    @staticmethod
    def _pearson_corr(a: list[float], b: list[float]) -> float:
        n = min(len(a), len(b))
        if n < 10:
            return 0.0
        a_tail, b_tail = a[-n:], b[-n:]
        try:
            return statistics.correlation(a_tail, b_tail)
        except Exception:
            mean_a, mean_b = statistics.mean(a_tail), statistics.mean(b_tail)
            cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a_tail, b_tail))
            var_a = sum((x - mean_a) ** 2 for x in a_tail)
            var_b = sum((y - mean_b) ** 2 for y in b_tail)
            denom = math.sqrt(var_a * var_b)
            return cov / denom if denom else 0.0

    def _diversification(self, return_map: dict[str, list[float]]) -> list[DiversificationPair]:
        symbols = [s for s in ("SPY", "QQQ", "XLK", "XLE", "XLU", "XLF", "GLD", "TLT") if s in return_map]
        pairs: list[DiversificationPair] = []
        for i in range(len(symbols)):
            for j in range(i + 1, len(symbols)):
                s1, s2 = symbols[i], symbols[j]
                corr = round(self._pearson_corr(return_map[s1], return_map[s2]), 4)
                if corr >= 0.7:
                    label = "highly correlated — limited diversification benefit"
                elif corr >= 0.3:
                    label = "moderately correlated"
                elif corr > -0.3:
                    label = "low correlation — good diversification pair"
                else:
                    label = "negatively correlated — strong hedge pair"
                pairs.append(DiversificationPair(pair=f"{s1}/{s2}", correlation=corr, label=label))
        pairs.sort(key=lambda p: p.correlation)
        return pairs

    @staticmethod
    def _risk_profiles(vix_level: float | None) -> list[RiskProfileStep]:
        note_suffix = ""
        if vix_level is not None:
            if vix_level >= 25:
                note_suffix = f" Current VIX ({vix_level:.1f}) is elevated — expect larger short-term swings at any allocation."
            elif vix_level <= 15:
                note_suffix = f" Current VIX ({vix_level:.1f}) is calm — a good environment to rebalance toward target weights."
        profiles = []
        for age in (25, 45, 65):
            stock_pct = max(0.0, min(100.0, 110 - age))
            profiles.append(RiskProfileStep(
                age_example=age,
                stock_allocation_pct=stock_pct,
                bond_allocation_pct=round(100 - stock_pct, 2),
                rule="110 minus age",
                note=(
                    f"Illustrative starting point for a {age}-year-old investor; adjust for personal "
                    f"risk tolerance and time horizon." + note_suffix
                ),
            ))
        return profiles

    @staticmethod
    def _debt_payoff_plans() -> list[DebtPayoffPlan]:
        # Classic illustrative example: 3 debts with distinct balances/rates.
        debts = [
            ("Credit card", 4000.0, 0.22),
            ("Personal loan", 6000.0, 0.11),
            ("Student loan", 15000.0, 0.06),
        ]
        MAX_PAYOFF_MONTHS = 600  # safety cap (50 years) so the simulation always terminates
        PAID_OFF_THRESHOLD = 0.01  # balances below one cent are treated as fully paid off

        def simulate(order: list[tuple[str, float, float]], monthly_payment: float = 600.0) -> tuple[float, int]:
            balances = {name: bal for name, bal, _ in order}
            rates = {name: rate for name, _, rate in order}
            months = 0
            total_interest = 0.0
            names_order = [name for name, _, _ in order]

            def remaining_names() -> list[str]:
                return [n for n in names_order if balances[n] > PAID_OFF_THRESHOLD]

            while remaining_names() and months < MAX_PAYOFF_MONTHS:
                months += 1
                active = remaining_names()
                for name in active:
                    interest = balances[name] * (rates[name] / 12)
                    total_interest += interest
                    balances[name] += interest
                payment_left = monthly_payment
                for name in remaining_names():
                    if payment_left <= 0:
                        break
                    pay = min(payment_left, balances[name])
                    balances[name] -= pay
                    payment_left -= pay
            return round(total_interest, 2), months

        avalanche_order = sorted(debts, key=lambda d: -d[2])
        snowball_order = sorted(debts, key=lambda d: d[1])

        aval_interest, aval_months = simulate(avalanche_order)
        snow_interest, snow_months = simulate(snowball_order)

        return [
            DebtPayoffPlan(
                strategy="avalanche (highest rate first)",
                order=[d[0] for d in avalanche_order],
                total_interest_paid=aval_interest,
                months_to_payoff=aval_months,
                note="Minimizes total interest paid across all debts.",
            ),
            DebtPayoffPlan(
                strategy="snowball (smallest balance first)",
                order=[d[0] for d in snowball_order],
                total_interest_paid=snow_interest,
                months_to_payoff=snow_months,
                note="Pays off individual debts fastest, which can build motivation even if total interest is higher.",
            ),
        ]

    @staticmethod
    def _retirement_ladder() -> list[RetirementPriorityStep]:
        steps = [
            ("Build a starter emergency fund (~1 month of expenses)", "Avoids high-interest debt for small shocks before investing."),
            ("Contribute enough to capture the full employer 401(k) match", "An instant, guaranteed return that beats nearly any market return."),
            ("Pay off high-interest debt (>8-10% APR)", "Guaranteed 'return' equal to the interest rate avoided."),
            ("Fully fund a 3-6 month emergency fund", "Protects invested assets from forced selling during income disruption."),
            ("Contribute to an HSA if eligible", "Triple tax advantage: deductible, tax-free growth, tax-free qualified withdrawals."),
            ("Max a Roth or Traditional IRA", "Additional tax-advantaged space beyond the employer plan."),
            ("Increase 401(k) contributions toward the annual max", "Further tax-deferred (or Roth) growth once prior steps are covered."),
            ("Invest in a taxable brokerage account", "For goals beyond tax-advantaged account limits."),
        ]
        return [RetirementPriorityStep(step=i + 1, action=a, rationale=r) for i, (a, r) in enumerate(steps)]

    def _market_signals(
        self,
        avg_correlation: float,
        vix_level: float | None,
        dca_results: list[DollarCostAveragingResult],
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        if avg_correlation >= 0.6:
            signals.append({
                "sector": "Cross-asset",
                "bias": "diversify",
                "tickers": ["GLD", "TLT", "XLU"],
                "reason": f"Average pairwise correlation across the watchlist is {avg_correlation:.2f} — "
                          "adding lower-correlated assets would improve diversification benefit.",
            })
        if vix_level is not None and vix_level >= 25:
            signals.append({
                "sector": "Volatility",
                "bias": "defensive",
                "tickers": ["TLT", "XLU"],
                "reason": f"VIX at {vix_level:.1f} is elevated — reinforce the emergency-fund lesson before adding risk.",
            })
        dca_wins = [r for r in dca_results if r.better_strategy == "dollar-cost averaging"]
        if dca_wins:
            signals.append({
                "sector": "Behavioral",
                "bias": "systematic",
                "tickers": [r.symbol for r in dca_wins],
                "reason": "Dollar-cost averaging outperformed a lump sum over the trailing year for "
                           f"{', '.join(r.symbol for r in dca_wins)} — favor scheduled contributions over timing.",
            })
        return signals

    def analyze(self) -> FinancialEducationReport:
        return_map: dict[str, list[float]] = {}
        close_map: dict[str, list[float]] = {}

        for symbol in WATCHLIST:
            closes = self._fetch_closes(symbol)
            if closes:
                close_map[symbol] = closes
                return_map[symbol] = self._daily_returns(closes)
            time.sleep(self.delay_seconds)

        if BENCHMARK not in return_map:
            raise RuntimeError("Unable to fetch SPY data for financial education analysis")

        market_cagr = self._annualized_return(return_map[BENCHMARK])
        compound_projections = self._compound_interest_projections(market_cagr)

        dca_results: list[DollarCostAveragingResult] = []
        for symbol in (BENCHMARK, "QQQ"):
            if symbol in close_map:
                result = self._dollar_cost_average(symbol, close_map[symbol])
                if result:
                    dca_results.append(result)

        diversification = self._diversification(return_map)
        avg_correlation = round(
            statistics.mean([p.correlation for p in diversification]), 4
        ) if diversification else 0.0
        if avg_correlation >= 0.6:
            diversification_label = "concentrated — most watchlist assets move together"
        elif avg_correlation >= 0.3:
            diversification_label = "moderately diversified"
        else:
            diversification_label = "well diversified"

        vix_level = close_map["^VIX"][-1] if "^VIX" in close_map else None
        risk_profiles = self._risk_profiles(vix_level)
        debt_plans = self._debt_payoff_plans()
        retirement_ladder = self._retirement_ladder()

        assessment = EducationAssessment(
            compounding_takeaway=(
                f"At the trailing-year market-implied rate ({market_cagr * 100:.1f}%/yr), a $1,000 start plus "
                "$200/month grows to "
                f"${next(p.future_value for p in compound_projections if 'market-implied' in p.scenario and p.years == 30):,.0f} "
                "over 30 years — most of that is compounding, not contributions."
            ),
            dca_takeaway=(
                "; ".join(
                    f"{r.symbol}: {r.better_strategy} won ({r.dca_return_pct:+.1f}% vs {r.lump_sum_return_pct:+.1f}%)"
                    for r in dca_results
                ) if dca_results else "Insufficient data to compare DCA vs. lump sum this run."
            ),
            diversification_takeaway=f"Average pairwise correlation {avg_correlation:.2f} — {diversification_label}.",
            risk_horizon_takeaway="Stock allocation under the 110-age rule ranges from "
            f"{risk_profiles[-1].stock_allocation_pct:.0f}% (age 65) to {risk_profiles[0].stock_allocation_pct:.0f}% (age 25).",
        )

        market_signals = self._market_signals(avg_correlation, vix_level, dca_results)

        recommendations = [
            "Automate contributions to capture compounding — time in the market matters more than timing it.",
            "Follow the retirement contribution ladder: employer match → emergency fund → HSA/IRA → max 401(k).",
            f"Rebalance toward assets with low correlation to SPY when average correlation exceeds 0.6 (currently {avg_correlation:.2f}).",
            "Pay down debt above ~8-10% APR before allocating new cash to taxable investing (avalanche minimizes interest paid).",
        ]
        if vix_level is not None and vix_level >= 25:
            recommendations.append(
                f"VIX at {vix_level:.1f} — verify the 3-6 month emergency fund is fully funded before increasing risk."
            )

        expert_summary = (
            f"Market-implied long-run return ~{market_cagr * 100:.1f}%/yr; watchlist diversification is "
            f"{diversification_label} (avg correlation {avg_correlation:.2f}); "
            f"{'DCA beat lump sum' if dca_results and dca_results[0].better_strategy == 'dollar-cost averaging' else 'lump sum performance was competitive'} "
            "over the trailing year."
        )

        return FinancialEducationReport(
            compound_projections=compound_projections,
            dca_results=dca_results,
            diversification=diversification,
            avg_correlation=avg_correlation,
            diversification_label=diversification_label,
            risk_profiles=risk_profiles,
            debt_plans=debt_plans,
            retirement_ladder=retirement_ladder,
            assessment=assessment,
            expert_summary=expert_summary,
            market_signals=market_signals,
            recommendations=recommendations,
            data_source="Yahoo Finance Chart API + Khan Academy personal-finance curriculum (static reference)",
        )

    def to_dict(self, report: FinancialEducationReport) -> dict[str, Any]:
        return {
            "meta": {
                "agent": "Financial Education Expert",
                "reference": KHAN_ACADEMY_URL,
                "expert_summary": report.expert_summary,
                "analyzed_at": report.analyzed_at,
                "temperature": self.temperature,
            },
            "compound_interest_projections": [
                {
                    "scenario": p.scenario,
                    "principal": p.principal,
                    "monthly_contribution": p.monthly_contribution,
                    "annual_rate_pct": p.annual_rate_pct,
                    "years": p.years,
                    "future_value": p.future_value,
                    "total_contributions": p.total_contributions,
                    "total_growth": p.total_growth,
                }
                for p in report.compound_projections
            ],
            "dollar_cost_averaging": [
                {
                    "symbol": r.symbol,
                    "months_observed": r.months_observed,
                    "lump_sum_return_pct": r.lump_sum_return_pct,
                    "dca_return_pct": r.dca_return_pct,
                    "better_strategy": r.better_strategy,
                    "note": r.note,
                }
                for r in report.dca_results
            ],
            "diversification": {
                "pairs": [
                    {"pair": p.pair, "correlation": p.correlation, "label": p.label}
                    for p in report.diversification
                ],
                "avg_correlation": report.avg_correlation,
                "label": report.diversification_label,
            },
            "risk_profiles": [
                {
                    "age_example": r.age_example,
                    "stock_allocation_pct": r.stock_allocation_pct,
                    "bond_allocation_pct": r.bond_allocation_pct,
                    "rule": r.rule,
                    "note": r.note,
                }
                for r in report.risk_profiles
            ],
            "debt_payoff_plans": [
                {
                    "strategy": d.strategy,
                    "order": d.order,
                    "total_interest_paid": d.total_interest_paid,
                    "months_to_payoff": d.months_to_payoff,
                    "note": d.note,
                }
                for d in report.debt_plans
            ],
            "retirement_contribution_ladder": [
                {"step": s.step, "action": s.action, "rationale": s.rationale}
                for s in report.retirement_ladder
            ],
            "education_assessment": {
                "compounding_takeaway": report.assessment.compounding_takeaway,
                "dca_takeaway": report.assessment.dca_takeaway,
                "diversification_takeaway": report.assessment.diversification_takeaway,
                "risk_horizon_takeaway": report.assessment.risk_horizon_takeaway,
            },
            "market_signals": report.market_signals,
            "recommendations": report.recommendations,
            "data_source": report.data_source,
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        result = self.to_dict(self.analyze())
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            lessons_path = output.parent / "khan_academy_lessons.json"
            lessons_path.write_text(json.dumps(CURRICULUM, indent=2), encoding="utf-8")
        return result


def run_financial_education_analysis(output: Path | None = None) -> dict[str, Any]:
    return FinancialEducationExpert().run(output=output)
