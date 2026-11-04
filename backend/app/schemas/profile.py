"""Request/response models for the candidate profile.

Input models forbid unknown fields, so clients cannot smuggle in ids, ownership or
audit columns. Text is whitespace-trimmed and length-bounded.
"""

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

from app.models.enums import ExperienceLevel, InterviewDifficulty, SkillCategory, SkillProficiency
from app.schemas.auth import FullName

MAX_ITEMS = 50


Name200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text5000 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]
Tag100 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Tag50 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]

_http_url = TypeAdapter(HttpUrl)


def _validate_http_url(value: str) -> str:
    """Only absolute http(s) URLs are accepted (rejects javascript:, data:, etc.)."""
    if len(value) > 500:
        raise ValueError("URL must be at most 500 characters")
    return str(_http_url.validate_python(value))


WebUrl = Annotated[str, AfterValidator(_validate_http_url)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _DateRange(_Input):
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def _end_not_before_start(self) -> Self:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class EducationIn(_DateRange):
    institution: Name200
    degree: Name200
    field_of_study: Name200 | None = None
    description: Text5000 | None = None


class WorkExperienceIn(_DateRange):
    company: Name200
    title: Name200
    is_current: bool = False
    description: Text5000 | None = None

    @model_validator(mode="after")
    def _current_role_has_no_end_date(self) -> Self:
        if self.is_current and self.end_date is not None:
            raise ValueError("A current role cannot have an end_date")
        return self


class SkillIn(_Input):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    category: SkillCategory
    proficiency: SkillProficiency | None = None


class ProjectIn(_Input):
    name: Name200
    description: Text5000 | None = None
    technologies: list[Tag50] = Field(default_factory=list, max_length=30)
    url: WebUrl | None = None


class CertificationIn(_Input):
    name: Name200
    issuer: Name200 | None = None
    issued_date: date | None = None
    credential_url: WebUrl | None = None


def check_unique_skills(skills: list[SkillIn]) -> list[SkillIn]:
    seen: set[tuple[SkillCategory, str]] = set()
    for skill in skills:
        key = (skill.category, skill.name.casefold())
        if key in seen:
            raise ValueError(f"Duplicate {skill.category.value} skill: {skill.name}")
        seen.add(key)
    return skills


class ProfileUpdate(_Input):
    """Full replacement of the profile (PUT semantics): omitted optional fields are
    cleared and omitted lists become empty."""

    full_name: FullName
    headline: Name200 | None = None
    career_objective: Text5000 | None = None
    experience_level: ExperienceLevel | None = None
    preferred_difficulty: InterviewDifficulty | None = None
    preferred_roles: list[Tag100] = Field(default_factory=list, max_length=20)
    education: list[EducationIn] = Field(default_factory=list, max_length=20)
    work_experience: list[WorkExperienceIn] = Field(default_factory=list, max_length=30)
    skills: list[SkillIn] = Field(default_factory=list, max_length=100)
    projects: list[ProjectIn] = Field(default_factory=list, max_length=30)
    certifications: list[CertificationIn] = Field(default_factory=list, max_length=30)

    @field_validator("preferred_roles")
    @classmethod
    def _unique_roles(cls, roles: list[str]) -> list[str]:
        seen: set[str] = set()
        for role in roles:
            key = role.casefold()
            if key in seen:
                raise ValueError(f"Duplicate preferred role: {role}")
            seen.add(key)
        return roles

    @field_validator("skills")
    @classmethod
    def _unique_skills(cls, skills: list[SkillIn]) -> list[SkillIn]:
        return check_unique_skills(skills)


class _Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EducationOut(_Output):
    id: uuid.UUID
    institution: str
    degree: str
    field_of_study: str | None
    start_date: date | None
    end_date: date | None
    description: str | None


class WorkExperienceOut(_Output):
    id: uuid.UUID
    company: str
    title: str
    start_date: date | None
    end_date: date | None
    is_current: bool
    description: str | None


class SkillOut(_Output):
    id: uuid.UUID
    name: str
    category: SkillCategory
    proficiency: SkillProficiency | None


class ProjectOut(_Output):
    id: uuid.UUID
    name: str
    description: str | None
    technologies: list[str]
    url: str | None


class CertificationOut(_Output):
    id: uuid.UUID
    name: str
    issuer: str | None
    issued_date: date | None
    credential_url: str | None


class ProfileResponse(_Output):
    email: str
    full_name: str
    headline: str | None
    career_objective: str | None
    experience_level: ExperienceLevel | None
    preferred_difficulty: InterviewDifficulty | None
    preferred_roles: list[str]
    education: list[EducationOut]
    work_experience: list[WorkExperienceOut]
    skills: list[SkillOut]
    projects: list[ProjectOut]
    certifications: list[CertificationOut]
    updated_at: datetime


class ApplyMode(StrEnum):
    MERGE = "merge"  # add new items, keep existing ones
    REPLACE = "replace"  # replace each provided section entirely


class ApplyToProfileRequest(_Input):
    """The reviewed data a user chooses to apply to their profile.

    Only fields that are present are touched; omitted fields (``null``) leave the
    profile unchanged. Lists use ``mode``; scalar fields never replace a different
    existing value unless ``overwrite_existing`` is true.
    """

    full_name: FullName | None = None
    headline: Name200 | None = None
    career_objective: Text5000 | None = None
    education: list[EducationIn] | None = Field(default=None, max_length=20)
    work_experience: list[WorkExperienceIn] | None = Field(default=None, max_length=30)
    skills: list[SkillIn] | None = Field(default=None, max_length=100)
    projects: list[ProjectIn] | None = Field(default=None, max_length=30)
    certifications: list[CertificationIn] | None = Field(default=None, max_length=30)
    mode: ApplyMode = ApplyMode.MERGE
    overwrite_existing: bool = False

    @field_validator("skills")
    @classmethod
    def _unique_skills(cls, skills: list[SkillIn] | None) -> list[SkillIn] | None:
        return None if skills is None else check_unique_skills(skills)

    @model_validator(mode="after")
    def _something_selected(self) -> Self:
        sections = (
            self.full_name,
            self.headline,
            self.career_objective,
            self.education,
            self.work_experience,
            self.skills,
            self.projects,
            self.certifications,
        )
        if all(value is None for value in sections):
            raise ValueError("Select at least one field or section to apply")
        return self


class SkippedField(_Output):
    field: str
    reason: str


class ApplyResult(_Output):
    applied: dict[str, int]
    skipped: list[SkippedField]
    profile: ProfileResponse
