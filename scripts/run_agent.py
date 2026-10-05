"""Run the repair agent on one task in the Docker sandbox and print the result.

Run from the repo root (so .env is found):
    python scripts/run_agent.py tasks/code/c001_mean
    python scripts/run_agent.py tasks/code/c001_mean --max-steps 10
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from repair_agent.agent import run_agent
from repair_agent.config import ConfigError
from repair_agent.sandbox import SandboxError


def main(argv: list[str] | None = None) -> int:
    # Windows consoles and pipes default to a legacy code page, so characters in test
    # output (like pytest's "±") would print as garbage without this.
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run the repair agent on one task.")
    parser.add_argument("task", type=Path, help="path to a task folder, e.g. tasks/code/c001_mean")
    parser.add_argument("--max-steps", type=int, help="maximum model calls (default: AGENT_MAX_STEPS from .env, or 20)")
    args = parser.parse_args(argv)

    if not args.task.is_dir():
        print(f"Task folder not found: {args.task}", file=sys.stderr)
        return 1
    try:
        result = run_agent(args.task, max_steps=args.max_steps)
    except (ConfigError, SandboxError) as error:
        print(error, file=sys.stderr)
        return 1

    print(f"Task:        {args.task.name}")
    print(f"Passed:      {result.passed}")
    print(f"Stop reason: {result.stop_reason.value}")
    print(f"Detail:      {result.detail}")
    print(f"Steps:       {result.steps}")
    print(f"Tokens:      {result.input_tokens} in / {result.output_tokens} out")
    print(f"Cost:        ${result.cost_usd:.6f}")
    print(f"Run on:      {result.provider} / {result.model} / {result.environment} / prompt {result.prompt_version}")
    print(f"Trace:       {result.trace_path}  (view: python scripts/show_trace.py {result.trace_path})")
    return 0 if result.passed else 2


if __name__ == "__main__":
    sys.exit(main())
