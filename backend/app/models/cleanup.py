"""Durable to-do list for work that must survive the deletion of the thing it is about."""

from datetime import datetime

from sqlalchemy import Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.types import UTCDateTime
from app.models.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin, utcnow


class PendingFileDeletion(UUIDPrimaryKeyMixin, Base):
    """Stored files that still have to be removed after an account was deleted.

    Deliberately has **no foreign key** to ``users``: the account is already gone when
    this record is needed, and it must not be removed by the cascade that deleted the
    account. It holds only the opaque storage namespace (the former user id in hex), no
    name, e-mail address or file name. It is written in the same transaction that
    deletes the account, so the intent to clean up cannot be lost.
    """

    __tablename__ = "pending_file_deletions"
    __table_args__ = (Index("ix_pending_file_deletions_next_attempt_at", "next_attempt_at"),)

    storage_namespace: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
