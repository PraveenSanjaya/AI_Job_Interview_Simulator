"""Connected public sources (GitHub profile, portfolio site) and their AI analyses.

``IntegrationSource.snapshot`` holds *observed facts* fetched from the public source
(never AI output). ``IntegrationAnalysis.result`` holds computed facts plus clearly
separated AI-generated assessment. Both are personal data owned by one user and are
deleted with the source/user.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.types import UTCDateTime
from app.models.base import Base
from app.models.enums import IntegrationKind
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin, str_enum, utcnow

if TYPE_CHECKING:
    from app.models.user import User


class IntegrationSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One connected source per kind per user (re-connecting replaces it)."""

    __tablename__ = "integration_sources"
    __table_args__ = (UniqueConstraint("user_id", "kind"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[IntegrationKind] = mapped_column(str_enum(IntegrationKind), nullable=False)
    # GitHub login, or the portfolio URL exactly as validated and normalised.
    source_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

    user: Mapped["User"] = relationship(back_populates="integration_sources")


class IntegrationAnalysis(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "integration_analyses"
    __table_args__ = (Index("ix_integration_analyses_user_id_created_at", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Analyses are derived from these inputs, so they are deleted with them.
    github_source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("integration_sources.id", ondelete="CASCADE"), nullable=True
    )
    portfolio_source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("integration_sources.id", ondelete="CASCADE"), nullable=True
    )
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("resumes.id", ondelete="CASCADE"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    consent_external_ai: Mapped[bool] = mapped_column(Boolean, nullable=False)
    input_truncated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
