"""Environment-based application configuration (Pydantic Settings)."""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance (also usable as a FastAPI dependency)."""
    return Settings()
