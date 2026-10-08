"""Minimal reproduction of the bug report, plus behaviour that already works."""

from more_itertools import numeric_range


def test_reversed_empty_range() -> None:
    assert list(reversed(numeric_range(0))) == []


def test_reversed_non_empty_ranges() -> None:
    assert list(reversed(numeric_range(3))) == [2, 1, 0]
    assert list(reversed(numeric_range(1.0, 2.0, 0.5))) == [1.5, 1.0]
