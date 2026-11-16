"""The `akeso` command-line tool.

    akeso run --suite smoke [--model M] [--max-steps N] [--max-cost USD] [--run-id ID] [--allow-modified]
    akeso run --suite full --official [--yes] [--repeats N]
    akeso run --suite smoke --mode oneshot
    akeso run --suite full --include-heldout   (a dev run that may include held-out tasks)
    akeso run --resume RUN_ID [--yes]
    akeso compare RUN_A RUN_B
    akeso report RUN_ID
    akeso trace RUN_ID TASK_ID [--repeat N]
    akeso validate [--suite smoke]
    akeso freeze
    akeso trace RUN_ID TASK_ID [--full]
    akeso cleanup [--all]
"""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from functools import wraps
from pathlib import Path
from typing import Any, NoReturn, Optional

import typer
from rich.console import Console
from rich.table import Table

from akeso import fingerprint as run_fingerprint
from akeso.agent import AgentResult
from akeso.batch import (
    MODES, SUMMARY_FILE, ResumeError, RunSummary, load_for_resume, planned_attempts, resume_differences, resume_tasks, run_tasks,
    saved_mode, split_attempts,
)
from akeso.compare import CompareError, compare_runs
from akeso.config import PRICES, ConfigError, Settings, load_settings
from akeso.failures import LabelsError
from akeso.freeze import (
    DEFAULT_MANIFEST, FreezeCheck, FreezeError, build_manifest, check_tasks, read_manifest, write_manifest,
)
from akeso.grading import Verdict
from akeso.official import OFFICIAL_REPEATS, estimate, official_problems
from akeso.report import REPORT_FILE, write_report
from akeso.sandbox import LEFTOVER_MAX_AGE, SandboxError, cleanup_leftover_containers, image_digest
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
        except (ConfigError, SuiteError, TaskError, SandboxError, FreezeError) as problem:
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
    suite: Optional[str] = typer.Option(None, "--suite", help="Suite name: runs the task ids in suites/<name>.yaml."),
    model: Optional[str] = typer.Option(None, "--model", help="Model to use for the active provider."),
    max_steps: Optional[int] = typer.Option(None, "--max-steps", min=1, help="Maximum model calls per task."),
    max_cost: Optional[float] = typer.Option(None, "--max-cost", min=0.0, help="Maximum cost per task, in dollars."),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Name for the run folder (default: timestamp)."),
    allow_modified: bool = typer.Option(
        False, "--allow-modified", help="Run even if task files changed since the freeze (recorded in the results)."),
    official: bool = typer.Option(
        False, "--official", help="An official (reportable) run: measurement setup, frozen suite, clean tree."),
    yes: bool = typer.Option(False, "--yes", help="Don't ask for confirmation before an official run."),
    repeats: Optional[int] = typer.Option(
        None, "--repeats", min=1, help="Attempts per task, each in fresh sandboxes (default 1; official runs 3)."),
    resume: Optional[str] = typer.Option(
        None, "--resume", help="Finish run RUN_ID: rerun only its missing and crashed attempts, same setup."),
    mode: Optional[str] = typer.Option(
        None, "--mode", help="loop (default): the agent with tools; oneshot: a single model call, same grading."),
    include_heldout: bool = typer.Option(
        False, "--include-heldout", help="Let a dev (non-official) run include held-out tasks."),
) -> None:
    """Run the agent on every task in a suite and print the results."""
    if resume:
        clashing = [name for name, value in (("--suite", suite), ("--model", model), ("--max-steps", max_steps),
                                             ("--max-cost", max_cost), ("--run-id", run_id), ("--repeats", repeats),
                                             ("--official", official or None), ("--mode", mode)) if value is not None]
        if clashing:
            _fail(f"{', '.join(clashing)} can't be used with --resume: a resumed run keeps its original setup.")
        _resume(resume, allow_modified=allow_modified, yes=yes, include_heldout=include_heldout)
        return
    if not suite:
        _fail("Pass --suite NAME (or --resume RUN_ID).")
    mode = mode or "loop"
    if mode not in MODES:
        _fail(f"--mode must be one of: {', '.join(MODES)}.")
    task_ids = load_suite(suite)
    tasks = [find_task(task_id) for task_id in task_ids]  # report a bad suite before spending anything
    if not official:
        _refuse_heldout(tasks, include_heldout)
    settings = load_settings()
    if model:
        settings = _with_model(settings, model)
    limits = settings.limits
    if max_steps is not None:
        limits = replace(limits, max_steps=max_steps)
    if max_cost is not None:
        limits = replace(limits, max_cost_usd=max_cost)
    fingerprint = run_fingerprint.collect(settings, limits, mode=mode, docker_image=image_digest())
    repeats = repeats or (OFFICIAL_REPEATS if official else 1)
    overrides = [name for name, value in (("--model", model), ("--max-steps", max_steps), ("--max-cost", max_cost))
                 if value is not None]
    check = _check_before_running(
        tasks, settings, limits, fingerprint, official=official, allow_modified=allow_modified, overrides=overrides,
        attempts=[(task_id, repeat) for repeat in range(1, repeats + 1) for task_id in task_ids], yes=yes,
        heading=f"Official {mode} run of [bold]{suite}[/bold]: {len(task_ids)} task(s) x {repeats} repeat(s)",
    )
    freeze = {"manifest_fingerprint": check.manifest_fingerprint, "allow_modified": allow_modified,
              "modified_files": check.modified}
    run_type = "official" if official else "dev"

    console.print(f"Running suite [bold]{suite}[/bold] ({len(task_ids)} tasks x {repeats} repeat(s), {mode} mode) on "
                  f"{settings.provider} / {settings.model} [bold]({run_type} run)[/bold]", soft_wrap=True)
    summary = run_tasks(
        task_ids, run_id=run_id, settings=settings, limits=limits, freeze=freeze,
        fingerprint=fingerprint, run_type=run_type, repeats=repeats, mode=mode, on_result=_progress(repeats),
    )
    _print_summary(summary, settings.cost_basis, run_type)


def _resume(run_id: str, *, allow_modified: bool, yes: bool, include_heldout: bool = False) -> None:
    """akeso run --resume RUN_ID: the same checks as a fresh run, against the run's own setup."""
    try:
        saved = load_for_resume(run_id, DEFAULT_TRACE_DIR)
    except ResumeError as problem:
        _fail(str(problem))
    settings = load_settings()
    limits = settings.limits
    fingerprint = run_fingerprint.collect(settings, limits, mode=saved_mode(saved), docker_image=image_digest())
    changed = resume_differences(saved, fingerprint)
    if changed:
        console.print(f"[red]Error:[/red] run {run_id} can't be resumed: the setup has changed since it started, "
                      "and resuming would mix two experiments:", highlight=False, soft_wrap=True)
        for line in changed:
            console.print(f"  - {line}", highlight=False, soft_wrap=True)
        raise typer.Exit(code=1)
    kept, todo = split_attempts(saved)
    if not todo:
        console.print(f"Run {run_id} is already complete; nothing to resume.")
        return
    run_type = saved.get("run_type") or "dev"
    task_ids = list(dict.fromkeys(task_id for task_id, _ in planned_attempts(saved)))
    tasks = [find_task(task_id) for task_id in task_ids]
    if run_type != "official":
        _refuse_heldout(tasks, include_heldout)
    allow_modified = allow_modified or bool((saved.get("freeze") or {}).get("allow_modified"))
    _check_before_running(
        tasks, settings, limits, fingerprint, official=run_type == "official", allow_modified=allow_modified,
        overrides=[], attempts=todo, yes=yes, heading=f"Resuming official run [bold]{run_id}[/bold]: {len(todo)} attempt(s)",
    )
    repeats = saved.get("repeats") or 1
    console.print(f"Resuming run [bold]{run_id}[/bold] [bold]({run_type} run)[/bold]: {len(kept)} attempt(s) kept, "
                  f"{len(todo)} to run", soft_wrap=True)
    summary = resume_tasks(run_id, fingerprint=fingerprint, settings=settings, limits=limits,
                           on_result=_progress(repeats))
    _print_summary(summary, settings.cost_basis, run_type)


def _refuse_heldout(tasks: list[Any], include_heldout: bool) -> None:
    """Held-out tasks are for official runs: a dev run that touches them risks tuning on
    them, so it needs --include-heldout."""
    heldout = [task.id for task in tasks if task.spec.split == "heldout"]
    if heldout and not include_heldout:
        _fail(f"{len(heldout)} held-out task(s) in a dev run: {', '.join(heldout)}. Held-out tasks are kept for "
              "official runs; pass --include-heldout to run them anyway.")


def _check_before_running(
    tasks: list[Any], settings: Settings, limits: Any, fingerprint: dict[str, Any], *, official: bool,
    allow_modified: bool, overrides: list[str], attempts: list[tuple[str, int]], yes: bool, heading: str,
) -> FreezeCheck:
    """Refuse modified tasks (unless allowed); for an official run, refuse anything but the
    measurement setup, then show an estimate and ask for confirmation."""
    if official:
        try:
            check: FreezeCheck | None = check_tasks(tasks, read_manifest())
        except FreezeError:
            check = None
        problems = official_problems(settings, limits, check, fingerprint, allow_modified=allow_modified, overrides=overrides)
        if problems:
            console.print("[red]Error:[/red] this can't be an official run:", highlight=False)
            for problem in problems:
                console.print(f"  - {problem}", highlight=False, soft_wrap=True)
            raise typer.Exit(code=1)
        assert check is not None
        guess = estimate([task_id for task_id, _ in attempts], settings.model, DEFAULT_TRACE_DIR,
                         mode=fingerprint.get("mode") or "loop")
        console.print(
            f"{heading} on {settings.provider} ({settings.tier} tier) / {settings.model}.\n"
            f"Estimated: about {guess.tokens:,} tokens ({guess.input_tokens:,} in, {guess.output_tokens:,} out), "
            f"about ${guess.cost_usd:.2f} at list prices, assuming no cache hits "
            f"({guess.tasks_with_history} of {guess.tasks} attempt estimates come from earlier runs).",
            highlight=False, soft_wrap=True,
        )
        if not yes and not typer.confirm("Start the official run?", default=False):
            console.print("Cancelled; nothing was run.")
            raise typer.Exit(code=1)
        return check
    check = check_tasks(tasks, read_manifest())
    if not check.ok and not allow_modified:
        listed = "\n  ".join(check.modified[:20]) + ("\n  ..." if len(check.modified) > 20 else "")
        console.print(f"[red]Error:[/red] {len(check.modified)} task file(s) changed since the freeze "
                      f"({DEFAULT_MANIFEST}):\n  {listed}\nTasks are frozen (see FREEZE.md). "
                      "Pass --allow-modified to run anyway; the run's results will record it.", highlight=False)
        raise typer.Exit(code=1)
    if not check.ok:
        console.print(f"[yellow]Warning:[/yellow] running with {len(check.modified)} task file(s) changed since the freeze.")
    return check


def _progress(repeats: int) -> Callable[[AgentResult], None]:
    return lambda r: console.print(
        f"  {r.task_id}" + (f" (repeat {r.repeat})" if repeats > 1 else "")
        + f": [{_VERDICT_STYLE[r.verdict]}]{r.verdict.value}[/]")


def _fail(message: str) -> NoReturn:
    console.print(f"[red]Error:[/red] {message}", highlight=False, soft_wrap=True)
    raise typer.Exit(code=1)


def _print_summary(summary: RunSummary, cost_basis: str, run_type: str) -> None:
    """The results table and totals, overall and per split. With repeats, one row per task
    with its solve rate; otherwise one row per attempt."""
    t = summary.totals
    table = Table(title=f"Run {summary.run_id} ({run_type})")
    if t["repeats"] > 1:
        for column, justify in (("Task", "left"), ("Solved", "right"), ("Avg steps", "right"),
                                ("Avg tokens", "right"), ("Avg cost", "right"), ("Stop reasons", "left")):
            table.add_column(column, justify=justify)
        for task_id, rate in t["solve_rates"].items():
            attempts = [r for r in summary.results if r.task_id == task_id]
            stops = Counter(r.stop_reason.value for r in attempts)
            table.add_row(
                task_id, rate, f"{sum(r.steps for r in attempts) / len(attempts):.1f}",
                f"{sum(r.input_tokens + r.output_tokens for r in attempts) / len(attempts):,.0f}",
                f"${sum(r.cost_usd for r in attempts) / len(attempts):.4f}",
                ", ".join(f"{stop} x{n}" if n > 1 else stop for stop, n in sorted(stops.items())),
            )
    else:
        for column, justify in (("Task", "left"), ("Verdict", "left"), ("Steps", "right"),
                                ("Tokens", "right"), ("Cost", "right"), ("Stop reason", "left")):
            table.add_column(column, justify=justify)
        for r in summary.results:
            table.add_row(
                r.task_id, f"[{_VERDICT_STYLE[r.verdict]}]{r.verdict.value}[/]", str(r.steps),
                f"{r.input_tokens + r.output_tokens:,}", f"${r.cost_usd:.4f}", r.stop_reason.value,
            )
    console.print(table)

    console.print(
        f"Passed {t['passed']}/{t['attempts']} attempts ({t['pass_rate']:.0%})"
        + (f", tampered {t['tampered']}" if t["tampered"] else "")
        + (f", stopped by the provider's token limit {t['provider_token_limit']}" if t["provider_token_limit"] else "")
        + f" | average steps {t['average_steps']:.1f}"
        + f" | total tokens {t['total_input_tokens'] + t['total_output_tokens']:,}"
        + f" | total cost ${t['total_cost_usd']:.4f} ({cost_basis})"
        + f" | rate-limit retries {t['total_rate_limit_retries']}"
        + f" | pacing waits {t['total_pacing_waits']} ({t['total_pacing_wait_seconds']:.0f}s)",
        soft_wrap=True,
    )
    groups = [("overall", t)] + list(t.get("by_split", {}).items())
    if t["repeats"] > 1 or len(groups) > 2:
        for name, g in groups:
            if name != "overall" and len(groups) <= 2:
                continue  # a single split repeats the overall line
            console.print(f"  {name}: {_rates(g)} | average steps {g['average_steps']:.1f}"
                          f" | average tokens {g['average_tokens']:,.0f} | total cost ${g['total_cost_usd']:.4f}",
                          soft_wrap=True)
    _print_categories(t)
    if summary.stopped:
        console.print(f"[yellow]Stopped early[/yellow] ({summary.stopped}). {len(summary.not_run)} attempt(s) not run; "
                      f"finish them later with: akeso run --resume {summary.run_id}", highlight=False, soft_wrap=True)
    console.print(f"Run folder: {summary.run_dir}")
    if (summary.run_dir / REPORT_FILE).is_file():
        console.print(f"Report: {summary.run_dir / REPORT_FILE}")


def _print_categories(totals: dict[str, Any]) -> None:
    """Why the failed attempts failed: one row per category, overall and per split."""
    overall = totals.get("failure_categories") or {}
    if not overall:
        return
    splits = {name: g.get("failure_categories", {}) for name, g in totals.get("by_split", {}).items()}
    console.print("Failure categories (failed attempts):")
    table = Table()
    table.add_column("Category")
    table.add_column("All", justify="right")
    for name in splits:
        table.add_column(name, justify="right")
    for category, count in overall.items():
        table.add_row(category, str(count), *(str(counts.get(category, 0)) for counts in splits.values()))
    console.print(table)


def _rates(g: dict[str, Any]) -> str:
    """The pass-rate line for one group: with repeats, mean and spread plus pass@1/pass@k."""
    if g["repeats"] <= 1:
        return f"passed {g['passed']}/{g['attempts']} ({g['pass_rate']:.0%})"
    return (f"pass rate {g['pass_rate_mean']:.0%} +/- {g['pass_rate_std']:.0%} over {g['repeats']} repeats"
            f" | pass@1 {g['pass_at_1']:.0%} | pass@{g['k']} {g['pass_at_k']:.0%}")


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
def freeze() -> None:
    """Write the freeze manifest: a fingerprint of every task and dataset file (see FREEZE.md)."""
    manifest = build_manifest()
    write_manifest(manifest)
    console.print(f"Froze {len(manifest['tasks'])} tasks ({len(manifest['files'])} files) into {DEFAULT_MANIFEST}. "
                  f"Fingerprint: {manifest['fingerprint']}")


@app.command()
@_friendly_errors
def compare(
    run_a: str = typer.Argument(..., help="The baseline run."),
    run_b: str = typer.Argument(..., help="The run compared against it."),
    runs_dir: Path = typer.Option(DEFAULT_TRACE_DIR, "--runs-dir", help="Where run folders live."),
) -> None:
    """Compare run B with run A: pass rates with their spread, the difference with a
    bootstrap interval, steps, tokens and cost, overall and per split."""
    try:
        result = compare_runs(run_a, run_b, runs_dir)
    except CompareError as problem:
        _fail(f"can't compare {run_a} and {run_b}: {problem}")
    for warning in result.warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}", highlight=False, soft_wrap=True)

    table = Table(title=f"Pass rates: {run_b} (B) vs {run_a} (A)")
    for column, justify in (("Group", "left"), ("Tasks", "right"), ("A", "right"), ("B", "right"),
                            ("B - A", "right"), ("95% CI", "right")):
        table.add_column(column, justify=justify)
    for g in result.groups:
        table.add_row(g.name, str(g.tasks), _spread(g.a), _spread(g.b), f"{g.difference:+.0%}",
                      f"[{g.ci_low:+.0%}, {g.ci_high:+.0%}]")
    console.print(table)
    console.print("B - A is the change in mean solve rate over the tasks in both runs; the interval is a paired "
                  "bootstrap over tasks. An interval that includes 0 means the runs aren't clearly different.",
                  soft_wrap=True)

    costs = Table(title="Per attempt (A -> B)")
    for column, justify in (("Group", "left"), ("Avg steps", "right"), ("Avg tokens", "right"), ("Avg cost", "right")):
        costs.add_column(column, justify=justify)
    for g in result.groups:
        costs.add_row(
            g.name,
            _change(g.a["average_steps"], g.b["average_steps"], "{:.1f}"),
            _change(g.a["average_tokens"], g.b["average_tokens"], "{:,.0f}"),
            _change(g.a["average_cost_usd"], g.b["average_cost_usd"], "${:.4f}"),
        )
    console.print(costs)

    if result.changed:
        changes = Table(title="Tasks whose solve rate changed")
        for column in ("Task", "Split", "A", "B"):
            changes.add_column(column)
        for c in result.changed:
            changes.add_row(c.task_id, c.split or "", c.a, c.b)
        console.print(changes)
    else:
        console.print("No task's solve rate changed.")


def _spread(totals: dict[str, Any]) -> str:
    """A group's pass rate: mean and spread over repeats, or just the rate for one."""
    if totals.get("repeats", 1) > 1:
        return f"{totals['pass_rate_mean']:.0%} +/- {totals['pass_rate_std']:.0%} (x{totals['repeats']})"
    return f"{totals['pass_rate']:.0%}"


def _change(a: float, b: float, fmt: str) -> str:
    """"A -> B" for a per-attempt average."""
    return f"{fmt.format(a)} -> {fmt.format(b)}"


@app.command()
@_friendly_errors
def report(
    run_id: str = typer.Argument(..., help="The run to report on."),
    runs_dir: Path = typer.Option(DEFAULT_TRACE_DIR, "--runs-dir", help="Where run folders live."),
) -> None:
    """(Re)build a run's report.html, applying its labels.yaml."""
    run_dir = runs_dir / run_id
    if not (run_dir / SUMMARY_FILE).is_file():
        _fail(f"no run {run_id!r} in {runs_dir} (no {SUMMARY_FILE}).")
    try:
        path = write_report(run_dir)
    except LabelsError as problem:
        _fail(str(problem))
    console.print(f"Report: {path}")


@app.command()
def trace(
    run_id: str = typer.Argument(..., help="The run's ID (its folder name under runs/)."),
    task_id: str = typer.Argument(..., help="The task to show."),
    full: bool = typer.Option(False, "--full", help="Show complete outputs instead of previews."),
    runs_dir: Path = typer.Option(DEFAULT_TRACE_DIR, "--runs-dir", help="Where run folders live."),
    repeat: int = typer.Option(1, "--repeat", min=1, help="Which attempt, in a run with repeats."),
) -> None:
    """Show one task's trace as a step-by-step story."""
    path = trace_path(runs_dir, run_id, task_id, repeat)
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
