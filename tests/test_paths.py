"""Tests for the shared path rules: path safety and task-copy exclusions."""

from pathlib import PurePosixPath

import pytest

from repair_agent.paths import UnsafePathError, is_excluded_task_file, safe_relative_path


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        ".env.example",
        "src/.env",
        ".git",
        ".git/config",
        ".git\\objects\\ab\\cd",
        "__pycache__",
        "src/__pycache__/stats.cpython-311.pyc",
        "src/stats.pyc",
        ".pytest_cache/v/cache/lastfailed",
    ],
)
def test_excluded_task_files(path: str) -> None:
    assert is_excluded_task_file(path)


@pytest.mark.parametrize(
    "path",
    ["src/stats.py", "tests/test_stats.py", "README.md", "pytest.ini", "src/environment.py", "src/git_utils.py"],
)
def test_normal_task_files_are_copied(path: str) -> None:
    assert not is_excluded_task_file(path)


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
