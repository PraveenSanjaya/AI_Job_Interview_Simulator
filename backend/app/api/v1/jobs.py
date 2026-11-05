"""Job descriptions: save, edit, list, delete, and read their structured analysis."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.ai.base import LLMProvider
from app.ai.match_advice import MatchAdvice
from app.api.deps import (
    CurrentUserDep,
    RateLimiterDep,
    SessionDep,
    SettingsDep,
    get_llm_provider,
)
from app.api.v1.integrations import get_page_fetcher
from app.integrations.portfolio.crawler import PageFetcher
from app.jobs.schemas import JobAnalysisResult
from app.matching.config import ScoringConfig
from app.matching.report import MatchReport
from app.models import JobAnalysis, JobDescription, JobMatch
from app.models.enums import JobStatus
from app.schemas.jobs import (
    AnalyzeJobRequest,
    JobAnalysisResponse,
    JobCreate,
    JobResponse,
    JobSummary,
    JobUpdate,
    MatchRequest,
    MatchResponse,
    MatchSummary,
)
from app.services.job_analysis import JobAnalysisRunner
from app.services.jobs import JobService
from app.services.matching import MatchService

router = APIRouter(prefix="/jobs", tags=["jobs"])


def get_job_service(
    session: SessionDep, pages: Annotated[PageFetcher, Depends(get_page_fetcher)]
) -> JobService:
    return JobService(session, pages)


JobServiceDep = Annotated[JobService, Depends(get_job_service)]


def get_analysis_runner(
    session: SessionDep,
    settings: SettingsDep,
    provider: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> JobAnalysisRunner:
    return JobAnalysisRunner(session, provider, settings.ai_max_input_chars)


AnalysisRunnerDep = Annotated[JobAnalysisRunner, Depends(get_analysis_runner)]


def get_match_service(
    session: SessionDep,
    settings: SettingsDep,
    provider: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> MatchService:
    return MatchService(session, settings, provider)


MatchServiceDep = Annotated[MatchService, Depends(get_match_service)]


def job_response(job: JobDescription) -> JobResponse:
    return JobResponse(
        id=job.id,
        title=job.title,
        company=job.company,
        description=job.description,
        source_url=job.source_url,
        status=job.status,
        has_analysis=job.status == JobStatus.PARSED,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def analysis_response(analysis: JobAnalysis) -> JobAnalysisResponse:
    return JobAnalysisResponse(
        job_id=analysis.job_id,
        parser=analysis.parser,
        provider=analysis.provider,
        model=analysis.model,
        consent_external_ai=analysis.consent_external_ai,
        input_truncated=analysis.input_truncated,
        created_at=analysis.created_at,
        result=JobAnalysisResult.model_validate(analysis.result),
    )


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    body: JobCreate, user: CurrentUserDep, service: JobServiceDep, limiter: RateLimiterDep
) -> JobResponse:
    """Save a job description and parse it (no AI involved).

    Paste the text in ``description``, or omit it and give a public ``source_url`` to have
    the server read the page with the same SSRF protections as portfolio fetching.
    Sites that forbid automated access or require a login (for example LinkedIn and
    Indeed) are refused with ``job_platform_not_supported``: paste the text instead.
    """
    await limiter.hit(f"jobs:user:{user.id}")
    return job_response(await service.create(user, body))


@router.get("", response_model=list[JobSummary])
async def list_jobs(user: CurrentUserDep, service: JobServiceDep) -> list[JobSummary]:
    return [
        JobSummary(
            id=j.id,
            title=j.title,
            company=j.company,
            source_url=j.source_url,
            status=j.status,
            created_at=j.created_at,
            updated_at=j.updated_at,
        )
        for j in await service.list_all(user)
    ]


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: uuid.UUID, user: CurrentUserDep, service: JobServiceDep) -> JobResponse:
    return job_response(await service.get(user, job_id))


@router.put("/{job_id}", response_model=JobResponse)
async def update_job(
    job_id: uuid.UUID,
    body: JobUpdate,
    user: CurrentUserDep,
    service: JobServiceDep,
    limiter: RateLimiterDep,
) -> JobResponse:
    """Change the fields you send. Changing the title, text or link re-parses the job and
    discards any earlier AI-enriched analysis (existing match reports are kept as
    historical records of what was compared at the time)."""
    await limiter.hit(f"jobs:user:{user.id}")
    return job_response(await service.update(user, job_id, body))


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(job_id: uuid.UUID, user: CurrentUserDep, service: JobServiceDep) -> None:
    """Delete the job together with its analysis and all of its match reports."""
    await service.delete(user, job_id)


@router.get("/{job_id}/analysis", response_model=JobAnalysisResponse)
async def get_job_analysis(
    job_id: uuid.UUID, user: CurrentUserDep, service: JobServiceDep
) -> JobAnalysisResponse:
    """The structured parse: every item quotes the sentence it came from."""
    return analysis_response(await service.get_analysis(user, job_id))


@router.post("/{job_id}/analyze", response_model=JobAnalysisResponse)
async def analyze_job(
    job_id: uuid.UUID,
    body: AnalyzeJobRequest,
    user: CurrentUserDep,
    runner: AnalysisRunnerDep,
    limiter: RateLimiterDep,
) -> JobAnalysisResponse:
    """Re-run the parse, optionally enriched by the AI provider (``use_ai=true``).

    The built-in parser always runs and needs no AI. With ``use_ai`` the model may add
    items the parser missed, but only ones that quote the description; the rest are
    dropped (``unverified_items_removed``). Errors: 503 ``ai_unavailable``, 403
    ``ai_consent_required`` (external provider without ``allow_external_ai``), 502
    ``invalid_ai_response``, 504 ``ai_timeout``, 429 ``ai_rate_limited``. On any error the
    previous analysis is kept.
    """
    await limiter.hit(f"job-analysis:user:{user.id}")
    analysis = await runner.run(
        user, job_id, use_ai=body.use_ai, allow_external_ai=body.allow_external_ai
    )
    return analysis_response(analysis)


# --------------------------------------------------------------------- matching


def match_response(match: JobMatch) -> MatchResponse:
    return MatchResponse(
        id=match.id,
        job_id=match.job_id,
        created_at=match.created_at,
        overall_score=match.overall_score,
        confidence=match.confidence,
        scoring_config=ScoringConfig.model_validate(match.scoring_config),
        evidence_used=match.evidence_used,
        report=MatchReport.model_validate(match.result["report"]),
        ai_advice=(
            MatchAdvice.model_validate(match.result["ai_advice"])
            if match.result.get("ai_advice")
            else None
        ),
        ai_provider=match.ai_provider,
        ai_model=match.ai_model,
        consent_external_ai=match.consent_external_ai,
    )


@router.post("/{job_id}/match", response_model=MatchResponse, status_code=status.HTTP_201_CREATED)
async def create_match(
    job_id: uuid.UUID,
    body: MatchRequest,
    user: CurrentUserDep,
    service: MatchServiceDep,
    limiter: RateLimiterDep,
) -> MatchResponse:
    """Compare your profile, analysed CV, GitHub and portfolio with this job.

    The result is computed by fixed rules (no AI) and stored as a historical report: later
    changes to your profile or sources never alter it. ``report.score.explanation`` shows
    how the score was calculated and ``scoring_config`` the weights used. A missing skill
    means *no evidence was found in the data on record*, not that you lack it. Nothing
    here predicts a hiring decision.

    With ``use_ai=true`` the configured AI provider also writes plain-language advice,
    stored separately in ``ai_advice``; it never changes the computed report. Errors:
    503 ``ai_unavailable``, 403 ``ai_consent_required`` (external provider without
    ``allow_external_ai``), 502 ``invalid_ai_response``, 504 ``ai_timeout``, 429
    ``ai_rate_limited``; on any of them no match is stored.
    """
    await limiter.hit(f"match:user:{user.id}")
    return match_response(await service.run(user, job_id, body))


@router.get("/{job_id}/matches", response_model=list[MatchSummary])
async def list_matches(
    job_id: uuid.UUID, user: CurrentUserDep, service: MatchServiceDep
) -> list[MatchSummary]:
    return [
        MatchSummary(
            id=m.id,
            job_id=m.job_id,
            created_at=m.created_at,
            overall_score=m.overall_score,
            score_status=m.result["report"]["score"]["status"],
            confidence=m.confidence,
        )
        for m in await service.list_all(user, job_id)
    ]


@router.get("/{job_id}/matches/{match_id}", response_model=MatchResponse)
async def get_match(
    job_id: uuid.UUID, match_id: uuid.UUID, user: CurrentUserDep, service: MatchServiceDep
) -> MatchResponse:
    return match_response(await service.get(user, job_id, match_id))
