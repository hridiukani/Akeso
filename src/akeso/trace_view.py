"""Turn an agent trace into a readable, step-by-step story (used by `akeso trace`)."""

from __future__ import annotations

from typing import Any

PREVIEW_LINES = 8


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
        elif kind == "check" and event["phase"] in ("initial", "final", "stop"):
            verdict = "PASSED" if event["passed"] else f"FAILED (exit {event['exit_code']})"
            label = "Check after the model stopped" if event["phase"] == "stop" else f"{event['phase'].capitalize()} check"
            lines.append(f"\n{label}: {verdict} in {event['duration']}s")
            if event["phase"] != "stop" or not event["passed"]:
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
        elif kind == "changes":
            lines.append(f"\nAgent changed: {', '.join(event['written'] + event['deleted']) or 'nothing'}")
            if event["ignored"]:
                lines.append(f"  Not carried into grading (outside the editable paths): {', '.join(event['ignored'])}")
            for finding in event["tampering"]:
                lines.append(f"  !! TAMPERING: {finding}")
        elif kind == "grading":
            if event.get("task_kind") == "sql":
                visible = "visible database matched" if event["visible_passed"] else "visible database DIDN'T MATCH"
                hidden = "hidden database matched" if event["hidden_passed"] else "hidden database DIDN'T MATCH"
            else:
                hidden = {True: "hidden tests passed", False: "hidden tests FAILED", None: "no hidden tests"}[event["hidden_passed"]]
                visible = "visible tests passed" if event["visible_passed"] else "visible tests FAILED"
            lines.append(f"\nGraded in a fresh environment: {event['verdict'].upper()} ({visible}, {hidden})")
            if not event["visible_passed"]:
                lines += _indent(event["visible_output"], full)
            elif event["hidden_passed"] is False:
                lines += _indent(event["hidden_output"], full)
        elif kind == "judge_restore":  # traces from before fresh-environment grading
            changed = event["restored"] or event["deleted"]
            lines.append(
                f"\nJudge restored: put back {event['restored'] or 'nothing'}, deleted {event['deleted'] or 'nothing'}"
                + ("  <- the agent had changed the tests or config" if changed else "")
            )
        elif kind == "result":
            lines += [
                f"\nRESULT: {'PASSED' if event['passed'] else 'FAILED'}  "
                f"(verdict: {event.get('verdict', 'n/a')}, stop reason: {event['stop_reason']})",
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
