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

    def __post_init__(self) -> None:
        # Catch malformed history here rather than as a confusing API error later.
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("a tool message needs the tool_call_id of the call it answers")
        if self.role != "tool" and (self.tool_call_id or self.is_error):
            raise ValueError("tool_call_id and is_error only belong on tool messages")
        if self.role != "assistant" and self.tool_calls:
            raise ValueError("only assistant messages can contain tool calls")

    @classmethod
    def user(cls, content: str) -> Message:
        return cls("user", content)

    @classmethod
    def assistant(cls, content: str, tool_calls: Sequence[ToolCall] = ()) -> Message:
        return cls("assistant", content, tool_calls=tuple(tool_calls))

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

    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class ModelResponse:
    """What a provider returns from one call."""

    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=lambda: Usage(input_tokens=0, output_tokens=0))
    stop_reason: StopReason = "end_turn"

    def as_message(self) -> Message:
        """This reply as an assistant message, to append to the conversation history."""
        return Message.assistant(self.text, self.tool_calls)
