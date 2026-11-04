"""Mock interview sessions, questions, answers, evaluations and reports.

Candidate answers are personal, untrusted text: they are stored as data, never logged, and
deleted with the session or user. A session keeps a snapshot of the job it targeted (and
only a nullable reference to it), so reports stay meaningful if the job is edited or
deleted later.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.types import UTCDateTime
from app.models.base import Base
from app.models.enums import EvaluationStatus, InterviewStatus, SessionDifficulty
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin, str_enum, utcnow


class InterviewSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "interview_sessions"
    __table_args__ = (Index("ix_interview_sessions_user_id_created_at", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # The job is optional and only referenced; ``job_snapshot`` keeps what was used.
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("job_descriptions.id", ondelete="SET NULL"), nullable=True
    )
    job_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    interview_types: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    difficulty: Mapped[SessionDifficulty] = mapped_column(
        str_enum(SessionDifficulty), nullable=False
    )
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    max_followups: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[InterviewStatus] = mapped_column(
        str_enum(InterviewStatus), default=InterviewStatus.CREATED, nullable=False
    )
    # "ai" or "question_bank"; why AI is not used is explained by ``ai_status``.
    mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    use_ai: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    consent_external_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    scoring_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # Increased by every accepted answer; guards against concurrent submissions.
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_activity_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, nullable=False
    )


class InterviewQuestion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "interview_questions"
    __table_args__ = (
        UniqueConstraint("session_id", "main_index", "followup_index"),
        Index("ix_interview_questions_session_id", "session_id"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    main_index: Mapped[int] = mapped_column(Integer, nullable=False)
    followup_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # ai | question_bank
    followup_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    skill_tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    # Expected points are never shown while the interview runs (no answer leakage).
    expected_points: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    asked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    @property
    def is_followup(self) -> bool:
        return self.followup_index > 0


class InterviewAnswer(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "interview_answers"

    question_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("interview_questions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("interview_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    skipped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class InterviewEvaluation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "interview_evaluations"

    answer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("interview_answers.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("interview_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[EvaluationStatus] = mapped_column(str_enum(EvaluationStatus), nullable=False)
    # Why there is no evaluation (``unavailable``/``failed``/``not_evaluated``).
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class InterviewReport(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "interview_reports"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("interview_sessions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    overall_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
