"""The one place for path rules: which paths are safe, and which task files are copied.

Paths from the model are untrusted. Every file operation (one-shot replies, sandbox
read/write/list) goes through safe_relative_path, and every task copy (LocalWorkspace
and DockerSandbox) goes through is_excluded_task_file, so the rules can't drift apart.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from pathlib import PurePosixPath

_DRIVE_LETTER = re.compile(r"^[A-Za-z]:$")


class UnsafePathError(ValueError):
    """A path is empty, absolute, or tries to escape its base folder."""


def safe_relative_path(path: str) -> PurePosixPath:
    """Normalise a path relative to some base folder, or raise UnsafePathError.

    Backslashes count as separators and "." parts are dropped, so "src\\.\\a.py" becomes
    "src/a.py". Rejects empty paths, absolute paths, Windows drive letters, NUL bytes and
    any ".." part. Returns PurePosixPath(".") for the base folder itself.

    This is a text check only; callers that touch a real filesystem should also confirm
    the resolved path stays inside the base folder.
    """
    if not path or not path.strip():
        raise UnsafePathError("path is empty.")
    if "\0" in path:
        raise UnsafePathError(f"path {path!r} contains a NUL byte.")
    normalised = PurePosixPath(path.replace("\\", "/"))
    # parts is empty for "." (the base folder), so guard before looking at parts[0].
    has_drive = bool(normalised.parts) and _DRIVE_LETTER.match(normalised.parts[0])
    if normalised.is_absolute() or has_drive:
        raise UnsafePathError(f"path {path!r} is absolute; use a relative path.")
    if ".." in normalised.parts:
        raise UnsafePathError(f"path {path!r} contains '..' and could escape the base folder.")
    return normalised


# What is never copied from a task folder into a run environment (LocalWorkspace or
# DockerSandbox). Extend these to exclude more.
_EXCLUDED_NAMES = {".git", "__pycache__", ".pytest_cache"}  # folders: everything inside goes too
_EXCLUDED_PREFIXES = (".env",)  # .env, .env.local, .env.example, ...: may hold secrets
_EXCLUDED_SUFFIXES = (".pyc",)  # bytecode from earlier runs
# Top-level entries that are for grading only. They're always excluded, even when a caller
# forgets to pass the task's own private folders, so the agent can never see them.
ALWAYS_PRIVATE = ("hidden_tests", "solution", "task.yaml")


def is_excluded_task_file(path: str, private_dirs: Collection[str] = ()) -> bool:
    """True if this file or folder inside a task must never be copied into a run.

    Every part of the path is checked, so anything inside an excluded folder (like
    .git/config) is excluded too. private_dirs names extra top-level folders to keep out
    (a task's hidden tests and solution).
    """
    parts = PurePosixPath(path.replace("\\", "/")).parts
    if parts and (parts[0] in ALWAYS_PRIVATE or parts[0] in private_dirs):
        return True
    if any(part in _EXCLUDED_NAMES or part.startswith(_EXCLUDED_PREFIXES) for part in parts):
        return True
    return bool(parts) and parts[-1].endswith(_EXCLUDED_SUFFIXES)
