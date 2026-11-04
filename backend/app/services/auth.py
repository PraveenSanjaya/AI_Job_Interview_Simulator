"""Authentication business logic: registration, login, token issuing."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.passwords import hash_password, needs_rehash, verify_against_dummy, verify_password
from app.core.tokens import create_access_token, generate_refresh_token, hash_refresh_token
from app.models import RefreshToken, User, UserProfile
from app.repositories.refresh_tokens import RefreshTokenRepository
from app.repositories.users import UserRepository
from app.schemas.auth import TokenResponse

INVALID_CREDENTIALS = "Incorrect email or password"


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._users = UserRepository(session)
        self._tokens = RefreshTokenRepository(session)

    async def register(self, *, email: str, password: str, full_name: str) -> User:
        if await self._users.get_by_email(email) is not None:
            raise ConflictError("Email is already registered", code="email_already_registered")
        # Argon2 is CPU-bound; keep it off the event loop.
        hashed = await asyncio.to_thread(hash_password, password)
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
            raise ConflictError(
                "Email is already registered", code="email_already_registered"
            ) from None
        return user

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
