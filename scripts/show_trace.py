"""Print an agent trace as a readable, step-by-step story.

    python scripts/show_trace.py runs/<run_id>/<task_id>.jsonl
    python scripts/show_trace.py runs/<run_id>            # every task in the run
    python scripts/show_trace.py runs/<run_id> --full     # don't shorten long outputs
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from akeso.trace import read_trace

PREVIEW_LINES = 8


def main(argv: list[str] | None = None) -> int:
    # Windows consoles and pipes default to a legacy code page, so characters in test
    # output (like pytest's "±") would print as garbage without this.
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Show an agent trace as a story.")
    parser.add_argument("path", type=Path, help="a .jsonl trace, or a run folder containing them")
    parser.add_argument("--full", action="store_true", help="show complete outputs instead of previews")
    args = parser.parse_args(argv)

    paths = sorted(args.path.glob("*.jsonl")) if args.path.is_dir() else [args.path]
    if not paths or not all(path.is_file() for path in paths):
        print(f"No trace found at {args.path}", file=sys.stderr)
        return 1
    for path in paths:
        print(story(read_trace(path), full=args.full))
        print()
    return 0


def story(events: list[dict[str, Any]], full: bool = False) -> str:
    """Turn a list of trace events into readable text."""
    lines: list[str] = []
    for event in events:
        kind = event["event"]
        if kind == "run_start":
            limits = event["limits"]
            lines += [
                f"=== Run {event['run_id']}  task {event['task_id']} ===",
                f"{event['provider']} / {event['model']} / {event['environment']} / prompt {event['prompt_version']}",
                f"Limits: {limits['max_steps']} steps, ${limits['max_cost_usd']}, "
                f"{limits['max_total_tokens']} tokens, stop after {limits['repeated_failure_limit']} identical failures",
            ]
        elif kind == "check" and event["phase"] in ("initial", "final"):
            verdict = "PASSED" if event["passed"] else f"FAILED (exit {event['exit_code']})"
            lines.append(f"\n{event['phase'].capitalize()} check: {verdict} in {event['duration']}s")
            lines += _indent(event["output"], full)
        elif kind == "model_call":
            lines.append(
                f"\nStep {event['step']}: model used {event['input_tokens']} in / {event['output_tokens']} out tokens"
                f" (${event['cost_usd']:.6f}; total {event['total_tokens']} tokens, ${event['total_cost_usd']:.6f})"
            )
            if event["text"].strip():
                lines += _indent(f'Model says: {event["text"].strip()}', full, prefix="  ")
            if not event["tool_calls"]:
                lines.append("  (no tool calls: the model stopped)")
        elif kind == "tool_call":
            status = "ERROR" if event["is_error"] else "ok"
            lines.append(f"  -> {event['name']}({_arguments(event['arguments'], full)})  [{event['duration']}s, {status}]")
            lines += _indent(event["result"], full, prefix="       | ")
        elif kind == "error":
            lines.append(f"\n!! Error at step {event['step']}: {event['error']}")
        elif kind == "judge_restore":
            changed = event["restored"] or event["deleted"]
            lines.append(
                f"\nJudge restored: put back {event['restored'] or 'nothing'}, deleted {event['deleted'] or 'nothing'}"
                + ("  <- the agent had changed the tests or config" if changed else "")
            )
        elif kind == "result":
            lines += [
                f"\nRESULT: {'PASSED' if event['passed'] else 'FAILED'}  (stop reason: {event['stop_reason']})",
                f"  {event['detail']}",
                f"  {event['steps']} steps, {event['input_tokens']} in / {event['output_tokens']} out tokens, ${event['cost_usd']:.6f}",
            ]
    return "\n".join(lines)


def _arguments(arguments: dict[str, Any], full: bool) -> str:
    parts = []
    for name, value in arguments.items():
        text = repr(value)
        if not full and len(text) > 60:
            text = text[:57] + "..."
        parts.append(f"{name}={text}")
    return ", ".join(parts)


def _indent(text: str, full: bool, prefix: str = "    ") -> list[str]:
    lines = text.rstrip().splitlines() or ["(empty)"]
    if not full and len(lines) > PREVIEW_LINES:
        hidden = len(lines) - PREVIEW_LINES
        lines = lines[:PREVIEW_LINES] + [f"... ({hidden} more lines; use --full)"]
    return [prefix + line for line in lines]


if __name__ == "__main__":
    sys.exit(main())
