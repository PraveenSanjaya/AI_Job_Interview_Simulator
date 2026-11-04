"""Schemas for AI CV analysis.

The result deliberately separates two kinds of content:

* ``facts``: information extracted from the resume text. Each fact is checked against
  the source text (see ``grounding``) and removed if it cannot be found there.
* ``assessment``: the AI's own opinion (strengths, possible gaps, a short summary).
  It is generated, may be wrong, and is never treated as a fact about the candidate.

Model output is parsed leniently where that is safe (trimming, capping list lengths,
normalising dates) and strictly where it matters (types and structure).
"""

import re
from datetime import date
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

# ---------------------------------------------------------------- normalisers

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}
_ISO = re.compile(r"^(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?$")
_MONTH_YEAR = re.compile(r"^([a-z]{3,9})\.?\s+(\d{4})$")
_SLASH = re.compile(r"^(\d{1,2})/(\d{4})$")


def normalize_partial_date(value: Any) -> str | None:
    """Return ``YYYY``, ``YYYY-MM`` or ``YYYY-MM-DD``, or ``None`` if not understood.

    Words such as "present" give ``None`` (current roles are flagged separately).
    """
    if value is None:
        return None
    text = str(value).strip().lower()
    candidate: tuple[int, int | None, int | None] | None = None
    if match := _ISO.match(text):
        year, month, day = match.groups()
        candidate = (int(year), int(month) if month else None, int(day) if day else None)
    elif match := _MONTH_YEAR.match(text):
        name, year = match.groups()
        if name in _MONTHS:
            candidate = (int(year), _MONTHS[name], None)
    elif match := _SLASH.match(text):
        candidate = (int(match.group(2)), int(match.group(1)), None)
    if candidate is None:
        return None
    year, month, day = candidate
    try:
        date(year, month or 1, day or 1)
    except ValueError:
        return None
    if not 1950 <= year <= 2100:
        return None
    if month is None:
        return f"{year:04d}"
    if day is None:
        return f"{year:04d}-{month:02d}"
    return f"{year:04d}-{month:02d}-{day:02d}"


def _text(max_length: int) -> Any:
    def clean(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, str | int | float):
            raise ValueError("expected text")
        cleaned = " ".join(str(value).split())
        return cleaned[:max_length] or None

    return BeforeValidator(clean)


def _text_list(max_items: int, max_length: int) -> Any:
    item = _text(max_length).func

    def clean(value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("expected a list")
        seen: set[str] = set()
        out: list[str] = []
        for raw in value:
            cleaned = item(raw)
            if cleaned and cleaned.casefold() not in seen:
                seen.add(cleaned.casefold())
                out.append(cleaned)
            if len(out) >= max_items:
                break
        return out

    return BeforeValidator(clean)


def _model_list(max_items: int) -> Any:
    def clean(value: Any) -> list[Any]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("expected a list")
        return [v for v in value if v is not None][:max_items]

    return BeforeValidator(clean)


Short = Annotated[str | None, _text(200)]
Medium = Annotated[str | None, _text(1000)]
Long = Annotated[str | None, _text(3000)]
PartialDate = Annotated[str | None, BeforeValidator(normalize_partial_date)]
NameList = Annotated[list[str], _text_list(60, 100)]
SentenceList = Annotated[list[str], _text_list(10, 300)]


# ---------------------------------------------------------------- facts


class _Lenient(BaseModel):
    """Unknown keys from the model are ignored; everything else is validated."""

    model_config = ConfigDict(extra="ignore")


class ExtractedEducation(_Lenient):
    institution: Short = None
    degree: Short = None
    field_of_study: Short = None
    start_date: PartialDate = None
    end_date: PartialDate = None


class ExtractedExperience(_Lenient):
    company: Short = None
    title: Short = None
    start_date: PartialDate = None
    end_date: PartialDate = None
    is_current: bool = False
    description: Medium = None


class ExtractedProject(_Lenient):
    name: Short = None
    description: Medium = None
    technologies: Annotated[list[str], _text_list(30, 50)] = Field(default_factory=list)
    url: Short = None


class ExtractedCertification(_Lenient):
    name: Short = None
    issuer: Short = None
    issued_date: PartialDate = None


class ExtractedFacts(_Lenient):
    """Information taken from the resume text (verified against it)."""

    full_name: Short = None
    email: Short = None
    phone: Short = None
    location: Short = None
    links: Annotated[list[str], _text_list(10, 300)] = Field(default_factory=list)
    summary_as_written: Long = None
    education: Annotated[list[ExtractedEducation], _model_list(20)] = Field(default_factory=list)
    work_experience: Annotated[list[ExtractedExperience], _model_list(30)] = Field(
        default_factory=list
    )
    technical_skills: NameList = Field(default_factory=list)
    soft_skills: NameList = Field(default_factory=list)
    tools_and_technologies: NameList = Field(default_factory=list)
    projects: Annotated[list[ExtractedProject], _model_list(30)] = Field(default_factory=list)
    certifications: Annotated[list[ExtractedCertification], _model_list(30)] = Field(
        default_factory=list
    )


class AIAssessment(_Lenient):
    """The AI's opinion. Generated content: may be incomplete or wrong."""

    ai_summary: Long = None
    strengths: SentenceList = Field(default_factory=list)
    potential_skill_gaps: SentenceList = Field(default_factory=list)


class CVAnalysisOutput(_Lenient):
    """The structure the model is asked to return."""

    facts: ExtractedFacts = Field(default_factory=ExtractedFacts)
    assessment: AIAssessment = Field(default_factory=AIAssessment)


class CVAnalysisResult(BaseModel):
    """What the application stores and returns."""

    facts: ExtractedFacts
    assessment: AIAssessment
    # Derived by code from the facts (not by the AI): sections with nothing found.
    missing_information: list[str] = Field(default_factory=list)
    # Items dropped because they could not be found in the resume text.
    unverified_items_removed: int = 0
