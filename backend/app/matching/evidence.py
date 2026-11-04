"""Candidate evidence gathered from every available source, de-duplicated.

Sources: the confirmed profile (including anything the candidate previously approved from
a CV or GitHub suggestion), the analysed resume, GitHub and the portfolio.

Two strengths of evidence exist:

* **declared**: the skill is listed (a skills list, a bio, a certification title);
* **demonstrated**: it appears in the description of something concrete (a project, a job,
  a repository, a portfolio page).

A repository's *name* is never evidence (see ``app.ai.integration_grounding``). The same
project often appears in the profile, the CV, GitHub and the portfolio; those sightings are
merged into one item so it is counted once, with every source listed as a reference.
"""

import calendar
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from app.ai.cv_schemas import ExtractedFacts
from app.ai.integration_grounding import contains_token
from app.integrations.github.snapshot import GitHubSnapshot
from app.integrations.portfolio.crawler import PortfolioSnapshot
from app.jobs.parser import education_level
from app.jobs.schemas import EducationLevel
from app.jobs.taxonomy import canonical_key, find_entries, squash
from app.matching.report import EvidenceKind, EvidenceRef, Source

Tier = Literal["declared", "demonstrated"]
_NON_ALNUM = re.compile(r"[^a-z0-9]")
MIN_NAME_LEN_FOR_PAGE_MERGE = 5


def norm(text: str) -> str:
    return _NON_ALNUM.sub("", text.casefold())


# ----------------------------------------------------------------- plain inputs


@dataclass(frozen=True)
class ProfileSkill:
    name: str
    category: Literal["technical", "soft"]


@dataclass(frozen=True)
class ProfileProject:
    name: str
    description: str | None = None
    technologies: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProfileWork:
    company: str
    title: str
    description: str | None = None
    start: date | None = None
    end: date | None = None
    is_current: bool = False


@dataclass(frozen=True)
class ProfileEducation:
    institution: str
    degree: str
    field_of_study: str | None = None


@dataclass(frozen=True)
class CandidateProfile:
    """The confirmed profile, as plain data."""

    experience_level: str | None = None
    preferred_roles: tuple[str, ...] = ()
    skills: tuple[ProfileSkill, ...] = ()
    projects: tuple[ProfileProject, ...] = ()
    work: tuple[ProfileWork, ...] = ()
    education: tuple[ProfileEducation, ...] = ()
    certifications: tuple[str, ...] = ()


# -------------------------------------------------------------- evidence model


@dataclass
class EvidenceItem:
    key: str
    kind: EvidenceKind
    tier: Tier
    refs: list[EvidenceRef]
    text: str = ""
    mentions: set[str] = field(default_factory=set)
    # Display name for projects (used in project relevance).
    label: str = ""

    def add_text(self, text: str) -> None:
        if text and text not in self.text:
            self.text = f"{self.text}\n{text}".strip()
            self.mentions |= text_mentions(text)

    def add_ref(self, ref: EvidenceRef) -> None:
        if ref not in self.refs:
            self.refs.append(ref)

    def mentions_skill(self, name: str) -> bool:
        key = canonical_key(name)
        if key in self.mentions:
            return True
        # Names outside the built-in vocabulary are matched as whole words in the text.
        return bool(self.text) and contains_token(squash(self.text), name)


def text_mentions(text: str) -> set[str]:
    found = find_entries(text, "technical") + find_entries(text, "soft")
    return {canonical_key(entry.name) for entry in found}


@dataclass
class CandidateEvidence:
    items: dict[str, EvidenceItem] = field(default_factory=dict)
    sources_with_content: set[Source] = field(default_factory=set)
    not_available: dict[str, str] = field(default_factory=dict)
    work_intervals: list[tuple[date, date]] = field(default_factory=list)
    work_entries: int = 0
    years_source: Literal["profile", "resume"] | None = None
    education_levels: list[EducationLevel] = field(default_factory=list)
    education_entries: int = 0
    experience_level: str | None = None
    preferred_roles: tuple[str, ...] = ()

    @property
    def has_any_content(self) -> bool:
        return bool(self.items)

    def projects(self) -> list[EvidenceItem]:
        """Distinct projects (a project seen in several sources is one item)."""
        return [i for i in self.items.values() if i.key.startswith("proj:")]

    def matching(self, skill: str) -> list[EvidenceItem]:
        return [i for i in self.items.values() if i.mentions_skill(skill)]


# ------------------------------------------------------------------ date helpers


def _partial_date(value: str | None, *, end: bool) -> date | None:
    """``YYYY``, ``YYYY-MM`` or ``YYYY-MM-DD`` -> a date (start of period, or end for ends)."""
    if not value:
        return None
    parts = value.split("-")
    try:
        year = int(parts[0])
        if len(parts) == 1:
            return date(year, 12, 31) if end else date(year, 1, 1)
        month = int(parts[1])
        if len(parts) == 2:
            last = calendar.monthrange(year, month)[1]
            return date(year, month, last if end else 1)
        return date(year, month, int(parts[2]))
    except (ValueError, IndexError):
        return None


def _merge_intervals(intervals: list[tuple[date, date]]) -> list[tuple[date, date]]:
    """Merge overlapping periods so concurrent jobs are not counted twice."""
    merged: list[tuple[date, date]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def years_in(intervals: list[tuple[date, date]]) -> float:
    return sum((end - start).days for start, end in intervals) / 365.25


# ---------------------------------------------------------------------- builder


class _Builder:
    def __init__(self) -> None:
        self.evidence = CandidateEvidence()

    def item(
        self,
        key: str,
        kind: EvidenceKind,
        tier: Tier,
        ref: EvidenceRef,
        text: str = "",
        label: str = "",
    ) -> EvidenceItem:
        existing = self.evidence.items.get(key)
        if existing is None:
            existing = EvidenceItem(key=key, kind=kind, tier=tier, refs=[], label=label)
            self.evidence.items[key] = existing
        existing.add_ref(ref)
        existing.add_text(text)
        if tier == "demonstrated":
            existing.tier = "demonstrated"
        self.evidence.sources_with_content.add(ref.source)
        return existing

    def declared_skill(self, source: Source, name: str) -> None:
        name = " ".join(name.split())
        if not name:
            return
        key = f"skill:{canonical_key(name)}"
        item = self.item(
            key, "skill_list", "declared", EvidenceRef(source=source, kind="skill_list", ref=name)
        )
        item.mentions.add(canonical_key(name))

    def project(self, source: Source, kind: EvidenceKind, name: str, text: str) -> None:
        if not norm(name):
            return
        # The project's name is used to recognise the same project elsewhere, but is not
        # searched for skills: a repository called "kubernetes-playground" shows nothing.
        self.item(
            f"proj:{norm(name)}",
            kind,
            "demonstrated",
            EvidenceRef(source=source, kind=kind, ref=name),
            text,
            label=name,
        )


def build_candidate_evidence(
    *,
    profile: CandidateProfile | None,
    resume: ExtractedFacts | None,
    github: GitHubSnapshot | None,
    portfolio: PortfolioSnapshot | None,
    today: date,
) -> CandidateEvidence:
    builder = _Builder()
    evidence = builder.evidence

    if profile is not None:
        evidence.experience_level = profile.experience_level
        evidence.preferred_roles = profile.preferred_roles
        for skill in profile.skills:
            builder.declared_skill("profile", skill.name)
        for project in profile.projects:
            text = " ".join([project.description or "", *project.technologies])
            builder.project("profile", "project", project.name, text)
        for job in profile.work:
            text = " ".join([job.title, job.description or ""])
            builder.item(
                f"exp:{norm(job.company)}|{norm(job.title)}",
                "experience",
                "demonstrated",
                EvidenceRef(
                    source="profile", kind="experience", ref=f"{job.title} at {job.company}"
                ),
                text,
            )
        for cert in profile.certifications:
            builder.item(
                f"cert:{norm(cert)}",
                "certification",
                "declared",
                EvidenceRef(source="profile", kind="certification", ref=cert),
                cert,
            )
        _profile_dates(evidence, profile, today)
        for education in profile.education:
            evidence.education_entries += 1
            _note_education(evidence, education.degree)

    if resume is not None:
        for name in [*resume.technical_skills, *resume.tools_and_technologies]:
            builder.declared_skill("resume", name)
        for name in resume.soft_skills:
            builder.declared_skill("resume", name)
        for r_project in resume.projects:
            if r_project.name:
                text = " ".join([r_project.description or "", *r_project.technologies])
                builder.project("resume", "project", r_project.name, text)
        for r_job in resume.work_experience:
            if r_job.title or r_job.company:
                builder.item(
                    f"exp:{norm(r_job.company or '')}|{norm(r_job.title or '')}",
                    "experience",
                    "demonstrated",
                    EvidenceRef(
                        source="resume",
                        kind="experience",
                        ref=f"{r_job.title or 'Role'} at {r_job.company or 'unknown company'}",
                    ),
                    " ".join([r_job.title or "", r_job.description or ""]),
                )
        for r_cert in resume.certifications:
            if r_cert.name:
                builder.item(
                    f"cert:{norm(r_cert.name)}",
                    "certification",
                    "declared",
                    EvidenceRef(source="resume", kind="certification", ref=r_cert.name),
                    r_cert.name,
                )
        if evidence.work_entries == 0:  # the profile wins; the CV never double-counts it
            _resume_dates(evidence, resume, today)
        if evidence.education_entries == 0:
            for r_education in resume.education:
                evidence.education_entries += 1
                _note_education(evidence, r_education.degree or "")
        evidence.sources_with_content.add("resume")

    if github is not None:
        evidence.sources_with_content.add("github")
        if github.bio:
            builder.item(
                "bio:github",
                "profile_bio",
                "declared",
                EvidenceRef(source="github", kind="profile_bio", ref=github.login),
                github.bio,
            )
        for repo in github.repositories:
            if repo.is_fork:  # forks are not the candidate's own work
                continue
            text = " ".join(
                [repo.description or "", " ".join(repo.topics), repo.primary_language or "",
                 repo.readme_excerpt or ""]
            )  # fmt: skip
            builder.project("github", "repository", repo.name, text)

    if portfolio is not None:
        evidence.sources_with_content.add("portfolio")
        _add_pages(builder, portfolio)

    return evidence


def _add_pages(builder: _Builder, portfolio: PortfolioSnapshot) -> None:
    """Portfolio pages often describe projects that are also in the CV or on GitHub. A page
    that names an already-known project is merged into it instead of counting twice."""
    projects = {
        key: item
        for key, item in builder.evidence.items.items()
        if key.startswith("proj:") and len(key) - 5 >= MIN_NAME_LEN_FOR_PAGE_MERGE
    }
    for page in portfolio.pages:
        text = " ".join([page.title or "", page.description or "", " ".join(page.headings),
                         page.text_excerpt])  # fmt: skip
        flat = norm(text)
        ref = EvidenceRef(source="portfolio", kind="page", ref=page.url)
        target = next((item for key, item in projects.items() if key[5:] in flat), None)
        if target is not None:
            target.add_ref(ref)
            target.add_text(text)
            builder.evidence.sources_with_content.add("portfolio")
        else:
            builder.item(f"page:{page.url}", "page", "demonstrated", ref, text)


def _profile_dates(evidence: CandidateEvidence, profile: CandidateProfile, today: date) -> None:
    for job in profile.work:
        evidence.work_entries += 1
        if job.start is None:
            continue
        end = today if job.is_current else job.end
        if end is None:
            continue
        if end >= job.start:
            evidence.work_intervals.append((job.start, min(end, today)))
    if evidence.work_entries:
        evidence.years_source = "profile"
        evidence.work_intervals = _merge_intervals(evidence.work_intervals)


def _resume_dates(evidence: CandidateEvidence, resume: ExtractedFacts, today: date) -> None:
    for job in resume.work_experience:
        evidence.work_entries += 1
        start = _partial_date(job.start_date, end=False)
        end = today if job.is_current else _partial_date(job.end_date, end=True)
        if start is not None and end is not None and end >= start:
            evidence.work_intervals.append((start, min(end, today)))
    if evidence.work_entries:
        evidence.years_source = "resume"
        evidence.work_intervals = _merge_intervals(evidence.work_intervals)


def _note_education(evidence: CandidateEvidence, degree: str) -> None:
    level = education_level(degree)
    if level is not None:
        evidence.education_levels.append(level)
