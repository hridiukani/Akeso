"""Tests for comparing two runs (summaries built in memory, no models or Docker)."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from akeso.agent import AgentResult, StopReason
from akeso.batch import summarize
from akeso.compare import CompareError, bootstrap_difference, compare_runs, compare_summaries
from akeso.grading import Verdict

SPLITS = {"c001": "dev", "c002": "dev", "s001": "heldout", "s002": "heldout"}
FP = {"provider": "groq", "model": "openai/gpt-oss-120b", "mode": "loop", "suite_freeze_fingerprint": "fp"}


def summary(run_id: str, outcomes: dict[str, list[bool]], **fingerprint) -> dict:
    """A summary.json-shaped dict: outcomes maps task -> pass/fail per repeat."""
    results = [
        AgentResult(task_id=task, passed=ok, verdict=Verdict.PASSED if ok else Verdict.FAILED,
                    stop_reason=StopReason.PASSED if ok else StopReason.MAX_STEPS, steps=4 if ok else 20,
                    input_tokens=1000, output_tokens=100, cost_usd=0.001, provider="groq",
                    model="openai/gpt-oss-120b", environment="docker", prompt_version="agent-v4", repeat=rep)
        for task, passes in outcomes.items() for rep, ok in enumerate(passes, start=1)
    ]
    splits = {t: SPLITS[t] for t in outcomes}
    return {"run_id": run_id, "run_type": "official", "complete": True, "fingerprint": {**FP, **fingerprint},
            "totals": summarize(results, splits),
            "results": [{**asdict(r), "split": splits[r.task_id]} for r in results]}


A = {"c001": [True, True], "c002": [False, False], "s001": [True, False], "s002": [False, False]}
B = {"c001": [True, True], "c002": [True, True], "s001": [True, True], "s002": [False, False]}


def test_difference_and_interval_overall_and_per_split() -> None:
    result = compare_summaries(summary("a", A), summary("b", B))

    overall, dev, heldout = result.groups
    assert (overall.name, dev.name, heldout.name) == ("overall", "dev", "heldout")
    assert overall.difference == pytest.approx((0 + 1 + 0.5 + 0) / 4)
    assert overall.ci_low <= overall.difference <= overall.ci_high
    assert overall.ci_low >= 0  # no task got worse, so no resample can show a drop
    assert dev.difference == 0.5 and heldout.difference == 0.25
    assert overall.a["pass_rate_mean"] == pytest.approx(0.375) and overall.b["pass_rate_mean"] == pytest.approx(0.75)
    assert result.warnings == []


def test_tasks_whose_solve_rate_changed() -> None:
    result = compare_summaries(summary("a", A), summary("b", B))

    assert [(c.task_id, c.split, c.a, c.b) for c in result.changed] == [
        ("c002", "dev", "0/2", "2/2"), ("s001", "heldout", "1/2", "2/2")]


def test_a_different_suite_is_refused() -> None:
    with pytest.raises(CompareError, match="different suites"):
        compare_summaries(summary("a", A), summary("b", B, suite_freeze_fingerprint="other"))


def test_a_different_model_or_mode_is_a_warning() -> None:
    result = compare_summaries(summary("a", A), summary("b", B, model="llama", mode="oneshot"))

    assert "model differs: 'openai/gpt-oss-120b' in a, 'llama' in b" in result.warnings
    assert "mode differs: 'loop' in a, 'oneshot' in b" in result.warnings


def test_dev_and_incomplete_runs_are_flagged() -> None:
    b = summary("b", B)
    b.update(run_type="dev", complete=False, not_run=[{"task_id": "c001", "repeat": 3}])

    warnings = compare_summaries(summary("a", A), b).warnings

    assert "b is a dev run, not an official one" in warnings
    assert "b is incomplete (1 attempt(s) not run)" in warnings


def test_tasks_in_only_one_run_are_left_out() -> None:
    result = compare_summaries(summary("a", A), summary("b", {k: v for k, v in B.items() if k != "s002"}))

    assert result.groups[0].tasks == 3
    assert any("only one run" in w and "s002" in w for w in result.warnings)


def test_bootstrap_is_reproducible_and_brackets_the_observed_difference() -> None:
    pairs = [(0.0, 1.0), (1.0, 1.0), (0.5, 0.0), (0.0, 0.0), (0.0, 1.0)]

    first, second = bootstrap_difference(pairs), bootstrap_difference(pairs)

    assert first == second
    observed, low, high = first
    assert observed == pytest.approx(0.3) and low < observed < high
    assert bootstrap_difference([]) == (0.0, 0.0, 0.0)


def test_identical_runs_have_a_zero_interval() -> None:
    _, low, high = bootstrap_difference([(0.5, 0.5)] * 6)

    assert low == high == 0.0


def test_compare_runs_reads_the_run_folders(tmp_path: Path) -> None:
    for run_id, outcomes in (("a", A), ("b", B)):
        (tmp_path / run_id).mkdir()
        (tmp_path / run_id / "summary.json").write_text(json.dumps(summary(run_id, outcomes), default=str))

    assert compare_runs("a", "b", tmp_path).groups[0].difference == pytest.approx(0.375)
    with pytest.raises(CompareError, match="no readable summary"):
        compare_runs("a", "missing", tmp_path)


# Known differences: a suite of 20 tasks run 3 times, where we decide exactly which tasks
# each run solves, so the true change in solve rate is known before comparing.
TASKS = [f"t{i:02}" for i in range(20)]


def suite_run(run_id: str, solved: dict[str, int], repeats: int = 3) -> dict:
    """solved maps task -> how many of its repeats pass (unlisted tasks: none)."""
    results = [
        AgentResult(task_id=task, passed=ok, verdict=Verdict.PASSED if ok else Verdict.FAILED,
                    stop_reason=StopReason.PASSED if ok else StopReason.GAVE_UP, steps=5, input_tokens=1000,
                    output_tokens=100, cost_usd=0.001, provider="groq", model="openai/gpt-oss-120b",
                    environment="docker", prompt_version="agent-v4", repeat=rep)
        for task in TASKS for rep in range(1, repeats + 1) for ok in [rep <= solved.get(task, 0)]
    ]
    splits = {task: "dev" for task in TASKS}
    return {"run_id": run_id, "run_type": "official", "complete": True, "fingerprint": dict(FP),
            "totals": summarize(results, splits),
            "results": [{**asdict(r), "split": "dev"} for r in results]}


def test_a_large_improvement_is_detected_with_an_interval_clear_of_zero() -> None:
    a = suite_run("a", {t: 3 for t in TASKS[:5]})  # 5 of 20 tasks solved: 25%
    b = suite_run("b", {t: 3 for t in TASKS[:15]})  # 15 of 20: 75%

    overall = compare_summaries(a, b).groups[0]

    assert overall.difference == pytest.approx(0.5)
    assert 0 < overall.ci_low < 0.5 < overall.ci_high <= 1
    assert overall.a["pass_rate_mean"] == pytest.approx(0.25) and overall.b["pass_rate_mean"] == pytest.approx(0.75)
    assert len(compare_summaries(a, b).changed) == 10


def test_a_regression_is_detected_as_negative() -> None:
    a = suite_run("a", {t: 3 for t in TASKS[:16]})  # 80%
    b = suite_run("b", {t: 3 for t in TASKS[:8]})  # 40%

    overall = compare_summaries(a, b).groups[0]

    assert overall.difference == pytest.approx(-0.4)
    assert overall.ci_low < -0.4 < overall.ci_high < 0


def test_partial_solve_rates_give_the_exact_difference() -> None:
    a = suite_run("a", {t: 1 for t in TASKS[:10]})  # 10 tasks at 1/3
    b = suite_run("b", {t: 2 for t in TASKS[:10]})  # the same 10 at 2/3

    overall = compare_summaries(a, b).groups[0]

    assert overall.difference == pytest.approx(10 * (1 / 3) / 20)  # +1/6
    assert overall.ci_low > 0  # every changed task moved up, so no resample shows a drop
    assert overall.b["pass_at_k"] == overall.a["pass_at_k"] == pytest.approx(0.5)  # pass@3 sees no change


def test_one_changed_task_is_not_called_a_real_difference() -> None:
    a = suite_run("a", {t: 3 for t in TASKS[:10]})
    b = suite_run("b", {t: 3 for t in TASKS[:11]})  # one more task solved

    overall = compare_summaries(a, b).groups[0]

    assert overall.difference == pytest.approx(0.05)
    assert overall.ci_low <= 0 < overall.ci_high  # could be luck: the interval reaches zero


def test_gains_and_losses_that_cancel_out_give_an_interval_around_zero() -> None:
    a = suite_run("a", {t: 3 for t in TASKS[:10]})
    b = suite_run("b", {t: 3 for t in TASKS[5:15]})  # 5 tasks lost, 5 gained

    overall = compare_summaries(a, b).groups[0]

    assert overall.difference == 0
    assert overall.ci_low < 0 < overall.ci_high
