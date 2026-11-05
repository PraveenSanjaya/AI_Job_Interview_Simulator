"""The deterministic matching engine: scoring, weights, evidence and honesty rules."""

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.ai.cv_schemas import (
    ExtractedCertification,
    ExtractedEducation,
    ExtractedExperience,
    ExtractedFacts,
    ExtractedProject,
)
from app.integrations.github.snapshot import ActivityFacts, GitHubSnapshot, RepositoryFact
from app.integrations.portfolio.crawler import PortfolioPageFact, PortfolioSnapshot
from app.jobs.parser import parse_job
from app.matching.config import ScoringConfig, ScoringWeights, resolve_config
from app.matching.engine import compute_match
from app.matching.evidence import (
    CandidateEvidence,
    CandidateProfile,
    ProfileEducation,
    ProfileProject,
    ProfileSkill,
    ProfileWork,
    build_candidate_evidence,
)
from app.matching.report import JobSnapshot, MatchReport, RequirementMatch
from tests.samples_jobs import BACKEND_JOB, INJECTION_JOB, JUNIOR_JOB, VAGUE_JOB

TODAY = date(2026, 11, 4)
NOW = datetime(2026, 11, 4, tzinfo=UTC)


def job_snapshot(title: str = "Backend Engineer") -> JobSnapshot:
    return JobSnapshot(
        job_id="job-1",
        title=title,
        company=None,
        description_sha256="0" * 64,
        analysis_parser="deterministic",
        seniority=None,
        seniority_basis="not_found",
    )


def evidence_for(
    profile: CandidateProfile | None = None,
    resume: ExtractedFacts | None = None,
    github: GitHubSnapshot | None = None,
    portfolio: PortfolioSnapshot | None = None,
) -> CandidateEvidence:
    return build_candidate_evidence(
        profile=profile, resume=resume, github=github, portfolio=portfolio, today=TODAY
    )


def match(
    text: str = BACKEND_JOB,
    *,
    title: str = "Senior Backend Engineer",
    evidence: CandidateEvidence | None = None,
    config: ScoringConfig | None = None,
) -> MatchReport:
    return compute_match(
        job=job_snapshot(title),
        parsed=parse_job(title, text),
        evidence=evidence if evidence is not None else evidence_for(),
        config=config or ScoringConfig(),
    )


def repo(name: str, **fields: object) -> RepositoryFact:
    return RepositoryFact(name=name, url=f"https://github.com/jane/{name}", **fields)


def github_with(*repos: RepositoryFact, bio: str | None = None) -> GitHubSnapshot:
    return GitHubSnapshot(
        login="jane",
        profile_url="https://github.com/jane",
        bio=bio,
        repositories=list(repos),
        activity=ActivityFacts(own_repos_pushed_last_90_days=0, own_repos_pushed_last_365_days=0),
        fetched_at=NOW,
    )


def page(url: str, text: str, title: str = "Page") -> PortfolioPageFact:
    return PortfolioPageFact(url=url, title=title, text_excerpt=text)


def portfolio_with(*pages: PortfolioPageFact) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        requested_url=pages[0].url, host="jane.example", pages=list(pages), fetched_at=NOW
    )


def strong_profile() -> CandidateProfile:
    return CandidateProfile(
        experience_level="senior",
        skills=(
            ProfileSkill("Python", "technical"),
            ProfileSkill("PostgreSQL", "technical"),
            ProfileSkill("Docker", "technical"),
            ProfileSkill("AWS", "technical"),
            ProfileSkill("Terraform", "technical"),
            ProfileSkill("Communication", "soft"),
        ),
        projects=(
            ProfileProject(
                "Orders API",
                "REST API built with Python and FastAPI, deployed with Docker on AWS",
                ("PostgreSQL", "Terraform"),
            ),
            ProfileProject("Billing", "Python service using PostgreSQL", ()),
        ),
        work=(
            ProfileWork(
                "Acme",
                "Backend Engineer",
                "Built REST APIs with Python",
                date(2018, 1, 1),
                None,
                True,
            ),
        ),
        education=(ProfileEducation("University of Colombo", "BSc", "Computer Science"),),
        certifications=("AWS Certified Solutions Architect",),
    )


def by_name(items: list[RequirementMatch], name: str) -> RequirementMatch:
    return next(i for i in items if i.name == name)


def dimension(report: MatchReport, key: str):  # type: ignore[no-untyped-def]
    return next(d for d in report.score.dimensions if d.key == key)


# ------------------------------------------------------------ statuses & coverage


def test_skill_statuses_are_supported_weak_or_not_found() -> None:
    profile = CandidateProfile(
        skills=(ProfileSkill("Docker", "technical"), ProfileSkill("PostgreSQL", "technical")),
        projects=(ProfileProject("Orders API", "REST API in Python", ()),),
    )
    report = match(evidence=evidence_for(profile))
    items = report.required_skills.items
    assert by_name(items, "Python").status == "supported"  # in a project's description
    assert by_name(items, "Docker").status == "weakly_supported"  # only listed
    assert by_name(items, "PostgreSQL").status == "weakly_supported"
    assert report.weakly_supported_requirements == ["PostgreSQL", "Docker"] or set(
        report.weakly_supported_requirements
    ) >= {"Docker", "PostgreSQL"}
    # Required coverage: Python 1.0, Docker 0.5, PostgreSQL 0.5 -> (1 + .5 + .5) / 3
    assert report.required_skills.coverage == pytest.approx(2 / 3)


def test_missing_is_not_found_and_explains_what_was_not_checked() -> None:
    profile = CandidateProfile(skills=(ProfileSkill("Python", "technical"),))
    evidence = evidence_for(profile)
    evidence.not_available = {"github": "not connected", "resume": "no analysed resume"}
    report = match(evidence=evidence)
    docker = by_name(report.required_skills.items, "Docker")
    assert docker.status == "not_found"
    assert docker.credit == 0
    assert "github (not connected)" in docker.unchecked_sources
    assert "does not prove" in docker.note
    assert "Docker" in report.missing_requirements
    assert report.unverifiable_requirements == []
    assert report.sources.not_available["portfolio"] == "no data"


def test_no_evidence_at_all_is_unknown_and_unscored() -> None:
    report = match(evidence=evidence_for(CandidateProfile()))
    assert report.score.score is None
    assert report.score.status == "insufficient_evidence"
    assert report.score.confidence == "none"
    assert {i.status for i in report.required_skills.items} == {"unknown"}
    assert report.missing_requirements == []  # nothing is called missing without evidence
    assert set(report.unverifiable_requirements) >= {"Python", "PostgreSQL", "Docker"}


def test_job_without_comparable_requirements_is_unscored() -> None:
    profile = CandidateProfile(skills=(ProfileSkill("Python", "technical"),))
    report = match("We need a friendly person to greet visitors at the front desk.", title="Host",
                   evidence=evidence_for(profile))  # fmt: skip
    assert report.score.score is None
    assert report.score.status == "insufficient_job_detail"


# ----------------------------------------------------------------- score maths


def test_strong_candidate_scores_high_and_dimensions_explain_the_total() -> None:
    report = match(evidence=evidence_for(strong_profile()))
    assert report.score.status == "scored"
    assert report.score.score is not None and report.score.score >= 90
    total = sum(d.points for d in report.score.dimensions)
    assert report.score.score == round(total)
    assert sum(d.effective_weight for d in report.score.dimensions) == pytest.approx(1.0, abs=1e-3)
    assert report.score.explanation.startswith(f"{report.score.score}/100 = ")
    assert "Required skills" in report.score.explanation
    assert "100 x sum" in report.score.formula


def test_score_stays_within_zero_and_one_hundred() -> None:
    perfect = match(evidence=evidence_for(strong_profile()))
    assert 0 <= (perfect.score.score or 0) <= 100
    unrelated = CandidateProfile(
        skills=(ProfileSkill("Knitting", "technical"),),
        projects=(ProfileProject("Scarf", "A very long scarf", ()),),
    )
    empty = match(evidence=evidence_for(unrelated))
    assert empty.score.score == 0
    assert empty.technical_strengths == []


def test_not_applicable_dimensions_are_left_out_and_weights_rescaled() -> None:
    profile = CandidateProfile(skills=(ProfileSkill("Python", "technical"),))
    report = match("Requirements\n- Python\n", title="Developer", evidence=evidence_for(profile))
    assessed = [d for d in report.score.dimensions if d.applicable]
    assert {d.key for d in assessed} == {
        "required_skills",
        "technology_alignment",
        "evidence_strength",
    }
    assert sum(d.effective_weight for d in assessed) == pytest.approx(1.0, abs=1e-3)
    assert "Not assessed" in report.score.explanation
    assert report.score.confidence == "low"


def test_weights_change_the_score_predictably() -> None:
    # Python is shown in a project; Docker only listed; Terraform missing; PostgreSQL missing.
    profile = CandidateProfile(
        skills=(ProfileSkill("Docker", "technical"),),
        projects=(ProfileProject("App", "Written in Python", ()),),
    )
    text = "Requirements\n- Python\n- Docker\nNice to have\n- Terraform\n"
    only_required = ScoringConfig(
        weights=ScoringWeights(
            required_skills=1,
            preferred_skills=0,
            experience=0,
            education=0,
            project_relevance=0,
            technology_alignment=0,
            evidence_strength=0,
        )
    )
    report = match(text, title="Dev", evidence=evidence_for(profile), config=only_required)
    assert report.score.score == 75  # (1.0 + 0.5) / 2
    only_preferred = ScoringConfig(
        weights=ScoringWeights(
            required_skills=0,
            preferred_skills=1,
            experience=0,
            education=0,
            project_relevance=0,
            technology_alignment=0,
            evidence_strength=0,
        )
    )
    assert (
        match(text, title="Dev", evidence=evidence_for(profile), config=only_preferred).score.score
        == 0
    )


def test_zero_weight_dimension_is_excluded_even_if_assessable() -> None:
    config = ScoringConfig(weights=ScoringWeights(evidence_strength=0))
    report = match(evidence=evidence_for(strong_profile()), config=config)
    strength = dimension(report, "evidence_strength")
    assert strength.applicable is False
    assert strength.effective_weight == 0


def test_declared_only_credit_is_configurable() -> None:
    profile = CandidateProfile(skills=(ProfileSkill("Python", "technical"),))
    text = "Requirements\n- Python\n"
    default = match(text, title="Dev", evidence=evidence_for(profile))
    generous = match(
        text,
        title="Dev",
        evidence=evidence_for(profile),
        config=ScoringConfig(declared_only_credit=1.0),
    )
    assert default.required_skills.coverage == 0.5
    assert generous.required_skills.coverage == 1.0


@pytest.mark.parametrize(
    "weights",
    [{"required_skills": -1}, {"unknown_dimension": 1}, {"required_skills": 1000}],
)
def test_invalid_weights_are_rejected(weights: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        resolve_config(None, weights)


def test_all_zero_weights_are_rejected() -> None:
    zero = dict.fromkeys(ScoringWeights().model_dump(), 0.0)
    with pytest.raises(ValidationError):
        resolve_config(None, zero)


def test_request_weights_override_server_weights_override_defaults() -> None:
    config = resolve_config({"required_skills": 0.9, "education": 0.2}, {"education": 0.0})
    assert config.weights.required_skills == 0.9
    assert config.weights.education == 0.0
    assert config.weights.experience == ScoringWeights().experience


# ------------------------------------------------------------- evidence rules


def test_the_same_project_in_several_sources_counts_once() -> None:
    profile = CandidateProfile(
        projects=(ProfileProject("Interview Simulator", "FastAPI backend", ()),)
    )
    resume = ExtractedFacts(
        projects=[ExtractedProject(name="Interview Simulator", description="FastAPI service")]
    )
    github = github_with(repo("interview-simulator", description="FastAPI mock interview app"))
    portfolio = portfolio_with(
        page("https://jane.example/p", "Interview Simulator: built with FastAPI", "Simulator")
    )
    report = match(
        "Requirements\n- FastAPI\n",
        title="Dev",
        evidence=evidence_for(profile, resume, github, portfolio),
    )
    fastapi = by_name(report.required_skills.items, "FastAPI")
    assert fastapi.independent_evidence == 1  # one project, seen four times
    assert {r.source for r in fastapi.evidence} == {"profile", "resume", "github", "portfolio"}
    assert len(report.project_relevance.projects) == 1


def test_different_projects_are_independent_evidence() -> None:
    profile = CandidateProfile(
        projects=(
            ProfileProject("Orders API", "FastAPI service", ()),
            ProfileProject("Blog", "A FastAPI blog engine", ()),
        )
    )
    report = match("Requirements\n- FastAPI\n", title="Dev", evidence=evidence_for(profile))
    assert by_name(report.required_skills.items, "FastAPI").independent_evidence == 2
    strength = dimension(report, "evidence_strength")
    assert strength.value == 1.0


def test_single_independent_evidence_is_weaker_than_two() -> None:
    one = CandidateProfile(projects=(ProfileProject("Orders API", "FastAPI service", ()),))
    report = match("Requirements\n- FastAPI\n", title="Dev", evidence=evidence_for(one))
    assert dimension(report, "evidence_strength").value == 0.7


def test_skill_listed_in_profile_and_resume_is_one_declaration() -> None:
    profile = CandidateProfile(skills=(ProfileSkill("Python", "technical"),))
    resume = ExtractedFacts(technical_skills=["Python"])
    report = match("Requirements\n- Python\n", title="Dev", evidence=evidence_for(profile, resume))
    python = by_name(report.required_skills.items, "Python")
    assert python.status == "weakly_supported"
    assert python.independent_evidence == 1
    assert {r.source for r in python.evidence} == {"profile", "resume"}


def test_repository_name_alone_is_not_evidence() -> None:
    github = github_with(repo("kubernetes-playground"), repo("notes", description="Python scripts"))
    report = match(
        "Requirements\n- Kubernetes\n- Python\n", title="Dev", evidence=evidence_for(github=github)
    )
    assert by_name(report.required_skills.items, "Kubernetes").status == "not_found"
    assert by_name(report.required_skills.items, "Python").status == "supported"


def test_forks_are_not_the_candidates_own_work() -> None:
    github = github_with(repo("django-fork", description="Django web framework", is_fork=True))
    github.repositories.append(repo("notes", description="misc"))
    report = match("Requirements\n- Django\n", title="Dev", evidence=evidence_for(github=github))
    assert by_name(report.required_skills.items, "Django").status == "not_found"


def test_github_primary_language_counts_as_demonstrated() -> None:
    github = github_with(repo("tool", primary_language="Go", description="A CLI"))
    report = match("Requirements\n- golang\n", title="Dev", evidence=evidence_for(github=github))
    assert by_name(report.required_skills.items, "Go").status == "supported"


def test_portfolio_only_candidate_is_scored_and_cites_the_page() -> None:
    portfolio = portfolio_with(page("https://jane.example/", "I build APIs with Python."))
    report = match(
        "Requirements\n- Python\n", title="Dev", evidence=evidence_for(portfolio=portfolio)
    )
    python = by_name(report.required_skills.items, "Python")
    assert python.status == "supported"
    assert python.evidence[0].source == "portfolio"
    assert python.evidence[0].ref == "https://jane.example/"
    assert report.sources.portfolio and not report.sources.github
    assert report.evidence_by_source["portfolio"][0].kind == "page"


def test_candidate_with_no_github_or_portfolio_still_gets_a_report() -> None:
    report = match(evidence=evidence_for(strong_profile()))
    assert report.sources.github is False and report.sources.portfolio is False
    assert report.score.confidence == "low"
    assert any("Not available for this comparison" in c for c in report.caveats)


def test_every_supported_requirement_cites_its_sources() -> None:
    report = match(evidence=evidence_for(strong_profile()))
    for item in report.required_skills.items + report.preferred_skills.items:
        if item.status in ("supported", "weakly_supported"):
            assert item.evidence, item.name
    assert report.technical_strengths
    assert all(s.evidence for s in report.technical_strengths)


def test_resume_evidence_is_used_when_profile_is_sparse() -> None:
    resume = ExtractedFacts(
        technical_skills=["Python"],
        work_experience=[
            ExtractedExperience(
                company="Acme",
                title="Developer",
                start_date="2019-01",
                end_date="2024-01",
                description="Built Docker based services",
            )
        ],
        education=[ExtractedEducation(institution="UoC", degree="MSc")],
        certifications=[ExtractedCertification(name="AWS Certified Solutions Architect")],
    )
    report = match(evidence=evidence_for(CandidateProfile(), resume))
    assert by_name(report.required_skills.items, "Docker").status == "supported"
    assert report.experience.years_source == "resume"
    assert report.education.status == "met"  # a master's covers a bachelor's requirement
    assert any(c.found for c in report.certifications)


# -------------------------------------------------------------- alternatives etc.


def test_alternatives_are_satisfied_by_either_and_counted_once() -> None:
    profile = CandidateProfile(projects=(ProfileProject("Tool", "Written in Java", ()),))
    report = match(JUNIOR_JOB, title="Junior Python Developer", evidence=evidence_for(profile))
    required = report.required_skills
    python, java = by_name(required.items, "Python"), by_name(required.items, "Java")
    assert java.status == "supported"
    assert python.status == "not_found"
    assert python.satisfied_via == "Java"
    assert "Python" not in report.missing_requirements
    # Python/Java form one unit alongside SQL.
    assert required.total == 2
    assert required.coverage == pytest.approx(0.5)  # (Java 1.0 + SQL 0.0) / 2


def test_company_context_skills_are_not_scored() -> None:
    profile = CandidateProfile(skills=(ProfileSkill("Python", "technical"),))
    report = match(evidence=evidence_for(profile))
    names = {i.name for i in report.required_skills.items + report.preferred_skills.items}
    assert "Kubernetes" not in names and "Kafka" not in names
    assert {"Kubernetes", "Kafka"} <= set(report.company_context_skills)


def test_unspecified_importance_is_scored_as_preferred_or_ignored_by_config() -> None:
    profile = CandidateProfile(skills=(ProfileSkill("Python", "technical"),))
    as_preferred = match(VAGUE_JOB, title="Software Engineer", evidence=evidence_for(profile))
    assert as_preferred.required_skills.total == 0
    assert by_name(as_preferred.preferred_skills.items, "Django").importance == "unspecified"
    assert as_preferred.score.status == "scored"
    assert any("scored with the preferred skills" in c for c in as_preferred.caveats)

    ignored = match(
        VAGUE_JOB,
        title="Software Engineer",
        evidence=evidence_for(profile),
        config=ScoringConfig(unspecified_importance="ignore"),
    )
    assert ignored.preferred_skills.total == 0
    assert ignored.score.status == "insufficient_job_detail"


def test_soft_skills_and_certifications_are_reported_but_not_scored() -> None:
    report = match(evidence=evidence_for(strong_profile()))
    soft = {s.name: s for s in report.soft_skills}
    assert soft["Communication"].found is True
    assert soft["Mentoring"].found is False
    certs = {c.name: c for c in report.certifications}
    assert certs["AWS Certified Solutions Architect"].found is True
    assert all(d.key not in ("soft_skills", "certifications") for d in report.score.dimensions)


# ---------------------------------------------------------- experience, education


def test_experience_is_compared_with_overlapping_jobs_counted_once() -> None:
    profile = CandidateProfile(
        skills=(ProfileSkill("Python", "technical"),),
        work=(
            ProfileWork("A", "Dev", None, date(2020, 1, 1), date(2022, 12, 31)),
            ProfileWork("B", "Dev", None, date(2021, 1, 1), date(2022, 12, 31)),  # inside A
            ProfileWork("C", "Dev", None, date(2023, 1, 1), date(2024, 6, 30)),
        ),
    )
    report = match(
        "Requirements\n- 8 years of experience\n- Python\n",
        title="Dev",
        evidence=evidence_for(profile),
    )
    assert report.experience.required_years == 8
    assert report.experience.candidate_years == pytest.approx(4.5, abs=0.1)
    assert report.experience.value == pytest.approx(0.56, abs=0.02)
    assert report.experience.status == "partial"


def test_experience_met_and_below() -> None:
    long_work = CandidateProfile(
        work=(ProfileWork("A", "Dev", "Python", date(2015, 1, 1), None, True),),
    )
    assert match(evidence=evidence_for(long_work)).experience.status == "aligned"
    short_work = CandidateProfile(
        work=(ProfileWork("A", "Dev", "Python", date(2026, 1, 1), None, True),),
    )
    below = match(evidence=evidence_for(short_work)).experience
    assert below.status == "below"
    assert 0 < (below.value or 0) < 0.5


def test_unrecorded_experience_is_unknown_not_zero() -> None:
    profile = CandidateProfile(skills=(ProfileSkill("Python", "technical"),))
    report = match(evidence=evidence_for(profile))
    assert report.experience.status == "unknown"
    assert report.experience.value is None
    assert dimension(report, "experience").applicable is False
    assert any("Experience could not be assessed" in c for c in report.caveats)


def test_undated_experience_is_unknown() -> None:
    profile = CandidateProfile(work=(ProfileWork("A", "Dev", "Python"),))
    assert match(evidence=evidence_for(profile)).experience.status == "unknown"


def test_technology_specific_years_are_reported_not_computed() -> None:
    report = match("Requirements\n- 3+ years of experience with Python\n", title="Dev",
                   evidence=evidence_for(strong_profile()))  # fmt: skip
    assert report.experience.status == "not_required"
    assert report.experience.technology_specific == ["Python: 3+ years"]
    assert any("Years per technology are not calculated" in n for n in report.experience.notes)


def test_education_alignment_levels() -> None:
    master_job = "Requirements\n- Master's degree in Computer Science\n- Python\n"
    bachelor = CandidateProfile(
        skills=(ProfileSkill("Python", "technical"),),
        education=(ProfileEducation("UoC", "BSc Computer Science"),),
    )
    partial = match(master_job, title="Dev", evidence=evidence_for(bachelor)).education
    assert partial.status == "partial"
    assert partial.candidate_level == "bachelor" and partial.required_level == "master"
    assert partial.value == pytest.approx(2 / 3, abs=0.01)

    equivalent = match(
        "Requirements\n- Master's degree or equivalent practical experience\n- Python\n",
        title="Dev",
        evidence=evidence_for(bachelor),
    ).education
    assert equivalent.equivalent_experience_ok is True

    none_recorded = match(master_job, title="Dev",
                          evidence=evidence_for(CandidateProfile(skills=(ProfileSkill("Python", "technical"),)))).education  # fmt: skip
    assert none_recorded.status == "unknown"
    assert none_recorded.value is None


def test_preferred_only_degree_is_not_scored() -> None:
    text = "Requirements\n- Python\nNice to have\n- Master's degree\n"
    report = match(text, title="Dev", evidence=evidence_for(strong_profile()))
    assert report.education.status == "not_required"


# -------------------------------------------------------- recommendations, honesty


def test_improvement_areas_prioritise_required_gaps() -> None:
    profile = CandidateProfile(skills=(ProfileSkill("Docker", "technical"),))
    report = match(evidence=evidence_for(profile))
    areas = report.improvement_areas
    assert areas
    priorities = [a.priority for a in areas]
    assert priorities == sorted(priorities, key=lambda p: {"high": 0, "medium": 1, "low": 2}[p])
    topics = {a.topic: a for a in areas}
    assert topics["Python"].priority == "high"
    assert topics["Docker"].priority == "medium"  # listed but not shown
    assert topics["AWS"].priority == "low"  # preferred
    assert len(areas) <= 10


def test_preparation_topics_cover_strengths_gaps_and_duties() -> None:
    report = match(evidence=evidence_for(strong_profile()))
    topics = [t.topic for t in report.preparation_topics]
    assert any(t.startswith("Tell a concrete story about") for t in topics)
    assert any(t.startswith("Duty from the posting") for t in topics)
    gap_report = match(
        evidence=evidence_for(CandidateProfile(skills=(ProfileSkill("Git", "technical"),)))
    )
    assert any(t.topic.startswith("Learn the basics of") for t in gap_report.preparation_topics)


def test_report_never_promises_outcomes() -> None:
    report = match(evidence=evidence_for(strong_profile()))
    assert "no score guarantees an interview or an offer" in report.disclaimer
    blob = report.model_dump_json().casefold()
    for phrase in ("you will get", "guaranteed", "you will be hired"):
        assert phrase not in blob.replace("no score guarantees", "")


def test_instructions_in_the_job_text_cannot_change_the_score() -> None:
    profile = CandidateProfile(skills=(ProfileSkill("Rust", "technical"),))
    report = match(INJECTION_JOB, title="Backend Developer", evidence=evidence_for(profile))
    assert by_name(report.required_skills.items, "Python").status == "not_found"
    assert report.score.score == 0


def test_matching_is_deterministic_and_order_independent() -> None:
    first = match(evidence=evidence_for(strong_profile())).model_dump()
    second = match(evidence=evidence_for(strong_profile())).model_dump()
    assert first == second
    reordered = CandidateProfile(
        **{**strong_profile().__dict__, "skills": tuple(reversed(strong_profile().skills))}
    )
    assert match(evidence=evidence_for(reordered)).score.score == first["score"]["score"]


def test_report_round_trips_through_json() -> None:
    report = match(evidence=evidence_for(strong_profile()))
    assert MatchReport.model_validate_json(report.model_dump_json()) == report
