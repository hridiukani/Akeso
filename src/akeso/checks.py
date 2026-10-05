"""Run a task's tests and report the result. The tests are the judge, never the model."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from akeso.environment import Environment

CHECK_TIMEOUT_SECONDS = 60
DEFAULT_OUTPUT_LIMIT = 4000

# "python" is the interpreter with pytest installed in every environment: the image's
# Python in Docker, and this program's own interpreter in LocalWorkspace.
PYTEST_COMMAND = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one pytest run."""

    passed: bool
    exit_code: int | None  # None when the run was killed by the timeout
    output: str  # stdout and stderr combined, in the order they were printed
    duration: float  # seconds


def run_checks(env: Environment, timeout: float = CHECK_TIMEOUT_SECONDS) -> CheckResult:
    """Run the task's tests inside env.

    Passes only if pytest exits with code 0, so failures, "no tests collected" (5) and
    timeouts all count as failures. `-p no:cacheprovider` keeps .pytest_cache out of
    the task folder.
    """
    start = time.perf_counter()
    result = env.exec(PYTEST_COMMAND, timeout=timeout)
    return CheckResult(
        passed=result.exit_code == 0,
        exit_code=result.exit_code,
        output=result.output,
        duration=time.perf_counter() - start,
    )


def trim_output(output: str, limit: int = DEFAULT_OUTPUT_LIMIT) -> str:
    """Keep the last `limit` characters of output, prefixed by a one-line trim marker.

    pytest prints the failure details and the summary last, so the end is the useful part.
    The marker tells the reader (and the model) that earlier output was cut.
    """
    if limit < 1:
        # output[-0:] would return everything, the opposite of trimming.
        raise ValueError("limit must be at least 1")
    if len(output) <= limit:
        return output
    return f"[...{len(output) - limit} characters trimmed ...]\n" + output[-limit:]


# Parts of pytest output that change between runs even when nothing real changed.
_VOLATILE = [
    (re.compile(r"\x1b\[[0-9;]*m"), ""),  # terminal colour codes
    (re.compile(r"\bin \d+(?:\.\d+)?s(?: \(\d+:\d\d:\d\d\))?"), "in <time>"),  # "in 0.05s (0:00:00)"
    (re.compile(r"\b\d+(?:\.\d+)?s\b"), "<time>"),  # other durations, e.g. "0.12s call"
    (re.compile(r"\b0x[0-9a-fA-F]+\b"), "0x<addr>"),  # memory addresses in reprs
    (re.compile(r"pytest-of-[^/\s]+/pytest-\d+"), "pytest-of-<user>/pytest-<n>"),  # tmp_path dirs
    (re.compile(r"repair-agent-[A-Za-z0-9_]+"), "repair-agent-<tmp>"),  # our workspace dirs
    (re.compile(r"\[\.\.\. ?\d+ characters trimmed \.\.\.\]"), "[... characters trimmed ...]"),
]


def normalize_check_output(output: str) -> str:
    """Remove run-to-run noise (timings, memory addresses, temp paths) from check output.

    Two runs that fail in the same way normalise to the same text, so the agent loop
    can tell when the model is stuck repeating an identical failure.
    """
    for pattern, replacement in _VOLATILE:
        output = pattern.sub(replacement, output)
    return "\n".join(line.rstrip() for line in output.strip().splitlines())
