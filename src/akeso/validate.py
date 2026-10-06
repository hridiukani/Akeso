"""Task validation: prove every task is a fair test before any agent attempts it.

For each task:
- the untouched broken version must FAIL its visible tests (otherwise there's nothing to fix)
- the reference solution must PASS the visible and the hidden tests
- the task must have a solution and hidden tests, and the solution must be graded cleanly
  (no changes outside the editable paths, nothing that counts as tampering)

Run it with:  python -m akeso.validate
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from akeso.environment import Environment
from akeso.grading import ChangeSet, changes_from_files, grade
from akeso.sandbox import DockerSandbox
from akeso.tasks import Task, all_tasks


@dataclass(frozen=True)
class TaskValidation:
    task_id: str
    broken_failed: bool  # the broken version fails its visible tests, as it should
    solution_visible_passed: bool
    solution_hidden_passed: bool | None  # None when the task has no hidden tests
    problems: list[str] = field(default_factory=list)

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


def validate_task(task: Task, make_environment: Callable[[], Environment] = DockerSandbox) -> TaskValidation:
    """Grade the broken version and the reference solution; report anything unfair."""
    problems: list[str] = []
    files = solution_files(task)
    if not files:
        problems.append(f"no reference solution in {task.spec.solution_dir}/")
    hidden = task.root / task.spec.hidden_tests_dir
    if not hidden.is_dir() or not any(p.is_file() for p in hidden.rglob("*.py")):
        problems.append(f"no hidden tests in {task.spec.hidden_tests_dir}/")

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


def format_report(results: Sequence[TaskValidation]) -> str:
    """A per-task report, one block per task, plus a total."""
    lines = []
    for r in results:
        hidden = {True: "pass", False: "FAIL", None: "none"}[r.solution_hidden_passed]
        lines.append(
            f"{'OK  ' if r.ok else 'FAIL'}  {r.task_id:<16} "
            f"broken: {'fails' if r.broken_failed else 'PASSES'}   "
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
