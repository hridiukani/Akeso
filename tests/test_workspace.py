"""Tests for workspace copies: originals stay untouched and cleanup is safe."""

from pathlib import Path

import pytest

from repair_agent.workspace import cleanup_workspace, create_workspace


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    """A tiny fake task folder."""
    task = tmp_path / "task"
    (task / "src").mkdir(parents=True)
    (task / "tests").mkdir()
    (task / "src" / "code.py").write_text("def f():\n    return 1\n")
    (task / "tests" / "test_code.py").write_text("from code import f\n")
    return task


def read_all(folder: Path) -> dict[str, str]:
    """Map each file's relative path to its contents."""
    return {
        path.relative_to(folder).as_posix(): path.read_text()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def test_copy_matches_original(task_dir: Path) -> None:
    workspace = create_workspace(task_dir)
    try:
        assert workspace != task_dir
        assert read_all(workspace) == read_all(task_dir)
    finally:
        cleanup_workspace(workspace)


def test_original_unchanged_after_modifying_copy(task_dir: Path) -> None:
    original = read_all(task_dir)
    workspace = create_workspace(task_dir)
    try:
        (workspace / "src" / "code.py").write_text("def f():\n    return 2\n")
        (workspace / "src" / "new_file.py").write_text("x = 1\n")
        (workspace / "tests" / "test_code.py").unlink()

        assert read_all(task_dir) == original
    finally:
        cleanup_workspace(workspace)


def test_cleanup_removes_copy(task_dir: Path) -> None:
    workspace = create_workspace(task_dir)

    cleanup_workspace(workspace)

    assert not workspace.exists()
    assert task_dir.exists()


def test_cleanup_twice_is_safe(task_dir: Path) -> None:
    workspace = create_workspace(task_dir)
    cleanup_workspace(workspace)

    cleanup_workspace(workspace)  # must not raise


def test_cleanup_refuses_non_workspace_paths(task_dir: Path) -> None:
    with pytest.raises(ValueError, match="not a repair-agent workspace"):
        cleanup_workspace(task_dir)
    assert task_dir.exists()


def test_missing_task_folder_raises(tmp_path: Path) -> None:
    with pytest.raises(NotADirectoryError):
        create_workspace(tmp_path / "does-not-exist")
