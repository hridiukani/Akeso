"""Test doubles: an in-memory Environment, so tool and agent tests need no disk, Docker or network."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from types import TracebackType

from repair_agent.checks import CheckResult
from repair_agent.environment import ExecResult
from repair_agent.paths import UnsafePathError, is_excluded_task_file, safe_relative_path

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
    ) -> None:
        self.checks = checks
        self.on_exec = on_exec or (lambda env, cmd: ExecResult(0, ""))
        self.raise_on = raise_on or {}
        self.files: dict[str, str] = {}
        self.started = False
        self.stopped = False
        self.check_runs = 0

    def start(self, task_dir: str | Path) -> None:
        self._maybe_raise("start")
        root = Path(task_dir)
        for path in root.rglob("*"):
            rel = path.relative_to(root).as_posix()
            if path.is_file() and not is_excluded_task_file(rel):
                self.files[rel] = path.read_text(encoding="utf-8")
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

    def run_checks(self, timeout: float = 60) -> CheckResult:
        self._maybe_raise("run_checks")
        self.check_runs += 1
        passed, output = self.checks(dict(self.files))
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
