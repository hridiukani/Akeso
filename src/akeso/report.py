"""report.html: one self-contained page per run, to read or publish (e.g. on GitHub Pages).

Everything is inline (styles, no scripts, no fonts or images from elsewhere), so the file
opens straight from disk. It shows the run's label (official or dev) and fingerprint, the
stats overall and per split, the failure categories, every attempt's result, and each
attempt's trace as an expandable section: model messages, tool calls with trimmed output,
and edits as diffs.
"""

from __future__ import annotations

import difflib
import html
import json
from pathlib import Path
from typing import Any

from akeso.checks import trim_output
from akeso.failures import category_counts, categorize_run
from akeso.trace import read_trace

REPORT_FILE = "report.html"
TEXT_LIMIT = 4000  # characters of any one message or output shown in the report


def write_report(run_dir: str | Path) -> Path:
    """Build <run_dir>/report.html from summary.json, the traces and labels.yaml."""
    run_dir = Path(run_dir)
    path = run_dir / REPORT_FILE
    path.write_text(build_report(run_dir), encoding="utf-8")
    return path


def build_report(run_dir: str | Path) -> str:
    run_dir = Path(run_dir)
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    categories = categorize_run(summary, run_dir)  # labels.yaml applied now, not when the run was written
    results = summary.get("results", [])
    run_type = summary.get("run_type") or "dev"
    title = f"Akeso run {summary['run_id']}"
    parts = [
        f"<h1>{_e(title)} <span class='badge {_e(run_type)}'>{_e(run_type)} run</span></h1>",
        _overview(summary),
        "<h2>Results by split</h2>", _stats(summary),
        "<h2>Failure categories</h2>", _categories(results, categories),
        "<h2>Attempts</h2>", _results_table(results, categories),
        _not_run(summary),
        "<h2>Traces</h2>",
        *(_trace_section(result, category, run_dir) for result, category in zip(results, categories)),
        "<h2>Fingerprint</h2>", _fingerprint(summary.get("fingerprint") or {}),
    ]
    return _PAGE.format(title=_e(title), style=_STYLE, body="\n".join(parts))


def _overview(summary: dict[str, Any]) -> str:
    t = summary.get("totals", {})
    if summary.get("complete", True):
        status = "complete"
    elif summary.get("not_run"):
        status = (f"incomplete: {len(summary['not_run'])} attempt(s) not run "
                  f"({summary.get('stopped') or 'interrupted'})")
    else:
        status = f"incomplete: {len(summary.get('crashed') or [])} attempt(s) crashed and must be rerun"
    if summary.get("run_type") == "official":
        label = "Official run: the measurement setup, the frozen suite unmodified, a clean working tree."
    else:
        label = "Dev run: not an official measurement; don't report these numbers."
    rows = [
        ("Label", label),
        ("Provider / model", f"{summary.get('provider')} / {summary.get('model')}"),
        ("Mode", summary.get("mode") or "loop"),
        ("Prompt version", summary.get("prompt_version")),
        ("Tasks x repeats", f"{t.get('tasks', 0)} x {summary.get('repeats', 1)} ({t.get('attempts', 0)} attempts)"),
        ("Crashed", f"{t.get('crashed', 0)} (harness or provider errors; not scored, rerun by --resume)"),
        ("Status", status),
        ("Started", summary.get("started")),
        ("Resumed", ", ".join(summary.get("resumed") or []) or "never"),
        ("Cost", f"${t.get('total_cost_usd', 0):.4f} ({summary.get('cost_basis', '')})"),
    ]
    return _key_values(rows)


def _stats(summary: dict[str, Any]) -> str:
    t = summary.get("totals", {})
    groups = [("overall", t), *t.get("by_split", {}).items()]
    head = ["Group", "Tasks", "Scored", "Crashed", "Passed", "Pass rate (mean ± std over repeats)", "pass@1", "pass@k",
            "Avg steps", "Avg tokens", "Avg cost", "Total cost"]
    rows = []
    for name, g in groups:
        rows.append([
            name, g.get("tasks", 0), g.get("scored_attempts", g.get("attempts", 0)), g.get("crashed", 0),
            g.get("passed", 0),
            f"{g.get('pass_rate_mean', 0):.0%} ± {g.get('pass_rate_std', 0):.0%}",
            f"{g.get('pass_at_1', 0):.0%}", f"pass@{g.get('k', 1)} {g.get('pass_at_k', 0):.0%}",
            f"{g.get('average_steps', 0):.1f}", f"{g.get('average_tokens', 0):,.0f}",
            f"${g.get('average_cost_usd', 0):.4f}", f"${g.get('total_cost_usd', 0):.4f}",
        ])
    return _table(head, rows)


def _categories(results: list[dict[str, Any]], categories: list[str | None]) -> str:
    overall = category_counts(categories)
    if not overall:
        return "<p>No failed attempts.</p>"
    splits = sorted({r.get("split") for r in results if r.get("split")})
    by_split = {s: category_counts(c for r, c in zip(results, categories) if r.get("split") == s) for s in splits}
    rows = [[name, count, *(by_split[s].get(name, 0) for s in splits)] for name, count in overall.items()]
    note = "<p class='note'>Automatic, unless overridden in the run folder's labels.yaml.</p>"
    return _table(["Category", "All", *splits], rows) + note


def _results_table(results: list[dict[str, Any]], categories: list[str | None]) -> str:
    head = ["Task", "Split", "Repeat", "Verdict", "Stop reason", "Category", "Steps", "Tokens", "Cost", "Detail"]
    rows = []
    for r, category in zip(results, categories):
        anchor = _anchor(r)
        rows.append([
            f"<a href='#{anchor}'>{_e(r['task_id'])}</a>", r.get("split") or "", r.get("repeat", 1),
            f"<span class='v {_e(r.get('verdict'))}'>{_e(r.get('verdict'))}</span>", r.get("stop_reason"),
            category or "", r.get("steps", 0), f"{r.get('input_tokens', 0) + r.get('output_tokens', 0):,}",
            f"${r.get('cost_usd', 0):.4f}", r.get("detail", ""),
        ])
    return _table(head, rows, raw_columns={0, 3})


def _not_run(summary: dict[str, Any]) -> str:
    missing = summary.get("not_run") or []
    if not missing:
        return ""
    items = "".join(f"<li>{_e(m['task_id'])} (repeat {m['repeat']})</li>" for m in missing)
    return (f"<h2>Not run</h2><p>{_e(summary.get('stopped') or 'The run was interrupted.')} "
            f"Finish with <code>akeso run --resume {_e(summary['run_id'])}</code>.</p><ul>{items}</ul>")


def _trace_section(result: dict[str, Any], category: str | None, run_dir: Path) -> str:
    events = _events(result, run_dir)
    summary_line = (f"{_e(result['task_id'])} · repeat {result.get('repeat', 1)} · "
                    f"<span class='v {_e(result.get('verdict'))}'>{_e(result.get('verdict'))}</span> · "
                    f"{_e(result.get('stop_reason'))}" + (f" · {_e(category)}" if category else ""))
    body = "".join(_event(e) for e in events) if events else "<p class='note'>No trace found.</p>"
    return f"<details id='{_anchor(result)}'><summary>{summary_line}</summary>{body}</details>"


def _event(event: dict[str, Any]) -> str:
    kind = event.get("event")
    if kind == "check":
        state = "passed" if event.get("passed") else "failed"
        return (f"<div class='ev check'><b>Check ({_e(event.get('phase'))}): {state}</b>"
                f"{_pre(event.get('output', ''))}</div>")
    if kind == "model_call":
        text = (event.get("text") or "").strip()
        calls = ", ".join(c.get("name", "?") for c in event.get("tool_calls") or []) or "none (stopped)"
        return (f"<div class='ev model'><b>Step {event.get('step')}: model</b> "
                f"<span class='note'>{event.get('input_tokens', 0):,} in / {event.get('output_tokens', 0):,} out tokens, "
                f"${event.get('cost_usd', 0):.6f}; tool calls: {_e(calls)}</span>"
                + (_pre(text) if text else "") + "</div>")
    if kind == "tool_call":
        status = "error" if event.get("is_error") else "ok"
        arguments = event.get("arguments") or {}
        return (f"<div class='ev tool {status}'><b>{_e(event.get('name'))}</b> "
                f"<code>{_e(_short_arguments(arguments))}</code> <span class='note'>{status}</span>"
                + _edit_diff(event.get("name"), arguments) + _pre(event.get("result", "")) + "</div>")
    if kind == "changes":
        written = ", ".join(event.get("written") or []) or "nothing"
        return f"<div class='ev'><b>Changes collected:</b> {_e(written)}</div>"
    if kind == "grading":
        return (f"<div class='ev grading'><b>Grading in a fresh environment: {_e(event.get('verdict'))}</b>"
                f"{_pre(event.get('visible_output', ''))}"
                + (_pre(event.get("hidden_output")) if event.get("hidden_output") else "") + "</div>")
    if kind == "error":
        return f"<div class='ev tool error'><b>Error</b>{_pre(event.get('error', ''))}</div>"
    return ""  # run_start and result are in the tables above


def _edit_diff(name: Any, arguments: dict[str, Any]) -> str:
    """apply_edit as a diff of old_str -> new_str; a one-shot write_file shows its content."""
    if name == "apply_edit" and "old_str" in arguments and "new_str" in arguments:
        lines = difflib.unified_diff(str(arguments["old_str"]).splitlines(), str(arguments["new_str"]).splitlines(),
                                     fromfile=str(arguments.get("path", "")), tofile=str(arguments.get("path", "")),
                                     lineterm="")
        return _diff(list(lines))
    if name == "write_file" and "content" in arguments:
        return _pre(str(arguments["content"]))
    return ""


def _diff(lines: list[str]) -> str:
    def css(line: str) -> str:
        if line.startswith(("+++", "---")):
            return "h"
        return {"+": "add", "-": "del", "@": "h"}.get(line[:1], "")
    body = "\n".join(f"<span class='{css(line)}'>{_e(line)}</span>" for line in lines)
    return f"<pre class='diff'>{body}</pre>"


def _short_arguments(arguments: dict[str, Any]) -> str:
    shown = {k: v for k, v in arguments.items() if k not in ("old_str", "new_str", "content")}
    return ", ".join(f"{k}={str(v)[:200]!r}" for k, v in shown.items())


def _fingerprint(fp: dict[str, Any]) -> str:
    return _key_values([(name, _format(value)) for name, value in fp.items()])


def _format(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in value.items())
    return "" if value is None else str(value)


def _events(result: dict[str, Any], run_dir: Path) -> list[dict[str, Any]]:
    recorded = result.get("trace_path")
    if not recorded:
        return []
    path = Path(recorded)
    if not path.is_file():
        path = run_dir / path.name
    try:
        return read_trace(path) if path.is_file() else []
    except (OSError, ValueError):
        return []


def _anchor(result: dict[str, Any]) -> str:
    return f"t-{result['task_id']}-r{result.get('repeat', 1)}"


def _pre(text: Any) -> str:
    return f"<pre>{_e(trim_output(str(text), TEXT_LIMIT))}</pre>" if str(text).strip() else ""


def _key_values(rows: list[tuple[str, Any]]) -> str:
    body = "".join(f"<tr><th>{_e(k)}</th><td>{_e(v)}</td></tr>" for k, v in rows)
    return f"<table class='kv'>{body}</table>"


def _table(head: list[str], rows: list[list[Any]], raw_columns: set[int] = frozenset()) -> str:
    """raw_columns hold HTML this module built (already escaped); everything else is escaped."""
    header = "".join(f"<th>{_e(h)}</th>" for h in head)
    body = "".join(
        "<tr>" + "".join(f"<td>{cell if i in raw_columns else _e(cell)}</td>" for i, cell in enumerate(row)) + "</tr>"
        for row in rows)
    return f"<div class='scroll'><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>"


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


_STYLE = """
:root { --bg: #ffffff; --fg: #1d2330; --muted: #5d6675; --line: #d9dde4; --panel: #f5f7fa;
        --pass: #17803d; --fail: #b42318; --tamper: #8e3bb5; --add: #e6f6ea; --del: #fdecec; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #14171c; --fg: #e3e7ee; --muted: #9aa3b2; --line: #2d333d; --panel: #1c2027;
          --pass: #4cc47a; --fail: #f07068; --tamper: #c48ae6; --add: #183323; --del: #3a1d1d; }
}
* { box-sizing: border-box; }
body { margin: 0 auto; max-width: 1200px; padding: 24px 16px 64px; background: var(--bg); color: var(--fg);
       font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
h1 { font-size: 1.6rem; margin: 0 0 16px; } h2 { font-size: 1.2rem; margin: 32px 0 8px; }
.badge { font-size: .8rem; padding: 2px 8px; border-radius: 999px; vertical-align: middle; border: 1px solid; }
.badge.official { color: var(--pass); } .badge.dev { color: var(--muted); }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
thead th { background: var(--panel); position: sticky; top: 0; }
table.kv th { width: 220px; color: var(--muted); font-weight: 500; }
.v.passed { color: var(--pass); } .v.failed { color: var(--fail); } .v.tampered { color: var(--tamper); }
details { border: 1px solid var(--line); border-radius: 8px; margin: 8px 0; background: var(--panel); }
summary { cursor: pointer; padding: 8px 12px; font-weight: 600; }
details[open] summary { border-bottom: 1px solid var(--line); }
.ev { padding: 8px 12px; border-bottom: 1px dashed var(--line); }
.ev.error b { color: var(--fail); }
.note { color: var(--muted); font-size: .85rem; }
pre { background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: 8px; overflow-x: auto;
      white-space: pre-wrap; word-break: break-word; font-size: .8rem; max-height: 420px; overflow-y: auto; }
pre.diff .add { background: var(--add); display: block; } pre.diff .del { background: var(--del); display: block; }
pre.diff .h { color: var(--muted); display: block; }
code { font-size: .85rem; }
"""

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{style}</style>
</head>
<body>
{body}
</body>
</html>
"""
