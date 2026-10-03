"""The interface every LLM provider implements."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from repair_agent.llm.types import Message, ModelResponse, ToolDefinition


class Provider(Protocol):
    """Anything with this method can be used as an LLM provider.

    Implementations (OpenAI-compatible, Anthropic) come later. The agent loop
    depends only on this protocol, never on a provider SDK.
    """

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] | None = None,
    ) -> ModelResponse:
        """Send one request to the model and return its reply in our format."""
        ...
