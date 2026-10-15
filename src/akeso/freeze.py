"""The freeze: a fingerprint of every task file and shared dataset file, so a run can prove
it used exactly the frozen suite.

suites/manifest.json records a SHA-256 for every file that defines a task (Task
.definition_files(): the task's own files plus, for SQL tasks, its dataset's). Line
endings are normalised to LF before hashing, so the same tasks give the same fingerprint
on any machine, whatever git's line-ending settings. `akeso run` compares the tasks it is
about to run with the manifest and refuses to start if anything changed (see FREEZE.md).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from akeso.tasks import DEFAULT_TASKS_ROOT, Task, all_tasks

DEFAULT_MANIFEST = Path("suites/manifest.json")
HASH_RULE = "sha256 of the file's bytes with CRLF and CR line endings normalised to LF"


class FreezeError(Exception):
    """The manifest is missing or unreadable."""


@dataclass(frozen=True)
class FreezeCheck:
    """How the tasks of a run compare with the manifest."""

    manifest_fingerprint: str
    modified: list[str] = field(default_factory=list)  # files changed, added or removed since the freeze

    @property
    def ok(self) -> bool:
        return not self.modified


def file_hash(path: Path) -> str:
    """SHA-256 of a file with line endings normalised to LF."""
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def _file_hashes(task: Task, tasks_root: Path) -> dict[str, str]:
    """Hash of each file defining a task, keyed by its path relative to the tasks root."""
    return {path.relative_to(tasks_root).as_posix(): file_hash(path) for path in task.definition_files()}


def build_manifest(tasks_root: str | Path = DEFAULT_TASKS_ROOT, frozen_on: date | None = None) -> dict[str, Any]:
    """The manifest for every task under tasks_root."""
    root = Path(tasks_root)
    tasks: dict[str, Any] = {}
    files: dict[str, str] = {}
    for task in all_tasks(root):
        hashes = _file_hashes(task, root)
        files.update(hashes)
        tasks[task.id] = {"split": task.spec.split, "files": sorted(hashes)}
    return {
        "frozen_on": (frozen_on or date.today()).isoformat(),
        "hash_rule": HASH_RULE,
        "fingerprint": fingerprint(files),
        "tasks": tasks,
        "files": dict(sorted(files.items())),
    }


def fingerprint(files: dict[str, str]) -> str:
    """One hash for a whole set of files: changes if any file, name or hash changes."""
    lines = "".join(f"{path}\t{digest}\n" for path, digest in sorted(files.items()))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def write_manifest(manifest: dict[str, Any], path: str | Path = DEFAULT_MANIFEST) -> None:
    Path(path).write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))


def read_manifest(path: str | Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FreezeError(f"No freeze manifest at {path}. The suite isn't frozen (see FREEZE.md).") from None
    except json.JSONDecodeError as problem:
        raise FreezeError(f"{path} isn't valid JSON: {problem}") from None


def check_tasks(tasks: Iterable[Task], manifest: dict[str, Any], tasks_root: str | Path = DEFAULT_TASKS_ROOT) -> FreezeCheck:
    """Compare these tasks' files (and their datasets') with the manifest."""
    root = Path(tasks_root)
    frozen: dict[str, str] = manifest["files"]
    modified: set[str] = set()
    for task in tasks:
        current = _file_hashes(task, root)
        expected_paths = set(manifest["tasks"].get(task.id, {}).get("files", []))
        if task.id not in manifest["tasks"]:
            modified.update(current)  # a task added after the freeze
        for path, digest in current.items():
            if frozen.get(path) != digest:
                modified.add(path)
        modified.update(expected_paths - set(current))  # removed since the freeze
    return FreezeCheck(manifest_fingerprint=manifest["fingerprint"], modified=sorted(modified))
