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
    assert sorted(p.name for p in summary.run_dir.iterdir()) == ["summary.json", "t001_fixable.jsonl", "t002_hopeless.jsonl"]
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
    assert data["totals"] == {
        "tasks": 2, "passed": 1, "failed": 1, "tampered": 0, "pass_rate": 0.5,
        "average_steps": 1.5, "total_input_tokens": 300, "total_output_tokens": 60,
        "total_cost_usd": pytest.approx(300 * 0.15e-6 + 60 * 0.60e-6),  # Groq Developer tier rates
        "total_rate_limit_retries": 0, "provider_token_limit": 0,
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
