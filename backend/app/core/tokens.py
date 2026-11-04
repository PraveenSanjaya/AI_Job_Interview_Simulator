"""Access-token (JWT) and refresh-token primitives.

* Access tokens are short-lived signed JWTs. The algorithm is pinned on decode, and
  ``exp``, ``iat``, ``sub``, ``iss`` and ``type`` are all required.
* Refresh tokens are opaque random strings. Only their SHA-256 digest is stored,
  so a database leak does not expose usable tokens. SHA-256 (not a slow hash) is
  appropriate because the tokens are 384 bits of randomness, not user passwords.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import Settings
from app.core.exceptions import UnauthorizedError

ACCESS_TOKEN_TYPE = "access"  # noqa: S105


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: uuid.UUID
    expires_at: datetime


def _secret(settings: Settings) -> str:
    assert settings.jwt_secret_key is not None  # guaranteed by Settings validation  # noqa: S101
    return settings.jwt_secret_key.get_secret_value()


def create_access_token(
    user_id: uuid.UUID, settings: Settings, *, now: datetime | None = None
) -> tuple[str, int]:
    """Return ``(token, expires_in_seconds)``."""
    issued_at = now or datetime.now(UTC)
    lifetime = timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "iss": settings.jwt_issuer,
        "iat": issued_at,
        "exp": issued_at + lifetime,
        "jti": uuid.uuid4().hex,
        "type": ACCESS_TOKEN_TYPE,
    }
    token = jwt.encode(payload, _secret(settings), algorithm=settings.jwt_algorithm)
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str, settings: Settings) -> AccessTokenClaims:
    """Validate signature, expiry, issuer and type; raise ``UnauthorizedError`` otherwise."""
    try:
        payload = jwt.decode(
            token,
            _secret(settings),
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "iss"]},
        )
        if payload.get("type") != ACCESS_TOKEN_TYPE:
            raise jwt.InvalidTokenError("wrong token type")
        return AccessTokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        )
    except jwt.ExpiredSignatureError:
        raise UnauthorizedError("Access token has expired", code="token_expired") from None
    except (jwt.InvalidTokenError, ValueError):
        raise UnauthorizedError("Invalid access token", code="invalid_token") from None


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
