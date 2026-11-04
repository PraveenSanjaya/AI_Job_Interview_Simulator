"""Resume metadata and CV analysis results.

Privacy: the uploaded file lives in storage (referenced by ``storage_key``) and the
extracted text is NOT persisted; it is re-extracted from the stored file when needed.
The analysis ``result`` contains personal data and is deleted with the resume.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.types import UTCDateTime
from app.models.base import Base
from app.models.enums import FailureStage, ResumeStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin, str_enum, utcnow

if TYPE_CHECKING:
    from app.models.user import User


class Resume(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "resumes"
    __table_args__ = (Index("ix_resumes_user_id_created_at", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_format: Mapped[str] = mapped_column(String(10), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)

    status: Mapped[ResumeStatus] = mapped_column(
        str_enum(ResumeStatus), default=ResumeStatus.UPLOADED, nullable=False
    )
    failure_stage: Mapped[FailureStage | None] = mapped_column(
        str_enum(FailureStage), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extracted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    analyzed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    user: Mapped["User"] = relationship(back_populates="resumes")
    analysis: Mapped["ResumeAnalysis | None"] = relationship(
        back_populates="resume", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )


class ResumeAnalysis(UUIDPrimaryKeyMixin, Base):
    """The current analysis of a resume (re-analysis replaces it)."""

    __tablename__ = "resume_analyses"

    resume_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("resumes.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    # Records that the user explicitly allowed sending the resume to an external AI.
    consent_external_ai: Mapped[bool] = mapped_column(Boolean, nullable=False)
    input_truncated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

    resume: Mapped[Resume] = relationship(back_populates="analysis")
