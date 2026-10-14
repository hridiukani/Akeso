"""The interface every LLM provider implements."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from akeso.config import Settings
from akeso.llm.types import Message, ModelResponse, ToolDefinition


class Provider(Protocol):
    """Anything with this method can be used as an LLM provider.

    Implementations: GroqProvider (OpenAI-compatible) and AnthropicProvider. The agent
    loop depends only on this protocol, never on a provider SDK.
    """

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] | None = None,
    ) -> ModelResponse:
        """Send one request to the model and return its reply in our format."""
        ...


def get_provider(settings: Settings) -> Provider:
    """Return the provider chosen by settings.provider, paced if it has a minimum call gap."""
    if settings.provider == "groq":
        # Imported here so the rest of the code only needs this module, not the SDK-specific one.
        from akeso.llm.groq_provider import GroqProvider

        # load_settings already guarantees these are set for the active provider.
        assert settings.groq_api_key and settings.groq_model
        provider: Provider = GroqProvider(api_key=settings.groq_api_key, model=settings.groq_model)
    elif settings.provider == "anthropic":
        from akeso.llm.anthropic_provider import AnthropicProvider

        assert settings.anthropic_api_key and settings.anthropic_model
        provider = AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.anthropic_model)
    else:
        raise ValueError(f"Unknown provider {settings.provider!r}.")

    if settings.min_call_interval > 0:
        from akeso.llm.pacing import PacedProvider

        provider = PacedProvider(provider, settings.min_call_interval)
    return provider
