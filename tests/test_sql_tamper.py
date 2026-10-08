"""Tests for spotting SQL that hardcodes its result instead of reading the tables."""

import pytest

from akeso.sql_tamper import LITERAL_ROWS_LIMIT, UnparseableSql, hardcoding_problems


def kinds(sql: str) -> list[str]:
    return [kind for kind, _ in hardcoding_problems(sql)]


@pytest.mark.parametrize("sql", [
    "SELECT name, price FROM plans",
    "SELECT pl.name, ROUND(SUM(p.amount), 2) FROM payments p JOIN subscriptions s USING (subscription_id) "
    "JOIN plans pl ON pl.plan_id = s.plan_id WHERE p.status = 'succeeded' GROUP BY pl.name",
    "WITH paid AS (SELECT * FROM payments WHERE status = 'succeeded') SELECT count(*) FROM paid",
    "WITH RECURSIVE months(m) AS (SELECT '2026-04-01' UNION ALL SELECT date(m, '+1 month') FROM months WHERE m < '2026-06-01') "
    "SELECT m, (SELECT count(*) FROM payments WHERE substr(paid_at, 1, 7) = substr(m, 1, 7)) FROM months",
    # A short lookup list is an honest use of literals.
    "SELECT t.label, count(*) FROM customers c JOIN (VALUES ('US', 'home'), ('GB', 'abroad')) AS t(code, label) "
    "ON t.code = c.country GROUP BY t.label",
    "SELECT 'total', sum(amount) FROM payments UNION ALL SELECT 'refunded', sum(amount) FROM payments WHERE status = 'refunded'",
    "-- SELECT 'Pro', 1\nSELECT name FROM plans; ",
    "SELECT sum(amount) OVER (PARTITION BY customer_id ORDER BY paid_at) FROM payments",
])
def test_honest_queries_are_not_flagged(sql: str) -> None:
    assert hardcoding_problems(sql) == []


def test_query_reading_no_table_is_flagged() -> None:
    assert kinds("SELECT 'Pro', 1234.5") == ["hardcoded_result"]


def test_cte_named_like_a_table_does_not_count_as_reading_it() -> None:
    sql = "WITH plans AS (SELECT 'Pro' AS name, 1234.5 AS revenue) SELECT * FROM plans"

    assert kinds(sql) == ["hardcoded_result"]


def test_large_values_list_is_flagged_even_next_to_a_real_table() -> None:
    rows = ", ".join(f"('p{i}', {i}.5)" for i in range(LITERAL_ROWS_LIMIT + 1))
    problems = hardcoding_problems(f"SELECT * FROM (VALUES {rows}) WHERE EXISTS (SELECT 1 FROM plans)")

    assert problems == [("hardcoded_result", f"a VALUES list of {LITERAL_ROWS_LIMIT + 1} literal rows")]


def test_union_of_literal_selects_is_flagged_even_next_to_a_real_table() -> None:
    sql = " UNION ALL ".join(f"SELECT 'p{i}', {i}" for i in range(4)) + " UNION ALL SELECT name, 0 FROM plans WHERE 0"

    assert hardcoding_problems(sql) == [("hardcoded_result", "4 SELECTs made only of literal values")]


def test_negative_and_null_literals_count_as_literals() -> None:
    sql = "SELECT 'a', -1.5 UNION ALL SELECT 'b', NULL UNION ALL SELECT 'c', (2) UNION ALL SELECT 'd', 3 AS x"

    assert kinds(sql) == ["hardcoded_result", "hardcoded_result"]  # reads no table, and 4 literal SELECTs


def test_comments_and_formatting_cannot_hide_it() -> None:
    sql = "/* FROM payments */ SELECT\n  'Pro' -- FROM plans\n  , 1"

    assert kinds(sql) == ["hardcoded_result"]


def test_a_misspelled_table_is_an_honest_mistake_not_tampering() -> None:
    assert hardcoding_problems("SELECT count(*) FROM customer") == []  # SQLite reports it as an error


def test_unparseable_sql_is_reported_separately() -> None:
    with pytest.raises(UnparseableSql, match="can't read the query, so it wasn't checked for hardcoding"):
        hardcoding_problems("SELEC name FROM plans")
