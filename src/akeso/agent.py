"""The agent loop: the model reads, edits and tests the task with tools until it stops.

The model's own claims never decide the result. When the loop ends for any reason,
we restore the original tests and pytest config (the judge) and run the checks
ourselves; that final check is the result.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from pathlib import Path, PurePosixPath

from akeso.checks import CheckResult, normalize_check_output, trim_output
from akeso.config import AgentLimits, Settings, load_settings
from akeso.environment import EnvError, Environment
from akeso.llm.cost import cost_usd
from akeso.llm.provider import Provider, get_provider
from akeso.llm.types import Message
from akeso.paths import is_excluded_task_file
from akeso.prompts import AGENT_PROMPT_VERSION, AGENT_SYSTEM_PROMPT, build_first_message
from akeso.sandbox import DockerSandbox
from akeso.tools import execute_tool, tool_definitions
from akeso.trace import DEFAULT_TRACE_DIR, TraceWriter, new_run_id, trace_path

# Files that define how the tests run. Anywhere in the task, these belong to the judge.
JUDGE_CONFIG_NAMES = {"pytest.ini", "conftest.py", "pyproject.toml", "setup.cfg", "tox.ini"}
JUDGE_FOLDER = "tests"
TRACE_OUTPUT_LIMIT = 3000  # characters of each tool/check output kept in the trace


class StopReason(str, Enum):
    """Why the run ended. A str enum, so it reads and serialises as plain text."""

    PASSED = "passed"
    MAX_STEPS = "max_steps"
    MAX_COST = "max_cost"
    MAX_TOKENS = "max_tokens"
    REPEATED_FAILURE = "repeated_failure"  # the same failing check output N times in a row
    GAVE_UP = "gave_up"  # the model stopped calling tools without a real pass
    ERROR = "error"


@dataclass(frozen=True)
class AgentResult:
    """Outcome of one agent run. `passed` comes from our final check, never the model."""

    passed: bool
    stop_reason: StopReason
    steps: int  # model calls made
    input_tokens: int
    output_tokens: int
    cost_usd: float
    provider: str
    model: str
    environment: str
    prompt_version: str
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


@dataclass
class RestoreReport:
    """What restore_judge changed: files put back and agent-created files removed."""

    restored: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)


def run_agent(
    task_dir: str | Path,
    max_steps: int | None = None,
    *,
    limits: AgentLimits | None = None,
    settings: Settings | None = None,
    provider: Provider | None = None,
    environment: Environment | None = None,
    run_id: str | None = None,
    trace_dir: str | Path = DEFAULT_TRACE_DIR,
) -> AgentResult:
    """Run the agent on a copy of task_dir (in Docker unless an environment is injected).

    Limits come from settings (.env) unless given; max_steps overrides just that one.
    Every event is written to the trace at <trace_dir>/<run_id>/<task id>.jsonl.
    """
    task_dir = Path(task_dir)
    settings = settings or load_settings()
    limits = limits or settings.limits
    if max_steps is not None:
        limits = replace(limits, max_steps=max_steps)
    provider = provider or get_provider(settings)
    env = environment or DockerSandbox()
    run_id = run_id or new_run_id()
    path = trace_path(Path(trace_dir), run_id, task_dir.name)
    stuck = RepeatedFailureDetector(limits.repeated_failure_limit)
    tools = tool_definitions(env.kind)  # descriptions must match where commands really run
    steps = input_tokens = output_tokens = 0
    cost = 0.0
    stop, detail = StopReason.ERROR, ""

    with TraceWriter(path) as trace:

        def result(passed: bool, stop_reason: StopReason, detail: str) -> AgentResult:
            outcome = AgentResult(
                passed, stop_reason, steps, input_tokens, output_tokens, cost,
                settings.provider, settings.model, env.kind, AGENT_PROMPT_VERSION, detail,
                run_id, path.as_posix(),
            )
            trace.event("result", **asdict(outcome))
            return outcome

        def record_check(phase: str, check: CheckResult) -> None:
            trace.event(
                "check", phase=phase, passed=check.passed, exit_code=check.exit_code,
                duration=round(check.duration, 3), output=trim_output(check.output, TRACE_OUTPUT_LIMIT),
            )

        trace.event(
            "run_start", run_id=run_id, task_id=task_dir.name, task_dir=task_dir.as_posix(),
            provider=settings.provider, model=settings.model, environment=env.kind,
            prompt_version=AGENT_PROMPT_VERSION, limits=limits,
        )
        with env:
            env.start(task_dir)
            initial = env.run_checks()
            record_check("initial", initial)
            if initial.passed:
                # Nothing to repair, so don't spend money asking the model.
                return result(False, StopReason.ERROR, "Checks already pass before any change; task is invalid.")

            readme = task_dir / "README.md"
            first = build_first_message(readme.read_text(encoding="utf-8") if readme.is_file() else None, initial.output)
            messages = [Message.user(first)]
            try:
                while True:
                    if steps >= limits.max_steps:
                        stop = StopReason.MAX_STEPS
                        break
                    response = provider.complete(AGENT_SYSTEM_PROMPT, messages, tools=tools)
                    steps += 1
                    input_tokens += response.usage.input_tokens
                    output_tokens += response.usage.output_tokens
                    call_cost = cost_usd(settings.model, response.usage)
                    cost += call_cost
                    messages.append(response.as_message())
                    trace.event(
                        "model_call", step=steps, input_tokens=response.usage.input_tokens,
                        output_tokens=response.usage.output_tokens, cost_usd=call_cost,
                        total_tokens=input_tokens + output_tokens, total_cost_usd=cost,
                        stop_reason=response.stop_reason, text=response.text,
                        tool_calls=[{"id": c.id, "name": c.name, "arguments": c.arguments} for c in response.tool_calls],
                    )

                    if not response.tool_calls:
                        stop = StopReason.GAVE_UP  # upgraded to PASSED below if the final check passes
                        break
                    checks_passed = repeated = False
                    for call in response.tool_calls:
                        started = time.perf_counter()
                        outcome = execute_tool(env, call)
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
                        stop = StopReason.PASSED  # provisional: only our final check counts
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

            report = restore_judge(env, task_dir)
            trace.event("judge_restore", restored=report.restored, deleted=report.deleted)
            final = env.run_checks()
            record_check("final", final)

        summary = _last_line(final.output)
        if final.passed:
            return result(True, StopReason.PASSED, f"Final check passed: {summary}")
        if stop is StopReason.PASSED:
            # The model's own run_checks passed but the restored tests don't: it changed the judge.
            return result(False, StopReason.GAVE_UP, f"Model's checks passed, but the final check failed: {summary}")
        return result(False, stop, detail or f"Final check failed: {summary}")


def restore_judge(env: Environment, task_dir: Path) -> RestoreReport:
    """Make the tests and pytest config in env identical to the original task's.

    Puts back every original file under tests/ and every pytest config file, and deletes
    any such file the agent created. Simple by design; full tamper detection comes later.
    """
    originals = {
        rel: path.read_bytes().decode("utf-8")  # bytes: keep line endings exactly as stored
        for path in sorted(task_dir.rglob("*"))
        if path.is_file()
        and _is_judge_file(rel := path.relative_to(task_dir).as_posix())
        and not is_excluded_task_file(rel)
    }
    report = RestoreReport()
    for rel in env.list_files():
        if _is_judge_file(rel) and rel not in originals:
            env.delete_file(rel)
            report.deleted.append(rel)
    for rel, content in originals.items():
        try:
            current = env.read_file(rel)
        except (FileNotFoundError, IsADirectoryError, EnvError):
            current = None  # missing, or replaced by something we refuse to read (e.g. a link)
        if current != content:
            env.write_file(rel, content)
            report.restored.append(rel)
    return report


def _is_judge_file(rel: str) -> bool:
    parts = PurePosixPath(rel).parts
    return bool(parts) and (parts[0] == JUDGE_FOLDER or parts[-1] in JUDGE_CONFIG_NAMES)


def _last_line(output: str) -> str:
    lines = output.strip().splitlines()
    return lines[-1] if lines else "(no output)"
