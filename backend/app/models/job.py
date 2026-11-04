"""Saved job descriptions, their structured analysis, and candidate-to-job match reports.

* ``JobDescription.description`` is untrusted third-party text; it is stored as data.
* ``JobAnalysis.result`` is the structured parse (requirements with quotes from the text).
  One current analysis per job; it is deleted when the description changes.
* ``JobMatch`` rows are **historical records**. They carry the scoring configuration, a
  description of the candidate evidence that was used and the whole report, and
  deliberately hold no foreign keys to candidate data, so later edits or deletions of the
  profile, resume or connected sources never change an old report. They are removed only
  with their job (or user).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.types import UTCDateTime
from app.models.base import Base
from app.models.enums import JobStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin, str_enum, utcnow


class JobDescription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "job_descriptions"
    __table_args__ = (Index("ix_job_descriptions_user_id_created_at", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    status: Mapped[JobStatus] = mapped_column(
        str_enum(JobStatus), default=JobStatus.SAVED, nullable=False
    )
    # Digest of the text the current analysis was produced from (detects stale analyses).
    description_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class JobAnalysis(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "job_analyses"

    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("job_descriptions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    parser: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    consent_external_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    input_truncated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class JobMatch(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "job_matches"
    __table_args__ = (Index("ix_job_matches_job_id_created_at", "job_id", "created_at"),)

    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("job_descriptions.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # ``None`` when there was too little candidate evidence to score responsibly.
    overall_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    scoring_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # Which candidate evidence (and which versions of it) the score was computed from.
    evidence_used: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    ai_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    consent_external_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
