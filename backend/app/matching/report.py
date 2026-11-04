"""The structured match report. Everything here is computed by code from stored evidence;
AI-written advice, when requested, is stored separately and never alters these values."""

from typing import Literal

from pydantic import BaseModel, Field

from app.jobs.schemas import EducationLevel, Importance, SeniorityLevel
from app.jobs.taxonomy import SkillKind

Source = Literal["profile", "resume", "github", "portfolio"]
EvidenceKind = Literal[
    "skill_list", "project", "experience", "certification", "repository", "page", "profile_bio"
]
SkillStatus = Literal["supported", "weakly_supported", "not_found", "unknown"]
Confidence = Literal["none", "low", "medium", "high"]
ScoreStatus = Literal["scored", "insufficient_evidence", "insufficient_job_detail"]

DISCLAIMER = (
    "This is a rule-based estimate of how well the evidence on record covers this job "
    "description. It is not a prediction of any hiring decision, and no score guarantees "
    "an interview or an offer. Missing evidence is not proof that you lack a skill."
)


class EvidenceRef(BaseModel):
    """Where a piece of evidence comes from. ``ref`` is the item's own name or address."""

    source: Source
    kind: EvidenceKind
    ref: str


class RequirementMatch(BaseModel):
    name: str
    kind: SkillKind
    importance: Importance
    importance_stated: bool
    status: SkillStatus
    # Points of credit this skill earned (1 supported, partial for listed-only, 0 otherwise).
    credit: float
    # Distinct pieces of evidence after the same project seen in several sources is merged.
    independent_evidence: int
    evidence: list[EvidenceRef] = Field(default_factory=list)
    job_quote: str | None = None
    # Set when the job offers alternatives and another one is the one that is satisfied.
    satisfied_via: str | None = None
    alternatives: list[str] = Field(default_factory=list)
    unchecked_sources: list[str] = Field(default_factory=list)
    note: str


class SkillGroupResult(BaseModel):
    label: str
    # Alternatives ("Python or Java") count once.
    total: int
    supported: int
    weakly_supported: int
    not_found: int
    unknown: int
    coverage: float | None
    items: list[RequirementMatch] = Field(default_factory=list)


class DimensionScore(BaseModel):
    key: str
    label: str
    weight: float
    applicable: bool
    value: float | None
    effective_weight: float
    points: float
    explanation: str


class ScoreBreakdown(BaseModel):
    score: int | None
    status: ScoreStatus
    confidence: Confidence
    formula: str
    explanation: str
    dimensions: list[DimensionScore]


class ExperienceAlignment(BaseModel):
    status: Literal["aligned", "partial", "below", "unknown", "not_required"]
    required_years: int | None
    candidate_years: float | None
    value: float | None
    years_source: Literal["profile", "resume"] | None = None
    technology_specific: list[str] = Field(default_factory=list)
    job_seniority: SeniorityLevel | None = None
    job_seniority_basis: str | None = None
    candidate_level: str | None = None
    notes: list[str] = Field(default_factory=list)


class EducationAlignment(BaseModel):
    status: Literal["met", "partial", "below", "unknown", "not_required"]
    required_level: EducationLevel | None
    required_field: str | None
    candidate_level: EducationLevel | None
    equivalent_experience_ok: bool = False
    value: float | None
    notes: list[str] = Field(default_factory=list)


class RelevantProject(BaseModel):
    name: str
    matched_technologies: list[str]
    overlap: float
    evidence: list[EvidenceRef]


class ProjectRelevance(BaseModel):
    value: float | None
    projects: list[RelevantProject] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class TechnicalStrength(BaseModel):
    skill: str
    importance: Importance
    independent_evidence: int
    evidence: list[EvidenceRef]


class InformationalMatch(BaseModel):
    """Soft skills and certifications: reported, never scored."""

    name: str
    importance: Importance
    found: bool
    evidence: list[EvidenceRef] = Field(default_factory=list)
    note: str


class ImprovementArea(BaseModel):
    topic: str
    priority: Literal["high", "medium", "low"]
    reason: str
    suggestion: str
    requirements: list[str] = Field(default_factory=list)


class PreparationTopic(BaseModel):
    topic: str
    reason: str


class SourceAvailability(BaseModel):
    profile: bool
    resume: bool
    github: bool
    portfolio: bool
    not_available: dict[str, str] = Field(default_factory=dict)


class JobSnapshot(BaseModel):
    """What was compared, kept so the report stays understandable if the job changes."""

    job_id: str
    title: str
    company: str | None
    description_sha256: str
    analysis_parser: str
    seniority: SeniorityLevel | None
    seniority_basis: str


class MatchReport(BaseModel):
    job: JobSnapshot
    score: ScoreBreakdown
    required_skills: SkillGroupResult
    preferred_skills: SkillGroupResult
    technical_strengths: list[TechnicalStrength]
    experience: ExperienceAlignment
    education: EducationAlignment
    project_relevance: ProjectRelevance
    soft_skills: list[InformationalMatch]
    certifications: list[InformationalMatch]
    missing_requirements: list[str]
    weakly_supported_requirements: list[str]
    unverifiable_requirements: list[str]
    company_context_skills: list[str] = Field(default_factory=list)
    evidence_by_source: dict[str, list[EvidenceRef]]
    sources: SourceAvailability
    improvement_areas: list[ImprovementArea]
    preparation_topics: list[PreparationTopic]
    caveats: list[str]
    disclaimer: str = DISCLAIMER
