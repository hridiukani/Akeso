"""Tests for shared SQL datasets: the saas schema and its seeded generator."""

import sqlite3
from pathlib import Path

import pytest

from akeso.datasets import Dataset, DatasetError, _build, load_dataset

SAAS = load_dataset("saas", Path("tasks/datasets"))


def open_db(data: bytes) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.deserialize(data)
    return conn


def scalar(conn: sqlite3.Connection, sql: str):
    return conn.execute(sql).fetchone()[0]


def test_same_seed_same_bytes() -> None:
    first = SAAS.build(5)
    _build.cache_clear()  # really generate it again

    assert SAAS.build(5) == first


def test_different_seeds_differ() -> None:
    assert SAAS.build(5) != SAAS.build(6)


@pytest.fixture(scope="module")
def db() -> sqlite3.Connection:
    return open_db(SAAS.build(11))


def test_has_the_messy_parts_real_data_has(db: sqlite3.Connection) -> None:
    assert scalar(db, "SELECT count(*) FROM customers WHERE email IS NULL") > 0
    assert scalar(db, "SELECT count(*) FROM customers WHERE country IS NULL") > 0
    assert scalar(db, "SELECT count(*) FROM customers c WHERE NOT EXISTS "
                      "(SELECT 1 FROM payments p WHERE p.customer_id = c.customer_id)") > 0
    assert scalar(db, "SELECT count(*) FROM subscriptions WHERE end_reason = 'plan_change'") > 0
    assert scalar(db, "SELECT count(*) FROM subscriptions WHERE end_date IS NULL") > 0
    assert scalar(db, "SELECT count(DISTINCT status) FROM payments") == 3
    assert scalar(db, "SELECT count(*) FROM payments WHERE amount <> round(amount)") > 0  # discounts, proration
    assert scalar(db, "SELECT count(*) FROM plans p WHERE NOT EXISTS "
                      "(SELECT 1 FROM subscriptions s WHERE s.plan_id = p.plan_id)") == 1


def test_has_timestamps_on_day_and_month_boundaries(db: sqlite3.Connection) -> None:
    assert scalar(db, "SELECT count(*) FROM payments WHERE time(paid_at) = '00:00:00'") > 0
    assert scalar(db, "SELECT count(*) FROM payments WHERE time(paid_at) = '23:59:59'") > 0
    assert scalar(db, "SELECT count(*) FROM payments WHERE date(paid_at) = date(paid_at, 'start of month')") > 0
    assert scalar(db, "SELECT count(*) FROM payments WHERE date(paid_at) = date(paid_at, 'start of month', '+1 month', '-1 day')") > 0


def test_data_is_consistent(db: sqlite3.Connection) -> None:
    # Every payment belongs to its customer's own subscription, inside the data's date range.
    assert scalar(db, "SELECT count(*) FROM payments p JOIN subscriptions s USING (subscription_id) "
                      "WHERE s.customer_id <> p.customer_id") == 0
    assert scalar(db, "SELECT min(date(paid_at)) >= '2025-01-01' AND max(date(paid_at)) <= '2026-09-30' FROM payments") == 1
    # A plan change ends one subscription and starts the next on the same day.
    assert scalar(db, "SELECT count(*) FROM subscriptions a WHERE end_reason = 'plan_change' AND NOT EXISTS "
                      "(SELECT 1 FROM subscriptions b WHERE b.customer_id = a.customer_id AND b.start_date = a.end_date)") == 0


def test_missing_dataset_is_reported(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="missing schema.sql, generate.py"):
        load_dataset("nope", tmp_path)


def test_generator_failure_is_reported(tmp_path: Path) -> None:
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "schema.sql").write_text("CREATE TABLE t (x INTEGER);")
    (tmp_path / "broken" / "generate.py").write_text("def populate(conn, seed):\n    raise ValueError('boom')\n")

    with pytest.raises(DatasetError, match="seed 3 failed: boom"):
        Dataset("broken", tmp_path / "broken").build(3)
