"""The Environment interface: everywhere a run can read, edit and test task files.

Two implementations: LocalWorkspace (a temp copy on this machine) and DockerSandbox
(a locked-down container). The rest of the code only uses this interface, so it never
needs to know which one it's talking to.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # avoid an import cycle: checks.py imports this module
    from akeso.checks import CheckResult


class EnvError(Exception):
    """An environment operation failed (e.g. reading through a link)."""


class FileTooLargeError(EnvError):
    """A file is bigger than the environment's max_file_bytes limit."""


@dataclass(frozen=True)
class ExecResult:
    """Outcome of one command run inside an environment."""

    exit_code: int | None  # None when the command was killed by the timeout
    output: str  # stdout and stderr combined


class Environment(Protocol):
    """A place holding a copy of one task, where files can be changed and tests run.

    All paths are relative to the task root and checked with paths.safe_relative_path.
    Use as a context manager so the environment is always cleaned up.
    """

    kind: str  # short name recorded in results, e.g. "docker" or "local"
    check_command: list[str]  # how run_checks runs the tests; set from the task's check_command

    def start(self, task_dir: str | Path, private_dirs: Sequence[str] = ()) -> None:
        """Copy the task into the environment, leaving out private_dirs (hidden tests,
        solution) and everything paths.is_excluded_task_file excludes. The original task
        folder is never modified."""
        ...

    def stop(self) -> None:
        """Delete the environment and everything in it. Safe to call more than once."""
        ...

    def read_file(self, path: str) -> str: ...

    def write_file(self, path: str, content: str) -> None: ...

    def delete_file(self, path: str) -> None:
        """Delete a file. Deleting a file that doesn't exist does nothing; folders are refused."""
        ...

    def list_files(self, path: str = ".") -> list[str]:
        """Every file under path, relative to the task root, sorted."""
        ...

    def exec(self, cmd: str | Sequence[str], timeout: float) -> ExecResult:
        """Run a command in the task root; kill it after `timeout` seconds."""
        ...

    def run_checks(self, timeout: float = ..., command: Sequence[str] | None = None) -> CheckResult:
        """Run the task's tests (check_command unless another command is given)."""
        ...

    def __enter__(self) -> Environment: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...
