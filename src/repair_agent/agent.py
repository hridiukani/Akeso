"""The agent loop: the model reads, edits and tests the task with tools until it stops.

The model's own claims never decide the result. When the loop ends for any reason,
we restore the original tests and pytest config (the judge) and run the checks
ourselves; that final check is the result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath

from repair_agent.config import Settings, load_settings
from repair_agent.environment import EnvError, Environment
from repair_agent.llm.cost import cost_usd
from repair_agent.llm.provider import Provider, get_provider
from repair_agent.llm.types import Message
from repair_agent.paths import is_excluded_task_file
from repair_agent.prompts import AGENT_PROMPT_VERSION, AGENT_SYSTEM_PROMPT, build_first_message
from repair_agent.sandbox import DockerSandbox
from repair_agent.tools import TOOL_DEFINITIONS, execute_tool

DEFAULT_MAX_STEPS = 20

# Files that define how the tests run. Anywhere in the task, these belong to the judge.
JUDGE_CONFIG_NAMES = {"pytest.ini", "conftest.py", "pyproject.toml", "setup.cfg", "tox.ini"}
JUDGE_FOLDER = "tests"


class StopReason(str, Enum):
    """Why the run ended. A str enum, so it reads and serialises as plain text."""

    PASSED = "passed"
    MAX_STEPS = "max_steps"
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


@dataclass
class RestoreReport:
    """What restore_judge changed: files put back and agent-created files removed."""

    restored: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)


def run_agent(
    task_dir: str | Path,
    max_steps: int = DEFAULT_MAX_STEPS,
    *,
    settings: Settings | None = None,
    provider: Provider | None = None,
    environment: Environment | None = None,
) -> AgentResult:
    """Run the agent on a copy of task_dir (in Docker unless an environment is injected)."""
    task_dir = Path(task_dir)
    settings = settings or load_settings()
    provider = provider or get_provider(settings)
    env = environment or DockerSandbox()
    steps = input_tokens = output_tokens = 0
    cost = 0.0
    stop, detail = StopReason.ERROR, ""

    def result(passed: bool, stop_reason: StopReason, detail: str) -> AgentResult:
        return AgentResult(
            passed, stop_reason, steps, input_tokens, output_tokens, cost,
            settings.provider, settings.model, env.kind, AGENT_PROMPT_VERSION, detail,
        )

    with env:
        env.start(task_dir)
        initial = env.run_checks()
        if initial.passed:
            # Nothing to repair, so don't spend money asking the model.
            return result(False, StopReason.ERROR, "Checks already pass before any change; task is invalid.")

        readme = task_dir / "README.md"
        first = build_first_message(readme.read_text(encoding="utf-8") if readme.is_file() else None, initial.output)
        messages = [Message.user(first)]
        try:
            while True:
                if steps >= max_steps:
                    stop = StopReason.MAX_STEPS
                    break
                response = provider.complete(AGENT_SYSTEM_PROMPT, messages, tools=TOOL_DEFINITIONS)
                steps += 1
                input_tokens += response.usage.input_tokens
                output_tokens += response.usage.output_tokens
                cost += cost_usd(settings.model, response.usage)
                messages.append(response.as_message())

                if not response.tool_calls:
                    stop = StopReason.GAVE_UP  # upgraded to PASSED below if the final check passes
                    break
                checks_passed = False
                for call in response.tool_calls:
                    outcome = execute_tool(env, call)
                    messages.append(Message.tool_result(call.id, outcome.output, outcome.is_error))
                    if call.name == "run_checks" and outcome.output.startswith("PASSED"):
                        checks_passed = True
                if checks_passed:
                    stop = StopReason.PASSED  # provisional: only our final check counts
                    break
        except Exception as problem:  # e.g. the provider gave up after rate limits
            stop, detail = StopReason.ERROR, f"{type(problem).__name__}: {problem}"

        restore_judge(env, task_dir)
        final = env.run_checks()

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
