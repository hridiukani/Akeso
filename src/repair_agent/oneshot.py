"""One-shot repair: show the model the failing task once, apply its fix, rerun the checks."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from repair_agent.checks import run_checks, trim_output
from repair_agent.config import Settings, load_settings
from repair_agent.llm.cost import cost_usd
from repair_agent.llm.provider import Provider, get_provider
from repair_agent.llm.types import Message, Usage
from repair_agent.workspace import cleanup_workspace, create_workspace

# Unusual markers rather than ``` fences, because file contents can contain fences.
FILE_START = "<<<FILE: "
FILE_END = "<<<END FILE>>>"
_FILE_BLOCK = re.compile(
    r"^<<<FILE: (?P<path>[^\n>]+)>>>\n(?P<content>.*?)\n?<<<END FILE>>>[ \t]*$",
    re.MULTILINE | re.DOTALL,
)

SYSTEM_PROMPT = f"""You fix bugs in small Python projects.
You will see the project's source files, its test files, and the output of the failing tests.
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
    confirm: bool = True,
    settings: Settings | None = None,
    provider: Provider | None = None,
) -> OneshotResult:
    """Run one repair attempt on a copy of task_dir. The original is never modified.

    confirm: show a diff of the proposed change and ask before writing it and running
    the checks. On by default because, until the Docker sandbox exists, checks run
    model-edited code directly on this machine.
    settings/provider: injectable for tests; loaded from config when omitted.
    """
    settings = settings or load_settings()
    provider = provider or get_provider(settings)
    no_usage = Usage(input_tokens=0, output_tokens=0)

    workspace = create_workspace(task_dir)
    try:
        before = run_checks(workspace)
        if before.passed:
            # Nothing to repair, so don't spend money asking the model.
            return OneshotResult(False, "Checks already pass before any change; task is invalid.", no_usage, 0.0)

        response = provider.complete(
            system=SYSTEM_PROMPT,
            messages=[Message(role="user", content=build_prompt(workspace, before.output))],
        )
        usage = response.usage
        cost = cost_usd(settings.model, usage)

        try:
            rel_path, new_content = parse_reply(response.text)
            target = resolve_src_path(workspace, rel_path)
        except ReplyError as error:
            return OneshotResult(False, f"Unusable reply: {error}", usage, cost)

        if confirm and not _approve(rel_path, target.read_text(encoding="utf-8"), new_content):
            return OneshotResult(False, "Change rejected by user; checks not run.", usage, cost, rel_path)

        target.write_text(new_content, encoding="utf-8")
        after = run_checks(workspace)
        summary = _last_line(after.output)
        reason = f"Checks pass: {summary}" if after.passed else f"Checks still fail: {summary}"
        return OneshotResult(after.passed, reason, usage, cost, rel_path)
    finally:
        cleanup_workspace(workspace)


def build_prompt(workspace: Path, failure_output: str) -> str:
    """Source files, test files and the trimmed failing output, as one user message."""
    sections = []
    for folder in ("src", "tests"):
        for path in sorted((workspace / folder).rglob("*.py")):
            rel = path.relative_to(workspace).as_posix()
            sections.append(f"===== {rel} =====\n{path.read_text(encoding='utf-8')}")
    sections.append(f"===== failing test output =====\n{trim_output(failure_output)}")
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


def resolve_src_path(workspace: Path, rel_path: str) -> Path:
    """Return the workspace file for rel_path, refusing anything that isn't an existing file under src/."""
    parts = PurePosixPath(rel_path.replace("\\", "/"))
    if parts.is_absolute() or ".." in parts.parts or not parts.parts or parts.parts[0] != "src":
        raise ReplyError(f"path {rel_path!r} is not inside src/.")
    target = (workspace / parts).resolve()
    # Second line of defence: after resolving, the file must still sit inside workspace/src.
    if not target.is_relative_to((workspace / "src").resolve()):
        raise ReplyError(f"path {rel_path!r} resolves outside src/.")
    if not target.is_file():
        raise ReplyError(f"path {rel_path!r} is not an existing file.")
    return target


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
