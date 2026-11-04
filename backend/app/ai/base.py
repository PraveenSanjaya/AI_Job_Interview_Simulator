"""Provider-independent LLM interface."""

from typing import Protocol


class LLMProvider(Protocol):
    """Anything that can turn a system+user prompt into a JSON string.

    Implementations must raise the errors in ``app.ai.errors`` and must never log
    prompts or responses. ``is_external`` is True when the prompt leaves the
    machine/network the application runs in; sending resume text to such a provider
    requires the user's explicit consent.
    """

    name: str
    model: str
    is_external: bool

    @property
    def available(self) -> bool: ...

    async def complete_json(self, *, system: str, user: str) -> str:
        """Return the model's reply, which is expected to be a JSON object."""
        ...
