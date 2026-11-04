"""AI provider abstraction and CV analysis."""

from app.ai.base import LLMProvider
from app.ai.openai_compat import OpenAICompatibleProvider, UnavailableProvider
from app.core.config import Settings


def create_llm_provider(settings: Settings) -> LLMProvider:
    """Build the configured provider; fall back to ``UnavailableProvider`` (never raises).

    AI is optional: with no provider configured the rest of the application works.
    """
    if settings.ai_provider == "openai":
        if settings.openai_api_key is None or not settings.openai_model:
            return UnavailableProvider(
                "OpenAI is selected but OPENAI_API_KEY/OPENAI_MODEL are not set"
            )
        return OpenAICompatibleProvider(
            api_key=settings.openai_api_key.get_secret_value(),
            model=settings.openai_model,
            base_url=settings.openai_base_url,
            timeout_seconds=settings.ai_timeout_seconds,
        )
    return UnavailableProvider()
