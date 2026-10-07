"""Tests for traces: the writer itself, and the events an agent run records."""

import json
from pathlib import Path

import pytest

from fakes import FakeFactory, ScriptedProvider, make_task, text_reply, tool_reply
from akeso.agent import StopReason, run_agent
from akeso.config import AgentLimits, Settings
from akeso.prompts import AGENT_PROMPT_VERSION
from akeso.trace import TraceWriter, new_run_id, read_trace, trace_path
from akeso.trace_view import story

FAKE_KEY = "gsk-fake-key-that-must-never-be-traced"
SETTINGS = Settings(provider="groq", groq_model="openai/gpt-oss-120b", anthropic_model=None, groq_api_key=FAKE_KEY)


def test_writer_appends_one_json_object_per_line(tmp_path: Path) -> None:
    path = tmp_path / "run" / "task.jsonl"
    with TraceWriter(path) as trace:
        trace.event("first", value=1)
        trace.event("second", reason=StopReason.MAX_STEPS, limits=AgentLimits(), where=Path("a/b"))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first, second = (json.loads(line) for line in lines)
    assert first["event"] == "first" and first["value"] == 1 and "ts" in first
    assert second["reason"] == "max_steps"  # enums are written as their value
    assert second["limits"]["max_steps"] == 20  # dataclasses become objects
    assert second["where"] == "a/b"
    assert read_trace(path) == [first, second]


def test_run_ids_are_unique_and_sortable() -> None:
    ids = [new_run_id() for _ in range(50)]

    assert len(set(ids)) == 50
    assert all(len(run_id.split("-")) == 3 for run_id in ids)


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    return make_task(tmp_path / "tasks", {
        "src/stats.py": "def mean(n):\n    return sum(n) / (len(n) - 1)\n",
        "tests/test_stats.py": "def test_mean(): ...\n",
    }, task_id="c999_demo")


def fixed_when_edited(files: dict[str, str]) -> tuple[bool, str]:
    if "- 1" not in files["src/stats.py"]:
        return True, "1 passed in 0.01s"
    return False, "FAILED tests/test_stats.py::test_mean - assert 6.0 == 4\n1 failed in 0.01s"


def test_agent_run_records_every_event(task_dir: Path, tmp_path: Path) -> None:
    provider = ScriptedProvider([
        tool_reply(("read_file", {"path": "src/stats.py"}), text="Let me look."),
        tool_reply(("apply_edit", {"path": "src/stats.py", "old_str": "(len(n) - 1)", "new_str": "len(n)"})),
        tool_reply(("run_checks", {})),
    ])
    result = run_agent(task_dir, settings=SETTINGS, provider=provider, environment_factory=FakeFactory(checks=fixed_when_edited),
                       run_id="run-1", trace_dir=tmp_path / "runs")

    path = trace_path(tmp_path / "runs", "run-1", "c999_demo")
    assert result.trace_path == path.as_posix()
    events = read_trace(path)
    kinds = [event["event"] for event in events]
    assert kinds == [
        "run_start", "check",
        "model_call", "tool_call",
        "model_call", "tool_call",
        "model_call", "tool_call", "check",
        "changes", "grading", "result",
    ]

    start = events[0]
    assert start["provider"] == "groq" and start["model"] == "openai/gpt-oss-120b"
    assert start["environment"] == "fake" and start["prompt_version"] == AGENT_PROMPT_VERSION
    assert start["limits"] == {"max_steps": 20, "max_cost_usd": 1.0, "max_total_tokens": 300000, "repeated_failure_limit": 3}

    first_call = events[2]
    assert first_call["step"] == 1 and first_call["text"] == "Let me look."
    assert first_call["input_tokens"] == 100 and first_call["tool_calls"][0]["name"] == "read_file"

    edit = events[5]
    assert edit["name"] == "apply_edit" and edit["is_error"] is False and "duration" in edit
    assert edit["arguments"]["new_str"] == "len(n)"

    assert [e["phase"] for e in events if e["event"] == "check"] == ["initial", "agent"]
    changes = events[-3]
    assert changes["written"] == ["src/stats.py"] and changes["ignored"] == [] and changes["tampering"] == []
    grading = events[-2]
    assert grading["verdict"] == "passed" and grading["applied"] == ["src/stats.py"]
    assert grading["visible_passed"] is True and grading["hidden_passed"] is None
    assert events[-1]["passed"] is True and events[-1]["verdict"] == "passed"
    assert events[-1]["task_id"] == "c999_demo" and events[-1]["stop_reason"] == "passed"

    assert FAKE_KEY not in path.read_text(encoding="utf-8")  # secrets never reach traces


def test_trace_records_errors_and_early_stops(task_dir: Path, tmp_path: Path) -> None:
    provider = ScriptedProvider([text_reply("I give up.")])

    result = run_agent(task_dir, settings=SETTINGS, provider=provider, environment_factory=FakeFactory(), trace_dir=tmp_path)

    events = read_trace(Path(result.trace_path))
    assert events[-1]["stop_reason"] == "gave_up"
    assert events[-1]["passed"] is False
    assert "grading" in [e["event"] for e in events]  # graded even when the model gives up
    assert events[-1]["verdict"] == "failed"


def test_story_tells_what_happened(task_dir: Path, tmp_path: Path) -> None:
    provider = ScriptedProvider([
        tool_reply(("apply_edit", {"path": "src/stats.py", "old_str": "nope", "new_str": "x"}), text="Trying an edit."),
        tool_reply(("apply_edit", {"path": "src/stats.py", "old_str": "(len(n) - 1)", "new_str": "len(n)"})),
        tool_reply(("run_checks", {})),
    ])
    result = run_agent(
        task_dir, settings=SETTINGS, provider=provider,
        environment_factory=FakeFactory(checks=fixed_when_edited), trace_dir=tmp_path,
    )

    text = story(read_trace(Path(result.trace_path)))

    assert "task c999_demo" in text
    assert "Initial check: FAILED (exit 1)" in text
    assert "Step 1: model used 100 in / 20 out tokens" in text
    assert "Model says: Trying an edit." in text
    assert "-> apply_edit(" in text and "ERROR]" in text  # the failed first edit is visible
    assert "Agent changed: src/stats.py" in text
    assert "Graded in a fresh environment: PASSED (visible tests passed, no hidden tests)" in text
    assert "RESULT: PASSED  (verdict: passed, stop reason: passed)" in text


def test_trace_command_prints_utf8_even_when_piped(tmp_path: Path) -> None:
    import subprocess
    import sys

    with TraceWriter(trace_path(tmp_path, "run-1", "t001")) as trace:
        trace.event("error", step=1, error="assert 6.0 == 4.0 \u00b1 4.0e-06")

    # A pipe, with no PYTHONIOENCODING help: Windows would default to a legacy code page.
    completed = subprocess.run(
        [sys.executable, "-m", "akeso", "trace", "run-1", "t001", "--runs-dir", str(tmp_path)],
        capture_output=True, check=True,
    )

    assert "\u00b1".encode("utf-8") in completed.stdout


def test_story_shows_the_check_when_the_model_stops(task_dir: Path, tmp_path: Path) -> None:
    provider = ScriptedProvider([
        tool_reply(("apply_edit", {"path": "src/stats.py", "old_str": "(len(n) - 1)", "new_str": "len(n)"})),
        text_reply("Done."),
    ])
    result = run_agent(task_dir, settings=SETTINGS, provider=provider,
                       environment_factory=FakeFactory(checks=fixed_when_edited), trace_dir=tmp_path)

    text = story(read_trace(Path(result.trace_path)))

    assert "Check after the model stopped: PASSED" in text
    assert "RESULT: PASSED  (verdict: passed, stop reason: passed)" in text
