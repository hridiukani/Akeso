"""Tests for token-aware pacing from rate-limit headers (fake headers and a fake clock)."""

import pytest

from akeso.llm.pacing import RateLimitBudget, RateLimitHeaders, estimate_tokens, parse_duration

GROQ_HEADERS = {
    "x-ratelimit-limit-requests": "1000",
    "x-ratelimit-remaining-requests": "998",
    "x-ratelimit-reset-requests": "2m52.8s",
    "x-ratelimit-limit-tokens": "8000",
    "x-ratelimit-remaining-tokens": "2000",
    "x-ratelimit-reset-tokens": "45s",
}


class FakeClock:
    def __init__(self) -> None:
        self.now = 50.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize(("text", "seconds"), [
    ("7.66s", 7.66), ("2m59.56s", 179.56), ("1h2m3s", 3723.0), ("120ms", 0.12), ("3", 3.0), ("0.5", 0.5),
])
def test_parse_duration(text: str, seconds: float) -> None:
    assert parse_duration(text) == pytest.approx(seconds)


@pytest.mark.parametrize("text", ["soon", "", "5x", "Wed, 21 Oct 2026 07:28:00 GMT"])
def test_unreadable_durations_are_none(text: str) -> None:
    assert parse_duration(text) is None


def test_parse_groq_headers() -> None:
    h = RateLimitHeaders.parse(GROQ_HEADERS)

    assert h == RateLimitHeaders(1000, 998, pytest.approx(172.8), 8000, 2000, 45.0)


def test_no_rate_limit_headers_is_none() -> None:
    assert RateLimitHeaders.parse({"content-type": "application/json"}) is None


def budget_with(headers: dict[str, str], clock: FakeClock, **kwargs) -> RateLimitBudget:
    budget = RateLimitBudget(clock=clock, **kwargs)
    budget.update(RateLimitHeaders.parse(headers))
    return budget


def test_no_headers_seen_means_no_wait() -> None:
    assert RateLimitBudget(clock=FakeClock()).wait_before(1_000_000) == 0.0


def test_no_wait_when_the_request_fits() -> None:
    assert budget_with(GROQ_HEADERS, FakeClock()).wait_before(1500) == 0.0


def test_waits_only_until_enough_tokens_have_refilled() -> None:
    # 6000 tokens refill over 45s (~133/s). Needing 3000 with 2000 left: wait 1000/133 = 7.5s.
    assert budget_with(GROQ_HEADERS, FakeClock()).wait_before(3000) == pytest.approx(7.5)


def test_time_already_passed_counts_towards_the_refill() -> None:
    clock = FakeClock()
    budget = budget_with(GROQ_HEADERS, clock)
    clock.now += 6.0  # e.g. tools ran for six seconds since the last reply

    assert budget.wait_before(3000) == pytest.approx(1.5)
    clock.now += 2.0
    assert budget.wait_before(3000) == 0.0


def test_request_bigger_than_the_whole_quota_waits_for_the_full_reset() -> None:
    assert budget_with(GROQ_HEADERS, FakeClock()).wait_before(9000) == pytest.approx(45.0)


def test_no_limit_header_waits_for_the_full_reset() -> None:
    headers = {k: v for k, v in GROQ_HEADERS.items() if k != "x-ratelimit-limit-tokens"}

    assert budget_with(headers, FakeClock()).wait_before(3000) == pytest.approx(45.0)


def test_out_of_requests_waits_for_the_request_reset() -> None:
    headers = {**GROQ_HEADERS, "x-ratelimit-remaining-requests": "0", "x-ratelimit-reset-requests": "20s"}

    assert budget_with(headers, FakeClock()).wait_before(10) == pytest.approx(20.0)


def test_wait_is_capped() -> None:
    headers = {**GROQ_HEADERS, "x-ratelimit-remaining-requests": "0"}  # resets in ~3 minutes

    assert budget_with(headers, FakeClock(), max_wait=60.0).wait_before(10) == 60.0


def test_latest_headers_win() -> None:
    clock = FakeClock()
    budget = budget_with(GROQ_HEADERS, clock)
    budget.update(RateLimitHeaders.parse({**GROQ_HEADERS, "x-ratelimit-remaining-tokens": "8000"}))
    budget.update(None)  # a reply without headers changes nothing

    assert budget.wait_before(3000) == 0.0


def test_estimate_grows_with_the_request() -> None:
    small = estimate_tokens({"messages": ["hi"]}, output_reserve=0)
    big = estimate_tokens({"messages": ["x" * 4000]}, output_reserve=0)

    assert small < 10 and 1000 <= big < 1010
    assert estimate_tokens({}, output_reserve=500) >= 500
