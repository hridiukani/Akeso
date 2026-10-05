"""The one place that decides whether a model-supplied path is safe to use.

Paths from the model are untrusted. Every file operation (one-shot replies, sandbox
read/write/list) goes through safe_relative_path, so the rules can't drift apart.
"""

from __future__ import annotations

import re
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
