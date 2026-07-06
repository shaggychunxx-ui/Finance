"""
Wisdom & Behavioral Judgment Expert Agent
=========================================
Synthesizes philosophical wisdom and psychological decision science into a
practical operating framework for judgment, reflection, emotional regulation,
and compassionate action.

Scope: structured wisdom frameworks and repeatable cognitive-behavioral
protocols that other agents or operators can study and implement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base import BaseExpert

PHILOSOPHICAL_PILLARS: list[dict[str, str]] = [
    {
        "id": "sophia",
        "name": "Sophia",
        "definition": "Theoretical wisdom aimed at universal truth and first principles.",
        "mechanics": "Analytical, contemplative, and detached from immediate utility.",
        "implementation": "Ask what is true before asking what is expedient.",
    },
    {
        "id": "phronesis",
        "name": "Phronesis",
        "definition": "Practical wisdom that identifies the best action in difficult human situations.",
        "mechanics": "Contextual, flexible, and action-oriented.",
        "implementation": "Translate principles into situation-specific judgment and timing.",
    },
]

BERLIN_WISDOM_CRITERIA: list[dict[str, str]] = [
    {
        "id": "factual_knowledge",
        "name": "Factual Knowledge",
        "focus": "Deep knowledge of human nature, tradeoffs, and life transitions.",
        "agent_application": "Maintain grounded models of incentives, behavior, and context.",
    },
    {
        "id": "procedural_knowledge",
        "name": "Procedural Knowledge",
        "focus": "Strategies for managing conflict, ambiguity, and dilemmas.",
        "agent_application": "Prefer process discipline over impulsive reaction.",
    },
    {
        "id": "lifespan_context",
        "name": "Life-Span Contextualism",
        "focus": "Interpret problems through age, culture, history, and changing conditions.",
        "agent_application": "Adjust judgments to cycle, regime, and stakeholder context.",
    },
    {
        "id": "relativism",
        "name": "Value Relativism",
        "focus": "Respect multiple legitimate perspectives without collapsing into nihilism.",
        "agent_application": "Generate competing interpretations before acting.",
    },
    {
        "id": "uncertainty",
        "name": "Uncertainty Management",
        "focus": "Operate intelligently despite incomplete information and unpredictability.",
        "agent_application": "Use contingencies, probability ranges, and reversible actions.",
    },
]

THREE_DIMENSIONAL_WISDOM_SCALE: list[dict[str, str]] = [
    {
        "id": "cognitive",
        "name": "Cognitive Dimension",
        "focus": "Desire to know the truth behind appearances and comforting illusions.",
        "agent_application": "Favor accuracy over ego defense.",
    },
    {
        "id": "reflective",
        "name": "Reflective Dimension",
        "focus": "Objective self-examination of bias, motive, and blind spots.",
        "agent_application": "Audit assumptions before escalating confidence.",
    },
    {
        "id": "affective",
        "name": "Affective Dimension",
        "focus": "Compassion, sympathy, and concern for others after self-centeredness drops.",
        "agent_application": "Recommend actions that preserve dignity while solving the problem.",
    },
]

CULTIVATION_LOOP: list[dict[str, str]] = [
    {
        "step": "experience",
        "description": "A charged event or dilemma occurs.",
        "implementation": "Capture the facts, stakes, and emotional trigger.",
    },
    {
        "step": "reaction",
        "description": "An immediate emotional or defensive reaction appears.",
        "implementation": "Name the feeling before letting it drive the decision.",
    },
    {
        "step": "evaluation",
        "description": "Metacognition inspects the reaction and the story behind it.",
        "implementation": "Ask what bias, fear, or attachment is distorting judgment.",
    },
    {
        "step": "revision",
        "description": "The mental model is updated and a wiser action is selected.",
        "implementation": "Act on a revised view that balances truth, timing, and care.",
    },
]

DISTANCING_INTERVENTIONS: list[dict[str, str]] = [
    {
        "id": "illeism",
        "name": "Illeism",
        "mechanism": "Refer to yourself in the third person to reduce emotional fusion.",
        "agent_application": "Reframe: 'What should Alex do here?' instead of 'What should I do?'",
    },
    {
        "id": "spatial_distancing",
        "name": "Spatial Distancing",
        "mechanism": "Imagine the problem from a bird's-eye or future vantage point.",
        "agent_application": "Assess the decision as if observing it from above or six months later.",
    },
    {
        "id": "wise_advisor",
        "name": "Wise-Advisor Perspective",
        "mechanism": "Answer the problem as if advising another person you care about.",
        "agent_application": "Convert self-threat into principle-guided counsel.",
    },
]

DIALECTICAL_TENSIONS: list[dict[str, str]] = [
    {
        "tension": "Truth and compassion",
        "integration": "Say what is real without weaponizing honesty.",
    },
    {
        "tension": "Boundaries and empathy",
        "integration": "Protect what matters while remaining humane toward others.",
    },
    {
        "tension": "Conviction and humility",
        "integration": "Act decisively while staying corrigible.",
    },
    {
        "tension": "Speed and reflection",
        "integration": "Move promptly without surrendering metacognition.",
    },
]

FAILURE_MODES: list[dict[str, str]] = [
    {
        "missing_capability": "Intellectual humility",
        "failure_mode": "Fanaticism, overconfidence, and cognitive stagnation.",
        "corrective": "State what is unknown and actively seek disconfirming evidence.",
    },
    {
        "missing_capability": "Emotional regulation",
        "failure_mode": "Impulsivity, burnout, and reactive decision-making.",
        "corrective": "Pause, reappraise, and separate the event from the first reaction.",
    },
    {
        "missing_capability": "Compassion",
        "failure_mode": "Instrumental cruelty, narcissism, and social decay.",
        "corrective": "Include the dignity and downstream wellbeing of others in the decision.",
    },
]

PRACTICE_PROTOCOLS: list[dict[str, Any]] = [
    {
        "name": "Two-Pass Judgment",
        "cadence": "per important decision",
        "steps": [
            "Pass 1: Sophia — identify the deepest truth, principle, or invariant.",
            "Pass 2: Phronesis — choose the most fitting action for this context and timing.",
        ],
    },
    {
        "name": "Post-Event Reflection",
        "cadence": "daily or after high-emotion events",
        "steps": [
            "Describe what happened.",
            "Name the emotion and trigger.",
            "Identify one bias or attachment.",
            "Rewrite the action you would endorse tomorrow.",
        ],
    },
    {
        "name": "Distancing Reset",
        "cadence": "during conflict or threat",
        "steps": [
            "Use illeism or a wise-advisor prompt.",
            "Take a bird's-eye or future-self perspective.",
            "Respond only after the frame becomes less self-protective.",
        ],
    },
]

WISDOM_FRAMEWORKS: dict[str, Any] = {
    "philosophical_pillars": PHILOSOPHICAL_PILLARS,
    "berlin_wisdom_paradigm": BERLIN_WISDOM_CRITERIA,
    "three_dimensional_wisdom_scale": THREE_DIMENSIONAL_WISDOM_SCALE,
    "cultivation_loop": CULTIVATION_LOOP,
    "distancing_interventions": DISTANCING_INTERVENTIONS,
    "dialectical_tensions": DIALECTICAL_TENSIONS,
    "failure_modes": FAILURE_MODES,
    "practice_protocols": PRACTICE_PROTOCOLS,
}


@dataclass
class WisdomAssessment:
    sophia_signal: str
    phronesis_signal: str
    reflective_signal: str
    emotional_regulation_signal: str
    compassion_signal: str
    distancing_signal: str
    dialectical_signal: str
    judgment_conclusion: str


@dataclass
class WisdomReport:
    conceptual_depth_score: float
    reflective_practice_score: float
    emotional_regulation_score: float
    compassionate_action_score: float
    decision_quality_score: float
    uncertainty_readiness_score: float
    regime_label: str
    assessment: WisdomAssessment
    expert_summary: str
    market_signals: list[dict[str, Any]]
    recommendations: list[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class WisdomBehavioralJudgmentExpert(BaseExpert):
    """Expert in practical wisdom, reflection, and disciplined judgment."""

    def __init__(self) -> None:
        super().__init__()

    @staticmethod
    def _assessment() -> WisdomAssessment:
        return WisdomAssessment(
            sophia_signal=(
                "Start with first principles: wise judgment begins by separating enduring truth "
                "from comforting narrative."
            ),
            phronesis_signal=(
                "Translate principles into context-sensitive action that fits timing, stakes, "
                "and human fragility."
            ),
            reflective_signal=(
                "Use metacognitive review to expose bias, status anxiety, and self-serving stories "
                "before acting."
            ),
            emotional_regulation_signal=(
                "Wise performance improves when reaction time is slowed long enough for reappraisal "
                "and parasympathetic recovery."
            ),
            compassion_signal=(
                "Compassion is treated as a decision constraint: outcomes should solve the problem "
                "without unnecessary humiliation or harm."
            ),
            distancing_signal=(
                "When self-threat rises, use illeism, wise-advisor framing, or bird's-eye distance "
                "to reduce Solomon's Paradox."
            ),
            dialectical_signal=(
                "Hold opposing truths together long enough to produce a non-binary answer."
            ),
            judgment_conclusion=(
                "The strongest operating posture is integrative wisdom: truth-seeking, reflective "
                "distance, emotional regulation, and compassionate execution under uncertainty."
            ),
        )

    @staticmethod
    def _expert_summary(scores: dict[str, float]) -> str:
        return (
            "This agent converts philosophy and psychology of wisdom into a repeatable decision "
            f"discipline. It emphasizes conceptual depth ({scores['conceptual_depth_score']}/10), "
            f"reflection ({scores['reflective_practice_score']}/10), emotional regulation "
            f"({scores['emotional_regulation_score']}/10), and compassionate action "
            f"({scores['compassionate_action_score']}/10) so agents can act more wisely under "
            "ambiguity, conflict, and emotional pressure."
        )

    @staticmethod
    def _market_signals(assessment: WisdomAssessment) -> list[dict[str, Any]]:
        return [
            {
                "sector": "Decision Process",
                "bias": "reflective",
                "tickers": [],
                "reason": assessment.reflective_signal,
            },
            {
                "sector": "Emotional Discipline",
                "bias": "regulated",
                "tickers": [],
                "reason": assessment.emotional_regulation_signal,
            },
            {
                "sector": "Compassionate Action",
                "bias": "pro-social",
                "tickers": [],
                "reason": assessment.compassion_signal,
            },
        ]

    @staticmethod
    def _recommendations(assessment: WisdomAssessment) -> list[str]:
        return [
            "Run a two-pass decision review: first identify the truest principle, then choose the most context-appropriate action.",
            "After emotionally charged events, complete the experience → reaction → evaluation → revision loop before making the next move.",
            "Use third-person self-talk or a wise-advisor prompt whenever self-interest threatens judgment quality.",
            "Force one dialectical question into every major dilemma: what two seemingly opposing truths are both present here?",
            "Treat compassion as an operating requirement, not a mood — preserve dignity while solving the underlying problem.",
            assessment.judgment_conclusion,
        ]

    def analyze(self) -> WisdomReport:
        scores = {
            "conceptual_depth_score": 9.4,
            "reflective_practice_score": 9.2,
            "emotional_regulation_score": 8.9,
            "compassionate_action_score": 8.8,
            "decision_quality_score": 9.3,
            "uncertainty_readiness_score": 9.1,
        }
        assessment = self._assessment()
        return WisdomReport(
            conceptual_depth_score=scores["conceptual_depth_score"],
            reflective_practice_score=scores["reflective_practice_score"],
            emotional_regulation_score=scores["emotional_regulation_score"],
            compassionate_action_score=scores["compassionate_action_score"],
            decision_quality_score=scores["decision_quality_score"],
            uncertainty_readiness_score=scores["uncertainty_readiness_score"],
            regime_label="Integrative wisdom discipline",
            assessment=assessment,
            expert_summary=self._expert_summary(scores),
            market_signals=self._market_signals(assessment),
            recommendations=self._recommendations(assessment),
        )

    def to_dict(self, report: WisdomReport) -> dict[str, Any]:
        a = report.assessment
        return {
            "meta": {
                "agent": "Wisdom & Behavioral Judgment Expert",
                "analyzed_at": report.analyzed_at,
                "data_sources": [
                    "Aristotle's Nicomachean Ethics",
                    "Berlin Wisdom Paradigm",
                    "Three-Dimensional Wisdom Scale",
                    "Solomon's Paradox research",
                ],
                "expert_summary": report.expert_summary,
                "temperature": self.temperature,
            },
            "philosophical_pillars": PHILOSOPHICAL_PILLARS,
            "berlin_wisdom_paradigm": BERLIN_WISDOM_CRITERIA,
            "three_dimensional_wisdom_scale": THREE_DIMENSIONAL_WISDOM_SCALE,
            "cultivation_loop": CULTIVATION_LOOP,
            "distancing_interventions": DISTANCING_INTERVENTIONS,
            "dialectical_tensions": DIALECTICAL_TENSIONS,
            "failure_modes": FAILURE_MODES,
            "practice_protocols": PRACTICE_PROTOCOLS,
            "wisdom_assessment": {
                "sophia_signal": a.sophia_signal,
                "phronesis_signal": a.phronesis_signal,
                "reflective_signal": a.reflective_signal,
                "emotional_regulation_signal": a.emotional_regulation_signal,
                "compassion_signal": a.compassion_signal,
                "distancing_signal": a.distancing_signal,
                "dialectical_signal": a.dialectical_signal,
                "judgment_conclusion": a.judgment_conclusion,
            },
            "metrics": {
                "conceptual_depth_score": report.conceptual_depth_score,
                "reflective_practice_score": report.reflective_practice_score,
                "emotional_regulation_score": report.emotional_regulation_score,
                "compassionate_action_score": report.compassionate_action_score,
                "decision_quality_score": report.decision_quality_score,
                "uncertainty_readiness_score": report.uncertainty_readiness_score,
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
            catalog = output.parent / "wisdom_frameworks.json"
            catalog.write_text(
                json.dumps(WISDOM_FRAMEWORKS, indent=2),
                encoding="utf-8",
            )
        return result


def run_wisdom_analysis(output: Path | None = None) -> dict[str, Any]:
    return WisdomBehavioralJudgmentExpert().run(output=output)
