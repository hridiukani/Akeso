"""Minimal reproduction of the bug report, plus values that already work."""

import humanize


def test_almost_three() -> None:
    assert humanize.fractional(2.9999999) == "3"


def test_ordinary_values() -> None:
    assert humanize.fractional(1.5) == "1 1/2"
    assert humanize.fractional(0.3) == "3/10"
    assert humanize.fractional(1) == "1"
    assert humanize.fractional(-2.5) == "-2 1/2"
