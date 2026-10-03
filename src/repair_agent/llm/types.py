"""Our internal, provider-neutral format for talking to LLMs.

Providers translate between these types and their own SDK types, so nothing
outside the providers depends on a vendor's format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# The system prompt is passed separately to Provider.complete, so it isn't a role here.
Role = Literal["user", "assistant"]

# Providers name these differently (e.g. OpenAI "tool_calls"/"length", Anthropic
# "tool_use"/"max_tokens"); each provider maps its values onto this shared set.
StopReason = Literal["end_turn", "tool_use", "max_tokens", "other"]


@dataclass(frozen=True)
class Message:
    """One turn in the conversation."""

    role: Role
    content: str


@dataclass(frozen=True)
class ToolCall:
    """A request from the model to run one of our tools."""

    id: str  # links the tool's result back to this call
    name: str
    arguments: dict[str, Any]  # already parsed from JSON


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
