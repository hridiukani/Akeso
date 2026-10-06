"""Pacing: keep a minimum gap between model calls, so free-tier rate limits are rarely hit.

Retrying after HTTP 429 (in the provider) still handles the limits we do hit; pacing
just avoids hitting them constantly, which wastes time in backoff.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence

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
