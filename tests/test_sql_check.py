"""Tests for what the agent sees on a SQL task: its check, the tools and the prompt."""

from pathlib import Path

import pytest

from fakes import FakeEnvironment, make_sql_task
from akeso.environment import SUPPORT_DIR
from akeso.llm.types import ToolCall
from akeso.sql_judge import HIDDEN_DB, SqlCheck, SqlJudgeError, preview, runner_command, support_files
from akeso.sql_compare import QueryResult
from akeso.tasks import load_task
from akeso.tools import execute_tool, tool_definitions

GOLD = "SELECT name, price FROM plans WHERE plan_id <= 3 ORDER BY plan_id;\n"
BROKEN = "SELECT name, price FROM plans WHERE plan_id < 3;\n"  # misses Business
ORDERED_WRONG = "SELECT name, price FROM plans WHERE plan_id <= 3 ORDER BY plan_id DESC;\n"


@pytest.fixture
def task(tmp_path: Path):
    return load_task(make_sql_task(tmp_path / "tasks", BROKEN, GOLD))


def started(task, files: dict[str, str] | None = None) -> FakeEnvironment:
    env = FakeEnvironment()
    env.start(task.root, task.private_dirs, support_files=support_files(task, hidden=False))
    env.files.update(files or {})
    return env


def prepared(task, env: FakeEnvironment) -> SqlCheck:
    check = SqlCheck(task)
    check.prepare(env)
    return check


def test_agent_environment_gets_the_runner_schema_and_visible_database_only(task) -> None:
    env = started(task)

    assert sorted(env.support_files) == ["run_query.py", "schema.sql", "visible.db"]
    assert HIDDEN_DB not in env.support_files
    assert sorted(env.files) == ["README.md", "solution.sql"]  # no task.yaml (hidden seed), no gold query


def test_hidden_database_is_only_for_grading(task) -> None:
    files = support_files(task, hidden=True)

    assert files[HIDDEN_DB] == task.dataset.build(911) != files["visible.db"]


def test_runner_command_runs_in_isolated_mode() -> None:
    assert runner_command("visible.db", file="solution.sql") == [
        "python", "-I", f"{SUPPORT_DIR}/run_query.py", "--db", f"{SUPPORT_DIR}/visible.db", "--file", "solution.sql"]


def test_broken_query_fails_with_counts_and_a_preview(task) -> None:
    env = started(task)
    result = prepared(task, env)(env)

    assert not result.passed and result.exit_code == 1
    assert result.summary == "FAILED: solution.sql runs, but its result is not the expected one."
    assert "Your result doesn't match the expected one: it has 2 row(s); the expected result has 3." in result.output
    assert "Your result: 2 row(s) x 2 column(s). Expected: 3 row(s) x 2 column(s)." in result.output
    assert "Your result (2 row(s)):\nname | price\nStarter | 19.0\nPro | 49.0" in result.output


def test_failure_never_reveals_expected_values(task) -> None:
    env = started(task)
    result = prepared(task, env)(env)

    assert "Business" not in result.output and "129" not in result.output  # the row the agent is missing


def test_fixed_query_passes(task) -> None:
    env = started(task, {"solution.sql": GOLD.replace("ORDER BY plan_id", "")})  # any order is fine
    result = prepared(task, env)(env)

    assert result.passed and result.summary == "PASSED: all checks pass."
    assert "solution.sql returns the expected result on the visible database." in result.output


def test_sql_errors_are_reported(task) -> None:
    env = started(task, {"solution.sql": "SELECT nme FROM plans"})
    result = prepared(task, env)(env)

    assert not result.passed
    assert result.summary == "FAILED: solution.sql raised an error."
    assert result.output == "solution.sql failed to run: no such column: nme"


def test_modifying_statements_are_reported_as_errors(task) -> None:
    env = started(task, {"solution.sql": "DELETE FROM plans"})

    assert "read-only" in prepared(task, env)(env).output


def test_order_matters_only_when_the_task_says_so(tmp_path: Path) -> None:
    ordered = load_task(make_sql_task(tmp_path / "tasks", ORDERED_WRONG, GOLD, order_matters=True))
    env = started(ordered)
    result = prepared(ordered, env)(env)

    assert not result.passed
    assert "in the wrong order" in result.output and "rows must be in the order the question asks for" in result.output


def test_gold_query_runs_before_the_agent_and_once(task) -> None:
    env = started(task)
    check = prepared(task, env)
    check(env)
    check(env)

    gold_runs = [c for c in env.commands if "--sql" in c]
    assert len(gold_runs) == 1 and env.commands[0] is gold_runs[0]


def test_broken_gold_query_is_a_task_error(tmp_path: Path) -> None:
    task = load_task(make_sql_task(tmp_path / "tasks", BROKEN, "SELECT oops FROM plans"))

    with pytest.raises(SqlJudgeError, match="gold query fails on the visible database: no such column: oops"):
        SqlCheck(task).prepare(started(task))


def test_check_needs_prepare(task) -> None:
    with pytest.raises(SqlJudgeError, match="prepare"):
        SqlCheck(task)(started(task))


def test_run_checks_tool_uses_the_sql_check(task) -> None:
    env = started(task)
    check = prepared(task, env)

    outcome = execute_tool(env, ToolCall("1", "run_checks", {}), check=check)

    assert outcome.output.startswith("FAILED: solution.sql runs, but its result is not the expected one.\nYour result doesn't match")
    assert env.check_runs == 0  # never the pytest command


def test_agent_can_explore_with_the_runner_through_run_command(task) -> None:
    env = started(task)

    outcome = execute_tool(env, ToolCall("1", "run_command", {"command": f'python -I {SUPPORT_DIR}/run_query.py --sql "SELECT count(*) AS n FROM plans"'}))

    assert outcome.output.startswith("Exit code: 0") and '"rows": [\n  [6]\n]' in outcome.output


def test_preview_is_capped() -> None:
    text = preview(QueryResult(["n", "note"], [[i, None if i % 2 else "x" * 60] for i in range(25)]))

    assert text.startswith("Your result (first 10 of 25 rows):\nn | note\n0 | " + "x" * 37 + "...\n1 | NULL")
    assert text.count("\n") == 11


def test_sql_tool_descriptions() -> None:
    tools = {t.name: t for t in tool_definitions("docker", "sql")}

    assert "never the expected values" in tools["run_checks"].description
    assert "/akeso/run_query.py" in tools["run_command"].description
    assert "/akeso" not in {t.name: t for t in tool_definitions("docker")}["run_command"].description
