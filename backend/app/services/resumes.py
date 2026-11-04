"""Resume upload, extraction and lifecycle management."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.documents.extract import ProcessingError, extract_text_async
from app.documents.validation import validate_upload
from app.models import Resume, User
from app.models.enums import FailureStage, ResumeStatus
from app.repositories.resumes import ResumeRepository
from app.storage.base import StorageBackend, StorageError, new_storage_key

# Never log filenames, extracted text or contact details: they are personal data.
logger = logging.getLogger(__name__)


class ResumeService:
    def __init__(self, session: AsyncSession, storage: StorageBackend, max_upload_bytes: int):
        self._session = session
        self._storage = storage
        self._max_bytes = max_upload_bytes
        self._resumes = ResumeRepository(session)

    async def upload(self, user: User, filename: str | None, data: bytes) -> Resume:
        """Validate, store and extract an uploaded resume.

        Invalid files (wrong type, too large, malformed) are rejected and not stored.
        A well-formed file whose text cannot be extracted (scanned, password-protected,
        empty) is stored with ``status=failed`` and a specific ``error_code`` so the
        user can see why and delete it.
        """
        document = validate_upload(filename, data, self._max_bytes)
        key = new_storage_key(user.id)
        await self._storage.put(key, data)

        resume = Resume(
            user_id=user.id,
            display_name=document.display_name,
            file_format=document.format.value,
            size_bytes=document.size_bytes,
            sha256=document.sha256,
            storage_key=key,
            status=ResumeStatus.EXTRACTING,
            analysis=None,  # marks the relationship as loaded (no lazy IO under asyncio)
        )
        self._resumes.add(resume)
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            await self._discard_file(key)  # do not leave an unreferenced file behind
            raise

        try:
            result = await extract_text_async(data, document.format)
        except ProcessingError as error:
            resume.status = ResumeStatus.FAILED
            resume.failure_stage = FailureStage.EXTRACTION
            resume.error_code = error.code
            resume.error_message = error.message
        else:
            resume.status = ResumeStatus.EXTRACTED
            resume.page_count = result.page_count
            resume.char_count = result.char_count
            resume.word_count = result.word_count
            resume.extracted_at = datetime.now(UTC)
        await self._session.commit()
        return resume

    async def list(self, user: User) -> list[Resume]:
        return await self._resumes.list_for_user(user.id)

    async def get(self, user: User, resume_id: uuid.UUID) -> Resume:
        resume = await self._resumes.get_for_user(resume_id, user.id)
        if resume is None:
            # Same response for "not yours" and "does not exist".
            raise NotFoundError("Resume not found", code="resume_not_found")
        return resume

    async def delete(self, user: User, resume_id: uuid.UUID) -> None:
        """Delete the resume record, its analysis and the stored file."""
        resume = await self.get(user, resume_id)
        key = resume.storage_key
        await self._resumes.delete(resume)
        await self._session.commit()
        await self._discard_file(key)

    async def _discard_file(self, key: str) -> None:
        try:
            await self._storage.delete(key)
        except StorageError:
            # The database no longer references it; an orphan sweep can remove it later.
            logger.warning("Failed to delete stored resume file", extra={"storage_key": key})
