"""Request/response models for job descriptions, their analysis and match reports."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.jobs.schemas import JobAnalysisResult
from app.models.enums import JobStatus

MAX_DESCRIPTION_CHARS = 30_000
MIN_DESCRIPTION_CHARS = 40

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Company = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Url = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Description = Annotated[str, Field(max_length=MAX_DESCRIPTION_CHARS)]


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title
    company: Company | None = None
    description: Description | None = Field(
        default=None,
        description="Paste the job text. Omit it to have the server read `source_url` instead.",
    )
    source_url: Url | None = Field(
        default=None,
        description="Public job posting address. Used to fetch the text only when "
        "`description` is omitted. Login-only and automation-restricted sites are refused.",
    )

    @model_validator(mode="after")
    def _needs_text_or_url(self) -> "JobCreate":
        if self.description is not None and not self.description.strip():
            self.description = None
        if self.description is None and self.source_url is None:
            raise ValueError("Provide the job description text or a public source_url")
        return self


class JobUpdate(BaseModel):
    """Only the fields you send are changed. ``company`` and ``source_url`` may be null."""

    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    company: Company | None = None
    description: Description | None = None
    source_url: Url | None = None

    @model_validator(mode="after")
    def _something_to_change(self) -> "JobUpdate":
        if not self.model_fields_set:
            raise ValueError("Send at least one field to change")
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title cannot be removed")
        if "description" in self.model_fields_set and (
            self.description is None or not self.description.strip()
        ):
            raise ValueError("description cannot be empty")
        return self


class JobResponse(BaseModel):
    id: uuid.UUID
    title: str
    company: str | None
    description: str
    source_url: str | None
    status: JobStatus
    has_analysis: bool
    created_at: datetime
    updated_at: datetime


class JobSummary(BaseModel):
    id: uuid.UUID
    title: str
    company: str | None
    source_url: str | None
    status: JobStatus
    created_at: datetime
    updated_at: datetime


class JobAnalysisResponse(BaseModel):
    job_id: uuid.UUID
    parser: str
    provider: str | None
    model: str | None
    consent_external_ai: bool
    input_truncated: bool
    created_at: datetime
    result: JobAnalysisResult


class AnalyzeJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use_ai: bool = Field(
        default=False,
        description="Also ask the configured AI provider to find items the built-in parser "
        "missed. Every AI item must quote the description and is dropped otherwise.",
    )
    allow_external_ai: bool = Field(
        default=False,
        description="Explicit consent, required when the AI provider is external, to send "
        "the job text to it.",
    )
