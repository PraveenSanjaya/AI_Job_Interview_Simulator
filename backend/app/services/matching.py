"""Run and store candidate-to-job matches.

A match is a *historical record*: the report, the scoring configuration and a description
of the candidate evidence used are stored together, with no foreign keys to candidate data.
Editing the profile, re-analysing a CV, reconnecting GitHub or deleting a resume later never
changes an existing match. Only the job's own deletion removes its matches.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.cv_schemas import CVAnalysisResult, ExtractedFacts
from app.core.config import Settings
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.integrations.errors import SourceNotConnectedError
from app.integrations.github.snapshot import GitHubSnapshot
from app.integrations.portfolio.crawler import PortfolioSnapshot
from app.jobs.errors import JobMatchNotFoundError, JobNotFoundError
from app.jobs.schemas import JobAnalysisResult
from app.matching.config import ScoringConfig, resolve_config
from app.matching.engine import compute_match
from app.matching.evidence import (
    CandidateProfile,
    ProfileEducation,
    ProfileProject,
    ProfileSkill,
    ProfileWork,
    build_candidate_evidence,
)
from app.matching.report import JobSnapshot, MatchReport
from app.models import (
    IntegrationSource,
    JobAnalysis,
    JobDescription,
    JobMatch,
    Resume,
    User,
    UserProfile,
)
from app.models.enums import IntegrationKind, JobStatus
from app.repositories.integrations import IntegrationRepository
from app.repositories.jobs import JobRepository
from app.repositories.resumes import ResumeRepository
from app.schemas.jobs import MatchRequest
from app.services.profile import ProfileService


class InvalidScoringWeightsError(AppError):
    status_code = 422
    code = "invalid_scoring_weights"


def to_candidate_profile(profile: UserProfile) -> CandidateProfile:
    """The confirmed profile as plain data (no contact details are carried over)."""
    return CandidateProfile(
        experience_level=profile.experience_level.value if profile.experience_level else None,
        preferred_roles=tuple(profile.preferred_roles),
        skills=tuple(ProfileSkill(s.name, s.category.value) for s in profile.skills),
        projects=tuple(
            ProfileProject(p.name, p.description, tuple(p.technologies)) for p in profile.projects
        ),
        work=tuple(
            ProfileWork(w.company, w.title, w.description, w.start_date, w.end_date, w.is_current)
            for w in profile.work_experience
        ),
        education=tuple(
            ProfileEducation(e.institution, e.degree, e.field_of_study) for e in profile.education
        ),
        certifications=tuple(c.name for c in profile.certifications),
    )


class MatchService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        today: Callable[[], date] = lambda: datetime.now(UTC).date(),
    ) -> None:
        self._session = session
        self._settings = settings
        self._today = today
        self._jobs = JobRepository(session)
        self._resumes = ResumeRepository(session)
        self._integrations = IntegrationRepository(session)

    # --------------------------------------------------------------- inputs

    async def _job_with_analysis(
        self, user: User, job_id: uuid.UUID
    ) -> tuple[JobDescription, JobAnalysis]:
        job = await self._jobs.get_job(user.id, job_id)
        if job is None:
            raise JobNotFoundError
        analysis = await self._jobs.get_analysis(user.id, job_id)
        if analysis is None or job.status != JobStatus.PARSED:
            raise ConflictError(
                "This job has no usable analysis yet. Re-run POST /jobs/{id}/analyze first.",
                code="job_not_analyzed",
            )
        return job, analysis

    async def _pick_resume(self, user: User, data: MatchRequest) -> Resume | None:
        wanted = data.include is None or "resume" in data.include
        if data.resume_id is not None:
            resume = await self._resumes.get_for_user(data.resume_id, user.id)
            if resume is None:
                raise NotFoundError("Resume not found", code="resume_not_found")
            if resume.analysis is None:
                raise ConflictError(
                    "Analyse the resume first so its verified details can be used",
                    code="resume_not_analyzed",
                )
            return resume
        if not wanted:
            return None
        for resume in await self._resumes.list_for_user(user.id):  # newest first
            if resume.analysis is not None:
                return resume
        if data.include is not None:
            raise ConflictError("You have no analysed resume yet", code="resume_not_analyzed")
        return None

    async def _source(
        self, user: User, kind: IntegrationKind, data: MatchRequest
    ) -> IntegrationSource | None:
        if data.include is not None and kind.value not in data.include:
            return None
        source = await self._integrations.get_source(user.id, kind)
        if source is None and data.include is not None:
            raise SourceNotConnectedError(f"No {kind.value} source is connected")
        return source

    # ------------------------------------------------------------------ run

    async def run(self, user: User, job_id: uuid.UUID, data: MatchRequest) -> JobMatch:
        job, analysis = await self._job_with_analysis(user, job_id)
        try:
            config = resolve_config(self._settings.match_weights, data.weights)
        except ValidationError:
            raise InvalidScoringWeightsError(
                "Invalid scoring weights: use known dimension names with values from 0 to 100, "
                "and at least one above zero"
            ) from None

        profile = await ProfileService(self._session).get(user)
        resume = await self._pick_resume(user, data)
        github_source = await self._source(user, IntegrationKind.GITHUB, data)
        portfolio_source = await self._source(user, IntegrationKind.PORTFOLIO, data)

        resume_facts: ExtractedFacts | None = None
        if resume is not None and resume.analysis is not None:
            resume_facts = CVAnalysisResult.model_validate(resume.analysis.result).facts
        github = GitHubSnapshot.model_validate(github_source.snapshot) if github_source else None
        portfolio = (
            PortfolioSnapshot.model_validate(portfolio_source.snapshot)
            if portfolio_source
            else None
        )

        evidence = build_candidate_evidence(
            profile=to_candidate_profile(profile),
            resume=resume_facts,
            github=github,
            portfolio=portfolio,
            today=self._today(),
        )
        evidence.not_available = self._unavailable(data, resume, github_source, portfolio_source)

        parsed = JobAnalysisResult.model_validate(analysis.result).parsed
        report = compute_match(
            job=JobSnapshot(
                job_id=str(job.id),
                title=job.title,
                company=job.company,
                description_sha256=job.description_sha256,
                analysis_parser=analysis.parser,
                seniority=parsed.seniority.level,
                seniority_basis=parsed.seniority.basis,
            ),
            parsed=parsed,
            evidence=evidence,
            config=config,
        )
        match = JobMatch(
            job_id=job.id,
            user_id=user.id,
            overall_score=report.score.score,
            confidence=report.score.confidence,
            scoring_config=config.model_dump(mode="json"),
            evidence_used=self._evidence_used(
                profile, resume, github_source, portfolio_source, job, analysis, report
            ),
            result={"report": report.model_dump(mode="json")},
        )
        self._jobs.add_match(match)
        await self._session.commit()
        return match

    @staticmethod
    def _unavailable(
        data: MatchRequest,
        resume: Resume | None,
        github: IntegrationSource | None,
        portfolio: IntegrationSource | None,
    ) -> dict[str, str]:
        def why(selected: object, name: str, missing: str) -> str:
            if data.include is not None and name not in data.include:
                return "excluded by request"
            return missing if selected is None else ""

        reasons = {
            "resume": why(resume, "resume", "no analysed resume"),
            "github": why(github, "github", "not connected"),
            "portfolio": why(portfolio, "portfolio", "not connected"),
        }
        return {name: reason for name, reason in reasons.items() if reason}

    @staticmethod
    def _evidence_used(
        profile: UserProfile,
        resume: Resume | None,
        github: IntegrationSource | None,
        portfolio: IntegrationSource | None,
        job: JobDescription,
        analysis: JobAnalysis,
        report: MatchReport,
    ) -> dict[str, Any]:
        """Identifies the exact versions of the inputs, without copying personal text."""
        return {
            "profile": {
                "updated_at": profile.updated_at.isoformat(),
                "skills": len(profile.skills),
                "projects": len(profile.projects),
                "work_experience": len(profile.work_experience),
                "education": len(profile.education),
                "certifications": len(profile.certifications),
            },
            "resume": (
                {
                    "resume_id": str(resume.id),
                    "analysis_id": str(resume.analysis.id),
                    "analyzed_at": resume.analyzed_at.isoformat() if resume.analyzed_at else None,
                }
                if resume is not None and resume.analysis is not None
                else None
            ),
            "github": (
                {
                    "source_id": str(github.id),
                    "login": github.source_ref,
                    "fetched_at": github.fetched_at.isoformat(),
                }
                if github
                else None
            ),
            "portfolio": (
                {
                    "source_id": str(portfolio.id),
                    "url": portfolio.source_ref,
                    "fetched_at": portfolio.fetched_at.isoformat(),
                }
                if portfolio
                else None
            ),
            "job": {
                "job_id": str(job.id),
                "title": job.title,
                "company": job.company,
                "description_sha256": job.description_sha256,
                "analysis_id": str(analysis.id),
                "analysis_parser": analysis.parser,
                "analysis_created_at": analysis.created_at.isoformat(),
            },
            "sources_used": [
                name
                for name, used in report.sources.model_dump().items()
                if name != "not_available" and used
            ],
            "sources_not_used": report.sources.not_available,
        }

    # ---------------------------------------------------------------- reads

    async def get(self, user: User, job_id: uuid.UUID, match_id: uuid.UUID) -> JobMatch:
        if await self._jobs.get_job(user.id, job_id) is None:
            raise JobNotFoundError
        match = await self._jobs.get_match(user.id, job_id, match_id)
        if match is None:
            raise JobMatchNotFoundError
        return match

    async def list_all(self, user: User, job_id: uuid.UUID) -> list[JobMatch]:
        if await self._jobs.get_job(user.id, job_id) is None:
            raise JobNotFoundError
        return await self._jobs.list_matches(user.id, job_id)


__all__ = ["InvalidScoringWeightsError", "MatchService", "ScoringConfig", "to_candidate_profile"]
