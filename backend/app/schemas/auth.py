"""Request/response models for authentication."""

import re
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
)

from app.models.enums import UserRole

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128  # bounds Argon2 work done on attacker-supplied input


def _normalize_email(value: str) -> str:
    return value.strip().lower()


NormalizedEmail = Annotated[EmailStr, AfterValidator(_normalize_email)]
FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class RegisterRequest(BaseModel):
    email: NormalizedEmail
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    full_name: FullName

    @field_validator("password")
    @classmethod
    def _password_strength(cls, value: str) -> str:
        if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
            raise ValueError("Password must contain at least one letter and one digit")
        return value


class LoginRequest(BaseModel):
    email: NormalizedEmail
    # No strength rules here: login must not reveal the policy or reject old passwords.
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class RegistrationAccepted(BaseModel):
    """Identical for new and already-registered emails (prevents account enumeration)."""

    message: str = (
        "Registration request accepted. If this email address was not already registered, "
        "you can now sign in."
    )


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class LogoutRequest(RefreshRequest):
    pass


class UserResponse(BaseModel):
    """Public view of a user. Never includes password or token hashes."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: UserRole
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int = Field(description="Access token lifetime in seconds")


class DeleteAccountRequest(BaseModel):
    """Deleting an account is irreversible, so the current password is required again."""

    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class AccountDeletionResult(BaseModel):
    deleted: bool = True
    stored_files_removed: bool = Field(
        description=(
            "False when the account was deleted but some uploaded files could not be removed "
            "yet; they are no longer reachable through the application."
        )
    )
