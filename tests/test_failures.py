"""Tests for automatic failure categories and the labels file."""

from pathlib import Path

import pytest

from akeso.failures import LabelsError, categorize, categorize_run, category_counts, read_labels
from akeso.trace import TraceWriter


def result(**fields) -> dict:
    return {"task_id": "c001", "repeat": 1, "passed": False, "verdict": "failed", "stop_reason": "max_steps",
            "visible_passed": False, "hidden_passed": None, **fields}


def trace(initial: str, visible: str, kind: str = "code") -> list[dict]:
    return [{"event": "check", "phase": "initial", "output": initial},
            {"event": "grading", "task_kind": kind, "visible_output": visible}]


@pytest.mark.parametrize("fields, category", [
    ({"passed": True, "verdict": "passed"}, None),
    ({"verdict": "tampered", "stop_reason": "passed"}, "tampered"),
    ({"stop_reason": "provider_token_limit", "verdict": "passed"}, "provider_token_limit"),
    ({"stop_reason": "error"}, "crashed"),
    ({"stop_reason": "edit_failed"}, "edit_failed_to_apply"),
    ({"stop_reason": "passed", "visible_passed": True, "hidden_passed": False}, "visible_pass_hidden_fail"),
    ({"stop_reason": "max_steps"}, "max_steps"),
    ({"stop_reason": "max_cost"}, "max_cost"),
    ({"stop_reason": "max_tokens"}, "max_tokens"),
    ({"stop_reason": "repeated_failure"}, "repeated_failure"),
    ({"stop_reason": "gave_up"}, "gave_up"),
    ({"stop_reason": "one_shot"}, "wrong_result"),
    ({"stop_reason": "passed"}, "wrong_result"),  # its own checks passed, grading's didn't
])
def test_categories_from_the_result(fields: dict, category: str | None) -> None:
    assert categorize(result(**fields)) == category


def test_a_newly_failing_visible_test_is_broke_other_test() -> None:
    before = "FAILED tests/test_a.py::test_one - assert 1 == 2\n1 failed, 1 passed"
    after = "FAILED tests/test_a.py::test_one - assert\nFAILED tests/test_a.py::test_two - boom\n2 failed"

    assert categorize(result(), trace(before, after)) == "broke_other_test"
    assert categorize(result(), trace(before, before)) == "max_steps"  # same failures as at the start


def test_a_collection_error_counts_as_breaking_tests() -> None:
    before = "FAILED tests/test_a.py::test_one - assert\n1 failed"
    after = "ERROR tests/test_a.py - SyntaxError\n1 error"

    assert categorize(result(stop_reason="gave_up"), trace(before, after)) == "broke_other_test"


def test_a_query_that_does_not_run_is_sql_error() -> None:
    events = trace("", "solution.sql failed to run on visible.db: no such column: x", kind="sql")

    assert categorize(result(stop_reason="gave_up"), events) == "sql_error"
    assert categorize(result(stop_reason="gave_up"), trace("", "row count differs", kind="sql")) == "gave_up"


def test_counts_skip_passes_and_put_the_most_common_first() -> None:
    assert category_counts([None, "gave_up", "max_steps", "gave_up", None]) == {"gave_up": 2, "max_steps": 1}


def test_labels_override_the_automatic_category(tmp_path: Path) -> None:
    path = tmp_path / "c001.r2.jsonl"
    with TraceWriter(path) as writer:
        writer.event("grading", task_kind="code", visible_output="")
    (tmp_path / "labels.yaml").write_text("c001: wrong_result\n", encoding="utf-8")
    summary = {"results": [result(), result(repeat=2, stop_reason="gave_up", trace_path="moved/c001.r2.jsonl")]}

    assert categorize_run(summary, tmp_path) == ["wrong_result", "gave_up"]


@pytest.mark.parametrize("content, message", [
    ("c001: lazy\n", "unknown categor"),
    ("- c001\n", "must map attempts"),
    ("c001: [\n", "isn't valid YAML"),
])
def test_bad_labels_files(tmp_path: Path, content: str, message: str) -> None:
    (tmp_path / "labels.yaml").write_text(content, encoding="utf-8")

    with pytest.raises(LabelsError, match=message):
        read_labels(tmp_path)


def test_no_labels_file_means_no_overrides(tmp_path: Path) -> None:
    assert read_labels(tmp_path) == {}
