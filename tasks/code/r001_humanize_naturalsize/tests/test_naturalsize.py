"""Minimal reproduction of the bug report, plus a few sizes that already work."""

import humanize


def test_just_below_a_megabyte() -> None:
    assert humanize.naturalsize(999999) == "1.0 MB"


def test_ordinary_sizes() -> None:
    assert humanize.naturalsize(3000000) == "3.0 MB"
    assert humanize.naturalsize(300) == "300 Bytes"
    assert humanize.naturalsize(3000, binary=True) == "2.9 KiB"
    assert humanize.naturalsize(3000, gnu=True) == "2.9K"
