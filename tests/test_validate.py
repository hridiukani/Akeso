"""Tests for task validation."""

from pathlib import Path

import pytest

from fakes import FakeFactory, make_task
from akeso.tasks import all_tasks, load_task
from akeso.validate import format_report, validate_task

BUGGY = "def mean(n):\n    return sum(n) / (len(n) - 1)\n"
FIXED = "def mean(n):\n    return sum(n) / len(n)\n"


def judge(files: dict[str, str]) -> tuple[bool, str]:
    return "- 1" not in files["src/stats.py"], "visible"


def hidden_judge(files: dict[str, str]) -> tuple[bool, str]:
    return "- 1" not in files["src/stats.py"], "hidden"


def task_with(tmp_path: Path, **overrides: str | None):
    files = {
        "src/stats.py": BUGGY,
        "tests/test_stats.py": "def test(): ...\n",
        "hidden_tests/test_hidden_stats.py": "def test_hidden(): ...\n",
        "solution/src/stats.py": FIXED,
    }
    for rel, content in overrides.items():
        rel = rel.replace("__", "/")
        if content is None:
            files.pop(rel)
        else:
            files[rel] = content
    return load_task(make_task(tmp_path / "tasks", files))


def test_valid_task(tmp_path: Path) -> None:
    result = validate_task(task_with(tmp_path), FakeFactory(checks=judge, hidden_checks=hidden_judge))

    assert result.ok
    assert result.broken_failed and result.solution_visible_passed and result.solution_hidden_passed


def test_broken_version_that_already_passes(tmp_path: Path) -> None:
    result = validate_task(task_with(tmp_path), FakeFactory(checks=lambda f: (True, ""), hidden_checks=hidden_judge))

    assert "the broken version already passes its visible tests" in result.problems


def test_solution_failing_visible_tests(tmp_path: Path) -> None:
    task = task_with(tmp_path, **{"solution__src__stats.py": BUGGY + "# a 'fix' that keeps the bug\n"})

    result = validate_task(task, FakeFactory(checks=judge, hidden_checks=hidden_judge))

    assert "the reference solution fails the visible tests" in result.problems


def test_solution_failing_hidden_tests(tmp_path: Path) -> None:
    result = validate_task(task_with(tmp_path), FakeFactory(checks=judge, hidden_checks=lambda f: (False, "")))

    assert result.problems == ["the reference solution fails the hidden tests"]


def test_missing_solution_and_hidden_tests(tmp_path: Path) -> None:
    task = task_with(tmp_path, **{"solution__src__stats.py": None, "hidden_tests__test_hidden_stats.py": None})

    result = validate_task(task, FakeFactory(checks=judge))

    assert "no reference solution in solution/" in result.problems
    assert "no hidden tests in hidden_tests/" in result.problems


@pytest.mark.parametrize("path", ["solution__tests__test_stats.py", "solution__src__conftest.py"])
def test_solution_that_would_count_as_tampering(tmp_path: Path, path: str) -> None:
    task = task_with(tmp_path, **{path: "def test(): pass\n"})

    result = validate_task(task, FakeFactory(checks=judge, hidden_checks=hidden_judge))

    assert any(p.startswith("the solution itself would count as tampering") for p in result.problems)


def test_report_format(tmp_path: Path) -> None:
    good = validate_task(task_with(tmp_path / "a"), FakeFactory(checks=judge, hidden_checks=hidden_judge))
    bad = validate_task(task_with(tmp_path / "b"), FakeFactory(checks=judge, hidden_checks=lambda f: (False, "")))

    report = format_report([good, bad])

    assert report.splitlines()[0].startswith("OK    t001_demo")
    assert "FAIL  t001_demo" in report and "- the reference solution fails the hidden tests" in report
    assert report.endswith("1/2 tasks valid")


@pytest.mark.docker
@pytest.mark.parametrize("task", all_tasks(), ids=lambda t: t.id)
def test_real_tasks_are_valid_in_docker(task) -> None:
    result = validate_task(task)

    assert result.ok, result.problems
