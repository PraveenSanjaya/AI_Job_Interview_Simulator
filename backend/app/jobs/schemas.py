"""Structured result of parsing a job description.

Every item carries ``quote`` (the sentence it came from) so a reader can check it. Items
come either from deterministic pattern matching (``source="text"``) or, optionally, from
an AI model (``source="ai"``) after being checked against the description text. Nothing
is added that the description does not say; ``seniority`` is the only inferred field and
says so in ``basis``.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, computed_field

from app.jobs.taxonomy import SkillKind

Importance = Literal["required", "preferred", "unspecified"]
Source = Literal["text", "ai"]
EducationLevel = Literal["associate", "bachelor", "master", "doctorate", "degree_unspecified"]
SeniorityLevel = Literal["entry", "junior", "mid", "senior", "lead"]

EDUCATION_RANK: dict[str, int] = {
    "associate": 1,
    "degree_unspecified": 2,  # "a degree": treated as bachelor level
    "bachelor": 2,
    "master": 3,
    "doctorate": 4,
}


def _clip(limit: int) -> BeforeValidator:
    def clean(value: object) -> object:
        if isinstance(value, str):
            return " ".join(value.split())[:limit]
        return value

    return BeforeValidator(clean)


Name = Annotated[str, _clip(100), Field(min_length=1, max_length=100)]
Quote = Annotated[str | None, _clip(300)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class JobSkill(_Model):
    name: Name
    kind: SkillKind
    importance: Importance = "unspecified"
    # True when the text or its section states the importance; False when it is a default.
    importance_stated: bool = False
    source: Source = "text"
    quote: Quote = None
    # True when every mention is in a company-context section ("About us", benefits):
    # it describes the employer's stack, not something the candidate is asked to have.
    context_only: bool = False
    # Other skills offered as interchangeable ("Python or Java"); one of them suffices.
    alternatives: list[str] = Field(default_factory=list)


class JobLabel(_Model):
    """A soft skill, certification or domain the text mentions."""

    name: Name
    importance: Importance = "unspecified"
    source: Source = "text"
    quote: Quote = None


class JobExperience(_Model):
    min_years: int = Field(ge=0, le=60)
    max_years: int | None = Field(default=None, ge=0, le=60)
    # The technology the years refer to, or None for years of experience in general.
    skill: str | None = None
    importance: Importance = "unspecified"
    quote: Quote = None


class JobEducation(_Model):
    level: EducationLevel
    field_of_study: Annotated[str | None, _clip(100)] = None
    importance: Importance = "unspecified"
    equivalent_experience_ok: bool = False
    quote: Quote = None


class JobStatement(_Model):
    """A responsibility or qualification, kept as the description wrote it."""

    text: Annotated[str, _clip(300), Field(min_length=1, max_length=300)]
    importance: Importance = "unspecified"


class JobSeniority(_Model):
    level: SeniorityLevel | None = None
    basis: Literal["stated", "inferred_from_years", "not_found"] = "not_found"
    quote: Quote = None


class ParsedJob(_Model):
    technical_skills: list[JobSkill] = Field(default_factory=list)
    soft_skills: list[JobLabel] = Field(default_factory=list)
    certifications: list[JobLabel] = Field(default_factory=list)
    domain_knowledge: list[JobLabel] = Field(default_factory=list)
    education: list[JobEducation] = Field(default_factory=list)
    experience: list[JobExperience] = Field(default_factory=list)
    responsibilities: list[JobStatement] = Field(default_factory=list)
    qualifications: list[JobStatement] = Field(default_factory=list)
    seniority: JobSeniority = Field(default_factory=JobSeniority)
    # Plain-language notes about ambiguity or thin input (e.g. unclear importance).
    warnings: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def required_technical_skills(self) -> list[str]:
        return [s.name for s in self.technical_skills if s.importance == "required"]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def preferred_technical_skills(self) -> list[str]:
        return [s.name for s in self.technical_skills if s.importance == "preferred"]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unspecified_importance_skills(self) -> list[str]:
        return [
            s.name
            for s in self.technical_skills
            if s.importance == "unspecified" and not s.context_only
        ]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def company_context_skills(self) -> list[str]:
        return [s.name for s in self.technical_skills if s.context_only]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def programming_languages(self) -> list[str]:
        return [s.name for s in self.technical_skills if s.kind == "language"]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def frameworks_and_tools(self) -> list[str]:
        kinds = {"framework", "library", "tool", "database", "cloud"}
        return [s.name for s in self.technical_skills if s.kind in kinds]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def overall_min_years(self) -> int | None:
        """Largest stated number of years of general (not technology-specific) experience."""
        general = [e.min_years for e in self.experience if e.skill is None]
        return max(general) if general else None


class JobAnalysisResult(_Model):
    """What is stored and returned for an analysed job."""

    parsed: ParsedJob
    # Items an AI proposed that could not be found in the description and were dropped.
    unverified_items_removed: int = 0
    notice: str = (
        "Extracted from the job description text. Each item quotes the sentence it came "
        "from. Nothing here is verified against the employer."
    )
