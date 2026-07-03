"""Multi-Agent Collaboration Coordinator
=========================================
Runs every intelligence agent through a three-phase collaborative workflow:

1. **Analyze** — agents are shuffled into random groups of 3-4 and each
   group produces a combined analysis from its members' individual reports.
2. **Peer review** — the pool is reshuffled into new random groups; each new
   group peer-reviews the group analyses that its members originated from
   (always by people outside the original group, wherever possible).
3. **Finalize** — the pool is reshuffled a third time; each new group merges
   the original analyses with peer-review feedback into a final consensus
   view for its members' original work.

The workflow reuses the existing per-domain agents (markets, geopolitics,
meteorology, etc.) as the underlying data sources.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agents.combined_conditional import run_combined_conditional_analysis
from agents.datascience import run_datascience_analysis
from agents.electricity import run_electricity_analysis
from agents.empirical_probability import run_empirical_probability_analysis
from agents.events import run_events_analysis
from agents.finance import run_finance_analysis
from agents.financial_data import run_financial_data_analysis
from agents.geopolitics import run_geopolitics_analysis
from agents.grid import run_grid_analysis
from agents.logistics import run_logistics_analysis
from agents.markets import run_markets_analysis
from agents.meteorology import run_meteorology_analysis
from agents.patents import run_patents_analysis
from agents.research_statistics import run_research_statistics_analysis
from agents.theoretical_probability import run_theoretical_probability_analysis
from agents.transportation import run_transportation_analysis

RUNNERS: dict[str, Callable[..., dict[str, Any]]] = {
    "combined-conditional": run_combined_conditional_analysis,
    "datascience": run_datascience_analysis,
    "electricity": run_electricity_analysis,
    "empirical-probability": run_empirical_probability_analysis,
    "events": run_events_analysis,
    "financial-data": run_financial_data_analysis,
    "finance": run_finance_analysis,
    "geopolitics": run_geopolitics_analysis,
    "grid": run_grid_analysis,
    "logistics": run_logistics_analysis,
    "markets": run_markets_analysis,
    "meteorology": run_meteorology_analysis,
    "patents": run_patents_analysis,
    "research-statistics": run_research_statistics_analysis,
    "theoretical-probability": run_theoretical_probability_analysis,
    "transportation": run_transportation_analysis,
}


def _group_sizes(n: int) -> list[int]:
    """Split n items into group sizes of 3 or 4 wherever possible."""
    if n <= 0:
        return []
    if n <= 4:
        return [n]
    lo = -(-n // 4)  # ceil(n / 4)
    hi = max(lo, n // 3)
    for k in range(lo, hi + 1):
        if 3 * k <= n <= 4 * k:
            base, rem = divmod(n, k)
            return [base + 1] * rem + [base] * (k - rem)
    return [n]


@dataclass
class AgentOutput:
    name: str
    summary: str
    signals: list[dict[str, Any]]
    recommendations: list[str]
    error: str | None = None


@dataclass
class Group:
    group_id: str
    members: list[str]


@dataclass
class GroupAnalysis:
    group_id: str
    members: list[str]
    combined_summary: str
    aggregated_signals: dict[str, str]
    top_recommendations: list[str]
    errors: list[str]
    baseline_confidence: float = 0.5


@dataclass
class PeerReview:
    reviewer_group_id: str
    reviewer_members: list[str]
    target_group_id: str
    target_members: list[str]
    agreement_score: float
    comments: list[str]
    self_review: bool
    has_correction: bool = False


@dataclass
class ScoreEvent:
    origin_group_id: str
    reviewer_group_id: str
    reviewer_members: list[str]
    corrected_members: list[str]
    baseline_confidence: float
    post_review_confidence: float
    outcome: str
    reviewer_delta: float
    corrected_delta: float


@dataclass
class FinalAnalysis:
    group_id: str
    members: list[str]
    origin_group_ids: list[str]
    final_summary: str
    consensus_signals: dict[str, str]
    confidence_score: float
    final_recommendations: list[str]
    peer_reviews_considered: int


@dataclass
class CollaborationReport:
    agent_names: list[str]
    outputs: dict[str, AgentOutput]
    phase1_groups: list[Group]
    phase1_analyses: dict[str, GroupAnalysis]
    phase2_groups: list[Group]
    peer_reviews: list[PeerReview]
    phase3_groups: list[Group]
    final_analyses: list[FinalAnalysis]
    agent_scores: dict[str, float]
    score_events: list[ScoreEvent]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CollaborationCoordinator:
    """Coordinates the three-phase group / peer-review / finalize workflow."""

    def __init__(self, agent_names: list[str] | None = None, seed: int | None = None):
        self.agent_names = sorted(agent_names) if agent_names else sorted(RUNNERS.keys())
        unknown = [n for n in self.agent_names if n not in RUNNERS]
        if unknown:
            raise ValueError(f"Unknown agent(s): {', '.join(unknown)}")
        self.rng = random.Random(seed)

    def _make_groups(self, prefix: str) -> list[Group]:
        members = list(self.agent_names)
        self.rng.shuffle(members)
        sizes = _group_sizes(len(members))
        groups: list[Group] = []
        idx = 0
        for i, size in enumerate(sizes, start=1):
            chunk = members[idx: idx + size]
            idx += size
            groups.append(Group(group_id=f"{prefix}-{i}", members=chunk))
        return groups

    def _run_agents(self) -> dict[str, AgentOutput]:
        outputs: dict[str, AgentOutput] = {}
        for name in self.agent_names:
            try:
                data = RUNNERS[name]()
                meta = data.get("meta", {})
                outputs[name] = AgentOutput(
                    name=name,
                    summary=meta.get("expert_summary", ""),
                    signals=data.get("market_signals", []) or [],
                    recommendations=data.get("recommendations", []) or [],
                )
            except Exception as exc:
                outputs[name] = AgentOutput(
                    name=name, summary="", signals=[], recommendations=[], error=str(exc)
                )
        return outputs

    @staticmethod
    def _aggregate_signals(signals: list[dict[str, Any]]) -> dict[str, str]:
        by_sector: dict[str, Counter] = {}
        for sig in signals:
            sector = sig.get("sector", "Unknown")
            bias = sig.get("bias", "NEUTRAL")
            by_sector.setdefault(sector, Counter())[bias] += 1
        aggregated: dict[str, str] = {}
        for sector, counts in by_sector.items():
            top = counts.most_common()
            if len(top) > 1 and top[0][1] == top[1][1]:
                aggregated[sector] = "MIXED"
            else:
                aggregated[sector] = top[0][0]
        return aggregated

    def _build_group_analysis(
        self, group: Group, outputs: dict[str, AgentOutput]
    ) -> GroupAnalysis:
        members_out = [outputs[m] for m in group.members]
        errors = [f"{o.name}: {o.error}" for o in members_out if o.error]
        summaries = [f"{o.name}: {o.summary}" for o in members_out if o.summary]
        combined_summary = (
            f"Group {group.group_id} ({', '.join(group.members)}) combined view — "
            + " | ".join(summaries[:4])
        )
        all_signals = [sig for o in members_out for sig in o.signals]
        aggregated = self._aggregate_signals(all_signals)
        member_matches = 0
        member_total = 0
        for sig in all_signals:
            member_total += 1
            if aggregated.get(sig.get("sector", "Unknown")) == sig.get("bias", "NEUTRAL"):
                member_matches += 1
        baseline_confidence = round(member_matches / member_total, 4) if member_total else 0.5
        recs: list[str] = []
        seen: set[str] = set()
        for o in members_out:
            for r in o.recommendations:
                if r not in seen:
                    seen.add(r)
                    recs.append(r)
        return GroupAnalysis(
            group_id=group.group_id,
            members=group.members,
            combined_summary=combined_summary,
            aggregated_signals=aggregated,
            top_recommendations=recs[:6],
            errors=errors,
            baseline_confidence=baseline_confidence,
        )

    def _build_peer_reviews(
        self,
        phase2_groups: list[Group],
        member_to_group1: dict[str, str],
        phase1_analyses: dict[str, GroupAnalysis],
        outputs: dict[str, AgentOutput],
    ) -> list[PeerReview]:
        reviews: list[PeerReview] = []
        for reviewer_group in phase2_groups:
            origin_ids = sorted({member_to_group1[m] for m in reviewer_group.members})
            for origin_id in origin_ids:
                target = phase1_analyses[origin_id]
                outsiders = [m for m in reviewer_group.members if m not in target.members]
                self_review = len(outsiders) == 0
                reviewer_signals = [
                    sig
                    for m in (outsiders or reviewer_group.members)
                    for sig in outputs[m].signals
                ]
                reviewer_view = self._aggregate_signals(reviewer_signals)

                comments: list[str] = []
                matches = 0
                sectors = sorted(set(reviewer_view) | set(target.aggregated_signals))
                for sector in sectors:
                    reviewer_bias = reviewer_view.get(sector)
                    target_bias = target.aggregated_signals.get(sector)
                    if reviewer_bias and target_bias:
                        if reviewer_bias == target_bias:
                            matches += 1
                            comments.append(f"Agree on {sector}: {target_bias}")
                        else:
                            comments.append(
                                f"Disagree on {sector}: group {origin_id} said {target_bias}, "
                                f"reviewers lean {reviewer_bias}"
                            )
                    elif target_bias:
                        comments.append(f"No independent view on {sector} ({target_bias})")
                agreement_score = round(matches / len(sectors), 2) if sectors else 0.5
                has_correction = any(c.startswith("Disagree on") for c in comments)
                if self_review:
                    comments.append(
                        "Note: reviewer group overlaps entirely with original group members"
                    )
                if not comments:
                    comments.append("No signals to compare; defaulting to neutral agreement")
                reviews.append(
                    PeerReview(
                        reviewer_group_id=reviewer_group.group_id,
                        reviewer_members=reviewer_group.members,
                        target_group_id=origin_id,
                        target_members=target.members,
                        agreement_score=agreement_score,
                        comments=comments,
                        self_review=self_review,
                        has_correction=has_correction,
                    )
                )
        return reviews

    @staticmethod
    def _score_agents(
        phase1_analyses: dict[str, GroupAnalysis], peer_reviews: list[PeerReview]
    ) -> tuple[dict[str, float], list[ScoreEvent]]:
        """Score agents on corrections raised during peer review.

        - A correction that yields better results: reviewer(s) +0.5, corrected agent(s) -1.
        - A correction that yields the same or worse results: reviewer(s) -1, corrected
          agent(s) +2 (compensating them for being wrongly corrected).
        """
        scores: dict[str, float] = {}
        events: list[ScoreEvent] = []
        by_target: dict[str, list[PeerReview]] = {}
        for review in peer_reviews:
            by_target.setdefault(review.target_group_id, []).append(review)

        for origin_id, reviews in by_target.items():
            baseline = phase1_analyses[origin_id].baseline_confidence
            post_review_confidence = round(
                sum(r.agreement_score for r in reviews) / len(reviews), 4
            )
            better = post_review_confidence > baseline
            reviewer_delta = 0.5 if better else -1.0
            corrected_delta = -1.0 if better else 2.0
            outcome = "better" if better else "same_or_worse"
            for review in reviews:
                if not review.has_correction:
                    continue
                for m in review.reviewer_members:
                    scores[m] = scores.get(m, 0.0) + reviewer_delta
                for m in review.target_members:
                    scores[m] = scores.get(m, 0.0) + corrected_delta
                events.append(
                    ScoreEvent(
                        origin_group_id=origin_id,
                        reviewer_group_id=review.reviewer_group_id,
                        reviewer_members=review.reviewer_members,
                        corrected_members=review.target_members,
                        baseline_confidence=baseline,
                        post_review_confidence=post_review_confidence,
                        outcome=outcome,
                        reviewer_delta=reviewer_delta,
                        corrected_delta=corrected_delta,
                    )
                )
        return scores, events

    def _finalize(
        self,
        group: Group,
        origin_ids: list[str],
        phase1_analyses: dict[str, GroupAnalysis],
        relevant_reviews: list[PeerReview],
    ) -> FinalAnalysis:
        merged_signals: dict[str, Counter] = {}
        recs: list[str] = []
        seen: set[str] = set()
        for origin_id in origin_ids:
            analysis = phase1_analyses[origin_id]
            for sector, bias in analysis.aggregated_signals.items():
                merged_signals.setdefault(sector, Counter())[bias] += 1
            for r in analysis.top_recommendations:
                if r not in seen:
                    seen.add(r)
                    recs.append(r)

        for review in relevant_reviews:
            for comment in review.comments:
                if comment not in seen:
                    seen.add(comment)
                    recs.append(f"Peer review: {comment}")

        consensus_signals: dict[str, str] = {}
        for sector, counts in merged_signals.items():
            top = counts.most_common()
            consensus_signals[sector] = (
                "MIXED" if len(top) > 1 and top[0][1] == top[1][1] else top[0][0]
            )

        if relevant_reviews:
            confidence = round(
                sum(r.agreement_score for r in relevant_reviews) / len(relevant_reviews), 2
            )
        else:
            confidence = 0.5

        final_summary = (
            f"Group {group.group_id} ({', '.join(group.members)}) finalized analysis for "
            f"original group(s) {', '.join(origin_ids)} with {len(relevant_reviews)} peer "
            f"review(s); confidence {confidence:.0%}."
        )

        return FinalAnalysis(
            group_id=group.group_id,
            members=group.members,
            origin_group_ids=origin_ids,
            final_summary=final_summary,
            consensus_signals=consensus_signals,
            confidence_score=confidence,
            final_recommendations=recs[:10],
            peer_reviews_considered=len(relevant_reviews),
        )

    def collaborate(self) -> CollaborationReport:
        outputs = self._run_agents()

        phase1_groups = self._make_groups("P1")
        phase1_analyses = {
            g.group_id: self._build_group_analysis(g, outputs) for g in phase1_groups
        }
        member_to_group1 = {m: g.group_id for g in phase1_groups for m in g.members}

        phase2_groups = self._make_groups("P2")
        peer_reviews = self._build_peer_reviews(
            phase2_groups, member_to_group1, phase1_analyses, outputs
        )

        phase3_groups = self._make_groups("P3")
        finals: list[FinalAnalysis] = []
        for g in phase3_groups:
            origin_ids = sorted({member_to_group1[m] for m in g.members})
            relevant_reviews = [pr for pr in peer_reviews if pr.target_group_id in origin_ids]
            finals.append(self._finalize(g, origin_ids, phase1_analyses, relevant_reviews))

        agent_scores, score_events = self._score_agents(phase1_analyses, peer_reviews)

        return CollaborationReport(
            agent_names=self.agent_names,
            outputs=outputs,
            phase1_groups=phase1_groups,
            phase1_analyses=phase1_analyses,
            phase2_groups=phase2_groups,
            peer_reviews=peer_reviews,
            phase3_groups=phase3_groups,
            final_analyses=finals,
            agent_scores=agent_scores,
            score_events=score_events,
        )

    @staticmethod
    def to_dict(report: CollaborationReport) -> dict[str, Any]:
        errored = [o.name for o in report.outputs.values() if o.error]
        overall_confidence = (
            round(
                sum(f.confidence_score for f in report.final_analyses)
                / len(report.final_analyses),
                2,
            )
            if report.final_analyses
            else 0.0
        )
        expert_summary = (
            f"{len(report.agent_names)} agents collaborated across "
            f"{len(report.phase1_groups)} initial groups, {len(report.peer_reviews)} peer "
            f"reviews, and {len(report.final_analyses)} finalized groups. "
            f"Overall confidence {overall_confidence:.0%}."
            + (f" Errors: {', '.join(errored)}." if errored else "")
        )
        return {
            "meta": {
                "agent": "Multi-Agent Collaboration Coordinator",
                "analyzed_at": report.analyzed_at,
                "agents_involved": report.agent_names,
                "expert_summary": expert_summary,
                "overall_confidence": overall_confidence,
            },
            "phase1_groups": [
                {"group_id": g.group_id, "members": g.members} for g in report.phase1_groups
            ],
            "phase1_analyses": [
                {
                    "group_id": a.group_id,
                    "members": a.members,
                    "combined_summary": a.combined_summary,
                    "aggregated_signals": a.aggregated_signals,
                    "top_recommendations": a.top_recommendations,
                    "errors": a.errors,
                }
                for a in report.phase1_analyses.values()
            ],
            "phase2_groups": [
                {"group_id": g.group_id, "members": g.members} for g in report.phase2_groups
            ],
            "peer_reviews": [
                {
                    "reviewer_group_id": r.reviewer_group_id,
                    "reviewer_members": r.reviewer_members,
                    "target_group_id": r.target_group_id,
                    "target_members": r.target_members,
                    "agreement_score": r.agreement_score,
                    "comments": r.comments,
                    "self_review": r.self_review,
                    "has_correction": r.has_correction,
                }
                for r in report.peer_reviews
            ],
            "phase3_groups": [
                {"group_id": g.group_id, "members": g.members} for g in report.phase3_groups
            ],
            "final_analyses": [
                {
                    "group_id": f.group_id,
                    "members": f.members,
                    "origin_group_ids": f.origin_group_ids,
                    "final_summary": f.final_summary,
                    "consensus_signals": f.consensus_signals,
                    "confidence_score": f.confidence_score,
                    "final_recommendations": f.final_recommendations,
                    "peer_reviews_considered": f.peer_reviews_considered,
                }
                for f in report.final_analyses
            ],
            "agent_scores": dict(sorted(report.agent_scores.items(), key=lambda kv: -kv[1])),
            "score_events": [
                {
                    "origin_group_id": e.origin_group_id,
                    "reviewer_group_id": e.reviewer_group_id,
                    "reviewer_members": e.reviewer_members,
                    "corrected_members": e.corrected_members,
                    "baseline_confidence": e.baseline_confidence,
                    "post_review_confidence": e.post_review_confidence,
                    "outcome": e.outcome,
                    "reviewer_delta": e.reviewer_delta,
                    "corrected_delta": e.corrected_delta,
                }
                for e in report.score_events
            ],
            "market_signals": [
                {"sector": sector, "tickers": [], "bias": bias, "reason": f.final_summary}
                for f in report.final_analyses
                for sector, bias in f.consensus_signals.items()
            ],
            "recommendations": [
                r for f in report.final_analyses for r in f.final_recommendations
            ][:15],
        }

    def run(self, output: Path | None = None) -> dict[str, Any]:
        report = self.collaborate()
        result = self.to_dict(report)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result


def run_collaboration_analysis(
    output: Path | None = None,
    agent_names: list[str] | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    return CollaborationCoordinator(agent_names=agent_names, seed=seed).run(output=output)
