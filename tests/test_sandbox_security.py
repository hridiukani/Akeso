"""Security tests: what model-written code can and can't do inside a DockerSandbox.

Each test checks behaviour from inside a real container rather than just the settings
we passed, so a misconfiguration (or a Docker change) shows up as a failure.
All tests need Docker and skip with the reason when it isn't available.
"""

import getpass
import json
import time
from collections.abc import Iterator
from pathlib import Path

import docker
import pytest

from akeso.sandbox import DockerSandbox

pytestmark = pytest.mark.docker

FAKE_KEYS = {
    "GROQ_API_KEY": "gsk-fake-groq-key-for-security-test",
    "ANTHROPIC_API_KEY": "sk-ant-fake-anthropic-key-for-security-test",
    "AKESO_PROBE": "fake-probe-value",
}


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    task = tmp_path / "task"
    (task / "src").mkdir(parents=True)
    (task / "src" / "code.py").write_text("VALUE = 1\n", newline="\n")
    return task


@pytest.fixture
def sandbox(task_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[DockerSandbox]:
    """A started sandbox, created while fake API keys are set in this (host) process."""
    for name, value in FAKE_KEYS.items():
        monkeypatch.setenv(name, value)
    with DockerSandbox() as box:
        box.start(task_dir)
        yield box


def python(sandbox: DockerSandbox, code: str, timeout: float = 30):
    return sandbox.exec(["python", "-c", code], timeout=timeout)


# --- network ---


def test_cannot_connect_to_outside_address(sandbox: DockerSandbox) -> None:
    result = python(sandbox, "import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)")

    assert result.exit_code not in (0, None)
    assert "Network is unreachable" in result.output


def test_cannot_resolve_hostnames(sandbox: DockerSandbox) -> None:
    result = python(sandbox, "import socket; socket.gethostbyname('example.com')")

    assert result.exit_code not in (0, None)
    assert "gaierror" in result.output


def test_only_loopback_network_interface(sandbox: DockerSandbox) -> None:
    result = python(sandbox, "import socket; print(sorted(n for _, n in socket.if_nameindex()))")

    assert result.output.strip() == "['lo']"


# --- user ---


def test_runs_as_non_root(sandbox: DockerSandbox) -> None:
    result = python(sandbox, "import os, pwd; print(os.getuid(), pwd.getpwuid(os.getuid()).pw_name)")

    uid, name = result.output.split()
    assert uid != "0"
    assert name == "agent"


def test_cannot_write_system_folders(sandbox: DockerSandbox) -> None:
    result = sandbox.exec("touch /etc/evil /usr/local/bin/evil", timeout=10)

    assert result.exit_code != 0
    assert "Permission denied" in result.output


# --- host environment ---


def test_host_environment_and_api_keys_not_visible(sandbox: DockerSandbox) -> None:
    result = sandbox.exec("env", timeout=10)

    for name, value in FAKE_KEYS.items():
        assert name not in result.output
        assert value not in result.output


def test_only_image_defined_variables_exist(sandbox: DockerSandbox) -> None:
    # Stronger than looking for known secret names: every variable must come from the
    # image itself (or be one Docker always sets), so nothing from the host can sneak in.
    # (The image's GPG_KEY is the public fingerprint for verifying Python, not a secret.)
    image_env = docker.from_env().images.get(sandbox.image).attrs["Config"]["Env"]
    allowed = {entry.split("=", 1)[0] for entry in image_env} | {"HOME", "HOSTNAME"}

    result = python(sandbox, "import os, json; print(json.dumps(sorted(os.environ)))")

    assert set(json.loads(result.output)) <= allowed


# --- host files ---


def test_no_host_mounts(sandbox: DockerSandbox) -> None:
    container = sandbox.container
    assert container is not None
    container.reload()

    assert container.attrs["Mounts"] == []


def test_docker_socket_not_present(sandbox: DockerSandbox) -> None:
    # With the socket, code could start its own unrestricted containers.
    for path in ("/var/run/docker.sock", "/run/docker.sock"):
        assert sandbox.exec(["test", "-e", path], timeout=10).exit_code == 1, path


def test_host_home_folder_not_present(sandbox: DockerSandbox) -> None:
    host_user = getpass.getuser()
    # Where a host home folder would appear if it were mounted (Linux, macOS, Docker
    # Desktop on Windows/macOS, WSL).
    candidates = ["/Users", "/host_mnt", "/mnt/c", "/mnt/host"]
    if host_user != "agent":
        candidates.append(f"/home/{host_user}")

    for path in candidates:
        assert sandbox.exec(["test", "-e", path], timeout=10).exit_code == 1, path
    assert sandbox.exec(["ls", "/home"], timeout=10).output.split() == ["agent"]


# --- resource limits ---


def test_command_that_sleeps_forever_is_killed(sandbox: DockerSandbox) -> None:
    start = time.monotonic()

    result = sandbox.exec(["sleep", "99999"], timeout=3)

    assert result.exit_code is None
    assert "timed out after 3 seconds" in result.output
    assert time.monotonic() - start < 10
    # And it's really gone, not left running in the background.
    procs = python(
        sandbox,
        "import os; print([open(f'/proc/{p}/cmdline', 'rb').read() for p in os.listdir('/proc') if p.isdigit()])",
    )
    assert "99999" not in procs.output


def test_command_using_too_much_memory_is_stopped(sandbox: DockerSandbox) -> None:
    # 1 GB of real (written) memory against a 512 MB limit.
    result = python(sandbox, "data = b'x' * (1024 * 1024 * 1024); print('allocated')", timeout=60)

    assert result.exit_code == 137  # killed with SIGKILL by the kernel's out-of-memory killer
    assert "allocated" not in result.output
    # The sandbox itself survives and is still usable.
    assert sandbox.exec(["echo", "still alive"], timeout=10).output.strip() == "still alive"


PROCESS_LIMIT_PROBE = """
import subprocess
procs = []
try:
    for _ in range(500):  # bounded: never an endless fork bomb
        try:
            procs.append(subprocess.Popen(["sleep", "60"]))
        except OSError as error:  # e.g. BlockingIOError: Resource temporarily unavailable
            print("blocked", len(procs), type(error).__name__)
            break
    else:
        print("started", len(procs))
finally:
    for proc in procs:
        proc.kill()
    for proc in procs:
        proc.wait()
"""


def test_process_limit_stops_runaway_process_creation(sandbox: DockerSandbox) -> None:
    # The exec timeout guarantees this can't hang even if the limit were missing.
    result = python(sandbox, PROCESS_LIMIT_PROBE, timeout=60)

    words = result.output.split()
    assert words[:1] == ["blocked"], result.output  # hit the limit before reaching 500
    assert int(words[1]) < 500
    assert int(words[1]) <= sandbox.pids_limit
    # The sandbox recovers and still runs normal commands.
    assert sandbox.exec(["echo", "still alive"], timeout=10).output.strip() == "still alive"


# --- cleanup ---


def test_container_gone_after_context_manager(task_dir: Path) -> None:
    with DockerSandbox() as box:
        box.start(task_dir)
        container_id = box.container.id

    assert docker.from_env().containers.list(all=True, filters={"id": container_id}) == []


def test_container_gone_after_error_in_context_manager(task_dir: Path) -> None:
    with pytest.raises(RuntimeError):
        with DockerSandbox() as box:
            box.start(task_dir)
            container_id = box.container.id
            raise RuntimeError("simulated crash mid-run")

    assert docker.from_env().containers.list(all=True, filters={"id": container_id}) == []
