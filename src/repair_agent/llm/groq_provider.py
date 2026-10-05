"""Groq provider: the OpenAI Python SDK pointed at Groq's OpenAI-compatible API."""

from __future__ import annotations

import json
import logging
import random
import time
from collections.abc import Callable, Sequence
from typing import Any

import openai

from repair_agent.llm.types import (
    Message,
    ModelResponse,
    StopReason,
    ToolCall,
    ToolDefinition,
    Usage,
)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# OpenAI-format finish_reason -> our StopReason.
_STOP_REASONS: dict[str, StopReason] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
}

logger = logging.getLogger(__name__)


class RateLimitExhausted(Exception):
    """Raised when the provider keeps returning HTTP 429 after all retry attempts."""


class GroqProvider:
    """Implements the Provider protocol for Groq."""

    def __init__(
        self,
        api_key: str,
        model: str,
        max_attempts: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self._sleep = sleep  # injectable so tests don't actually wait
        # max_retries=0: the SDK would otherwise retry 429s itself; we own the retry policy.
        self._client = openai.OpenAI(api_key=api_key, base_url=GROQ_BASE_URL, max_retries=0)

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] | None = None,
    ) -> ModelResponse:
        """Send one chat request, retrying on rate limits, and return it in our format."""
        request: dict[str, Any] = {
            "model": self.model,
            "messages": _to_openai_messages(system, messages),
        }
        if tools:
            request["tools"] = [_to_openai_tool(t) for t in tools]

        response = self._create_with_retry(request)
        return _from_openai_response(response)

    def _create_with_retry(self, request: dict[str, Any]) -> Any:
        """Call the API, waiting with exponential backoff on HTTP 429."""
        for attempt in range(1, self.max_attempts + 1):
            try:
                return self._client.chat.completions.create(**request)
            except openai.RateLimitError as error:
                if attempt == self.max_attempts:
                    raise RateLimitExhausted(
                        f"Groq rate limit (HTTP 429) persisted after {self.max_attempts} attempts. "
                        "Wait a minute and try again, or reduce how often requests are sent."
                    ) from error
                delay = self._retry_delay(attempt, error)
                logger.warning(
                    "Groq rate limited (HTTP 429); retrying in %.1fs (attempt %d/%d)",
                    delay, attempt, self.max_attempts,
                )
                self._sleep(delay)
        raise AssertionError("unreachable")  # the loop always returns or raises

    def _retry_delay(self, attempt: int, error: openai.RateLimitError) -> float:
        """Use the server's retry-after if given, else exponential backoff with jitter."""
        retry_after = error.response.headers.get("retry-after")
        if retry_after:
            try:
                return min(float(retry_after), self.max_delay)
            except ValueError:
                pass  # some servers send an HTTP date; fall back to backoff
        backoff = self.base_delay * 2 ** (attempt - 1)  # 1s, 2s, 4s, ...
        # Jitter spreads out retries so parallel runs don't all hit the limit at once.
        return min(backoff, self.max_delay) + random.uniform(0, self.base_delay)


def _to_openai_messages(system: str, messages: Sequence[Message]) -> list[dict[str, Any]]:
    """OpenAI format puts the system prompt in the message list as the first message."""
    converted: list[dict[str, Any]] = [{"role": "system", "content": system}]
    converted.extend(_to_openai_message(m) for m in messages)
    return converted


def _to_openai_message(message: Message) -> dict[str, Any]:
    if message.role == "tool":
        # OpenAI format has no is_error flag; our error results already start with "Error:".
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}
    if message.role == "assistant" and message.tool_calls:
        return {
            "role": "assistant",
            "content": message.content or None,  # OpenAI format uses null when there's no text
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    # Arguments go back as a JSON string, the way the API sent them.
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for call in message.tool_calls
            ],
        }
    return {"role": message.role, "content": message.content}


def _to_openai_tool(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        },
    }


def _from_openai_response(response: Any) -> ModelResponse:
    choice = response.choices[0]
    message = choice.message

    tool_calls = [
        ToolCall(
            id=call.id,
            name=call.function.name,
            arguments=_parse_arguments(call.function.name, call.function.arguments),
        )
        for call in (message.tool_calls or [])
    ]

    usage = response.usage
    return ModelResponse(
        text=message.content or "",
        tool_calls=tool_calls,
        usage=Usage(
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        ),
        stop_reason=_STOP_REASONS.get(choice.finish_reason, "other"),
    )


def _parse_arguments(tool_name: str, raw: str | None) -> dict[str, Any]:
    """OpenAI format sends tool arguments as a JSON string; we want a dict."""
    if not raw:
        return {}  # tools with no parameters may come back with an empty string
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"Model sent invalid JSON arguments for tool {tool_name!r}.") from error
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ValueError(f"Model sent non-object arguments for tool {tool_name!r}.")
    return parsed
