"""Environment-based application configuration (Pydantic Settings)."""

import secrets
from functools import lru_cache
from typing import Any, Literal, Self

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

    # What to do when REDIS_URL is set but Redis cannot be reached while serving a request:
    # "fallback" counts per process (limits become per instance), "reject" answers 503.
    rate_limit_on_redis_failure: Literal["fallback", "reject"] = "fallback"

    # Sign-in failures per account, across all client addresses. Deliberately much higher than
    # the per-address limits: it only bounds guessing spread over many addresses, and it is
    # the one limit through which an attacker could slow down a victim, so it is generous and
    # counts failed attempts only.
    login_account_failure_attempts: int = Field(default=50, ge=1)
    login_account_failure_window_seconds: int = Field(default=900, ge=1)

    # AI. Optional: with ai_provider="none" (default) every non-AI feature still works.
    # Resume text is only sent to a non-local provider when the user explicitly consents.
    ai_provider: Literal["none", "openai"] = "none"
    openai_api_key: SecretStr | None = None
    openai_model: str | None = None  # no default: model names are deployment decisions
    openai_base_url: str = "https://api.openai.com/v1"
    ai_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    ai_max_input_chars: int = Field(default=30_000, ge=1000, le=200_000)

    # Public-source integrations (no credentials required). GITHUB_TOKEN is optional and
    # only raises the API rate limit for reading public data.
    github_api_base_url: str = "https://api.github.com"
    github_token: SecretStr | None = None
    github_max_repos: int = Field(default=100, ge=1, le=100)
    github_readme_repos: int = Field(default=5, ge=0, le=10)
    integration_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    integration_max_response_bytes: int = Field(default=1_000_000, ge=10_000, le=5_000_000)
    portfolio_max_pages: int = Field(default=5, ge=1, le=10)

    # Job matching. Optional overrides of the default scoring weights by dimension name,
    # as JSON, e.g. MATCH_WEIGHTS='{"required_skills": 0.5, "education": 0.0}'. Validated at
    # startup; individual match requests may override them again.
    match_weights: dict[str, float] | None = None

    # Mock interviews. Follow-ups per main question are capped; a running interview that is
    # idle for ``interview_idle_minutes`` becomes "interrupted" (resumable) and an unstarted one
    # expires after ``interview_created_expiry_hours``. ``interview_scoring`` optionally
    # overrides the default scoring rules (JSON), validated at startup.
    interview_default_followups: int = Field(default=2, ge=0, le=5)
    interview_max_followups: int = Field(default=3, ge=0, le=5)
    interview_max_questions: int = Field(default=30, ge=1, le=100)
    interview_idle_minutes: int = Field(default=120, ge=1, le=10_080)
    interview_created_expiry_hours: int = Field(default=72, ge=1, le=8_760)
    interview_scoring: dict[str, Any] | None = None

    # Document storage. "local" writes under local_storage_path (must not be served by a
    # web server); "s3" is reserved for a later phase and rejected at startup.
    storage_backend: Literal["local", "s3"] = "local"
    local_storage_path: str = "./storage"
    max_upload_bytes: int = Field(default=5 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    # Cap for every non-upload request body (JSON documents).
    max_json_body_bytes: int = Field(default=1024 * 1024, ge=16 * 1024, le=10 * 1024 * 1024)

    # How often the background retry of file removal after account deletion runs (seconds).
    # 0 turns the in-process loop off; ``python -m app.cleanup`` can then run it from cron.
    file_cleanup_interval_seconds: int = Field(default=300, ge=0)

    frontend_url: str = "http://localhost:5173"
    # Extra browser origins allowed to call the API (JSON list). ``frontend_url`` is always allowed.
    cors_allowed_origins: list[str] = Field(default_factory=list)
    backend_url: str = "http://localhost:8000"

    @field_validator("interview_scoring", mode="after")
    @classmethod
    def _valid_interview_scoring(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None:
            from app.interview.config import resolve_scoring

            resolve_scoring(value, None)  # raises a clear error for invalid rules
        return value

    @field_validator("match_weights", mode="after")
    @classmethod
    def _valid_match_weights(cls, value: dict[str, float] | None) -> dict[str, float] | None:
        if value is not None:
            from app.matching.config import ScoringWeights

            ScoringWeights(**value)  # raises a clear error for unknown names or bad values
        return value

    @field_validator(
        "database_url", "redis_url", "openai_api_key", "openai_model", "github_token", mode="before"
    )
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
