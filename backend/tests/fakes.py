"""Test doubles for the AI layer. No real provider or credentials are ever needed."""

import json
from collections.abc import Callable
from typing import Any

SAMPLE_RESUME = """\
Jane Doe
jane.doe@example.com | +94 77 123 4567 | Colombo, Sri Lanka
https://github.com/janedoe

Summary
Backend engineer with five years of experience building APIs.

Experience
Backend Engineer, Acme Corp (Jan 2021 - Present)
Built REST APIs with Python and FastAPI. Led a team of three.

Education
BSc Computer Science, University of Colombo (2016 - 2020)

Skills
Python, FastAPI, PostgreSQL, Docker, Teamwork

Projects
Interview Simulator - an AI mock interview platform (FastAPI, React)

Certifications
AWS Certified Cloud Practitioner, Amazon Web Services, 2022
"""


def good_model_output(**overrides: Any) -> dict[str, Any]:
    """A well-formed model reply consistent with ``SAMPLE_RESUME``."""
    data: dict[str, Any] = {
        "facts": {
            "full_name": "Jane Doe",
            "email": "jane.doe@example.com",
            "phone": "+94 77 123 4567",
            "location": "Colombo, Sri Lanka",
            "links": ["https://github.com/janedoe"],
            "summary_as_written": "Backend engineer with five years of experience building APIs.",
            "education": [
                {
                    "institution": "University of Colombo",
                    "degree": "BSc",
                    "field_of_study": "Computer Science",
                    "start_date": "2016",
                    "end_date": "2020",
                }
            ],
            "work_experience": [
                {
                    "company": "Acme Corp",
                    "title": "Backend Engineer",
                    "start_date": "Jan 2021",
                    "end_date": None,
                    "is_current": True,
                    "description": "Built REST APIs with Python and FastAPI.",
                }
            ],
            "technical_skills": ["Python", "FastAPI", "PostgreSQL"],
            "soft_skills": ["Teamwork"],
            "tools_and_technologies": ["Docker"],
            "projects": [
                {
                    "name": "Interview Simulator",
                    "description": "AI mock interview platform",
                    "technologies": ["FastAPI", "React"],
                }
            ],
            "certifications": [
                {
                    "name": "AWS Certified Cloud Practitioner",
                    "issuer": "Amazon Web Services",
                    "issued_date": "2022",
                }
            ],
        },
        "assessment": {
            "ai_summary": "A backend engineer with API experience.",
            "strengths": ["Python and FastAPI experience"],
            "potential_skill_gaps": ["No cloud deployment experience listed"],
        },
    }
    data.update(overrides)
    return data


class FakeLLMProvider:
    """Scripted provider: returns a canned reply or raises, and records every call."""

    name = "fake"
    model = "fake-model"

    def __init__(
        self,
        reply: str | dict[str, Any] | Callable[[str, str], str] | None = None,
        *,
        error: Exception | None = None,
        is_external: bool = False,
        available: bool = True,
    ) -> None:
        self._reply = good_model_output() if reply is None else reply
        self._error = error
        self.is_external = is_external
        self._available = available
        self.calls: list[tuple[str, str]] = []

    @property
    def available(self) -> bool:
        return self._available

    async def complete_json(self, *, system: str, user: str) -> str:
        self.calls.append((system, user))
        if self._error is not None:
            raise self._error
        if callable(self._reply):
            return self._reply(system, user)
        return self._reply if isinstance(self._reply, str) else json.dumps(self._reply)
