"""Job descriptions: save, edit, list, delete, and read their structured analysis."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUserDep, RateLimiterDep, SessionDep
from app.api.v1.integrations import get_page_fetcher
from app.integrations.portfolio.crawler import PageFetcher
from app.jobs.schemas import JobAnalysisResult
from app.models import JobAnalysis, JobDescription
from app.models.enums import JobStatus
from app.schemas.jobs import (
    JobAnalysisResponse,
    JobCreate,
    JobResponse,
    JobSummary,
    JobUpdate,
)
from app.services.jobs import JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])


def get_job_service(
    session: SessionDep, pages: Annotated[PageFetcher, Depends(get_page_fetcher)]
) -> JobService:
    return JobService(session, pages)


JobServiceDep = Annotated[JobService, Depends(get_job_service)]


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
    limiter.hit(f"jobs:user:{user.id}")
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
    limiter.hit(f"jobs:user:{user.id}")
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
