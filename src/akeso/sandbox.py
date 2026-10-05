"""A locked-down, disposable Docker container to run task code in.

The container gets a copy of the task files and nothing else from the host: no network,
no host folders, no host environment variables, and limited memory, CPU and processes.
"""

from __future__ import annotations

import io
import tarfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from types import TracebackType

import docker
from docker.errors import DockerException, ImageNotFound, NotFound
from docker.models.containers import Container

from akeso.checks import CHECK_TIMEOUT_SECONDS, CheckResult, run_checks
from akeso.environment import EnvError, ExecResult, FileTooLargeError
from akeso.paths import UnsafePathError, is_excluded_task_file, safe_relative_path

__all__ = ["DockerSandbox", "ExecResult", "FileTooLargeError", "SandboxError"]

IMAGE = "repair-agent-code:latest"
WORKDIR = "/workspace"
USER = "agent"
USER_ID = 1000  # must match the uid created in docker/code.Dockerfile
# Lets us find (and clean up) our containers: docker ps -a --filter label=repair-agent
LABEL = {"repair-agent": "sandbox"}
# Labelled containers older than this are leftovers from crashed runs (no run lasts this long).
LEFTOVER_MAX_AGE = timedelta(hours=1)

# Exit codes from coreutils `timeout`: 124 after SIGTERM, 137 if it had to SIGKILL.
_TIMEOUT_EXIT_CODES = (124, 137)
_KILL_GRACE_SECONDS = 2


class SandboxError(EnvError):
    """Docker isn't available, the image is missing, or the sandbox is used incorrectly."""


class DockerSandbox:
    """Disposable container for one run. Use as a context manager so it's always removed:

        with DockerSandbox() as sandbox:
            sandbox.start("tasks/code/c001_mean")
            result = sandbox.exec("python -m pytest -q", timeout=60)
    """

    kind = "docker"

    def __init__(
        self,
        image: str = IMAGE,
        memory: str = "512m",
        cpus: float = 1.0,
        pids_limit: int = 128,
        max_file_bytes: int = 1_000_000,
    ) -> None:
        self.image = image
        self.memory = memory
        self.cpus = cpus
        self.pids_limit = pids_limit
        # Caps read_file/write_file so a model can't write huge files or pull them into
        # its context (which costs tokens and money).
        self.max_file_bytes = max_file_bytes
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

    def read_file(self, path: str) -> str:
        """Return the text of a file, given a path relative to /workspace."""
        rel = _file_path(path)
        container = self._require_started()
        try:
            stream, stat = container.get_archive(f"{WORKDIR}/{rel}")
        except NotFound:
            raise FileNotFoundError(f"{rel} does not exist in {WORKDIR}.") from None
        # Docker reports the size up front, so refuse before downloading anything.
        if stat.get("size", 0) > self.max_file_bytes:
            raise FileTooLargeError(
                f"{rel} is {stat['size']} bytes; the limit is {self.max_file_bytes} bytes."
            )
        with tarfile.open(fileobj=io.BytesIO(b"".join(stream))) as archive:
            member = archive.next()
            # get_archive returns links as links (it doesn't follow them), so we can spot
            # and refuse them rather than read whatever they point at.
            if member is not None and (member.issym() or member.islnk()):
                raise SandboxError(f"{rel} is a link; reading through links is not allowed.")
            if member is not None and member.isdir():
                raise IsADirectoryError(f"{rel} is a directory, not a file.")
            if member is None or not member.isfile():
                raise SandboxError(f"{rel} is not a regular file.")
            data = archive.extractfile(member).read()
        return data.decode("utf-8", errors="replace")

    def write_file(self, path: str, content: str) -> None:
        """Create or overwrite a file (and any missing parent folders) relative to /workspace."""
        rel = _file_path(path)
        data = content.encode("utf-8")
        if len(data) > self.max_file_bytes:
            raise FileTooLargeError(
                f"Refusing to write {len(data)} bytes to {rel}; the limit is {self.max_file_bytes} bytes."
            )
        container = self._require_started()
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            # Explicit folder entries so new folders are owned by the sandbox user too.
            for parent in reversed(rel.parents[:-1]):  # parents[-1] is "." (/workspace itself)
                archive.addfile(_owned_tarinfo(parent.as_posix(), is_dir=True))
            info = _owned_tarinfo(rel.as_posix(), is_dir=False)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        container.put_archive(WORKDIR, buffer.getvalue())

    def delete_file(self, path: str) -> None:
        """Delete a file relative to /workspace (a no-op if it doesn't exist)."""
        rel = _file_path(path)
        self._require_started()
        # Argument list (no shell) and "--" so a name starting with "-" isn't read as an option.
        result = self.exec(["rm", "-f", "--", rel.as_posix()], timeout=30)
        if result.exit_code != 0:
            if "Is a directory" in result.output:
                raise IsADirectoryError(f"{rel} is a directory, not a file.")
            raise SandboxError(f"Deleting {rel} failed: {result.output.strip()}")

    def list_files(self, path: str = ".") -> list[str]:
        """Return every file under path (recursively), relative to /workspace, sorted."""
        rel = safe_relative_path(path)
        self._require_started()
        # A list (not a shell string), so the path can't inject extra shell commands.
        result = self.exec(["find", rel.as_posix(), "-type", "f"], timeout=30)
        if result.exit_code != 0:
            if "No such file" in result.output:
                raise FileNotFoundError(f"{rel} does not exist in {WORKDIR}.")
            raise SandboxError(f"Listing {rel} failed: {result.output.strip()}")
        files = (line.removeprefix("./") for line in result.output.splitlines() if line)
        return sorted(files)

    def run_checks(self, timeout: float = CHECK_TIMEOUT_SECONDS) -> CheckResult:
        """Run the task's tests inside the container."""
        return run_checks(self, timeout)

    def _require_started(self) -> Container:
        if self.container is None:
            raise SandboxError("Sandbox not started; call start() first.")
        return self.container

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


def cleanup_leftover_containers(max_age: timedelta | None = LEFTOVER_MAX_AGE) -> list[str]:
    """Remove our labelled containers older than max_age; return their short ids.

    The context manager removes containers even after exceptions, but not if this
    process is killed outright (crash, Ctrl+C at the wrong moment, power loss). This
    sweeps up those leftovers. Only containers with our label are touched.

    Age comes from Docker's own creation time. The default (1 hour) is far longer than
    any run, so a run still in progress is never removed. max_age=None removes every
    labelled container regardless of age, including ones in use.
    """
    client = _connect()
    label_filter = [f"{key}={value}" for key, value in LABEL.items()]
    now = datetime.now(timezone.utc)
    removed = []
    for container in client.containers.list(all=True, filters={"label": label_filter}):
        if max_age is not None and now - _docker_time(container.attrs["Created"]) < max_age:
            continue  # too recent: may belong to a run that's still going
        try:
            container.remove(force=True)
            removed.append(container.short_id)
        except NotFound:
            pass  # removed by someone else in the meantime
    return removed


def _docker_time(value: str) -> datetime:
    """Parse Docker's RFC 3339 timestamp, e.g. '2026-10-05T03:38:21.478256052Z'.

    Docker gives nanoseconds (9 digits) but datetime holds microseconds (6), so the
    extra digits are dropped before parsing.
    """
    main, _, fraction = value.rstrip("Z").partition(".")
    fraction = fraction[:6].ljust(6, "0")
    return datetime.fromisoformat(f"{main}.{fraction}").replace(tzinfo=timezone.utc)


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


def _file_path(path: str) -> PurePosixPath:
    """A safe path that names a file, not /workspace itself."""
    rel = safe_relative_path(path)
    if rel == PurePosixPath("."):
        raise UnsafePathError(f"path {path!r} refers to {WORKDIR} itself, not a file.")
    return rel


def _owned_tarinfo(name: str, is_dir: bool) -> tarfile.TarInfo:
    """A tar entry owned by the sandbox user, so the agent can edit what we write."""
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE if is_dir else tarfile.REGTYPE
    info.uid = info.gid = USER_ID
    info.uname = info.gname = USER
    info.mode = 0o755 if is_dir else 0o644
    info.mtime = int(time.time())
    return info


def _tar_folder(folder: Path) -> bytes:
    """Pack folder's contents into an in-memory tar owned by the sandbox user.

    Ownership matters: put_archive keeps the tar's owner, and files owned by root
    would be read-only for the non-root user that edits them.
    """
    def as_sandbox_user(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        if is_excluded_task_file(info.name):
            return None  # never copied: secrets, .git, caches
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
