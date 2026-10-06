"""Grading: decide whether a task was solved, in a brand-new environment the agent never touched.

1. collect_changes: compare the agent's environment with the pristine task and keep only
   regular files inside the task's editable paths. Everything else stays behind.
2. grade: start a fresh environment from the pristine task, apply only those changes, run
   the visible tests, then add the hidden tests and run them.

Nothing the agent left in its own environment (running processes, caches, edited config)
can reach the fresh one, so it can't influence the verdict.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from akeso.checks import CheckResult, trim_output
from akeso.environment import EnvError, Environment
from akeso.paths import is_excluded_task_file
from akeso.tasks import Task

GRADE_OUTPUT_LIMIT = 3000  # characters of test output kept in a grade


class Verdict(str, Enum):
    PASSED = "passed"  # visible and hidden tests pass, and no tampering
    FAILED = "failed"
    TAMPERED = "tampered"  # the agent tried to change how it's judged; always a failure


@dataclass(frozen=True)
class TamperFinding:
    """One tampering attempt: what kind, which file, and why it counts."""

    kind: str
    path: str
    detail: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.path} ({self.detail})"


@dataclass
class ChangeSet:
    """The agent's changes, split into what grading will apply and what it won't."""

    written: dict[str, str] = field(default_factory=dict)  # editable files added or modified
    deleted: list[str] = field(default_factory=list)  # editable files removed
    ignored: list[str] = field(default_factory=list)  # changes not carried into grading
    findings: list[TamperFinding] = field(default_factory=list)  # tampering detected


@dataclass(frozen=True)
class GradeResult:
    verdict: Verdict
    visible_passed: bool
    hidden_passed: bool | None  # None when the task has no hidden tests
    applied: list[str]  # files written or deleted in the grading environment
    tampering: list[TamperFinding]
    visible_output: str
    hidden_output: str


def pristine_files(task: Task) -> dict[str, str]:
    """The task's files exactly as the agent first saw them (private folders excluded)."""
    return {
        rel: path.read_bytes().decode("utf-8", errors="replace")  # bytes: keep line endings as stored
        for path in sorted(task.root.rglob("*"))
        if path.is_file() and not is_excluded_task_file(rel := path.relative_to(task.root).as_posix(), task.private_dirs)
    }


def collect_changes(env: Environment, task: Task) -> ChangeSet:
    """What the agent changed in env, compared with the pristine task."""
    original = pristine_files(task)
    changes = ChangeSet()
    current = env.list_files()  # regular files only; links are never collected

    for rel in current:
        try:
            content = env.read_file(rel)
        except EnvError as problem:  # e.g. too large to read
            changes.ignored.append(rel)
            changes.findings.append(TamperFinding("unreadable", rel, str(problem)))
            continue
        if original.get(rel) == content:
            continue
        if task.is_editable(rel):
            changes.written[rel] = content
        else:
            changes.ignored.append(rel)

    for rel in sorted(set(original) - set(current)):
        if task.is_editable(rel):
            changes.deleted.append(rel)
        else:
            changes.ignored.append(rel)
    return changes


def grade(task: Task, changes: ChangeSet, make_environment: Callable[[], Environment]) -> GradeResult:
    """Apply the agent's allowed changes to a fresh copy of the task and run all its tests."""
    hidden_root = task.root / task.spec.hidden_tests_dir
    hidden_files = sorted(p for p in hidden_root.rglob("*") if p.is_file()) if hidden_root.is_dir() else []

    with make_environment() as env:
        env.start(task.root, task.private_dirs)
        env.check_command = task.check_command
        for rel in changes.deleted:
            env.delete_file(rel)
        for rel, content in changes.written.items():
            env.write_file(rel, content)

        visible = env.run_checks()  # before the hidden tests exist, so it runs only visible ones
        hidden: CheckResult | None = None
        if hidden_files:
            for path in hidden_files:
                rel = path.relative_to(task.root).as_posix()
                env.write_file(rel, path.read_bytes().decode("utf-8"))
            hidden = env.run_checks(command=[*task.check_command, task.spec.hidden_tests_dir])

    hidden_passed = None if hidden is None else hidden.passed
    if changes.findings:
        verdict = Verdict.TAMPERED
    elif visible.passed and hidden_passed is not False:
        verdict = Verdict.PASSED
    else:
        verdict = Verdict.FAILED
    return GradeResult(
        verdict=verdict,
        visible_passed=visible.passed,
        hidden_passed=hidden_passed,
        applied=sorted([*changes.written, *changes.deleted]),
        tampering=list(changes.findings),
        visible_output=trim_output(visible.output, GRADE_OUTPUT_LIMIT),
        hidden_output=trim_output(hidden.output, GRADE_OUTPUT_LIMIT) if hidden else "",
    )
