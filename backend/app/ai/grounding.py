"""Verify extracted facts against the resume text so nothing is invented.

An LLM can hallucinate or be steered by text hidden in a document. Every concrete
claim that can be checked mechanically (contact details, names of employers,
institutions, skills, certifications, projects) must literally appear in the resume
text, otherwise it is removed and counted. Opinions live in ``assessment`` and are
not treated as facts.
"""

import re
from collections.abc import Callable

from app.ai.cv_schemas import ExtractedFacts

_WHITESPACE = re.compile(r"\s+")


def _squash(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip().casefold()


class _Source:
    def __init__(self, text: str) -> None:
        self.text = _squash(text)
        self.digits = re.sub(r"\D", "", text)

    def contains(self, needle: str | None) -> bool:
        """Whole-token containment, so "Go" does not match "good"."""
        if not needle:
            return False
        pattern = rf"(?<![a-z0-9]){re.escape(_squash(needle))}(?![a-z0-9])"
        return re.search(pattern, self.text) is not None

    def contains_verbatim(self, needle: str | None) -> bool:
        return bool(needle) and _squash(needle or "") in self.text

    def contains_phone(self, phone: str | None) -> bool:
        digits = re.sub(r"\D", "", phone or "")
        return len(digits) >= 6 and digits in self.digits


def ground_facts(facts: ExtractedFacts, source_text: str) -> tuple[ExtractedFacts, int]:
    """Return ``(verified_facts, number_of_items_removed)``."""
    source = _Source(source_text)
    removed = 0

    def keep_scalar(value: str | None, check: Callable[[str | None], bool]) -> str | None:
        nonlocal removed
        if value is None:
            return None
        if check(value):
            return value
        removed += 1
        return None

    def keep_names(values: list[str]) -> list[str]:
        nonlocal removed
        kept = [v for v in values if source.contains(v)]
        removed += len(values) - len(kept)
        return kept

    def keep_objects[T](items: list[T], key: Callable[[T], str | None]) -> list[T]:
        nonlocal removed
        kept = [item for item in items if source.contains(key(item))]
        removed += len(items) - len(kept)
        return kept

    return (
        ExtractedFacts(
            full_name=keep_scalar(facts.full_name, source.contains),
            email=keep_scalar(facts.email, source.contains),
            phone=keep_scalar(facts.phone, source.contains_phone),
            location=keep_scalar(facts.location, source.contains),
            links=keep_names(facts.links),
            summary_as_written=keep_scalar(facts.summary_as_written, source.contains_verbatim),
            education=keep_objects(facts.education, lambda e: e.institution),
            work_experience=keep_objects(facts.work_experience, lambda w: w.company),
            technical_skills=keep_names(facts.technical_skills),
            soft_skills=keep_names(facts.soft_skills),
            tools_and_technologies=keep_names(facts.tools_and_technologies),
            projects=keep_objects(facts.projects, lambda p: p.name),
            certifications=keep_objects(facts.certifications, lambda c: c.name),
        ),
        removed,
    )


def find_missing_information(facts: ExtractedFacts) -> list[str]:
    """Which commonly expected resume sections yielded nothing (computed, not AI)."""
    checks = {
        "full_name": bool(facts.full_name),
        "email": bool(facts.email),
        "phone": bool(facts.phone),
        "education": bool(facts.education),
        "work_experience": bool(facts.work_experience),
        "technical_skills": bool(facts.technical_skills or facts.tools_and_technologies),
        "projects": bool(facts.projects),
        "certifications": bool(facts.certifications),
    }
    return [name for name, present in checks.items() if not present]
