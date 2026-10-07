"""Compare a query's result with the gold query's result, fairly.

Two results match when they hold the same rows after normalising:
- columns are compared by position; their names (aliases) don't matter
- rows are compared as a multiset (order ignored, duplicates counted) unless the task
  says order matters, in which case they must also be in the same order
- numbers are compared as numbers: 1 equals 1.0, and floats are rounded to the task's
  precision, so float noise from a different but equivalent calculation doesn't matter
- NULL equals NULL and nothing else (not 0, not '')
- text is compared exactly

The Comparison never contains expected values, so it's safe to describe to the agent.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

# Integers beyond this can't all be represented as floats, so they stay integers.
_EXACT_FLOAT_INT = 2**53
# Extra decimals rounded away first, so values that differ only by float noise
# (2.67499999999 vs 2.675) become the same float before the final rounding.
_NOISE_DIGITS = 6
_NAN = ("NaN",)  # NaN never equals itself, so it gets a stand-in that does


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]

    @property
    def shape(self) -> tuple[int, int]:
        """(rows, columns)."""
        return len(self.rows), len(self.columns)


@dataclass(frozen=True)
class Comparison:
    matches: bool
    reason: str  # why not, in words that never reveal expected values ("" when it matches)
    candidate_shape: tuple[int, int]
    expected_shape: tuple[int, int]
    missing: int  # expected rows the candidate lacks (duplicates counted)
    extra: int  # candidate rows that aren't expected (duplicates counted)


def normalize_value(value: Any, precision: int) -> Any:
    """One value in comparable form: numbers as rounded floats, NULL as None, text as is."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, int):
        if abs(value) >= _EXACT_FLOAT_INT:
            return value
        value = float(value)
    if isinstance(value, float):
        if math.isnan(value):
            return _NAN
        if math.isinf(value):
            return value
        rounded = round(round(value, precision + _NOISE_DIGITS), precision)
        return rounded + 0.0  # turns -0.0 into 0.0
    return value


def normalize_rows(rows: Sequence[Sequence[Any]], precision: int) -> list[tuple[Any, ...]]:
    return [tuple(normalize_value(value, precision) for value in row) for row in rows]


def compare_results(candidate: QueryResult, expected: QueryResult, *, order_matters: bool, precision: int) -> Comparison:
    """Does candidate hold the same rows as expected? See the module docstring for the rules."""

    def outcome(reason: str, missing: int = 0, extra: int = 0) -> Comparison:
        return Comparison(not reason, reason, candidate.shape, expected.shape, missing, extra)

    if len(candidate.columns) != len(expected.columns):
        return outcome(f"it has {len(candidate.columns)} column(s); the expected result has {len(expected.columns)}")
    got = normalize_rows(candidate.rows, precision)
    want = normalize_rows(expected.rows, precision)
    got_counts, want_counts = Counter(got), Counter(want)
    missing = sum((want_counts - got_counts).values())
    extra = sum((got_counts - want_counts).values())

    if missing or extra:
        if len(got) != len(want):
            return outcome(f"it has {len(got)} row(s); the expected result has {len(want)}", missing, extra)
        return outcome("it has the right number of rows, but some rows hold different values", missing, extra)
    if order_matters and got != want:
        return outcome("it has the right rows, but in the wrong order (this question asks for a specific order)")
    return outcome("")
