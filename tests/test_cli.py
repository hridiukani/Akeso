"""Tests for the akeso command-line tool (run_tasks and Docker replaced by fakes)."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from akeso import cli
from akeso.agent import AgentResult, StopReason
from akeso.batch import RunSummary, summarize
from akeso.config import Settings
from akeso.grading import Verdict
from akeso.suites import SuiteError, load_suite
from akeso.trace import TraceWriter, trace_path
from akeso.validate import TaskValidation

runner = CliRunner()
SETTINGS = Settings(provider="groq", groq_model="openai/gpt-oss-120b", anthropic_model=None, groq_api_key="fake")


def result(task_id: str, verdict: Verdict, steps: int, tokens: int, stop: StopReason) -> AgentResult:
    return AgentResult(
        task_id=task_id, passed=verdict is Verdict.PASSED, verdict=verdict, stop_reason=stop,
        steps=steps, input_tokens=tokens, output_tokens=100, cost_usd=0.0,
        provider="groq", model="openai/gpt-oss-120b", environment="docker", prompt_version="agent-v3",
    )


def fixed_suite(name: str) -> list[str]:
    """A stand-in suite, so these tests don't depend on what the real suites contain."""
    if name != "smoke":
        return load_suite(name)  # real lookup, for the unknown-suite error
    return ["c001_mean", "c002_shipping", "c003_discount"]


@pytest.fixture
def fake_run(monkeypatch: pytest.MonkeyPatch):
    calls = {}

    def fake_run_tasks(task_ids, **kwargs):
        calls.update(task_ids=task_ids, **kwargs)
        results = [
            result("c001_mean", Verdict.PASSED, 3, 4500, StopReason.PASSED),
            result("c002_shipping", Verdict.FAILED, 20, 30000, StopReason.MAX_STEPS),
            result("c003_discount", Verdict.TAMPERED, 4, 6000, StopReason.PASSED),
        ]
        return RunSummary(run_id="run-xyz", run_dir=Path("runs/run-xyz"), results=results, totals=summarize(results))

    monkeypatch.setattr(cli, "run_tasks", fake_run_tasks)
    monkeypatch.setattr(cli, "load_settings", lambda: SETTINGS)
    monkeypatch.setattr(cli, "load_suite", fixed_suite)
    return calls


def test_run_prints_table_and_totals(fake_run) -> None:
    out = runner.invoke(cli.app, ["run", "--suite", "smoke"])

    assert out.exit_code == 0, out.output
    assert fake_run["task_ids"] == ["c001_mean", "c002_shipping", "c003_discount"]
    for text in ("c001_mean", "passed", "c002_shipping", "failed", "max_steps", "tampered", "4,600", "30,100"):
        assert text in out.output
    assert "Passed 1/3 (33%), tampered 1" in out.output
    assert "average steps 9.0" in out.output and "total tokens 40,800" in out.output
    assert "rate-limit retries 0" in out.output
    assert "Run folder: runs" in out.output and "run-xyz" in out.output


def test_run_options_reach_the_runner(fake_run) -> None:
    out = runner.invoke(cli.app, ["run", "--suite", "smoke", "--max-steps", "5", "--max-cost", "0.25",
                                  "--run-id", "my-run", "--model", "llama-3.3-70b-versatile"])

    assert out.exit_code == 0, out.output
    assert fake_run["run_id"] == "my-run"
    assert (fake_run["limits"].max_steps, fake_run["limits"].max_cost_usd) == (5, 0.25)
    assert fake_run["settings"].model == "llama-3.3-70b-versatile"


def test_run_rejects_a_model_without_a_price(fake_run) -> None:
    out = runner.invoke(cli.app, ["run", "--suite", "smoke", "--model", "gpt-9"])

    assert out.exit_code == 1
    assert "has no entry in PRICES" in out.output


def test_run_with_an_unknown_suite(fake_run) -> None:
    out = runner.invoke(cli.app, ["run", "--suite", "nope"])

    assert out.exit_code == 1
    assert "No suite named 'nope'" in out.output and "smoke" in out.output


def test_validate_prints_the_report(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "load_suite", fixed_suite)
    monkeypatch.setattr(cli, "validate_task", lambda task: TaskValidation(task.id, True, True, True))

    out = runner.invoke(cli.app, ["validate", "--suite", "smoke"])

    assert out.exit_code == 0, out.output
    assert "OK    c001_mean" in out.output and "3/3 tasks valid" in out.output


def test_validate_fails_when_a_task_is_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "validate_task", lambda task: TaskValidation(task.id, False, True, True, ["broken passes"]))

    out = runner.invoke(cli.app, ["validate", "--suite", "smoke"])

    assert out.exit_code == 1
    assert "- broken passes" in out.output


def test_trace_shows_the_story(tmp_path: Path) -> None:
    with TraceWriter(trace_path(tmp_path, "run-1", "c001_mean")) as trace:
        trace.event("error", step=2, error="the model ran out of ideas")

    out = runner.invoke(cli.app, ["trace", "run-1", "c001_mean", "--runs-dir", str(tmp_path)])

    assert out.exit_code == 0
    assert "Error at step 2: the model ran out of ideas" in out.output


def test_trace_for_a_missing_run(tmp_path: Path) -> None:
    out = runner.invoke(cli.app, ["trace", "nope", "c001_mean", "--runs-dir", str(tmp_path)])

    assert out.exit_code == 1 and "no trace at" in out.output


@pytest.mark.parametrize(("args", "expected_max_age"), [(["cleanup"], cli.LEFTOVER_MAX_AGE), (["cleanup", "--all"], None)])
def test_cleanup(monkeypatch: pytest.MonkeyPatch, args: list[str], expected_max_age) -> None:
    seen = {}

    def fake_cleanup(max_age):
        seen["max_age"] = max_age
        return ["abc123"]

    monkeypatch.setattr(cli, "cleanup_leftover_containers", fake_cleanup)

    out = runner.invoke(cli.app, args)

    assert out.exit_code == 0 and seen["max_age"] == expected_max_age
    assert "Removed 1 container(s)" in out.output


# --- suites ---


def test_smoke_suite() -> None:
    assert load_suite("smoke")[:3] == ["c001_mean", "c002_shipping", "c003_discount"]


@pytest.mark.parametrize(
    ("content", "message"),
    [("c001_mean\n", "must be a non-empty YAML list"), ("[]\n", "must be a non-empty YAML list"),
     ("- a\n- a\n", "listed more than once: a"), ("- [unclosed\n", "not valid YAML")],
)
def test_bad_suite_files(tmp_path: Path, content: str, message: str) -> None:
    (tmp_path / "bad.yaml").write_text(content)

    with pytest.raises(SuiteError, match=message.replace("[", r"\[")):
        load_suite("bad", suites_dir=tmp_path)
