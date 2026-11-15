"""Run many tasks under one run ID, with everything for the run in one folder.

    runs/<run_id>/
        <task_id>.jsonl   one trace per task
        summary.json      every task's result plus the totals (rewritten after each task)

Tasks run one at a time, sharing one (paced) provider.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from akeso.agent import AgentResult, EnvironmentFactory, StopReason, run_agent
from akeso.config import AgentLimits, Settings, load_settings
from akeso.grading import Verdict
from akeso.llm.provider import Provider, get_provider
from akeso.prompts import AGENT_PROMPT_VERSION
from akeso import fingerprint as run_fingerprint
from akeso.sandbox import DockerSandbox, cleanup_leftover_containers, image_digest
from akeso.tasks import DEFAULT_TASKS_ROOT, find_task
from akeso.stats import mean_and_std, pass_at, solve_counts
from akeso.trace import DEFAULT_TRACE_DIR, new_run_id

SUMMARY_FILE = "summary.json"


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    run_dir: Path
    results: list[AgentResult]
    totals: dict[str, Any]


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
) -> RunSummary:
    """Run each task `repeats` times, each attempt in fresh sandboxes, and write the run
    folder. The suite is run once per repeat (repeat 1 for every task, then repeat 2, ...),
    so an interrupted run still holds whole passes. A task that crashes is recorded as an
    error result rather than stopping the run."""
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    tasks = [find_task(task_id, tasks_root) for task_id in task_ids]  # fail fast on a bad id
    splits = {task.id: task.spec.split for task in tasks}
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
        fingerprint = run_fingerprint.collect(settings, limits, docker_image=docker_image)

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results: list[AgentResult] = []
    for repeat in range(1, repeats + 1):
        for task in tasks:
            try:
                result = run_agent(
                    task.root, settings=settings, provider=provider, limits=limits,
                    environment_factory=environment_factory, run_id=run_id, trace_dir=runs_dir, repeat=repeat,
                )
            except Exception as problem:  # e.g. Docker went away: record it and carry on
                result = _error_result(task.id, settings, run_id, f"{type(problem).__name__}: {problem}", repeat)
            results.append(result)
            if on_result:
                on_result(result)
            _write_summary(run_dir, run_id, started, settings, limits, results, splits, freeze, fingerprint,
                           run_type, repeats)

    return RunSummary(run_id=run_id, run_dir=run_dir, results=results, totals=summarize(results, splits))


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
    across repeats, pass@1 and pass@k describe the tasks (see stats.py)."""
    count = len(results)
    # r.passed, not the verdict: a run stopped by the provider's token limit is a failure.
    passed = sum(r.passed for r in results)
    counts = solve_counts((r.task_id, r.passed) for r in results)
    repeats = max((n for _, n in counts.values()), default=0)
    per_repeat = []
    for repeat in sorted({r.repeat for r in results}):
        attempts = [r for r in results if r.repeat == repeat]
        per_repeat.append(sum(r.passed for r in attempts) / len(attempts))
    rate_mean, rate_std = mean_and_std(per_repeat)
    return {
        "tasks": len(counts),
        "attempts": count,
        "repeats": repeats,
        "passed": passed,
        "failed": sum(not r.passed and r.verdict is not Verdict.TAMPERED for r in results),
        "tampered": sum(r.verdict is Verdict.TAMPERED for r in results),
        "pass_rate": passed / count if count else 0.0,
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
    run_dir: Path, run_id: str, started: str, settings: Settings, limits: AgentLimits, results: list[AgentResult],
    splits: Mapping[str, str],
    freeze: dict[str, Any] | None = None,
    fingerprint: dict[str, Any] | None = None,
    run_type: str = "dev",
    repeats: int = 1,
) -> None:
    summary = {
        "run_id": run_id,
        "run_type": run_type,  # "official" (reportable) or "dev"
        "repeats": repeats,  # attempts planned per task
        "started": started,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": settings.provider,
        "model": settings.model,
        "prompt_version": AGENT_PROMPT_VERSION,
        # How the run's tasks compared with the freeze manifest (None when not checked).
        "freeze": freeze,
        "fingerprint": fingerprint,
        "cost_basis": settings.cost_basis,
        "limits": asdict(limits),
        "totals": summarize(results, splits),
        "results": [{**asdict(r), "split": splits.get(r.task_id)} for r in results],
    }
    # Write then rename, so a crash mid-write never leaves a half-written summary.
    temporary = run_dir / f"{SUMMARY_FILE}.tmp"
    temporary.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    temporary.replace(run_dir / SUMMARY_FILE)


def _error_result(task_id: str, settings: Settings, run_id: str, detail: str, repeat: int = 1) -> AgentResult:
    return AgentResult(
        repeat=repeat,
        task_id=task_id, passed=False, verdict=Verdict.FAILED, stop_reason=StopReason.ERROR,
        steps=0, input_tokens=0, output_tokens=0, cost_usd=0.0,
        provider=settings.provider, model=settings.model, environment="unknown",
        prompt_version=AGENT_PROMPT_VERSION, detail=detail, run_id=run_id,
    )
