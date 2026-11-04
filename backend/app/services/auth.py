"""Authentication business logic: registration, login, token issuing."""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import NoReturn

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import UnauthorizedError
from app.core.passwords import hash_password, needs_rehash, verify_against_dummy, verify_password
from app.core.tokens import create_access_token, generate_refresh_token, hash_refresh_token
from app.models import RefreshToken, User, UserProfile
from app.repositories.refresh_tokens import RefreshTokenRepository
from app.repositories.users import UserRepository
from app.schemas.auth import TokenResponse

INVALID_CREDENTIALS = "Incorrect email or password"
INVALID_REFRESH = "Invalid or expired refresh token"

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._users = UserRepository(session)
        self._tokens = RefreshTokenRepository(session)

    async def register(self, *, email: str, password: str, full_name: str) -> bool:
        """Create an account if the email is free. Returns whether one was created.

        Callers must NOT expose the result to the client: responding differently for
        an existing email would let anyone enumerate registered addresses. The
        password is hashed before the lookup so both paths do the expensive work, and
        an existing account is never modified.
        """
        # Argon2 is CPU-bound; keep it off the event loop.
        hashed = await asyncio.to_thread(hash_password, password)
        if await self._users.get_by_email(email) is not None:
            logger.info("Registration ignored: email already registered")
            return False
        user = User(
            email=email,
            hashed_password=hashed,
            profile=UserProfile(full_name=full_name),
        )
        self._users.add(user)
        try:
            await self._session.commit()
        except IntegrityError:
            # Lost a race with a concurrent registration of the same email.
            await self._session.rollback()
            logger.info("Registration ignored: email already registered (race)")
            return False
        return True

    async def login(self, *, email: str, password: str) -> TokenResponse:
        """Authenticate and issue a token pair.

        Unknown email, wrong password and disabled account all produce the same
        error, and an unknown email still performs a full hash verification so the
        outcomes cannot be distinguished by response content or timing.
        """
        user = await self._users.get_by_email(email)
        if user is None:
            await asyncio.to_thread(verify_against_dummy, password)
            raise UnauthorizedError(INVALID_CREDENTIALS, code="invalid_credentials")

        valid = await asyncio.to_thread(verify_password, password, user.hashed_password)
        if not valid or not user.is_active:
            raise UnauthorizedError(INVALID_CREDENTIALS, code="invalid_credentials")

        if needs_rehash(user.hashed_password):
            user.hashed_password = await asyncio.to_thread(hash_password, password)

        tokens = self._issue_tokens(user.id, family_id=uuid.uuid4())
        await self._session.commit()
        return tokens

    async def refresh(self, raw_refresh_token: str) -> TokenResponse:
        """Rotate a refresh token: revoke the presented one and issue a new pair.

        Presenting an already-revoked token means it was stolen or replayed, so the
        entire token family (every descendant of the original login) is revoked.
        """
        stored = await self._tokens.get_by_hash(
            hash_refresh_token(raw_refresh_token), for_update=True
        )
        if stored is None:
            raise UnauthorizedError(INVALID_REFRESH, code="invalid_refresh_token")

        now = datetime.now(UTC)
        if stored.revoked_at is not None:
            await self._reject_reuse(stored, now)
        if stored.expires_at <= now:
            raise UnauthorizedError(INVALID_REFRESH, code="invalid_refresh_token")

        user = await self._users.get_by_id(stored.user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError(INVALID_REFRESH, code="invalid_refresh_token")

        if not await self._tokens.revoke_if_active(stored.id, now):
            # Lost a concurrent rotation race: treat the loser as a replay.
            await self._reject_reuse(stored, now)

        tokens = self._issue_tokens(user.id, family_id=stored.family_id)
        await self._session.commit()
        return tokens

    async def logout(self, raw_refresh_token: str) -> None:
        """Revoke the session owning this refresh token. Idempotent; never reveals
        whether the token existed."""
        stored = await self._tokens.get_by_hash(hash_refresh_token(raw_refresh_token))
        if stored is not None:
            await self._tokens.revoke_family(stored.family_id, datetime.now(UTC))
            await self._session.commit()

    async def _reject_reuse(self, stored: RefreshToken, now: datetime) -> NoReturn:
        await self._tokens.revoke_family(stored.family_id, now)
        await self._session.commit()  # must persist before the error aborts the request
        logger.warning(
            "Refresh token reuse detected; token family revoked",
            extra={"user_id": str(stored.user_id), "family_id": str(stored.family_id)},
        )
        raise UnauthorizedError(INVALID_REFRESH, code="invalid_refresh_token")

    def _issue_tokens(self, user_id: uuid.UUID, *, family_id: uuid.UUID) -> TokenResponse:
        """Create an access token and a persisted refresh token (caller commits)."""
        access_token, expires_in = create_access_token(user_id, self._settings)
        refresh_token = generate_refresh_token()
        self._tokens.add(
            RefreshToken(
                user_id=user_id,
                family_id=family_id,
                token_hash=hash_refresh_token(refresh_token),
                expires_at=datetime.now(UTC)
                + timedelta(days=self._settings.jwt_refresh_token_expire_days),
            )
        )
        return TokenResponse(
            access_token=access_token, refresh_token=refresh_token, expires_in=expires_in
        )
