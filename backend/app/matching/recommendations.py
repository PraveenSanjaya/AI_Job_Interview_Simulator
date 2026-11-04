"""Rule-based improvement areas and preparation topics.

Plain templates driven by the computed results, written for candidates who are still
building their skills. They need no AI and never state anything the report does not support.
"""

from app.jobs.schemas import ParsedJob
from app.matching.report import (
    ImprovementArea,
    MatchReport,
    PreparationTopic,
    RequirementMatch,
)

MAX_AREAS = 10
MAX_TOPICS = 15
_PRIORITY = {"high": 0, "medium": 1, "low": 2}


def improvement_areas(report: MatchReport, bests: list[RequirementMatch]) -> list[ImprovementArea]:
    areas: list[ImprovementArea] = []
    for match in bests:
        required = match.importance == "required"
        if match.status == "not_found":
            areas.append(
                ImprovementArea(
                    topic=match.name,
                    priority="high" if required else "low",
                    reason=(
                        f"The job {'requires' if required else 'mentions'} {match.name} and no "
                        "evidence of it was found in your records."
                    ),
                    suggestion=(
                        f"If you have used {match.name}, add it to your profile with an example. "
                        "If not, learn the fundamentals and build a small project with it."
                    ),
                    requirements=[match.name],
                )
            )
        elif match.status == "weakly_supported":
            areas.append(
                ImprovementArea(
                    topic=match.name,
                    priority="medium" if required else "low",
                    reason=(
                        f"{match.name} is listed as a skill but not shown in any project or job."
                    ),
                    suggestion=(
                        f"Add a project, repository or job description that shows how you used "
                        f"{match.name}."
                    ),
                    requirements=[match.name],
                )
            )

    experience = report.experience
    if experience.status in ("below", "partial") and experience.required_years:
        areas.append(
            ImprovementArea(
                topic="Hands-on experience",
                priority="medium",
                reason=(
                    f"About {experience.candidate_years} years of recorded work against "
                    f"{experience.required_years}+ asked for."
                ),
                suggestion=(
                    "Describe relevant internships, freelance, open-source or volunteer work "
                    "in your profile, and apply anyway if the rest fits: years are often flexible."
                ),
            )
        )
    education = report.education
    if education.status in ("below", "partial"):
        areas.append(
            ImprovementArea(
                topic="Education",
                priority="low",
                reason="The degree level on record is below what the job describes.",
                suggestion=(
                    "Highlight relevant coursework, certificates and projects"
                    + (
                        "; this job accepts equivalent practical experience."
                        if education.equivalent_experience_ok
                        else "."
                    )
                ),
            )
        )
    relevance = report.project_relevance
    if relevance.value is not None and relevance.value < 0.5:
        areas.append(
            ImprovementArea(
                topic="Relevant projects",
                priority="medium",
                reason="Your projects cover little of the technology this job names.",
                suggestion=(
                    "Build or describe a project that combines the job's main technologies, "
                    "and write what it does and what you built yourself."
                ),
            )
        )
    areas.sort(key=lambda a: _PRIORITY[a.priority])
    return areas[:MAX_AREAS]


def preparation_topics(report: MatchReport, parsed: ParsedJob) -> list[PreparationTopic]:
    topics: list[PreparationTopic] = []
    for strength in report.technical_strengths[:5]:
        where = strength.evidence[0].ref if strength.evidence else "your records"
        topics.append(
            PreparationTopic(
                topic=f"Tell a concrete story about {strength.skill}",
                reason=(
                    f"The job asks for it and you have evidence ({where}). Prepare the problem, "
                    "what you did yourself, and the result."
                ),
            )
        )
    for name in report.weakly_supported_requirements[:4]:
        topics.append(
            PreparationTopic(
                topic=f"Prepare an example of using {name}",
                reason=(
                    "You list it but have no concrete example yet; interviewers will ask for one."
                ),
            )
        )
    for name in report.missing_requirements[:5]:
        topics.append(
            PreparationTopic(
                topic=f"Learn the basics of {name}",
                reason=(
                    "The job mentions it and nothing on record shows it. Be honest about your "
                    "level and show how you learn new tools quickly."
                ),
            )
        )
    for statement in parsed.responsibilities[:3]:
        topics.append(
            PreparationTopic(
                topic=f"Duty from the posting: {statement.text[:120]}",
                reason="Think of a past situation (study, project or work) that resembles this.",
            )
        )
    for soft in parsed.soft_skills[:3]:
        topics.append(
            PreparationTopic(
                topic=f"Examples of {soft.name.lower()}",
                reason="The posting mentions it; prepare a short example for each.",
            )
        )
    return topics[:MAX_TOPICS]
