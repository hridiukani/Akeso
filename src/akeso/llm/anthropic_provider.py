"""Anthropic provider: the native Anthropic SDK, with prompt caching.

Not the MVP's measurement model (see CLAUDE.md's Measurement rule); built and tested
offline for later. Its settings are kept fixed and simple: the model's default thinking and effort, and one
cache breakpoint on the system prompt. Tools render before the system prompt, so that
breakpoint caches the tool definitions and the system prompt together; every step of a
run then reads them from the cache instead of paying for them again.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Sequence
from typing import Any

import anthropic

from akeso.llm.types import Message, ModelResponse, ProviderTokenLimitError, StopReason, ToolCall, ToolDefinition, Usage

# Anthropic stop_reason -> our StopReason ("refusal", "pause_turn", ... map to "other").
_STOP_REASONS: dict[str, StopReason] = {"end_turn": "end_turn", "tool_use": "tool_use", "max_tokens": "max_tokens"}
# Worth retrying: rate limited, server errors, and 529 overloaded.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504, 529}

logger = logging.getLogger(__name__)


class AnthropicRetriesExhausted(Exception):
    """Raised when the API keeps returning a retryable error after every attempt."""


class AnthropicProvider:
    """Implements the Provider protocol for the Anthropic Messages API."""

    def __init__(
        self,
        api_key: str,
        model: str,
        max_tokens: int = 16_000,
        max_attempts: int = 6,
        base_delay: float = 2.0,
        max_delay: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens  # output cap per call, thinking included
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self._sleep = sleep  # injectable so tests don't actually wait
        # max_retries=0: we own the retry policy, so retries can be counted per call.
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=0)

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] | None = None,
    ) -> ModelResponse:
        """Send one request, retrying on rate limits and overload, and return it in our format."""
        request = build_request(self.model, self.max_tokens, system, messages, tools)
        response, retries = self._create_with_retry(request)
        return from_anthropic_response(response, retries)

    def _create_with_retry(self, request: dict[str, Any]) -> tuple[Any, int]:
        retries = 0
        while True:
            try:
                return self._client.messages.create(**request), retries
            except anthropic.APIStatusError as error:
                if error.status_code == 413:
                    raise ProviderTokenLimitError(f"Anthropic refused the request as too large (HTTP 413): {error.message}") from error
                if error.status_code not in _RETRYABLE_STATUS:
                    raise  # a genuinely bad request: retrying won't help
                retries += 1
                if retries >= self.max_attempts:
                    raise AnthropicRetriesExhausted(
                        f"Anthropic API kept returning HTTP {error.status_code} after {self.max_attempts} attempts."
                    ) from error
                delay = self._retry_delay(retries, error)
                logger.debug("Anthropic HTTP %d; retrying in %.1fs (%d/%d)", error.status_code, delay, retries, self.max_attempts)
                self._sleep(delay)

    def _retry_delay(self, attempt: int, error: anthropic.APIStatusError) -> float:
        """The server's retry-after if given, else exponential backoff with jitter."""
        retry_after = error.response.headers.get("retry-after")
        if retry_after:
            try:
                return min(float(retry_after), self.max_delay)
            except ValueError:
                pass
        return min(self.base_delay * 2 ** (attempt - 1), self.max_delay) + random.uniform(0, 1)


def build_request(
    model: str, max_tokens: int, system: str, messages: Sequence[Message], tools: Sequence[ToolDefinition] | None
) -> dict[str, Any]:
    """The messages.create arguments for our conversation, with the cache breakpoint."""
    request: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": to_anthropic_messages(messages),
    }
    if tools:
        request["tools"] = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools
        ]
    return request


def to_anthropic_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """Our messages in Anthropic's format. Tool results go back as tool_result blocks in a
    user message, all results of one turn together; assistant replies are replayed from
    their raw blocks when we have them."""
    converted: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "tool":
            block = {"type": "tool_result", "tool_use_id": message.tool_call_id, "content": message.content}
            if message.is_error:
                block["is_error"] = True
            previous = converted[-1] if converted else None
            if previous and previous["role"] == "user" and isinstance(previous["content"], list) \
                    and previous["content"] and previous["content"][-1].get("type") == "tool_result":
                previous["content"].append(block)
            else:
                converted.append({"role": "user", "content": [block]})
        elif message.role == "assistant":
            converted.append({"role": "assistant", "content": list(message.raw) or _assistant_blocks(message)})
        else:
            converted.append({"role": "user", "content": message.content})
    return converted


def _assistant_blocks(message: Message) -> list[dict[str, Any]]:
    """An assistant turn rebuilt from text and tool calls (for history from elsewhere)."""
    blocks: list[dict[str, Any]] = [{"type": "text", "text": message.content}] if message.content else []
    blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments} for c in message.tool_calls]
    return blocks


def from_anthropic_response(response: Any, rate_limit_retries: int = 0) -> ModelResponse:
    """An Anthropic Message in our format, keeping its raw blocks for replay."""
    text = "".join(block.text for block in response.content if block.type == "text")
    tool_calls = [
        ToolCall(id=block.id, name=block.name, arguments=dict(block.input or {}))
        for block in response.content if block.type == "tool_use"
    ]
    usage = response.usage
    cache_write = usage.cache_creation_input_tokens or 0
    cache_read = usage.cache_read_input_tokens or 0
    return ModelResponse(
        text=text,
        tool_calls=tool_calls,
        # Anthropic's input_tokens counts only uncached input; ours counts all of it.
        usage=Usage(
            input_tokens=usage.input_tokens + cache_write + cache_read,
            output_tokens=usage.output_tokens,
            cache_write_tokens=cache_write,
            cache_read_tokens=cache_read,
        ),
        stop_reason=_STOP_REASONS.get(response.stop_reason or "", "other"),
        rate_limit_retries=rate_limit_retries,
        raw=tuple(block.to_dict(exclude_none=True) for block in response.content),  # nulls the API never sent
    )
