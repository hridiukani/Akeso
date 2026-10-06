import pytest

from dates import days_in_month, is_leap_year


@pytest.mark.parametrize(
    ("year", "expected"),
    [(1600, True), (1700, False), (1800, False), (2000, True), (2019, False),
     (2028, True), (2100, False), (2400, True)],
)
def test_leap_years(year: int, expected: bool) -> None:
    assert is_leap_year(year) is expected


def test_february_2400() -> None:
    assert days_in_month(2400, 2) == 29


def test_february_2100() -> None:
    assert days_in_month(2100, 2) == 28


def test_months_other_than_february_ignore_leap_years() -> None:
    assert days_in_month(2000, 1) == 31 and days_in_month(2000, 3) == 31
