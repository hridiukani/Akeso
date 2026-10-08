"""The agent loop: the model reads, edits and tests the task with tools until it stops.

The model's own claims never decide the result. When the loop ends for any reason, the
agent's allowed changes are collected and graded in a brand-new environment, with the
hidden tests added (see grading.py). That grade is the result.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from pathlib import Path

from akeso.checks import CheckResult, normalize_check_output, trim_output
from akeso.config import AgentLimits, Settings, load_settings
from akeso.environment import Environment
from akeso.grading import GradeResult, Verdict, collect_changes, grade
from akeso.llm.cost import cost_usd
from akeso.llm.provider import Provider, get_provider
from akeso.llm.types import Message
from akeso.prompts import AGENT_PROMPT_VERSION, build_first_message, build_sql_first_message, system_prompt
from akeso.sandbox import DockerSandbox
from akeso.sql_judge import SqlCheck, comparison_rules, support_files
from akeso.tasks import Task, load_task
from akeso.tools import Check, execute_tool, tool_definitions
from akeso.trace import DEFAULT_TRACE_DIR, TraceWriter, new_run_id, trace_path

TRACE_OUTPUT_LIMIT = 3000  # characters of each tool/check output kept in the trace

EnvironmentFactory = Callable[[], Environment]


class StopReason(str, Enum):
    """Why the agent loop ended (not whether the task was solved: that's the verdict)."""

    # Checks passed in the agent's environment when the loop ended: either the model's own
    # run_checks, or the check we run when it stops calling tools.
    PASSED = "passed"
    MAX_STEPS = "max_steps"
    MAX_COST = "max_cost"
    MAX_TOKENS = "max_tokens"
    REPEATED_FAILURE = "repeated_failure"  # the same failing check output N times in a row
    GAVE_UP = "gave_up"  # the model stopped calling tools while the checks were still failing
    ERROR = "error"


@dataclass(frozen=True)
class AgentResult:
    """Outcome of one agent run. `passed` and `verdict` come from grading, never the model."""

    task_id: str
    passed: bool
    verdict: Verdict
    stop_reason: StopReason
    steps: int  # model calls made
    input_tokens: int
    output_tokens: int
    cost_usd: float
    provider: str
    model: str
    environment: str
    prompt_version: str
    visible_passed: bool = False
    hidden_passed: bool | None = None  # None when the task has no hidden tests
    tampering: list[str] = field(default_factory=list)  # what was detected, if anything
    warnings: list[str] = field(default_factory=list)  # checks that couldn't run (not tampering)
    rate_limit_retries: int = 0  # times the provider had to wait after HTTP 429 during this task
    detail: str = ""  # human-readable explanation of the outcome
    run_id: str = ""
    trace_path: str = ""  # the JSON Lines trace of this run


class RepeatedFailureDetector:
    """Notices when the checks fail the same way `limit` times in a row (the model is stuck)."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._last: str | None = None
        self._count = 0

    def record(self, passed: bool, output: str) -> bool:
        """Record one check run; True once the same failure has been seen `limit` times running."""
        if passed:
            self._last, self._count = None, 0
            return False
        normalized = normalize_check_output(output)
        self._count = self._count + 1 if normalized == self._last else 1
        self._last = normalized
        return self._count >= self.limit


def run_agent(
    task_dir: str | Path,
    max_steps: int | None = None,
    *,
    limits: AgentLimits | None = None,
    settings: Settings | None = None,
    provider: Provider | None = None,
    environment_factory: EnvironmentFactory = DockerSandbox,
    run_id: str | None = None,
    trace_dir: str | Path = DEFAULT_TRACE_DIR,
) -> AgentResult:
    """Run the agent on one task, then grade its changes in a fresh environment.

    environment_factory makes a new, unstarted environment; it's called once for the
    agent and once more for grading. Limits come from settings (.env) unless given;
    max_steps overrides just that one. Every event goes to the trace at
    <trace_dir>/<run_id>/<task id>.jsonl.
    """
    task = load_task(task_dir)
    settings = settings or load_settings()
    limits = limits or settings.limits
    if max_steps is not None:
        limits = replace(limits, max_steps=max_steps)
    provider = provider or get_provider(settings)
    env = environment_factory()
    run_id = run_id or new_run_id()
    path = trace_path(Path(trace_dir), run_id, task.id)
    stuck = RepeatedFailureDetector(limits.repeated_failure_limit)
    tools = tool_definitions(env.kind, task.spec.kind)  # descriptions must match where commands really run
    # How the task is checked: its test command, or (SQL) a comparison with the gold query.
    sql_check = SqlCheck(task) if task.spec.kind == "sql" else None
    check: Check = sql_check or (lambda e, **kwargs: e.run_checks(**kwargs))
    steps = input_tokens = output_tokens = rate_limit_retries = 0
    cost = 0.0
    stop, detail = StopReason.ERROR, ""

    with TraceWriter(path) as trace:

        def result(stop_reason: StopReason, detail: str, graded: GradeResult | None = None) -> AgentResult:
            verdict = graded.verdict if graded else Verdict.FAILED
            outcome = AgentResult(
                task_id=task.id, passed=verdict is Verdict.PASSED, verdict=verdict, stop_reason=stop_reason,
                steps=steps, input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost,
                rate_limit_retries=rate_limit_retries,
                provider=settings.provider, model=settings.model, environment=env.kind,
                prompt_version=AGENT_PROMPT_VERSION,
                visible_passed=graded.visible_passed if graded else False,
                hidden_passed=graded.hidden_passed if graded else None,
                tampering=[str(finding) for finding in graded.tampering] if graded else [],
                warnings=list(graded.warnings) if graded else [],
                detail=detail, run_id=run_id, trace_path=path.as_posix(),
            )
            trace.event("result", **asdict(outcome))
            return outcome

        def record_check(phase: str, check: CheckResult) -> None:
            trace.event(
                "check", phase=phase, passed=check.passed, exit_code=check.exit_code,
                duration=round(check.duration, 3), output=trim_output(check.output, TRACE_OUTPUT_LIMIT),
            )

        trace.event(
            "run_start", run_id=run_id, task_id=task.id, task_dir=task.root.as_posix(),
            editable_paths=task.spec.editable_paths, provider=settings.provider, model=settings.model,
            environment=env.kind, prompt_version=AGENT_PROMPT_VERSION, limits=limits,
        )
        with env:
            env.start(task.root, task.private_dirs,
                      support_files=support_files(task, hidden=False) if sql_check else None)
            env.check_command = task.check_command
            if sql_check:
                sql_check.prepare(env)  # before the model's first turn
            initial = check(env)
            record_check("initial", initial)
            if initial.passed:
                # Nothing to repair, so don't spend money asking the model.
                return result(StopReason.ERROR, "Checks already pass before any change; task is invalid.")

            messages = [Message.user(_first_message(task, initial))]
            try:
                while True:
                    if steps >= limits.max_steps:
                        stop = StopReason.MAX_STEPS
                        break
                    response = provider.complete(system_prompt(task.spec.kind), messages, tools=tools)
                    steps += 1
                    input_tokens += response.usage.input_tokens
                    rate_limit_retries += response.rate_limit_retries
                    output_tokens += response.usage.output_tokens
                    call_cost = cost_usd(settings.model, response.usage)
                    cost += call_cost
                    messages.append(response.as_message())
                    trace.event(
                        "model_call", step=steps, input_tokens=response.usage.input_tokens,
                        output_tokens=response.usage.output_tokens, cost_usd=call_cost,
                        total_tokens=input_tokens + output_tokens, total_cost_usd=cost,
                        stop_reason=response.stop_reason, rate_limit_retries=response.rate_limit_retries,
                        text=response.text,
                        tool_calls=[{"id": c.id, "name": c.name, "arguments": c.arguments} for c in response.tool_calls],
                    )

                    if not response.tool_calls:
                        # The model has stopped. Run the checks before saying why: it may
                        # have finished the fix without running them itself.
                        final_check = check(env)
                        record_check("stop", final_check)
                        stop = StopReason.PASSED if final_check.passed else StopReason.GAVE_UP
                        break
                    checks_passed = repeated = False
                    for call in response.tool_calls:
                        started = time.perf_counter()
                        outcome = execute_tool(env, call, check=check)
                        trace.event(
                            "tool_call", step=steps, id=call.id, name=call.name, arguments=call.arguments,
                            is_error=outcome.is_error, duration=round(time.perf_counter() - started, 3),
                            result=trim_output(outcome.output, TRACE_OUTPUT_LIMIT),
                        )
                        messages.append(Message.tool_result(call.id, outcome.output, outcome.is_error))
                        if call.name == "run_checks" and not outcome.is_error:
                            checks_passed = outcome.output.startswith("PASSED")
                            repeated = stuck.record(checks_passed, outcome.output)
                            trace.event("check", phase="agent", step=steps, passed=checks_passed)
                    if checks_passed:
                        stop = StopReason.PASSED  # the agent thinks it's done; grading decides
                        break
                    if repeated:
                        stop = StopReason.REPEATED_FAILURE
                        break
                    # Budgets are checked after each call, so one call can overshoot slightly.
                    if cost >= limits.max_cost_usd:
                        stop = StopReason.MAX_COST
                        break
                    if input_tokens + output_tokens >= limits.max_total_tokens:
                        stop = StopReason.MAX_TOKENS
                        break
            except Exception as problem:  # e.g. the provider gave up after rate limits
                stop, detail = StopReason.ERROR, f"{type(problem).__name__}: {problem}"
                trace.event("error", step=steps, error=detail)

            changes = collect_changes(env, task)
            trace.event(
                "changes", written=sorted(changes.written), deleted=changes.deleted,
                ignored=changes.ignored, tampering=[str(f) for f in changes.findings], warnings=changes.warnings,
            )
        # The agent's environment is gone now; grade in a brand-new one.
        graded = grade(task, changes, environment_factory)
        trace.event(
            "grading", task_kind=task.spec.kind, verdict=graded.verdict, visible_passed=graded.visible_passed,
            hidden_passed=graded.hidden_passed, applied=graded.applied,
            tampering=[str(f) for f in graded.tampering],
            visible_output=graded.visible_output, hidden_output=graded.hidden_output,
        )
        return result(stop, detail or _explain(graded, task.spec.kind), graded)


def _first_message(task: Task, initial: CheckResult) -> str:
    """The opening message: the README and how the checks fail, plus the question, date and
    schema for a SQL task."""
    readme_path = task.root / "README.md"
    readme = readme_path.read_text(encoding="utf-8") if readme_path.is_file() else None
    if task.spec.kind == "sql":
        return build_sql_first_message(
            readme, task.sql.question, task.sql.as_of.isoformat(), task.dataset.schema,
            comparison_rules(task), initial.output,
        )
    return build_first_message(readme, initial.output, task.spec.editable_paths)


def _explain(graded: GradeResult, task_kind: str = "code") -> str:
    if graded.verdict is Verdict.TAMPERED:
        return "Tampering detected: " + "; ".join(str(f) for f in graded.tampering)
    if task_kind == "sql":
        if graded.verdict is Verdict.PASSED:
            return "Graded in a fresh environment: matches the gold query on the visible and hidden databases."
        if not graded.visible_passed:
            return f"Doesn't match the gold query on the visible database: {graded.visible_output.splitlines()[0]}"
        return f"Matches on the visible database, but not on the hidden one: {graded.hidden_output.splitlines()[0]}"
    if graded.verdict is Verdict.PASSED:
        return "Graded in a fresh environment: visible and hidden tests pass."
    if not graded.visible_passed:
        return f"Visible tests fail after applying the agent's changes: {_last_line(graded.visible_output)}"
    return f"Visible tests pass, but hidden tests fail: {_last_line(graded.hidden_output)}"


def _last_line(output: str) -> str:
    lines = output.strip().splitlines()
    return lines[-1] if lines else "(no output)"
