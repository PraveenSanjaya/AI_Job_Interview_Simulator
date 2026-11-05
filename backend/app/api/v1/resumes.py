"""Resume endpoints. Every route requires authentication and is scoped to the caller."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, status

from app.ai.base import LLMProvider
from app.ai.cv_schemas import CVAnalysisResult
from app.ai.suggestions import build_profile_suggestion
from app.api.deps import CurrentUserDep, RateLimiterDep, SessionDep, SettingsDep, get_llm_provider
from app.models import ResumeAnalysis
from app.schemas.profile import ApplyResult, ApplyToProfileRequest
from app.schemas.resume import AnalysisResponse, AnalyzeRequest, ResumeResponse
from app.services.profile import ProfileService
from app.services.resume_analysis import ResumeAnalysisService
from app.services.resumes import ResumeService
from app.storage.base import StorageBackend

router = APIRouter(prefix="/resumes", tags=["resumes"])


def get_storage(request: Request) -> StorageBackend:
    storage: StorageBackend = request.app.state.storage
    return storage


def get_resume_service(
    session: SessionDep,
    settings: SettingsDep,
    storage: Annotated[StorageBackend, Depends(get_storage)],
) -> ResumeService:
    return ResumeService(session, storage, settings.max_upload_bytes)


ResumeServiceDep = Annotated[ResumeService, Depends(get_resume_service)]


def get_analysis_service(
    session: SessionDep,
    settings: SettingsDep,
    storage: Annotated[StorageBackend, Depends(get_storage)],
    provider: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> ResumeAnalysisService:
    return ResumeAnalysisService(session, storage, provider, settings.ai_max_input_chars)


AnalysisServiceDep = Annotated[ResumeAnalysisService, Depends(get_analysis_service)]


@router.post("", response_model=ResumeResponse, status_code=status.HTTP_201_CREATED)
async def upload_resume(
    file: Annotated[UploadFile, File(description="PDF, DOCX or TXT resume")],
    user: CurrentUserDep,
    service: ResumeServiceDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> ResumeResponse:
    """Upload a resume (PDF, DOCX or TXT).

    The file type is determined from the content, not the filename or Content-Type.
    If the text cannot be extracted (e.g. a scanned PDF), the resume is still created
    with ``status="failed"`` and an ``error_code`` such as ``ocr_required``.
    """
    await limiter.hit(f"resume-upload:user:{user.id}")
    data = await file.read(settings.max_upload_bytes + 1)
    resume = await service.upload(user, file.filename, data)
    return ResumeResponse.model_validate(resume)


@router.get("", response_model=list[ResumeResponse])
async def list_resumes(user: CurrentUserDep, service: ResumeServiceDep) -> list[ResumeResponse]:
    return [ResumeResponse.model_validate(r) for r in await service.list(user)]


@router.get("/{resume_id}", response_model=ResumeResponse)
async def get_resume(
    resume_id: uuid.UUID, user: CurrentUserDep, service: ResumeServiceDep
) -> ResumeResponse:
    return ResumeResponse.model_validate(await service.get(user, resume_id))


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(
    resume_id: uuid.UUID, user: CurrentUserDep, service: ResumeServiceDep
) -> None:
    """Delete the resume, its analysis and the stored file."""
    await service.delete(user, resume_id)


@router.post("/{resume_id}/analyze", response_model=AnalysisResponse)
async def analyze_resume(
    resume_id: uuid.UUID,
    user: CurrentUserDep,
    service: AnalysisServiceDep,
    limiter: RateLimiterDep,
    body: AnalyzeRequest | None = None,
) -> AnalysisResponse:
    """Analyse the resume with the configured AI provider.

    * 503 ``ai_unavailable``: no provider configured (everything else keeps working).
    * 403 ``ai_consent_required``: the provider is external and ``allow_external_ai``
      was not set to true.
    * 409: analysis already running, or the text could not be extracted.
    * 502/504/429: invalid AI output, provider timeout, provider rate limit.
    """
    await limiter.hit(f"resume-analyze:user:{user.id}")
    request_body = body or AnalyzeRequest()
    resume = await service.analyze(
        user, resume_id, allow_external_ai=request_body.allow_external_ai
    )
    assert resume.analysis is not None  # noqa: S101  (set on successful completion)
    return _analysis_response(resume.id, resume.analysis)


@router.get("/{resume_id}/analysis", response_model=AnalysisResponse)
async def get_analysis(
    resume_id: uuid.UUID, user: CurrentUserDep, service: AnalysisServiceDep
) -> AnalysisResponse:
    return _analysis_response(resume_id, await service.get_analysis(user, resume_id))


def _analysis_response(resume_id: uuid.UUID, analysis: ResumeAnalysis) -> AnalysisResponse:
    result = CVAnalysisResult.model_validate(analysis.result)
    suggestion, notes = build_profile_suggestion(result)
    return AnalysisResponse(
        resume_id=resume_id,
        provider=analysis.provider,
        model=analysis.model,
        consent_external_ai=analysis.consent_external_ai,
        input_truncated=analysis.input_truncated,
        created_at=analysis.created_at,
        result=result,
        profile_suggestion=suggestion,
        suggestion_notes=notes,
    )


@router.post("/{resume_id}/apply-to-profile", response_model=ApplyResult)
async def apply_to_profile(
    resume_id: uuid.UUID,
    body: ApplyToProfileRequest,
    user: CurrentUserDep,
    service: AnalysisServiceDep,
) -> ApplyResult:
    """Apply the data the user reviewed to their profile.

    Nothing is applied automatically: send only the fields and sections you approve
    (typically the ``profile_suggestion`` from the analysis, after editing it).
    Existing profile data is preserved: list sections are merged without duplicates
    (``mode="replace"`` replaces a section explicitly), and a scalar that already has a
    different value is kept unless ``overwrite_existing`` is true. Requires a
    completed analysis of the caller's own resume.
    """
    _, outcome = await service.apply_to_profile(user, resume_id, body)
    return ApplyResult(
        applied=outcome.applied,
        skipped=outcome.skipped,
        profile=ProfileService.to_response(user, outcome.profile),
    )
