import pytest

from stats import mean


@pytest.mark.parametrize(
    ("numbers", "expected"),
    [
        ([1, 2, 3, 4], 2.5),
        ([10, 20], 15.0),
        ([-1.5, 1.5, 3.0], 1.0),
        ([0.1, 0.2, 0.3], 0.2),
        ([1_000_000, 3_000_000], 2_000_000.0),
    ],
)
def test_mean_of_other_lists(numbers: list[float], expected: float) -> None:
    assert mean(numbers) == pytest.approx(expected)


def test_mean_of_a_single_negative_number() -> None:
    assert mean([-4]) == pytest.approx(-4.0)
