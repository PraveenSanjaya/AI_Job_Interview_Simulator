"""Environment-based application configuration (Pydantic Settings)."""

import secrets
from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_PRODUCTION_SECRET_LENGTH = 32
PLACEHOLDER_SECRETS = {"replace_with_secure_secret", "changeme", "secret"}


class Settings(BaseSettings):
    """Typed settings loaded from environment variables or a .env file.

    Only values needed by the current phase are declared. Unknown variables
    (e.g. future API keys) are ignored, and no external credential is required.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI Job Interview Simulator"
    app_env: Literal["development", "testing", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # None means "not configured". PostgreSQL is the production database; SQLite
    # URLs are accepted only so automated tests can run without a server.
    database_url: str | None = None
    database_echo: bool = False
    redis_url: str | None = None

    # Authentication. In production the signing secret is mandatory; elsewhere an
    # unset secret becomes a random per-process one (tokens die on restart).
    jwt_secret_key: SecretStr | None = None
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_issuer: str = "ai-job-interview-simulator"
    jwt_access_token_expire_minutes: int = Field(default=30, ge=1, le=1440)
    jwt_refresh_token_expire_days: int = Field(default=7, ge=1, le=90)
    jwt_secret_is_ephemeral: bool = False

    # Per-process rate limiting (see app.core.rate_limit); not shared between workers.
    rate_limit_enabled: bool = True
    auth_rate_limit_attempts: int = Field(default=10, ge=1)
    auth_rate_limit_window_seconds: int = Field(default=60, ge=1)

    # Document storage. "local" writes under local_storage_path (must not be served by a
    # web server); "s3" is reserved for a later phase and rejected at startup.
    storage_backend: Literal["local", "s3"] = "local"
    local_storage_path: str = "./storage"
    max_upload_bytes: int = Field(default=5 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)

    frontend_url: str = "http://localhost:5173"
    backend_url: str = "http://localhost:8000"

    @field_validator("database_url", "redis_url", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("database_url", mode="after")
    @classmethod
    def _use_async_driver(cls, value: str | None) -> str | None:
        """Accept plain postgresql:// URLs and select the asyncpg driver."""
        if value is None:
            return None
        for plain, async_prefix in (
            ("postgresql://", "postgresql+asyncpg://"),
            ("postgres://", "postgresql+asyncpg://"),
            ("sqlite://", "sqlite+aiosqlite://"),
        ):
            if value.startswith(plain):
                return async_prefix + value[len(plain) :]
        return value

    @model_validator(mode="after")
    def _ensure_jwt_secret(self) -> Self:
        secret = self.jwt_secret_key.get_secret_value() if self.jwt_secret_key else ""
        if self.app_env == "production":
            if len(secret) < MIN_PRODUCTION_SECRET_LENGTH or secret in PLACEHOLDER_SECRETS:
                raise ValueError(
                    "JWT_SECRET_KEY must be set to a random value of at least "
                    f"{MIN_PRODUCTION_SECRET_LENGTH} characters in production"
                )
        elif not secret or secret in PLACEHOLDER_SECRETS:
            self.jwt_secret_key = SecretStr(secrets.token_urlsafe(48))
            self.jwt_secret_is_ephemeral = True
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance (also usable as a FastAPI dependency)."""
    return Settings()
