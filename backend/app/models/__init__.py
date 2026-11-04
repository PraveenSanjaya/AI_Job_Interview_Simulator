"""Import every model so that ``Base.metadata`` is complete (used by Alembic)."""

from app.models.base import Base
from app.models.integration import IntegrationAnalysis, IntegrationSource
from app.models.profile import (
    Certification,
    Education,
    Project,
    Skill,
    UserProfile,
    WorkExperience,
)
from app.models.resume import Resume, ResumeAnalysis
from app.models.user import RefreshToken, User

__all__ = [
    "Base",
    "Certification",
    "Education",
    "IntegrationAnalysis",
    "IntegrationSource",
    "Project",
    "RefreshToken",
    "Resume",
    "ResumeAnalysis",
    "Skill",
    "User",
    "UserProfile",
    "WorkExperience",
]
