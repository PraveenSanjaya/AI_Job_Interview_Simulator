"""Turn verified CV facts into a *suggested* profile update for the user to review.

Nothing here touches the profile. The suggestion has exactly the shape of the
apply request, so a client can show it, let the user edit or deselect parts, and
send back what they approve. Items that cannot form a valid entry without inventing
data (for example an education entry with no degree) are left out and reported in
``notes`` rather than filled with placeholders.
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError

from app.ai.cv_schemas import CVAnalysisResult
from app.ai.integration_schemas import IntegrationAnalysisResult
from app.models.enums import SkillCategory
from app.schemas.profile import (
    ApplyToProfileRequest,
    CertificationIn,
    EducationIn,
    ProjectIn,
    SkillIn,
    WorkExperienceIn,
)


def partial_to_date(value: str | None) -> date | None:
    """``YYYY``, ``YYYY-MM`` or ``YYYY-MM-DD`` -> a date (first day of the period)."""
    if not value:
        return None
    parts = [int(p) for p in value.split("-")]
    return date(parts[0], parts[1] if len(parts) > 1 else 1, parts[2] if len(parts) > 2 else 1)


def _build[T: BaseModel](
    model: type[T], data: dict[str, Any], notes: list[str], label: str
) -> T | None:
    """Validate one entry; on failure retry without dates, then give up with a note."""
    adapter = TypeAdapter(model)
    for attempt in (data, {k: v for k, v in data.items() if "date" not in k and k != "url"}):
        try:
            return adapter.validate_python(attempt)
        except ValidationError:
            continue
    notes.append(f"A {label} entry could not be converted and was left out")
    return None


def build_profile_suggestion(
    result: CVAnalysisResult,
) -> tuple[ApplyToProfileRequest | None, list[str]]:
    facts = result.facts
    notes: list[str] = []

    skills: list[SkillIn] = []
    for names, category in (
        (facts.technical_skills + facts.tools_and_technologies, SkillCategory.TECHNICAL),
        (facts.soft_skills, SkillCategory.SOFT),
    ):
        seen: set[str] = set()
        for name in names:
            if name.casefold() not in seen:
                seen.add(name.casefold())
                skills.append(SkillIn(name=name, category=category))

    education: list[EducationIn] = []
    for entry in facts.education:
        if not (entry.institution and entry.degree):
            notes.append("An education entry without a degree was left out")
            continue
        built = _build(
            EducationIn,
            {
                "institution": entry.institution,
                "degree": entry.degree,
                "field_of_study": entry.field_of_study,
                "start_date": partial_to_date(entry.start_date),
                "end_date": partial_to_date(entry.end_date),
            },
            notes,
            "education",
        )
        if built:
            education.append(built)

    work: list[WorkExperienceIn] = []
    for job in facts.work_experience:
        if not (job.company and job.title):
            notes.append("A work experience entry without both company and title was left out")
            continue
        built_job = _build(
            WorkExperienceIn,
            {
                "company": job.company,
                "title": job.title,
                "start_date": partial_to_date(job.start_date),
                "end_date": None if job.is_current else partial_to_date(job.end_date),
                "is_current": job.is_current,
                "description": job.description,
            },
            notes,
            "work experience",
        )
        if built_job:
            work.append(built_job)

    projects: list[ProjectIn] = []
    for project in facts.projects:
        if not project.name:
            continue
        built_project = _build(
            ProjectIn,
            {
                "name": project.name,
                "description": project.description,
                "technologies": project.technologies,
                "url": project.url,
            },
            notes,
            "project",
        )
        if built_project:
            projects.append(built_project)

    certifications: list[CertificationIn] = []
    for cert in facts.certifications:
        if not cert.name:
            continue
        built_cert = _build(
            CertificationIn,
            {
                "name": cert.name,
                "issuer": cert.issuer,
                "issued_date": partial_to_date(cert.issued_date),
            },
            notes,
            "certification",
        )
        if built_cert:
            certifications.append(built_cert)

    suggestion_data: dict[str, Any] = {
        "full_name": facts.full_name,
        # Only text the candidate wrote themselves; never the AI-generated summary.
        "career_objective": facts.summary_as_written,
        "skills": skills or None,
        "education": education or None,
        "work_experience": work or None,
        "projects": projects or None,
        "certifications": certifications or None,
    }
    if all(value is None for value in suggestion_data.values()):
        return None, notes
    try:
        return ApplyToProfileRequest.model_validate(suggestion_data), notes
    except ValidationError:
        notes.append("The extracted data could not be turned into a profile suggestion")
        return None, notes


def build_integration_suggestion(
    result: IntegrationAnalysisResult,
) -> tuple[ApplyToProfileRequest | None, list[str]]:
    """Suggest projects and skills from a source analysis, for the user to review.

    Projects are the candidate's own repositories exactly as GitHub describes them
    (observed facts). Skills are languages those repositories are labelled with plus
    skills the analysis could verify in the sources' descriptive text.
    """
    notes: list[str] = []
    projects: list[ProjectIn] = []
    skills: dict[str, SkillIn] = {}

    github = result.facts.github
    if github is not None:
        for repo in github.notable_repositories:
            if not repo.description:
                continue
            technologies = [t for t in [repo.primary_language, *repo.topics] if t]
            built = _build(
                ProjectIn,
                {
                    "name": repo.name,
                    "description": repo.description,
                    "technologies": technologies[:30],
                    "url": repo.url,
                },
                notes,
                "project",
            )
            if built:
                projects.append(built)
        for language in github.language_distribution:
            skills.setdefault(
                language.casefold(), SkillIn(name=language, category=SkillCategory.TECHNICAL)
            )

    for skill in result.assessment.demonstrated_skills:
        if skill.name:
            skills.setdefault(
                skill.name.casefold(), SkillIn(name=skill.name, category=SkillCategory.TECHNICAL)
            )

    if not projects and not skills:
        return None, notes
    try:
        return (
            ApplyToProfileRequest.model_validate(
                {
                    "projects": [p.model_dump() for p in projects] or None,
                    "skills": [s.model_dump() for s in skills.values()] or None,
                }
            ),
            notes,
        )
    except ValidationError:
        notes.append("The analysis could not be turned into a profile suggestion")
        return None, notes
