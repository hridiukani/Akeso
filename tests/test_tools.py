"""Tests for the model's tools. Each tool test runs in LocalWorkspace and DockerSandbox."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from repair_agent import tools
from repair_agent.environment import Environment
from repair_agent.sandbox import DockerSandbox
from repair_agent.workspace import LocalWorkspace

BUGGY = '''def mean(numbers):
    """Average of numbers."""
    total = sum(numbers)
    return total / (len(numbers) - 1)
'''
TESTS = "from stats import mean\n\ndef test_mean():\n    assert mean([2, 4, 6]) == 4\n"


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    task = tmp_path / "task"
    (task / "src").mkdir(parents=True)
    (task / "tests").mkdir()
    (task / "src" / "stats.py").write_text(BUGGY, newline="\n")
    (task / "tests" / "test_stats.py").write_text(TESTS, newline="\n")
    (task / "pytest.ini").write_text("[pytest]\npythonpath = src\n", newline="\n")
    return task


@pytest.fixture(params=["local", pytest.param("docker", marks=pytest.mark.docker)])
def env(request: pytest.FixtureRequest, task_dir: Path) -> Iterator[Environment]:
    environment: Environment = LocalWorkspace() if request.param == "local" else DockerSandbox()
    with environment:
        environment.start(task_dir)
        yield environment


# --- read_file ---


def test_read_file_returns_exact_contents(env: Environment) -> None:
    result = tools.read_file(env, "src/stats.py")

    assert not result.is_error
    assert result.output == BUGGY


def test_read_file_on_folder_lists_files(env: Environment) -> None:
    assert tools.read_file(env, "src").output == "src is a folder containing 1 file(s):\nsrc/stats.py"
    everything = tools.read_file(env, ".").output
    assert everything.splitlines()[1:] == ["pytest.ini", "src/stats.py", "tests/test_stats.py"]


@pytest.mark.parametrize(("path", "message"), [("src/missing.py", "does not exist"), ("../outside.py", "'..'"), ("/etc/passwd", "absolute")])
def test_read_file_errors(env: Environment, path: str, message: str) -> None:
    result = tools.read_file(env, path)

    assert result.is_error
    assert result.output.startswith("Error:")
    assert message in result.output


def test_read_file_truncates_long_files(env: Environment) -> None:
    env.write_file("src/big.py", "x" * (tools.READ_LIMIT + 500))

    result = tools.read_file(env, "src/big.py")

    assert not result.is_error
    assert "truncated" in result.output
    assert len(result.output) < tools.READ_LIMIT + 200


# --- apply_edit ---


def test_apply_edit_replaces_unique_text(env: Environment) -> None:
    result = tools.apply_edit(env, "src/stats.py", "(len(numbers) - 1)", "len(numbers)")

    assert not result.is_error
    assert result.output == "Edited src/stats.py: replaced 1 occurrence starting at line 4."
    assert env.read_file("src/stats.py") == BUGGY.replace("(len(numbers) - 1)", "len(numbers)")


def test_apply_edit_not_found_changes_nothing(env: Environment) -> None:
    result = tools.apply_edit(env, "src/stats.py", "len(numbers)-1", "len(numbers)")  # spacing differs

    assert result.is_error
    assert "was not found in src/stats.py" in result.output
    assert "exactly" in result.output
    assert env.read_file("src/stats.py") == BUGGY


def test_apply_edit_found_several_times_changes_nothing(env: Environment) -> None:
    result = tools.apply_edit(env, "src/stats.py", "numbers", "values")

    assert result.is_error
    assert "found 4 times" in result.output  # signature, docstring, sum(...), len(...)
    assert "exactly once" in result.output
    assert env.read_file("src/stats.py") == BUGGY


def test_apply_edit_can_delete_text(env: Environment) -> None:
    result = tools.apply_edit(env, "src/stats.py", '    """Average of numbers."""\n', "")

    assert not result.is_error
    assert '"""' not in env.read_file("src/stats.py")


def test_apply_edit_handles_windows_line_endings(env: Environment) -> None:
    env.write_file("src/crlf.py", "a = 1\r\nb = 2\r\n")

    result = tools.apply_edit(env, "src/crlf.py", "a = 1\nb = 2", "a = 10\nb = 20")

    assert not result.is_error, result.output
    assert env.read_file("src/crlf.py") == "a = 10\r\nb = 20\r\n"  # line endings preserved


@pytest.mark.parametrize(
    ("path", "old_str", "new_str", "message"),
    [
        ("tests/test_stats.py", "assert", "pass", "cannot be edited"),
        ("src/stats.py", "", "x", "old_str is empty"),
        ("src/stats.py", "total", "total", "identical"),
        ("src/missing.py", "a", "b", "does not exist"),
        ("src", "a", "b", "is a folder"),
        ("../outside.py", "a", "b", "'..'"),
        ("/etc/passwd", "a", "b", "absolute"),
    ],
)
def test_apply_edit_refusals(env: Environment, path: str, old_str: str, new_str: str, message: str) -> None:
    result = tools.apply_edit(env, path, old_str, new_str)

    assert result.is_error
    assert message in result.output
    assert env.read_file("src/stats.py") == BUGGY
    assert env.read_file("tests/test_stats.py") == TESTS


# --- run_command ---


def test_run_command_reports_exit_code_and_output(env: Environment) -> None:
    result = tools.run_command(env, "python -c \"import sys; print('hello'); sys.exit(3)\"")

    assert not result.is_error
    assert result.output.splitlines()[0] == "Exit code: 3"
    assert "hello" in result.output


def test_run_command_timeout(env: Environment) -> None:
    result = tools.run_command(env, "python -c \"import time; time.sleep(30)\"", timeout=2)

    assert result.output.startswith("Command timed out after 2 seconds")


def test_run_command_trims_long_output(env: Environment) -> None:
    result = tools.run_command(env, "python -c \"print('x' * 20000 + 'END')\"")

    assert "characters trimmed" in result.output
    assert result.output.rstrip().endswith("END")  # the end is kept
    assert len(result.output) < tools.OUTPUT_LIMIT + 200


def test_run_command_rejects_empty_command(env: Environment) -> None:
    assert tools.run_command(env, "   ").is_error


# --- run_checks ---


def test_run_checks_fails_then_passes_after_edit(env: Environment) -> None:
    before = tools.run_checks(env)
    assert before.output.startswith("FAILED: pytest exited with code 1.")
    assert "assert 6.0 == 4" in before.output  # failure details reach the model

    tools.apply_edit(env, "src/stats.py", "(len(numbers) - 1)", "len(numbers)")
    after = tools.run_checks(env)

    assert after.output.startswith("PASSED")
    assert not after.is_error


# --- definitions (no environment needed) ---


def test_definitions_match_the_tools() -> None:
    names = [definition.name for definition in tools.TOOL_DEFINITIONS]

    assert names == ["read_file", "apply_edit", "run_command", "run_checks"]
    for name in names:
        assert callable(getattr(tools, name))


@pytest.mark.parametrize("definition", tools.TOOL_DEFINITIONS, ids=lambda d: d.name)
def test_definition_schemas_are_well_formed(definition) -> None:
    schema = definition.input_schema

    assert len(definition.description) > 80  # a real explanation, not a placeholder
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema.get("required", [])) <= set(schema["properties"])
    for prop in schema["properties"].values():
        assert prop["type"] == "string"
        assert prop["description"]
