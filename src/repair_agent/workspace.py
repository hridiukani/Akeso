"""Disposable copies of task folders, so the agent never touches the originals."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from types import TracebackType

from repair_agent.checks import CHECK_TIMEOUT_SECONDS, CheckResult, run_checks
from repair_agent.environment import EnvError, ExecResult, FileTooLargeError
from repair_agent.paths import UnsafePathError, is_excluded_task_file, safe_relative_path

WORKSPACE_PREFIX = "repair-agent-"


def _ignore_excluded(directory: str, names: list[str]) -> set[str]:
    """copytree callback: skip the same files the sandbox skips (secrets, .git, caches)."""
    return {name for name in names if is_excluded_task_file(name)}


# The only parent variables local task code may see. Everything else (API keys, tokens,
# personal settings) is left out. PATH lets tests find programs; SYSTEMROOT is required
# for Python to start on Windows; TEMP/TMP let pytest's tmp_path work.
_PASSTHROUGH_ENV_VARS = ("PATH", "SYSTEMROOT", "TEMP", "TMP")


def minimal_env() -> dict[str, str]:
    """Environment for local task code: an allowlist of parent variables plus fixed settings.

    An allowlist (not a blocklist) means a new secret added to the parent environment
    is hidden by default.
    """
    env = {name: os.environ[name] for name in _PASSTHROUGH_ENV_VARS if name in os.environ}
    env["PYTHONIOENCODING"] = "utf-8"  # matches how we decode the output
    env["PYTHONDONTWRITEBYTECODE"] = "1"  # keep __pycache__ out of the workspace
    return env


def create_workspace(task_dir: str | Path) -> Path:
    """Copy task_dir into a new temporary directory and return that directory's path.

    The copy is independent: editing files in it never changes task_dir.
    """
    source = Path(task_dir).resolve()
    if not source.is_dir():
        raise NotADirectoryError(f"Task folder not found: {source}")

    workspace = Path(tempfile.mkdtemp(prefix=WORKSPACE_PREFIX))
    # symlinks=False copies the files a link points to rather than the link itself,
    # so edits in the workspace can never write through a link into the original.
    shutil.copytree(source, workspace, symlinks=False, ignore=_ignore_excluded, dirs_exist_ok=True)
    return workspace


def cleanup_workspace(workspace: str | Path) -> None:
    """Delete a workspace made by create_workspace. Safe to call twice.

    Refuses any other path, so a bug can never delete a task folder or the repo.
    """
    path = Path(workspace).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if path.parent != temp_root or not path.name.startswith(WORKSPACE_PREFIX):
        raise ValueError(f"Refusing to delete {path}: not a repair-agent workspace.")
    if path.exists():
        shutil.rmtree(path)


class LocalWorkspace:
    """Environment backed by a temporary copy of the task on this machine.

    Only environment variables are hidden from task code here: it can still read your
    files and use the network. Prefer DockerSandbox; this is for quick runs or machines
    without Docker.
    """

    kind = "local"

    def __init__(self, max_file_bytes: int = 1_000_000) -> None:
        self.max_file_bytes = max_file_bytes
        self.root: Path | None = None

    def start(self, task_dir: str | Path) -> None:
        if self.root is not None:
            raise EnvError("Workspace already started; call stop() first.")
        self.root = create_workspace(task_dir)

    def stop(self) -> None:
        if self.root is None:
            return
        try:
            cleanup_workspace(self.root)
        finally:
            self.root = None

    def read_file(self, path: str) -> str:
        rel, target = self._resolve(path)
        if target.is_symlink():
            raise EnvError(f"{rel} is a link; reading through links is not allowed.")
        if not target.exists():
            raise FileNotFoundError(f"{rel} does not exist in the workspace.")
        if target.is_dir():
            raise IsADirectoryError(f"{rel} is a directory, not a file.")
        size = target.stat().st_size
        if size > self.max_file_bytes:
            raise FileTooLargeError(f"{rel} is {size} bytes; the limit is {self.max_file_bytes} bytes.")
        # Bytes, not read_text, so line endings come back exactly as stored (like Docker).
        return target.read_bytes().decode("utf-8", errors="replace")

    def write_file(self, path: str, content: str) -> None:
        data = content.encode("utf-8")
        if len(data) > self.max_file_bytes:
            raise FileTooLargeError(
                f"Refusing to write {len(data)} bytes to {path}; the limit is {self.max_file_bytes} bytes."
            )
        _, target = self._resolve(path)
        if target.is_symlink():
            target.unlink()  # replace the link itself; never write through it
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def delete_file(self, path: str) -> None:
        rel, target = self._resolve(path)
        if target.is_symlink() or target.is_file():
            target.unlink()  # a link is removed itself, never its target
        elif target.is_dir():
            raise IsADirectoryError(f"{rel} is a directory, not a file.")

    def list_files(self, path: str = ".") -> list[str]:
        rel, base = self._resolve(path, allow_root=True)
        if not base.exists():
            raise FileNotFoundError(f"{rel} does not exist in the workspace.")
        root = self._require_started()
        candidates = [base] if base.is_file() else base.rglob("*")
        # Regular files only (not links), matching `find -type f` in the sandbox.
        return sorted(
            p.relative_to(root).as_posix() for p in candidates if p.is_file() and not p.is_symlink()
        )

    def exec(self, cmd: str | Sequence[str], timeout: float) -> ExecResult:
        """Run cmd in the workspace with a minimal environment.

        A list runs directly; "python" as the first item means this interpreter, which
        has pytest installed (as "python" does in the Docker image). A string runs
        through the system shell.
        """
        root = self._require_started()
        if isinstance(cmd, str):
            args: str | list[str] = cmd
        else:
            args = list(cmd)
            if args and args[0] == "python":
                args[0] = sys.executable
        try:
            completed = subprocess.run(
                args,
                shell=isinstance(args, str),
                cwd=root,
                env=minimal_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            partial = error.output or ""
            if isinstance(partial, bytes):  # TimeoutExpired can hold bytes even when text=True
                partial = partial.decode("utf-8", errors="replace")
            return ExecResult(None, f"{partial}\n[command timed out after {timeout:g} seconds]")
        return ExecResult(completed.returncode, completed.stdout)

    def run_checks(self, timeout: float = CHECK_TIMEOUT_SECONDS) -> CheckResult:
        return run_checks(self, timeout)

    def _require_started(self) -> Path:
        if self.root is None:
            raise EnvError("Workspace not started; call start() first.")
        return self.root

    def _resolve(self, path: str, allow_root: bool = False) -> tuple[PurePosixPath, Path]:
        """Check path with the shared rules, then confirm it stays inside the workspace."""
        rel = safe_relative_path(path)
        if rel == PurePosixPath(".") and not allow_root:
            raise UnsafePathError(f"path {path!r} refers to the workspace itself, not a file.")
        root = self._require_started()
        target = root / rel
        # Second line of defence: a link in a parent folder must not lead outside.
        # (For "." the target is the root itself, so check it rather than its parent.)
        container = target if rel == PurePosixPath(".") else target.parent
        if not container.resolve().is_relative_to(root.resolve()):
            raise UnsafePathError(f"path {path!r} leads outside the workspace.")
        return rel, target

    def __enter__(self) -> LocalWorkspace:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()
