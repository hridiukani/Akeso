"""Tests for the akeso command-line tool (run_tasks and Docker replaced by fakes)."""

import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from akeso import cli
from akeso.agent import AgentResult, StopReason
from akeso.batch import RunSummary, summarize
from akeso.freeze import FreezeCheck, read_manifest
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
        splits = {"c001_mean": "dev", "c002_shipping": "dev", "c003_discount": "heldout"}
        return RunSummary(run_id="run-xyz", run_dir=Path("runs/run-xyz"), results=results, totals=summarize(results, splits))

    monkeypatch.setattr(cli, "run_tasks", fake_run_tasks)
    monkeypatch.setattr(cli, "load_settings", lambda: SETTINGS)
    monkeypatch.setattr(cli, "read_manifest", lambda: {})
    monkeypatch.setattr(cli, "image_digest", lambda: "sha256:image")
    monkeypatch.setattr(cli.run_fingerprint, "collect", lambda settings, limits, mode="loop", docker_image=None: dict(
        calls.get("fingerprint", {"harness_commit": "c" * 40, "harness_dirty": False}), docker_image=docker_image,
        mode=mode))
    monkeypatch.setattr(cli, "check_tasks", lambda tasks, manifest: calls.get("freeze_check", FreezeCheck("fp-123")))
    monkeypatch.setattr(cli, "load_suite", fixed_suite)
    return calls


def test_run_prints_table_and_totals(fake_run) -> None:
    out = runner.invoke(cli.app, ["run", "--suite", "smoke"])

    assert out.exit_code == 0, out.output
    assert fake_run["task_ids"] == ["c001_mean", "c002_shipping", "c003_discount"]
    for text in ("c001_mean", "passed", "c002_shipping", "failed", "max_steps", "tampered", "4,600", "30,100"):
        assert text in out.output
    assert "Passed 1/3 attempts (33%), tampered 1" in out.output
    assert "average steps 9.0" in out.output and "total tokens 40,800" in out.output
    assert "rate-limit retries 0" in out.output
    assert "dev: passed 1/2 (50%)" in out.output and "heldout: passed 0/1 (0%)" in out.output
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


def test_run_records_a_clean_freeze_check(fake_run) -> None:
    out = runner.invoke(cli.app, ["run", "--suite", "smoke"])

    assert out.exit_code == 0, out.output
    assert fake_run["freeze"] == {"manifest_fingerprint": "fp-123", "allow_modified": False, "modified_files": []}


def test_run_refuses_modified_tasks(fake_run) -> None:
    fake_run["freeze_check"] = FreezeCheck("fp-123", modified=["code/c001_mean/src/stats.py"])

    out = runner.invoke(cli.app, ["run", "--suite", "smoke"])

    assert out.exit_code == 1
    assert "1 task file(s) changed since the freeze" in out.output and "code/c001_mean/src/stats.py" in out.output
    assert "--allow-modified" in out.output
    assert "task_ids" not in fake_run  # nothing ran


def test_allow_modified_runs_and_is_recorded(fake_run) -> None:
    fake_run["freeze_check"] = FreezeCheck("fp-123", modified=["code/c001_mean/src/stats.py"])

    out = runner.invoke(cli.app, ["run", "--suite", "smoke", "--allow-modified"])

    assert out.exit_code == 0, out.output
    assert "running with 1 task file(s) changed since the freeze" in out.output
    assert fake_run["freeze"] == {"manifest_fingerprint": "fp-123", "allow_modified": True,
                                  "modified_files": ["code/c001_mean/src/stats.py"]}


def test_run_without_a_manifest_is_a_clear_error(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(cli, "load_suite", fixed_suite)
    monkeypatch.setattr(cli, "read_manifest", lambda: read_manifest(tmp_path / "manifest.json"))
    monkeypatch.setattr(cli, "load_settings", lambda: SETTINGS)
    monkeypatch.setattr(cli, "image_digest", lambda: "sha256:image")

    out = runner.invoke(cli.app, ["run", "--suite", "smoke"])

    assert out.exit_code == 1 and "No freeze manifest" in out.output


DEVELOPER = replace(SETTINGS, groq_tier="developer")


def test_official_run_refuses_the_free_tier_and_says_why(fake_run) -> None:
    fake_run["fingerprint"] = {"harness_commit": "c" * 40, "harness_dirty": True}

    out = runner.invoke(cli.app, ["run", "--suite", "smoke", "--official", "--max-steps", "5"])

    assert out.exit_code == 1 and "this can't be an official run" in out.output
    assert "the Groq tier is 'free'; official runs need the 'developer' tier" in out.output
    assert "--max-steps can't be used with --official" in out.output
    assert "uncommitted changes" in out.output
    assert "task_ids" not in fake_run  # nothing ran


def test_official_run_shows_an_estimate_and_can_be_cancelled(fake_run, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "load_settings", lambda: DEVELOPER)

    out = runner.invoke(cli.app, ["run", "--suite", "smoke", "--official"], input="n\n")

    assert out.exit_code == 1
    assert "Official loop run of smoke: 3 task(s) x 3 repeat(s) on groq (developer tier) / openai/gpt-oss-120b." in out.output
    assert "Estimated: about" in out.output and "at list prices" in out.output
    assert "Cancelled; nothing was run." in out.output and "task_ids" not in fake_run


def test_confirmed_official_run_is_labelled_official(fake_run, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "load_settings", lambda: DEVELOPER)

    out = runner.invoke(cli.app, ["run", "--suite", "smoke", "--official"], input="y\n")

    assert out.exit_code == 0, out.output
    assert fake_run["run_type"] == "official" and "(official run)" in out.output


def test_yes_skips_the_confirmation(fake_run, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "load_settings", lambda: DEVELOPER)

    out = runner.invoke(cli.app, ["run", "--suite", "smoke", "--official", "--yes"])

    assert out.exit_code == 0 and "Start the official run?" not in out.output and fake_run["run_type"] == "official"


def test_ordinary_runs_are_labelled_dev(fake_run) -> None:
    out = runner.invoke(cli.app, ["run", "--suite", "smoke"])

    assert out.exit_code == 0 and fake_run["run_type"] == "dev" and "(dev run)" in out.output


def test_repeats_show_solve_rates_and_spread(fake_run, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_tasks(task_ids, **kwargs):
        fake_run.update(task_ids=task_ids, **kwargs)
        results = [replace(result("c001_mean", Verdict.PASSED if rep < 3 else Verdict.FAILED, 3, 4000, StopReason.PASSED), repeat=rep)
                   for rep in (1, 2, 3)]
        return RunSummary(run_id="run-r", run_dir=Path("runs/run-r"), results=results,
                          totals=summarize(results, {"c001_mean": "dev"}))

    monkeypatch.setattr(cli, "run_tasks", fake_run_tasks)

    out = runner.invoke(cli.app, ["run", "--suite", "smoke", "--repeats", "3"])

    assert out.exit_code == 0, out.output
    assert fake_run["repeats"] == 3
    assert "2/3" in out.output and "Solved" in out.output
    assert "pass rate 67% +/- 58% over 3 repeats | pass@1 67% | pass@3 100%" in out.output


def test_official_runs_default_to_three_repeats(fake_run, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "load_settings", lambda: DEVELOPER)

    out = runner.invoke(cli.app, ["run", "--suite", "smoke", "--official", "--yes"])

    assert out.exit_code == 0 and fake_run["repeats"] == 3


def test_trace_shows_a_later_repeat(tmp_path: Path) -> None:
    with TraceWriter(trace_path(tmp_path, "run-1", "c001_mean", 2)) as trace:
        trace.event("error", step=1, error="second attempt")

    out = runner.invoke(cli.app, ["trace", "run-1", "c001_mean", "--repeat", "2", "--runs-dir", str(tmp_path)])

    assert out.exit_code == 0 and "second attempt" in out.output


FP = {"harness_commit": "c" * 40, "harness_dirty": False, "docker_image": "sha256:image", "mode": "loop"}


@pytest.fixture
def saved_run(fake_run, monkeypatch: pytest.MonkeyPatch):
    """A dev run of two tasks x 2 repeats that stopped after its first attempt."""
    done = result("c001_mean", Verdict.PASSED, 3, 4500, StopReason.PASSED)
    saved = {"run_id": "run-old", "run_type": "dev", "repeats": 2, "task_ids": ["c001_mean", "c002_shipping"],
             "fingerprint": dict(FP), "freeze": {"allow_modified": False},
             "results": [{**asdict(done), "verdict": "passed", "stop_reason": "passed"}]}
    monkeypatch.setattr(cli, "load_for_resume", lambda run_id, runs_dir: saved)

    def fake_resume_tasks(run_id, **kwargs):
        fake_run.update(resumed=run_id, **kwargs)
        return RunSummary(run_id=run_id, run_dir=Path("runs") / run_id, results=[done], totals=summarize([done]))

    monkeypatch.setattr(cli, "resume_tasks", fake_resume_tasks)
    return saved


def test_resume_runs_what_is_left(fake_run, saved_run) -> None:
    out = runner.invoke(cli.app, ["run", "--resume", "run-old"])

    assert out.exit_code == 0, out.output
    assert fake_run["resumed"] == "run-old"
    assert "Resuming run run-old (dev run): 1 attempt(s) kept, 3 to run" in out.output


def test_resume_refuses_a_changed_setup(fake_run, saved_run) -> None:
    fake_run["fingerprint"] = {**FP, "harness_commit": "d" * 40}

    out = runner.invoke(cli.app, ["run", "--resume", "run-old"])

    assert out.exit_code == 1 and "can't be resumed" in out.output and "harness_commit" in out.output
    assert "resumed" not in fake_run


def test_resume_keeps_the_original_options(fake_run, saved_run) -> None:
    out = runner.invoke(cli.app, ["run", "--resume", "run-old", "--max-steps", "3", "--suite", "smoke"])

    assert out.exit_code == 1 and "--suite, --max-steps can't be used with --resume" in out.output


def test_resume_of_a_complete_run_does_nothing(fake_run, saved_run) -> None:
    saved_run["repeats"], saved_run["task_ids"] = 1, ["c001_mean"]

    out = runner.invoke(cli.app, ["run", "--resume", "run-old"])

    assert out.exit_code == 0 and "already complete" in out.output and "resumed" not in fake_run


def test_resuming_an_official_run_rechecks_the_measurement_setup(fake_run, saved_run) -> None:
    saved_run["run_type"] = "official"

    out = runner.invoke(cli.app, ["run", "--resume", "run-old"])  # SETTINGS is the free tier

    assert out.exit_code == 1 and "this can't be an official run" in out.output and "resumed" not in fake_run


def test_run_needs_a_suite_or_resume(fake_run) -> None:
    out = runner.invoke(cli.app, ["run"])

    assert out.exit_code == 1 and "Pass --suite NAME (or --resume RUN_ID)" in out.output


def test_a_run_stopped_by_the_quota_says_how_to_finish_it(fake_run, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_tasks(task_ids, **kwargs):
        done = [result("c001_mean", Verdict.PASSED, 3, 4500, StopReason.PASSED)]
        return RunSummary(run_id="run-q", run_dir=Path("runs/run-q"), results=done, totals=summarize(done),
                          not_run=[("c002_shipping", 1), ("c003_discount", 1)], stopped="quota exhausted: used up")

    monkeypatch.setattr(cli, "run_tasks", fake_run_tasks)

    out = runner.invoke(cli.app, ["run", "--suite", "smoke"])

    assert out.exit_code == 0
    assert "Stopped early (quota exhausted: used up). 2 attempt(s) not run" in out.output
    assert "akeso run --resume run-q" in out.output


def test_mode_reaches_the_runner_and_the_fingerprint(fake_run) -> None:
    out = runner.invoke(cli.app, ["run", "--suite", "smoke", "--mode", "oneshot"])

    assert out.exit_code == 0, out.output
    assert fake_run["mode"] == "oneshot" and fake_run["fingerprint"]["mode"] == "oneshot"
    assert "oneshot mode" in out.output


def test_loop_is_the_default_mode(fake_run) -> None:
    out = runner.invoke(cli.app, ["run", "--suite", "smoke"])

    assert out.exit_code == 0 and fake_run["mode"] == "loop"


def test_an_unknown_mode_is_refused(fake_run) -> None:
    out = runner.invoke(cli.app, ["run", "--suite", "smoke", "--mode", "twoshot"])

    assert out.exit_code == 1 and "--mode must be one of: loop, oneshot" in out.output and "task_ids" not in fake_run


def test_resume_uses_the_saved_mode(fake_run, saved_run) -> None:
    saved_run["mode"] = "oneshot"
    saved_run["fingerprint"]["mode"] = "oneshot"

    out = runner.invoke(cli.app, ["run", "--resume", "run-old"])

    assert out.exit_code == 0, out.output
    assert fake_run["resumed"] == "run-old" and fake_run["fingerprint"]["mode"] == "oneshot"


def write_run(runs: Path, run_id: str, passes: list[bool], **fingerprint) -> None:
    results = [replace(result("c001_mean", Verdict.PASSED if ok else Verdict.FAILED, 3, 1000,
                              StopReason.PASSED if ok else StopReason.GAVE_UP), repeat=rep)
               for rep, ok in enumerate(passes, start=1)]
    data = {"run_id": run_id, "run_type": "dev", "complete": True,
            "fingerprint": {"suite_freeze_fingerprint": "fp", "model": "openai/gpt-oss-120b", **fingerprint},
            "totals": summarize(results, {"c001_mean": "dev"}),
            "results": [{**asdict(r), "split": "dev"} for r in results]}
    (runs / run_id).mkdir(parents=True)
    (runs / run_id / "summary.json").write_text(json.dumps(data, default=str), encoding="utf-8")


def test_compare_prints_the_difference_and_changed_tasks(tmp_path: Path) -> None:
    write_run(tmp_path, "a", [False, False])
    write_run(tmp_path, "b", [True, False], model="llama")

    out = runner.invoke(cli.app, ["compare", "a", "b", "--runs-dir", str(tmp_path)], env={"COLUMNS": "200"})

    assert out.exit_code == 0, out.output
    assert "1,100 -> 1,100" in out.output
    assert "model differs" in out.output and "a is a dev run" in out.output
    assert "0% +/- 0% (x2)" in out.output and "50% +/- 71% (x2)" in out.output and "+50%" in out.output
    assert "Tasks whose solve rate changed" in out.output and "0/2" in out.output and "1/2" in out.output


def test_compare_refuses_different_suites(tmp_path: Path) -> None:
    write_run(tmp_path, "a", [True])
    write_run(tmp_path, "b", [True], suite_freeze_fingerprint="other")

    out = runner.invoke(cli.app, ["compare", "a", "b", "--runs-dir", str(tmp_path)])

    assert out.exit_code == 1 and "different suites" in out.output


def test_run_prints_the_failure_categories(fake_run, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_tasks(task_ids, **kwargs):
        results = [result("c001_mean", Verdict.FAILED, 20, 1000, StopReason.MAX_STEPS)]
        totals = summarize(results, {"c001_mean": "dev"})
        totals["failure_categories"] = {"max_steps": 1}
        totals["by_split"]["dev"]["failure_categories"] = {"max_steps": 1}
        return RunSummary(run_id="run-c", run_dir=Path("runs/run-c"), results=results, totals=totals)

    monkeypatch.setattr(cli, "run_tasks", fake_run_tasks)

    out = runner.invoke(cli.app, ["run", "--suite", "smoke"])

    assert out.exit_code == 0 and "Failure categories (failed attempts):" in out.output and "max_steps" in out.output
