"""Tests for the read-only query runner, run the way the sandbox runs it: `python -I run_query.py ...`."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from akeso import sql_runner
from akeso.datasets import load_dataset
from akeso.sql_runner import format_result, run_query

RUNNER = Path(sql_runner.__file__)


@pytest.fixture(scope="module")
def db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("db") / "visible.db"
    path.write_bytes(load_dataset("saas", Path("tasks/datasets")).build(11))
    return path


def run(*args: str, cwd: Path | None = None) -> tuple[int, dict]:
    done = subprocess.run([sys.executable, "-I", str(RUNNER), *args], capture_output=True, text=True, cwd=cwd, timeout=60)
    return done.returncode, json.loads(done.stdout)


def query(db: Path, sql: str) -> tuple[int, dict]:
    """In-process, for the many-case tests (the same code; a subprocess per case is slow)."""
    out = run_query(db, sql)
    return (0 if out["ok"] else 1), out


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_select_prints_columns_and_rows(db: Path) -> None:
    code, out = run("--db", str(db), "--sql", "SELECT plan_id, name AS plan FROM plans ORDER BY plan_id LIMIT 2")

    assert code == 0
    assert out == {"ok": True, "columns": ["plan_id", "plan"], "row_count": 2, "truncated": False,
                   "rows": [[1, "Starter"], [2, "Pro"]]}


def test_reads_the_query_from_a_file(db: Path, tmp_path: Path) -> None:
    (tmp_path / "solution.sql").write_text("-- how many plans?\nSELECT count(*) AS n FROM plans;\n")

    code, out = run("--db", str(db), "--file", "solution.sql", cwd=tmp_path)

    assert code == 0 and out["rows"] == [[6]]


def test_with_and_recursive_queries_work(db: Path) -> None:
    code, out = run("--db", str(db), "--sql",
                    "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 3) SELECT i FROM n")

    assert code == 0 and out["rows"] == [[1], [2], [3]]


def test_nulls_floats_and_max_rows(db: Path) -> None:
    code, out = run("--db", str(db), "--max-rows", "1", "--sql", "SELECT NULL, 1.5, x'00ff' UNION ALL SELECT 1, 2, 3")

    assert code == 0
    assert out["rows"] == [[None, 1.5, "00ff"]]
    assert out["row_count"] == 2 and out["truncated"] is True


def test_schema_pragmas_are_allowed_for_exploring(db: Path) -> None:
    code, out = query(db, "PRAGMA table_info(plans)")

    assert code == 0 and [row[1] for row in out["rows"]] == ["plan_id", "name", "billing_period", "price"]


@pytest.mark.parametrize("sql", [
    "INSERT INTO plans VALUES (99, 'Free', 'monthly', 0)",
    "UPDATE payments SET amount = 0",
    "DELETE FROM customers",
    "DROP TABLE payments",
    "CREATE TABLE notes (x TEXT)",
    "CREATE TEMP TABLE notes AS SELECT 1",
    "ALTER TABLE plans ADD COLUMN y",
    "ATTACH DATABASE 'other.db' AS other",
    "VACUUM INTO 'copy.db'",
    "PRAGMA query_only = OFF",
    "PRAGMA journal_mode = DELETE",
    "SELECT load_extension('evil')",
    "REPLACE INTO plans VALUES (1, 'Starter', 'monthly', 0)",
    "WITH x AS (SELECT 1) DELETE FROM plans",
])
def test_statements_that_change_anything_are_blocked(db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sql: str) -> None:
    before = digest(db)

    monkeypatch.chdir(tmp_path)  # a relative 'copy.db' or 'other.db' would land here
    code, out = query(db, sql)

    assert code == 1 and out["ok"] is False
    assert "read-only" in out["error"] or "not allowed" in out["error"]
    assert digest(db) == before
    assert list(tmp_path.iterdir()) == []  # no copy or attached file was created


def test_only_one_statement(db: Path) -> None:
    before = digest(db)

    code, out = run("--db", str(db), "--sql", "SELECT 1; DELETE FROM plans")

    assert code == 1 and "only one SQL statement" in out["error"]
    assert digest(db) == before


@pytest.mark.parametrize(("sql", "message"), [
    ("SELEC 1", "syntax error"),
    ("SELECT nope FROM plans", "no such column: nope"),
    ("SELECT * FROM missing", "no such table: missing"),
    ("   ", "the query is empty"),
    ("-- just a comment", "no result"),
])
def test_errors_are_reported_clearly(db: Path, sql: str, message: str) -> None:
    code, out = query(db, sql)

    assert code == 1 and message in out["error"]


def test_missing_database_is_never_created(tmp_path: Path) -> None:
    code, out = run("--db", str(tmp_path / "nope.db"), "--sql", "SELECT 1")

    assert code == 1 and "database not found" in out["error"]
    assert not (tmp_path / "nope.db").exists()


def test_missing_query_file(db: Path, tmp_path: Path) -> None:
    code, out = run("--db", str(db), "--file", "solution.sql", cwd=tmp_path)

    assert code == 1 and "can't read solution.sql" in out["error"]


def test_runaway_results_are_refused(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sql_runner, "ROW_LIMIT", 10)

    assert run_query(db, "SELECT * FROM payments")["error"] == "the query returned more than 10 rows"


def test_format_result_is_json_with_a_row_per_line() -> None:
    text = format_result({"ok": True, "columns": ["a"], "row_count": 2, "truncated": False, "rows": [[1], [2]]})

    assert text.count("\n") == 3
    assert json.loads(text)["rows"] == [[1], [2]]
    assert json.loads(format_result({"ok": True, "columns": ["a"], "row_count": 0, "truncated": False, "rows": []}))["rows"] == []
