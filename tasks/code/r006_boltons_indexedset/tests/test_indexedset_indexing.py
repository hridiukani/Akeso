"""Minimal reproduction of the bug report, plus indexing that already works."""

import pytest

from boltons.setutils import IndexedSet


def test_negative_index_past_the_start_raises() -> None:
    with pytest.raises(IndexError):
        IndexedSet([10, 20, 30])[-4]


def test_valid_indexes() -> None:
    s = IndexedSet([10, 20, 30])
    assert (s[0], s[-1], s[-3]) == (10, 30, 10)
    with pytest.raises(IndexError):
        s[3]
