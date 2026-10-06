"""Run many tasks under one run ID, with everything for the run in one folder.

    runs/<run_id>/
        <task_id>.jsonl   one trace per task
        summary.json      every task's result plus the totals (rewritten after each task)

Tasks run one at a time, sharing one (paced) provider.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from akeso.agent import AgentResult, EnvironmentFactory, StopReason, run_agent
from akeso.config import AgentLimits, Settings, load_settings
from akeso.grading import Verdict
from akeso.llm.provider import Provider, get_provider
from akeso.prompts import AGENT_PROMPT_VERSION
from akeso.sandbox import DockerSandbox, cleanup_leftover_containers
from akeso.tasks import DEFAULT_TASKS_ROOT, find_task
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
) -> RunSummary:
    """Run each task in turn and write the run folder. A task that crashes is recorded
    as an error result rather than stopping the run."""
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

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results: list[AgentResult] = []
    for task in tasks:
        try:
            result = run_agent(
                task.root, settings=settings, provider=provider, limits=limits,
                environment_factory=environment_factory, run_id=run_id, trace_dir=runs_dir,
            )
        except Exception as problem:  # e.g. Docker went away: record it and carry on
            result = _error_result(task.id, settings, run_id, f"{type(problem).__name__}: {problem}")
        results.append(result)
        if on_result:
            on_result(result)
        _write_summary(run_dir, run_id, started, settings, limits, results)

    return RunSummary(run_id=run_id, run_dir=run_dir, results=results, totals=summarize(results))


def summarize(results: Sequence[AgentResult]) -> dict[str, Any]:
    """Totals across a run: verdict counts, pass rate, average steps, tokens and cost."""
    count = len(results)
    passed = sum(r.verdict is Verdict.PASSED for r in results)
    return {
        "tasks": count,
        "passed": passed,
        "failed": sum(r.verdict is Verdict.FAILED for r in results),
        "tampered": sum(r.verdict is Verdict.TAMPERED for r in results),
        "pass_rate": passed / count if count else 0.0,
        "average_steps": sum(r.steps for r in results) / count if count else 0.0,
        "total_input_tokens": sum(r.input_tokens for r in results),
        "total_output_tokens": sum(r.output_tokens for r in results),
        "total_cost_usd": sum(r.cost_usd for r in results),
    }


def read_summary(run_dir: str | Path) -> dict[str, Any]:
    return json.loads((Path(run_dir) / SUMMARY_FILE).read_text(encoding="utf-8"))


def _write_summary(
    run_dir: Path, run_id: str, started: str, settings: Settings, limits: AgentLimits, results: list[AgentResult]
) -> None:
    summary = {
        "run_id": run_id,
        "started": started,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": settings.provider,
        "model": settings.model,
        "prompt_version": AGENT_PROMPT_VERSION,
        "limits": asdict(limits),
        "totals": summarize(results),
        "results": [asdict(r) for r in results],
    }
    # Write then rename, so a crash mid-write never leaves a half-written summary.
    temporary = run_dir / f"{SUMMARY_FILE}.tmp"
    temporary.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    temporary.replace(run_dir / SUMMARY_FILE)


def _error_result(task_id: str, settings: Settings, run_id: str, detail: str) -> AgentResult:
    return AgentResult(
        task_id=task_id, passed=False, verdict=Verdict.FAILED, stop_reason=StopReason.ERROR,
        steps=0, input_tokens=0, output_tokens=0, cost_usd=0.0,
        provider=settings.provider, model=settings.model, environment="unknown",
        prompt_version=AGENT_PROMPT_VERSION, detail=detail, run_id=run_id,
    )
