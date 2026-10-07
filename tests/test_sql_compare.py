"""Tests for comparing a query result with the gold result."""

import pytest

from akeso.sql_compare import QueryResult, compare_results, normalize_value

GOLD = QueryResult(["plan", "revenue"], [["Pro", 1234.5], ["Starter", 380.0], ["Business", 2580.0]])


def compare(candidate: QueryResult, expected: QueryResult = GOLD, *, order_matters: bool = False, precision: int = 2):
    return compare_results(candidate, expected, order_matters=order_matters, precision=precision)


def test_identical_results_match() -> None:
    result = compare(GOLD)

    assert result.matches and result.reason == ""
    assert result.candidate_shape == result.expected_shape == (3, 2)


def test_same_rows_in_a_different_order_match() -> None:
    assert compare(QueryResult(["plan", "revenue"], list(reversed(GOLD.rows)))).matches


def test_float_noise_is_ignored() -> None:
    noisy = QueryResult(["plan", "revenue"], [["Pro", 1234.4999999999998], ["Starter", 379.99999999999994], ["Business", 2580.0000000001]])

    assert compare(noisy).matches


def test_noise_at_a_rounding_boundary_is_ignored() -> None:
    # 2.675 is stored as 2.67499999...; a sum that lands just above it must still match.
    assert compare(QueryResult(["x"], [[2.6750000000001]]), QueryResult(["x"], [[2.675]])).matches


def test_real_differences_beyond_the_precision_count() -> None:
    result = compare(QueryResult(["plan", "revenue"], [["Pro", 1234.51], ["Starter", 380.0], ["Business", 2580.0]]))

    assert not result.matches
    assert result.reason == "it has the right number of rows, but some rows hold different values"
    assert (result.missing, result.extra) == (1, 1)


def test_precision_is_configurable() -> None:
    close = QueryResult(["x"], [[0.123]])

    assert compare(close, QueryResult(["x"], [[0.12]]), precision=2).matches
    assert not compare(close, QueryResult(["x"], [[0.12]]), precision=3).matches


def test_a_missing_row_fails() -> None:
    result = compare(QueryResult(["plan", "revenue"], GOLD.rows[:2]))

    assert not result.matches
    assert result.reason == "it has 2 row(s); the expected result has 3"
    assert (result.missing, result.extra) == (1, 0)


def test_an_extra_duplicate_row_fails() -> None:
    # As a set this would match: duplicates must be counted.
    result = compare(QueryResult(["plan", "revenue"], [*GOLD.rows, GOLD.rows[0]]))

    assert not result.matches
    assert (result.missing, result.extra) == (0, 1)


def test_duplicates_must_match_in_number() -> None:
    expected = QueryResult(["x"], [[1], [1], [2]])

    assert compare(QueryResult(["x"], [[1], [2], [1]]), expected).matches
    assert not compare(QueryResult(["x"], [[1], [2], [2]]), expected).matches


def test_column_aliases_do_not_matter() -> None:
    assert compare(QueryResult(["plan_name", "total_revenue_usd"], GOLD.rows)).matches


def test_columns_are_compared_by_position() -> None:
    swapped = QueryResult(["revenue", "plan"], [[r, p] for p, r in GOLD.rows])

    assert not compare(swapped).matches


def test_a_different_number_of_columns_fails() -> None:
    result = compare(QueryResult(["plan"], [[p] for p, _ in GOLD.rows]))

    assert not result.matches
    assert result.reason == "it has 1 column(s); the expected result has 2"


def test_integer_and_float_are_equal() -> None:
    assert compare(QueryResult(["n"], [[1], [2]]), QueryResult(["n"], [[1.0], [2.0]])).matches


def test_nulls_equal_only_nulls() -> None:
    expected = QueryResult(["country", "n"], [[None, 3], ["US", 5]])

    assert compare(QueryResult(["c", "n"], [["US", 5], [None, 3]]), expected).matches
    assert not compare(QueryResult(["c", "n"], [["", 3], ["US", 5]]), expected).matches
    assert not compare(QueryResult(["c", "n"], [[None, 3], ["US", None]]), QueryResult(["c", "n"], [[None, 3], ["US", 0]])).matches


def test_text_is_exact() -> None:
    assert not compare(QueryResult(["x"], [["pro"]]), QueryResult(["x"], [["Pro"]])).matches
    assert not compare(QueryResult(["x"], [["1"]]), QueryResult(["x"], [[1]])).matches


def test_order_sensitive_task() -> None:
    ordered = QueryResult(["plan", "revenue"], sorted(GOLD.rows, key=lambda r: -r[1]))

    assert compare(ordered, ordered, order_matters=True).matches
    result = compare(QueryResult(["plan", "revenue"], list(reversed(ordered.rows))), ordered, order_matters=True)
    assert not result.matches
    assert result.reason == "it has the right rows, but in the wrong order (this question asks for a specific order)"


def test_order_sensitive_task_still_ignores_float_noise() -> None:
    expected = QueryResult(["x"], [[0.3], [0.1]])

    assert compare(QueryResult(["x"], [[0.1 + 0.2], [0.1]]), expected, order_matters=True).matches


def test_empty_results() -> None:
    empty = QueryResult(["x"], [])

    assert compare(empty, empty).matches
    assert compare(empty, QueryResult(["x"], [[1]])).reason == "it has 0 row(s); the expected result has 1"


@pytest.mark.parametrize(("value", "normalized"), [
    (None, None), ("a", "a"), (1, 1.0), (True, 1.0), (-0.0, 0.0), (2.0000000001, 2.0), (10**20, 10**20),
    (float("inf"), float("inf")),
])
def test_normalize_value(value, normalized) -> None:
    assert normalize_value(value, 2) == normalized


def test_nan_equals_nan() -> None:
    assert compare(QueryResult(["x"], [[float("nan")]]), QueryResult(["x"], [[float("nan")]])).matches


def test_reasons_never_contain_expected_values() -> None:
    for candidate in (QueryResult(["p", "r"], [["Pro", 1.0]]), QueryResult(["p", "r"], [["Pro", 1.0], ["X", 2.0], ["Y", 3.0]])):
        reason = compare(candidate).reason
        assert not any(str(v) in reason for row in GOLD.rows for v in row)
