import pytest

from intervals import busy_minutes, merge


@pytest.mark.parametrize(("intervals", "merged"), [
    ([], []),
    ([(10, 20)], [(10, 20)]),
    ([(30, 40), (10, 20), (20, 30)], [(10, 40)]),
    ([(100, 200), (0, 50), (150, 160), (50, 60)], [(0, 60), (100, 200)]),
    ([(5, 5), (5, 10)], [(5, 10)]),
    ([(0, 10), (0, 10), (2, 3)], [(0, 10)]),
    ([(700, 800), (100, 200), (650, 700), (300, 400)], [(100, 200), (300, 400), (650, 800)]),
])
def test_merge(intervals, merged) -> None:
    assert merge(intervals) == merged


def test_busy_minutes_for_unsorted_input() -> None:
    assert busy_minutes([(600, 660), (540, 600), (550, 560)]) == 120
    assert busy_minutes([]) == 0
