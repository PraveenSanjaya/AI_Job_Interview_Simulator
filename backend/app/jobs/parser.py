"""Deterministic job description parser.

Works only from what the text literally says: a technology is reported when its name (or a
listed alias) appears; importance comes from the section heading it sits under or from
explicit wording in its sentence ("required", "nice to have"). When neither says, the
importance is ``unspecified`` and a warning explains that, rather than guessing. The same
input always gives the same output; no network or AI is involved.
"""

import re
from itertools import pairwise
from typing import Literal

from app.jobs.schemas import (
    EducationLevel,
    Importance,
    JobEducation,
    JobExperience,
    JobLabel,
    JobSeniority,
    JobSkill,
    JobStatement,
    ParsedJob,
    SeniorityLevel,
)
from app.jobs.taxonomy import find_entries, find_matches

Section = Literal["intro", "required", "preferred", "responsibilities", "other"]

MAX_QUOTE = 220
MAX_STATEMENTS = 25

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BULLET = re.compile(r"^\s*(?:[-*•▪◦·‣]|\d{1,2}[.)])\s+")
_SENTENCES = re.compile(r"(?<=[.!?;])\s+(?=[A-Z0-9(\"'])")

_REQUIRED_HEADINGS = {
    "requirements", "required", "required skills", "required qualifications",
    "minimum qualifications", "basic qualifications", "minimum requirements", "must have",
    "must haves", "musthaves", "what you need", "what we are looking for",
    "what were looking for", "what you bring", "what youll bring", "who you are",
    "about you", "your profile", "you have", "qualifications", "skills",
    "skills and qualifications", "skills and experience", "experience", "key requirements",
    "essential", "essential skills", "requirements and qualifications", "technical skills",
    "technical requirements", "the ideal candidate", "ideal candidate", "what we expect",
    "key qualifications", "what you should have",
}  # fmt: skip
_PREFERRED_HEADINGS = {
    "preferred", "preferred qualifications", "preferred skills", "nice to have",
    "nice to haves", "nicetohave", "bonus", "bonus points", "good to have", "desirable",
    "desirable skills", "pluses", "a plus", "extra credit", "additional qualifications",
    "its a plus", "preferred experience", "bonus skills",
}  # fmt: skip
_RESPONSIBILITY_HEADINGS = {
    "responsibilities", "key responsibilities", "what youll do", "what you will do",
    "your responsibilities", "the role", "your role", "role overview", "duties", "day to day",
    "in this role", "what you will be doing", "job duties", "role and responsibilities",
    "responsibilities and duties", "what youll be doing",
}  # fmt: skip
_OTHER_HEADINGS = {
    "about us", "about the company", "about the team", "company overview", "who we are",
    "benefits", "perks", "what we offer", "why join us", "compensation", "salary",
    "equal opportunity", "equal opportunity employer", "how to apply", "our values",
    "culture", "about", "about the role", "overview", "our mission",
}  # fmt: skip

_HEADING_WITH_TEXT = re.compile(r"^\W*([A-Za-z'\u2019/& -]{3,45}?)\s*:\s*(.*)$")

_PREFERRED_CUES = re.compile(
    r"\b(nice[- ]to[- ]have|preferred|preferably|a plus|is a plus|bonus|desirable|ideally|"
    r"advantage|beneficial|good to have|an asset|not required|optional)\b",
    re.IGNORECASE,
)
_REQUIRED_CUES = re.compile(
    r"\b(required|requirements?|must|essential|mandatory|minimum|proficien\w*|strong|solid|"
    r"extensive|expert\w*|need(?:ed)?)\b",
    re.IGNORECASE,
)
_EXPLICIT_REQUIRED = re.compile(r"\b(required|must|essential|mandatory)\b", re.IGNORECASE)

_YEARS = re.compile(
    r"(?<![\d.])(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|\u2013|to)\s*(\d{1,2})\s*)?(?:\+\s*)?"
    r"(?:years?|yrs?)\b",
    re.IGNORECASE,
)
_EQUIVALENT = re.compile(
    r"\bor\s+(?:equivalent|comparable|relevant)\b|\bor\s+equivalent\s+(?:practical\s+)?experience\b"
    r"|\bequivalent\s+(?:practical\s+)?experience\b",
    re.IGNORECASE,
)

_EDUCATION_PATTERNS: tuple[tuple[EducationLevel, re.Pattern[str]], ...] = (
    ("doctorate", re.compile(r"\b(ph\.?d\.?|doctorate|doctoral)\b", re.IGNORECASE)),
    (
        "master",
        re.compile(r"\b(master'?s?|masters|m\.?sc\.?|mba|m\.s\.|master of)\b", re.IGNORECASE),
    ),
    (
        "bachelor",
        re.compile(
            r"\b(bachelor'?s?|bachelors|b\.?sc\.?|b\.?tech|b\.s\.|b\.a\.|b\.?eng\.?|bs|ba)\b"
            r"(?=\s*(?:\(|degree|in|of|,|/|or|$|\.))",
            re.IGNORECASE,
        ),
    ),
    ("associate", re.compile(r"\b(associate'?s? degree|diploma)\b", re.IGNORECASE)),
    (
        "degree_unspecified",
        re.compile(
            r"\b(university degree|college degree|undergraduate degree|degree in|a degree)\b",
            re.IGNORECASE,
        ),
    ),
)
_FIELD = re.compile(
    r"\b(?:degree|bachelor'?s?|master'?s?|b\.?sc\.?|m\.?sc\.?|ph\.?d\.?)\s*"
    r"(?:\([^)]*\)\s*)?(?:degree\s*)?(?:in|of)\s+([A-Za-z][A-Za-z ,&/-]{2,70}?)"
    r"(?=\s*(?:[.;:)]|,\s*(?:or|and)\b|\bor\b|\band\b(?!\s+[A-Za-z]+\s+Science)|\bwith\b|$))",
    re.IGNORECASE,
)

_CERT_GENERIC = re.compile(
    r"\b((?:AWS|Azure|Google Cloud|GCP|Microsoft|Cisco|Oracle|Kubernetes|Red Hat)\s+"
    r"Certified\s+[A-Z][A-Za-z0-9+-]*(?:\s+[A-Z][A-Za-z0-9+-]*){0,3})"
)

_SENIORITY_PATTERNS: tuple[tuple[SeniorityLevel, re.Pattern[str]], ...] = (
    (
        "lead",
        re.compile(
            r"\b(lead|staff|principal|head of|architect|engineering manager)\b", re.IGNORECASE
        ),
    ),
    ("senior", re.compile(r"\b(senior|sr\.?)\b", re.IGNORECASE)),
    ("mid", re.compile(r"\b(mid[- ]level|mid[- ]senior|intermediate)\b", re.IGNORECASE)),
    (
        "junior",
        re.compile(r"\b(junior|jr\.?|associate engineer|associate developer)\b", re.IGNORECASE),
    ),
    (
        "entry",
        re.compile(
            r"\b(intern(?:ship)?|entry[- ]level|new grad(?:uate)?|"
            r"graduate (?:role|program|engineer)|apprentice|trainee)\b",
            re.IGNORECASE,
        ),
    ),
)

_RANK: dict[Importance, int] = {"unspecified": 0, "preferred": 1, "required": 2}


def _normalise_heading(text: str) -> str:
    cleaned = re.sub(r"[*#_`]", "", text).replace("\u2019", "").replace("'", "")
    return " ".join(cleaned.strip().strip(":").split()).lower()


def _section_for(heading: str) -> Section | None:
    key = _normalise_heading(heading)
    if key in _PREFERRED_HEADINGS:
        return "preferred"
    if key in _REQUIRED_HEADINGS:
        return "required"
    if key in _RESPONSIBILITY_HEADINGS:
        return "responsibilities"
    if key in _OTHER_HEADINGS:
        return "other"
    return None


def _quote(text: str) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= MAX_QUOTE else one_line[: MAX_QUOTE - 1] + "…"


def _importance(unit: str, section: Section) -> tuple[Importance, bool]:
    """Importance of a sentence: explicit wording first, then its section, else unspecified."""
    if _PREFERRED_CUES.search(unit):
        return "preferred", True
    if section == "preferred":
        return "preferred", True
    if section in ("responsibilities", "other"):
        if _EXPLICIT_REQUIRED.search(unit):
            return "required", True
        return "unspecified", False
    if section == "required":
        return "required", True
    if _REQUIRED_CUES.search(unit):
        return "required", True
    return "unspecified", False


class _Unit:
    __slots__ = ("bullet", "section", "text")

    def __init__(self, text: str, section: Section, bullet: bool) -> None:
        self.text = text
        self.section = section
        self.bullet = bullet


def _split_units(description: str) -> list[_Unit]:
    cleaned = _CONTROL.sub("", description.replace("\r\n", "\n").replace("\r", "\n"))
    units: list[_Unit] = []
    section: Section = "intro"
    for raw_line in cleaned.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        content = line
        bullet = bool(_BULLET.match(line))
        if bullet:
            content = _BULLET.sub("", line, count=1).strip()
        elif (heading := _section_for(line)) is not None and len(line) <= 60:
            section = heading
            continue
        else:
            with_text = _HEADING_WITH_TEXT.match(line)
            if with_text and (new := _section_for(with_text.group(1))) is not None:
                section = new
                content = with_text.group(2).strip()
                if not content:
                    continue
        for sentence in _SENTENCES.split(content):
            sentence = sentence.strip()
            if sentence:
                units.append(_Unit(sentence, section, bullet))
    return units


_OR = re.compile(r"^\s*(?:,\s*)?or\s*$", re.IGNORECASE)


def _alternatives(unit: str) -> dict[str, list[str]]:
    """Skills the sentence offers as interchangeable: only the word "or" counts
    ("Python or Java"), never "and" or a slash ("HTML/CSS")."""
    hits = find_matches(unit, "technical")
    groups: dict[str, list[str]] = {}
    for (_, end, first), (start, _, second) in pairwise(hits):
        if first.name != second.name and _OR.match(unit[end:start]):
            groups.setdefault(first.name, []).append(second.name)
            groups.setdefault(second.name, []).append(first.name)
    return groups


def _merge_skill(store: dict[str, JobSkill], skill: JobSkill) -> None:
    existing = store.get(skill.name)
    if existing is None:
        store[skill.name] = skill
        return
    if _RANK[skill.importance] > _RANK[existing.importance]:
        existing.importance = skill.importance
        existing.importance_stated = skill.importance_stated
        existing.quote = skill.quote
    elif skill.importance == existing.importance and skill.importance_stated:
        existing.importance_stated = True
    for alt in skill.alternatives:
        if alt not in existing.alternatives:
            existing.alternatives.append(alt)


def _merge_label(store: dict[str, JobLabel], label: JobLabel) -> None:
    existing = store.get(label.name)
    if existing is None or _RANK[label.importance] > _RANK[existing.importance]:
        store[label.name] = label


def _education_in(unit: _Unit, importance: Importance) -> list[JobEducation]:
    found: list[JobEducation] = []
    for level, pattern in _EDUCATION_PATTERNS:
        if pattern.search(unit.text):
            field = None
            if match := _FIELD.search(unit.text):
                field = " ".join(match.group(1).split()).strip(" ,")
            found.append(
                JobEducation(
                    level=level,
                    field_of_study=field,
                    importance=importance,
                    equivalent_experience_ok=bool(_EQUIVALENT.search(unit.text)),
                    quote=_quote(unit.text),
                )
            )
            break  # the highest level named in the sentence is the one that matters
    return found


def _experience_in(unit: _Unit, importance: Importance) -> list[JobExperience]:
    found: list[JobExperience] = []
    for match in _YEARS.finditer(unit.text):
        low = int(match.group(1))
        high = int(match.group(2)) if match.group(2) else None
        if high is not None and high < low:
            low, high = high, low
        tail = unit.text[match.end() : match.end() + 90]
        head = unit.text[max(0, match.start() - 40) : match.start()]
        # Only count phrases about experience, not e.g. "company founded 10 years ago".
        if not re.search(r"experience|exposure|background|working|using|with", tail + head, re.I):
            continue
        skill = None
        if (named := find_entries(tail, "technical")) and re.search(
            r"(?:in|with|using|of)\b", tail[: tail.casefold().find(named[0].name.casefold())]
        ):
            skill = named[0].name
        found.append(
            JobExperience(
                min_years=low,
                max_years=high,
                skill=skill,
                importance=importance,
                quote=_quote(unit.text),
            )
        )
    return found


def _seniority(title: str, units: list[_Unit], overall_years: int | None) -> JobSeniority:
    for text in [title] + [u.text for u in units[:6]]:
        for level, pattern in _SENIORITY_PATTERNS:
            if pattern.search(text):
                return JobSeniority(level=level, basis="stated", quote=_quote(text))
    if overall_years is not None:
        inferred: SeniorityLevel = (
            "junior" if overall_years <= 2 else "mid" if overall_years <= 5 else "senior"
        )
        return JobSeniority(
            level=inferred,
            basis="inferred_from_years",
            quote=f"Inferred from the stated {overall_years}+ years of experience.",
        )
    return JobSeniority()


def parse_job(title: str, description: str) -> ParsedJob:
    """Parse a job description. Pure and deterministic."""
    units = _split_units(description)

    skills: dict[str, JobSkill] = {}
    soft: dict[str, JobLabel] = {}
    certs: dict[str, JobLabel] = {}
    domains: dict[str, JobLabel] = {}
    education: list[JobEducation] = []
    experience: list[JobExperience] = []
    responsibilities: list[JobStatement] = []
    qualifications: list[JobStatement] = []

    for unit in units:
        importance, stated = _importance(unit.text, unit.section)
        technical = find_entries(unit.text, "technical")
        groups = _alternatives(unit.text)
        for entry in technical:
            _merge_skill(
                skills,
                JobSkill(
                    name=entry.name,
                    kind=entry.kind,
                    importance=importance,
                    importance_stated=stated,
                    quote=_quote(unit.text),
                    alternatives=groups.get(entry.name, []),
                ),
            )
        for entry in find_entries(unit.text, "soft"):
            _merge_label(
                soft, JobLabel(name=entry.name, importance=importance, quote=_quote(unit.text))
            )
        for entry in find_entries(unit.text, "domain"):
            _merge_label(
                domains, JobLabel(name=entry.name, importance=importance, quote=_quote(unit.text))
            )
        cert_names = [e.name for e in find_entries(unit.text, "certification")]
        cert_names += [m.group(1).strip() for m in _CERT_GENERIC.finditer(unit.text)]
        for cert in cert_names:
            _merge_label(certs, JobLabel(name=cert, importance=importance, quote=_quote(unit.text)))

        if unit.section != "other":
            education.extend(_education_in(unit, importance))
            experience.extend(_experience_in(unit, importance))

        if unit.section == "responsibilities" and len(responsibilities) < MAX_STATEMENTS:
            responsibilities.append(JobStatement(text=unit.text, importance="unspecified"))
        elif (
            unit.section in ("required", "preferred")
            and len(qualifications) < MAX_STATEMENTS
            and len(unit.text) >= 12
            and (unit.bullet or len(unit.text) <= 300)
        ):
            qualifications.append(JobStatement(text=unit.text, importance=importance))

    overall = max((e.min_years for e in experience if e.skill is None), default=None)
    parsed = ParsedJob(
        technical_skills=list(skills.values()),
        soft_skills=list(soft.values()),
        certifications=list(certs.values()),
        domain_knowledge=list(domains.values()),
        education=education,
        experience=experience,
        responsibilities=responsibilities,
        qualifications=qualifications,
        seniority=_seniority(title, units, overall),
    )
    parsed.warnings = _warnings(parsed)
    return parsed


def _warnings(parsed: ParsedJob) -> list[str]:
    notes: list[str] = []
    if not parsed.technical_skills:
        notes.append(
            "No specific technologies were recognised in this description, so a skills "
            "match cannot be calculated from it."
        )
    else:
        vague = parsed.unspecified_importance_skills
        if vague and len(vague) == len(parsed.technical_skills):
            notes.append(
                "The description never says which skills are required and which are "
                "optional, so every skill is treated as 'importance unclear'."
            )
        elif vague:
            notes.append(
                f"{len(vague)} skill(s) are mentioned without saying whether they are "
                "required or preferred: " + ", ".join(vague[:8]) + "."
            )
    if any(s.alternatives for s in parsed.technical_skills):
        notes.append(
            "Some skills are offered as alternatives (for example 'Python or Java'); "
            "having one of them is enough."
        )
    if parsed.seniority.basis == "inferred_from_years":
        notes.append("The seniority level is inferred from years of experience, not stated.")
    return notes
