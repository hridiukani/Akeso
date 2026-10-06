import pytest

from durations import format_duration


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0:00:00"),
        (3600, "1:00:00"),
        (3661, "1:01:01"),
        (7322, "2:02:02"),
        (36000, "10:00:00"),
        (86399, "23:59:59"),
        (93784, "26:03:04"),
    ],
)
def test_other_durations(seconds: int, expected: str) -> None:
    assert format_duration(seconds) == expected
