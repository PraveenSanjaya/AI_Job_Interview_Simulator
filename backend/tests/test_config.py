import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_defaults_require_no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("APP_ENV", "DATABASE_URL", "REDIS_URL", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert settings.app_env == "development"
    assert settings.database_url is None
    assert settings.redis_url is None


def test_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "p" * 40)
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("REDIS_URL", "redis://example:6379/0")
    settings = Settings(_env_file=None)
    assert settings.app_env == "production"
    assert settings.log_level == "WARNING"
    assert settings.redis_url == "redis://example:6379/0"


def test_empty_urls_become_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "  ")
    monkeypatch.setenv("REDIS_URL", "")
    settings = Settings(_env_file=None)
    assert settings.database_url is None
    assert settings.redis_url is None


def test_invalid_environment_fails_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging-ish")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_unknown_variables_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "not-used-yet")
    assert not hasattr(Settings(_env_file=None), "openai_api_key")
