"""Candidate profile endpoints (always operate on the authenticated user's profile)."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUserDep, SessionDep
from app.schemas.profile import ProfileResponse, ProfileUpdate, SkillOut
from app.services.profile import ProfileService

router = APIRouter(prefix="/profile", tags=["profile"])


def get_profile_service(session: SessionDep) -> ProfileService:
    return ProfileService(session)


ProfileServiceDep = Annotated[ProfileService, Depends(get_profile_service)]


@router.get("", response_model=ProfileResponse)
async def get_profile(user: CurrentUserDep, service: ProfileServiceDep) -> ProfileResponse:
    profile = await service.get(user)
    return service.to_response(user, profile)


@router.put("", response_model=ProfileResponse)
async def update_profile(
    body: ProfileUpdate, user: CurrentUserDep, service: ProfileServiceDep
) -> ProfileResponse:
    """Replace the whole profile. Omitted optional fields are cleared."""
    profile = await service.replace(user, body)
    return service.to_response(user, profile)


@router.get("/skills", response_model=list[SkillOut])
async def list_skills(user: CurrentUserDep, service: ProfileServiceDep) -> list[SkillOut]:
    profile = await service.get(user)
    return [SkillOut.model_validate(skill) for skill in profile.skills]
