"""What an interview may know about the candidate and the target job.

Built only from structured data (never raw CV text), and deliberately free of names,
contact details, employers and URLs. This is also exactly what is sent to an AI provider
for question generation, so the privacy boundary is in one place.
"""

from dataclasses import dataclass, field
from typing import Any

MAX_PROJECTS = 5
MAX_SKILLS = 25
MAX_DUTIES = 8
MAX_FOCUS = 8


@dataclass(frozen=True)
class ProjectContext:
    name: str
    description: str | None = None
    technologies: tuple[str, ...] = ()


@dataclass
class InterviewContext:
    experience_level: str | None = None
    preferred_roles: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    projects: list[ProjectContext] = field(default_factory=list)
    job_title: str | None = None
    job_company: str | None = None
    job_required: list[str] = field(default_factory=list)
    job_preferred: list[str] = field(default_factory=list)
    job_duties: list[str] = field(default_factory=list)
    job_seniority: str | None = None
    # Requirements the latest match found weak or missing, and topics weak in earlier
    # interviews: worth probing.
    focus_topics: list[str] = field(default_factory=list)

    @property
    def has_job(self) -> bool:
        return self.job_title is not None

    def project_names(self) -> dict[str, str]:
        return {p.name.casefold(): p.name for p in self.projects}

    def prompt_data(self) -> dict[str, Any]:
        return {
            "candidate": {
                "experience_level": self.experience_level,
                "preferred_roles": self.preferred_roles[:5],
                "skills": self.skills[:MAX_SKILLS],
                "projects": [
                    {
                        "name": p.name,
                        "description": (p.description or "")[:300],
                        "technologies": list(p.technologies)[:8],
                    }
                    for p in self.projects[:MAX_PROJECTS]
                ],
            },
            "job": (
                {
                    "title": self.job_title,
                    "company": self.job_company,
                    "seniority": self.job_seniority,
                    "required_skills": self.job_required[:15],
                    "preferred_skills": self.job_preferred[:10],
                    "duties": [d[:200] for d in self.job_duties[:MAX_DUTIES]],
                }
                if self.has_job
                else None
            ),
            "topics_to_probe": self.focus_topics[:MAX_FOCUS],
        }


@dataclass(frozen=True)
class PlannedQuestion:
    category: str
    text: str
    tags: tuple[str, ...] = ()
    expected_points: tuple[str, ...] = ()
    source: str = "question_bank"
