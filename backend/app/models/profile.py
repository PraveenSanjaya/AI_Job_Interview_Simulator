"""Candidate profile and its child collections."""

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import (
    ExperienceLevel,
    InterviewDifficulty,
    SkillCategory,
    SkillProficiency,
)
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin, str_enum

if TYPE_CHECKING:
    from app.models.user import User

_CHILD_CASCADE = "all, delete-orphan"


class UserProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    headline: Mapped[str | None] = mapped_column(String(200), nullable=True)
    career_objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    experience_level: Mapped[ExperienceLevel | None] = mapped_column(
        str_enum(ExperienceLevel), nullable=True
    )
    preferred_difficulty: Mapped[InterviewDifficulty | None] = mapped_column(
        str_enum(InterviewDifficulty), nullable=True
    )
    preferred_roles: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    user: Mapped["User"] = relationship(back_populates="profile")
    education: Mapped[list["Education"]] = relationship(
        cascade=_CHILD_CASCADE, order_by="Education.position", lazy="selectin"
    )
    work_experience: Mapped[list["WorkExperience"]] = relationship(
        cascade=_CHILD_CASCADE, order_by="WorkExperience.position", lazy="selectin"
    )
    skills: Mapped[list["Skill"]] = relationship(
        cascade=_CHILD_CASCADE, order_by="Skill.position", lazy="selectin"
    )
    projects: Mapped[list["Project"]] = relationship(
        cascade=_CHILD_CASCADE, order_by="Project.position", lazy="selectin"
    )
    certifications: Mapped[list["Certification"]] = relationship(
        cascade=_CHILD_CASCADE, order_by="Certification.position", lazy="selectin"
    )


class _ProfileChildMixin(UUIDPrimaryKeyMixin):
    """Common columns for rows owned by a profile and kept in user-defined order."""

    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


def _profile_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        Uuid, ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )


class Education(_ProfileChildMixin, Base):
    __tablename__ = "education"

    profile_id: Mapped[uuid.UUID] = _profile_fk()
    institution: Mapped[str] = mapped_column(String(200), nullable=False)
    degree: Mapped[str] = mapped_column(String(200), nullable=False)
    field_of_study: Mapped[str | None] = mapped_column(String(200), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class WorkExperience(_ProfileChildMixin, Base):
    __tablename__ = "work_experience"

    profile_id: Mapped[uuid.UUID] = _profile_fk()
    company: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Skill(_ProfileChildMixin, Base):
    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("profile_id", "category", "name"),)

    profile_id: Mapped[uuid.UUID] = _profile_fk()
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[SkillCategory] = mapped_column(str_enum(SkillCategory), nullable=False)
    proficiency: Mapped[SkillProficiency | None] = mapped_column(
        str_enum(SkillProficiency), nullable=True
    )


class Project(_ProfileChildMixin, Base):
    __tablename__ = "projects"

    profile_id: Mapped[uuid.UUID] = _profile_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    technologies: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)


class Certification(_ProfileChildMixin, Base):
    __tablename__ = "certifications"

    profile_id: Mapped[uuid.UUID] = _profile_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    issuer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    issued_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    credential_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
