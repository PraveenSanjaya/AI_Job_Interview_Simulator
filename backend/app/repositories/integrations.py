"""Data access for connected sources and their analyses (always scoped by user)."""

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IntegrationAnalysis, IntegrationSource
from app.models.enums import IntegrationKind


class IntegrationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_source(
        self, user_id: uuid.UUID, kind: IntegrationKind
    ) -> IntegrationSource | None:
        result = await self._session.execute(
            select(IntegrationSource).where(
                IntegrationSource.user_id == user_id, IntegrationSource.kind == kind
            )
        )
        return result.scalar_one_or_none()

    async def replace_source(
        self, user_id: uuid.UUID, kind: IntegrationKind, source_ref: str, snapshot: dict[str, Any]
    ) -> IntegrationSource:
        """Delete any existing source of this kind (and, by cascade, analyses derived from
        it) and store the new one. The caller commits."""
        await self._session.execute(
            delete(IntegrationSource).where(
                IntegrationSource.user_id == user_id, IntegrationSource.kind == kind
            )
        )
        source = IntegrationSource(
            user_id=user_id, kind=kind, source_ref=source_ref, snapshot=snapshot
        )
        self._session.add(source)
        await self._session.flush()
        return source

    async def delete_source(self, user_id: uuid.UUID, kind: IntegrationKind) -> bool:
        result = await self._session.execute(
            delete(IntegrationSource).where(
                IntegrationSource.user_id == user_id, IntegrationSource.kind == kind
            )
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    def add_analysis(self, analysis: IntegrationAnalysis) -> None:
        self._session.add(analysis)

    async def get_analysis(
        self, user_id: uuid.UUID, analysis_id: uuid.UUID
    ) -> IntegrationAnalysis | None:
        result = await self._session.execute(
            select(IntegrationAnalysis).where(
                IntegrationAnalysis.id == analysis_id, IntegrationAnalysis.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def list_analyses(self, user_id: uuid.UUID) -> list[IntegrationAnalysis]:
        result = await self._session.execute(
            select(IntegrationAnalysis)
            .where(IntegrationAnalysis.user_id == user_id)
            .order_by(IntegrationAnalysis.created_at.desc())
        )
        return list(result.scalars())

    async def delete_analysis(self, user_id: uuid.UUID, analysis_id: uuid.UUID) -> bool:
        result = await self._session.execute(
            delete(IntegrationAnalysis).where(
                IntegrationAnalysis.id == analysis_id, IntegrationAnalysis.user_id == user_id
            )
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]
