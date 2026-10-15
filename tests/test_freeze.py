"""Tests for the freeze manifest: hashing with normalised line endings, and spotting changes."""

from datetime import date
from pathlib import Path

import pytest

from fakes import make_sql_task, make_task
from akeso.freeze import FreezeError, build_manifest, check_tasks, file_hash, read_manifest, write_manifest
from akeso.tasks import all_tasks


@pytest.fixture
def tasks_root(tmp_path: Path) -> Path:
    root = tmp_path / "tasks"
    make_task(root / "code", {"src/stats.py": "x = 1\n", "tests/test_stats.py": "def test(): ...\n"})
    make_sql_task(root, "SELECT 1 FROM plans;\n", "SELECT count(*) FROM plans;\n")
    return root


def test_line_endings_do_not_change_the_hash(tmp_path: Path) -> None:
    (tmp_path / "lf.py").write_bytes(b"a = 1\nb = 2\n")
    (tmp_path / "crlf.py").write_bytes(b"a = 1\r\nb = 2\r\n")
    (tmp_path / "other.py").write_bytes(b"a = 1\nb = 3\n")

    assert file_hash(tmp_path / "lf.py") == file_hash(tmp_path / "crlf.py") != file_hash(tmp_path / "other.py")


def test_manifest_covers_task_and_dataset_files(tasks_root: Path) -> None:
    manifest = build_manifest(tasks_root, frozen_on=date(2026, 10, 15))

    assert manifest["frozen_on"] == "2026-10-15"
    assert set(manifest["tasks"]) == {"t001_demo", "s001_demo"}
    assert "code/t001_demo/src/stats.py" in manifest["files"]
    assert {"datasets/saas/schema.sql", "datasets/saas/generate.py"} <= set(manifest["tasks"]["s001_demo"]["files"])
    assert manifest["tasks"]["t001_demo"]["split"] == "dev"


def test_manifest_round_trip_and_fingerprint_is_stable(tasks_root: Path, tmp_path: Path) -> None:
    manifest = build_manifest(tasks_root)
    write_manifest(manifest, tmp_path / "manifest.json")

    assert read_manifest(tmp_path / "manifest.json") == manifest
    assert build_manifest(tasks_root)["fingerprint"] == manifest["fingerprint"]


def test_unchanged_tasks_pass_the_check(tasks_root: Path) -> None:
    manifest = build_manifest(tasks_root)

    check = check_tasks(all_tasks(tasks_root), manifest, tasks_root)

    assert check.ok and check.manifest_fingerprint == manifest["fingerprint"]


def test_converting_line_endings_is_not_a_change(tasks_root: Path) -> None:
    manifest = build_manifest(tasks_root)
    path = tasks_root / "code" / "t001_demo" / "src" / "stats.py"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))

    assert check_tasks(all_tasks(tasks_root), manifest, tasks_root).ok


def test_changed_added_and_removed_files_are_reported(tasks_root: Path) -> None:
    manifest = build_manifest(tasks_root)
    task = tasks_root / "code" / "t001_demo"
    (task / "src" / "stats.py").write_text("x = 2\n")
    (task / "src" / "extra.py").write_text("y = 1\n")
    (task / "tests" / "test_stats.py").unlink()

    check = check_tasks(all_tasks(tasks_root), manifest, tasks_root)

    assert check.modified == ["code/t001_demo/src/extra.py", "code/t001_demo/src/stats.py", "code/t001_demo/tests/test_stats.py"]


def test_a_dataset_change_affects_every_task_using_it(tasks_root: Path) -> None:
    manifest = build_manifest(tasks_root)
    schema = tasks_root / "datasets" / "saas" / "schema.sql"
    schema.write_text(schema.read_text() + "\n-- a comment\n")

    sql_task = [t for t in all_tasks(tasks_root) if t.id == "s001_demo"]
    code_task = [t for t in all_tasks(tasks_root) if t.id == "t001_demo"]

    assert check_tasks(sql_task, manifest, tasks_root).modified == ["datasets/saas/schema.sql"]
    assert check_tasks(code_task, manifest, tasks_root).ok


def test_a_task_added_after_the_freeze_is_reported(tasks_root: Path) -> None:
    manifest = build_manifest(tasks_root)
    make_task(tasks_root / "code", {"src/a.py": "a = 1\n"}, task_id="t002_new")

    check = check_tasks(all_tasks(tasks_root), manifest, tasks_root)

    assert "code/t002_new/task.yaml" in check.modified


def test_missing_manifest_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(FreezeError, match="No freeze manifest"):
        read_manifest(tmp_path / "nope.json")
