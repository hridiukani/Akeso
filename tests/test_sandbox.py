"""Tests for DockerSandbox. Tests marked "docker" skip when Docker or the image is missing.

Build the image with: python scripts/build_images.py
"""

import time
from pathlib import Path

import docker
import pytest

from repair_agent import sandbox as sandbox_module
from repair_agent.paths import UnsafePathError
from repair_agent.sandbox import (
    IMAGE,
    DockerSandbox,
    FileTooLargeError,
    SandboxError,
    cleanup_leftover_containers,
)


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    task = tmp_path / "task"
    (task / "src").mkdir(parents=True)
    # newline="\n" so Windows doesn't write \r\n; the sandbox copies bytes exactly.
    (task / "src" / "code.py").write_text("VALUE = 1\n", newline="\n")
    (task / "src" / "__pycache__").mkdir()
    (task / "src" / "__pycache__" / "code.cpython-311.pyc").write_bytes(b"stale")
    return task


@pytest.fixture
def running(task_dir: Path):
    with DockerSandbox() as sandbox:
        sandbox.start(task_dir)
        yield sandbox


# --- isolation settings ---


@pytest.mark.docker
def test_container_is_locked_down(running: DockerSandbox) -> None:
    container = running.container
    assert container is not None
    container.reload()
    host_config = container.attrs["HostConfig"]

    assert host_config["NetworkMode"] == "none"
    assert host_config["Memory"] == 512 * 1024 * 1024
    assert host_config["NanoCpus"] == 1_000_000_000
    assert host_config["PidsLimit"] == 128
    assert container.attrs["Mounts"] == []  # no host folders
    assert container.labels == {"repair-agent": "sandbox"}


@pytest.mark.docker
def test_runs_as_non_root_in_workspace(running: DockerSandbox) -> None:
    result = running.exec("whoami && pwd", timeout=10)

    assert result.exit_code == 0
    assert result.output.split() == ["agent", "/workspace"]


@pytest.mark.docker
def test_no_network(running: DockerSandbox) -> None:
    code = "import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)"

    result = running.exec(["python", "-c", code], timeout=15)

    assert result.exit_code != 0
    assert "unreachable" in result.output.lower()


@pytest.mark.docker
def test_host_environment_not_passed(task_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPAIR_AGENT_PROBE", "host-secret-value")
    with DockerSandbox() as sandbox:
        sandbox.start(task_dir)  # started after the variable is set in this process

        result = sandbox.exec("env", timeout=10)

    assert "REPAIR_AGENT_PROBE" not in result.output
    assert "host-secret-value" not in result.output


# --- files ---


@pytest.mark.docker
def test_task_files_copied_and_editable(running: DockerSandbox) -> None:
    assert running.exec("cat src/code.py", timeout=10).output == "VALUE = 1\n"

    # Owned by the sandbox user, so the agent can edit them.
    edit = running.exec("echo 'VALUE = 2' > src/code.py && cat src/code.py", timeout=10)
    assert edit.exit_code == 0
    assert edit.output == "VALUE = 2\n"


@pytest.mark.docker
def test_caches_are_not_copied(running: DockerSandbox) -> None:
    result = running.exec("test -e src/__pycache__", timeout=10)

    assert result.exit_code == 1  # does not exist


@pytest.mark.docker
def test_original_unchanged_after_editing_in_container(
    running: DockerSandbox, task_dir: Path
) -> None:
    running.exec("echo 'VALUE = 99' > src/code.py", timeout=10)

    assert (task_dir / "src" / "code.py").read_bytes() == b"VALUE = 1\n"


# --- exec ---


@pytest.mark.docker
def test_exec_returns_exit_code_and_combined_output(running: DockerSandbox) -> None:
    result = running.exec("echo out; echo err >&2; exit 3", timeout=10)

    assert result.exit_code == 3
    assert "out" in result.output and "err" in result.output


@pytest.mark.docker
def test_exec_timeout_kills_command(running: DockerSandbox) -> None:
    start = time.monotonic()

    result = running.exec("sleep 30", timeout=2)

    assert result.exit_code is None
    assert "timed out after 2 seconds" in result.output
    assert time.monotonic() - start < 10


# --- lifecycle ---


@pytest.mark.docker
def test_container_removed_after_error_in_with_block(task_dir: Path) -> None:
    with pytest.raises(RuntimeError):
        with DockerSandbox() as sandbox:
            sandbox.start(task_dir)
            container_id = sandbox.container.id
            raise RuntimeError("boom")

    remaining = docker.from_env().containers.list(all=True, filters={"id": container_id})
    assert remaining == []


@pytest.mark.docker
def test_stop_twice_is_safe(task_dir: Path) -> None:
    sandbox = DockerSandbox()
    sandbox.start(task_dir)

    sandbox.stop()
    sandbox.stop()

    assert sandbox.container is None


def test_exec_before_start_raises() -> None:
    with pytest.raises(SandboxError, match="not started"):
        DockerSandbox().exec("true", timeout=5)


# --- clear errors ---


@pytest.mark.docker
def test_missing_image_gives_build_instructions(task_dir: Path) -> None:
    with pytest.raises(SandboxError, match="build_images.py"):
        DockerSandbox(image="repair-agent-does-not-exist:latest").start(task_dir)


def test_docker_not_running_gives_clear_message(
    task_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_docker() -> None:
        raise docker.errors.DockerException("Error while fetching server API version")

    monkeypatch.setattr(sandbox_module.docker, "from_env", no_docker)

    with pytest.raises(SandboxError, match="Start Docker Desktop"):
        DockerSandbox().start(task_dir)


# --- read_file / write_file / list_files ---


@pytest.mark.docker
def test_read_file(running: DockerSandbox) -> None:
    assert running.read_file("src/code.py") == "VALUE = 1\n"


@pytest.mark.docker
def test_write_then_read_round_trip(running: DockerSandbox) -> None:
    running.write_file("src/code.py", "VALUE = 2\n")

    assert running.read_file("src/code.py") == "VALUE = 2\n"
    assert running.exec("cat src/code.py", timeout=10).output == "VALUE = 2\n"


@pytest.mark.docker
def test_write_creates_folders_owned_by_agent(running: DockerSandbox) -> None:
    running.write_file("src/new/deep/mod.py", "X = 1\n")

    owners = running.exec("stat -c %U src/new src/new/deep src/new/deep/mod.py", timeout=10)
    assert owners.output.split() == ["agent", "agent", "agent"]
    # The agent user can edit what write_file created.
    assert running.exec("echo 'Y = 2' >> src/new/deep/mod.py", timeout=10).exit_code == 0


@pytest.mark.docker
def test_list_files(running: DockerSandbox) -> None:
    running.write_file("tests/test_code.py", "def test(): pass\n")

    assert running.list_files() == ["src/code.py", "tests/test_code.py"]
    assert running.list_files("src") == ["src/code.py"]


@pytest.mark.docker
def test_read_missing_file_raises(running: DockerSandbox) -> None:
    with pytest.raises(FileNotFoundError):
        running.read_file("src/missing.py")


@pytest.mark.docker
def test_list_missing_folder_raises(running: DockerSandbox) -> None:
    with pytest.raises(FileNotFoundError):
        running.list_files("nope")


@pytest.mark.docker
def test_read_directory_raises(running: DockerSandbox) -> None:
    with pytest.raises(IsADirectoryError):
        running.read_file("src")


@pytest.mark.docker
def test_read_refuses_symlink_out_of_workspace(running: DockerSandbox) -> None:
    running.exec("ln -s /etc/passwd src/link", timeout=10)

    with pytest.raises(SandboxError, match="is a link"):
        running.read_file("src/link")


@pytest.mark.docker
def test_read_refuses_symlink_inside_workspace(running: DockerSandbox) -> None:
    # Even a link to a harmless file is refused: reads never follow links.
    running.exec("ln -s code.py src/alias.py", timeout=10)

    with pytest.raises(SandboxError, match="is a link"):
        running.read_file("src/alias.py")


# Path checks run before touching Docker, so these tests don't need a container.
UNSAFE_PATHS = ["/etc/passwd", "../outside.py", "src/../../outside.py", "C:\\Windows\\x.py", ""]


@pytest.mark.parametrize("path", UNSAFE_PATHS)
def test_read_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(UnsafePathError):
        DockerSandbox().read_file(path)


@pytest.mark.parametrize("path", UNSAFE_PATHS)
def test_write_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(UnsafePathError):
        DockerSandbox().write_file(path, "x")


@pytest.mark.parametrize("path", UNSAFE_PATHS)
def test_list_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(UnsafePathError):
        DockerSandbox().list_files(path)


def test_read_and_write_reject_workspace_root() -> None:
    with pytest.raises(UnsafePathError, match="itself"):
        DockerSandbox().read_file(".")
    with pytest.raises(UnsafePathError, match="itself"):
        DockerSandbox().write_file(".", "x")


@pytest.mark.docker
def test_unsafe_write_leaves_container_unchanged(running: DockerSandbox) -> None:
    before = running.list_files()

    with pytest.raises(UnsafePathError):
        running.write_file("../outside.py", "x")

    assert running.list_files() == before
    assert running.exec("test -e /outside.py", timeout=10).exit_code == 1


# --- size limits ---


@pytest.fixture
def small_limit(task_dir: Path):
    with DockerSandbox(max_file_bytes=100) as sandbox:
        sandbox.start(task_dir)
        yield sandbox


@pytest.mark.docker
def test_write_over_limit_is_refused_and_writes_nothing(small_limit: DockerSandbox) -> None:
    with pytest.raises(FileTooLargeError, match="limit is 100 bytes"):
        small_limit.write_file("src/big.py", "x" * 101)

    assert "src/big.py" not in small_limit.list_files()


@pytest.mark.docker
def test_write_at_limit_is_allowed(small_limit: DockerSandbox) -> None:
    small_limit.write_file("src/exact.py", "x" * 100)

    assert small_limit.read_file("src/exact.py") == "x" * 100


@pytest.mark.docker
def test_read_over_limit_is_refused(small_limit: DockerSandbox) -> None:
    # Created by a command inside the container, bypassing write_file's own limit.
    small_limit.exec("head -c 5000 /dev/zero > src/big.bin", timeout=10)

    with pytest.raises(FileTooLargeError, match="5000 bytes"):
        small_limit.read_file("src/big.bin")


def test_size_limit_counts_bytes_not_characters() -> None:
    # "é" is 2 bytes in UTF-8, so 60 of them (120 bytes) exceed a 100-byte limit.
    # The check runs before the container is needed, so no Docker required.
    with pytest.raises(FileTooLargeError):
        DockerSandbox(max_file_bytes=100).write_file("src/a.py", "é" * 60)


# --- leftover cleanup ---


@pytest.mark.docker
def test_cleanup_removes_sandbox_left_by_hard_crash(task_dir: Path) -> None:
    # A hard crash (process killed) means stop()/__exit__ never run, so simulate that
    # by starting a sandbox and simply never stopping it.
    abandoned = DockerSandbox()
    abandoned.start(task_dir)
    container_id = abandoned.container.id
    client = docker.from_env()
    assert client.containers.list(all=True, filters={"id": container_id})

    removed = cleanup_leftover_containers()

    assert abandoned.container.short_id in removed
    assert client.containers.list(all=True, filters={"id": container_id}) == []


@pytest.mark.docker
def test_cleanup_leaves_unlabelled_containers_alone() -> None:
    client = docker.from_env()
    # Stands in for someone's unrelated container (e.g. another project's).
    other = client.containers.create(IMAGE, command=["true"])
    try:
        cleanup_leftover_containers()

        assert client.containers.list(all=True, filters={"id": other.id}) != []
    finally:
        other.remove(force=True)


def test_cleanup_without_docker_gives_clear_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_docker() -> None:
        raise docker.errors.DockerException("Error while fetching server API version")

    monkeypatch.setattr(sandbox_module.docker, "from_env", no_docker)

    with pytest.raises(SandboxError, match="Start Docker Desktop"):
        cleanup_leftover_containers()
