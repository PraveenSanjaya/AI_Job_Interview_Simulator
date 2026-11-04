from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Education, Skill, UserProfile
from tests.helpers import bearer, register_and_login

pytestmark = pytest.mark.anyio

PROFILE = "/api/v1/profile"


def full_profile(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "full_name": "Ada Lovelace",
        "headline": "Junior Python Developer",
        "career_objective": "Build reliable backend systems.",
        "experience_level": "junior",
        "preferred_difficulty": "intermediate",
        "preferred_roles": ["Backend Developer", "Data Engineer"],
        "education": [
            {
                "institution": "SLIIT",
                "degree": "BSc (Hons) IT",
                "field_of_study": "Software Engineering",
                "start_date": "2022-02-01",
                "end_date": "2026-01-31",
            }
        ],
        "work_experience": [
            {
                "company": "Acme",
                "title": "Intern",
                "start_date": "2025-06-01",
                "is_current": True,
                "description": "Built APIs.",
            }
        ],
        "skills": [
            {"name": "Python", "category": "technical", "proficiency": "advanced"},
            {"name": "SQL", "category": "technical"},
            {"name": "Teamwork", "category": "soft"},
        ],
        "projects": [
            {
                "name": "Interview Simulator",
                "description": "AI mock interviews.",
                "technologies": ["FastAPI", "PostgreSQL"],
                "url": "https://github.com/example/sim",
            }
        ],
        "certifications": [
            {"name": "AWS Cloud Practitioner", "issuer": "AWS", "issued_date": "2025-03-01"}
        ],
    }
    data.update(overrides)
    return data


async def auth_headers(client: httpx.AsyncClient, email: str = "ada@example.com") -> dict[str, str]:
    tokens = await register_and_login(client, email)
    return bearer(tokens["access_token"])


async def test_new_user_has_an_empty_profile_from_registration(
    client: httpx.AsyncClient,
) -> None:
    headers = await auth_headers(client)
    response = await client.get(PROFILE, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "ada@example.com"
    assert body["full_name"] == "Ada Lovelace"
    assert body["headline"] is None
    for key in ("preferred_roles", "education", "work_experience", "skills", "projects"):
        assert body[key] == []
    assert body["certifications"] == []


async def test_profile_requires_authentication(client: httpx.AsyncClient) -> None:
    for method in ("get", "put"):
        response = await getattr(client, method)(PROFILE)
        assert response.status_code == 401
    assert (await client.get(f"{PROFILE}/skills")).status_code == 401


async def test_put_stores_all_sections_and_get_returns_them(client: httpx.AsyncClient) -> None:
    headers = await auth_headers(client)
    response = await client.put(PROFILE, json=full_profile(), headers=headers)
    assert response.status_code == 200, response.text
    body = (await client.get(PROFILE, headers=headers)).json()

    assert body["headline"] == "Junior Python Developer"
    assert body["experience_level"] == "junior"
    assert body["preferred_difficulty"] == "intermediate"
    assert body["preferred_roles"] == ["Backend Developer", "Data Engineer"]
    assert body["education"][0]["institution"] == "SLIIT"
    assert body["education"][0]["start_date"] == "2022-02-01"
    assert body["work_experience"][0]["is_current"] is True
    assert [s["name"] for s in body["skills"]] == ["Python", "SQL", "Teamwork"]
    assert body["skills"][0]["proficiency"] == "advanced"
    assert body["projects"][0]["technologies"] == ["FastAPI", "PostgreSQL"]
    assert body["certifications"][0]["issuer"] == "AWS"
    assert body == response.json()


async def test_put_replaces_everything_and_clears_omitted_fields(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    headers = await auth_headers(client)
    await client.put(PROFILE, json=full_profile(), headers=headers)
    response = await client.put(PROFILE, json={"full_name": "Ada L."}, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Ada L."
    assert body["headline"] is None
    assert body["skills"] == [] and body["education"] == []
    # Replaced rows are really deleted, not orphaned.
    assert (await session.execute(select(func.count()).select_from(Skill))).scalar_one() == 0
    assert (await session.execute(select(func.count()).select_from(Education))).scalar_one() == 0


async def test_resubmitting_the_same_skills_does_not_violate_uniqueness(
    client: httpx.AsyncClient,
) -> None:
    headers = await auth_headers(client)
    payload = full_profile()
    assert (await client.put(PROFILE, json=payload, headers=headers)).status_code == 200
    assert (await client.put(PROFILE, json=payload, headers=headers)).status_code == 200


async def test_order_of_items_is_preserved(client: httpx.AsyncClient) -> None:
    headers = await auth_headers(client)
    skills = [{"name": n, "category": "technical"} for n in ("Zed", "Alpha", "Mid")]
    await client.put(PROFILE, json=full_profile(skills=skills), headers=headers)
    body = (await client.get(PROFILE, headers=headers)).json()
    assert [s["name"] for s in body["skills"]] == ["Zed", "Alpha", "Mid"]


async def test_skills_endpoint(client: httpx.AsyncClient) -> None:
    headers = await auth_headers(client)
    await client.put(PROFILE, json=full_profile(), headers=headers)
    response = await client.get(f"{PROFILE}/skills", headers=headers)
    assert response.status_code == 200
    assert {(s["name"], s["category"]) for s in response.json()} == {
        ("Python", "technical"),
        ("SQL", "technical"),
        ("Teamwork", "soft"),
    }


async def test_text_is_trimmed(client: httpx.AsyncClient) -> None:
    headers = await auth_headers(client)
    response = await client.put(
        PROFILE, json=full_profile(headline="  Dev  ", preferred_roles=["  QA  "]), headers=headers
    )
    assert response.json()["headline"] == "Dev"
    assert response.json()["preferred_roles"] == ["QA"]


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"full_name": ""}, "full_name"),
        ({"headline": "x" * 201}, "headline"),
        ({"experience_level": "wizard"}, "experience_level"),
        ({"preferred_difficulty": "impossible"}, "preferred_difficulty"),
        ({"preferred_roles": ["a", "A"]}, "preferred_roles"),
        ({"preferred_roles": [f"r{i}" for i in range(21)]}, "preferred_roles"),
        ({"skills": [{"name": "Go", "category": "technical"}] * 2}, "skills"),
        ({"skills": [{"name": "Go", "category": "magic"}]}, "skills"),
        ({"skills": [{"name": "", "category": "soft"}]}, "skills"),
        (
            {
                "education": [
                    {
                        "institution": "X",
                        "degree": "Y",
                        "start_date": "2020-01-01",
                        "end_date": "2019-01-01",
                    }
                ]
            },
            "education",
        ),
        (
            {
                "work_experience": [
                    {"company": "A", "title": "B", "is_current": True, "end_date": "2024-01-01"}
                ]
            },
            "work_experience",
        ),
        (
            {"education": [{"institution": "X", "degree": "Y", "start_date": "not-a-date"}]},
            "education",
        ),
        ({"projects": [{"name": "P", "url": "javascript:alert(1)"}]}, "projects"),
        ({"projects": [{"name": "P", "url": "ftp://example.com/x"}]}, "projects"),
        ({"projects": [{"name": "P", "technologies": ["t"] * 31}]}, "projects"),
        (
            {"certifications": [{"name": "C", "credential_url": "data:text/html,hi"}]},
            "certifications",
        ),
        ({"career_objective": "x" * 5001}, "career_objective"),
    ],
)
async def test_invalid_profile_data_is_rejected(
    client: httpx.AsyncClient, override: dict[str, Any], field: str
) -> None:
    headers = await auth_headers(client)
    response = await client.put(PROFILE, json=full_profile(**override), headers=headers)
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert any(field in detail["location"] for detail in body["details"])


async def test_invalid_update_leaves_existing_profile_unchanged(
    client: httpx.AsyncClient,
) -> None:
    headers = await auth_headers(client)
    await client.put(PROFILE, json=full_profile(), headers=headers)
    bad = await client.put(PROFILE, json=full_profile(headline="x" * 500), headers=headers)
    assert bad.status_code == 422
    body = (await client.get(PROFILE, headers=headers)).json()
    assert body["headline"] == "Junior Python Developer"
    assert len(body["skills"]) == 3


async def test_client_cannot_inject_ids_or_ownership_fields(client: httpx.AsyncClient) -> None:
    headers = await auth_headers(client)
    for extra in (
        {"user_id": "00000000-0000-0000-0000-000000000000"},
        {"id": "x"},
        {"role": "admin"},
    ):
        response = await client.put(PROFILE, json=full_profile(**extra), headers=headers)
        assert response.status_code == 422
    nested = full_profile(skills=[{"name": "Go", "category": "soft", "id": "abc"}])
    assert (await client.put(PROFILE, json=nested, headers=headers)).status_code == 422


async def test_stored_markup_is_returned_verbatim_as_json_text(
    client: httpx.AsyncClient,
) -> None:
    """The API stores text as data and never interprets it; escaping is the UI's job."""
    headers = await auth_headers(client)
    payload = "<script>alert(1)</script>"
    response = await client.put(PROFILE, json=full_profile(headline=payload), headers=headers)
    assert response.json()["headline"] == payload
    assert response.headers["content-type"].startswith("application/json")


async def test_sql_injection_strings_are_treated_as_data(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    headers = await auth_headers(client)
    evil = "x'); DROP TABLE user_profiles;--"
    response = await client.put(PROFILE, json=full_profile(headline=evil), headers=headers)
    assert response.status_code == 200
    assert response.json()["headline"] == evil
    assert (await session.execute(select(func.count()).select_from(UserProfile))).scalar_one() == 1
