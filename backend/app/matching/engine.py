"""Deterministic, explainable candidate-to-job matching.

No AI and no randomness: the same job analysis, candidate evidence and configuration always
give the same report. The score is a weighted average of dimensions; a dimension that cannot
be assessed (the job does not ask for it, or the candidate has not recorded the data) is left
out and the remaining weights are rescaled, and the report says so. Absence of evidence is
reported as ``not_found``/``unknown``, never as proof that the candidate lacks a skill.
"""

from dataclasses import dataclass

from app.jobs.schemas import EDUCATION_RANK, JobSkill, ParsedJob
from app.jobs.taxonomy import canonical_key
from app.matching.config import ScoringConfig
from app.matching.evidence import CandidateEvidence, norm, years_in
from app.matching.recommendations import improvement_areas, preparation_topics
from app.matching.report import (
    DimensionScore,
    EducationAlignment,
    EvidenceRef,
    ExperienceAlignment,
    InformationalMatch,
    JobSnapshot,
    MatchReport,
    ProjectRelevance,
    RelevantProject,
    RequirementMatch,
    ScoreBreakdown,
    SkillGroupResult,
    SkillStatus,
    SourceAvailability,
    TechnicalStrength,
)

ALL_SOURCES = ("profile", "resume", "github", "portfolio")
SENIORITY_ORDER = {"entry": 0, "junior": 1, "mid": 2, "senior": 3, "lead": 4}
MAX_REFS = 6
_STATUS_RANK: dict[SkillStatus, int] = {
    "supported": 3,
    "weakly_supported": 2,
    "not_found": 1,
    "unknown": 0,
}
DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("required_skills", "Required skills"),
    ("preferred_skills", "Preferred skills"),
    ("experience", "Experience"),
    ("education", "Education"),
    ("project_relevance", "Project relevance"),
    ("technology_alignment", "Technology alignment"),
    ("evidence_strength", "Evidence strength"),
)


# ------------------------------------------------------------------ skills


def _unique(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    seen: set[tuple[str, str, str]] = set()
    out: list[EvidenceRef] = []
    for ref in refs:
        key = (ref.source, ref.kind, ref.ref)
        if key not in seen:
            seen.add(key)
            out.append(ref)
    return out


def _describe_refs(refs: list[EvidenceRef], limit: int = 2) -> str:
    return "; ".join(f"{r.ref} ({r.source})" for r in refs[:limit])


def _assess(
    skill: JobSkill, evidence: CandidateEvidence, unchecked: dict[str, str], config: ScoringConfig
) -> RequirementMatch:
    matched = evidence.matching(skill.name)
    shown = [i for i in matched if i.tier == "demonstrated"]
    listed = [i for i in matched if i.tier == "declared"]
    refs = _unique([r for i in shown for r in i.refs] + [r for i in listed for r in i.refs])

    status: SkillStatus
    unchecked_list = [f"{source} ({why})" for source, why in unchecked.items()]
    if shown:
        status, credit = "supported", 1.0
        shown_refs = _unique([r for i in shown for r in i.refs])
        note = f"Shown in your own material: {_describe_refs(shown_refs)}."
    elif listed:
        status, credit = "weakly_supported", config.declared_only_credit
        note = (
            "You list this skill, but it is not yet shown in a project, job or repository. "
            "Add an example that uses it to make it convincing."
        )
    elif not evidence.has_any_content:
        status, credit = "unknown", 0.0
        note = "There is no candidate evidence on record yet, so this cannot be assessed."
    else:
        status, credit = "not_found", 0.0
        note = (
            "No evidence of this was found in the data on record. That does not prove "
            "you lack it: add it to your profile if you have used it."
        )
        if unchecked_list:
            note += " Not checked: " + ", ".join(unchecked_list) + "."
    return RequirementMatch(
        name=skill.name,
        kind=skill.kind,
        importance=skill.importance,
        importance_stated=skill.importance_stated,
        status=status,
        credit=credit,
        independent_evidence=len(shown) if shown else (1 if listed else 0),
        evidence=refs[:MAX_REFS],
        job_quote=skill.quote,
        alternatives=list(skill.alternatives),
        unchecked_sources=unchecked_list if status == "not_found" else [],
        note=note,
    )


@dataclass
class _Group:
    members: list[RequirementMatch]
    best: RequirementMatch


def _groups(matches: list[RequirementMatch]) -> list[_Group]:
    """Merge skills the job offers as alternatives ("Python or Java") into one unit whose
    result is its best member, so having either is enough and neither is double counted."""
    parent = {m.name: m.name for m in matches}

    def find(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    for m in matches:
        for alt in m.alternatives:
            if alt in parent:
                parent[find(alt)] = find(m.name)
    buckets: dict[str, list[RequirementMatch]] = {}
    for m in matches:
        buckets.setdefault(find(m.name), []).append(m)
    result: list[_Group] = []
    for members in buckets.values():
        best = max(members, key=lambda m: (_STATUS_RANK[m.status], m.independent_evidence))
        if best.status in ("supported", "weakly_supported"):
            for m in members:
                if m is not best:
                    m.satisfied_via = best.name
                    m.note += f" The job accepts {best.name} instead, which is covered."
        result.append(_Group(members=members, best=best))
    return result


def _group_result(
    label: str, matches: list[RequirementMatch]
) -> tuple[SkillGroupResult, list[_Group]]:
    groups = _groups(matches)
    count = {s: sum(1 for g in groups if g.best.status == s) for s in _STATUS_RANK}
    coverage = sum(g.best.credit for g in groups) / len(groups) if groups else None
    return (
        SkillGroupResult(
            label=label,
            total=len(groups),
            supported=count["supported"],
            weakly_supported=count["weakly_supported"],
            not_found=count["not_found"],
            unknown=count["unknown"],
            coverage=coverage,
            items=matches,
        ),
        groups,
    )


# ------------------------------------------------------------- experience etc.


def _experience(parsed: ParsedJob, evidence: CandidateEvidence) -> ExperienceAlignment:
    required = parsed.overall_min_years
    specific = [f"{e.skill}: {e.min_years}+ years" for e in parsed.experience if e.skill]
    notes: list[str] = []
    if specific:
        notes.append(
            "The job asks for years with specific technologies ("
            + ", ".join(specific)
            + "). Years per technology are not calculated; check these yourself."
        )
    job_level = parsed.seniority.level
    candidate_level = evidence.experience_level
    if (
        job_level
        and candidate_level in SENIORITY_ORDER
        and SENIORITY_ORDER[candidate_level] < SENIORITY_ORDER[job_level]
    ):
        notes.append(
            f"The role looks {job_level}-level and your profile says {candidate_level}. "
            "This is informational and does not change the score."
        )
    base = {
        "required_years": required,
        "technology_specific": specific,
        "job_seniority": job_level,
        "job_seniority_basis": parsed.seniority.basis,
        "candidate_level": candidate_level,
    }
    if not required:
        return ExperienceAlignment(
            status="not_required",
            candidate_years=None,
            value=None,
            notes=notes,
            **base,
        )
    if evidence.work_entries == 0 or not evidence.work_intervals:
        reason = (
            "No work experience is recorded on your profile or CV"
            if evidence.work_entries == 0
            else "Your recorded work experience has no usable dates"
        )
        notes.append(f"{reason}, so experience could not be compared; it is left out of the score.")
        return ExperienceAlignment(
            status="unknown",
            candidate_years=None,
            value=None,
            notes=notes,
            **base,
        )
    years = years_in(evidence.work_intervals)
    value = min(1.0, years / required)
    status = "aligned" if years >= required else "partial" if value >= 0.5 else "below"
    notes.append(
        f"About {years:.1f} years of recorded work (overlapping jobs counted once) against "
        f"{required}+ requested."
    )
    return ExperienceAlignment(
        status=status,
        candidate_years=round(years, 1),
        value=round(value, 4),
        years_source=evidence.years_source,
        notes=notes,
        **base,
    )


def _education(parsed: ParsedJob, evidence: CandidateEvidence) -> EducationAlignment:
    required = [e for e in parsed.education if e.importance != "preferred"]
    if not required:
        notes = (
            ["A degree is mentioned only as preferred; it is not scored."]
            if parsed.education
            else []
        )
        return EducationAlignment(
            status="not_required",
            required_level=None,
            required_field=None,
            candidate_level=None,
            value=None,
            notes=notes,
        )
    top = max(required, key=lambda e: EDUCATION_RANK[e.level])
    base = {
        "required_level": top.level,
        "required_field": top.field_of_study,
        "equivalent_experience_ok": top.equivalent_experience_ok,
    }
    if not evidence.education_levels:
        reason = (
            "No education is recorded"
            if evidence.education_entries == 0
            else "The degree titles on record were not recognised"
        )
        return EducationAlignment(
            status="unknown",
            candidate_level=None,
            value=None,
            notes=[f"{reason}, so education could not be compared; it is left out of the score."],
            **base,
        )
    candidate = max(evidence.education_levels, key=lambda lv: EDUCATION_RANK[lv])
    have, need = EDUCATION_RANK[candidate], EDUCATION_RANK[top.level]
    if have >= need:
        return EducationAlignment(
            status="met",
            candidate_level=candidate,
            value=1.0,
            **base,
        )
    value = have / need
    notes = []
    if top.equivalent_experience_ok:
        value = max(value, 0.5)
        notes.append("The job accepts equivalent practical experience instead of this degree.")
    return EducationAlignment(
        status="partial" if value >= 0.5 else "below",
        candidate_level=candidate,
        value=round(value, 4),
        notes=notes,
        **base,
    )


def _project_relevance(scored: list[JobSkill], evidence: CandidateEvidence) -> ProjectRelevance:
    techs = {canonical_key(s.name): s.name for s in scored if s.kind != "concept"}
    if not techs:
        return ProjectRelevance(value=None, notes=["The job names no specific technologies."])
    projects = evidence.projects()
    if not projects:
        return ProjectRelevance(
            value=None,
            notes=[
                "No projects are recorded on your profile, CV, GitHub or portfolio, so project "
                "relevance is left out of the score. Adding projects makes it assessable."
            ],
        )
    relevant: list[RelevantProject] = []
    for project in projects:
        matched = [name for name in techs.values() if project.mentions_skill(name)]
        if matched:
            relevant.append(
                RelevantProject(
                    name=project.label,
                    matched_technologies=matched,
                    overlap=round(len(matched) / len(techs), 4),
                    evidence=project.refs[:MAX_REFS],
                )
            )
    relevant.sort(key=lambda p: (-p.overlap, p.name))
    best = relevant[0].overlap if relevant else 0.0
    # Covering half of the job's technologies in a single project counts as fully relevant.
    value = min(1.0, best / 0.5)
    note = (
        f"Your most relevant project covers {best:.0%} of the job's technologies."
        if relevant
        else "None of your projects mention the technologies this job names."
    )
    return ProjectRelevance(value=round(value, 4), projects=relevant[:5], notes=[note])


def _informational(
    items: list[tuple[str, str]], evidence: CandidateEvidence, kind: str
) -> list[InformationalMatch]:
    out: list[InformationalMatch] = []
    for name, importance in items:
        if kind == "cert":
            wanted = norm(name)
            hits = [
                i
                for i in evidence.items.values()
                if i.kind == "certification" and (wanted in norm(i.text) or norm(i.text) in wanted)
            ]
        else:
            hits = evidence.matching(name)
        refs = _unique([r for i in hits for r in i.refs])[:MAX_REFS]
        out.append(
            InformationalMatch(
                name=name,
                importance=importance,
                found=bool(hits),
                evidence=refs,
                note=(
                    "Mentioned in your records."
                    if hits
                    else "Not found in your records; this is not scored."
                ),
            )
        )
    return out


# -------------------------------------------------------------------- scoring


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _score(
    values: dict[str, float | None],
    explanations: dict[str, str],
    config: ScoringConfig,
    evidence: CandidateEvidence,
    job_has_requirements: bool,
) -> ScoreBreakdown:
    weights = config.weights.model_dump()
    applicable = {k: v for k, v in values.items() if v is not None and weights[k] > 0}
    total = sum(weights[k] for k in applicable)
    dimensions: list[DimensionScore] = []
    score_float = 0.0
    for key, label in DIMENSIONS:
        value = values[key]
        is_applicable = key in applicable
        effective = weights[key] / total if is_applicable and total else 0.0
        points = effective * (value or 0.0) * 100
        score_float += points
        dimensions.append(
            DimensionScore(
                key=key,
                label=label,
                weight=weights[key],
                applicable=is_applicable,
                value=None if value is None else round(value, 4),
                effective_weight=round(effective, 4),
                points=round(points, 2),
                explanation=explanations[key],
            )
        )
    formula = (
        "score = 100 x sum(effective_weight x value) over the dimensions that could be assessed; "
        "effective_weight = weight / total weight of assessed dimensions."
    )
    present = len(evidence.sources_with_content)
    confidence = "high" if present >= 3 else "medium" if present == 2 else "low"
    if len(applicable) < 3 and confidence == "high":
        confidence = "medium"
    if len(applicable) < 2:
        confidence = "low"

    if not evidence.has_any_content:
        return ScoreBreakdown(
            score=None,
            status="insufficient_evidence",
            confidence="none",
            formula=formula,
            explanation=(
                "There is no candidate evidence yet (no profile skills, projects, work "
                "history, CV analysis, GitHub or portfolio), so no score was calculated."
            ),
            dimensions=dimensions,
        )
    if not applicable or not job_has_requirements:
        return ScoreBreakdown(
            score=None,
            status="insufficient_job_detail",
            confidence="none",
            formula=formula,
            explanation=(
                "The job description names too little that can be compared (no recognisable "
                "technologies, years or degree), so no score was calculated."
            ),
            dimensions=dimensions,
        )
    score = max(0, min(100, round(score_float)))
    parts = [f"{d.label} {d.points:.1f}" for d in dimensions if d.applicable]
    skipped = [d.label for d in dimensions if not d.applicable]
    explanation = f"{score}/100 = " + " + ".join(parts) + "."
    if skipped:
        explanation += " Not assessed (left out and weights rescaled): " + ", ".join(skipped) + "."
    return ScoreBreakdown(
        score=score,
        status="scored",
        confidence=confidence,
        formula=formula,
        explanation=explanation,
        dimensions=dimensions,
    )


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


# ----------------------------------------------------------------------- main


def compute_match(
    *,
    job: JobSnapshot,
    parsed: ParsedJob,
    evidence: CandidateEvidence,
    config: ScoringConfig,
) -> MatchReport:
    unchecked = {
        source: evidence.not_available.get(source, "no data")
        for source in ALL_SOURCES
        if source not in evidence.sources_with_content
    }
    skills = [s for s in parsed.technical_skills if not s.context_only]
    required_skills = [s for s in skills if s.importance == "required"]
    preferred_skills = [s for s in skills if s.importance == "preferred"]
    if config.unspecified_importance == "as_preferred":
        preferred_skills += [s for s in skills if s.importance == "unspecified"]

    required_matches = [_assess(s, evidence, unchecked, config) for s in required_skills]
    preferred_matches = [_assess(s, evidence, unchecked, config) for s in preferred_skills]
    required, required_groups = _group_result("Required skills", required_matches)
    preferred, preferred_groups = _group_result("Preferred skills", preferred_matches)
    all_groups = required_groups + preferred_groups

    credit_by_name: dict[str, float] = {}
    for group in all_groups:
        for member in group.members:
            credit_by_name[member.name] = group.best.credit

    stack = [s for s in required_skills + preferred_skills if s.kind in ("language", "framework")]
    stack_names = list(dict.fromkeys(s.name for s in stack))
    technology_alignment = _mean([credit_by_name[n] for n in stack_names])

    matched_groups = [g for g in all_groups if g.best.status in ("supported", "weakly_supported")]
    strengths = [
        0.4
        if g.best.status == "weakly_supported"
        else (0.7 if g.best.independent_evidence == 1 else 1.0)
        for g in matched_groups
    ]
    evidence_strength = _mean(strengths)

    experience = _experience(parsed, evidence)
    education = _education(parsed, evidence)
    project_relevance = _project_relevance(required_skills + preferred_skills, evidence)

    values = {
        "required_skills": required.coverage,
        "preferred_skills": preferred.coverage,
        "experience": experience.value,
        "education": education.value,
        "project_relevance": project_relevance.value,
        "technology_alignment": technology_alignment,
        "evidence_strength": evidence_strength,
    }
    explanations = {
        "required_skills": (
            f"{required.supported} of {required.total} required skills shown in your material, "
            f"{required.weakly_supported} only listed, {required.not_found} not found."
            if required.total
            else "The job states no required technologies."
        ),
        "preferred_skills": (
            f"{preferred.supported} of {preferred.total} preferred skills shown, "
            f"{preferred.weakly_supported} only listed, {preferred.not_found} not found."
            if preferred.total
            else "The job states no preferred technologies."
        ),
        "experience": "; ".join(experience.notes[-1:]) or "The job states no years of experience.",
        "education": "; ".join(education.notes)
        or f"Education: {education.status.replace('_', ' ')}.",
        "project_relevance": "; ".join(project_relevance.notes),
        "technology_alignment": (
            f"Coverage of the job's languages and frameworks ({', '.join(stack_names)}): "
            f"{_percent(technology_alignment)}."
            if stack_names
            else "The job names no languages or frameworks."
        ),
        "evidence_strength": (
            f"How well-supported the {len(matched_groups)} matched skill(s) are: a skill "
            "shown in two or more independent places scores highest, one place less, "
            "only listed least."
            if matched_groups
            else "No matched skills to judge the strength of."
        ),
    }
    job_has_requirements = bool(skills) or bool(parsed.education) or bool(parsed.overall_min_years)
    breakdown = _score(values, explanations, config, evidence, job_has_requirements)

    best_by_status: dict[SkillStatus, list[RequirementMatch]] = {s: [] for s in _STATUS_RANK}
    for group in all_groups:
        if group.best.status in ("supported", "weakly_supported") or all(
            m.satisfied_via is None for m in group.members
        ):
            best_by_status[group.best.status].append(group.best)
    missing = [m.name for m in best_by_status["not_found"]]
    weak = [m.name for m in best_by_status["weakly_supported"]]
    unknown = [m.name for m in best_by_status["unknown"]]

    order = {"required": 0, "preferred": 1, "unspecified": 2}
    strong = sorted(
        best_by_status["supported"], key=lambda m: (order[m.importance], -m.independent_evidence)
    )
    technical_strengths = [
        TechnicalStrength(
            skill=m.name,
            importance=m.importance,
            independent_evidence=m.independent_evidence,
            evidence=m.evidence,
        )
        for m in strong
    ]

    by_source: dict[str, list[EvidenceRef]] = {s: [] for s in ALL_SOURCES}
    for group in matched_groups:
        for ref in group.best.evidence:
            if ref not in by_source[ref.source]:
                by_source[ref.source].append(ref)

    soft = _informational([(s.name, s.importance) for s in parsed.soft_skills], evidence, "soft")
    certs = _informational(
        [(c.name, c.importance) for c in parsed.certifications], evidence, "cert"
    )

    caveats = _caveats(parsed, evidence, unchecked, config, experience, education)
    report = MatchReport(
        job=job,
        score=breakdown,
        required_skills=required,
        preferred_skills=preferred,
        technical_strengths=technical_strengths,
        experience=experience,
        education=education,
        project_relevance=project_relevance,
        soft_skills=soft,
        certifications=certs,
        missing_requirements=missing,
        weakly_supported_requirements=weak,
        unverifiable_requirements=unknown,
        company_context_skills=parsed.company_context_skills,
        evidence_by_source=by_source,
        sources=SourceAvailability(
            profile="profile" in evidence.sources_with_content,
            resume="resume" in evidence.sources_with_content,
            github="github" in evidence.sources_with_content,
            portfolio="portfolio" in evidence.sources_with_content,
            not_available=unchecked,
        ),
        improvement_areas=[],
        preparation_topics=[],
        caveats=caveats,
    )
    report.improvement_areas = improvement_areas(report, [g.best for g in all_groups])
    report.preparation_topics = preparation_topics(report, parsed)
    return report


def _caveats(
    parsed: ParsedJob,
    evidence: CandidateEvidence,
    unchecked: dict[str, str],
    config: ScoringConfig,
    experience: ExperienceAlignment,
    education: EducationAlignment,
) -> list[str]:
    caveats = [
        "Everything is checked against what you have recorded (profile, CV, GitHub, "
        "portfolio). All of it is self-published, so this is a comparison of claims with "
        "the job text, not a verification of your skills."
    ]
    if unchecked:
        caveats.append(
            "Not available for this comparison: "
            + ", ".join(f"{s} ({why})" for s, why in unchecked.items())
            + ". Skills that look missing may simply be recorded there."
        )
    if parsed.unspecified_importance_skills and config.unspecified_importance == "as_preferred":
        caveats.append(
            "These skills appear in the job without saying whether they are required, so they "
            "were scored with the preferred skills: "
            + ", ".join(parsed.unspecified_importance_skills[:10])
            + "."
        )
    if parsed.company_context_skills:
        caveats.append(
            "Technologies mentioned only in company-background sections were not treated as "
            "requirements: " + ", ".join(parsed.company_context_skills[:10]) + "."
        )
    if experience.status == "unknown":
        caveats.append("Experience could not be assessed from the data on record.")
    if education.status == "unknown":
        caveats.append("Education could not be assessed from the data on record.")
    caveats.extend(parsed.warnings)
    return caveats
