"""Tests for the shared path-safety rules."""

from pathlib import PurePosixPath

import pytest

from repair_agent.paths import UnsafePathError, safe_relative_path


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/stats.py", "src/stats.py"),
        ("src\\stats.py", "src/stats.py"),  # backslashes are separators
        ("src/./stats.py", "src/stats.py"),  # "." parts are dropped
        ("src//stats.py", "src/stats.py"),
        ("stats.py", "stats.py"),
        ("src/", "src"),
        (".", "."),  # the base folder itself
    ],
)
def test_safe_paths_are_normalised(path: str, expected: str) -> None:
    assert safe_relative_path(path) == PurePosixPath(expected)


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("", "empty"),
        ("   ", "empty"),
        ("/etc/passwd", "absolute"),
        ("\\Windows\\win.ini", "absolute"),
        ("C:\\Windows\\win.ini", "absolute"),
        ("c:/Windows/win.ini", "absolute"),
        ("../outside.py", "'..'"),
        ("src/../../outside.py", "'..'"),
        ("src\\..\\..\\outside.py", "'..'"),
        ("src/..", "'..'"),
        ("src/a\0.py", "NUL"),
    ],
)
def test_unsafe_paths_are_rejected(path: str, reason: str) -> None:
    with pytest.raises(UnsafePathError, match=reason):
        safe_relative_path(path)
