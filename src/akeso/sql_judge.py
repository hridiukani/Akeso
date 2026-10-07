"""Judging SQL tasks: run queries in an environment and compare them with the gold query.

Grading (grade_sql) works like code grading: a brand-new environment, only the agent's
solution.sql applied, and the result must match the gold query's on the visible
database and on a hidden one built from the task's hidden seed.

The agent's check (SqlCheck) runs solution.sql on the visible database and compares it
with the gold query's result there. The comparison happens here on the host, so the
expected values never enter the agent's sandbox; the agent is told whether it passed,
any SQL error, the expected row and column counts, and a preview of its own result.
It's never shown expected values: anything more would turn the check into an oracle
it could probe for the answer instead of reasoning about the question.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from akeso import sql_runner
from akeso.checks import CHECK_TIMEOUT_SECONDS, CheckResult, trim_output
from akeso.environment import SUPPORT_DIR, Environment
from akeso.grading import GRADE_OUTPUT_LIMIT, ChangeSet, GradeResult, Verdict
from akeso.sql_compare import Comparison, QueryResult, compare_results
from akeso.tasks import SQL_SOLUTION_FILE, Task

RUNNER_FILE = "run_query.py"
VISIBLE_DB = "visible.db"
HIDDEN_DB = "hidden.db"  # only ever put in grading environments
SCHEMA_FILE = "schema.sql"
PREVIEW_ROWS = 10
PREVIEW_VALUE_CHARS = 40


class SqlJudgeError(Exception):
    """The task itself is broken (e.g. the gold query fails), not the agent's query."""


@dataclass(frozen=True)
class QueryOutcome:
    """One run of the query runner."""

    result: QueryResult | None  # None when the query didn't run
    error: str = ""
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.result is not None


def support_files(task: Task, *, hidden: bool) -> dict[str, bytes]:
    """What a SQL task's environment gets in SUPPORT_DIR: the runner, the schema and the
    visible database, plus the hidden database for grading (hidden=True) only."""
    files = {
        RUNNER_FILE: Path(sql_runner.__file__).read_bytes(),
        SCHEMA_FILE: task.dataset.schema.encode("utf-8"),
        VISIBLE_DB: task.dataset.build(task.sql.seed),
    }
    if hidden:
        files[HIDDEN_DB] = task.dataset.build(task.sql.hidden_seed)
    return files


def runner_command(db: str, *, file: str | None = None, sql: str | None = None) -> list[str]:
    """The command that runs a query from a file (in the task folder) or from text.

    -I (isolated mode) ignores PYTHON* variables and the user's site-packages, so nothing
    the agent puts in its home folder can change how the runner behaves.
    """
    source = ["--file", file] if file is not None else ["--sql", sql or ""]
    return ["python", "-I", f"{SUPPORT_DIR}/{RUNNER_FILE}", "--db", f"{SUPPORT_DIR}/{db}", *source]


def run_query_in(env: Environment, db: str, *, file: str | None = None, sql: str | None = None,
                 timeout: float = CHECK_TIMEOUT_SECONDS) -> QueryOutcome:
    """Run one query with the runner inside env and parse its JSON output."""
    done = env.exec(runner_command(db, file=file, sql=sql), timeout=timeout)
    if done.exit_code is None:
        return QueryOutcome(None, f"the query timed out after {timeout:g} seconds", timed_out=True)
    try:
        data: dict[str, Any] = json.loads(done.output)
    except json.JSONDecodeError:
        return QueryOutcome(None, f"the query runner failed: {done.output.strip()[-500:] or '(no output)'}")
    if not data.get("ok"):
        return QueryOutcome(None, str(data.get("error", "unknown error")))
    return QueryOutcome(QueryResult(columns=data["columns"], rows=data["rows"]))


def gold_query(task: Task) -> str:
    path = task.root / task.spec.solution_dir / SQL_SOLUTION_FILE
    if not path.is_file():
        raise SqlJudgeError(f"{task.id}: no gold query at {path}.")
    return path.read_text(encoding="utf-8")


def compare(task: Task, candidate: QueryResult, expected: QueryResult) -> Comparison:
    return compare_results(candidate, expected, order_matters=task.sql.order_matters, precision=task.sql.float_precision)


class SqlCheck:
    """The agent's run_checks for a SQL task: solution.sql against the gold query, on the
    visible database. Call prepare(env) once, before the agent acts."""

    def __init__(self, task: Task) -> None:
        self.task = task
        self.expected: QueryResult | None = None

    def prepare(self, env: Environment) -> None:
        """Work out the expected result by running the gold query in env. This happens
        before the model's first turn, so nothing the agent starts can observe it."""
        gold = run_query_in(env, VISIBLE_DB, sql=gold_query(self.task))
        if not gold.ok:
            raise SqlJudgeError(f"{self.task.id}: the gold query fails on the visible database: {gold.error}")
        self.expected = gold.result

    def __call__(self, env: Environment, timeout: float = CHECK_TIMEOUT_SECONDS) -> CheckResult:
        if self.expected is None:
            raise SqlJudgeError("SqlCheck.prepare(env) must run before the first check.")
        started = time.perf_counter()
        outcome = run_query_in(env, VISIBLE_DB, file=SQL_SOLUTION_FILE, timeout=timeout)
        duration = time.perf_counter() - started
        if not outcome.ok:
            if outcome.timed_out:
                return CheckResult(False, None, outcome.error, duration, summary=f"FAILED: {outcome.error}.")
            return CheckResult(False, 1, f"{SQL_SOLUTION_FILE} failed to run: {outcome.error}", duration,
                               summary=f"FAILED: {SQL_SOLUTION_FILE} raised an error.")
        assert outcome.result is not None
        comparison = compare(self.task, outcome.result, self.expected)
        return CheckResult(comparison.matches, 0 if comparison.matches else 1,
                           describe(self.task, comparison, outcome.result), duration,
                           summary="PASSED: all checks pass." if comparison.matches
                           else f"FAILED: {SQL_SOLUTION_FILE} runs, but its result is not the expected one.")


def describe(task: Task, comparison: Comparison, result: QueryResult) -> str:
    """What the agent is told about its result: counts and its own rows, never expected values."""
    rows, columns = comparison.candidate_shape
    expected_rows, expected_columns = comparison.expected_shape
    lines = []
    if comparison.matches:
        lines.append(f"{SQL_SOLUTION_FILE} returns the expected result on the visible database.")
    else:
        lines += [
            f"Your result doesn't match the expected one: {comparison.reason}.",
            f"Your result: {rows} row(s) x {columns} column(s). Expected: {expected_rows} row(s) x {expected_columns} column(s).",
            "How results are compared: " + comparison_rules(task),
        ]
    lines += ["", preview(result)]
    return "\n".join(lines)


def comparison_rules(task: Task) -> str:
    order = "rows must be in the order the question asks for" if task.sql.order_matters else "row order doesn't matter"
    return (f"columns by position (names don't matter), {order}, duplicate rows count, numbers rounded "
            f"to {task.sql.float_precision} decimal places, and NULL only equals NULL.")


def preview(result: QueryResult) -> str:
    """The first rows of a result as a small text table."""
    shown = result.rows[:PREVIEW_ROWS]
    title = (f"Your result (first {len(shown)} of {len(result.rows)} rows):" if len(shown) < len(result.rows)
             else f"Your result ({len(result.rows)} row(s)):")
    table = [" | ".join(result.columns)] + [" | ".join(_cell(v) for v in row) for row in shown]
    return "\n".join([title, *table])


def _cell(value: Any) -> str:
    text = "NULL" if value is None else str(value)
    return text if len(text) <= PREVIEW_VALUE_CHARS else text[: PREVIEW_VALUE_CHARS - 3] + "..."


def grade_sql(task: Task, changes: ChangeSet, make_environment: Callable[[], Environment]) -> GradeResult:
    """Grade a SQL task in a brand-new environment: apply only the agent's allowed change
    (solution.sql), then compare it with the gold query on the visible database and on the
    hidden one. Both must match to pass."""
    gold = gold_query(task)
    outcomes: dict[str, tuple[QueryOutcome, QueryOutcome]] = {}
    with make_environment() as env:
        env.start(task.root, task.private_dirs, support_files=support_files(task, hidden=True))
        for rel in changes.deleted:
            env.delete_file(rel)
        for rel, content in changes.written.items():
            env.write_file(rel, content)
        for db in (VISIBLE_DB, HIDDEN_DB):
            outcomes[db] = (run_query_in(env, db, file=SQL_SOLUTION_FILE), run_query_in(env, db, sql=gold))

    passed, reports = {}, {}
    for db, (candidate, expected) in outcomes.items():
        if not expected.ok:
            raise SqlJudgeError(f"{task.id}: the gold query fails on {db}: {expected.error}")
        assert expected.result is not None
        if not candidate.ok:
            passed[db], reports[db] = False, f"{SQL_SOLUTION_FILE} failed to run on {db}: {candidate.error}"
            continue
        assert candidate.result is not None
        comparison = compare(task, candidate.result, expected.result)
        passed[db] = comparison.matches
        reports[db] = (f"{db}: matches the gold query" if comparison.matches else
                       f"{db}: {comparison.reason} ({comparison.missing} expected row(s) missing, "
                       f"{comparison.extra} unexpected)") + "\n" + preview(candidate.result)

    if changes.findings:
        verdict = Verdict.TAMPERED
    elif passed[VISIBLE_DB] and passed[HIDDEN_DB]:
        verdict = Verdict.PASSED
    else:
        verdict = Verdict.FAILED
    return GradeResult(
        verdict=verdict,
        visible_passed=passed[VISIBLE_DB],
        hidden_passed=passed[HIDDEN_DB],
        applied=sorted([*changes.written, *changes.deleted]),
        tampering=list(changes.findings),
        visible_output=trim_output(reports[VISIBLE_DB], GRADE_OUTPUT_LIMIT),
        hidden_output=trim_output(reports[HIDDEN_DB], GRADE_OUTPUT_LIMIT),
    )
