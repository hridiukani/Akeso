"""Offline tests for the Anthropic provider: request building, response conversion, caching, retries."""

import anthropic
import pytest

try:  # anthropic 1.x is built on httpx2
    import httpx2 as httpx
except ImportError:
    import httpx

from akeso.config import PRICES, Settings
from akeso.llm.anthropic_provider import (
    AnthropicProvider,
    AnthropicRetriesExhausted,
    build_request,
    from_anthropic_response,
    to_anthropic_messages,
)
from akeso.llm.cost import cost_usd
from akeso.llm.provider import get_provider
from akeso.llm.types import Message, ToolCall, ToolDefinition, Usage

TOOL = ToolDefinition("read_file", "Read a file.", {"type": "object", "properties": {"path": {"type": "string"}}})


def api_message(content: list[dict], stop_reason: str = "tool_use", **usage) -> anthropic.types.Message:
    """A real SDK Message object, as messages.create would return it."""
    return anthropic.types.Message.model_validate({
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5",
        "content": content, "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 100, "output_tokens": 20, "cache_creation_input_tokens": 0,
                  "cache_read_input_tokens": 0, **usage},
    })


THINKING = {"type": "thinking", "thinking": "", "signature": "sig-abc"}
TOOL_USE = {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "src/a.py"}}


def test_system_prompt_carries_the_cache_breakpoint_and_tools_come_first() -> None:
    request = build_request("claude-sonnet-5", 16000, "You fix bugs.", [Message.user("hi")], [TOOL])

    assert request["system"] == [{"type": "text", "text": "You fix bugs.", "cache_control": {"type": "ephemeral"}}]
    assert request["tools"] == [{"name": "read_file", "description": "Read a file.", "input_schema": TOOL.input_schema}]
    assert request["messages"] == [{"role": "user", "content": "hi"}]
    assert request["max_tokens"] == 16000 and "thinking" not in request  # the model's default


def test_no_tools_key_without_tools() -> None:
    assert "tools" not in build_request("m", 10, "s", [Message.user("hi")], None)


def test_tool_results_of_one_turn_go_back_in_one_user_message() -> None:
    calls = [ToolCall("toolu_1", "read_file", {"path": "a"}), ToolCall("toolu_2", "read_file", {"path": "b"})]
    messages = [
        Message.user("fix it"),
        Message.assistant("Reading.", calls),
        Message.tool_result("toolu_1", "contents of a"),
        Message.tool_result("toolu_2", "Error: no such file", is_error=True),
    ]

    converted = to_anthropic_messages(messages)

    assert [m["role"] for m in converted] == ["user", "assistant", "user"]
    assert converted[1]["content"] == [
        {"type": "text", "text": "Reading."},
        {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "a"}},
        {"type": "tool_use", "id": "toolu_2", "name": "read_file", "input": {"path": "b"}},
    ]
    assert converted[2]["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "contents of a"},
        {"type": "tool_result", "tool_use_id": "toolu_2", "content": "Error: no such file", "is_error": True},
    ]


def test_response_conversion_keeps_raw_blocks_and_counts_cached_input() -> None:
    response = api_message([THINKING, {"type": "text", "text": "Let me look."}, TOOL_USE],
                           input_tokens=50, cache_creation_input_tokens=1500, cache_read_input_tokens=0)

    reply = from_anthropic_response(response, rate_limit_retries=2)

    assert reply.text == "Let me look." and reply.stop_reason == "tool_use"
    assert reply.tool_calls == [ToolCall("toolu_1", "read_file", {"path": "src/a.py"})]
    assert reply.usage == Usage(input_tokens=1550, output_tokens=20, cache_write_tokens=1500, cache_read_tokens=0)
    assert reply.rate_limit_retries == 2
    assert reply.raw[0] == THINKING and reply.raw[2] == TOOL_USE


def test_thinking_blocks_are_replayed_exactly_on_the_next_request() -> None:
    reply = from_anthropic_response(api_message([THINKING, TOOL_USE]))
    history = [Message.user("fix it"), reply.as_message(), Message.tool_result("toolu_1", "x = 1")]

    converted = to_anthropic_messages(history)

    assert converted[1] == {"role": "assistant", "content": [THINKING, TOOL_USE]}


@pytest.mark.parametrize(("stop", "ours"), [("end_turn", "end_turn"), ("tool_use", "tool_use"),
                                            ("max_tokens", "max_tokens"), ("refusal", "other")])
def test_stop_reasons(stop: str, ours: str) -> None:
    assert from_anthropic_response(api_message([{"type": "text", "text": "done"}], stop_reason=stop)).stop_reason == ours


def provider_with(outcomes: list) -> tuple[AnthropicProvider, list[float], list[dict]]:
    sleeps: list[float] = []
    requests: list[dict] = []
    provider = AnthropicProvider(api_key="fake", model="claude-sonnet-5", sleep=sleeps.append)
    remaining = list(outcomes)

    def create(**request):
        requests.append(request)
        outcome = remaining.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    provider._client.messages.create = create
    return provider, sleeps, requests


def status_error(code: int, retry_after: str | None = None) -> anthropic.APIStatusError:
    headers = {"retry-after": retry_after} if retry_after else {}
    response = httpx.Response(code, headers=headers, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    return anthropic.APIStatusError(f"HTTP {code}", response=response, body=None)


def test_rate_limits_and_overload_are_retried_and_counted() -> None:
    ok = api_message([{"type": "text", "text": "done"}], stop_reason="end_turn")
    provider, sleeps, _ = provider_with([status_error(429, retry_after="7"), status_error(529), ok])

    reply = provider.complete("s", [Message.user("hi")])

    assert reply.text == "done" and reply.rate_limit_retries == 2
    assert sleeps[0] == 7.0 and len(sleeps) == 2


def test_retries_give_up_with_a_clear_error() -> None:
    provider, _, _ = provider_with([status_error(529)] * 6)

    with pytest.raises(AnthropicRetriesExhausted, match="HTTP 529 after 6 attempts"):
        provider.complete("s", [Message.user("hi")])


def test_bad_requests_are_not_retried() -> None:
    provider, sleeps, _ = provider_with([status_error(400)])

    with pytest.raises(anthropic.APIStatusError):
        provider.complete("s", [Message.user("hi")])
    assert sleeps == []


def test_cost_prices_cache_writes_and_reads() -> None:
    # Sonnet 5: $2 input, $2.50 cache write, $0.20 cache read, $10 output per MTok.
    usage = Usage(input_tokens=3_000_000, output_tokens=100_000, cache_write_tokens=1_000_000, cache_read_tokens=1_000_000)

    assert cost_usd("claude-sonnet-5", usage) == pytest.approx(1 * 2.0 + 1 * 2.5 + 1 * 0.2 + 0.1 * 10.0)


def test_cache_prices_default_to_the_usual_multiples() -> None:
    from akeso.config import ModelPrice

    price = ModelPrice(4.0, 20.0)
    assert (price.cache_write, price.cache_read) == (5.0, pytest.approx(0.4))
    assert PRICES["claude-sonnet-5-5"].cache_read == 0.10  # 0.05x on Sonnet 5.5


def test_get_provider_builds_the_anthropic_provider() -> None:
    settings = Settings(provider="anthropic", groq_model=None, anthropic_model="claude-sonnet-5", anthropic_api_key="fake")

    provider = get_provider(settings)

    assert isinstance(provider, AnthropicProvider) and provider.model == "claude-sonnet-5"


def test_raw_content_only_on_assistant_messages() -> None:
    with pytest.raises(ValueError, match="only assistant messages carry raw provider content"):
        Message("user", "hi", raw=({"type": "text"},))
