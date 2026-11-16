"""Tests for the statistics over repeated attempts."""

import pytest

from akeso.stats import mean_and_std, pass_at, pass_at_k, solve_counts


@pytest.mark.parametrize(("n", "c", "k", "expected"), [
    (3, 0, 1, 0.0), (3, 3, 1, 1.0), (3, 1, 1, 1 / 3), (3, 1, 3, 1.0), (3, 1, 2, 2 / 3), (5, 2, 2, 1 - 3 / 10),
])
def test_pass_at_k(n: int, c: int, k: int, expected: float) -> None:
    assert pass_at_k(n, c, k) == pytest.approx(expected)


def test_pass_at_k_rejects_impossible_counts() -> None:
    with pytest.raises(ValueError):
        pass_at_k(2, 3, 1)


def test_mean_and_std() -> None:
    assert mean_and_std([0.5, 0.7, 0.6]) == (pytest.approx(0.6), pytest.approx(0.1))
    assert mean_and_std([0.4]) == (0.4, 0.0)
    assert mean_and_std([]) == (0.0, 0.0)


def test_solve_counts_and_pass_at() -> None:
    counts = solve_counts([("a", True), ("a", False), ("b", False), ("b", False), ("a", True)])

    assert counts == {"a": (2, 3), "b": (0, 2)}
    assert pass_at(counts, 1) == pytest.approx((2 / 3 + 0) / 2)
    assert pass_at(counts, 3) == pytest.approx((1.0 + 0.0) / 2)  # b has only 2 attempts: uses pass@2


def test_known_differences_between_two_sets_of_results() -> None:
    # Run A: task a solved 1/3, b 0/3. Run B: a 3/3, b 1/3.
    run_a = solve_counts([("a", True), ("a", False), ("a", False), ("b", False), ("b", False), ("b", False)])
    run_b = solve_counts([("a", True), ("a", True), ("a", True), ("b", True), ("b", False), ("b", False)])

    assert pass_at(run_b, 1) - pass_at(run_a, 1) == pytest.approx((3 / 3 + 1 / 3) / 2 - (1 / 3 + 0) / 2)  # +0.5
    assert pass_at(run_a, 2) == pytest.approx((2 / 3 + 0) / 2)
    assert pass_at(run_b, 2) == pytest.approx((1.0 + 2 / 3) / 2)
    assert pass_at(run_b, 3) - pass_at(run_a, 3) == pytest.approx(0.5)  # b went from never to at least once


def test_the_spread_between_repeats_reflects_a_known_change() -> None:
    steady = mean_and_std([0.6, 0.6, 0.6])
    swinging = mean_and_std([0.2, 0.6, 1.0])

    assert steady == (pytest.approx(0.6), 0.0)
    assert swinging == (pytest.approx(0.6), pytest.approx(0.4))  # same mean, spread 0.4
