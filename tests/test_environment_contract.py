"""Contract tests: every Environment implementation must pass the same tests.

Each test runs once with LocalWorkspace and once with DockerSandbox, proving the two
behave the same. The Docker runs carry the "docker" marker, so they skip when Docker
isn't available and are left out of quick runs (pytest -m "not docker").
"""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from repair_agent.environment import Environment, FileTooLargeError
from repair_agent.paths import UnsafePathError
from repair_agent.sandbox import DockerSandbox
from repair_agent.workspace import LocalWorkspace

IMPLEMENTATIONS = [
    pytest.param("local", id="local"),
    pytest.param("docker", id="docker", marks=pytest.mark.docker),
]

EnvFactory = Callable[..., Environment]


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    task = tmp_path / "task"
    (task / "src").mkdir(parents=True)
    (task / "tests").mkdir()
    (task / "src" / "code.py").write_text("VALUE = 1\n", newline="\n")
    (task / "tests" / "test_code.py").write_text(
        "from code import VALUE\n\ndef test_value():\n    assert VALUE == 2\n", newline="\n"
    )
    (task / "pytest.ini").write_text("[pytest]\npythonpath = src\n", newline="\n")
    return task


@pytest.fixture(params=IMPLEMENTATIONS)
def make_env(request: pytest.FixtureRequest, task_dir: Path) -> Iterator[EnvFactory]:
    """Factory that builds and starts an environment of the parametrised kind."""
    created: list[Environment] = []

    def factory(**kwargs: int) -> Environment:
        env: Environment = LocalWorkspace(**kwargs) if request.param == "local" else DockerSandbox(**kwargs)
        created.append(env)
        env.start(task_dir)
        return env

    yield factory
    for env in created:
        env.stop()


@pytest.fixture
def env(make_env: EnvFactory) -> Environment:
    return make_env()


# --- files ---


def test_read_file(env: Environment) -> None:
    assert env.read_file("src/code.py") == "VALUE = 1\n"


def test_write_then_read(env: Environment) -> None:
    env.write_file("src/code.py", "VALUE = 2\n")

    assert env.read_file("src/code.py") == "VALUE = 2\n"


def test_write_creates_parent_folders(env: Environment) -> None:
    env.write_file("src/new/deep/mod.py", "X = 1\n")

    assert env.read_file("src/new/deep/mod.py") == "X = 1\n"


def test_list_files(env: Environment) -> None:
    assert env.list_files() == ["pytest.ini", "src/code.py", "tests/test_code.py"]
    assert env.list_files("src") == ["src/code.py"]


def test_secrets_git_and_caches_never_copied(make_env: EnvFactory, task_dir: Path) -> None:
    secret = "ANTHROPIC_API_KEY=sk-ant-should-never-be-copied"
    (task_dir / ".env").write_text(secret)
    (task_dir / ".env.local").write_text(secret)
    (task_dir / "src" / ".env").write_text(secret)
    (task_dir / ".git").mkdir()
    (task_dir / ".git" / "config").write_text("[core]\n")
    (task_dir / "src" / "__pycache__").mkdir()
    (task_dir / "src" / "__pycache__" / "code.cpython-311.pyc").write_bytes(b"stale")
    (task_dir / "src" / "old.pyc").write_bytes(b"stale")

    env = make_env()  # copies the task now, with the extra files present

    assert env.list_files() == ["pytest.ini", "src/code.py", "tests/test_code.py"]
    with pytest.raises(FileNotFoundError):
        env.read_file(".env")
    # Belt and braces: nothing anywhere in the copy contains the secret.
    search = env.exec(
        ["python", "-c", "import pathlib; print([str(p) for p in pathlib.Path('.').rglob('*') if p.is_file() and b'sk-ant' in p.read_bytes()])"],
        timeout=30,
    )
    assert search.output.strip() == "[]"


def test_original_task_unchanged(env: Environment, task_dir: Path) -> None:
    env.write_file("src/code.py", "VALUE = 99\n")

    assert (task_dir / "src" / "code.py").read_bytes() == b"VALUE = 1\n"


def test_missing_file_and_folder(env: Environment) -> None:
    with pytest.raises(FileNotFoundError):
        env.read_file("src/missing.py")
    with pytest.raises(FileNotFoundError):
        env.list_files("missing")


def test_read_directory(env: Environment) -> None:
    with pytest.raises(IsADirectoryError):
        env.read_file("src")


@pytest.mark.parametrize("path", ["/etc/passwd", "../outside.py", "src/../../x.py", "C:\\x.py", ""])
def test_unsafe_paths_rejected(env: Environment, path: str) -> None:
    with pytest.raises(UnsafePathError):
        env.read_file(path)
    with pytest.raises(UnsafePathError):
        env.write_file(path, "x")
    with pytest.raises(UnsafePathError):
        env.list_files(path)


def test_size_limits(make_env: EnvFactory) -> None:
    env = make_env(max_file_bytes=100)
    with pytest.raises(FileTooLargeError):
        env.write_file("src/big.py", "x" * 101)

    # Create an oversized file from inside, bypassing write_file's own check.
    env.exec(["python", "-c", "open('src/big.bin', 'wb').write(b'0' * 5000)"], timeout=30)
    with pytest.raises(FileTooLargeError):
        env.read_file("src/big.bin")


# --- exec ---


def test_exec_exit_code_and_combined_output(env: Environment) -> None:
    code = "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"

    result = env.exec(["python", "-c", code], timeout=30)

    assert result.exit_code == 3
    assert "out" in result.output and "err" in result.output


def test_exec_runs_in_task_root(env: Environment) -> None:
    result = env.exec(["python", "-c", "print(open('src/code.py').read())"], timeout=30)

    assert "VALUE = 1" in result.output


def test_exec_timeout(env: Environment) -> None:
    result = env.exec(["python", "-c", "import time; time.sleep(30)"], timeout=2)

    assert result.exit_code is None
    assert "timed out after 2 seconds" in result.output


def test_exec_hides_host_environment(make_env: EnvFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPAIR_AGENT_PROBE", "host-secret-value")
    env = make_env()

    result = env.exec(["python", "-c", "import os; print(os.environ.get('REPAIR_AGENT_PROBE'))"], timeout=30)

    assert result.output.strip() == "None"


# --- run_checks ---


def test_run_checks_failing_then_passing(env: Environment) -> None:
    before = env.run_checks()
    assert not before.passed
    assert before.exit_code == 1
    assert "1 failed" in before.output

    env.write_file("src/code.py", "VALUE = 2\n")
    after = env.run_checks()

    assert after.passed, after.output
    assert after.exit_code == 0
    assert "1 passed" in after.output


def test_run_checks_timeout(env: Environment) -> None:
    env.write_file("tests/test_slow.py", "import time\n\ndef test_slow():\n    time.sleep(30)\n")

    result = env.run_checks(timeout=2)

    assert not result.passed
    assert result.exit_code is None
    assert result.duration < 15
