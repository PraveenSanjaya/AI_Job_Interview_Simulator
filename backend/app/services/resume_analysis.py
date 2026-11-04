"""Orchestrates CV analysis of a stored resume.

Lifecycle: extracted -> analyzing -> completed, or analyzing -> failed (analysis stage).
The analysis runs inside the request (bounded by the provider timeout); a background
worker can replace this later without changing the state model.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import LLMProvider
from app.ai.cv_analysis import CVAnalysisService
from app.ai.errors import AIConsentRequiredError, AIUnavailableError
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.documents.extract import ProcessingError, extract_text_async
from app.documents.validation import DocumentFormat
from app.models import Resume, ResumeAnalysis, User, UserProfile
from app.models.enums import FailureStage, ResumeStatus
from app.repositories.resumes import ResumeRepository
from app.schemas.profile import ApplyToProfileRequest, SkippedField
from app.services.profile import ProfileService
from app.services.resumes import ResumeService
from app.storage.base import StorageBackend, StorageError

# Never log resume text, extracted facts or filenames.
logger = logging.getLogger(__name__)

STALE_ANALYSIS_AFTER = timedelta(minutes=10)


@dataclass(frozen=True)
class ApplyOutcome:
    profile: UserProfile
    applied: dict[str, int]
    skipped: list[SkippedField]


class ResumeAnalysisService:
    def __init__(
        self,
        session: AsyncSession,
        storage: StorageBackend,
        provider: LLMProvider,
        max_input_chars: int,
    ) -> None:
        self._session = session
        self._storage = storage
        self._provider = provider
        self._resumes = ResumeRepository(session)
        self._lookup = ResumeService(session, storage, max_upload_bytes=1)
        self._cv = CVAnalysisService(provider, max_input_chars)

    async def analyze(self, user: User, resume_id: uuid.UUID, *, allow_external_ai: bool) -> Resume:
        resume = await self._lookup.get(user, resume_id)

        # Checked before any state change or data leaves the server.
        if not self._provider.available:
            raise AIUnavailableError("AI analysis is not configured on this server")
        if self._provider.is_external and not allow_external_ai:
            raise AIConsentRequiredError(
                "This resume would be sent to an external AI service. "
                "Set allow_external_ai=true to explicitly consent."
            )

        now = datetime.now(UTC)
        if not await self._resumes.claim_for_analysis(
            resume.id, user.id, now, now - STALE_ANALYSIS_AFTER
        ):
            await self._session.rollback()
            await self._session.refresh(resume)
            if resume.status is ResumeStatus.ANALYZING:
                raise ConflictError("Analysis is already in progress", code="analysis_in_progress")
            raise ConflictError(
                "Text could not be extracted from this resume, so it cannot be analysed",
                code="resume_not_extracted",
            )
        await self._session.commit()
        await self._session.refresh(resume)

        try:
            text = await self._load_text(resume)
            outcome = await self._cv.analyze(text)
        except AppError as error:
            await self._mark_failed(resume, error.code, error.message)
            raise
        except ProcessingError as error:
            await self._mark_failed(resume, error.code, error.message)
            raise ConflictError(error.message, code=error.code) from None
        except Exception:
            await self._mark_failed(resume, "internal_error", "Analysis failed unexpectedly")
            raise

        payload = outcome.result.model_dump(mode="json")
        analysis = resume.analysis
        if analysis is None:
            analysis = ResumeAnalysis(
                provider=self._provider.name,
                model=self._provider.model,
                consent_external_ai=allow_external_ai,
                input_truncated=outcome.input_truncated,
                result=payload,
            )
            resume.analysis = analysis
        else:  # re-analysis replaces the previous result
            analysis.provider = self._provider.name
            analysis.model = self._provider.model
            analysis.consent_external_ai = allow_external_ai
            analysis.input_truncated = outcome.input_truncated
            analysis.result = payload
            analysis.created_at = datetime.now(UTC)
        resume.status = ResumeStatus.COMPLETED
        resume.analyzed_at = datetime.now(UTC)
        await self._session.commit()
        return resume

    async def get_analysis(self, user: User, resume_id: uuid.UUID) -> ResumeAnalysis:
        resume = await self._lookup.get(user, resume_id)
        if resume.analysis is None:
            raise NotFoundError("This resume has not been analysed", code="analysis_not_found")
        return resume.analysis

    async def apply_to_profile(
        self, user: User, resume_id: uuid.UUID, data: ApplyToProfileRequest
    ) -> tuple[Resume, ApplyOutcome]:
        """Apply user-reviewed data to the user's own profile.

        Requires a completed analysis of the user's own resume. The server never
        applies extracted data by itself: it only applies what the user sends here.
        """
        resume = await self._lookup.get(user, resume_id)
        if resume.analysis is None:
            raise ConflictError(
                "Analyse the resume before applying it to your profile", code="analysis_required"
            )
        profile_service = ProfileService(self._session)
        profile, applied, skipped = await profile_service.apply_selected(user, data)
        return resume, ApplyOutcome(profile=profile, applied=applied, skipped=skipped)

    async def _load_text(self, resume: Resume) -> str:
        try:
            data = await self._storage.get(resume.storage_key)
        except StorageError:
            raise ProcessingError("file_missing", "The stored resume file is missing") from None
        result = await extract_text_async(data, DocumentFormat(resume.file_format))
        return result.text

    async def _mark_failed(self, resume: Resume, code: str, message: str) -> None:
        await self._session.rollback()
        await self._session.refresh(resume)
        resume.status = ResumeStatus.FAILED
        resume.failure_stage = FailureStage.ANALYSIS
        resume.error_code = code
        resume.error_message = message[:500]
        await self._session.commit()
        logger.warning("Resume analysis failed", extra={"error_code": code})
