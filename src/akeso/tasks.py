"""Task descriptions: each task folder has a task.yaml saying what the task is and how it's graded.

A task folder looks like:
    task.yaml          what this file describes
    README.md          the spec the agent sees
    src/ ...           the broken code (editable_paths)
    tests/ ...         the visible tests the agent can run
    hidden_tests/ ...  extra tests used only for grading (never shown to the agent)
    solution/ ...      the reference fix, laid out like the task (never shown to the agent)

A SQL task (kind: sql) has a `sql:` block instead, and its only editable file is
solution.sql (the broken query); solution/solution.sql is the gold query. Its data comes
from a shared dataset in tasks/datasets/<name>/ (see datasets.py), built from a seed.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from akeso.datasets import DATASETS_FOLDER, Dataset, DatasetError, load_dataset
from akeso.paths import UnsafePathError, safe_relative_path

TASK_FILE = "task.yaml"
DEFAULT_TASKS_ROOT = Path("tasks")
SQL_SOLUTION_FILE = "solution.sql"  # the one file a SQL task's agent may edit


class TaskError(Exception):
    """A task.yaml is missing, unreadable, or invalid. The message names the file and the problem."""


class SqlSpec(BaseModel):
    """The `sql:` block of a SQL task."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)  # what solution.sql must answer
    # The date the question is asked on. Fixed, so results never depend on when a run happens.
    as_of: date
    dataset: str = Field(pattern=r"^[a-z0-9][a-z0-9_]*$")  # a folder in tasks/datasets/
    seed: int  # builds the visible database the agent works with
    hidden_seed: int  # builds the grading-only database; never enters the agent's sandbox
    order_matters: bool = False  # compare rows in order (only when the question asks for an order)
    float_precision: int = Field(default=2, ge=0, le=10)  # decimal places floats are rounded to when comparing

    @field_validator("as_of", mode="before")
    @classmethod
    def _as_of_is_fixed(cls, value: object) -> object:
        if isinstance(value, str) and value.strip().lower() in ("today", "now", "current_date"):
            raise ValueError("must be a fixed date such as 2026-06-30, never today")
        return value

    @model_validator(mode="after")
    def _seeds_differ(self) -> SqlSpec:
        if self.seed == self.hidden_seed:
            raise ValueError("hidden_seed must differ from seed, or the hidden database can't catch anything")
        return self


class TaskSpec(BaseModel):
    """The contents of one task.yaml, validated."""

    # extra="forbid": a misspelled field is an error, not silently ignored.
    # validate_default: defaults go through the same validators (e.g. "src/" -> "src").
    model_config = ConfigDict(extra="forbid", validate_default=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]*$")
    kind: Literal["code", "sql"]
    description: str = Field(min_length=1)
    check_command: str = "python -m pytest -q -p no:cacheprovider"
    editable_paths: list[str] = Field(default_factory=lambda: ["src/"], min_length=1)
    hidden_tests_dir: str = "hidden_tests"
    solution_dir: str = "solution"
    split: Literal["dev", "heldout"]
    tags: list[str] = Field(default_factory=list)
    sql: SqlSpec | None = None  # required for kind: sql, not allowed for kind: code

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

    @model_validator(mode="after")
    def _kind_specific_fields(self) -> TaskSpec:
        if self.kind == "code":
            if self.sql is not None:
                raise ValueError("a 'sql' block is only for kind: sql")
            return self
        if self.sql is None:
            raise ValueError("kind: sql needs a 'sql' block (question, as_of, dataset, seed, hidden_seed)")
        if self.editable_paths != [SQL_SOLUTION_FILE]:
            raise ValueError(f"a SQL task's editable_paths must be exactly [{SQL_SOLUTION_FILE}]")
        if "check_command" in self.model_fields_set:
            raise ValueError("SQL tasks don't take a check_command: they're checked against the gold query")
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

    @property
    def sql(self) -> SqlSpec:
        """The `sql:` block (SQL tasks only)."""
        if self.spec.sql is None:
            raise TaskError(f"{self.id} is a {self.spec.kind} task, not a SQL task.")
        return self.spec.sql

    @property
    def dataset(self) -> Dataset:
        """The shared dataset a SQL task uses, from tasks/datasets/<name>/."""
        return load_dataset(self.sql.dataset, self.root.parent.parent / DATASETS_FOLDER)

    def definition_files(self) -> list[Path]:
        """Every file that defines this task, including a SQL task's shared dataset, so a
        fingerprint of these changes whenever anything that affects the task changes."""
        files = [p for p in self.root.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
        if self.spec.kind == "sql":
            files += self.dataset.files()
        return sorted(files)

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
    task = Task(spec=spec, root=root)
    if spec.kind == "sql":
        try:
            task.dataset
        except DatasetError as problem:
            raise TaskError(f"{path}: {problem}") from None
    return task


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
