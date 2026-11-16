"""One-shot mode: a single model call, no tools, then the same grading as the agent loop.

The model sees everything the loop's first message shows plus the contents of the files it
may need (for code: the editable folders and tests/; for SQL: solution.sql), and replies
with whole files. Those are written into the sandbox, and from there it's exactly the
loop's path: the changes are collected, graded in a fresh environment and traced, and the
result is an AgentResult. So `akeso run --mode oneshot` measures what the loop adds over
asking once, with everything else held the same.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict
from pathlib import Path

from akeso.agent import (
    TRACE_OUTPUT_LIMIT, AgentResult, EnvironmentFactory, StopReason, _explain, _first_message,
)
from akeso.checks import CheckResult, trim_output
from akeso.config import AgentLimits, Settings, load_settings
from akeso.environment import Environment
from akeso.grading import GradeResult, Verdict, collect_changes, grade
from akeso.llm.cost import cost_usd
from akeso.llm.provider import Provider, get_provider
from akeso.llm.types import Message, ProviderTokenLimitError, QuotaExhaustedError
from akeso.paths import UnsafePathError, safe_relative_path
from akeso.prompts import FILE_END, FILE_START, ONESHOT_PROMPT_VERSION, oneshot_system_prompt
from akeso.sandbox import DockerSandbox
from akeso.sql_judge import SqlCheck, support_files
from akeso.tasks import Task, load_task
from akeso.tools import Check
from akeso.trace import DEFAULT_TRACE_DIR, TraceWriter, new_run_id, trace_path

# The header's closing ">>>" is optional: gpt-oss sometimes leaves it off ("<<<FILE: src/a.py").
_FILE_BLOCK = re.compile(
    r"^" + re.escape(FILE_START) + r"(?P<path>[^\n>]+?)[ \t]*(?:>>>)?[ \t]*\n(?P<content>.*?)\n?"
    + re.escape(FILE_END) + r"[ \t]*$",
    re.MULTILINE | re.DOTALL,
)


class ReplyError(ValueError):
    """The model's reply couldn't be applied."""


def run_oneshot_agent(
    task_dir: str | Path,
    *,
    limits: AgentLimits | None = None,
    settings: Settings | None = None,
    provider: Provider | None = None,
    environment_factory: EnvironmentFactory = DockerSandbox,
    run_id: str | None = None,
    trace_dir: str | Path = DEFAULT_TRACE_DIR,
    repeat: int = 1,
) -> AgentResult:
    """One attempt at the task with a single model call; same arguments, trace and result
    as run_agent. limits are recorded but can't bind: there's only one call."""
    task = load_task(task_dir)
    settings = settings or load_settings()
    limits = limits or settings.limits
    provider = provider or get_provider(settings)
    env = environment_factory()
    run_id = run_id or new_run_id()
    path = trace_path(Path(trace_dir), run_id, task.id, repeat)
    sql_check = SqlCheck(task) if task.spec.kind == "sql" else None
    check: Check = sql_check or (lambda e, **kwargs: e.run_checks(**kwargs))
    steps = input_tokens = output_tokens = rate_limit_retries = pacing_waits = cached_input_tokens = 0
    pacing_wait_seconds = cost = 0.0

    with TraceWriter(path) as trace:

        def result(stop_reason: StopReason, detail: str, graded: GradeResult | None = None) -> AgentResult:
            verdict = graded.verdict if graded else Verdict.FAILED
            passed = verdict is Verdict.PASSED and stop_reason is not StopReason.PROVIDER_TOKEN_LIMIT
            outcome = AgentResult(
                task_id=task.id, passed=passed, verdict=verdict, stop_reason=stop_reason,
                steps=steps, input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost,
                rate_limit_retries=rate_limit_retries, pacing_waits=pacing_waits,
                pacing_wait_seconds=round(pacing_wait_seconds, 3), cached_input_tokens=cached_input_tokens,
                provider=settings.provider, model=settings.model, environment=env.kind,
                prompt_version=ONESHOT_PROMPT_VERSION,
                visible_passed=graded.visible_passed if graded else False,
                hidden_passed=graded.hidden_passed if graded else None,
                tampering=[str(finding) for finding in graded.tampering] if graded else [],
                warnings=list(graded.warnings) if graded else [],
                detail=detail, run_id=run_id, trace_path=path.as_posix(), repeat=repeat,
            )
            trace.event("result", **asdict(outcome))
            return outcome

        def record_check(phase: str, outcome: CheckResult) -> None:
            trace.event(
                "check", phase=phase, passed=outcome.passed, exit_code=outcome.exit_code,
                duration=round(outcome.duration, 3), output=trim_output(outcome.output, TRACE_OUTPUT_LIMIT),
            )

        trace.event(
            "run_start", run_id=run_id, task_id=task.id, task_dir=task.root.as_posix(), mode="oneshot",
            editable_paths=task.spec.editable_paths, provider=settings.provider, model=settings.model,
            environment=env.kind, prompt_version=ONESHOT_PROMPT_VERSION, limits=limits,
        )
        with env:
            env.start(task.root, task.private_dirs,
                      support_files=support_files(task, hidden=False) if sql_check else None)
            env.check_command = task.check_command
            if sql_check:
                sql_check.prepare(env)
            initial = check(env)
            record_check("initial", initial)
            if initial.passed:
                return result(StopReason.ERROR, "Checks already pass before any change; task is invalid.")

            message = Message.user(_first_message(task, initial) + "\n\n" + _file_sections(env, task))
            stop, detail = StopReason.ERROR, ""
            try:
                response = provider.complete(oneshot_system_prompt(task.spec.kind), [message])
                steps = 1
                input_tokens, output_tokens = response.usage.input_tokens, response.usage.output_tokens
                rate_limit_retries, pacing_waits = response.rate_limit_retries, response.pacing_waits
                pacing_wait_seconds = response.pacing_wait_seconds
                cached_input_tokens = response.usage.cache_read_tokens
                cost = cost_usd(settings.model, response.usage)
                trace.event(
                    "model_call", step=1, input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost,
                    cache_write_tokens=response.usage.cache_write_tokens, cache_read_tokens=cached_input_tokens,
                    total_tokens=input_tokens + output_tokens, total_cost_usd=cost, stop_reason=response.stop_reason,
                    rate_limit_retries=rate_limit_retries, pacing_waits=pacing_waits,
                    pacing_wait_seconds=round(pacing_wait_seconds, 3), text=response.text, tool_calls=[],
                )
                try:
                    files = parse_reply(response.text)
                except ReplyError as problem:
                    stop, detail = StopReason.EDIT_FAILED, f"The reply couldn't be applied: {problem}"
                    trace.event("error", step=1, error=detail)
                else:
                    for rel_path, content in files:
                        started = time.perf_counter()
                        try:
                            env.write_file(rel_path, content)
                            outcome, is_error = f"Wrote {rel_path}", False
                        except Exception as problem:  # e.g. the sandbox refuses the path
                            outcome, is_error = f"Error: {type(problem).__name__}: {problem}", True
                        # Traced like the loop's edits, so the trace viewer and report show them.
                        trace.event(
                            "tool_call", step=1, id=f"oneshot-{rel_path}", name="write_file",
                            arguments={"path": rel_path, "content": content}, is_error=is_error,
                            duration=round(time.perf_counter() - started, 3), result=outcome,
                        )
                        if is_error:
                            stop, detail = StopReason.EDIT_FAILED, f"The reply couldn't be applied: {outcome}"
                            break
                    else:
                        final = check(env)
                        record_check("stop", final)
                        stop = StopReason.PASSED if final.passed else StopReason.ONE_SHOT
            except ProviderTokenLimitError as problem:
                stop, detail = StopReason.PROVIDER_TOKEN_LIMIT, f"{problem} Counted as a failure."
                trace.event("error", step=0, error=str(problem))
            except QuotaExhaustedError as problem:
                trace.event("error", step=0, error=f"QuotaExhaustedError: {problem}")
                raise  # not the task's fault: the batch records it as not run
            except Exception as problem:
                stop, detail = StopReason.ERROR, f"{type(problem).__name__}: {problem}"
                trace.event("error", step=steps, error=detail)

            changes = collect_changes(env, task)
            trace.event(
                "changes", written=sorted(changes.written), deleted=changes.deleted,
                ignored=changes.ignored, tampering=[str(f) for f in changes.findings], warnings=changes.warnings,
            )
        graded = grade(task, changes, environment_factory)
        trace.event(
            "grading", task_kind=task.spec.kind, verdict=graded.verdict, visible_passed=graded.visible_passed,
            hidden_passed=graded.hidden_passed, applied=graded.applied,
            tampering=[str(f) for f in graded.tampering],
            visible_output=graded.visible_output, hidden_output=graded.hidden_output,
        )
        if stop is StopReason.EDIT_FAILED:
            return result(stop, detail, graded)
        return result(stop, (detail + " " if detail else "") + _explain(graded, task.spec.kind), graded)


def _file_sections(env: Environment, task: Task) -> str:
    """The files the model may need, each under a "### FILE <path>" header."""
    if task.spec.kind == "sql":
        paths = list(task.spec.editable_paths)
    else:
        folders = [*task.spec.editable_paths, "tests/"]
        paths = [rel for folder in folders for rel in env.list_files(folder.rstrip("/")) if rel.endswith(".py")]
    return "\n\n".join(f"### FILE {rel}\n{env.read_file(rel)}" for rel in dict.fromkeys(paths))


def parse_reply(text: str) -> list[tuple[str, str]]:
    """(path, content) for each file block in the reply. Raises ReplyError if there are none
    or a path isn't a safe relative path. Paths outside the editable folders are still
    written: grading records that as tampering, as it would in the loop."""
    blocks = list(_FILE_BLOCK.finditer(text))
    if not blocks:
        raise ReplyError(f"no {FILE_START}...>>> / {FILE_END} block found")
    files: dict[str, str] = {}
    for block in blocks:
        raw = block["path"].strip()
        try:
            rel = safe_relative_path(raw).as_posix()
        except UnsafePathError:
            rel = "."
        if rel == ".":
            raise ReplyError(f"unsafe path {raw!r}")
        content = _strip_code_fence(block["content"])
        files[rel] = content if content.endswith("\n") else content + "\n"
    return list(files.items())


def _strip_code_fence(content: str) -> str:
    """Models often wrap the file in ``` fences inside our markers; remove them if so."""
    lines = content.strip("\n").splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        lines = lines[1:-1]
    return "\n".join(lines)
