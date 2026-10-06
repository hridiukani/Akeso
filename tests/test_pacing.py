"""Tests for pacing model calls (with a fake clock, so nothing actually waits)."""

import pytest

from fakes import ScriptedProvider, text_reply
from akeso.config import Settings
from akeso.llm.pacing import PacedProvider
from akeso.llm.provider import get_provider
from akeso.llm.types import Message


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 3))
        self.now += seconds


def paced(min_interval: float, clock: FakeClock) -> tuple[PacedProvider, ScriptedProvider]:
    inner = ScriptedProvider([text_reply(str(i)) for i in range(10)])
    return PacedProvider(inner, min_interval, clock=clock, sleep=clock.sleep), inner


def ask(provider) -> str:
    return provider.complete("sys", [Message.user("hi")]).text


def test_first_call_never_waits() -> None:
    clock = FakeClock()
    provider, _ = paced(2.0, clock)

    ask(provider)

    assert clock.sleeps == []


def test_back_to_back_calls_wait_for_the_gap() -> None:
    clock = FakeClock()
    provider, inner = paced(2.0, clock)

    ask(provider)
    clock.now += 0.5  # the model answered in half a second
    ask(provider)
    ask(provider)

    assert clock.sleeps == [1.5, 2.0]
    assert len(inner.calls) == 3


def test_no_wait_when_enough_time_has_passed() -> None:
    clock = FakeClock()
    provider, _ = paced(2.0, clock)

    ask(provider)
    clock.now += 5  # e.g. tools ran for a while
    ask(provider)

    assert clock.sleeps == []


def test_passes_everything_through() -> None:
    clock = FakeClock()
    provider, inner = paced(1.0, clock)

    assert ask(provider) == "0"
    assert inner.calls[0][0].content == "hi"


def test_get_provider_paces_groq_by_default() -> None:
    settings = Settings(provider="groq", groq_model="openai/gpt-oss-120b", anthropic_model=None, groq_api_key="fake")

    provider = get_provider(settings)

    assert isinstance(provider, PacedProvider) and provider.min_interval == 2.0


def test_get_provider_skips_pacing_when_the_gap_is_zero() -> None:
    settings = Settings(
        provider="groq", groq_model="openai/gpt-oss-120b", anthropic_model=None, groq_api_key="fake",
        groq_min_call_interval=0.0,
    )

    assert not isinstance(get_provider(settings), PacedProvider)


@pytest.mark.parametrize(("provider", "expected"), [("groq", 2.0), ("anthropic", 0.0)])
def test_min_call_interval_follows_the_active_provider(provider: str, expected: float) -> None:
    settings = Settings(provider=provider, groq_model="m", anthropic_model="m")

    assert settings.min_call_interval == expected
