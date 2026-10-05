"""Tests for execute_tool: lookup, schema validation, and turning every failure into an error result."""

from pathlib import Path
from typing import Any

import pytest

from fakes import FakeEnvironment
from akeso.llm.types import ToolCall
from akeso.sandbox import SandboxError
from akeso.tools import execute_tool


@pytest.fixture
def env(tmp_path: Path) -> FakeEnvironment:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "stats.py").write_text("def mean(n):\n    return sum(n) / (len(n) - 1)\n", newline="\n")
    fake = FakeEnvironment()
    fake.start(tmp_path)
    return fake


def call(name: str, arguments: Any) -> ToolCall:
    return ToolCall(id="call_1", name=name, arguments=arguments)


def test_valid_call_runs_the_tool(env: FakeEnvironment) -> None:
    result = execute_tool(env, call("read_file", {"path": "src/stats.py"}))

    assert not result.is_error
    assert "def mean" in result.output


def test_valid_edit_changes_the_file(env: FakeEnvironment) -> None:
    result = execute_tool(env, call("apply_edit", {"path": "src/stats.py", "old_str": "(len(n) - 1)", "new_str": "len(n)"}))

    assert not result.is_error
    assert "len(n)\n" in env.files["src/stats.py"]


def test_unknown_tool_lists_available_tools(env: FakeEnvironment) -> None:
    result = execute_tool(env, call("delete_everything", {}))

    assert result.is_error
    assert "unknown tool 'delete_everything'" in result.output
    assert "apply_edit, read_file, run_checks, run_command" in result.output


@pytest.mark.parametrize(
    ("name", "arguments", "expected"),
    [
        ("apply_edit", {"path": "src/stats.py"}, "'old_str' is a required property"),
        ("read_file", {"path": 5}, "path: 5 is not of type 'string'"),
        ("read_file", {"path": "a", "mode": "w"}, "('mode' was unexpected)"),
        ("run_checks", {"verbose": True}, "('verbose' was unexpected)"),
        ("run_command", {}, "'command' is a required property"),
        ("read_file", ["src/stats.py"], "is not of type 'object'"),
    ],
)
def test_invalid_arguments_are_explained(env: FakeEnvironment, name: str, arguments: Any, expected: str) -> None:
    result = execute_tool(env, call(name, arguments))

    assert result.is_error
    assert f"invalid arguments for {name}" in result.output
    assert expected in result.output
    assert "Expected:" in result.output  # tells the model what the right arguments are


def test_invalid_arguments_never_reach_the_tool(env: FakeEnvironment) -> None:
    before = dict(env.files)

    execute_tool(env, call("apply_edit", {"path": "src/stats.py", "old_str": "sum", "new_str": 1}))

    assert env.files == before


def test_sandbox_error_becomes_error_result(env: FakeEnvironment) -> None:
    env.raise_on["run_checks"] = SandboxError("Can't connect to Docker.")

    result = execute_tool(env, call("run_checks", {}))

    assert result.is_error
    assert "the sandbox failed while running run_checks: Can't connect to Docker." in result.output


def test_unexpected_exception_becomes_error_result(env: FakeEnvironment) -> None:
    env.raise_on["exec"] = RuntimeError("disk on fire")

    result = execute_tool(env, call("run_command", {"command": "ls"}))

    assert result.is_error
    assert "run_command failed unexpectedly: RuntimeError: disk on fire" in result.output


@pytest.mark.parametrize(
    "tool_call",
    [
        call("", {}),
        call("read_file", None),
        call("read_file", {"path": None}),
        call("apply_edit", {"path": "../../etc/passwd", "old_str": "a", "new_str": "b"}),
        call("run_command", {"command": "x" * 100_000}),
    ],
)
def test_bad_calls_never_raise(env: FakeEnvironment, tool_call: ToolCall) -> None:
    result = execute_tool(env, tool_call)  # must return, whatever the input

    assert isinstance(result.output, str)
