"""A locked-down, disposable Docker container to run task code in.

The container gets a copy of the task files and nothing else from the host: no network,
no host folders, no host environment variables, and limited memory, CPU and processes.
"""

from __future__ import annotations

import io
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

import docker
from docker.errors import DockerException, ImageNotFound, NotFound
from docker.models.containers import Container

IMAGE = "repair-agent-code:latest"
WORKDIR = "/workspace"
USER = "agent"
USER_ID = 1000  # must match the uid created in docker/code.Dockerfile
# Lets us find (and clean up) our containers: docker ps -a --filter label=repair-agent
LABEL = {"repair-agent": "sandbox"}

# Exit codes from coreutils `timeout`: 124 after SIGTERM, 137 if it had to SIGKILL.
_TIMEOUT_EXIT_CODES = (124, 137)
_KILL_GRACE_SECONDS = 2
_SKIPPED_NAMES = {"__pycache__", ".pytest_cache"}


class SandboxError(Exception):
    """Docker isn't available, the image is missing, or the sandbox is used incorrectly."""


@dataclass(frozen=True)
class ExecResult:
    """Outcome of one command run inside the sandbox."""

    exit_code: int | None  # None when the command was killed by the timeout
    output: str  # stdout and stderr combined


class DockerSandbox:
    """Disposable container for one run. Use as a context manager so it's always removed:

        with DockerSandbox() as sandbox:
            sandbox.start("tasks/code/c001_mean")
            result = sandbox.exec("python -m pytest -q", timeout=60)
    """

    def __init__(
        self,
        image: str = IMAGE,
        memory: str = "512m",
        cpus: float = 1.0,
        pids_limit: int = 128,
    ) -> None:
        self.image = image
        self.memory = memory
        self.cpus = cpus
        self.pids_limit = pids_limit
        self.container: Container | None = None

    def start(self, task_dir: str | Path) -> None:
        """Create the container, copy the task files into /workspace, and start it."""
        if self.container is not None:
            raise SandboxError("Sandbox already started; call stop() first.")
        source = Path(task_dir).resolve()
        if not source.is_dir():
            raise SandboxError(f"Task folder not found: {source}")

        client = _connect()
        try:
            client.images.get(self.image)
        except ImageNotFound:
            raise SandboxError(
                f"Docker image {self.image!r} not found. Build it with: python scripts/build_images.py"
            ) from None

        self.container = client.containers.create(
            self.image,
            command=["sleep", "infinity"],  # keep the container alive; work happens via exec
            user=USER,
            working_dir=WORKDIR,
            labels=LABEL,
            network_mode="none",  # no network at all, only loopback
            mem_limit=self.memory,
            memswap_limit=self.memory,  # same as mem_limit, so no extra swap beyond it
            nano_cpus=int(self.cpus * 1_000_000_000),
            pids_limit=self.pids_limit,  # stops fork bombs
            # Deliberately no `volumes`/`mounts` (no host folders) and no `environment`
            # (the container only has the image's own variables, never the host's).
        )
        try:
            self.container.put_archive(WORKDIR, _tar_folder(source))
            self.container.start()
        except Exception:
            self.stop()  # don't leave a half-built container behind
            raise

    def exec(self, cmd: str | list[str], timeout: float) -> ExecResult:
        """Run cmd in /workspace as the non-root user, killing it after `timeout` seconds.

        A string runs through `sh -c`; a list runs as-is.
        """
        if self.container is None:
            raise SandboxError("Sandbox not started; call start() first.")
        argv = ["sh", "-c", cmd] if isinstance(cmd, str) else list(cmd)
        # docker exec has no timeout of its own, so wrap the command in coreutils `timeout`:
        # SIGTERM at the limit, then SIGKILL if it's still running a moment later.
        wrapped = ["timeout", "--kill-after", str(_KILL_GRACE_SECONDS), str(timeout), *argv]

        start = time.monotonic()
        exit_code, raw = self.container.exec_run(wrapped, user=USER, workdir=WORKDIR)
        elapsed = time.monotonic() - start
        output = raw.decode("utf-8", errors="replace") if raw else ""

        # Check elapsed time too, so a command that exits 124/137 on its own isn't misread.
        if exit_code in _TIMEOUT_EXIT_CODES and elapsed >= timeout:
            return ExecResult(None, f"{output}\n[command timed out after {timeout:g} seconds]")
        return ExecResult(exit_code, output)

    def stop(self) -> None:
        """Remove the container (killing it if running). Safe to call more than once."""
        if self.container is None:
            return
        try:
            self.container.remove(force=True)
        except NotFound:
            pass  # already gone
        finally:
            self.container = None

    def __enter__(self) -> DockerSandbox:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()


def _connect() -> docker.DockerClient:
    """Connect to the Docker engine, or fail with instructions."""
    try:
        client = docker.from_env()
        client.ping()
    except (DockerException, OSError) as error:  # OSError covers connection failures
        raise SandboxError(
            "Can't connect to Docker. Start Docker Desktop, wait until it says it's running, "
            "then try again."
        ) from error
    return client


def _tar_folder(folder: Path) -> bytes:
    """Pack folder's contents into an in-memory tar owned by the sandbox user.

    Ownership matters: put_archive keeps the tar's owner, and files owned by root
    would be read-only for the non-root user that edits them.
    """
    def as_sandbox_user(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        if _SKIPPED_NAMES.intersection(Path(info.name).parts) or info.name.endswith(".pyc"):
            return None
        info.uid = info.gid = USER_ID
        info.uname = info.gname = USER
        # Windows doesn't have Unix permissions, so set sensible ones explicitly.
        info.mode = 0o755 if info.isdir() else 0o644
        return info

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for child in sorted(folder.iterdir()):
            archive.add(child, arcname=child.name, filter=as_sandbox_user)
    return buffer.getvalue()
