"""Re-run or AI-enrich the analysis of a saved job.

Order of checks (nothing is sent anywhere until all pass): job owned -> AI provider
available -> consent for external providers. A failure at any step leaves the existing
analysis untouched.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import LLMProvider
from app.ai.errors import AIConsentRequiredError, AIUnavailableError
from app.ai.job_analysis import JobAIAnalyzer
from app.jobs.errors import JobNotFoundError, JobParseError
from app.jobs.parser import parse_job
from app.jobs.schemas import JobAnalysisResult
from app.models import JobAnalysis, User
from app.models.enums import JobStatus
from app.repositories.jobs import JobRepository

logger = logging.getLogger(__name__)


class JobAnalysisRunner:
    def __init__(self, session: AsyncSession, provider: LLMProvider, max_input_chars: int) -> None:
        self._session = session
        self._provider = provider
        self._repo = JobRepository(session)
        self._ai = JobAIAnalyzer(provider, max_input_chars)

    async def run(
        self, user: User, job_id: uuid.UUID, *, use_ai: bool, allow_external_ai: bool
    ) -> JobAnalysis:
        job = await self._repo.get_job(user.id, job_id)
        if job is None:
            raise JobNotFoundError
        if use_ai:
            if not self._provider.available:
                raise AIUnavailableError("AI analysis is not configured on this server")
            if self._provider.is_external and not allow_external_ai:
                raise AIConsentRequiredError(
                    "The job description would be sent to an external AI service. "
                    "Set allow_external_ai=true to explicitly consent."
                )

        try:
            parsed = parse_job(job.title, job.description)
        except Exception:
            logger.warning("Job parsing failed", extra={"job_id": str(job.id)})
            job.status = JobStatus.FAILED
            await self._repo.delete_analysis(user.id, job.id)
            await self._session.commit()
            raise JobParseError from None

        analysis = JobAnalysis(
            job_id=job.id,
            user_id=user.id,
            parser="deterministic",
            description_sha256=job.description_sha256,
            result=JobAnalysisResult(parsed=parsed).model_dump(mode="json"),
        )
        if use_ai:
            outcome = await self._ai.enrich(job.title, job.description, parsed)  # may raise
            analysis.parser = "deterministic+ai"
            analysis.provider = self._provider.name
            analysis.model = self._provider.model
            analysis.consent_external_ai = allow_external_ai
            analysis.input_truncated = outcome.input_truncated
            analysis.result = JobAnalysisResult(
                parsed=outcome.parsed, unverified_items_removed=outcome.unverified_items_removed
            ).model_dump(mode="json")

        job.status = JobStatus.PARSED
        await self._repo.replace_analysis(analysis)
        await self._session.commit()
        return analysis
