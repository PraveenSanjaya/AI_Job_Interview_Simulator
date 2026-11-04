"""Deterministic job description parsing."""

from app.jobs.parser import parse_job
from app.jobs.schemas import JobSkill, ParsedJob
from app.jobs.taxonomy import aliases_for, canonical_key, find_entries
from tests.samples_jobs import (
    BACKEND_JOB,
    INJECTION_JOB,
    JUNIOR_JOB,
    NO_TECH_JOB,
    VAGUE_JOB,
)


def skill(parsed: ParsedJob, name: str) -> JobSkill:
    return next(s for s in parsed.technical_skills if s.name == name)


def test_required_and_preferred_skills_follow_the_sections() -> None:
    parsed = parse_job("Senior Backend Engineer", BACKEND_JOB)
    assert {"Python", "PostgreSQL", "Docker"} <= set(parsed.required_technical_skills)
    assert {"AWS", "Terraform"} <= set(parsed.preferred_technical_skills)
    assert skill(parsed, "Python").importance_stated is True


def test_languages_frameworks_and_tools_are_listed_separately() -> None:
    parsed = parse_job("Senior Backend Engineer", BACKEND_JOB)
    assert "Python" in parsed.programming_languages
    assert "PostgreSQL" not in parsed.programming_languages
    assert {"FastAPI", "PostgreSQL", "Docker", "AWS", "Terraform"} <= set(
        parsed.frameworks_and_tools
    )


def test_company_context_section_is_not_a_requirement() -> None:
    parsed = parse_job("Senior Backend Engineer", BACKEND_JOB)
    # Kubernetes and Kafka are only mentioned in "About us": reported, but not required.
    assert skill(parsed, "Kubernetes").importance == "unspecified"
    assert skill(parsed, "Kafka").importance == "unspecified"


def test_responsibility_mentions_alone_do_not_make_a_skill_required() -> None:
    parsed = parse_job("Engineer", "Responsibilities\n- Build services with Go (golang) daily\n")
    assert skill(parsed, "Go").importance == "unspecified"


def test_required_wins_when_a_skill_appears_in_several_places() -> None:
    parsed = parse_job("Senior Backend Engineer", BACKEND_JOB)
    assert skill(parsed, "Python").importance == "required"  # also in Responsibilities


def test_every_extracted_skill_quotes_its_source_sentence() -> None:
    parsed = parse_job("Senior Backend Engineer", BACKEND_JOB)
    for item in parsed.technical_skills:
        assert item.quote
        assert item.name.casefold() in item.quote.casefold() or any(
            alias.casefold() in item.quote.casefold() for alias in aliases_for(item.name)
        )


def test_soft_skills_responsibilities_and_qualifications() -> None:
    parsed = parse_job("Senior Backend Engineer", BACKEND_JOB)
    assert "Communication" in {s.name for s in parsed.soft_skills}
    assert "Mentoring" in {s.name for s in parsed.soft_skills}
    assert any("REST APIs" in r.text for r in parsed.responsibilities)
    assert any("Strong proficiency in Python" in q.text for q in parsed.qualifications)


def test_certifications_and_domain() -> None:
    parsed = parse_job("Senior Backend Engineer", BACKEND_JOB)
    certs = {c.name: c for c in parsed.certifications}
    assert certs["AWS Certified Solutions Architect"].importance == "preferred"
    assert "Fintech" in {d.name for d in parsed.domain_knowledge}


def test_experience_requirements() -> None:
    parsed = parse_job("Senior Backend Engineer", BACKEND_JOB)
    assert parsed.overall_min_years == 5
    assert parsed.experience[0].importance == "required"


def test_technology_specific_years_are_attached_to_the_technology() -> None:
    parsed = parse_job(
        "Engineer", "Requirements\n- 3-5 years of experience with Python and 2+ years of AWS\n"
    )
    by_skill = {e.skill: e for e in parsed.experience}
    assert by_skill["Python"].min_years == 3
    assert by_skill["Python"].max_years == 5
    assert parsed.overall_min_years is None  # no general requirement was stated


def test_unrelated_years_are_not_experience_requirements() -> None:
    parsed = parse_job("Engineer", "About us\nWe were founded 12 years ago in Colombo.\n")
    assert parsed.experience == []


def test_education_requirement_with_equivalent_experience() -> None:
    parsed = parse_job("Senior Backend Engineer", BACKEND_JOB)
    education = parsed.education[0]
    assert education.level == "bachelor"
    assert education.field_of_study == "Computer Science"
    assert education.equivalent_experience_ok is True
    assert education.importance == "required"


def test_vague_education_wording_is_kept_vague() -> None:
    parsed = parse_job("Junior Python Developer", JUNIOR_JOB)
    assert parsed.education[0].level == "degree_unspecified"


def test_seniority_stated_in_title() -> None:
    parsed = parse_job("Senior Backend Engineer", BACKEND_JOB)
    assert parsed.seniority.level == "senior"
    assert parsed.seniority.basis == "stated"


def test_seniority_inferred_only_from_stated_years_and_labelled() -> None:
    parsed = parse_job("Developer", "Requirements\n- 7 years of experience in software\n")
    assert parsed.seniority.level == "senior"
    assert parsed.seniority.basis == "inferred_from_years"
    assert any("inferred" in w for w in parsed.warnings)


def test_no_seniority_signal_is_reported_as_not_found() -> None:
    parsed = parse_job("Developer", "We need someone who can write Python code for us.")
    assert parsed.seniority.level is None
    assert parsed.seniority.basis == "not_found"


def test_alternatives_are_recognised_only_for_the_word_or() -> None:
    parsed = parse_job("Junior Python Developer", JUNIOR_JOB)
    assert skill(parsed, "Python").alternatives == ["Java"]
    assert skill(parsed, "Java").alternatives == ["Python"]
    assert skill(parsed, "SQL").alternatives == []
    css = parse_job("Dev", "Requirements\n- HTML/CSS and Python\n")
    assert skill(css, "HTML").alternatives == []


def test_unspecified_importance_is_reported_not_guessed() -> None:
    parsed = parse_job("Software Engineer", VAGUE_JOB)
    assert parsed.required_technical_skills == []
    assert set(parsed.unspecified_importance_skills) >= {"Python", "Django", "PostgreSQL", "Git"}
    assert any("never says which skills are required" in w for w in parsed.warnings)


def test_a_plus_wording_marks_preferred_inside_free_text() -> None:
    parsed = parse_job("Junior Python Developer", JUNIOR_JOB)
    assert skill(parsed, "React").importance == "preferred"
    assert skill(parsed, "Docker").importance == "preferred"


def test_description_without_technologies_warns() -> None:
    parsed = parse_job("Office Coordinator", NO_TECH_JOB)
    assert parsed.technical_skills == []
    assert any("No specific technologies" in w for w in parsed.warnings)
    assert "Time Management" in {s.name for s in parsed.soft_skills}


def test_parsing_is_deterministic() -> None:
    first = parse_job("Senior Backend Engineer", BACKEND_JOB)
    second = parse_job("Senior Backend Engineer", BACKEND_JOB)
    assert first.model_dump() == second.model_dump()


def test_instructions_inside_the_description_are_just_text() -> None:
    parsed = parse_job("Backend Developer", INJECTION_JOB)
    assert parsed.required_technical_skills == ["Python"]
    assert len(parsed.technical_skills) == 1


def test_ambiguous_words_are_not_technologies() -> None:
    parsed = parse_job(
        "Engineer",
        "Requirements\n- Go beyond what is asked and take the rest of the day to plan.\n"
        "- Work with the R&D team; the C-suite reads our reports. Rest assured.\n",
    )
    assert parsed.technical_skills == []


def test_whole_word_matching_avoids_substring_hits() -> None:
    assert [e.name for e in find_entries("We use JavaScript and Postgres.", "technical")] == [
        "JavaScript",
        "PostgreSQL",
    ]
    assert find_entries("MySQL and mysqldump", "technical")[0].name == "MySQL"
    assert [e.name for e in find_entries("We use C++ and C#.", "technical")] == ["C++", "C#"]


def test_canonical_keys_unify_spellings() -> None:
    assert canonical_key("Postgres") == canonical_key("PostgreSQL")
    assert canonical_key("K8s") == canonical_key("Kubernetes")
    assert canonical_key("Go") == canonical_key("golang")
    assert canonical_key("Underwater Basket Weaving") == "underwater basket weaving"


def test_control_characters_and_windows_newlines_are_handled() -> None:
    text = "Requirements\r\n- Python\x00 and Docker\r\n"
    parsed = parse_job("Dev", text)
    assert set(parsed.required_technical_skills) == {"Python", "Docker"}


def test_skills_mentioned_only_in_company_sections_are_flagged_as_context() -> None:
    parsed = parse_job("Senior Backend Engineer", BACKEND_JOB)
    assert skill(parsed, "Kubernetes").context_only is True
    assert set(parsed.company_context_skills) == {"Kubernetes", "Kafka"}
    assert "Kubernetes" not in parsed.unspecified_importance_skills
    assert skill(parsed, "Python").context_only is False


def test_a_skill_also_required_elsewhere_is_not_context_only() -> None:
    text = "About us\nWe use Docker.\n\nRequirements\n- Docker\n"
    assert skill(parse_job("Dev", text), "Docker").context_only is False


def test_education_level_of_degree_titles() -> None:
    from app.jobs.parser import education_level

    assert education_level("BSc Computer Science") == "bachelor"
    assert education_level("MSc") == "master"
    assert education_level("PhD") == "doctorate"
    assert education_level("Diploma in IT") == "associate"
    assert education_level("Basket weaving") is None
