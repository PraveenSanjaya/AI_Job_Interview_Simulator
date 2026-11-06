import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import UnauthorizedError
from app.core.tokens import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_refresh_token,
)

SECRET = "unit-test-secret-that-is-long-enough-123456"


def make_settings() -> Settings:
    return Settings(_env_file=None, jwt_secret_key=SECRET)


def test_access_token_round_trip() -> None:
    settings = make_settings()
    user_id = uuid.uuid4()
    token, expires_in = create_access_token(user_id, settings)
    claims = decode_access_token(token, settings)
    assert claims.user_id == user_id
    assert expires_in == settings.jwt_access_token_expire_minutes * 60


def test_expired_token_is_rejected_with_specific_code() -> None:
    settings = make_settings()
    token, _ = create_access_token(
        uuid.uuid4(), settings, now=datetime.now(UTC) - timedelta(hours=2)
    )
    with pytest.raises(UnauthorizedError) as error:
        decode_access_token(token, settings)
    assert error.value.code == "token_expired"


def test_token_signed_with_another_secret_is_rejected() -> None:
    token, _ = create_access_token(uuid.uuid4(), make_settings())
    other = Settings(_env_file=None, jwt_secret_key="a-completely-different-secret-value-9876")
    with pytest.raises(UnauthorizedError) as error:
        decode_access_token(token, other)
    assert error.value.code == "invalid_token"


def test_tampered_token_is_rejected() -> None:
    settings = make_settings()
    token, _ = create_access_token(uuid.uuid4(), settings)
    header, payload, signature = token.split(".")
    forged = ".".join(
        [header, payload, signature[:-2] + ("AA" if signature[-2:] != "AA" else "BB")]
    )
    with pytest.raises(UnauthorizedError):
        decode_access_token(forged, settings)


def test_unsigned_alg_none_token_is_rejected() -> None:
    settings = make_settings()
    payload = {
        "sub": str(uuid.uuid4()),
        "iss": settings.jwt_issuer,
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        "type": "access",
    }
    token = jwt.encode(payload, key=None, algorithm="none")
    with pytest.raises(UnauthorizedError):
        decode_access_token(token, settings)


def test_token_with_wrong_type_or_issuer_is_rejected() -> None:
    settings = make_settings()
    base = {
        "sub": str(uuid.uuid4()),
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }
    wrong_type = jwt.encode(
        {**base, "iss": settings.jwt_issuer, "type": "refresh"}, SECRET, algorithm="HS256"
    )
    wrong_issuer = jwt.encode({**base, "iss": "someone-else", "type": "access"}, SECRET, "HS256")
    for token in (wrong_type, wrong_issuer):
        with pytest.raises(UnauthorizedError):
            decode_access_token(token, settings)


def test_token_missing_required_claims_is_rejected() -> None:
    settings = make_settings()
    token = jwt.encode({"sub": str(uuid.uuid4())}, SECRET, algorithm="HS256")
    with pytest.raises(UnauthorizedError):
        decode_access_token(token, settings)


def test_garbage_and_non_uuid_subject_are_rejected() -> None:
    settings = make_settings()
    with pytest.raises(UnauthorizedError):
        decode_access_token("not.a.jwt", settings)
    bad_sub = jwt.encode(
        {
            "sub": "not-a-uuid",
            "iss": settings.jwt_issuer,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "type": "access",
        },
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(UnauthorizedError):
        decode_access_token(bad_sub, settings)


def test_refresh_tokens_are_random_and_hashed_deterministically() -> None:
    first, second = generate_refresh_token(), generate_refresh_token()
    assert first != second
    assert len(first) >= 64
    digest = hash_refresh_token(first)
    assert digest == hash_refresh_token(first)
    assert len(digest) == 64
    assert first not in digest


def test_production_requires_a_strong_secret() -> None:
    for bad in (None, "short", "replace_with_secure_secret"):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, app_env="production", jwt_secret_key=bad)
    ok = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret_key="x" * 40,
        frontend_url="https://app.example.com",
    )
    assert ok.jwt_secret_is_ephemeral is False


def test_development_without_secret_gets_ephemeral_random_secret() -> None:
    first = Settings(_env_file=None)
    second = Settings(_env_file=None)
    assert first.jwt_secret_is_ephemeral is True
    assert first.jwt_secret_key is not None and second.jwt_secret_key is not None
    assert first.jwt_secret_key.get_secret_value() != second.jwt_secret_key.get_secret_value()


def test_placeholder_secret_is_not_used_even_in_development() -> None:
    settings = Settings(_env_file=None, jwt_secret_key="replace_with_secure_secret")
    assert settings.jwt_secret_is_ephemeral is True
    assert settings.jwt_secret_key is not None
    assert settings.jwt_secret_key.get_secret_value() != "replace_with_secure_secret"


def test_secret_is_not_exposed_in_repr() -> None:
    assert SECRET not in repr(make_settings())
