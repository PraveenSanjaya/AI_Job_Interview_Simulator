"""Schemas for the GitHub/portfolio/CV analysis.

``facts`` are computed by code from stored source snapshots and the verified CV facts;
no AI is involved, so they cannot be hallucinated. ``assessment`` is the model's opinion
and every checkable claim in it is verified against the sources (see
``integration_grounding``). The two are kept in separate objects.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ai.cv_schemas import Long, Medium, NameList, SentenceList, Short, _model_list


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


SourceKind = Literal["github", "portfolio", "resume"]
Complexity = Literal["basic", "moderate", "advanced", "unclear"]


class SourceReference(_Lenient):
    """Points at the evidence: a repository name, a page URL, or ``resume``."""

    source: SourceKind
    ref: Short = None


# ----------------------------------------------------------------- AI assessment


class ProjectAssessment(_Lenient):
    name: Short = None
    source: SourceReference = Field(default_factory=lambda: SourceReference(source="github"))
    technologies_demonstrated: NameList = Field(default_factory=list)
    what_it_shows: Medium = None
    relevance: Medium = None
    complexity: Complexity = "unclear"
    complexity_basis: Medium = None


class DemonstratedSkill(_Lenient):
    name: Short = None
    evidence: Annotated[list[SourceReference], _model_list(5)] = Field(default_factory=list)


class IntegrationAssessment(_Lenient):
    """Opinions of the AI. May be incomplete or wrong; not a measure of ability."""

    summary: Long = None
    strengths: SentenceList = Field(default_factory=list)
    potential_skill_gaps: SentenceList = Field(default_factory=list)
    project_assessments: Annotated[list[ProjectAssessment], _model_list(10)] = Field(
        default_factory=list
    )
    demonstrated_skills: Annotated[list[DemonstratedSkill], _model_list(40)] = Field(
        default_factory=list
    )
    consistency_notes: SentenceList = Field(default_factory=list)
    caveats: SentenceList = Field(default_factory=list)


class IntegrationAnalysisOutput(_Lenient):
    """The structure the model is asked to return."""

    assessment: IntegrationAssessment = Field(default_factory=IntegrationAssessment)


# ----------------------------------------------------------------- computed facts


class NotableRepository(BaseModel):
    name: str
    url: str
    description: str | None = None
    primary_language: str | None = None
    topics: list[str] = Field(default_factory=list)
    stars: int = 0
    has_readme_excerpt: bool = False


class GitHubFacts(BaseModel):
    login: str
    profile_url: str
    own_repositories_considered: int
    language_distribution: dict[str, int]
    notable_repositories: list[NotableRepository]
    own_repos_pushed_last_365_days: int
    note: str = "Counts of public repositories; not a measure of programming ability."


class PortfolioPageSummary(BaseModel):
    url: str
    title: str | None = None


class PortfolioFacts(BaseModel):
    host: str
    pages: list[PortfolioPageSummary]


class SkillEvidence(BaseModel):
    skill: str
    found_in: list[SourceReference]


class ConsistencyFacts(BaseModel):
    """Computed by exact text matching, not by the AI."""

    cv_skills_with_public_evidence: list[SkillEvidence] = Field(default_factory=list)
    cv_skills_without_public_evidence: list[str] = Field(default_factory=list)
    note: str = (
        "A CV skill with no match in the connected public sources is not evidence that the "
        "skill is missing: much work is private or not described online."
    )


class IntegrationFacts(BaseModel):
    sources_used: list[SourceKind]
    github: GitHubFacts | None = None
    portfolio: PortfolioFacts | None = None
    consistency: ConsistencyFacts | None = None


class IntegrationAnalysisResult(BaseModel):
    facts: IntegrationFacts
    assessment: IntegrationAssessment
    unverified_items_removed: int = 0
