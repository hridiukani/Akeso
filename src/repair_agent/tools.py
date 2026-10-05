"""The tools the model can call, and the definitions (descriptions + JSON schemas) it reads.

Each tool takes an Environment first (where the task lives), then the arguments the
model supplies. Mistakes the model can fix (text not found, bad path, missing file)
come back as ToolResult(is_error=True) with a message saying exactly what went wrong,
so the model can correct itself. Infrastructure failures (e.g. Docker dying) raise.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

from jsonschema import Draft202012Validator, ValidationError

from repair_agent.checks import CHECK_TIMEOUT_SECONDS, trim_output
from repair_agent.environment import EnvError, Environment
from repair_agent.llm.types import ToolCall, ToolDefinition
from repair_agent.paths import UnsafePathError, safe_relative_path
from repair_agent.sandbox import SandboxError

COMMAND_TIMEOUT_SECONDS = 60
OUTPUT_LIMIT = 6000  # characters of command/test output returned to the model (the end is kept)
READ_LIMIT = 20000  # characters of a file returned by read_file (the start is kept)
# The tests are the judge: the model must not be able to rewrite them with apply_edit.
PROTECTED_FOLDER = "tests"


@dataclass(frozen=True)
class ToolResult:
    """What a tool call returns to the model."""

    output: str
    is_error: bool = False  # True when the call was invalid and the model should correct it


def error(message: str) -> ToolResult:
    return ToolResult(f"Error: {message}", is_error=True)


# --- read_file ---


def read_file(env: Environment, path: str) -> ToolResult:
    """Return a file's contents, or the list of files if path is a folder."""
    try:
        rel = safe_relative_path(path)
        if rel == PurePosixPath("."):
            return _list_folder(env, ".")
        content = env.read_file(rel.as_posix())
    except IsADirectoryError:
        return _list_folder(env, path)
    except FileNotFoundError:
        return error(f"{path!r} does not exist. Use read_file on '.' to list all files.")
    except (UnsafePathError, EnvError) as problem:  # includes FileTooLargeError
        return error(str(problem))

    if len(content) > READ_LIMIT:
        return ToolResult(
            content[:READ_LIMIT]
            + f"\n[... truncated: showing the first {READ_LIMIT} of {len(content)} characters]"
        )
    return ToolResult(content)


def _list_folder(env: Environment, path: str) -> ToolResult:
    try:
        files = env.list_files(path)
    except FileNotFoundError:
        return error(f"{path!r} does not exist. Use read_file on '.' to list all files.")
    if not files:
        return ToolResult(f"{path} is an empty folder.")
    return ToolResult(f"{path} is a folder containing {len(files)} file(s):\n" + "\n".join(files))


# --- apply_edit ---


def apply_edit(env: Environment, path: str, old_str: str, new_str: str) -> ToolResult:
    """Replace the single exact occurrence of old_str in the file with new_str."""
    try:
        rel = safe_relative_path(path)
    except UnsafePathError as problem:
        return error(str(problem))
    if rel.parts[:1] == (PROTECTED_FOLDER,):
        return error(f"files under {PROTECTED_FOLDER}/ are the judge and cannot be edited. Fix the code instead.")
    if not old_str:
        return error("old_str is empty. Copy the exact text to replace from the file (use read_file first).")
    if old_str == new_str:
        return error("old_str and new_str are identical, so nothing would change.")

    try:
        content = env.read_file(rel.as_posix())
    except FileNotFoundError:
        return error(f"{path!r} does not exist. Use read_file on '.' to list all files.")
    except IsADirectoryError:
        return error(f"{path!r} is a folder, not a file.")
    except (UnsafePathError, EnvError) as problem:
        return error(str(problem))

    # Files checked out on Windows can have \r\n line endings while the model writes \n.
    if "\r\n" in content and "\r\n" not in old_str:
        old_str, new_str = old_str.replace("\n", "\r\n"), new_str.replace("\n", "\r\n")

    count = content.count(old_str)
    if count == 0:
        return error(
            f"old_str was not found in {rel}. It must match the file exactly, including "
            "whitespace, indentation and blank lines. Use read_file to see the current contents."
        )
    if count > 1:
        return error(
            f"old_str was found {count} times in {rel}; it must appear exactly once. "
            "Include more surrounding lines in old_str to make it unique."
        )

    start_line = content[: content.index(old_str)].count("\n") + 1
    try:
        env.write_file(rel.as_posix(), content.replace(old_str, new_str, 1))
    except EnvError as problem:  # e.g. FileTooLargeError
        return error(str(problem))
    return ToolResult(f"Edited {rel}: replaced 1 occurrence starting at line {start_line}.")


# --- run_command ---


def run_command(env: Environment, command: str, timeout: float = COMMAND_TIMEOUT_SECONDS) -> ToolResult:
    """Run a shell command in the task folder and report its exit code and output."""
    if not command.strip():
        return error("command is empty.")
    result = env.exec(command, timeout=timeout)
    output = trim_output(result.output, OUTPUT_LIMIT) if result.output else "(no output)"
    if result.exit_code is None:
        return ToolResult(f"Command timed out after {timeout:g} seconds and was killed.\n{output}")
    return ToolResult(f"Exit code: {result.exit_code}\n{output}")


# --- run_checks ---


def run_checks(env: Environment, timeout: float = CHECK_TIMEOUT_SECONDS) -> ToolResult:
    """Run the task's tests and report pass/fail with the (trimmed) test output."""
    result = env.run_checks(timeout=timeout)
    output = trim_output(result.output, OUTPUT_LIMIT)
    if result.passed:
        status = "PASSED: all checks pass."
    elif result.exit_code is None:
        status = f"FAILED: the checks timed out after {timeout:g} seconds."
    else:
        status = f"FAILED: pytest exited with code {result.exit_code}."
    return ToolResult(f"{status}\n{output}")


# --- definitions the model reads ---

READ_FILE_TOOL = ToolDefinition(
    name="read_file",
    description=(
        "Read a file in the project and return its exact contents. If the path is a folder, "
        "returns the list of files inside it instead (use '.' to list every file in the project). "
        "Paths are relative to the project root, e.g. 'src/stats.py'. Always read a file before "
        "editing it, so you can copy text exactly. Very long files are truncated."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path of a file or folder, e.g. 'src/stats.py' or '.'.",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    },
)

APPLY_EDIT_TOOL = ToolDefinition(
    name="apply_edit",
    description=(
        "Edit a file by replacing one exact piece of text with new text. old_str must match the "
        "file character for character, including indentation, spaces and line breaks, and must "
        "appear exactly once in the file; include a few surrounding lines if needed to make it "
        "unique. The edit is refused (and nothing changes) if old_str is not found or is found "
        "more than once; the error says which. Use read_file first to copy the text exactly. "
        "Files under tests/ cannot be edited: the tests define correct behaviour."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path of the file to edit, e.g. 'src/stats.py'."},
            "old_str": {
                "type": "string",
                "description": "The exact existing text to replace. Must occur exactly once in the file.",
            },
            "new_str": {
                "type": "string",
                "description": "The text to put in its place. Use an empty string to delete old_str.",
            },
        },
        "required": ["path", "old_str", "new_str"],
        "additionalProperties": False,
    },
)

RUN_COMMAND_TOOL = ToolDefinition(
    name="run_command",
    description=(
        "Run a shell command in the project root inside an isolated sandbox and return its exit "
        f"code and output (the end of long output is kept). Commands are killed after "
        f"{COMMAND_TIMEOUT_SECONDS} seconds. There is no network access, so installing packages "
        "will fail. Use it to inspect the project or run Python, e.g. "
        "'python -c \"from stats import mean; print(mean([1, 2]))\"'. To run the task's tests, "
        "use run_checks instead."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The shell command to run, e.g. 'python -m pytest -q tests/test_stats.py'."},
        },
        "required": ["command"],
        "additionalProperties": False,
    },
)

RUN_CHECKS_TOOL = ToolDefinition(
    name="run_checks",
    description=(
        "Run the task's test suite and report PASSED or FAILED with the test output (the end is "
        "kept, where the failures and summary are). The task is solved only when this reports "
        "PASSED. Run it after each edit to see whether your fix works and what still fails."
    ),
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
)

TOOL_DEFINITIONS = [READ_FILE_TOOL, APPLY_EDIT_TOOL, RUN_COMMAND_TOOL, RUN_CHECKS_TOOL]


# --- executing a model's tool call ---

# name -> (definition, function). Each function takes (env, **arguments).
_REGISTRY: dict[str, tuple[ToolDefinition, Callable[..., ToolResult]]] = {
    READ_FILE_TOOL.name: (READ_FILE_TOOL, read_file),
    APPLY_EDIT_TOOL.name: (APPLY_EDIT_TOOL, apply_edit),
    RUN_COMMAND_TOOL.name: (RUN_COMMAND_TOOL, run_command),
    RUN_CHECKS_TOOL.name: (RUN_CHECKS_TOOL, run_checks),
}


def execute_tool(env: Environment, tool_call: ToolCall) -> ToolResult:
    """Run one tool call from the model. Never raises: every problem becomes an error result.

    Unknown tools and arguments that don't match the tool's JSON schema are rejected
    with a message saying what was wrong, so the model can correct itself.
    """
    entry = _REGISTRY.get(tool_call.name)
    if entry is None:
        return error(
            f"unknown tool {tool_call.name!r}. Available tools: {', '.join(sorted(_REGISTRY))}."
        )
    definition, function = entry

    problems = sorted(
        Draft202012Validator(definition.input_schema).iter_errors(tool_call.arguments),
        key=lambda e: list(e.path),
    )
    if problems:
        details = "; ".join(_describe(problem) for problem in problems)
        expected = ", ".join(
            f"{name}{'' if name in definition.input_schema.get('required', []) else ' (optional)'}"
            for name in definition.input_schema.get("properties", {})
        ) or "no arguments"
        return error(f"invalid arguments for {tool_call.name}: {details}. Expected: {expected}.")

    try:
        return function(env, **tool_call.arguments)
    except SandboxError as problem:
        return error(f"the sandbox failed while running {tool_call.name}: {problem}")
    except Exception as problem:  # a bad tool call must never crash the agent
        return error(f"{tool_call.name} failed unexpectedly: {type(problem).__name__}: {problem}")


def _describe(problem: ValidationError) -> str:
    """One readable line per schema violation, naming the argument when there is one."""
    where = ".".join(str(part) for part in problem.path)
    return f"{where}: {problem.message}" if where else problem.message
