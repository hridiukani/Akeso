"""The `akeso` command-line tool.

    akeso run --suite smoke [--model M] [--max-steps N] [--max-cost USD] [--run-id ID]
    akeso validate [--suite smoke]
    akeso trace RUN_ID TASK_ID [--full]
    akeso cleanup [--all]
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import replace
from functools import wraps
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console
from rich.table import Table

from akeso.batch import run_tasks
from akeso.config import PRICES, ConfigError, Settings, load_settings
from akeso.grading import Verdict
from akeso.sandbox import LEFTOVER_MAX_AGE, SandboxError, cleanup_leftover_containers
from akeso.suites import SuiteError, load_suite
from akeso.tasks import TaskError, all_tasks, find_task
from akeso.trace import DEFAULT_TRACE_DIR, read_trace, trace_path
from akeso.trace_view import story
from akeso.validate import format_report, validate_task

app = typer.Typer(
    help="Akeso: a sandboxed agent that repairs code, with a measured eval suite.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

_VERDICT_STYLE = {Verdict.PASSED: "green", Verdict.FAILED: "red", Verdict.TAMPERED: "bold magenta"}


@app.callback()
def _setup() -> None:
    # Windows consoles default to a legacy code page; test output contains characters
    # (like pytest's plus-minus sign) that would otherwise print as garbage.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def _friendly_errors(command: Callable[..., Any]) -> Callable[..., Any]:
    """Turn expected problems (bad settings, unknown suite, Docker down) into a clear message."""

    @wraps(command)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return command(*args, **kwargs)
        except (ConfigError, SuiteError, TaskError, SandboxError) as problem:
            console.print(f"[red]Error:[/red] {problem}")
            raise typer.Exit(code=1) from None

    return wrapper


def _with_model(settings: Settings, model: str) -> Settings:
    """Settings using `model` for the active provider (it must have a price, like any model)."""
    if model not in PRICES:
        raise ConfigError(f"Model {model!r} has no entry in PRICES; add its price in config.py first.")
    field = "groq_model" if settings.provider == "groq" else "anthropic_model"
    return replace(settings, **{field: model})


@app.command()
@_friendly_errors
def run(
    suite: str = typer.Option(..., "--suite", help="Suite name: runs the task ids in suites/<name>.yaml."),
    model: Optional[str] = typer.Option(None, "--model", help="Model to use for the active provider."),
    max_steps: Optional[int] = typer.Option(None, "--max-steps", min=1, help="Maximum model calls per task."),
    max_cost: Optional[float] = typer.Option(None, "--max-cost", min=0.0, help="Maximum cost per task, in dollars."),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Name for the run folder (default: timestamp)."),
) -> None:
    """Run the agent on every task in a suite and print the results."""
    task_ids = load_suite(suite)
    for task_id in task_ids:
        find_task(task_id)  # report a bad suite before spending anything
    settings = load_settings()
    if model:
        settings = _with_model(settings, model)
    limits = settings.limits
    if max_steps is not None:
        limits = replace(limits, max_steps=max_steps)
    if max_cost is not None:
        limits = replace(limits, max_cost_usd=max_cost)

    console.print(f"Running suite [bold]{suite}[/bold] ({len(task_ids)} tasks) on {settings.provider} / {settings.model}")
    summary = run_tasks(
        task_ids, run_id=run_id, settings=settings, limits=limits,
        on_result=lambda r: console.print(f"  {r.task_id}: [{_VERDICT_STYLE[r.verdict]}]{r.verdict.value}[/]"),
    )

    table = Table(title=f"Run {summary.run_id}")
    for column, justify in (("Task", "left"), ("Verdict", "left"), ("Steps", "right"),
                            ("Tokens", "right"), ("Cost", "right"), ("Stop reason", "left")):
        table.add_column(column, justify=justify)
    for r in summary.results:
        table.add_row(
            r.task_id, f"[{_VERDICT_STYLE[r.verdict]}]{r.verdict.value}[/]", str(r.steps),
            f"{r.input_tokens + r.output_tokens:,}", f"${r.cost_usd:.4f}", r.stop_reason.value,
        )
    console.print(table)

    t = summary.totals
    console.print(
        f"Passed {t['passed']}/{t['tasks']} ({t['pass_rate']:.0%})"
        + (f", tampered {t['tampered']}" if t["tampered"] else "")
        + f" | average steps {t['average_steps']:.1f}"
        + f" | total tokens {t['total_input_tokens'] + t['total_output_tokens']:,}"
        + f" | total cost ${t['total_cost_usd']:.4f}"
    )
    console.print(f"Run folder: {summary.run_dir}")


@app.command()
@_friendly_errors
def validate(
    suite: Optional[str] = typer.Option(None, "--suite", help="Only the tasks in this suite (default: every task)."),
) -> None:
    """Check every task is fair: broken version fails, reference solution passes (in Docker)."""
    tasks = [find_task(task_id) for task_id in load_suite(suite)] if suite else all_tasks()
    results = []
    for task in tasks:
        with console.status(f"Validating {task.id}..."):
            results.append(validate_task(task))
    console.print(format_report(results), highlight=False)
    if not all(r.ok for r in results):
        raise typer.Exit(code=1)


@app.command()
def trace(
    run_id: str = typer.Argument(..., help="The run's ID (its folder name under runs/)."),
    task_id: str = typer.Argument(..., help="The task to show."),
    full: bool = typer.Option(False, "--full", help="Show complete outputs instead of previews."),
    runs_dir: Path = typer.Option(DEFAULT_TRACE_DIR, "--runs-dir", help="Where run folders live."),
) -> None:
    """Show one task's trace as a step-by-step story."""
    path = trace_path(runs_dir, run_id, task_id)
    if not path.is_file():
        console.print(f"[red]Error:[/red] no trace at {path}")
        raise typer.Exit(code=1)
    # Plain print: trace text contains brackets that rich would read as markup.
    print(story(read_trace(path), full=full))


@app.command()
@_friendly_errors
def cleanup(
    all_: bool = typer.Option(False, "--all", help="Remove every Akeso container, even ones in use."),
) -> None:
    """Remove leftover sandbox containers (by default only ones older than an hour)."""
    removed = cleanup_leftover_containers(max_age=None if all_ else LEFTOVER_MAX_AGE)
    scope = "any age" if all_ else f"older than {LEFTOVER_MAX_AGE}"
    if removed:
        console.print(f"Removed {len(removed)} container(s) ({scope}): {', '.join(removed)}")
    else:
        console.print(f"No leftover containers ({scope}).")
