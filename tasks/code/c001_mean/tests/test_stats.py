import pytest

from stats import mean


def test_mean_of_several_numbers() -> None:
    assert mean([2, 4, 6]) == pytest.approx(4.0)


def test_mean_of_single_number() -> None:
    assert mean([7]) == pytest.approx(7.0)


def test_mean_of_numbers_centered_on_zero() -> None:
    assert mean([-3, 0, 3]) == pytest.approx(0.0)
