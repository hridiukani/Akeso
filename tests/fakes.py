"""Test doubles: an in-memory Environment and a scripted Provider, so tests need no Docker or network."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from types import TracebackType

from akeso.checks import CheckResult
from akeso.environment import ExecResult
from akeso.llm.types import Message, ModelResponse, ToolCall, ToolDefinition, Usage
from akeso.paths import UnsafePathError, is_excluded_task_file, safe_relative_path

# Decides the result of run_checks from the current files: returns (passed, output).
ChecksRule = Callable[[dict[str, str]], tuple[bool, str]]


def always_failing(files: dict[str, str]) -> tuple[bool, str]:
    return False, "F\nFAILED tests/test_x.py::test_x - assert 1 == 2\n1 failed in 0.01s"


class FakeEnvironment:
    """Implements the Environment protocol with a dict of files.

    start() loads the real files of task_dir (so judge-restore code can compare against
    them). run_checks() is decided by `checks`, exec() by `on_exec`. `raise_on` makes a
    named method raise an exception, to test error handling.
    """

    kind = "fake"

    def __init__(
        self,
        checks: ChecksRule = always_failing,
        on_exec: Callable[[FakeEnvironment, str | Sequence[str]], ExecResult] | None = None,
        raise_on: dict[str, Exception] | None = None,
        hidden_checks: ChecksRule | None = None,
    ) -> None:
        self.checks = checks
        self.hidden_checks = hidden_checks or checks
        self.check_command = ["python", "-m", "pytest"]
        self.commands_run: list[list[str]] = []  # every check command, to see what grading ran
        self.on_exec = on_exec or (lambda env, cmd: ExecResult(0, ""))
        self.raise_on = raise_on or {}
        self.files: dict[str, str] = {}
        self.started = False
        self.stopped = False
        self.check_runs = 0

    def start(self, task_dir: str | Path, private_dirs: Sequence[str] = ()) -> None:
        self._maybe_raise("start")
        root = Path(task_dir)
        for path in root.rglob("*"):
            rel = path.relative_to(root).as_posix()
            if path.is_file() and not is_excluded_task_file(rel, private_dirs):
                # Bytes, not read_text: keep \r\n exactly, like the real environments do.
                self.files[rel] = path.read_bytes().decode("utf-8")
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def read_file(self, path: str) -> str:
        self._maybe_raise("read_file")
        rel = self._file(path)
        if rel in self.files:
            return self.files[rel]
        if any(name.startswith(rel + "/") for name in self.files):
            raise IsADirectoryError(f"{rel} is a directory, not a file.")
        raise FileNotFoundError(f"{rel} does not exist.")

    def write_file(self, path: str, content: str) -> None:
        self._maybe_raise("write_file")
        self.files[self._file(path)] = content

    def delete_file(self, path: str) -> None:
        self._maybe_raise("delete_file")
        self.files.pop(self._file(path), None)

    def list_files(self, path: str = ".") -> list[str]:
        self._maybe_raise("list_files")
        rel = safe_relative_path(path).as_posix()
        if rel == ".":
            return sorted(self.files)
        found = sorted(name for name in self.files if name == rel or name.startswith(rel + "/"))
        if not found:
            raise FileNotFoundError(f"{rel} does not exist.")
        return found

    def exec(self, cmd: str | Sequence[str], timeout: float) -> ExecResult:
        self._maybe_raise("exec")
        return self.on_exec(self, cmd)

    def run_checks(self, timeout: float = 60, command: Sequence[str] | None = None) -> CheckResult:
        self._maybe_raise("run_checks")
        self.check_runs += 1
        command = list(command or self.check_command)
        self.commands_run.append(command)
        # A command other than the normal one is the hidden-test run during grading.
        rule = self.checks if command == self.check_command else self.hidden_checks
        passed, output = rule(dict(self.files))
        return CheckResult(passed, 0 if passed else 1, output, 0.01)

    def _file(self, path: str) -> str:
        rel = safe_relative_path(path)
        if rel == PurePosixPath("."):
            raise UnsafePathError(f"path {path!r} refers to the workspace itself, not a file.")
        return rel.as_posix()

    def _maybe_raise(self, method: str) -> None:
        if method in self.raise_on:
            raise self.raise_on[method]

    def __enter__(self) -> FakeEnvironment:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()


class ScriptedProvider:
    """Implements the Provider protocol by replaying a fixed list of responses in order.

    Records every conversation it was sent, so tests can check what the model saw.
    Running out of responses raises, which the agent records as an error.
    """

    def __init__(self, responses: Sequence[ModelResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[list[Message]] = []
        self.tools: list[list[ToolDefinition]] = []  # the tool definitions sent with each call

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] | None = None,
    ) -> ModelResponse:
        self.calls.append(list(messages))
        self.tools.append(list(tools or []))
        if len(self.calls) > len(self.responses):
            raise RuntimeError("ScriptedProvider ran out of responses")
        return self.responses[len(self.calls) - 1]


def tool_reply(*calls: tuple[str, dict], text: str = "", usage: Usage = Usage(100, 20)) -> ModelResponse:
    """A model reply that calls the given tools: tool_reply(("read_file", {"path": "a"}))."""
    tool_calls = [ToolCall(f"call_{index}", name, args) for index, (name, args) in enumerate(calls)]
    return ModelResponse(text=text, tool_calls=tool_calls, usage=usage, stop_reason="tool_use")


def text_reply(text: str, usage: Usage = Usage(100, 20)) -> ModelResponse:
    """A model reply with no tool calls (the model is done, or giving up)."""
    return ModelResponse(text=text, usage=usage, stop_reason="end_turn")
