"""Response models for resumes. Internal fields (storage key, hash) are never exposed."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.ai.cv_schemas import CVAnalysisResult
from app.models.enums import FailureStage, ResumeStatus
from app.schemas.profile import ApplyToProfileRequest


class ResumeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    file_format: str
    size_bytes: int
    status: ResumeStatus
    failure_stage: FailureStage | None
    error_code: str | None
    error_message: str | None
    page_count: int | None
    char_count: int | None
    word_count: int | None
    has_analysis: bool
    created_at: datetime
    extracted_at: datetime | None
    analyzed_at: datetime | None


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_external_ai: bool = Field(
        default=False,
        description=(
            "Explicit consent to send this resume's text to an external AI service. "
            "Required whenever the configured provider is not local."
        ),
    )


class AnalysisResponse(BaseModel):
    """Analysis of one resume. ``result.facts`` are verified against the resume text;
    ``result.assessment`` is AI-generated opinion."""

    resume_id: uuid.UUID
    provider: str
    model: str
    consent_external_ai: bool
    input_truncated: bool
    created_at: datetime
    result: CVAnalysisResult
    # A starting point for the user to review/edit; it has NOT been applied to the profile.
    profile_suggestion: ApplyToProfileRequest | None = None
    suggestion_notes: list[str] = Field(default_factory=list)
