"""Tests for official-run checks and the pre-run estimate."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from akeso.config import AgentLimits, ModelSettings, Settings
from akeso.freeze import FreezeCheck
from akeso.official import FALLBACK_INPUT_TOKENS, FALLBACK_OUTPUT_TOKENS, estimate, official_problems

GOOD = Settings(provider="groq", groq_model="openai/gpt-oss-120b", anthropic_model=None, groq_api_key="k", groq_tier="developer")
CLEAN = {"harness_commit": "c" * 40, "harness_dirty": False, "docker_image": "sha256:img"}
FROZEN = FreezeCheck("fp")


def problems(settings=GOOD, limits=AgentLimits(), check=FROZEN, fp=CLEAN, **kwargs):
    return official_problems(settings, limits, check, fp, **kwargs)


def test_the_measurement_setup_passes() -> None:
    assert problems() == []


@pytest.mark.parametrize(("change", "expected"), [
    ({"settings": replace(GOOD, groq_tier="free")}, "the Groq tier is 'free'"),
    ({"settings": replace(GOOD, groq_model="llama-3.3-70b-versatile")}, "the model is 'llama-3.3-70b-versatile'"),
    ({"settings": replace(GOOD, provider="anthropic", anthropic_model="claude-sonnet-5")}, "the provider is 'anthropic'"),
    ({"settings": replace(GOOD, model_settings=ModelSettings(reasoning_effort="high"))},
     "model settings reasoning_effort='high' (expected 'medium') differ"),
    ({"limits": AgentLimits(max_steps=5)}, "limits max_steps=5 (expected 20) differ"),
    ({"check": None}, "the suite isn't frozen"),
    ({"check": FreezeCheck("fp", modified=["code/x/a.py"])}, "1 task file(s) changed since the freeze"),
    ({"allow_modified": True}, "--allow-modified can't be used with --official"),
    ({"overrides": ["--model"]}, "--model can't be used with --official"),
    ({"fp": {**CLEAN, "harness_dirty": True}}, "uncommitted changes"),
    ({"fp": {**CLEAN, "harness_commit": None}}, "harness commit is unknown"),
    ({"fp": {**CLEAN, "docker_image": None}}, "Docker sandbox image isn't available"),
])
def test_each_problem_is_named(change: dict, expected: str) -> None:
    found = problems(**change)

    assert any(expected in problem for problem in found), found


def write_run(runs: Path, name: str, rows: list[tuple[str, int, int, int]]) -> None:
    (runs / name).mkdir(parents=True)
    results = [{"task_id": t, "steps": steps, "input_tokens": i, "output_tokens": o} for t, steps, i, o in rows]
    (runs / name / "summary.json").write_text(json.dumps({"results": results}))


def test_estimate_uses_the_median_of_earlier_runs(tmp_path: Path) -> None:
    write_run(tmp_path, "a", [("c001", 3, 1000, 100), ("c002", 0, 0, 0)])  # c002 never reached the model
    write_run(tmp_path, "b", [("c001", 4, 3000, 300)])
    write_run(tmp_path, "c", [("c001", 5, 2000, 200)])

    guess = estimate(["c001", "c002"], "openai/gpt-oss-120b", tmp_path, repeats=3)

    assert guess.tasks_with_history == 1 and guess.tasks == 2
    assert guess.input_tokens == 3 * (2000 + FALLBACK_INPUT_TOKENS)
    assert guess.output_tokens == 3 * (200 + FALLBACK_OUTPUT_TOKENS)
    assert guess.cost_usd == pytest.approx((guess.input_tokens * 0.15 + guess.output_tokens * 0.60) / 1e6)
