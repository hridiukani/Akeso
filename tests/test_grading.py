"""Tests for grading: collecting the agent's changes and grading them in a fresh environment."""

from pathlib import Path

import pytest

from fakes import FakeEnvironment, FakeFactory, make_task
from akeso.grading import ChangeSet, Verdict, collect_changes, grade, pristine_files
from akeso.tasks import load_task

BUGGY = "def mean(n):\n    return sum(n) / (len(n) - 1)\n"
FIXED = "def mean(n):\n    return sum(n) / len(n)\n"
TESTS = "from stats import mean\n\ndef test_mean():\n    assert mean([2, 4, 6]) == 4\n"
HIDDEN = "from stats import mean\n\ndef test_hidden_mean():\n    assert mean([1, 2]) == 1.5\n"


@pytest.fixture
def task(tmp_path: Path):
    root = make_task(tmp_path / "tasks", {
        "src/stats.py": BUGGY,
        "src/helpers.py": "X = 1\n",
        "tests/test_stats.py": TESTS,
        "hidden_tests/test_hidden_stats.py": HIDDEN,
        "solution/src/stats.py": FIXED,
        "README.md": "mean\n",
    })
    return load_task(root)


def started(task) -> FakeEnvironment:
    env = FakeEnvironment()
    env.start(task.root, task.private_dirs)
    return env


def visible_judge(files: dict[str, str]) -> tuple[bool, str]:
    return ("- 1" not in files["src/stats.py"]), "visible run"


def hidden_judge(files: dict[str, str]) -> tuple[bool, str]:
    # Hidden tests need a real fix *and* must actually be present in the grading environment.
    ok = "- 1" not in files["src/stats.py"] and "hidden_tests/test_hidden_stats.py" in files
    return ok, "hidden run"


# --- collecting changes ---


def test_pristine_files_match_what_the_agent_sees(task) -> None:
    # task.yaml, hidden tests and the solution are private, exactly as in the agent's sandbox.
    assert sorted(pristine_files(task)) == ["README.md", "src/helpers.py", "src/stats.py", "tests/test_stats.py"]


def test_no_changes(task) -> None:
    changes = collect_changes(started(task), task)

    assert changes == ChangeSet()


def test_editable_changes_are_kept(task) -> None:
    env = started(task)
    env.files["src/stats.py"] = FIXED
    env.files["src/new_module.py"] = "Y = 2\n"
    del env.files["src/helpers.py"]

    changes = collect_changes(env, task)

    assert changes.written == {"src/stats.py": FIXED, "src/new_module.py": "Y = 2\n"}
    assert changes.deleted == ["src/helpers.py"]
    assert changes.ignored == []


def test_changes_outside_editable_paths_are_left_behind(task) -> None:
    env = started(task)
    env.files["tests/test_stats.py"] = "def test_mean():\n    pass\n"
    env.files["README.md"] = "edited\n"
    env.files["notes.txt"] = "scratch\n"

    changes = collect_changes(env, task)

    assert changes.written == {}
    assert sorted(changes.ignored) == ["README.md", "notes.txt", "tests/test_stats.py"]


def test_deleting_a_test_is_left_behind(task) -> None:
    env = started(task)
    del env.files["tests/test_stats.py"]

    changes = collect_changes(env, task)

    assert changes.deleted == [] and changes.ignored == ["tests/test_stats.py"]


# --- grading ---


def test_grading_uses_a_fresh_pristine_environment(task) -> None:
    factory = FakeFactory(checks=visible_judge, hidden_checks=hidden_judge)
    changes = ChangeSet(written={"src/stats.py": FIXED}, deleted=["src/helpers.py"])

    result = grade(task, changes, factory)

    env = factory.grading_env
    assert env.started and env.stopped
    assert env.files["src/stats.py"] == FIXED and "src/helpers.py" not in env.files
    assert env.files["tests/test_stats.py"] == TESTS  # pristine tests
    assert "solution/src/stats.py" not in env.files
    assert result.verdict is Verdict.PASSED
    assert result.visible_passed and result.hidden_passed
    assert result.applied == ["src/helpers.py", "src/stats.py"]


def test_hidden_tests_run_after_the_visible_ones(task) -> None:
    factory = FakeFactory(checks=visible_judge, hidden_checks=hidden_judge)

    grade(task, ChangeSet(written={"src/stats.py": FIXED}), factory)

    env = factory.grading_env
    assert env.commands_run == [env.check_command, [*task.check_command, "hidden_tests"]]


def test_visible_failure_fails(task) -> None:
    result = grade(task, ChangeSet(), FakeFactory(checks=visible_judge, hidden_checks=hidden_judge))

    assert result.verdict is Verdict.FAILED
    assert not result.visible_passed and result.hidden_passed is False


def test_hidden_failure_fails_even_if_visible_tests_pass(task) -> None:
    factory = FakeFactory(checks=visible_judge, hidden_checks=lambda files: (False, "1 failed (hidden)"))

    result = grade(task, ChangeSet(written={"src/stats.py": FIXED}), factory)

    assert result.verdict is Verdict.FAILED
    assert result.visible_passed and result.hidden_passed is False
    assert "1 failed (hidden)" in result.hidden_output


def test_task_without_hidden_tests(tmp_path: Path) -> None:
    task = load_task(make_task(tmp_path / "t", {"src/stats.py": BUGGY, "tests/test_stats.py": TESTS}))
    factory = FakeFactory(checks=visible_judge)

    result = grade(task, ChangeSet(written={"src/stats.py": FIXED}), factory)

    assert result.verdict is Verdict.PASSED and result.hidden_passed is None
    assert len(factory.grading_env.commands_run) == 1
