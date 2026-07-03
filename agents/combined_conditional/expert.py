"""
Combined & Conditional Probability Expert Agent
===============================================
Expert in combined and conditional probabilities applied to financial markets:
joint P(A∩B), union P(A∪B), conditional P(A|B), multi-condition P(A|B∩C),
independence tests, chain-rule decomposition, and combined scenario scoring.

Data: Yahoo Finance chart API (1-year daily history).
"""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Finance-Combined-Conditional/1.0 (shaggychunxx@gmail.com)"}

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

PROBABILITY_CONCEPTS: list[dict[str, Any]] = [
    {
        "id": "joint_probability",
        "name": "Joint Probability P(A∩B)",
        "description": "Probability both events occur on the same day",
        "formula": "P(A∩B) = count(A and B) / total_days",
    },
    {
        "id": "union_probability",
        "name": "Union Probability P(A∪B)",
        "description": "Probability at least one event occurs",
        "formula": "P(A∪B) = P(A) + P(B) - P(A∩B)",
    },
    {
        "id": "conditional_probability",
        "name": "Conditional Probability P(A|B)",
        "description": "Probability of A given B has occurred",
        "formula": "P(A|B) = P(A∩B) / P(B)",
    },
    {
        "id": "multi_conditional",
        "name": "Multi-Condition P(A|B∩C)",
        "description": "Probability of A given both B and C occur",
        "formula": "P(A|B∩C) = count(A and B and C) / count(B and C)",
    },
    {
        "id": "independence",
        "name": "Independence Test",
        "description": "Compare observed P(A∩B) to P(A)·P(B) under independence",
        "formula": "independence_ratio = P(A∩B) / (P(A)·P(B))",
    },
    {
        "id": "chain_rule",
        "name": "Chain Rule Decomposition",
        "description": "Factor joint probability into conditional chain",
        "formula": "P(A∩B∩C) = P(A)·P(B|A)·P(C|A∩B)",
    },
    {
        "id": "complement_conditional",
        "name": "Conditional Complement P(A'|B)",
        "description": "Probability A does not occur given B",
        "formula": "P(A'|B) = 1 - P(A|B)",
    },
    {
        "id": "scenario_scoring",
        "name": "Combined Scenario Score",
        "description": "Rank multi-asset joint outcomes by historical frequency",
        "formula": "score = P(A∩B) × lift_factor",
    },
]


@dataclass
class JointProb:
    event_a: str
    event_b: str
    symbol_a: str
    symbol_b: str
    joint_prob: float
    prob_a: float
    prob_b: float
    sample_size: int
    label: str


@dataclass
class UnionProb:
    event_a: str
    event_b: str
    union_prob: float
    joint_prob: float
    prob_a: float
    prob_b: float
    sample_size: int


@dataclass
class ConditionalProb:
    event: str
    condition: str
    symbol: str
    condition_symbol: str
    conditional_prob: float
    joint_prob: float
    condition_prob: float
    sample_size: int
    label: str


@dataclass
class MultiConditionalProb:
    event: str
    conditions: str
    conditional_prob: float
    joint_all_prob: float
    condition_sample_size: int
    label: str


@dataclass
class IndependenceTest:
    event_a: str
    event_b: str
    observed_joint: float
    expected_independent: float
    independence_ratio: float
    independent: bool
    dependence_label: str


@dataclass
class ChainRuleDecomp:
    events: str
    joint_prob: float
    chain_product: float
    factor_a: float
    factor_b_given_a: float
    factor_c_given_ab: float
    consistent: bool


@dataclass
class CombinedScenario:
    name: str
    events: list[str]
    combined_prob: float
    conditional_prob: float
    lift_vs_unconditional: float
    strategy: str
    tickers: list[str]


@dataclass
class CombinedAssessment:
    joint_structure: str
    conditional_structure: str
    independence_signal: str
    multi_condition_signal: str
    chain_rule_signal: str
    scenario_signal: str
    combined_edge: str


@dataclass
class CombinedConditionalReport:
    joint_probabilities: list[JointProb]
    union_probabilities: list[UnionProb]
    conditional_probabilities: list[ConditionalProb]
    multi_conditionals: list[MultiConditionalProb]
    independence_tests: list[IndependenceTest]
    chain_decompositions: list[ChainRuleDecomp]
    scenarios: list[CombinedScenario]
    assessment: CombinedAssessment
    coherence_score: float
    dependence_score: float
    regime_label: str
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    data_source: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CombinedConditionalExpert:
    """Expert in combined & conditional probabilities on market return events."""

    def __init__(self, delay_seconds: float = 0.3) -> None:
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
    def _align(
        return_map: dict[str, list[float]], sym_a: str, sym_b: str
    ) -> tuple[list[float], list[float], int]:
        a = return_map.get(sym_a, [])
        b = return_map.get(sym_b, [])
        n = min(len(a), len(b))
        return a[-n:], b[-n:], n

    def _joint(
        self,
        return_map: dict[str, list[float]],
        sym_a: str,
        sym_b: str,
        event_a: str,
        event_b: str,
        pred_a: Callable[[float], bool] | None = None,
        pred_b: Callable[[float], bool] | None = None,
    ) -> JointProb | None:
        pred_a = pred_a or (lambda r: r > 0)
        pred_b = pred_b or (lambda r: r > 0)
        a, b, n = self._align(return_map, sym_a, sym_b)
        if n < 30:
            return None

        count_a = sum(1 for r in a if pred_a(r))
        count_b = sum(1 for r in b if pred_b(r))
        count_joint = sum(1 for i in range(n) if pred_a(a[i]) and pred_b(b[i]))

        p_a = round(count_a / n, 4)
        p_b = round(count_b / n, 4)
        p_joint = round(count_joint / n, 4)

        if p_joint >= 0.35:
            label = "frequent joint occurrence"
        elif p_joint <= 0.10:
            label = "rare joint event"
        else:
            label = "moderate joint frequency"

        return JointProb(
            event_a=event_a,
            event_b=event_b,
            symbol_a=sym_a,
            symbol_b=sym_b,
            joint_prob=p_joint,
            prob_a=p_a,
            prob_b=p_b,
            sample_size=n,
            label=label,
        )

    def _union_from_joint(self, joint: JointProb) -> UnionProb:
        p_union = round(joint.prob_a + joint.prob_b - joint.joint_prob, 4)
        return UnionProb(
            event_a=joint.event_a,
            event_b=joint.event_b,
            union_prob=p_union,
            joint_prob=joint.joint_prob,
            prob_a=joint.prob_a,
            prob_b=joint.prob_b,
            sample_size=joint.sample_size,
        )

    def _conditional(
        self,
        return_map: dict[str, list[float]],
        sym: str,
        cond_sym: str,
        event: str,
        condition: str,
        pred_event: Callable[[float], bool] | None = None,
        pred_cond: Callable[[float], bool] | None = None,
    ) -> ConditionalProb | None:
        pred_event = pred_event or (lambda r: r > 0)
        pred_cond = pred_cond or (lambda r: r > 0)
        a, b, n = self._align(return_map, sym, cond_sym)
        if n < 30:
            return None

        cond_indices = [i for i in range(n) if pred_cond(b[i])]
        if len(cond_indices) < 8:
            return None

        joint = sum(1 for i in cond_indices if pred_event(a[i]))
        p_cond = round(len(cond_indices) / n, 4)
        p_joint = round(joint / n, 4)
        p_given = round(joint / len(cond_indices), 4)

        if p_given >= 0.70:
            label = "strong conditional dependence"
        elif p_given <= 0.30:
            label = "inverse conditional relationship"
        else:
            label = "moderate conditional link"

        return ConditionalProb(
            event=event,
            condition=condition,
            symbol=sym,
            condition_symbol=cond_sym,
            conditional_prob=p_given,
            joint_prob=p_joint,
            condition_prob=p_cond,
            sample_size=len(cond_indices),
            label=label,
        )

    def _multi_conditional(
        self,
        return_map: dict[str, list[float]],
        sym_a: str,
        sym_b: str,
        sym_c: str,
        event: str,
        conditions: str,
    ) -> MultiConditionalProb | None:
        a, b, _ = self._align(return_map, sym_a, sym_b)
        _, c, n = self._align(return_map, sym_a, sym_c)
        if n < 30:
            return None

        b = return_map[sym_b][-n:]
        c = return_map[sym_c][-n:]
        a = return_map[sym_a][-n:]

        cond_idx = [i for i in range(n) if b[i] > 0 and c[i] < 0]
        if len(cond_idx) < 5:
            cond_idx = [i for i in range(n) if b[i] > 0 and c[i] > 0]
        if len(cond_idx) < 5:
            return None

        successes = sum(1 for i in cond_idx if a[i] > 0)
        joint_all = sum(1 for i in range(n) if a[i] > 0 and b[i] > 0 and c[i] < 0)
        if joint_all < 3:
            joint_all = sum(1 for i in range(n) if a[i] > 0 and b[i] > 0 and c[i] > 0)

        p_given = round(successes / len(cond_idx), 4)
        p_joint_all = round(joint_all / n, 4)

        if p_given >= 0.70:
            label = "high multi-condition probability"
        elif p_given <= 0.35:
            label = "low multi-condition probability"
        else:
            label = "moderate multi-condition link"

        return MultiConditionalProb(
            event=event,
            conditions=conditions,
            conditional_prob=p_given,
            joint_all_prob=p_joint_all,
            condition_sample_size=len(cond_idx),
            label=label,
        )

    def _independence_test(self, joint: JointProb) -> IndependenceTest:
        expected = round(joint.prob_a * joint.prob_b, 4)
        ratio = round(joint.joint_prob / expected, 4) if expected > 0 else 0.0
        independent = 0.85 <= ratio <= 1.15

        if ratio >= 1.25:
            dep_label = "positive dependence — assets move together more than independent"
        elif ratio <= 0.75:
            dep_label = "negative dependence — joint events rarer than independent"
        elif independent:
            dep_label = "approximately independent"
        else:
            dep_label = "weak dependence"

        return IndependenceTest(
            event_a=joint.event_a,
            event_b=joint.event_b,
            observed_joint=joint.joint_prob,
            expected_independent=expected,
            independence_ratio=ratio,
            independent=independent,
            dependence_label=dep_label,
        )

    def _chain_rule(
        self,
        return_map: dict[str, list[float]],
        sym_a: str,
        sym_b: str,
        sym_c: str,
    ) -> ChainRuleDecomp | None:
        a, b, n = self._align(return_map, sym_a, sym_b)
        c = return_map.get(sym_c, [])[-n:]
        if n < 30 or len(c) < n:
            return None

        count_a = sum(1 for r in a if r > 0)
        count_ab = sum(1 for i in range(n) if a[i] > 0 and b[i] > 0)
        count_abc = sum(1 for i in range(n) if a[i] > 0 and b[i] > 0 and c[i] > 0)

        p_a = count_a / n
        p_b_given_a = count_ab / count_a if count_a else 0
        ab_indices = [i for i in range(n) if a[i] > 0 and b[i] > 0]
        p_c_given_ab = (
            sum(1 for i in ab_indices if c[i] > 0) / len(ab_indices) if ab_indices else 0
        )

        joint = round(count_abc / n, 4)
        chain = round(p_a * p_b_given_a * p_c_given_ab, 4)
        consistent = abs(joint - chain) <= 0.02

        return ChainRuleDecomp(
            events=f"{sym_a} up ∩ {sym_b} up ∩ {sym_c} up",
            joint_prob=joint,
            chain_product=chain,
            factor_a=round(p_a, 4),
            factor_b_given_a=round(p_b_given_a, 4),
            factor_c_given_ab=round(p_c_given_ab, 4),
            consistent=consistent,
        )

    def _scenarios(
        self,
        joints: list[JointProb],
        conditionals: list[ConditionalProb],
        multi: list[MultiConditionalProb],
    ) -> list[CombinedScenario]:
        scenarios: list[CombinedScenario] = []

        for j in joints:
            if j.joint_prob >= 0.25:
                lift = round(j.joint_prob / j.prob_a if j.prob_a else 1, 2)
                scenarios.append(CombinedScenario(
                    name=f"{j.event_a} AND {j.event_b}",
                    events=[j.event_a, j.event_b],
                    combined_prob=j.joint_prob,
                    conditional_prob=round(j.joint_prob / j.prob_b if j.prob_b else 0, 4),
                    lift_vs_unconditional=lift,
                    strategy="momentum_pairs",
                    tickers=[j.symbol_a, j.symbol_b],
                ))

        for c in conditionals:
            if c.conditional_prob >= 0.75:
                scenarios.append(CombinedScenario(
                    name=f"{c.event} given {c.condition}",
                    events=[c.event, c.condition],
                    combined_prob=c.joint_prob,
                    conditional_prob=c.conditional_prob,
                    lift_vs_unconditional=round(
                        c.conditional_prob / (c.joint_prob / c.sample_size * c.sample_size / c.sample_size)
                        if c.joint_prob else 1, 2
                    ),
                    strategy="conditional_trade",
                    tickers=[c.symbol],
                ))

        for m in multi:
            if m.conditional_prob >= 0.65:
                scenarios.append(CombinedScenario(
                    name=f"{m.event} given {m.conditions}",
                    events=m.conditions.split(" AND "),
                    combined_prob=m.joint_all_prob,
                    conditional_prob=m.conditional_prob,
                    lift_vs_unconditional=round(m.conditional_prob / max(m.joint_all_prob, 0.01), 2),
                    strategy="multi_condition_filter",
                    tickers=["SPY", "QQQ", "XLK"],
                ))

        scenarios.sort(key=lambda s: -s.combined_prob)
        return scenarios[:10]

    def _assessment(
        self,
        joints: list[JointProb],
        conditionals: list[ConditionalProb],
        independence: list[IndependenceTest],
        multi: list[MultiConditionalProb],
        chains: list[ChainRuleDecomp],
        scenarios: list[CombinedScenario],
    ) -> CombinedAssessment:
        if joints:
            top_j = max(joints, key=lambda j: j.joint_prob)
            joint_struct = (
                f"highest joint P({top_j.event_a}∩{top_j.event_b})={top_j.joint_prob:.0%} "
                f"({top_j.label})"
            )
        else:
            joint_struct = "joint probability data limited"

        if conditionals:
            top_c = max(conditionals, key=lambda c: c.conditional_prob)
            cond_struct = (
                f"strongest P({top_c.event}|{top_c.condition})={top_c.conditional_prob:.0%} "
                f"({top_c.label})"
            )
        else:
            cond_struct = "conditional probability data limited"

        dependent = [t for t in independence if not t.independent]
        if dependent:
            top_d = max(dependent, key=lambda t: abs(t.independence_ratio - 1))
            indep_sig = (
                f"{top_d.event_a} & {top_d.event_b}: ratio={top_d.independence_ratio:.2f} "
                f"— {top_d.dependence_label}"
            )
        else:
            indep_sig = "asset pairs approximately independent on daily up/down events"

        if multi:
            top_m = max(multi, key=lambda m: m.conditional_prob)
            multi_sig = (
                f"P({top_m.event}|{top_m.conditions})={top_m.conditional_prob:.0%} "
                f"(n={top_m.condition_sample_size})"
            )
        else:
            multi_sig = "multi-condition probabilities inconclusive"

        if chains:
            ch = chains[0]
            chain_sig = (
                f"chain rule {ch.events}: P={ch.joint_prob:.0%} = "
                f"{ch.factor_a:.0%}×{ch.factor_b_given_a:.0%}×{ch.factor_c_given_ab:.0%} "
                f"({'consistent' if ch.consistent else 'approximate'})"
            )
        else:
            chain_sig = "chain rule decomposition unavailable"

        if scenarios:
            top_s = scenarios[0]
            scen_sig = (
                f"top scenario '{top_s.name}': combined P={top_s.combined_prob:.0%}, "
                f"conditional P={top_s.conditional_prob:.0%}"
            )
        else:
            scen_sig = "no high-probability combined scenarios"

        high_cond = [c for c in conditionals if c.conditional_prob >= 0.70]
        if high_cond:
            edge = (
                f"trade conditional setups when {high_cond[0].condition} — "
                f"P({high_cond[0].event})={high_cond[0].conditional_prob:.0%}"
            )
        elif scenarios:
            edge = f"combined scenario edge via {scenarios[0].strategy} on {scenarios[0].tickers}"
        else:
            edge = "combined/conditional structure shows no dominant trading edge"

        return CombinedAssessment(
            joint_structure=joint_struct,
            conditional_structure=cond_struct,
            independence_signal=indep_sig,
            multi_condition_signal=multi_sig,
            chain_rule_signal=chain_sig,
            scenario_signal=scen_sig,
            combined_edge=edge,
        )

    def _expert_summary(
        self,
        assessment: CombinedAssessment,
        label: str,
        coherence: float,
    ) -> str:
        return (
            f"Combined & conditional probability scan: {label} (coherence {coherence:.2f}). "
            f"{assessment.joint_structure}. "
            f"{assessment.conditional_structure}. "
            f"{assessment.independence_signal}. "
            f"{assessment.multi_condition_signal}. "
            f"{assessment.chain_rule_signal}. "
            f"{assessment.scenario_signal}. "
            f"Edge: {assessment.combined_edge}."
        )

    def analyze(self) -> CombinedConditionalReport:
        return_map: dict[str, list[float]] = {}

        for symbol in WATCHLIST:
            closes = self._fetch_closes(symbol)
            if closes:
                return_map[symbol] = self._daily_returns(closes)
            time.sleep(self.delay_seconds)

        if BENCHMARK not in return_map:
            raise RuntimeError("Unable to fetch SPY data for combined/conditional analysis")

        joint_defs = [
            ("SPY", "QQQ", "SPY up", "QQQ up"),
            ("SPY", "IWM", "SPY up", "IWM up"),
            ("SPY", "XLK", "SPY up", "XLK up"),
            ("QQQ", "XLK", "QQQ up", "XLK up"),
            ("SPY", "GLD", "SPY up", "GLD up"),
            ("SPY", "^VIX", "SPY up", "VIX up", lambda r: r > 0, lambda r: r > 0),
            ("SPY", "XLU", "SPY down", "Utilities up", lambda r: r < 0, lambda r: r > 0),
            ("XLE", "XLF", "Energy up", "Financials up"),
        ]

        joints: list[JointProb] = []
        for item in joint_defs:
            if len(item) == 6:
                sym_a, sym_b, ev_a, ev_b, pa, pb = item
                j = self._joint(return_map, sym_a, sym_b, ev_a, ev_b, pa, pb)
            else:
                sym_a, sym_b, ev_a, ev_b = item
                j = self._joint(return_map, sym_a, sym_b, ev_a, ev_b)
            if j:
                joints.append(j)

        unions = [self._union_from_joint(j) for j in joints]

        cond_defs = [
            ("XLK", "SPY", "Tech up", "SPY up"),
            ("QQQ", "SPY", "Nasdaq up", "SPY up"),
            ("IWM", "SPY", "Small-cap up", "SPY up"),
            ("XLU", "SPY", "Utilities up", "SPY down", None, lambda r: r < 0),
            ("GLD", "SPY", "Gold up", "SPY down", None, lambda r: r < 0),
            ("^VIX", "SPY", "VIX up", "SPY down", None, lambda r: r < 0),
            ("XLE", "SPY", "Energy up", "SPY up"),
            ("XLF", "SPY", "Financials up", "SPY up"),
            ("TLT", "SPY", "Bonds up", "SPY down", None, lambda r: r < 0),
        ]

        conditionals: list[ConditionalProb] = []
        for item in cond_defs:
            if len(item) == 6:
                sym, csym, ev, cond, pe, pc = item
                c = self._conditional(return_map, sym, csym, ev, cond, pe, pc)
            else:
                sym, csym, ev, cond = item
                c = self._conditional(return_map, sym, csym, ev, cond)
            if c:
                conditionals.append(c)

        multi = [
            m for m in (
                self._multi_conditional(
                    return_map, "XLK", "SPY", "^VIX",
                    "Tech up", "SPY up AND VIX down",
                ),
                self._multi_conditional(
                    return_map, "QQQ", "SPY", "IWM",
                    "Nasdaq up", "SPY up AND small-cap up",
                ),
                self._multi_conditional(
                    return_map, "GLD", "SPY", "^VIX",
                    "Gold up", "SPY down AND VIX up",
                ),
            ) if m
        ]

        independence = [self._independence_test(j) for j in joints]
        chains = [
            c for c in (
                self._chain_rule(return_map, "SPY", "QQQ", "XLK"),
                self._chain_rule(return_map, "SPY", "IWM", "XLF"),
            ) if c
        ]

        scenarios = self._scenarios(joints, conditionals, multi)
        assessment = self._assessment(
            joints, conditionals, independence, multi, chains, scenarios
        )

        avg_joint = statistics.mean(j.joint_prob for j in joints) if joints else 0.5
        dep_count = sum(1 for t in independence if not t.independent)
        coherence = round(
            0.35 * avg_joint
            + 0.35 * (max(c.conditional_prob for c in conditionals) if conditionals else 0.5)
            + 0.30 * (dep_count / max(len(independence), 1)),
            4,
        )
        dependence_score = round(dep_count / max(len(independence), 1), 4)

        if coherence >= 0.55 and conditionals and max(c.conditional_prob for c in conditionals) >= 0.70:
            regime_label = "Strong Combined Dependence"
        elif dependence_score >= 0.5:
            regime_label = "Structured Dependence"
        else:
            regime_label = "Weak Combined Structure"

        summary = self._expert_summary(assessment, regime_label, coherence)
        signals = self._market_signals(joints, conditionals, multi, scenarios, independence)
        recs = self._recommendations(
            assessment, joints, unions, conditionals, multi,
            independence, chains, scenarios,
        )

        return CombinedConditionalReport(
            joint_probabilities=joints,
            union_probabilities=unions,
            conditional_probabilities=conditionals,
            multi_conditionals=multi,
            independence_tests=independence,
            chain_decompositions=chains,
            scenarios=scenarios,
            assessment=assessment,
            coherence_score=coherence,
            dependence_score=dependence_score,
            regime_label=regime_label,
            expert_summary=summary,
            market_signals=signals,
            recommendations=recs,
            data_source="Yahoo Finance API",
        )

    @staticmethod
    def _market_signals(
        joints: list[JointProb],
        conditionals: list[ConditionalProb],
        multi: list[MultiConditionalProb],
        scenarios: list[CombinedScenario],
        independence: list[IndependenceTest],
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        if joints:
            top = max(joints, key=lambda j: j.joint_prob)
            signals.append({
                "sector": "Joint Probability",
                "tickers": [top.symbol_a, top.symbol_b],
                "bias": "BULLISH" if "up" in top.event_a else "NEUTRAL",
                "reason": f"P({top.event_a}∩{top.event_b})={top.joint_prob:.0%}",
            })

        for c in sorted(conditionals, key=lambda x: -x.conditional_prob)[:2]:
            if c.conditional_prob >= 0.65:
                signals.append({
                    "sector": f"Conditional — {c.event}",
                    "tickers": [c.symbol],
                    "bias": "BULLISH" if c.conditional_prob >= 0.5 else "BEARISH",
                    "reason": f"P({c.event}|{c.condition})={c.conditional_prob:.0%}",
                })

        for m in multi[:1]:
            if m.conditional_prob >= 0.60:
                signals.append({
                    "sector": f"Multi-Condition — {m.event}",
                    "tickers": ["SPY", "QQQ", "XLK"],
                    "bias": "BULLISH",
                    "reason": f"P({m.event}|{m.conditions})={m.conditional_prob:.0%}",
                })

        for t in independence:
            if t.independence_ratio >= 1.3:
                signals.append({
                    "sector": f"Positive Dependence — {t.event_a}",
                    "tickers": ["SPY", "QQQ"],
                    "bias": "BULLISH",
                    "reason": f"joint/independent ratio={t.independence_ratio:.2f}",
                })

        if scenarios:
            s = scenarios[0]
            signals.append({
                "sector": f"Combined Scenario — {s.strategy}",
                "tickers": s.tickers,
                "bias": "BULLISH",
                "reason": f"'{s.name}' P={s.combined_prob:.0%}",
            })

        if not signals:
            signals.append({
                "sector": "Combined Neutral",
                "tickers": ["SPY"],
                "bias": "NEUTRAL",
                "reason": "No dominant combined/conditional edge",
            })
        return signals

    @staticmethod
    def _recommendations(
        assessment: CombinedAssessment,
        joints: list[JointProb],
        unions: list[UnionProb],
        conditionals: list[ConditionalProb],
        multi: list[MultiConditionalProb],
        independence: list[IndependenceTest],
        chains: list[ChainRuleDecomp],
        scenarios: list[CombinedScenario],
    ) -> list[str]:
        recs = [
            assessment.joint_structure,
            assessment.conditional_structure,
            assessment.independence_signal,
            assessment.multi_condition_signal,
            assessment.chain_rule_signal,
            assessment.scenario_signal,
            assessment.combined_edge,
        ]
        for j in sorted(joints, key=lambda x: -x.joint_prob)[:4]:
            recs.append(
                f"P({j.event_a}∩{j.event_b})={j.joint_prob:.0%} "
                f"(P(A)={j.prob_a:.0%}, P(B)={j.prob_b:.0%}, n={j.sample_size})"
            )
        for u in unions[:3]:
            recs.append(
                f"P({u.event_a}∪{u.event_b})={u.union_prob:.0%} "
                f"(joint={u.joint_prob:.0%})"
            )
        for c in sorted(conditionals, key=lambda x: -x.conditional_prob)[:4]:
            recs.append(
                f"P({c.event}|{c.condition})={c.conditional_prob:.0%} "
                f"[joint={c.joint_prob:.0%}, P(B)={c.condition_prob:.0%}] — {c.label}"
            )
        for m in multi:
            recs.append(
                f"P({m.event}|{m.conditions})={m.conditional_prob:.0%} "
                f"(joint all={m.joint_all_prob:.0%}, n={m.condition_sample_size})"
            )
        for t in independence:
            if not t.independent:
                recs.append(
                    f"Independence {t.event_a}/{t.event_b}: "
                    f"observed={t.observed_joint:.0%} vs independent={t.expected_independent:.0%} "
                    f"(ratio {t.independence_ratio:.2f})"
                )
        for ch in chains:
            recs.append(
                f"Chain: P({ch.events})={ch.joint_prob:.0%} = "
                f"{ch.factor_a:.0%}×{ch.factor_b_given_a:.0%}×{ch.factor_c_given_ab:.0%}"
            )
        for s in scenarios[:3]:
            recs.append(
                f"Scenario '{s.name}': combined={s.combined_prob:.0%}, "
                f"conditional={s.conditional_prob:.0%}, strategy={s.strategy}"
            )
        return recs

    def to_dict(self, report: CombinedConditionalReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Combined & Conditional Probability Expert",
                "analyzed_at": report.analyzed_at,
                "data_source": report.data_source,
                "expert_summary": report.expert_summary,
                "concepts_applied": [c["id"] for c in PROBABILITY_CONCEPTS],
            },
            "probability_concepts": PROBABILITY_CONCEPTS,
            "joint_probabilities": [
                {
                    "event_a": j.event_a,
                    "event_b": j.event_b,
                    "symbol_a": j.symbol_a,
                    "symbol_b": j.symbol_b,
                    "joint_prob": j.joint_prob,
                    "prob_a": j.prob_a,
                    "prob_b": j.prob_b,
                    "sample_size": j.sample_size,
                    "label": j.label,
                }
                for j in report.joint_probabilities
            ],
            "union_probabilities": [
                {
                    "event_a": u.event_a,
                    "event_b": u.event_b,
                    "union_prob": u.union_prob,
                    "joint_prob": u.joint_prob,
                    "prob_a": u.prob_a,
                    "prob_b": u.prob_b,
                    "sample_size": u.sample_size,
                }
                for u in report.union_probabilities
            ],
            "conditional_probabilities": [
                {
                    "event": c.event,
                    "condition": c.condition,
                    "symbol": c.symbol,
                    "condition_symbol": c.condition_symbol,
                    "conditional_prob": c.conditional_prob,
                    "joint_prob": c.joint_prob,
                    "condition_prob": c.condition_prob,
                    "sample_size": c.sample_size,
                    "label": c.label,
                }
                for c in report.conditional_probabilities
            ],
            "multi_conditionals": [
                {
                    "event": m.event,
                    "conditions": m.conditions,
                    "conditional_prob": m.conditional_prob,
                    "joint_all_prob": m.joint_all_prob,
                    "condition_sample_size": m.condition_sample_size,
                    "label": m.label,
                }
                for m in report.multi_conditionals
            ],
            "independence_tests": [
                {
                    "event_a": t.event_a,
                    "event_b": t.event_b,
                    "observed_joint": t.observed_joint,
                    "expected_independent": t.expected_independent,
                    "independence_ratio": t.independence_ratio,
                    "independent": t.independent,
                    "dependence_label": t.dependence_label,
                }
                for t in report.independence_tests
            ],
            "chain_decompositions": [
                {
                    "events": ch.events,
                    "joint_prob": ch.joint_prob,
                    "chain_product": ch.chain_product,
                    "factor_a": ch.factor_a,
                    "factor_b_given_a": ch.factor_b_given_a,
                    "factor_c_given_ab": ch.factor_c_given_ab,
                    "consistent": ch.consistent,
                }
                for ch in report.chain_decompositions
            ],
            "combined_scenarios": [
                {
                    "name": s.name,
                    "events": s.events,
                    "combined_prob": s.combined_prob,
                    "conditional_prob": s.conditional_prob,
                    "lift_vs_unconditional": s.lift_vs_unconditional,
                    "strategy": s.strategy,
                    "tickers": s.tickers,
                }
                for s in report.scenarios
            ],
            "combined_assessment": {
                "joint_structure": a.joint_structure,
                "conditional_structure": a.conditional_structure,
                "independence_signal": a.independence_signal,
                "multi_condition_signal": a.multi_condition_signal,
                "chain_rule_signal": a.chain_rule_signal,
                "scenario_signal": a.scenario_signal,
                "combined_edge": a.combined_edge,
            },
            "metrics": {
                "coherence_score": report.coherence_score,
                "dependence_score": report.dependence_score,
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
            catalog = output.parent / "probability_concepts.json"
            catalog.write_text(
                json.dumps(PROBABILITY_CONCEPTS, indent=2),
                encoding="utf-8",
            )
        return result


def run_combined_conditional_analysis(output: Path | None = None) -> dict[str, Any]:
    return CombinedConditionalExpert().run(output=output)