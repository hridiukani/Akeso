"""Tests for task.yaml loading and validation."""

from pathlib import Path

import pytest

from akeso.tasks import TaskError, all_tasks, find_task, load_task

VALID = """\
id: t001_demo
kind: code
description: A demo task.
split: dev
"""


def make_task(tmp_path: Path, yaml_text: str, folder: str = "t001_demo") -> Path:
    task = tmp_path / "code" / folder
    task.mkdir(parents=True)
    (task / "task.yaml").write_text(yaml_text)
    return task


def test_real_tasks_load() -> None:
    tasks = all_tasks()

    assert [t.id for t in tasks][:3] == ["c001_mean", "c002_shipping", "c003_discount"]
    for task in tasks:
        assert task.spec.kind == "code"
        assert (task.root / task.spec.solution_dir).is_dir()


def test_defaults(tmp_path: Path) -> None:
    task = load_task(make_task(tmp_path, VALID))

    assert task.spec.editable_paths == ["src"]
    assert task.spec.hidden_tests_dir == "hidden_tests" and task.spec.solution_dir == "solution"
    assert task.check_command == ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    assert task.spec.tags == []
    assert task.private_dirs == ("hidden_tests", "solution")


def test_sql_kind_is_accepted_for_later(tmp_path: Path) -> None:
    assert load_task(make_task(tmp_path, VALID.replace("kind: code", "kind: sql"))).spec.kind == "sql"


def test_is_editable(tmp_path: Path) -> None:
    task = load_task(make_task(tmp_path, VALID + "editable_paths: [src/, lib/utils]\n"))

    assert task.is_editable("src/stats.py")
    assert task.is_editable("lib/utils/helpers.py")
    assert not task.is_editable("lib/other.py")
    assert not task.is_editable("tests/test_stats.py")
    assert not task.is_editable("srcfoo/x.py")  # a prefix of the name is not the folder


@pytest.mark.parametrize(
    ("yaml_text", "message"),
    [
        ("id: t001_demo\nkind: code\nsplit: dev\n", "description: Field required"),
        (VALID.replace("kind: code", "kind: java"), "kind: Input should be 'code' or 'sql'"),
        (VALID.replace("split: dev", "split: test"), "split: Input should be 'dev' or 'heldout'"),
        (VALID + "editable: [src/]\n", "editable: Extra inputs are not permitted"),
        (VALID + "editable_paths: [../outside]\n", "contains '..'"),
        (VALID + "editable_paths: [/etc]\n", "is absolute"),
        (VALID + "editable_paths: ['.']\n", "whole task can't be editable"),
        (VALID + "editable_paths: [tests/]\n", "overlaps tests"),
        (VALID + "editable_paths: [solution/src]\n", "overlaps tests, hidden tests or the solution"),
        (VALID + "editable_paths: []\n", "editable_paths: List should have at least 1 item"),
        (VALID + "hidden_tests_dir: nested/hidden\n", "single top-level folder name"),
        (VALID + "check_command: '  '\n", "must not be empty"),
        (VALID.replace("id: t001_demo", "id: T001 Demo"), "id: String should match pattern"),
        ("- just\n- a list\n", "must contain a mapping"),
        ("id: [unclosed\n", "not valid YAML"),
    ],
)
def test_invalid_task_files_explain_the_problem(tmp_path: Path, yaml_text: str, message: str) -> None:
    with pytest.raises(TaskError, match=message.replace("(", r"\(").replace(")", r"\)").replace("[", r"\[")):
        load_task(make_task(tmp_path, yaml_text))


def test_error_names_the_file(tmp_path: Path) -> None:
    task_dir = make_task(tmp_path, "id: t001_demo\n")

    with pytest.raises(TaskError) as error:
        load_task(task_dir)
    assert str(task_dir / "task.yaml") in str(error.value)


def test_id_must_match_folder(tmp_path: Path) -> None:
    with pytest.raises(TaskError, match="must match the folder name 'other_name'"):
        load_task(make_task(tmp_path, VALID, folder="other_name"))


def test_missing_task_file(tmp_path: Path) -> None:
    with pytest.raises(TaskError, match="not found"):
        load_task(tmp_path)


def test_find_task(tmp_path: Path) -> None:
    make_task(tmp_path, VALID)

    assert find_task("t001_demo", tasks_root=tmp_path).id == "t001_demo"
    with pytest.raises(TaskError, match="No task with id 'nope'"):
        find_task("nope", tasks_root=tmp_path)
