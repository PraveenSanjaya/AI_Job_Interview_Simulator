"""Response models for resumes. Internal fields (storage key, hash) are never exposed."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import FailureStage, ResumeStatus


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
