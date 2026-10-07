"""Pacing: avoid free-tier rate limits instead of hitting them and backing off.

Two layers: a minimum gap between calls (for request-per-minute limits, which Groq doesn't
report in headers), and a quota budget read from the server's rate-limit headers (for
token-per-minute limits). Retrying after HTTP 429 in the provider handles anything left.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from akeso.llm.provider import Provider
from akeso.llm.types import Message, ModelResponse, ToolDefinition


class PacedProvider:
    """Wraps any Provider so consecutive calls start at least min_interval seconds apart."""

    def __init__(
        self,
        inner: Provider,
        min_interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.inner = inner
        self.min_interval = min_interval
        self._clock = clock  # injectable so tests don't actually wait
        self._sleep = sleep
        self._last_start: float | None = None

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] | None = None,
    ) -> ModelResponse:
        if self._last_start is not None:
            wait = self.min_interval - (self._clock() - self._last_start)
            if wait > 0:
                self._sleep(wait)
        self._last_start = self._clock()
        return self.inner.complete(system, messages, tools)


@dataclass(frozen=True)
class RateLimitHeaders:
    """The quota a server reported with its last reply (None for anything it didn't send).

    Groq sends x-ratelimit-{limit,remaining,reset}-{requests,tokens}; resets are
    durations such as "7.66s" or "2m59.56s".
    """

    limit_requests: int | None = None
    remaining_requests: int | None = None
    reset_requests: float | None = None  # seconds until the request quota is full again
    limit_tokens: int | None = None
    remaining_tokens: int | None = None
    reset_tokens: float | None = None  # seconds until the token quota is full again

    @classmethod
    def parse(cls, headers: Mapping[str, str]) -> RateLimitHeaders | None:
        """Read the rate-limit headers, or None if there are none (other providers, tests)."""

        def number(name: str) -> int | None:
            try:
                return int(float(headers[name]))
            except (KeyError, ValueError):
                return None

        def duration(name: str) -> float | None:
            value = headers.get(name)
            return parse_duration(value) if value else None

        parsed = cls(
            limit_requests=number("x-ratelimit-limit-requests"),
            remaining_requests=number("x-ratelimit-remaining-requests"),
            reset_requests=duration("x-ratelimit-reset-requests"),
            limit_tokens=number("x-ratelimit-limit-tokens"),
            remaining_tokens=number("x-ratelimit-remaining-tokens"),
            reset_tokens=duration("x-ratelimit-reset-tokens"),
        )
        return None if parsed == cls() else parsed


_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
_UNIT_SECONDS = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}


def parse_duration(text: str) -> float | None:
    """'2m59.56s' -> 179.56 seconds; a bare number is seconds; None if unreadable."""
    text = text.strip()
    try:
        return float(text)
    except ValueError:
        pass
    parts = _DURATION_PART.findall(text)
    if not parts or "".join(n + u for n, u in parts) != text:
        return None
    return sum(float(n) * _UNIT_SECONDS[u] for n, u in parts)


class RateLimitBudget:
    """Remembers the latest quota a server reported and says how long to wait before a call
    that would exceed it, so we wait a little up front instead of hitting HTTP 429 and
    backing off. If the server never sends headers, it never asks for a wait.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic, max_wait: float = 60.0) -> None:
        self._clock = clock
        self.max_wait = max_wait
        self._latest: RateLimitHeaders | None = None
        self._seen_at = 0.0

    def update(self, headers: RateLimitHeaders | None) -> None:
        if headers is not None:
            self._latest = headers
            self._seen_at = self._clock()

    def wait_before(self, estimated_tokens: int) -> float:
        """Seconds to wait before sending a request of about estimated_tokens tokens."""
        h = self._latest
        if h is None:
            return 0.0
        elapsed = self._clock() - self._seen_at
        wait = 0.0
        if h.remaining_requests is not None and h.remaining_requests < 1 and h.reset_requests:
            wait = h.reset_requests - elapsed
        if h.remaining_tokens is not None and h.reset_tokens and estimated_tokens > h.remaining_tokens:
            wait = max(wait, self._token_wait(h, estimated_tokens, elapsed))
        return min(max(wait, 0.0), self.max_wait)

    @staticmethod
    def _token_wait(h: RateLimitHeaders, needed: int, elapsed: float) -> float:
        """Tokens refill steadily until the reset time, so wait only until enough are back."""
        assert h.remaining_tokens is not None and h.reset_tokens
        full_reset = h.reset_tokens - elapsed
        if h.limit_tokens is None or h.limit_tokens <= h.remaining_tokens or needed > h.limit_tokens:
            return full_reset  # can't estimate the refill rate (or need the whole quota)
        rate = (h.limit_tokens - h.remaining_tokens) / h.reset_tokens  # tokens per second
        available = h.remaining_tokens + rate * elapsed
        return min((needed - available) / rate, full_reset)


def estimate_tokens(payload: object, output_reserve: int = 1024) -> int:
    """A rough token count for a request: about 4 characters per token for the input, plus
    room for the reply (rate limits count both). Erring high only costs a short wait."""
    return len(json.dumps(payload, default=str)) // 4 + output_reserve
