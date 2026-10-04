"""Run a task's tests and report the result. The tests are the judge, never the model."""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

CHECK_TIMEOUT_SECONDS = 60
DEFAULT_OUTPUT_LIMIT = 4000


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one pytest run."""

    passed: bool
    exit_code: int | None  # None when the run was killed by the timeout
    output: str  # stdout and stderr combined, in the order they were printed
    duration: float  # seconds


def run_checks(workdir: str | Path, timeout: float = CHECK_TIMEOUT_SECONDS) -> CheckResult:
    """Run pytest in workdir with the current Python interpreter.

    Passes only if pytest exits with code 0. A timeout counts as a failure.
    """
    command = [
        sys.executable,  # same interpreter (and installed pytest) as this program
        "-m", "pytest",
        "-q",
        "-p", "no:cacheprovider",  # don't write .pytest_cache into the workspace
    ]
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=workdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # merge so errors appear next to the output they belong to
            text=True,
            encoding="utf-8",
            errors="replace",  # never crash on odd bytes in test output
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        partial = error.output or ""
        if isinstance(partial, bytes):  # TimeoutExpired can hold bytes even when text=True
            partial = partial.decode("utf-8", errors="replace")
        return CheckResult(
            passed=False,
            exit_code=None,
            output=f"{partial}\n[checks timed out after {timeout:g} seconds]",
            duration=time.perf_counter() - start,
        )

    return CheckResult(
        passed=completed.returncode == 0,
        exit_code=completed.returncode,
        output=completed.stdout,
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
