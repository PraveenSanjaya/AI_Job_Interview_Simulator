"""Run, store, retrieve and apply analyses of connected public sources.

Order of checks (nothing is sent anywhere until all pass): AI provider available ->
requested sources connected -> CV (if requested) owned and analysed -> consent for
external providers.
"""

import uuid
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import LLMProvider
from app.ai.cv_schemas import CVAnalysisResult, ExtractedFacts
from app.ai.errors import AIConsentRequiredError, AIUnavailableError
from app.ai.integration_analysis import IntegrationAnalysisService
from app.core.exceptions import ConflictError, NotFoundError
from app.integrations.errors import SourceNotConnectedError
from app.integrations.github.snapshot import GitHubSnapshot
from app.integrations.portfolio.crawler import PortfolioSnapshot
from app.models import IntegrationAnalysis, IntegrationSource, Resume, User, UserProfile
from app.models.enums import IntegrationKind
from app.repositories.integrations import IntegrationRepository
from app.repositories.resumes import ResumeRepository
from app.schemas.profile import ApplyToProfileRequest, SkippedField
from app.services.profile import ProfileService

SourceName = Literal["github", "portfolio"]


class IntegrationAnalysisRunner:
    def __init__(self, session: AsyncSession, provider: LLMProvider, max_input_chars: int) -> None:
        self._session = session
        self._provider = provider
        self._repo = IntegrationRepository(session)
        self._resumes = ResumeRepository(session)
        self._analysis = IntegrationAnalysisService(provider, max_input_chars)

    async def run(
        self,
        user: User,
        *,
        include: list[SourceName] | None,
        resume_id: uuid.UUID | None,
        allow_external_ai: bool,
    ) -> IntegrationAnalysis:
        if not self._provider.available:
            raise AIUnavailableError("AI analysis is not configured on this server")

        github_source, portfolio_source = await self._load_sources(user, include)
        resume = await self._load_resume(user, resume_id)

        if self._provider.is_external and not allow_external_ai:
            raise AIConsentRequiredError(
                "Your connected profiles would be sent to an external AI service. "
                "Set allow_external_ai=true to explicitly consent."
            )

        profile: UserProfile = await ProfileService(self._session).get(user)
        cv_facts: ExtractedFacts | None = None
        if resume is not None and resume.analysis is not None:
            cv_facts = CVAnalysisResult.model_validate(resume.analysis.result).facts

        outcome = await self._analysis.analyze(
            github=GitHubSnapshot.model_validate(github_source.snapshot) if github_source else None,
            portfolio=(
                PortfolioSnapshot.model_validate(portfolio_source.snapshot)
                if portfolio_source
                else None
            ),
            cv=cv_facts,
            target_roles=list(profile.preferred_roles),
        )
        analysis = IntegrationAnalysis(
            user_id=user.id,
            github_source_id=github_source.id if github_source else None,
            portfolio_source_id=portfolio_source.id if portfolio_source else None,
            resume_id=resume.id if resume else None,
            provider=self._provider.name,
            model=self._provider.model,
            consent_external_ai=allow_external_ai,
            input_truncated=outcome.input_truncated,
            result=outcome.result.model_dump(mode="json"),
        )
        self._repo.add_analysis(analysis)
        await self._session.commit()
        return analysis

    async def _load_sources(
        self, user: User, include: list[SourceName] | None
    ) -> tuple[IntegrationSource | None, IntegrationSource | None]:
        wanted = set(include) if include is not None else {"github", "portfolio"}
        github = (
            await self._repo.get_source(user.id, IntegrationKind.GITHUB)
            if "github" in wanted
            else None
        )
        portfolio = (
            await self._repo.get_source(user.id, IntegrationKind.PORTFOLIO)
            if "portfolio" in wanted
            else None
        )
        if include is not None:  # an explicit request for something not connected is an error
            if "github" in wanted and github is None:
                raise SourceNotConnectedError("No github source is connected")
            if "portfolio" in wanted and portfolio is None:
                raise SourceNotConnectedError("No portfolio source is connected")
        if github is None and portfolio is None:
            raise ConflictError(
                "Connect a GitHub profile or portfolio site first", code="no_sources_connected"
            )
        return github, portfolio

    async def _load_resume(self, user: User, resume_id: uuid.UUID | None) -> Resume | None:
        if resume_id is None:
            return None
        resume = await self._resumes.get_for_user(resume_id, user.id)
        if resume is None:
            raise NotFoundError("Resume not found", code="resume_not_found")
        if resume.analysis is None:
            raise ConflictError(
                "Analyse the resume first so its verified details can be compared",
                code="resume_not_analyzed",
            )
        return resume

    async def get(self, user: User, analysis_id: uuid.UUID) -> IntegrationAnalysis:
        analysis = await self._repo.get_analysis(user.id, analysis_id)
        if analysis is None:
            raise NotFoundError("Analysis not found", code="analysis_not_found")
        return analysis

    async def list_all(self, user: User) -> list[IntegrationAnalysis]:
        return await self._repo.list_analyses(user.id)

    async def delete(self, user: User, analysis_id: uuid.UUID) -> None:
        if not await self._repo.delete_analysis(user.id, analysis_id):
            raise NotFoundError("Analysis not found", code="analysis_not_found")
        await self._session.commit()

    async def apply_to_profile(
        self, user: User, analysis_id: uuid.UUID, data: ApplyToProfileRequest
    ) -> tuple[UserProfile, dict[str, int], list[SkippedField]]:
        """Apply what the user approved (see ``ProfileService.apply_selected``)."""
        await self.get(user, analysis_id)  # ownership check
        return await ProfileService(self._session).apply_selected(user, data)
