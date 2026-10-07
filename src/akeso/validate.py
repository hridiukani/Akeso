"""Task validation: prove every task is a fair test before any agent attempts it.

For every task:
- no symbolic links anywhere in it (a link could point grading at something else)
- the solution must be graded cleanly (nothing that counts as tampering)

For a code task:
- the untouched broken version must FAIL its visible tests (otherwise there's nothing to fix)
- the reference solution must PASS the visible and the hidden tests
- there must be hidden tests, and their file names must not collide with visible test
  files (pytest refuses two test modules with the same name)

For a SQL task:
- the broken solution.sql must FAIL against the gold query on the visible database
- the gold query must PASS on both the visible and the hidden database
- the gold query must give DIFFERENT results on the two databases, otherwise the hidden
  database can't catch a query tuned to the visible data

Run it with:  akeso validate  (or python -m akeso.validate)
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from akeso.environment import Environment
from akeso.grading import ChangeSet, changes_from_files, grade
from akeso.sandbox import DockerSandbox
from akeso.tasks import Task, all_tasks


@dataclass(frozen=True)
class TaskValidation:
    task_id: str
    broken_failed: bool  # the broken version fails its visible check, as it should
    solution_visible_passed: bool
    solution_hidden_passed: bool | None  # None when the task has no hidden tests
    problems: list[str] = field(default_factory=list)
    kind: str = "code"
    hidden_differs: bool | None = None  # SQL only: the gold result differs on the hidden database

    @property
    def ok(self) -> bool:
        return not self.problems


def solution_files(task: Task) -> dict[str, str]:
    """The reference solution, as task-relative paths (solution/src/x.py -> src/x.py)."""
    root = task.root / task.spec.solution_dir
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes().decode("utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


def symlinks(folder: Path) -> list[str]:
    """Every symbolic link under folder (files or folders), relative to it. Links are never
    followed, so a link to a folder is reported, not walked into."""
    found = []
    for directory, folders, files in os.walk(folder, followlinks=False):
        for name in folders + files:
            path = Path(directory, name)
            if path.is_symlink():
                found.append(path.relative_to(folder).as_posix())
    return sorted(found)


def colliding_test_names(task: Task) -> list[str]:
    """Hidden test files whose names are also used by a visible test file."""

    def test_names(paths: list[Path]) -> set[str]:
        return {p.name for p in paths if p.is_file() and (p.name.startswith("test_") or p.name.endswith("_test.py"))}

    hidden_root = task.root / task.spec.hidden_tests_dir
    hidden = test_names(list(hidden_root.rglob("*.py"))) if hidden_root.is_dir() else set()
    visible = test_names([p for p in task.root.rglob("*.py") if p.relative_to(task.root).parts[0] not in task.private_dirs])
    return sorted(hidden & visible)


def validate_task(task: Task, make_environment: Callable[[], Environment] = DockerSandbox) -> TaskValidation:
    """Check that task is fair (see the module docstring) and report anything that isn't."""
    problems = [f"symbolic link in the task: {link}" for link in symlinks(task.root)]
    if task.spec.kind == "sql":
        problems += [f"symbolic link in dataset {task.dataset.name!r}: {link}" for link in symlinks(task.dataset.root)]
        return _validate_sql(task, make_environment, problems)

    files = solution_files(task)
    if not files:
        problems.append(f"no reference solution in {task.spec.solution_dir}/")
    hidden = task.root / task.spec.hidden_tests_dir
    if not hidden.is_dir() or not any(p.is_file() for p in hidden.rglob("*.py")):
        problems.append(f"no hidden tests in {task.spec.hidden_tests_dir}/")
    for name in colliding_test_names(task):
        problems.append(f"hidden test file {name} has the same name as a visible test file (pytest can't load both)")

    solution = changes_from_files(task, files)
    for finding in solution.findings:
        problems.append(f"the solution itself would count as tampering: {finding}")

    broken = grade(task, ChangeSet(), make_environment)
    if broken.visible_passed:
        problems.append("the broken version already passes its visible tests")

    fixed = grade(task, ChangeSet(written=solution.written), make_environment)
    if not fixed.visible_passed:
        problems.append("the reference solution fails the visible tests")
    if fixed.hidden_passed is False:
        problems.append("the reference solution fails the hidden tests")

    return TaskValidation(
        task_id=task.id,
        broken_failed=not broken.visible_passed,
        solution_visible_passed=fixed.visible_passed,
        solution_hidden_passed=fixed.hidden_passed,
        problems=problems,
    )


def _validate_sql(task: Task, make_environment: Callable[[], Environment], problems: list[str]) -> TaskValidation:
    from akeso.sql_judge import SqlJudgeError, gold_results_differ  # sql_judge imports grading

    files = solution_files(task)
    solution = changes_from_files(task, files)
    for finding in solution.findings:
        problems.append(f"the gold query itself would count as tampering: {finding}")
    try:
        broken = grade(task, ChangeSet(), make_environment)
        fixed = grade(task, ChangeSet(written=solution.written), make_environment)
        hidden_differs = gold_results_differ(task, make_environment)
    except SqlJudgeError as problem:  # e.g. no gold query, or it fails to run
        problems.append(str(problem))
        return TaskValidation(task.id, False, False, None, problems, kind="sql")

    if broken.visible_passed:
        problems.append("the broken solution.sql already matches the gold query on the visible database")
    if not fixed.visible_passed or not fixed.hidden_passed:
        problems.append("the gold query doesn't pass its own check (is the comparison precision too strict?)")
    if not hidden_differs:
        problems.append("the gold query gives the same result on the hidden database as on the visible one, "
                        "so the hidden database can't catch anything (choose another hidden_seed)")
    return TaskValidation(
        task_id=task.id,
        broken_failed=not broken.visible_passed,
        solution_visible_passed=fixed.visible_passed,
        solution_hidden_passed=fixed.hidden_passed,
        problems=problems,
        kind="sql",
        hidden_differs=hidden_differs,
    )


def format_report(results: Sequence[TaskValidation]) -> str:
    """A per-task report, one block per task, plus a total."""
    lines = []
    for r in results:
        status = "OK  " if r.ok else "FAIL"
        broken = f"broken: {'fails' if r.broken_failed else 'PASSES'}"
        if r.kind == "sql":
            hidden = "pass" if r.solution_hidden_passed else "FAIL"
            differs = {True: "yes", False: "NO", None: "?"}[r.hidden_differs]
            lines.append(
                f"{status}  {r.task_id:<22} {broken}   gold: visible db {'pass' if r.solution_visible_passed else 'FAIL'}, "
                f"hidden db {hidden}   hidden db gives a different answer: {differs}"
            )
        else:
            hidden = {True: "pass", False: "FAIL", None: "none"}[r.solution_hidden_passed]
            lines.append(
                f"{status}  {r.task_id:<22} {broken}   "
                f"solution: visible {'pass' if r.solution_visible_passed else 'FAIL'}, hidden {hidden}"
            )
        lines += [f"      - {problem}" for problem in r.problems]
    valid = sum(r.ok for r in results)
    lines.append(f"\n{valid}/{len(results)} tasks valid")
    return "\n".join(lines)


def main() -> int:
    results = [validate_task(task) for task in all_tasks()]
    print(format_report(results))
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
