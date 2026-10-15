"""Our internal, provider-neutral format for talking to LLMs.

Providers translate between these types and their own SDK types, so nothing
outside the providers depends on a vendor's format.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

# The system prompt is passed separately to Provider.complete, so it isn't a role here.
# "tool" messages carry the result of one tool call back to the model.
Role = Literal["user", "assistant", "tool"]

# Providers name these differently (e.g. OpenAI "tool_calls"/"length", Anthropic
# "tool_use"/"max_tokens"); each provider maps its values onto this shared set.
StopReason = Literal["end_turn", "tool_use", "max_tokens", "other"]


class ProviderTokenLimitError(Exception):
    """One request is bigger than the provider accepts at all (HTTP 413), e.g. Groq's
    free-tier limit of 8,000 tokens per request. Waiting doesn't help: the conversation
    has outgrown what this provider can serve."""


@dataclass(frozen=True)
class ToolCall:
    """A request from the model to run one of our tools."""

    id: str  # links the tool's result back to this call
    name: str
    arguments: dict[str, Any]  # already parsed from JSON


@dataclass(frozen=True)
class Message:
    """One turn in the conversation.

    - user: content is the text.
    - assistant: content is the text (may be empty); tool_calls lists any tools it asked for.
    - tool: content is one tool's result; tool_call_id names the ToolCall it answers.
    Prefer the constructors Message.user / .assistant / .tool_result.
    """

    role: Role
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    is_error: bool = False  # tool results only: the tool call failed (Anthropic sends this flag)
    # Assistant messages only: the provider's own content blocks for this reply, replayed
    # unchanged when the same provider continues the conversation (Anthropic requires its
    # thinking blocks to come back exactly as sent). Other providers ignore it.
    raw: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        # Catch malformed history here rather than as a confusing API error later.
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("a tool message needs the tool_call_id of the call it answers")
        if self.role != "tool" and (self.tool_call_id or self.is_error):
            raise ValueError("tool_call_id and is_error only belong on tool messages")
        if self.role != "assistant" and self.tool_calls:
            raise ValueError("only assistant messages can contain tool calls")
        if self.role != "assistant" and self.raw:
            raise ValueError("only assistant messages carry raw provider content")

    @classmethod
    def user(cls, content: str) -> Message:
        return cls("user", content)

    @classmethod
    def assistant(cls, content: str, tool_calls: Sequence[ToolCall] = (), raw: Sequence[Any] = ()) -> Message:
        return cls("assistant", content, tool_calls=tuple(tool_calls), raw=tuple(raw))

    @classmethod
    def tool_result(cls, tool_call_id: str, content: str, is_error: bool = False) -> Message:
        return cls("tool", content, tool_call_id=tool_call_id, is_error=is_error)


@dataclass(frozen=True)
class ToolDefinition:
    """A tool we offer the model."""

    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema describing the arguments


@dataclass(frozen=True)
class Usage:
    """Token counts for one model call, used for cost tracking."""

    input_tokens: int  # every input token, including the cached ones below
    output_tokens: int
    cache_write_tokens: int = 0  # input tokens written to the prompt cache (priced higher)
    cache_read_tokens: int = 0  # input tokens read from the prompt cache (priced much lower)


@dataclass(frozen=True)
class ModelResponse:
    """What a provider returns from one call."""

    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=lambda: Usage(input_tokens=0, output_tokens=0))
    stop_reason: StopReason = "end_turn"
    rate_limit_retries: int = 0  # times the provider waited and retried after HTTP 429
    raw: tuple[Any, ...] = ()  # the provider's own content blocks, see Message.raw

    def as_message(self) -> Message:
        """This reply as an assistant message, to append to the conversation history."""
        return Message.assistant(self.text, self.tool_calls, self.raw)
