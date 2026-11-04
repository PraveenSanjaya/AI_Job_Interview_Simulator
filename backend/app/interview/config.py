"""Interview state machine and explicit, configurable scoring rules."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import InterviewStatus

# --------------------------------------------------------------- state machine

TRANSITIONS: dict[InterviewStatus, frozenset[InterviewStatus]] = {
    InterviewStatus.CREATED: frozenset(
        {InterviewStatus.IN_PROGRESS, InterviewStatus.CANCELLED, InterviewStatus.EXPIRED}
    ),
    InterviewStatus.IN_PROGRESS: frozenset(
        {InterviewStatus.COMPLETED, InterviewStatus.CANCELLED, InterviewStatus.INTERRUPTED}
    ),
    # An interrupted interview (idle for too long) can be resumed, finished early or dropped.
    InterviewStatus.INTERRUPTED: frozenset(
        {InterviewStatus.IN_PROGRESS, InterviewStatus.COMPLETED, InterviewStatus.CANCELLED}
    ),
    InterviewStatus.COMPLETED: frozenset(),
    InterviewStatus.CANCELLED: frozenset(),
    InterviewStatus.EXPIRED: frozenset(),
}


def sources_for(target: InterviewStatus) -> frozenset[InterviewStatus]:
    """States from which ``target`` may be entered."""
    return frozenset(src for src, targets in TRANSITIONS.items() if target in targets)


# --------------------------------------------------------------------- scoring

DIMENSIONS = (
    "technical_correctness",
    "relevance",
    "completeness",
    "problem_solving",
    "practical_application",
    "clarity",
    "evidence_examples",
)
# Objective content, approach, and subjective communication are reported separately.
GROUPS: dict[str, tuple[str, ...]] = {
    "knowledge": ("technical_correctness", "relevance", "completeness"),
    "approach": ("problem_solving", "practical_application"),
    "communication": ("clarity", "evidence_examples"),
}


class DimensionWeights(BaseModel):
    """Relative weights of the evaluation dimensions in a question's score. A dimension the
    evaluator could not judge for an answer is left out and the rest are rescaled."""

    model_config = ConfigDict(extra="forbid")

    technical_correctness: float = Field(default=0.30, ge=0, le=100)
    relevance: float = Field(default=0.15, ge=0, le=100)
    completeness: float = Field(default=0.15, ge=0, le=100)
    problem_solving: float = Field(default=0.15, ge=0, le=100)
    practical_application: float = Field(default=0.10, ge=0, le=100)
    clarity: float = Field(default=0.10, ge=0, le=100)
    evidence_examples: float = Field(default=0.05, ge=0, le=100)

    @model_validator(mode="after")
    def _some_weight(self) -> Self:
        if sum(self.model_dump().values()) <= 0:
            raise ValueError("At least one weight must be greater than zero")
        return self


class InterviewScoringConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weights: DimensionWeights = Field(default_factory=DimensionWeights)
    # A follow-up answer counts this much compared with its main question's answer (1.0).
    followup_weight: float = Field(default=0.5, ge=0, le=1)
    # Main questions the candidate explicitly skipped score 0; questions never asked are
    # excluded. Questions whose answers could not be evaluated are always excluded.
    skipped_counts_as_zero: bool = True
    strong_threshold: float = Field(default=7.5, ge=0, le=10)
    weak_threshold: float = Field(default=5.0, ge=0, le=10)
    algorithm_version: str = "1"

    @model_validator(mode="after")
    def _thresholds(self) -> Self:
        if self.weak_threshold > self.strong_threshold:
            raise ValueError("weak_threshold must not exceed strong_threshold")
        return self


def resolve_scoring(
    server: dict[str, object] | None, request: dict[str, object] | None
) -> InterviewScoringConfig:
    """Defaults, overridden by server settings, overridden by the request (weights merge per
    dimension). Raises ``pydantic.ValidationError`` for invalid input."""
    merged: dict[str, object] = {}
    weights: dict[str, object] = {}
    for source in (server, request):
        if not source:
            continue
        for key, value in source.items():
            if key == "weights" and isinstance(value, dict):
                weights.update(value)
            else:
                merged[key] = value
    if weights:
        merged["weights"] = weights
    return InterviewScoringConfig.model_validate(merged)
