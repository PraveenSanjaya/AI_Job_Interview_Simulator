"""Resume endpoints. Every route requires authentication and is scoped to the caller."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, status

from app.api.deps import CurrentUserDep, RateLimiterDep, SessionDep, SettingsDep
from app.schemas.resume import ResumeResponse
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
    limiter.hit(f"resume-upload:user:{user.id}")
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
