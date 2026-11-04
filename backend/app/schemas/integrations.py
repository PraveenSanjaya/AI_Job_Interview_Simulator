"""Request/response models for public-source integrations."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ai.integration_schemas import IntegrationAnalysisResult
from app.integrations.github.snapshot import GitHubSnapshot
from app.integrations.portfolio.crawler import PortfolioSnapshot
from app.schemas.profile import ApplyToProfileRequest


class GitHubConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        min_length=1,
        max_length=300,
        description="A GitHub username, @username, or github.com profile URL",
    )


class GitHubSourceResponse(BaseModel):
    """What GitHub's public API reported. These are observed facts, not assessments."""

    source_ref: str
    fetched_at: datetime
    snapshot: GitHubSnapshot


class PortfolioConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(
        min_length=1,
        max_length=2000,
        description="Public http(s) address of your portfolio site",
    )


class PortfolioSourceResponse(BaseModel):
    """What the public pages said, with source URLs. Untrusted text, not verified facts."""

    source_ref: str
    fetched_at: datetime
    snapshot: PortfolioSnapshot


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include: list[Literal["github", "portfolio"]] | None = Field(
        default=None,
        max_length=2,
        description="Sources to analyse; omit to use every connected source",
    )
    resume_id: uuid.UUID | None = Field(
        default=None,
        description="Also compare against the verified details of this analysed resume",
    )
    allow_external_ai: bool = Field(
        default=False,
        description="Explicit consent to send the selected data to an external AI service",
    )


class AnalysisSummary(BaseModel):
    id: uuid.UUID
    created_at: datetime
    provider: str
    model: str
    sources_used: list[str]


class IntegrationAnalysisResponse(BaseModel):
    """``result.facts`` are computed from the sources; ``result.assessment`` is AI opinion
    whose checkable claims were verified against them."""

    id: uuid.UUID
    created_at: datetime
    provider: str
    model: str
    consent_external_ai: bool
    input_truncated: bool
    github_source_id: uuid.UUID | None
    portfolio_source_id: uuid.UUID | None
    resume_id: uuid.UUID | None
    result: IntegrationAnalysisResult
    # A starting point for the user to review; it has NOT been applied to the profile.
    profile_suggestion: ApplyToProfileRequest | None = None
    suggestion_notes: list[str] = Field(default_factory=list)
