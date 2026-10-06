import pytest

from durations import format_duration


def test_seconds_only() -> None:
    assert format_duration(59) == "0:00:59"


def test_whole_minutes() -> None:
    assert format_duration(600) == "0:10:00"


def test_more_than_an_hour() -> None:
    assert format_duration(3725) == "1:02:05"


def test_negative_seconds_are_rejected() -> None:
    with pytest.raises(ValueError):
        format_duration(-1)
