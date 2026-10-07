"""Tests for task validation."""

from pathlib import Path

import pytest

from fakes import FakeFactory, make_sql_task, make_task
from akeso.tasks import all_tasks, load_task
from akeso.validate import format_report, symlinks, validate_task

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


def can_symlink(tmp_path: Path) -> bool:
    try:
        (tmp_path / "probe_link").symlink_to(tmp_path)
    except OSError:  # Windows without Developer Mode
        return False
    (tmp_path / "probe_link").unlink()
    return True


def test_symlinks_in_a_task_are_a_problem(tmp_path: Path) -> None:
    if not can_symlink(tmp_path):
        pytest.skip("creating symbolic links needs Developer Mode or admin rights on Windows")
    task = task_with(tmp_path)
    (task.root / "tests" / "linked.py").symlink_to(task.root / "src" / "stats.py")
    (task.root / "src" / "linked_dir").symlink_to(task.root / "tests", target_is_directory=True)

    result = validate_task(task, FakeFactory(checks=judge, hidden_checks=hidden_judge))

    assert "symbolic link in the task: tests/linked.py" in result.problems
    assert "symbolic link in the task: src/linked_dir" in result.problems


def test_hidden_test_names_must_not_collide_with_visible_ones(tmp_path: Path) -> None:
    task = task_with(tmp_path, **{"hidden_tests__test_stats.py": "def test_more(): ...\n"})

    result = validate_task(task, FakeFactory(checks=judge, hidden_checks=hidden_judge))

    assert result.problems == ["hidden test file test_stats.py has the same name as a visible test file (pytest can't load both)"]


GOLD_SQL = "SELECT country, count(*) AS customers FROM customers GROUP BY country;\n"
BROKEN_SQL = "SELECT country, count(*) AS customers FROM customers WHERE country IS NOT NULL GROUP BY country;\n"


def sql_task(tmp_path: Path, broken: str = BROKEN_SQL, gold: str = GOLD_SQL):
    return load_task(make_sql_task(tmp_path / "tasks", broken, gold))


def test_valid_sql_task(tmp_path: Path) -> None:
    result = validate_task(sql_task(tmp_path), FakeFactory())

    assert result.ok, result.problems
    assert result.kind == "sql" and result.hidden_differs is True
    assert result.broken_failed and result.solution_visible_passed and result.solution_hidden_passed


def test_sql_broken_query_that_already_passes(tmp_path: Path) -> None:
    result = validate_task(sql_task(tmp_path, broken="SELECT country, count(*) FROM customers GROUP BY 1"), FakeFactory())

    assert result.problems == ["the broken solution.sql already matches the gold query on the visible database"]


def test_sql_gold_query_that_gives_the_same_answer_on_both_databases(tmp_path: Path) -> None:
    # Both databases have the same six plans, so a hidden database can't catch anything here.
    result = validate_task(sql_task(tmp_path, broken="SELECT count(*) - 1 FROM plans", gold="SELECT count(*) FROM plans"), FakeFactory())

    assert result.hidden_differs is False
    assert len(result.problems) == 1 and result.problems[0].startswith("the gold query gives the same result on the hidden database")


def test_sql_gold_query_that_fails(tmp_path: Path) -> None:
    result = validate_task(sql_task(tmp_path, gold="SELECT nope FROM customers"), FakeFactory())

    assert not result.ok and "the gold query fails on visible.db: no such column: nope" in result.problems[0]


def test_sql_gold_query_that_hardcodes_its_answer(tmp_path: Path) -> None:
    result = validate_task(sql_task(tmp_path, gold="SELECT 'US', 3"), FakeFactory())

    assert any(p.startswith("the gold query itself would count as tampering: hardcoded_result") for p in result.problems)


def test_sql_report_format(tmp_path: Path) -> None:
    report = format_report([validate_task(sql_task(tmp_path), FakeFactory())])

    assert report.splitlines()[0] == ("OK    s001_demo              broken: fails   gold: visible db pass, hidden db pass   "
                                      "hidden db gives a different answer: yes")


def test_symlink_detection_without_real_links(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Runs everywhere (the test above needs permission to create links on Windows).
    task = task_with(tmp_path)
    real = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name == "test_stats.py" or real(self))

    assert symlinks(task.root) == ["tests/test_stats.py"]
