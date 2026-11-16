"""Tests for running many tasks under one run ID (scripted model, fake environments)."""

import json
from pathlib import Path

import pytest

from fakes import FakeFactory, ScriptedProvider, make_task, text_reply, tool_reply
from akeso import batch
from akeso.batch import read_summary, run_tasks, summarize
from akeso.config import Settings
from akeso.grading import Verdict
from akeso.tasks import TaskError

SETTINGS = Settings(provider="groq", groq_model="openai/gpt-oss-120b", anthropic_model=None, groq_api_key="fake")
BUGGY = "def mean(n):\n    return sum(n) / (len(n) - 1)\n"
FIX = ("apply_edit", {"path": "src/stats.py", "old_str": "(len(n) - 1)", "new_str": "len(n)"})


def judge(files: dict[str, str]) -> tuple[bool, str]:
    return "- 1" not in files["src/stats.py"], "1 failed" if "- 1" in files["src/stats.py"] else "1 passed"


@pytest.fixture
def tasks_root(tmp_path: Path) -> Path:
    root = tmp_path / "tasks"
    for task_id in ("t001_fixable", "t002_hopeless"):
        make_task(root / "code", {"src/stats.py": BUGGY, "tests/test_stats.py": "def test(): ...\n"}, task_id=task_id)
    return root


def run(tasks_root: Path, tmp_path: Path, responses, task_ids=("t001_fixable", "t002_hopeless"), **kwargs):
    return run_tasks(
        list(task_ids), run_id="run-1", runs_dir=tmp_path / "runs", settings=SETTINGS,
        provider=ScriptedProvider(responses), environment_factory=FakeFactory(checks=judge),
        tasks_root=tasks_root, **kwargs,
    )


def test_runs_every_task_into_one_folder(tasks_root: Path, tmp_path: Path) -> None:
    # Task 1: fix it in two steps. Task 2: give up straight away.
    summary = run(tasks_root, tmp_path, [tool_reply(FIX), tool_reply(("run_checks", {})), text_reply("I give up.")])

    assert summary.run_dir == tmp_path / "runs" / "run-1"
    assert sorted(p.name for p in summary.run_dir.iterdir()) == [
        "report.html", "summary.json", "t001_fixable.jsonl", "t002_hopeless.jsonl"]
    assert [(r.task_id, r.verdict) for r in summary.results] == [("t001_fixable", Verdict.PASSED), ("t002_hopeless", Verdict.FAILED)]
    assert all(r.run_id == "run-1" for r in summary.results)


def test_summary_file_has_results_and_totals(tasks_root: Path, tmp_path: Path) -> None:
    summary = run(tasks_root, tmp_path, [tool_reply(FIX), tool_reply(("run_checks", {})), text_reply("I give up.")])

    data = read_summary(summary.run_dir)
    assert data["run_id"] == "run-1" and data["provider"] == "groq" and data["model"] == "openai/gpt-oss-120b"
    assert [r["task_id"] for r in data["results"]] == ["t001_fixable", "t002_hopeless"]
    assert data["results"][0]["verdict"] == "passed" and data["results"][0]["split"] == "dev"
    by_split = data["totals"].pop("by_split")
    assert by_split == {"dev": data["totals"]}  # both test tasks are dev
    assert (data["totals"]["attempts"], data["totals"]["repeats"], data["repeats"]) == (2, 1, 1)
    assert {key: data["totals"][key] for key in (
        "tasks", "passed", "failed", "tampered", "pass_rate", "average_steps", "total_input_tokens",
        "total_output_tokens", "total_cost_usd", "total_rate_limit_retries", "total_pacing_waits",
        "total_pacing_wait_seconds", "total_cached_input_tokens", "provider_token_limit")} == {
        "tasks": 2, "passed": 1, "failed": 1, "tampered": 0, "pass_rate": 0.5,
        "average_steps": 1.5, "total_input_tokens": 300, "total_output_tokens": 60,
        "total_cost_usd": pytest.approx(300 * 0.15e-6 + 60 * 0.60e-6),  # Groq Developer tier rates
        "total_rate_limit_retries": 0, "total_pacing_waits": 0, "total_pacing_wait_seconds": 0.0,
        "total_cached_input_tokens": 0, "provider_token_limit": 0,
    }
    assert data["limits"]["max_steps"] == 20


def test_summary_is_written_after_each_task(tasks_root: Path, tmp_path: Path) -> None:
    seen = []

    def check_summary(result) -> None:
        seen.append(len(json.loads((tmp_path / "runs" / "run-1" / "summary.json").read_text())["results"])
                    if (tmp_path / "runs" / "run-1" / "summary.json").exists() else 0)

    run(tasks_root, tmp_path, [text_reply("no"), text_reply("no")], on_result=check_summary)

    # on_result runs before the summary is rewritten, so it sees the previous count.
    assert seen == [0, 1]
    assert len(read_summary(tmp_path / "runs" / "run-1")["results"]) == 2


def test_a_crashing_task_does_not_stop_the_run(tasks_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_run_agent = batch.run_agent

    def flaky(task_dir, **kwargs):
        if Path(task_dir).name == "t001_fixable":
            raise RuntimeError("Docker went away")
        return real_run_agent(task_dir, **kwargs)

    monkeypatch.setattr(batch, "run_agent", flaky)
    summary = run(tasks_root, tmp_path, [text_reply("I give up.")])

    first, second = summary.results
    assert first.task_id == "t001_fixable" and first.stop_reason.value == "error"
    assert "RuntimeError: Docker went away" in first.detail
    assert second.task_id == "t002_hopeless"  # the run carried on


def test_unknown_task_id_fails_before_anything_runs(tasks_root: Path, tmp_path: Path) -> None:
    with pytest.raises(TaskError, match="No task with id 'nope'"):
        run(tasks_root, tmp_path, [], task_ids=["t001_fixable", "nope"])
    assert not (tmp_path / "runs").exists()


def test_leftover_containers_are_swept_before_a_docker_run(tasks_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    swept = []
    monkeypatch.setattr(batch, "cleanup_leftover_containers", lambda: swept.append(True))
    monkeypatch.setattr(batch, "image_digest", lambda: "sha256:fake")
    monkeypatch.setattr(batch, "run_agent", lambda task_dir, **kw: batch._error_result(Path(task_dir).name, SETTINGS, "run-1", "skipped"))

    run_tasks(["t001_fixable"], run_id="run-1", runs_dir=tmp_path / "runs", settings=SETTINGS,
              provider=ScriptedProvider([]), tasks_root=tasks_root)  # default factory: Docker

    assert swept == [True]


def test_no_sweep_for_non_docker_environments(tasks_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(batch, "cleanup_leftover_containers", lambda: pytest.fail("must not sweep"))

    run(tasks_root, tmp_path, [text_reply("no")], task_ids=["t001_fixable"])


def test_summarize_empty_run() -> None:
    assert summarize([])["pass_rate"] == 0.0


def test_summary_totals_rate_limit_retries(tasks_root: Path, tmp_path: Path) -> None:
    from dataclasses import replace

    summary = run(tasks_root, tmp_path, [replace(text_reply("no"), rate_limit_retries=4), replace(text_reply("no"), rate_limit_retries=1)])

    data = read_summary(summary.run_dir)
    assert [r["rate_limit_retries"] for r in data["results"]] == [4, 1]
    assert data["totals"]["total_rate_limit_retries"] == 5


def test_provider_token_limit_counts_as_a_failure_and_separately(tasks_root: Path, tmp_path: Path) -> None:
    from dataclasses import replace as replace_result

    from akeso.agent import StopReason

    passing = batch._error_result("t001_fixable", SETTINGS, "run-1", "")
    limited = replace_result(passing, verdict=Verdict.PASSED, passed=False, stop_reason=StopReason.PROVIDER_TOKEN_LIMIT)
    solved = replace_result(passing, verdict=Verdict.PASSED, passed=True, stop_reason=StopReason.PASSED)

    totals = summarize([limited, solved])

    assert (totals["passed"], totals["failed"], totals["pass_rate"]) == (1, 1, 0.5)
    assert totals["provider_token_limit"] == 1


def test_totals_per_split(tasks_root: Path, tmp_path: Path) -> None:
    yaml = tasks_root / "code" / "t002_hopeless" / "task.yaml"
    yaml.write_text(yaml.read_text().replace("split: dev", "split: heldout"), newline="\n")

    summary = run(tasks_root, tmp_path, [tool_reply(FIX), tool_reply(("run_checks", {})), text_reply("I give up.")])

    by_split = read_summary(summary.run_dir)["totals"]["by_split"]
    assert (by_split["dev"]["tasks"], by_split["dev"]["passed"]) == (1, 1)
    assert (by_split["heldout"]["tasks"], by_split["heldout"]["passed"], by_split["heldout"]["pass_rate"]) == (1, 0, 0.0)
    assert summary.totals["by_split"] == by_split
    assert [r["split"] for r in read_summary(summary.run_dir)["results"]] == ["dev", "heldout"]


def test_summary_records_the_fingerprint_and_cost_basis(tasks_root: Path, tmp_path: Path) -> None:
    summary = run(tasks_root, tmp_path, [text_reply("no"), text_reply("no")])

    data = read_summary(summary.run_dir)
    fp = data["fingerprint"]
    assert (fp["provider"], fp["tier"], fp["model"], fp["mode"]) == ("groq", "free", "openai/gpt-oss-120b", "loop")
    assert fp["model_settings"] == {"temperature": 1.0, "reasoning_effort": "medium", "max_output_tokens": 8192}
    assert fp["limits"]["max_steps"] == 20 and fp["prompt_version"] == data["prompt_version"]
    assert fp["docker_image"] is None  # fake environments have no image
    assert len(fp["harness_commit"]) == 40 and isinstance(fp["harness_dirty"], bool)
    assert data["cost_basis"] == "estimated (not billed)"


def test_repeats_run_every_task_again_in_fresh_sandboxes(tasks_root: Path, tmp_path: Path) -> None:
    # Repeat 1: t001 fixed, t002 gives up. Repeat 2: t001 gives up, t002 gives up.
    factory = FakeFactory(checks=judge)
    responses = [tool_reply(FIX), tool_reply(("run_checks", {})), text_reply("no"), text_reply("no"), text_reply("no")]
    summary = run_tasks(
        ["t001_fixable", "t002_hopeless"], run_id="run-1", runs_dir=tmp_path / "runs", settings=SETTINGS,
        provider=ScriptedProvider(responses), environment_factory=factory, tasks_root=tasks_root, repeats=2,
    )

    assert [(r.task_id, r.repeat, r.passed) for r in summary.results] == [
        ("t001_fixable", 1, True), ("t002_hopeless", 1, False), ("t001_fixable", 2, False), ("t002_hopeless", 2, False)]
    assert len(factory.created) == 8  # an agent and a grading sandbox per attempt
    assert sorted(p.name for p in summary.run_dir.glob("*.jsonl")) == [
        "t001_fixable.jsonl", "t001_fixable.r2.jsonl", "t002_hopeless.jsonl", "t002_hopeless.r2.jsonl"]
    t = summary.totals
    assert (t["tasks"], t["attempts"], t["repeats"], t["k"]) == (2, 4, 2, 2)
    assert t["solve_rates"] == {"t001_fixable": "1/2", "t002_hopeless": "0/2"}
    assert t["pass_rates_by_repeat"] == [0.5, 0.0]
    assert t["pass_rate_mean"] == 0.25 and t["pass_rate_std"] == pytest.approx(0.35355, abs=1e-4)
    assert t["pass_at_1"] == 0.25 and t["pass_at_k"] == 0.5
    assert read_summary(summary.run_dir)["repeats"] == 2


def test_repeats_must_be_positive(tasks_root: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        run(tasks_root, tmp_path, [], repeats=0)


FINGERPRINT = {"provider": "groq", "model": "openai/gpt-oss-120b", "harness_commit": "abc", "harness_dirty": False}


class QuotaAfter(ScriptedProvider):
    """Scripted replies, then the provider's daily quota is used up."""

    def complete(self, system, messages, tools=None):
        from akeso.llm.types import QuotaExhaustedError

        if len(self.calls) >= len(self.responses):
            raise QuotaExhaustedError("Groq's quota is used up for about 7 minute(s)")
        return super().complete(system, messages, tools)


def interrupted_run(tasks_root: Path, tmp_path: Path, **kwargs):
    """t001 is fixed, then the quota runs out during t002's first attempt."""
    return run_tasks(
        ["t001_fixable", "t002_hopeless"], run_id="run-1", runs_dir=tmp_path / "runs", settings=SETTINGS,
        provider=QuotaAfter([tool_reply(FIX), tool_reply(("run_checks", {}))]),
        environment_factory=FakeFactory(checks=judge), tasks_root=tasks_root, fingerprint=FINGERPRINT, **kwargs,
    )


def test_exhausted_quota_stops_the_run_and_lists_what_was_not_run(tasks_root: Path, tmp_path: Path) -> None:
    summary = interrupted_run(tasks_root, tmp_path, repeats=2)

    assert [(r.task_id, r.repeat) for r in summary.results] == [("t001_fixable", 1)]
    assert summary.not_run == [("t002_hopeless", 1), ("t001_fixable", 2), ("t002_hopeless", 2)]
    assert summary.stopped.startswith("quota exhausted: Groq's quota is used up")
    data = read_summary(summary.run_dir)
    assert data["complete"] is False and data["stopped"] == summary.stopped
    assert data["not_run"][0] == {"task_id": "t002_hopeless", "repeat": 1}
    assert data["task_ids"] == ["t001_fixable", "t002_hopeless"]


def test_a_finished_run_is_complete(tasks_root: Path, tmp_path: Path) -> None:
    summary = run(tasks_root, tmp_path, [tool_reply(FIX), tool_reply(("run_checks", {})), text_reply("no")])

    data = read_summary(summary.run_dir)
    assert (data["complete"], data["stopped"], data["not_run"]) == (True, None, [])


def test_resume_runs_only_what_is_missing(tasks_root: Path, tmp_path: Path) -> None:
    interrupted_run(tasks_root, tmp_path)
    factory = FakeFactory(checks=judge)

    summary = batch.resume_tasks(
        "run-1", fingerprint=FINGERPRINT, runs_dir=tmp_path / "runs", settings=SETTINGS,
        provider=ScriptedProvider([text_reply("I give up.")]), environment_factory=factory, tasks_root=tasks_root,
    )

    assert [(r.task_id, r.passed) for r in summary.results] == [("t001_fixable", True), ("t002_hopeless", False)]
    assert len(factory.created) == 2  # only t002 ran again
    assert summary.not_run == [] and summary.stopped is None
    data = read_summary(summary.run_dir)
    assert data["complete"] is True and len(data["resumed"]) == 1
    assert data["totals"]["attempts"] == 2
    # The half-written trace of the abandoned attempt was replaced, not appended to.
    trace = (summary.run_dir / "t002_hopeless.jsonl").read_text(encoding="utf-8")
    assert "QuotaExhaustedError" not in trace and trace.count('"event": "run_start"') <= 1


def test_resume_reruns_crashed_attempts(tasks_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = batch.run_agent
    monkeypatch.setattr(batch, "run_agent", lambda task_dir, **kw: (_ for _ in ()).throw(RuntimeError("Docker went away")))
    run(tasks_root, tmp_path, [], fingerprint=FINGERPRINT)
    monkeypatch.setattr(batch, "run_agent", real)

    summary = batch.resume_tasks(
        "run-1", fingerprint=FINGERPRINT, runs_dir=tmp_path / "runs", settings=SETTINGS,
        provider=ScriptedProvider([text_reply("no"), text_reply("no")]),
        environment_factory=FakeFactory(checks=judge), tasks_root=tasks_root,
    )

    assert [r.stop_reason.value for r in summary.results] == ["gave_up", "gave_up"]


def test_resume_refuses_a_different_setup(tasks_root: Path, tmp_path: Path) -> None:
    interrupted_run(tasks_root, tmp_path)

    with pytest.raises(batch.ResumeError, match="harness_commit: 'abc' then, 'def' now"):
        batch.resume_tasks("run-1", fingerprint={**FINGERPRINT, "harness_commit": "def"}, runs_dir=tmp_path / "runs",
                           settings=SETTINGS, provider=ScriptedProvider([]), tasks_root=tasks_root)


def test_resume_needs_an_existing_run(tmp_path: Path) -> None:
    with pytest.raises(batch.ResumeError, match="no readable summary"):
        batch.resume_tasks("nope", fingerprint=FINGERPRINT, runs_dir=tmp_path / "runs", settings=SETTINGS)


def test_results_survive_the_round_trip_through_summary_json(tasks_root: Path, tmp_path: Path) -> None:
    summary = interrupted_run(tasks_root, tmp_path)

    saved = read_summary(summary.run_dir)["results"][0]
    assert batch.result_from_dict(saved) == summary.results[0]


ONESHOT_FIX = "<<<FILE: src/stats.py>>>\ndef mean(n):\n    return sum(n) / len(n)\n<<<END FILE>>>"


def test_oneshot_mode_runs_each_attempt_with_one_call(tasks_root: Path, tmp_path: Path) -> None:
    summary = run(tasks_root, tmp_path, [text_reply(ONESHOT_FIX), text_reply("no idea")], mode="oneshot")

    assert [(r.task_id, r.passed, r.steps, r.stop_reason.value) for r in summary.results] == [
        ("t001_fixable", True, 1, "passed"), ("t002_hopeless", False, 1, "edit_failed")]
    data = read_summary(summary.run_dir)
    assert data["mode"] == "oneshot" and data["prompt_version"] == "oneshot-v1"
    assert data["fingerprint"]["mode"] == "oneshot" and data["fingerprint"]["prompt_version"] == "oneshot-v1"


def test_resume_keeps_the_runs_mode(tasks_root: Path, tmp_path: Path) -> None:
    run_tasks(["t001_fixable"], run_id="run-1", runs_dir=tmp_path / "runs", settings=SETTINGS,
              provider=QuotaAfter([]), environment_factory=FakeFactory(checks=judge), tasks_root=tasks_root,
              fingerprint=FINGERPRINT, mode="oneshot")

    summary = batch.resume_tasks("run-1", fingerprint=FINGERPRINT, runs_dir=tmp_path / "runs", settings=SETTINGS,
                                 provider=ScriptedProvider([text_reply(ONESHOT_FIX)]),
                                 environment_factory=FakeFactory(checks=judge), tasks_root=tasks_root)

    assert summary.results[0].prompt_version == "oneshot-v1" and summary.results[0].passed


def test_an_unknown_mode_is_refused(tasks_root: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="mode must be one of"):
        run(tasks_root, tmp_path, [], mode="twoshot")


def test_failed_attempts_get_a_category_in_the_summary(tasks_root: Path, tmp_path: Path) -> None:
    summary = run(tasks_root, tmp_path, [tool_reply(FIX), tool_reply(("run_checks", {})), text_reply("I give up.")])

    data = read_summary(summary.run_dir)
    assert [r["category"] for r in data["results"]] == [None, "gave_up"]
    assert data["totals"]["failure_categories"] == {"gave_up": 1}
    assert summary.totals["failure_categories"] == {"gave_up": 1}


def test_labels_file_overrides_categories_while_running(tasks_root: Path, tmp_path: Path) -> None:
    (tmp_path / "runs" / "run-1").mkdir(parents=True)
    (tmp_path / "runs" / "run-1" / "labels.yaml").write_text("t002_hopeless: wrong_result\n", encoding="utf-8")

    summary = run(tasks_root, tmp_path, [tool_reply(FIX), tool_reply(("run_checks", {})), text_reply("I give up.")])

    assert read_summary(summary.run_dir)["results"][1]["category"] == "wrong_result"


def crash_t002(monkeypatch: pytest.MonkeyPatch) -> None:
    real_run_agent = batch.run_agent

    def flaky(task_dir, **kwargs):
        if Path(task_dir).name == "t002_hopeless":
            raise RuntimeError("Docker went away")
        return real_run_agent(task_dir, **kwargs)

    monkeypatch.setattr(batch, "run_agent", flaky)


def test_crashed_attempts_are_counted_but_not_scored(tasks_root: Path, tmp_path: Path, monkeypatch) -> None:
    crash_t002(monkeypatch)
    summary = run(tasks_root, tmp_path, [tool_reply(FIX), tool_reply(("run_checks", {}))])

    t = summary.totals
    assert (t["attempts"], t["scored_attempts"], t["crashed"], t["passed"], t["failed"]) == (2, 1, 1, 1, 0)
    assert t["pass_rate"] == 1.0 and t["pass_at_1"] == 1.0 and t["solve_rates"] == {"t001_fixable": "1/1"}
    assert summary.crashed == [("t002_hopeless", 1)]
    saved = read_summary(summary.run_dir)
    assert saved["crashed"] == [{"task_id": "t002_hopeless", "repeat": 1}]
    assert saved["totals"]["failure_categories"] == {"crashed": 1}  # still categorised
    assert saved["complete"] is True  # a dev run: crashes are reported, not blocking


def test_an_official_run_with_crashes_is_incomplete(tasks_root: Path, tmp_path: Path, monkeypatch) -> None:
    crash_t002(monkeypatch)
    summary = run(tasks_root, tmp_path, [tool_reply(FIX), tool_reply(("run_checks", {}))], run_type="official")

    assert read_summary(summary.run_dir)["complete"] is False


def test_a_repeat_where_everything_crashed_has_no_pass_rate(tasks_root: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(batch, "run_agent", lambda task_dir, **kw: (_ for _ in ()).throw(RuntimeError("down")))
    summary = run(tasks_root, tmp_path, [])

    t = summary.totals
    assert (t["scored_attempts"], t["crashed"], t["pass_rate"], t["pass_rates_by_repeat"]) == (0, 2, 0.0, [])
