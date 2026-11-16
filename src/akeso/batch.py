"""Run many tasks under one run ID, with everything for the run in one folder.

    runs/<run_id>/
        <task_id>.jsonl   one trace per task (<task_id>.r2.jsonl for repeat 2, ...)
        summary.json      every attempt's result plus the totals (rewritten after each one)
        report.html       a self-contained page of the results and traces (at the end)

Tasks run one at a time, sharing one (paced) provider. If the provider's quota runs out,
the run stops cleanly and lists the attempts it didn't get to as "not_run";
resume_tasks finishes those later, along with any that crashed.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from akeso.agent import AgentResult, EnvironmentFactory, StopReason, run_agent
from akeso.config import AgentLimits, Settings, load_settings
from akeso.failures import categorize, category_counts, label_key, read_labels
from akeso.grading import Verdict
from akeso.llm.provider import Provider, get_provider
from akeso.llm.types import QuotaExhaustedError
from akeso.oneshot_agent import run_oneshot_agent
from akeso.prompts import AGENT_PROMPT_VERSION, prompt_version
from akeso.report import write_report
from akeso import fingerprint as run_fingerprint
from akeso.sandbox import DockerSandbox, cleanup_leftover_containers, image_digest
from akeso.tasks import DEFAULT_TASKS_ROOT, find_task
from akeso.stats import mean_and_std, pass_at, solve_counts
from akeso.trace import DEFAULT_TRACE_DIR, new_run_id, read_trace, trace_path

SUMMARY_FILE = "summary.json"

logger = logging.getLogger(__name__)

MODES = ("loop", "oneshot")  # the agent loop, or a single model call (oneshot_agent.py)

# Resuming needs the same experiment and the same code: every fingerprint field.
RESUME_FIELDS = run_fingerprint.EXPERIMENT_FIELDS + ("harness_commit", "harness_dirty")

Attempt = tuple[str, int]  # (task id, repeat)


class ResumeError(Exception):
    """A run can't be resumed (missing, or set up differently from now)."""


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    run_dir: Path
    results: list[AgentResult]
    totals: dict[str, Any]
    not_run: list[Attempt] = field(default_factory=list)  # attempts left for --resume
    stopped: str | None = None  # why the run stopped early, if it did

    @property
    def crashed(self) -> list[Attempt]:
        """Attempts that crashed: not scored, and rerun by --resume."""
        return [(r.task_id, r.repeat) for r in self.results if is_crashed(r)]


def run_tasks(
    task_ids: Sequence[str],
    *,
    run_id: str | None = None,
    runs_dir: str | Path = DEFAULT_TRACE_DIR,
    settings: Settings | None = None,
    provider: Provider | None = None,
    limits: AgentLimits | None = None,
    environment_factory: EnvironmentFactory = DockerSandbox,
    tasks_root: str | Path = DEFAULT_TASKS_ROOT,
    on_result: Callable[[AgentResult], None] | None = None,
    freeze: dict[str, Any] | None = None,
    fingerprint: dict[str, Any] | None = None,
    run_type: str = "dev",
    repeats: int = 1,
    mode: str = "loop",
) -> RunSummary:
    """Run each task `repeats` times, each attempt in fresh sandboxes, and write the run
    folder. The suite is run once per repeat (repeat 1 for every task, then repeat 2, ...),
    so an interrupted run still holds whole passes. A task that crashes is recorded as an
    error result rather than stopping the run."""
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    tasks = [find_task(task_id, tasks_root) for task_id in task_ids]  # fail fast on a bad id
    settings = settings or load_settings()
    limits = limits or settings.limits
    provider = provider or get_provider(settings)  # shared, so pacing spans the whole run
    run_id = run_id or new_run_id()
    run_dir = Path(runs_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if environment_factory is DockerSandbox:
        # Containers more than an hour old are leftovers from crashed runs, never this one.
        cleanup_leftover_containers()
    if fingerprint is None:
        docker_image = image_digest() if environment_factory is DockerSandbox else None
        fingerprint = run_fingerprint.collect(settings, limits, mode=mode, docker_image=docker_image)

    header = {
        "run_id": run_id,
        "run_type": run_type,  # "official" (reportable) or "dev"
        "repeats": repeats,  # attempts planned per task
        "mode": mode,
        "task_ids": [task.id for task in tasks],
        "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "resumed": [],
        # How the run's tasks compared with the freeze manifest (None when not checked).
        "freeze": freeze,
        "fingerprint": fingerprint,
    }
    plan = [(task.id, repeat) for repeat in range(1, repeats + 1) for task in tasks]
    return _run_attempts(plan, [], header, run_dir, {task.id: task for task in tasks}, settings, limits,
                         provider, environment_factory, runs_dir, on_result)


def resume_tasks(
    run_id: str,
    *,
    fingerprint: dict[str, Any],
    runs_dir: str | Path = DEFAULT_TRACE_DIR,
    settings: Settings | None = None,
    provider: Provider | None = None,
    limits: AgentLimits | None = None,
    environment_factory: EnvironmentFactory = DockerSandbox,
    tasks_root: str | Path = DEFAULT_TASKS_ROOT,
    on_result: Callable[[AgentResult], None] | None = None,
) -> RunSummary:
    """Finish an earlier run: rerun the attempts it never got to or that crashed (stop
    reason "error"), keep every other result, and rewrite its summary. Refuses unless
    `fingerprint` (of the setup now) matches the run's in every field."""
    run_dir = Path(runs_dir) / run_id
    saved = load_for_resume(run_id, runs_dir)
    changed = resume_differences(saved, fingerprint)
    if changed:
        raise ResumeError(f"run {run_id!r} was set up differently, so resuming would mix two experiments "
                          f"({'; '.join(changed)})")
    settings = settings or load_settings()
    limits = limits or settings.limits
    plan = planned_attempts(saved)
    tasks = {task_id: find_task(task_id, tasks_root) for task_id in dict.fromkeys(t for t, _ in plan)}
    kept, todo = split_attempts(saved)
    for task_id, repeat in todo:  # traces are appended to, so clear any partial one first
        trace_path(Path(runs_dir), run_id, task_id, repeat).unlink(missing_ok=True)
    header = {name: saved.get(name) for name in ("run_id", "run_type", "repeats", "started", "freeze", "fingerprint")}
    header["mode"] = saved_mode(saved)
    header["task_ids"] = list(tasks)
    header["resumed"] = [*(saved.get("resumed") or []), datetime.now(timezone.utc).isoformat(timespec="seconds")]
    provider = provider or get_provider(settings)
    if environment_factory is DockerSandbox:
        cleanup_leftover_containers()
    return _run_attempts(todo, kept, header, run_dir, tasks, settings, limits, provider, environment_factory,
                         runs_dir, on_result)


def load_for_resume(run_id: str, runs_dir: str | Path = DEFAULT_TRACE_DIR) -> dict[str, Any]:
    """The saved summary of the run to resume."""
    run_dir = Path(runs_dir) / run_id
    try:
        return read_summary(run_dir)
    except (OSError, json.JSONDecodeError) as problem:
        raise ResumeError(f"no readable summary for run {run_id!r} in {run_dir}") from problem


def resume_differences(saved: dict[str, Any], fingerprint: dict[str, Any]) -> list[str]:
    """How the setup now differs from the saved run's, one line per field (empty if it doesn't)."""
    then = saved.get("fingerprint") or {}
    return [f"{name}: {then.get(name)!r} then, {fingerprint.get(name)!r} now"
            for name in run_fingerprint.differences(then, fingerprint, RESUME_FIELDS)]


def saved_mode(saved: dict[str, Any]) -> str:
    """The mode a saved run used (runs from before modes existed were all loop runs)."""
    return saved.get("mode") or (saved.get("fingerprint") or {}).get("mode") or "loop"


def planned_attempts(saved: dict[str, Any]) -> list[Attempt]:
    """Every (task, repeat) the run set out to do, in running order. Runs from before
    task_ids were recorded fall back to the tasks in their results."""
    task_ids = saved.get("task_ids") or list(dict.fromkeys(r["task_id"] for r in saved.get("results", [])))
    repeats = saved.get("repeats") or 1
    return [(task_id, repeat) for repeat in range(1, repeats + 1) for task_id in task_ids]


def split_attempts(saved: dict[str, Any]) -> tuple[list[AgentResult], list[Attempt]]:
    """(results to keep, attempts to run again): crashed attempts (stop reason "error")
    and attempts with no result are run again."""
    kept = [result_from_dict(r) for r in saved.get("results", []) if r.get("stop_reason") != StopReason.ERROR.value]
    done = {(r.task_id, r.repeat) for r in kept}
    return kept, [attempt for attempt in planned_attempts(saved) if attempt not in done]


def is_crashed(result: AgentResult) -> bool:
    """The harness or provider failed (stop reason "error"), so the attempt says nothing
    about the model: it's left out of the pass rate and rerun by --resume."""
    return result.stop_reason is StopReason.ERROR


def result_from_dict(data: dict[str, Any]) -> AgentResult:
    """An AgentResult back from its summary.json form."""
    known = {f.name for f in fields(AgentResult)}
    values = {name: value for name, value in data.items() if name in known}
    values["verdict"] = Verdict(values["verdict"])
    values["stop_reason"] = StopReason(values["stop_reason"])
    return AgentResult(**values)


def _run_attempts(
    todo: Sequence[Attempt], results: list[AgentResult], header: dict[str, Any], run_dir: Path,
    tasks: Mapping[str, Any], settings: Settings, limits: AgentLimits, provider: Provider,
    environment_factory: EnvironmentFactory, runs_dir: str | Path,
    on_result: Callable[[AgentResult], None] | None,
) -> RunSummary:
    """Run the attempts in order after the results already in hand, rewriting the summary
    after each one. Stops early, listing what's left as not run, if the quota runs out."""
    splits = {task_id: task.spec.split for task_id, task in tasks.items()}
    run_id = header["run_id"]
    runner = run_oneshot_agent if header["mode"] == "oneshot" else run_agent
    not_run: list[Attempt] = []
    stopped = None
    labels = read_labels(run_dir)
    categories = {(r.task_id, r.repeat): _category(r, labels) for r in results}
    _write_summary(run_dir, header, settings, limits, results, splits, list(todo), None, categories)
    for index, (task_id, repeat) in enumerate(todo):
        try:
            result = runner(
                tasks[task_id].root, settings=settings, provider=provider, limits=limits,
                environment_factory=environment_factory, run_id=run_id, trace_dir=runs_dir, repeat=repeat,
            )
        except QuotaExhaustedError as problem:
            not_run, stopped = list(todo[index:]), f"quota exhausted: {problem}"
            break
        except Exception as problem:  # e.g. Docker went away: record it and carry on
            result = _error_result(task_id, settings, run_id, f"{type(problem).__name__}: {problem}", repeat,
                                   prompt_version(header["mode"]))
        results.append(result)
        categories[(result.task_id, result.repeat)] = _category(result, labels)
        if on_result:
            on_result(result)
        _write_summary(run_dir, header, settings, limits, results, splits, list(todo[index + 1:]), None, categories)
    totals = _write_summary(run_dir, header, settings, limits, results, splits, not_run, stopped, categories)
    try:
        write_report(run_dir)
    except Exception as problem:  # the results are safe in summary.json; `akeso report` can retry
        logger.warning("Couldn't write the report for run %s: %s", run_id, problem)
    return RunSummary(run_id=run_id, run_dir=run_dir, results=results, totals=totals,
                      not_run=not_run, stopped=stopped)


def _category(result: AgentResult, labels: Mapping[str, str]) -> str | None:
    """The attempt's failure category: a label from labels.yaml, else the automatic one
    (worked out once, from its trace)."""
    key = label_key(result.task_id, result.repeat)
    if key in labels:
        return labels[key]
    path = Path(result.trace_path)
    try:
        events = read_trace(path) if result.trace_path and path.is_file() else []
    except (OSError, ValueError):
        events = []
    return categorize({**asdict(result), "verdict": result.verdict.value, "stop_reason": result.stop_reason.value},
                      events)


def summarize(results: Sequence[AgentResult], splits: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Totals across a run: verdict counts, pass rate, average steps, tokens and cost.
    With splits (task id -> "dev" or "heldout"), the same totals per split too, under
    "by_split": official results are reported per split as well as overall."""
    totals = _totals(results)
    if splits is not None:
        totals["by_split"] = {
            split: _totals([r for r in results if splits.get(r.task_id) == split])
            for split in sorted(set(splits.values()))
        }
    return totals


def _totals(results: Sequence[AgentResult]) -> dict[str, Any]:
    """Counts are per attempt; with several repeats, solve rates, the pass rate's spread
    across repeats, pass@1 and pass@k describe the tasks (see stats.py). Crashed attempts
    are counted but not scored: every rate is over the other ("scored") attempts. Steps,
    tokens and cost include them, since they were really spent."""
    count = len(results)
    scored = [r for r in results if not is_crashed(r)]
    # r.passed, not the verdict: a run stopped by the provider's token limit is a failure.
    passed = sum(r.passed for r in scored)
    counts = solve_counts((r.task_id, r.passed) for r in scored)
    repeats = max((n for _, n in counts.values()), default=0)
    per_repeat = []
    for repeat in sorted({r.repeat for r in scored}):
        attempts = [r for r in scored if r.repeat == repeat]
        per_repeat.append(sum(r.passed for r in attempts) / len(attempts))
    rate_mean, rate_std = mean_and_std(per_repeat)
    return {
        "tasks": len(counts),
        "attempts": count,
        "scored_attempts": len(scored),
        "crashed": count - len(scored),
        "repeats": repeats,
        "passed": passed,
        "failed": sum(not r.passed and r.verdict is not Verdict.TAMPERED for r in scored),
        "tampered": sum(r.verdict is Verdict.TAMPERED for r in scored),
        "pass_rate": passed / len(scored) if scored else 0.0,
        "pass_rate_mean": rate_mean,  # mean over repeats of each repeat's pass rate
        "pass_rate_std": rate_std,  # their sample standard deviation (0 with one repeat)
        "pass_rates_by_repeat": per_repeat,
        "pass_at_1": pass_at(counts, 1),
        "pass_at_k": pass_at(counts, repeats) if repeats else 0.0,
        "k": repeats,
        "solve_rates": {task: f"{c}/{n}" for task, (c, n) in sorted(counts.items())},
        "average_steps": sum(r.steps for r in results) / count if count else 0.0,
        "average_tokens": sum(r.input_tokens + r.output_tokens for r in results) / count if count else 0.0,
        "average_cost_usd": sum(r.cost_usd for r in results) / count if count else 0.0,
        "total_input_tokens": sum(r.input_tokens for r in results),
        "total_output_tokens": sum(r.output_tokens for r in results),
        "total_cost_usd": sum(r.cost_usd for r in results),
        "total_rate_limit_retries": sum(r.rate_limit_retries for r in results),
        "total_pacing_waits": sum(r.pacing_waits for r in results),
        "total_pacing_wait_seconds": round(sum(r.pacing_wait_seconds for r in results), 3),
        "total_cached_input_tokens": sum(r.cached_input_tokens for r in results),
        "provider_token_limit": sum(r.stop_reason is StopReason.PROVIDER_TOKEN_LIMIT for r in results),
    }


def read_summary(run_dir: str | Path) -> dict[str, Any]:
    return json.loads((Path(run_dir) / SUMMARY_FILE).read_text(encoding="utf-8"))


def _write_summary(
    run_dir: Path, header: dict[str, Any], settings: Settings, limits: AgentLimits, results: list[AgentResult],
    splits: Mapping[str, str], not_run: list[Attempt], stopped: str | None,
    categories: Mapping[Attempt, str | None],
) -> dict[str, Any]:
    """Write summary.json and return its totals. While a run is going, not_run lists what's
    still to do, so a run that dies outright (killed, power cut) can be resumed too."""
    totals = summarize(results, splits)
    category = {id(r): categories.get((r.task_id, r.repeat)) for r in results}
    totals["failure_categories"] = category_counts(category[id(r)] for r in results)
    for split, group in totals.get("by_split", {}).items():
        group["failure_categories"] = category_counts(
            category[id(r)] for r in results if splits.get(r.task_id) == split)
    summary = {
        **{name: header[name] for name in ("run_id", "run_type", "repeats", "mode", "task_ids", "started", "resumed")},
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": settings.provider,
        "model": settings.model,
        "prompt_version": prompt_version(header["mode"]),
        "freeze": header["freeze"],
        "fingerprint": header["fingerprint"],
        "cost_basis": settings.cost_basis,
        "limits": asdict(limits),
        # An official run also needs every attempt scored: crashed ones are rerun by --resume.
        "complete": not not_run and not (header["run_type"] == "official" and totals["crashed"]),
        "stopped": stopped,
        "not_run": [{"task_id": task_id, "repeat": repeat} for task_id, repeat in not_run],
        "crashed": [{"task_id": r.task_id, "repeat": r.repeat} for r in results if is_crashed(r)],
        "totals": totals,
        "results": [{**asdict(r), "split": splits.get(r.task_id), "category": category[id(r)]} for r in results],
    }
    # Write then rename, so a crash mid-write never leaves a half-written summary.
    temporary = run_dir / f"{SUMMARY_FILE}.tmp"
    temporary.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    temporary.replace(run_dir / SUMMARY_FILE)
    return totals


def _error_result(
    task_id: str, settings: Settings, run_id: str, detail: str, repeat: int = 1, prompt: str = AGENT_PROMPT_VERSION,
) -> AgentResult:
    return AgentResult(
        repeat=repeat,
        task_id=task_id, passed=False, verdict=Verdict.FAILED, stop_reason=StopReason.ERROR,
        steps=0, input_tokens=0, output_tokens=0, cost_usd=0.0,
        provider=settings.provider, model=settings.model, environment="unknown",
        prompt_version=prompt, detail=detail, run_id=run_id,
    )
