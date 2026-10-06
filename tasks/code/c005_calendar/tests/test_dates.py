import pytest

from dates import days_in_month


def test_april_has_30_days() -> None:
    assert days_in_month(2023, 4) == 30


def test_february_in_a_common_year() -> None:
    assert days_in_month(2023, 2) == 28


def test_february_in_a_leap_year() -> None:
    assert days_in_month(2024, 2) == 29


def test_century_years_are_usually_not_leap_years() -> None:
    assert days_in_month(1900, 2) == 28


def test_year_2000_was_a_leap_year() -> None:
    assert days_in_month(2000, 2) == 29


def test_invalid_month_is_rejected() -> None:
    with pytest.raises(ValueError):
        days_in_month(2023, 13)
