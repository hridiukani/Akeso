"""Failure categories: why each failed attempt failed, in one word.

Every failed attempt gets exactly one category, the most specific that applies, checked
in this order:

    tampered                  grading found changes outside what may be edited
    provider_token_limit      the conversation outgrew what the provider accepts (HTTP 413)
    crashed                   the harness or provider failed (stop reason "error")
    edit_failed_to_apply      one-shot: the reply had no usable files
    visible_pass_hidden_fail  the visible checks pass but the hidden ones don't (overfitting)
    broke_other_test          a visible test that passed before the change fails after it
                              (from the result's full list of initially failing tests)
    sql_error                 the final query doesn't run
    max_steps, max_cost, max_tokens, repeated_failure, gave_up
                              the loop stopped for that reason with the checks still failing
    wrong_result              anything else: the change ran but the answer is still wrong

Passing attempts have no category. A human can override any of them in the run folder's
labels.yaml, one line per attempt (".r2" for repeat 2, as in the trace names):

    c002_shipping: wrong_result
    c003_discount.r2: gave_up
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

from akeso.checks import failing_tests
from akeso.trace import read_trace

LABELS_FILE = "labels.yaml"

CATEGORIES = (
    "tampered", "provider_token_limit", "crashed", "edit_failed_to_apply", "visible_pass_hidden_fail",
    "broke_other_test", "sql_error", "max_steps", "max_cost", "max_tokens", "repeated_failure", "gave_up",
    "wrong_result",
)
_STOPPED_BY = {"max_steps", "max_cost", "max_tokens", "repeated_failure", "gave_up"}


class LabelsError(ValueError):
    """labels.yaml can't be used."""


def categorize(result: Mapping[str, Any], trace: Iterable[Mapping[str, Any]] = ()) -> str | None:
    """The category of one attempt (a result as in summary.json), or None if it passed.
    The trace (its events) is needed to spot broke_other_test and sql_error. Results from
    before initial_failing_tests was recorded fall back to the trace's initial check, which
    is cut short for long output."""
    if result.get("passed"):
        return None
    stop = result.get("stop_reason")
    if result.get("verdict") == "tampered":
        return "tampered"
    if stop == "provider_token_limit":
        return "provider_token_limit"
    if stop == "error":
        return "crashed"
    if stop == "edit_failed":
        return "edit_failed_to_apply"
    if result.get("visible_passed") and result.get("hidden_passed") is False:
        return "visible_pass_hidden_fail"
    initial, grading = _initial_and_grading(trace)
    if grading is not None:
        visible = str(grading.get("visible_output") or "")
        if grading.get("task_kind") == "sql":
            if "failed to run" in visible:
                return "sql_error"
        else:
            before = result.get("initial_failing_tests")
            if before is None and initial is not None:
                before = failing_tests(str(initial.get("output") or ""))
            if before is not None and set(failing_tests(visible)) - set(before):
                return "broke_other_test"
    if stop in _STOPPED_BY:
        return stop
    return "wrong_result"


def categorize_run(summary: Mapping[str, Any], run_dir: str | Path) -> list[str | None]:
    """Each result's category, in order: labels.yaml overrides, else the automatic one."""
    run_dir = Path(run_dir)
    labels = read_labels(run_dir)
    categories = []
    for result in summary.get("results", []):
        key = label_key(result["task_id"], result.get("repeat", 1))
        if key in labels:
            categories.append(labels[key])
            continue
        categories.append(categorize(result, _trace_events(result, run_dir)))
    return categories


def category_counts(categories: Iterable[str | None]) -> dict[str, int]:
    """How many failed attempts fell in each category, most common first."""
    counts = Counter(c for c in categories if c)
    return dict(sorted(counts.items(), key=lambda item: (-item[1], CATEGORIES.index(item[0]))))


def label_key(task_id: str, repeat: int) -> str:
    return task_id if repeat == 1 else f"{task_id}.r{repeat}"


def read_labels(run_dir: str | Path) -> dict[str, str]:
    """The manual overrides in <run_dir>/labels.yaml ({} if there's no file)."""
    path = Path(run_dir) / LABELS_FILE
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as problem:
        raise LabelsError(f"{path} isn't valid YAML: {problem}") from problem
    if not isinstance(data, dict):
        raise LabelsError(f"{path} must map attempts to categories, e.g. 'c002_shipping: wrong_result'")
    unknown = {str(k): v for k, v in data.items() if v not in CATEGORIES}
    if unknown:
        raise LabelsError(f"{path}: unknown categor(ies) {unknown}; use one of: {', '.join(CATEGORIES)}")
    return {str(k): str(v) for k, v in data.items()}


def _initial_and_grading(trace: Iterable[Mapping[str, Any]]) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    initial = grading = None
    for event in trace:
        if event.get("event") == "check" and event.get("phase") == "initial":
            initial = event
        elif event.get("event") == "grading":
            grading = event
    return initial, grading


def _trace_events(result: Mapping[str, Any], run_dir: Path) -> list[dict[str, Any]]:
    """The attempt's trace events, or [] if the trace is missing or unreadable."""
    recorded = result.get("trace_path")
    if not recorded:
        return []
    path = Path(recorded)
    if not path.is_file():
        path = run_dir / path.name  # the run folder may have been moved since
    try:
        return read_trace(path) if path.is_file() else []
    except (OSError, ValueError):
        return []
