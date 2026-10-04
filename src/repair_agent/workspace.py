"""Disposable copies of task folders, so the agent never touches the originals."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

WORKSPACE_PREFIX = "repair-agent-"

# Caches from earlier host runs could make results depend on stale state, so don't copy them.
_IGNORED = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc")


def create_workspace(task_dir: str | Path) -> Path:
    """Copy task_dir into a new temporary directory and return that directory's path.

    The copy is independent: editing files in it never changes task_dir.
    """
    source = Path(task_dir).resolve()
    if not source.is_dir():
        raise NotADirectoryError(f"Task folder not found: {source}")

    workspace = Path(tempfile.mkdtemp(prefix=WORKSPACE_PREFIX))
    # symlinks=False copies the files a link points to rather than the link itself,
    # so edits in the workspace can never write through a link into the original.
    shutil.copytree(source, workspace, symlinks=False, ignore=_IGNORED, dirs_exist_ok=True)
    return workspace


def cleanup_workspace(workspace: str | Path) -> None:
    """Delete a workspace made by create_workspace. Safe to call twice.

    Refuses any other path, so a bug can never delete a task folder or the repo.
    """
    path = Path(workspace).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if path.parent != temp_root or not path.name.startswith(WORKSPACE_PREFIX):
        raise ValueError(f"Refusing to delete {path}: not a repair-agent workspace.")
    if path.exists():
        shutil.rmtree(path)
