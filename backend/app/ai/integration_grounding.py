"""Evidence handling for source analysis: computed facts and assessment verification.

Rule that matters most: **a repository's name is not evidence.** A skill or technology
counts as demonstrated only if it appears in descriptive content (description, topics,
primary language, README excerpt, bio, page text), never merely in a repo name such as
"kubernetes-playground".
"""

import re

from app.ai.cv_schemas import ExtractedFacts
from app.ai.integration_schemas import (
    ConsistencyFacts,
    DemonstratedSkill,
    GitHubFacts,
    IntegrationAssessment,
    IntegrationFacts,
    NotableRepository,
    PortfolioFacts,
    PortfolioPageSummary,
    ProjectAssessment,
    SkillEvidence,
    SourceReference,
)
from app.integrations.github.snapshot import GitHubSnapshot, RepositoryFact
from app.integrations.portfolio.crawler import PortfolioPageFact, PortfolioSnapshot

MIN_EVIDENCE_CHARS_FOR_COMPLEXITY = 200
MAX_NOTABLE = 10
_WS = re.compile(r"\s+")


def _squash(text: str) -> str:
    return _WS.sub(" ", text).strip().casefold()


def contains_token(haystack: str, needle: str | None) -> bool:
    """Whole-token containment on already-squashed text."""
    if not needle:
        return False
    pattern = rf"(?<![a-z0-9]){re.escape(_squash(needle))}(?![a-z0-9])"
    return re.search(pattern, haystack) is not None


def repo_evidence_text(repo: RepositoryFact) -> str:
    """Descriptive content of a repository. Deliberately excludes the repo *name*."""
    parts = [repo.description or "", " ".join(repo.topics), repo.primary_language or ""]
    parts.append(repo.readme_excerpt or "")
    return _squash(" ".join(parts))


def page_evidence_text(page: PortfolioPageFact) -> str:
    parts = [page.title or "", page.description or "", " ".join(page.headings), page.text_excerpt]
    return _squash(" ".join(parts))


class Evidence:
    """Searchable evidence per source item, built from stored snapshots."""

    def __init__(
        self,
        github: GitHubSnapshot | None,
        portfolio: PortfolioSnapshot | None,
        cv: ExtractedFacts | None,
    ) -> None:
        self.repos: dict[str, tuple[RepositoryFact, str]] = {}
        self.pages: dict[str, tuple[PortfolioPageFact, str]] = {}
        self.github_profile_text = ""
        if github is not None:
            self.github_profile_text = _squash(github.bio or "")
            for repo in github.repositories:
                self.repos[repo.name.casefold()] = (repo, repo_evidence_text(repo))
        if portfolio is not None:
            for page in portfolio.pages:
                self.pages[page.url] = (page, page_evidence_text(page))
        self.cv = cv

    def text_for(self, ref: SourceReference) -> str | None:
        """Evidence text for a reference, or ``None`` if the reference does not exist."""
        if ref.ref is None:
            return None
        if ref.source == "github":
            entry = self.repos.get(ref.ref.casefold())
            if entry is None or entry[0].is_fork:  # forks are not the candidate's own work
                return None
            return entry[1]
        if ref.source == "portfolio":
            page = self.pages.get(ref.ref)
            return page[1] if page else None
        return None

    def all_public_texts(self) -> list[tuple[SourceReference, str]]:
        found: list[tuple[SourceReference, str]] = []
        for repo, text in self.repos.values():
            if not repo.is_fork:
                found.append((SourceReference(source="github", ref=repo.name), text))
        for url, (_, text) in self.pages.items():
            found.append((SourceReference(source="portfolio", ref=url), text))
        return found


def notable_repositories(snapshot: GitHubSnapshot) -> list[RepositoryFact]:
    own = [r for r in snapshot.repositories if not r.is_fork]
    own.sort(key=lambda r: (r.stars, r.pushed_at.timestamp() if r.pushed_at else 0.0), reverse=True)
    return own[:MAX_NOTABLE]


def compute_facts(
    github: GitHubSnapshot | None,
    portfolio: PortfolioSnapshot | None,
    cv: ExtractedFacts | None,
    evidence: Evidence,
) -> IntegrationFacts:
    sources = [kind for kind, present in (("github", github), ("portfolio", portfolio)) if present]
    if cv is not None:
        sources.append("resume")

    github_facts = None
    if github is not None:
        own = [r for r in github.repositories if not r.is_fork]
        github_facts = GitHubFacts(
            login=github.login,
            profile_url=github.profile_url,
            own_repositories_considered=len(own),
            language_distribution=github.language_distribution,
            notable_repositories=[
                NotableRepository(
                    name=r.name,
                    url=r.url,
                    description=r.description,
                    primary_language=r.primary_language,
                    topics=r.topics,
                    stars=r.stars,
                    has_readme_excerpt=bool(r.readme_excerpt),
                )
                for r in notable_repositories(github)
            ],
            own_repos_pushed_last_365_days=github.activity.own_repos_pushed_last_365_days,
        )

    portfolio_facts = None
    if portfolio is not None:
        portfolio_facts = PortfolioFacts(
            host=portfolio.host,
            pages=[PortfolioPageSummary(url=p.url, title=p.title) for p in portfolio.pages],
        )

    consistency = None
    if cv is not None and (github is not None or portfolio is not None):
        consistency = _consistency(cv, evidence)

    return IntegrationFacts(
        sources_used=sources,
        github=github_facts,
        portfolio=portfolio_facts,
        consistency=consistency,
    )


def _consistency(cv: ExtractedFacts, evidence: Evidence) -> ConsistencyFacts:
    texts = evidence.all_public_texts()
    if evidence.github_profile_text:
        texts.append(
            (SourceReference(source="github", ref="profile bio"), evidence.github_profile_text)
        )
    with_evidence: list[SkillEvidence] = []
    without: list[str] = []
    for skill in dict.fromkeys(cv.technical_skills + cv.tools_and_technologies):
        refs = [ref for ref, text in texts if contains_token(text, skill)][:5]
        if refs:
            with_evidence.append(SkillEvidence(skill=skill, found_in=refs))
        else:
            without.append(skill)
    return ConsistencyFacts(
        cv_skills_with_public_evidence=with_evidence, cv_skills_without_public_evidence=without
    )


def verify_assessment(
    assessment: IntegrationAssessment, evidence: Evidence
) -> tuple[IntegrationAssessment, int]:
    """Drop every checkable claim the sources do not support. Returns (clean, removed)."""
    removed = 0

    projects: list[ProjectAssessment] = []
    for project in assessment.project_assessments:
        evidence_text = evidence.text_for(project.source)
        if evidence_text is None:
            removed += 1  # reference to a source item that does not exist (or is a fork)
            continue
        if project.source.source == "github" and project.source.ref:
            project.name = evidence.repos[project.source.ref.casefold()][0].name
        elif not contains_token(evidence_text, project.name):
            removed += 1
            continue
        kept = [t for t in project.technologies_demonstrated if contains_token(evidence_text, t)]
        removed += len(project.technologies_demonstrated) - len(kept)
        project.technologies_demonstrated = kept
        if len(evidence_text) < MIN_EVIDENCE_CHARS_FOR_COMPLEXITY or not project.complexity_basis:
            # Too little to judge from (e.g. a repo with only a name and a one-line description).
            project.complexity = "unclear"
        projects.append(project)

    skills: list[DemonstratedSkill] = []
    for skill in assessment.demonstrated_skills:
        valid = [
            ref
            for ref in skill.evidence
            if (text := evidence.text_for(ref)) is not None and contains_token(text, skill.name)
        ]
        if not skill.name or not valid:
            removed += 1
            continue
        skill.evidence = valid
        skills.append(skill)

    cleaned = assessment.model_copy(
        update={"project_assessments": projects, "demonstrated_skills": skills}
    )
    return cleaned, removed
