"""Run one read-only SQL query against a SQLite database and print the result as JSON.

This file is part of the judge. It's copied into every SQL sandbox as
/akeso/run_query.py, owned by root and read-only, so the agent can run it but never
change it. It uses only the standard library, because it runs inside the container.

    python -I /akeso/run_query.py --sql "SELECT * FROM plans"
    python -I /akeso/run_query.py --file solution.sql [--db /akeso/visible.db] [--max-rows 20]

Prints one JSON object:
    {"ok": true, "columns": [...], "row_count": N, "truncated": false, "rows": [[...], ...]}
    {"ok": false, "error": "..."}
and exits 0 if the query ran, 1 if it didn't.

A query can only read. Three layers make sure of it: the database is opened read-only,
query_only is switched on, and an authorizer allows nothing but reading tables and
calling ordinary functions (so no INSERT/UPDATE/DELETE, CREATE/DROP, ATTACH, VACUUM INTO
or write PRAGMAs). Only one statement is accepted.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(__file__).with_name("visible.db")
ROW_LIMIT = 100_000  # more rows than any task needs: almost certainly a runaway join

# Authorizer action codes that only read. Numbers are fallbacks for Pythons that don't
# export every name.
_SELECT = getattr(sqlite3, "SQLITE_SELECT", 21)
_READ = getattr(sqlite3, "SQLITE_READ", 20)
_FUNCTION = getattr(sqlite3, "SQLITE_FUNCTION", 31)
_RECURSIVE = getattr(sqlite3, "SQLITE_RECURSIVE", 33)  # WITH RECURSIVE
_PRAGMA = getattr(sqlite3, "SQLITE_PRAGMA", 19)
# Pragmas that only describe the schema (their argument names a table or index), for exploring.
_SCHEMA_PRAGMAS = {"table_info", "table_xinfo", "index_list", "index_info", "foreign_key_list"}
_BLOCKED_FUNCTIONS = {"load_extension"}

READ_ONLY_MESSAGE = (
    "not allowed: the database is read-only. Only a single SELECT (or WITH ... SELECT) "
    "query can run; statements that change data, attach databases or change settings are blocked."
)


def _authorize(action: int, arg1: str | None, arg2: str | None, db_name: str | None, source: str | None) -> int:
    if action in (_SELECT, _READ, _RECURSIVE):
        return sqlite3.SQLITE_OK
    if action == _FUNCTION and (arg2 or "").lower() not in _BLOCKED_FUNCTIONS:
        return sqlite3.SQLITE_OK
    if action == _PRAGMA and (arg1 or "").lower() in _SCHEMA_PRAGMAS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def run_query(db_path: str | Path, sql: str, max_rows: int | None = None) -> dict[str, Any]:
    """Run sql read-only against db_path. Returns the result, or {"ok": False, "error": ...}."""
    path = Path(db_path)
    if not path.is_file():
        return {"ok": False, "error": f"database not found: {path}"}
    if not sql.strip():
        return {"ok": False, "error": "the query is empty"}
    # mode=ro: SQLite refuses every write, and never creates a missing file.
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only = ON")
        conn.set_authorizer(_authorize)
        cursor = conn.execute(sql)
        if cursor.description is None:
            return {"ok": False, "error": "the statement returned no result; write a SELECT query"}
        rows = cursor.fetchmany(ROW_LIMIT + 1)
    except sqlite3.ProgrammingError as problem:
        if "one statement at a time" in str(problem):
            return {"ok": False, "error": "only one SQL statement is allowed (remove the extra statements)"}
        return {"ok": False, "error": str(problem)}
    except sqlite3.DatabaseError as problem:  # includes OperationalError (syntax, missing table, ...)
        message = str(problem)
        if "not authorized" in message or "authorization denied" in message:
            message = READ_ONLY_MESSAGE
        return {"ok": False, "error": message}
    finally:
        conn.close()

    if len(rows) > ROW_LIMIT:
        return {"ok": False, "error": f"the query returned more than {ROW_LIMIT} rows"}
    shown = rows if max_rows is None else rows[:max_rows]
    return {
        "ok": True,
        "columns": [column[0] for column in cursor.description],
        "row_count": len(rows),
        "truncated": len(shown) < len(rows),
        "rows": [[_json_value(value) for value in row] for row in shown],
    }


def _json_value(value: Any) -> Any:
    """SQLite values as JSON: blobs (the one type JSON lacks) become hex strings."""
    return value.hex() if isinstance(value, bytes) else value


def format_result(result: dict[str, Any]) -> str:
    """JSON with one row per line, so long results stay readable."""
    if not result["ok"]:
        return json.dumps(result)
    head = {k: v for k, v in result.items() if k != "rows"}
    rows = ",\n  ".join(json.dumps(row) for row in result["rows"])
    return json.dumps(head)[:-1] + (f', "rows": [\n  {rows}\n]}}' if rows else ', "rows": []}')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one read-only SQL query and print the result as JSON.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--sql", help="the query text")
    source.add_argument("--file", help="a file containing the query, e.g. solution.sql")
    parser.add_argument("--db", default=str(DEFAULT_DB), help=f"the database (default: {DEFAULT_DB})")
    parser.add_argument("--max-rows", type=int, default=None, help="print at most this many rows")
    args = parser.parse_args(argv)

    if args.file is not None:
        try:
            sql = Path(args.file).read_text(encoding="utf-8")
        except OSError as problem:
            result: dict[str, Any] = {"ok": False, "error": f"can't read {args.file}: {problem.strerror}"}
            print(format_result(result))
            return 1
    else:
        sql = args.sql
    result = run_query(args.db, sql, args.max_rows)
    print(format_result(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
