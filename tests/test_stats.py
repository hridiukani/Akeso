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
