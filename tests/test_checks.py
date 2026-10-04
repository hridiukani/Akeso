"""Tests for run_checks isolation."""

from pathlib import Path

import pytest

from repair_agent.checks import run_checks

PROBE_NAME = "REPAIR_AGENT_TEST_SECRET"
PROBE_VALUE = "fake-secret-value-123"


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

    result = run_checks(tmp_path)

    assert result.passed, result.output
    assert "1 passed" in result.output  # the probe test really ran
    assert PROBE_VALUE not in result.output
