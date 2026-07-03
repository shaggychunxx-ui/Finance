"""
Agent Prediction Scoring
========================
Shared accuracy-scoring rules applied uniformly across every intelligence
agent in this repository.

Rules
-----
- Every agent earns **+1.0 point** for a prediction that resolves accurate.
- Every agent loses **-1.5 points** for a prediction that resolves inaccurate.
- Agents must be detailed and truthful: a prediction is rejected before it can
  even be logged unless it carries a non-trivial rationale and at least one
  piece of supporting evidence (a data point, indicator, or source).

The asymmetric penalty (losing more than is gained) intentionally discourages
low-conviction or speculative calls and rewards agents that are careful and
well-supported before committing to a directional prediction.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

POINTS_ACCURATE = 1.0
POINTS_INACCURATE = -1.5

MIN_RATIONALE_LENGTH = 20
MIN_EVIDENCE_ITEMS = 1

DEFAULT_LEDGER_PATH = Path("output/agent_scoreboard.json")


class PredictionValidationError(ValueError):
    """Raised when a prediction is not detailed and truthful enough to log."""


@dataclass
class Prediction:
    """A single directional call made by an agent, awaiting resolution."""

    prediction_id: str
    agent: str
    subject: str
    call: str
    rationale: str
    evidence: list[str]
    horizon: str
    confidence: float
    created_at: str
    status: str = "pending"  # pending | accurate | inaccurate
    resolved_at: str | None = None
    actual_outcome: str | None = None
    points: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentScore:
    """Running tally of points and prediction accuracy for one agent."""

    agent: str
    points: float = 0.0
    accurate: int = 0
    inaccurate: int = 0
    pending: int = 0

    @property
    def resolved(self) -> int:
        return self.accurate + self.inaccurate

    @property
    def hit_rate(self) -> float | None:
        if self.resolved == 0:
            return None
        return round(self.accurate / self.resolved, 4)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["resolved"] = self.resolved
        data["hit_rate"] = self.hit_rate
        return data


def validate_prediction(rationale: str, evidence: list[str]) -> None:
    """Enforce that a prediction is detailed and truthful before it is logged.

    - "Detailed": the rationale must be a substantive explanation, not a
      one-word guess.
    - "Truthful": the call must be backed by at least one concrete piece of
      evidence (an observed metric, indicator value, or cited source) rather
      than an unsupported assertion.
    """
    if not rationale or len(rationale.strip()) < MIN_RATIONALE_LENGTH:
        raise PredictionValidationError(
            f"Prediction rationale must be detailed (>= {MIN_RATIONALE_LENGTH} "
            "characters); agents must explain the reasoning behind a call."
        )
    cleaned_evidence = [e.strip() for e in evidence if e and e.strip()]
    if len(cleaned_evidence) < MIN_EVIDENCE_ITEMS:
        raise PredictionValidationError(
            "Prediction must cite at least one piece of supporting evidence "
            "(data point, indicator, or source) to be truthful."
        )


class ScoringLedger:
    """Persistent, file-backed ledger of agent predictions and points.

    Each agent starts at 0 points. A prediction is recorded as *pending*
    until it is resolved as accurate (+1.0 point) or inaccurate (-1.5 points).
    """

    def __init__(self, ledger_path: Path | str = DEFAULT_LEDGER_PATH) -> None:
        self.ledger_path = Path(ledger_path)
        self._predictions: dict[str, Prediction] = {}
        self._load()

    def _load(self) -> None:
        if not self.ledger_path.exists():
            return
        try:
            raw = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for item in raw.get("predictions", []):
            pred = Prediction(**item)
            self._predictions[pred.prediction_id] = pred

    def _save(self) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "predictions": [p.to_dict() for p in self._predictions.values()],
            "leaderboard": [s.to_dict() for s in self.leaderboard()],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.ledger_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def record_prediction(
        self,
        agent: str,
        subject: str,
        call: str,
        rationale: str,
        evidence: list[str],
        horizon: str = "unspecified",
        confidence: float = 0.5,
    ) -> Prediction:
        """Log a new prediction. Raises PredictionValidationError if the
        prediction isn't detailed and truthful enough to score."""
        validate_prediction(rationale, evidence)
        pred = Prediction(
            prediction_id=str(uuid.uuid4()),
            agent=agent,
            subject=subject,
            call=call,
            rationale=rationale.strip(),
            evidence=[e.strip() for e in evidence if e and e.strip()],
            horizon=horizon,
            confidence=confidence,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._predictions[pred.prediction_id] = pred
        self._save()
        return pred

    def resolve_prediction(self, prediction_id: str, accurate: bool, actual_outcome: str | None = None) -> Prediction:
        """Resolve a pending prediction, awarding +1.0 (accurate) or -1.5
        (inaccurate) points to the agent that made the call."""
        pred = self._predictions.get(prediction_id)
        if pred is None:
            raise KeyError(f"Unknown prediction_id: {prediction_id}")
        if pred.status != "pending":
            raise ValueError(f"Prediction {prediction_id} is already resolved as {pred.status}")
        pred.status = "accurate" if accurate else "inaccurate"
        pred.points = POINTS_ACCURATE if accurate else POINTS_INACCURATE
        pred.actual_outcome = actual_outcome
        pred.resolved_at = datetime.now(timezone.utc).isoformat()
        self._save()
        return pred

    def leaderboard(self) -> list[AgentScore]:
        scores: dict[str, AgentScore] = {}
        for pred in self._predictions.values():
            score = scores.setdefault(pred.agent, AgentScore(agent=pred.agent))
            if pred.status == "accurate":
                score.points += pred.points
                score.accurate += 1
            elif pred.status == "inaccurate":
                score.points += pred.points
                score.inaccurate += 1
            else:
                score.pending += 1
        return sorted(scores.values(), key=lambda s: s.points, reverse=True)

    def pending_predictions(self, agent: str | None = None) -> list[Prediction]:
        preds = [p for p in self._predictions.values() if p.status == "pending"]
        if agent:
            preds = [p for p in preds if p.agent == agent]
        return preds
