from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.cv_schemas import CVAnalysisResult, ExtractedFacts
from app.ai.suggestions import build_profile_suggestion, partial_to_date
from tests.fakes import SAMPLE_RESUME, FakeLLMProvider, good_model_output
from tests.helpers import bearer, register_and_login
from tests.samples import make_txt

pytestmark = pytest.mark.anyio

RESUMES = "/api/v1/resumes"
PROFILE = "/api/v1/profile"


async def setup_analyzed_resume(
    app: FastAPI, client: httpx.AsyncClient, email: str = "ada@example.com", reply: Any = None
) -> tuple[dict[str, str], str, dict[str, Any]]:
    app.state.llm_provider = FakeLLMProvider(reply)
    headers = bearer((await register_and_login(client, email))["access_token"])
    upload = await client.post(
        RESUMES,
        headers=headers,
        files={"file": ("cv.txt", make_txt(SAMPLE_RESUME.splitlines()), "text/plain")},
    )
    resume_id = upload.json()["id"]
    analysis = await client.post(f"{RESUMES}/{resume_id}/analyze", headers=headers)
    assert analysis.status_code == 200, analysis.text
    return headers, resume_id, analysis.json()


async def apply(
    client: httpx.AsyncClient, headers: dict[str, str], resume_id: str, body: dict[str, Any]
) -> httpx.Response:
    return await client.post(f"{RESUMES}/{resume_id}/apply-to-profile", headers=headers, json=body)


async def get_profile(client: httpx.AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    profile: dict[str, Any] = (await client.get(PROFILE, headers=headers)).json()
    return profile


# ------------------------------------------------------------- suggestion


async def test_analysis_offers_a_suggestion_but_applies_nothing(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    headers, _, analysis = await setup_analyzed_resume(app, client)
    suggestion = analysis["profile_suggestion"]
    assert suggestion["full_name"] == "Jane Doe"
    assert {s["name"] for s in suggestion["skills"]} == {
        "Python",
        "FastAPI",
        "PostgreSQL",
        "Docker",
        "Teamwork",
    }
    assert {s["category"] for s in suggestion["skills"] if s["name"] == "Teamwork"} == {"soft"}
    assert suggestion["education"][0]["start_date"] == "2016-01-01"
    assert suggestion["work_experience"][0]["is_current"] is True
    assert suggestion["work_experience"][0]["end_date"] is None
    # Only text the candidate wrote, never the AI-generated summary:
    assert suggestion["career_objective"].startswith("Backend engineer with five years")
    assert analysis["result"]["assessment"]["ai_summary"] not in str(suggestion)

    # ...and the profile is untouched.
    profile = await get_profile(client, headers)
    assert profile["skills"] == [] and profile["education"] == []
    assert profile["full_name"] == "Ada Lovelace" and profile["career_objective"] is None


async def test_suggestion_can_be_posted_back_unchanged(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    headers, resume_id, analysis = await setup_analyzed_resume(app, client)
    response = await apply(client, headers, resume_id, analysis["profile_suggestion"])
    assert response.status_code == 200, response.text
    assert response.json()["applied"]["skills"] == 5
    assert (await get_profile(client, headers))["education"][0]["institution"] == (
        "University of Colombo"
    )


def test_incomplete_entries_are_left_out_with_a_note_not_invented() -> None:
    facts = ExtractedFacts.model_validate(
        {
            "education": [{"institution": "Some College"}],  # no degree
            "work_experience": [{"company": "Acme"}],  # no title
            "technical_skills": ["Python"],
        }
    )
    suggestion, notes = build_profile_suggestion(CVAnalysisResult(facts=facts, assessment={}))
    assert suggestion is not None
    assert suggestion.education is None and suggestion.work_experience is None
    assert [s.name for s in suggestion.skills or []] == ["Python"]
    assert len(notes) == 2 and all("left out" in n for n in notes)


def test_nothing_extracted_means_no_suggestion() -> None:
    suggestion, notes = build_profile_suggestion(
        CVAnalysisResult(facts=ExtractedFacts(), assessment={})
    )
    assert suggestion is None and notes == []


def test_inconsistent_dates_degrade_gracefully() -> None:
    facts = ExtractedFacts.model_validate(
        {
            "work_experience": [
                {"company": "A", "title": "B", "start_date": "2022", "end_date": "2020"}
            ]
        }
    )
    suggestion, _ = build_profile_suggestion(CVAnalysisResult(facts=facts, assessment={}))
    assert suggestion is not None and suggestion.work_experience is not None
    assert suggestion.work_experience[0].start_date is None  # dates dropped, entry kept


def test_partial_dates_become_first_day_of_period() -> None:
    assert str(partial_to_date("2021")) == "2021-01-01"
    assert str(partial_to_date("2021-06")) == "2021-06-01"
    assert str(partial_to_date("2021-06-15")) == "2021-06-15"
    assert partial_to_date(None) is None


# ------------------------------------------------------------- approval & preservation


async def test_only_the_fields_the_user_selects_are_applied(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    headers, resume_id, _ = await setup_analyzed_resume(app, client)
    response = await apply(
        client, headers, resume_id, {"skills": [{"name": "Python", "category": "technical"}]}
    )
    assert response.json()["applied"] == {"skills": 1}
    profile = await get_profile(client, headers)
    assert [s["name"] for s in profile["skills"]] == ["Python"]  # not FastAPI, Docker, ...
    assert profile["education"] == [] and profile["work_experience"] == []
    assert profile["career_objective"] is None


async def test_user_can_correct_extracted_values_before_applying(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    headers, resume_id, analysis = await setup_analyzed_resume(app, client)
    edited = analysis["profile_suggestion"]
    edited["work_experience"][0]["title"] = "Senior Backend Engineer"  # user's correction
    edited["skills"] = [s for s in edited["skills"] if s["name"] != "Docker"]  # deselected
    await apply(client, headers, resume_id, edited)
    profile = await get_profile(client, headers)
    assert profile["work_experience"][0]["title"] == "Senior Backend Engineer"
    assert "Docker" not in {s["name"] for s in profile["skills"]}


async def test_existing_profile_data_is_preserved_by_default(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    headers, resume_id, analysis = await setup_analyzed_resume(app, client)
    mine = {
        "full_name": "Ada Lovelace",
        "headline": "My own headline",
        "career_objective": "My own objective",
        "skills": [
            {"name": "python", "category": "technical", "proficiency": "expert"},
            {"name": "Rust", "category": "technical"},
        ],
        "education": [{"institution": "MIT", "degree": "BSc"}],
    }
    assert (await client.put(PROFILE, json=mine, headers=headers)).status_code == 200

    response = await apply(client, headers, resume_id, analysis["profile_suggestion"])
    body = response.json()
    profile = body["profile"]

    # Scalars the user already filled are kept and reported.
    assert profile["full_name"] == "Ada Lovelace"
    assert profile["career_objective"] == "My own objective"
    assert {s["field"] for s in body["skipped"]} >= {"full_name", "career_objective"}
    # Existing skills untouched (including proficiency); "python" is not duplicated.
    by_name = {s["name"].lower(): s for s in profile["skills"]}
    assert by_name["python"]["name"] == "python" and by_name["python"]["proficiency"] == "expert"
    assert "rust" in by_name
    assert len([s for s in profile["skills"] if s["name"].lower() == "python"]) == 1
    # New skills were added, and existing education kept alongside the new entry.
    assert {"fastapi", "postgresql", "docker", "teamwork"} <= set(by_name)
    assert [e["institution"] for e in profile["education"]] == ["MIT", "University of Colombo"]
    assert body["applied"]["skills"] == 4


async def test_empty_scalars_are_filled_and_overwrite_must_be_explicit(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    headers, resume_id, _ = await setup_analyzed_resume(app, client)
    filled = await apply(client, headers, resume_id, {"career_objective": "From my CV"})
    assert filled.json()["applied"] == {"career_objective": 1}

    kept = await apply(client, headers, resume_id, {"career_objective": "Different text"})
    assert kept.json()["profile"]["career_objective"] == "From my CV"
    assert kept.json()["skipped"][0]["field"] == "career_objective"

    forced = await apply(
        client,
        headers,
        resume_id,
        {"career_objective": "Different text", "overwrite_existing": True},
    )
    assert forced.json()["profile"]["career_objective"] == "Different text"


async def test_applying_twice_is_idempotent_in_merge_mode(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    headers, resume_id, analysis = await setup_analyzed_resume(app, client)
    first = await apply(client, headers, resume_id, analysis["profile_suggestion"])
    second = await apply(client, headers, resume_id, analysis["profile_suggestion"])
    assert first.status_code == second.status_code == 200
    assert second.json()["applied"] == {}
    profile = await get_profile(client, headers)
    assert len(profile["skills"]) == 5 and len(profile["education"]) == 1
    assert len(profile["work_experience"]) == 1


async def test_replace_mode_replaces_only_the_selected_sections(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    headers, resume_id, analysis = await setup_analyzed_resume(app, client)
    await client.put(
        PROFILE,
        json={
            "full_name": "Ada Lovelace",
            "skills": [{"name": "COBOL", "category": "technical"}],
            "education": [{"institution": "MIT", "degree": "BSc"}],
        },
        headers=headers,
    )
    response = await apply(
        client,
        headers,
        resume_id,
        {"skills": analysis["profile_suggestion"]["skills"], "mode": "replace"},
    )
    profile = response.json()["profile"]
    assert "COBOL" not in {s["name"] for s in profile["skills"]}
    assert len(profile["skills"]) == 5
    assert [e["institution"] for e in profile["education"]] == ["MIT"]  # not selected: untouched


async def test_replace_can_resubmit_identical_skills_without_constraint_errors(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    headers, resume_id, analysis = await setup_analyzed_resume(app, client)
    body = {"skills": analysis["profile_suggestion"]["skills"], "mode": "replace"}
    assert (await apply(client, headers, resume_id, body)).status_code == 200
    assert (await apply(client, headers, resume_id, body)).status_code == 200


# ------------------------------------------------------------- validation & access


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"mode": "merge"},
        {"unknown_field": 1, "headline": "x"},
        {"skills": [{"name": "Go", "category": "magic"}]},
        {"skills": [{"name": "Go", "category": "soft"}, {"name": "go", "category": "soft"}]},
        {"projects": [{"name": "P", "url": "javascript:alert(1)"}]},
        {"mode": "obliterate", "headline": "x"},
        {"headline": "x" * 201},
    ],
)
async def test_invalid_apply_requests_are_rejected(
    app: FastAPI, client: httpx.AsyncClient, body: dict[str, Any]
) -> None:
    headers, resume_id, _ = await setup_analyzed_resume(app, client)
    response = await apply(client, headers, resume_id, body)
    assert response.status_code == 422
    assert (await get_profile(client, headers))["headline"] is None


async def test_apply_requires_a_completed_analysis(app: FastAPI, client: httpx.AsyncClient) -> None:
    headers = bearer((await register_and_login(client))["access_token"])
    upload = await client.post(
        RESUMES, headers=headers, files={"file": ("cv.txt", make_txt(), "text/plain")}
    )
    response = await apply(client, headers, upload.json()["id"], {"headline": "x"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "analysis_required"
    assert (await get_profile(client, headers))["headline"] is None


async def test_apply_requires_authentication(client: httpx.AsyncClient) -> None:
    zero = "00000000-0000-0000-0000-000000000000"
    response = await client.post(f"{RESUMES}/{zero}/apply-to-profile", json={"headline": "x"})
    assert response.status_code == 401


async def test_users_cannot_apply_someone_elses_resume_or_change_their_profile(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    ada_headers, resume_id, analysis = await setup_analyzed_resume(app, client, "ada@example.com")
    bob_headers = bearer((await register_and_login(client, "bob@example.com"))["access_token"])

    response = await apply(client, bob_headers, resume_id, analysis["profile_suggestion"])
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "resume_not_found"
    # Neither profile changed.
    assert (await get_profile(client, bob_headers))["skills"] == []
    assert (await get_profile(client, ada_headers))["skills"] == []


async def test_apply_changes_only_the_callers_profile(
    app: FastAPI, client: httpx.AsyncClient, session: AsyncSession
) -> None:
    ada_headers, resume_id, analysis = await setup_analyzed_resume(app, client, "ada@example.com")
    bob_headers = bearer((await register_and_login(client, "bob@example.com"))["access_token"])
    await apply(client, ada_headers, resume_id, analysis["profile_suggestion"])
    assert len((await get_profile(client, ada_headers))["skills"]) == 5
    assert (await get_profile(client, bob_headers))["skills"] == []


async def test_hallucinated_data_cannot_reach_the_profile_through_the_suggestion(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    reply = good_model_output()
    reply["facts"]["technical_skills"].append("Quantum Hacking")
    headers, resume_id, analysis = await setup_analyzed_resume(app, client, reply=reply)
    assert "Quantum Hacking" not in str(analysis["profile_suggestion"])
    await apply(client, headers, resume_id, analysis["profile_suggestion"])
    assert "Quantum Hacking" not in str(await get_profile(client, headers))
