"""Enumerations shared by database models and API schemas."""

from enum import StrEnum


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


class ResumeStatus(StrEnum):
    """Lifecycle: uploaded -> extracting -> extracted -> analyzing -> completed.

    ``failed`` can occur at any processing step (see ``FailureStage``).
    """

    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"


class IntegrationKind(StrEnum):
    GITHUB = "github"
    PORTFOLIO = "portfolio"


class JobStatus(StrEnum):
    """Processing status of a saved job description."""

    SAVED = "saved"
    PARSED = "parsed"
    FAILED = "failed"


class InterviewType(StrEnum):
    HR = "hr"
    BEHAVIORAL = "behavioral"
    TECHNICAL = "technical"
    PROGRAMMING = "programming"
    PROJECT = "project"
    SYSTEM_DESIGN = "system_design"
    JOB_SPECIFIC = "job_specific"


class SessionDifficulty(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class InterviewStatus(StrEnum):
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    EXPIRED = "expired"


class EvaluationStatus(StrEnum):
    EVALUATED = "evaluated"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    NOT_EVALUATED = "not_evaluated"


class FailureStage(StrEnum):
    EXTRACTION = "extraction"
    ANALYSIS = "analysis"


class ExperienceLevel(StrEnum):
    ENTRY = "entry"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"


class InterviewDifficulty(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


class SkillCategory(StrEnum):
    TECHNICAL = "technical"
    SOFT = "soft"


class SkillProficiency(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"
