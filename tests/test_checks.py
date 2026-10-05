"""Tests for run_checks (via LocalWorkspace): pass/fail, timeouts, and env isolation.

The Docker side is covered by tests/test_environment_contract.py.
"""

from pathlib import Path

import pytest

from akeso.checks import CheckResult, run_checks
from akeso.workspace import LocalWorkspace

PROBE_NAME = "REPAIR_AGENT_TEST_SECRET"
PROBE_VALUE = "fake-secret-value-123"


def write_project(folder: Path, test_code: str) -> Path:
    """Create a tiny project with a single test file and return its folder."""
    (folder / "test_tiny.py").write_text(test_code)
    return folder


def check(folder: Path, timeout: float = 60) -> CheckResult:
    """Run checks on a copy of folder in a LocalWorkspace."""
    with LocalWorkspace() as env:
        env.start(folder)
        return run_checks(env, timeout=timeout)


def test_passing_project(tmp_path: Path) -> None:
    project = write_project(tmp_path, "def test_ok():\n    assert 1 + 1 == 2\n")

    result = check(project)

    assert result.passed
    assert result.exit_code == 0
    assert "1 passed" in result.output
    assert result.duration > 0


def test_failing_project(tmp_path: Path) -> None:
    project = write_project(tmp_path, "def test_broken():\n    total = 1 + 1\n    assert total == 3\n")

    result = check(project)

    assert not result.passed
    assert result.exit_code == 1  # pytest's code for "some tests failed"
    assert "1 failed" in result.output
    assert "assert 2 == 3" in result.output  # failure details are captured for the model


def test_timeout_counts_as_failure(tmp_path: Path) -> None:
    project = write_project(tmp_path, "import time\ndef test_slow():\n    time.sleep(30)\n")

    result = check(project, timeout=1)

    assert not result.passed
    assert result.exit_code is None
    assert "timed out after 1 seconds" in result.output
    assert result.duration < 15  # killed early, not left to run its full 30 seconds


def test_parent_env_var_is_not_visible_to_task_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(PROBE_NAME, PROBE_VALUE)
    # A tiny "task" whose only test passes if the variable is invisible. It also prints
    # the variable's value, so a leak would show up in the captured output.
    (tmp_path / "test_probe.py").write_text(
        "import os\n"
        "def test_probe():\n"
        f"    value = os.environ.get({PROBE_NAME!r})\n"
        "    print('probe value:', value)\n"
        "    assert value is None\n"
    )

    result = check(tmp_path)

    assert result.passed, result.output
    assert "1 passed" in result.output  # the probe test really ran
    assert PROBE_VALUE not in result.output
