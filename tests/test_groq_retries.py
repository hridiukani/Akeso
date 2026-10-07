"""Tests for the Groq provider's retries: rate limits and rejected tool calls. No network."""

from types import SimpleNamespace as NS

import openai
import pytest

try:  # the SDK ships its own copy of httpx in some versions
    import httpx2 as httpx
except ImportError:
    import httpx

from akeso.llm.groq_provider import GroqProvider, RateLimitExhausted, ToolCallRejected
from akeso.llm.types import Message

OK = NS(
    choices=[NS(message=NS(content="done", tool_calls=None), finish_reason="stop")],
    usage=NS(prompt_tokens=5, completion_tokens=1),
)


def response(status: int) -> "httpx.Response":
    return httpx.Response(status, request=httpx.Request("POST", "https://api.groq.com"))


def rate_limited() -> openai.RateLimitError:
    return openai.RateLimitError("rate limited", response=response(429), body=None)


def tool_use_failed() -> openai.BadRequestError:
    body = {"error": {"message": "Tool call validation failed", "type": "invalid_request_error", "code": "tool_use_failed"}}
    return openai.BadRequestError("Tool call validation failed", response=response(400), body=body)


def provider_with(outcomes: list, **kwargs) -> tuple[GroqProvider, list[float]]:
    """A provider whose API calls produce the given outcomes in order (exceptions are raised)."""
    sleeps: list[float] = []
    provider = GroqProvider(api_key="fake", model="openai/gpt-oss-120b", sleep=sleeps.append, **kwargs)
    remaining = list(outcomes)

    def send(request):
        outcome = remaining.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome, {}

    provider._send = send
    return provider, sleeps


def ask(provider: GroqProvider):
    return provider.complete("system", [Message.user("hi")])


def test_rate_limit_retries_with_backoff() -> None:
    provider, sleeps = provider_with([rate_limited(), rate_limited(), OK])

    assert ask(provider).text == "done"
    assert len(sleeps) == 2 and sleeps[1] > sleeps[0] - 1  # waits, growing (with jitter)


def test_rate_limit_gives_up_with_a_clear_error() -> None:
    provider, _ = provider_with([rate_limited()] * 3, max_attempts=3)

    with pytest.raises(RateLimitExhausted, match="persisted after 3 attempts"):
        ask(provider)


def test_rejected_tool_call_is_asked_again() -> None:
    provider, sleeps = provider_with([tool_use_failed(), OK])

    assert ask(provider).text == "done"
    assert sleeps == []  # not a rate limit, so no waiting


def test_rejected_tool_calls_give_up_after_the_limit() -> None:
    provider, _ = provider_with([tool_use_failed()] * 3, max_tool_call_attempts=3)

    with pytest.raises(ToolCallRejected, match="rejected the model's tool call as invalid 3 times"):
        ask(provider)


def test_other_bad_requests_are_not_retried() -> None:
    other = openai.BadRequestError("bad model name", response=response(400), body={"error": {"code": "model_not_found"}})
    provider, _ = provider_with([other, OK])

    with pytest.raises(openai.BadRequestError, match="bad model name"):
        ask(provider)


def test_rate_limits_and_rejections_are_counted_separately() -> None:
    provider, _ = provider_with([rate_limited(), tool_use_failed(), rate_limited(), tool_use_failed(), OK],
                                max_attempts=3, max_tool_call_attempts=3)

    assert ask(provider).text == "done"


def test_response_reports_how_many_rate_limit_retries_it_took() -> None:
    provider, _ = provider_with([rate_limited(), rate_limited(), OK])

    assert ask(provider).rate_limit_retries == 2


def test_no_retries_reported_when_not_rate_limited() -> None:
    provider, _ = provider_with([tool_use_failed(), OK])  # a rejected tool call isn't a rate limit

    assert ask(provider).rate_limit_retries == 0


def test_waits_for_the_token_quota_before_a_call_that_would_exceed_it() -> None:
    low_quota = {"x-ratelimit-limit-tokens": "8000", "x-ratelimit-remaining-tokens": "100", "x-ratelimit-reset-tokens": "30s"}
    sleeps: list[float] = []
    provider = GroqProvider(api_key="fake", model="openai/gpt-oss-120b", sleep=sleeps.append, clock=lambda: 0.0)
    replies = [(OK, low_quota), (OK, {})]
    provider._send = lambda request: replies.pop(0)

    ask(provider)  # no headers seen yet: no wait
    assert sleeps == []
    ask(provider)  # ~1000 tokens needed, 100 left: wait for some to refill, without a 429
    assert len(sleeps) == 1 and 0 < sleeps[0] <= 30


def test_rate_limit_headers_on_a_429_are_remembered() -> None:
    error = openai.RateLimitError(
        "rate limited", body=None,
        response=httpx.Response(429, headers={"x-ratelimit-remaining-tokens": "0", "x-ratelimit-reset-tokens": "12s"},
                                request=httpx.Request("POST", "https://api.groq.com")),
    )
    provider, _ = provider_with([error, OK])
    ask(provider)

    assert provider.budget._latest is not None and provider.budget._latest.reset_tokens == 12.0


def test_retries_are_quiet(caplog: pytest.LogCaptureFixture) -> None:
    provider, _ = provider_with([rate_limited(), tool_use_failed(), OK])

    with caplog.at_level("INFO"):
        ask(provider)

    assert caplog.records == []  # counted per task instead of printing a line per retry


def test_send_reads_headers_through_the_real_sdk() -> None:
    body = {"id": "x", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body, headers={"x-ratelimit-remaining-tokens": "42"}))
    provider = GroqProvider(api_key="fake", model="m")
    provider._client = openai.OpenAI(api_key="fake", base_url="https://example.invalid/v1", max_retries=0,
                                     http_client=httpx.Client(transport=transport))

    reply = ask(provider)

    assert reply.text == "hi"
    assert provider.budget._latest.remaining_tokens == 42
