"""Task descriptions: each task folder has a task.yaml saying what the task is and how it's graded.

A task folder looks like:
    task.yaml          what this file describes
    README.md          the spec the agent sees
    src/ ...           the broken code (editable_paths)
    tests/ ...         the visible tests the agent can run
    hidden_tests/ ...  extra tests used only for grading (never shown to the agent)
    solution/ ...      the reference fix, laid out like the task (never shown to the agent)
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from akeso.paths import UnsafePathError, safe_relative_path

TASK_FILE = "task.yaml"
DEFAULT_TASKS_ROOT = Path("tasks")


class TaskError(Exception):
    """A task.yaml is missing, unreadable, or invalid. The message names the file and the problem."""


class TaskSpec(BaseModel):
    """The contents of one task.yaml, validated."""

    # extra="forbid": a misspelled field is an error, not silently ignored.
    # validate_default: defaults go through the same validators (e.g. "src/" -> "src").
    model_config = ConfigDict(extra="forbid", validate_default=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]*$")
    kind: Literal["code", "sql"]  # only "code" can run today; "sql" is reserved for later
    description: str = Field(min_length=1)
    check_command: str = "python -m pytest -q -p no:cacheprovider"
    editable_paths: list[str] = Field(default_factory=lambda: ["src/"], min_length=1)
    hidden_tests_dir: str = "hidden_tests"
    solution_dir: str = "solution"
    split: Literal["dev", "heldout"]
    tags: list[str] = Field(default_factory=list)

    @field_validator("check_command")
    @classmethod
    def _command_parses(cls, value: str) -> str:
        if not shlex.split(value):
            raise ValueError("must not be empty")
        return value

    @field_validator("editable_paths")
    @classmethod
    def _editable_paths_are_safe(cls, paths: list[str]) -> list[str]:
        cleaned = []
        for path in paths:
            try:
                rel = safe_relative_path(path)
            except UnsafePathError as problem:
                raise ValueError(str(problem)) from None
            if rel == PurePosixPath("."):
                raise ValueError("the whole task can't be editable; name a folder such as 'src/'")
            cleaned.append(rel.as_posix())
        return cleaned

    @field_validator("hidden_tests_dir", "solution_dir")
    @classmethod
    def _private_dir_is_top_level_name(cls, value: str) -> str:
        if not value or "/" in value or "\\" in value or value in (".", ".."):
            raise ValueError("must be a single top-level folder name, e.g. 'hidden_tests'")
        return value

    @model_validator(mode="after")
    def _private_dirs_not_editable(self) -> TaskSpec:
        # If the agent could edit the hidden tests or the solution, grading would be meaningless.
        protected = {self.hidden_tests_dir, self.solution_dir, "tests"}
        for path in self.editable_paths:
            if PurePosixPath(path).parts[0] in protected:
                raise ValueError(f"editable path {path!r} overlaps tests, hidden tests or the solution")
        return self


@dataclass(frozen=True)
class Task:
    """A loaded task: its validated spec and where its folder is."""

    spec: TaskSpec
    root: Path

    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def private_dirs(self) -> tuple[str, str]:
        """Folders that must never be copied into the agent's sandbox."""
        return (self.spec.hidden_tests_dir, self.spec.solution_dir)

    @property
    def check_command(self) -> list[str]:
        return shlex.split(self.spec.check_command)

    def is_editable(self, rel_path: str) -> bool:
        """True if rel_path is inside one of the task's editable paths."""
        parts = PurePosixPath(rel_path).parts
        return any(parts[: len(PurePosixPath(p).parts)] == PurePosixPath(p).parts for p in self.spec.editable_paths)


def load_task(task_dir: str | Path) -> Task:
    """Load and validate task_dir/task.yaml. Raises TaskError with a readable explanation."""
    root = Path(task_dir)
    path = root / TASK_FILE
    if not path.is_file():
        raise TaskError(f"{path}: not found. Every task folder needs a {TASK_FILE}.")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as problem:
        raise TaskError(f"{path}: not valid YAML ({problem}).") from None
    if not isinstance(data, dict):
        raise TaskError(f"{path}: must contain a mapping of fields (id, kind, description, ...).")
    try:
        spec = TaskSpec.model_validate(data)
    except ValidationError as problem:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'task'}: {error['msg']}"
            for error in problem.errors()
        )
        raise TaskError(f"{path}: {details}") from None
    if spec.id != root.name:
        raise TaskError(f"{path}: id {spec.id!r} must match the folder name {root.name!r}.")
    return Task(spec=spec, root=root)


def find_task(task_id: str, tasks_root: str | Path = DEFAULT_TASKS_ROOT) -> Task:
    """Find a task by id anywhere under tasks_root (e.g. tasks/code/c001_mean)."""
    matches = [path.parent for path in Path(tasks_root).glob(f"*/{task_id}/{TASK_FILE}")]
    if not matches:
        raise TaskError(f"No task with id {task_id!r} under {tasks_root}/.")
    if len(matches) > 1:
        raise TaskError(f"Task id {task_id!r} is used more than once: {', '.join(map(str, matches))}.")
    return load_task(matches[0])


def all_tasks(tasks_root: str | Path = DEFAULT_TASKS_ROOT) -> list[Task]:
    """Every task under tasks_root, sorted by id."""
    return sorted((load_task(path.parent) for path in Path(tasks_root).glob(f"*/*/{TASK_FILE}")), key=lambda t: t.id)
