"""One-shot repair: show the model the failing task once, apply its fix, rerun the checks."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from repair_agent.checks import trim_output
from repair_agent.config import Settings, load_settings
from repair_agent.environment import Environment
from repair_agent.llm.cost import cost_usd
from repair_agent.llm.provider import Provider, get_provider
from repair_agent.llm.types import Message, Usage
from repair_agent.paths import UnsafePathError, safe_relative_path
from repair_agent.sandbox import DockerSandbox
from repair_agent.workspace import LocalWorkspace

Mode = Literal["docker", "local"]

# Unusual markers rather than ``` fences, because file contents can contain fences.
FILE_START = "<<<FILE: "
FILE_END = "<<<END FILE>>>"
_FILE_BLOCK = re.compile(
    r"^<<<FILE: (?P<path>[^\n>]+)>>>\n(?P<content>.*?)\n?<<<END FILE>>>[ \t]*$",
    re.MULTILINE | re.DOTALL,
)

# Headers for the prompt we send. Distinct from pytest's "=====" lines in the failure
# output, and from the reply markers above, so the model can tell the three apart.
INPUT_FILE_HEADER = "### FILE "
INPUT_OUTPUT_HEADER = "### FAILING TEST OUTPUT"

SYSTEM_PROMPT = f"""You fix bugs in small Python projects.
You will see the project's source files and its test files, each under a
"{INPUT_FILE_HEADER}<path>" header, then the output of the failing tests under
"{INPUT_OUTPUT_HEADER}".
The tests are correct. Fix the code under src/ so the tests pass. Do not change the tests.

Reply with the complete corrected contents of exactly one file under src/, using exactly
this format and nothing else:

{FILE_START}src/path/to/file.py>>>
<the complete file contents>
{FILE_END}"""


@dataclass(frozen=True)
class OneshotResult:
    """Outcome of one one-shot repair attempt."""

    passed: bool
    reason: str  # human-readable explanation, especially for failures
    usage: Usage
    cost_usd: float
    file_path: str | None = None  # the file the model replaced, if its reply was valid


class ReplyError(ValueError):
    """The model's reply couldn't be used (unparseable, or an unsafe/unknown path)."""


def run_oneshot(
    task_dir: str | Path,
    *,
    mode: Mode = "docker",
    confirm: bool | None = None,
    settings: Settings | None = None,
    provider: Provider | None = None,
    environment: Environment | None = None,
) -> OneshotResult:
    """Run one repair attempt on a copy of task_dir. The original is never modified.

    mode: "docker" (default) runs everything in a locked-down container. "local" runs
    the model's code directly on this machine and must be chosen explicitly.
    confirm: show a diff of the proposed change and ask before writing it and running
    the checks. Defaults to on for local runs and off for Docker, where the code can't
    reach this machine.
    settings/provider/environment: injectable for tests. An injected environment (must
    be unstarted) takes priority over mode; run_oneshot starts it and always stops it.
    """
    settings = settings or load_settings()
    provider = provider or get_provider(settings)
    env = environment or make_environment(mode)
    if confirm is None:
        confirm = isinstance(env, LocalWorkspace)  # only host-side runs need a human check
    no_usage = Usage(input_tokens=0, output_tokens=0)

    with env:
        env.start(task_dir)
        before = env.run_checks()
        if before.passed:
            # Nothing to repair, so don't spend money asking the model.
            return OneshotResult(False, "Checks already pass before any change; task is invalid.", no_usage, 0.0)

        response = provider.complete(
            system=SYSTEM_PROMPT,
            messages=[Message(role="user", content=build_prompt(env, before.output))],
        )
        usage = response.usage
        cost = cost_usd(settings.model, usage)

        try:
            rel_path, new_content = parse_reply(response.text)
            rel_path = resolve_src_path(env, rel_path)
        except ReplyError as error:
            return OneshotResult(False, f"Unusable reply: {error}", usage, cost)

        if confirm and not _approve(rel_path, env.read_file(rel_path), new_content):
            return OneshotResult(False, "Change rejected by user; checks not run.", usage, cost, rel_path)

        env.write_file(rel_path, new_content)
        after = env.run_checks()
        summary = _last_line(after.output)
        reason = f"Checks pass: {summary}" if after.passed else f"Checks still fail: {summary}"
        return OneshotResult(after.passed, reason, usage, cost, rel_path)


def make_environment(mode: Mode) -> Environment:
    """A new, unstarted environment for the given mode."""
    if mode == "docker":
        return DockerSandbox()
    if mode == "local":
        return LocalWorkspace()
    raise ValueError(f"mode must be 'docker' or 'local', got {mode!r}.")


def build_prompt(env: Environment, failure_output: str) -> str:
    """Source files, test files and the trimmed failing output, as one user message."""
    sections = []
    for folder in ("src", "tests"):
        for rel in env.list_files(folder):
            if rel.endswith(".py"):
                sections.append(f"{INPUT_FILE_HEADER}{rel}\n{env.read_file(rel)}")
    sections.append(f"{INPUT_OUTPUT_HEADER}\n{trim_output(failure_output)}")
    return "\n\n".join(sections)


def parse_reply(text: str) -> tuple[str, str]:
    """Extract (path, content) from the model's reply. Raises ReplyError if not exactly one block."""
    blocks = list(_FILE_BLOCK.finditer(text))
    if not blocks:
        raise ReplyError(f"no {FILE_START}...>>> / {FILE_END} block found.")
    if len(blocks) > 1:
        raise ReplyError(f"expected exactly one file block, found {len(blocks)}.")
    path = blocks[0]["path"].strip()
    content = _strip_code_fence(blocks[0]["content"])
    return path, content if content.endswith("\n") else content + "\n"


def resolve_src_path(env: Environment, rel_path: str) -> str:
    """Return the normalised path if it names an existing file under src/, else raise ReplyError.

    The environment's own checks (paths stay inside the task, links aren't followed)
    still apply when the file is later read or written.
    """
    try:
        parts = safe_relative_path(rel_path)
    except UnsafePathError:
        raise ReplyError(f"path {rel_path!r} is not inside src/.") from None
    if parts.parts[:1] != ("src",):
        raise ReplyError(f"path {rel_path!r} is not inside src/.")
    normalised = parts.as_posix()
    if normalised not in env.list_files("src"):
        raise ReplyError(f"path {rel_path!r} is not an existing file.")
    return normalised


def _strip_code_fence(content: str) -> str:
    """Models often wrap the file in ``` fences inside our markers; remove them if so."""
    lines = content.strip("\n").splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        lines = lines[1:-1]
    return "\n".join(lines)


def _approve(rel_path: str, old: str, new: str) -> bool:
    """Print a unified diff and ask the user to approve it."""
    diff = difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"a/{rel_path}", tofile=f"b/{rel_path}",
    )
    print("".join(diff) or f"(no changes to {rel_path})")
    return input("Apply this change and run the checks? [y/N] ").strip().lower() == "y"


def _last_line(output: str) -> str:
    lines = output.strip().splitlines()
    return lines[-1] if lines else "(no output)"
