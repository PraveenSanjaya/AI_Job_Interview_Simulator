"""Reusable model columns and helpers."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import Enum, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.types import UTCDateTime


def utcnow() -> datetime:
    return datetime.now(UTC)


def str_enum(enum_cls: type[StrEnum], length: int = 20) -> Enum:
    """Portable string-backed enum (VARCHAR, no native PostgreSQL ENUM type).

    Storing values keeps migrations simple: adding a member needs no ALTER TYPE.
    """
    return Enum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda members: [member.value for member in members],
    )


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    # Python-side defaults keep values available after flush without a refresh,
    # which matters for async sessions where lazy loads are not allowed.
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )
