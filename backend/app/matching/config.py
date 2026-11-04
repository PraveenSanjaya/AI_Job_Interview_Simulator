"""Scoring configuration. Stored with every match so a score can always be explained."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScoringWeights(BaseModel):
    """Relative importance of each dimension. They need not add up to 1: dimensions that
    cannot be assessed for a given job or candidate are left out and the rest are
    rescaled to fill 100 points."""

    model_config = ConfigDict(extra="forbid")

    required_skills: float = Field(default=0.40, ge=0, le=100)
    preferred_skills: float = Field(default=0.10, ge=0, le=100)
    experience: float = Field(default=0.15, ge=0, le=100)
    education: float = Field(default=0.05, ge=0, le=100)
    project_relevance: float = Field(default=0.10, ge=0, le=100)
    technology_alignment: float = Field(default=0.10, ge=0, le=100)
    evidence_strength: float = Field(default=0.10, ge=0, le=100)

    @model_validator(mode="after")
    def _some_weight(self) -> Self:
        if sum(self.model_dump().values()) <= 0:
            raise ValueError("At least one scoring weight must be greater than zero")
        return self


class ScoringConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weights: ScoringWeights = Field(default_factory=ScoringWeights)
    # Credit for a skill that is only listed (not shown in a project, job or repository).
    declared_only_credit: float = Field(default=0.5, ge=0, le=1)
    # Skills the job mentions without saying whether they are required: score them with
    # the preferred skills, or leave them out of the score (they are still reported).
    unspecified_importance: Literal["as_preferred", "ignore"] = "as_preferred"
    algorithm_version: str = "1"


def resolve_config(
    server_weights: dict[str, float] | None, request_weights: dict[str, float] | None
) -> ScoringConfig:
    """Built-in defaults, overridden by server settings, overridden by the request.
    Raises ``pydantic.ValidationError`` for unknown names or invalid values."""
    merged: dict[str, float] = {}
    merged.update(server_weights or {})
    merged.update(request_weights or {})
    return ScoringConfig(weights=ScoringWeights(**merged))
