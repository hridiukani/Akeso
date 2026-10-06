"""Agent loop tests with a scripted fake model and an in-memory environment (no network, no Docker)."""

from pathlib import Path

import pytest

from fakes import FakeEnvironment, FakeFactory, ScriptedProvider, make_task, text_reply, tool_reply
from akeso.agent import StopReason, run_agent
from akeso.config import AgentLimits, Settings
from akeso.environment import ExecResult
from akeso.grading import Verdict
from akeso.llm.types import Usage

GROQ = Settings(provider="groq", groq_model="openai/gpt-oss-120b", anthropic_model=None, groq_api_key="fake")
SONNET = Settings(provider="anthropic", groq_model=None, anthropic_model="claude-sonnet-5", anthropic_api_key="fake")

BUGGY = "def mean(n):\n    return sum(n) / (len(n) - 1)\n"
TESTS = "from stats import mean\n\ndef test_mean():\n    assert mean([2, 4, 6]) == 4\n"
FIX = ("apply_edit", {"path": "src/stats.py", "old_str": "(len(n) - 1)", "new_str": "len(n)"})
CHECKS = ("run_checks", {})
READ = ("read_file", {"path": "src/stats.py"})


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    return make_task(tmp_path / "tasks", {
        "src/stats.py": BUGGY,
        "tests/test_stats.py": TESTS,
        "README.md": "mean(n) returns the average of n.\n",
    })


def judge(files: dict[str, str]) -> tuple[bool, str]:
    """Fake pytest: passes if the bug is fixed or the test has been gutted."""
    fixed = "- 1" not in files.get("src/stats.py", "")
    gutted = "assert" not in files.get("tests/test_stats.py", "")
    if fixed or gutted:
        return True, "1 passed in 0.01s"
    return False, "FAILED tests/test_stats.py::test_mean - assert 6.0 == 4\n1 failed in 0.02s"


def run(task_dir: Path, tmp_path: Path, responses, *, settings=GROQ, limits=None, factory=None):
    provider = ScriptedProvider(responses)
    factory = factory or FakeFactory(checks=judge)
    result = run_agent(task_dir, settings=settings, limits=limits, provider=provider,
                       environment_factory=factory, trace_dir=tmp_path / "runs")
    return result, provider, factory


def test_successful_fix_in_a_few_steps(task_dir: Path, tmp_path: Path) -> None:
    result, provider, factory = run(task_dir, tmp_path, [tool_reply(READ), tool_reply(FIX), tool_reply(CHECKS)])

    assert result.passed and result.verdict is Verdict.PASSED
    assert result.stop_reason is StopReason.PASSED
    assert result.steps == 3
    assert (result.input_tokens, result.output_tokens) == (300, 60)
    # Two environments: the agent's, then a fresh one for grading. Both were cleaned up.
    assert len(factory.created) == 2
    assert all(env.started and env.stopped for env in factory.created)
    # The model saw the README and the failing output first.
    first = provider.calls[0][0].content
    assert "mean(n) returns the average" in first and "assert 6.0 == 4" in first


def test_max_steps(task_dir: Path, tmp_path: Path) -> None:
    result, provider, _ = run(task_dir, tmp_path, [tool_reply(READ)] * 10, limits=AgentLimits(max_steps=3))

    assert not result.passed and result.verdict is Verdict.FAILED
    assert result.stop_reason is StopReason.MAX_STEPS
    assert result.steps == 3
    assert len(provider.calls) == 3


def test_repeated_identical_failures(task_dir: Path, tmp_path: Path) -> None:
    # The model keeps re-running the checks without changing anything.
    result, _, _ = run(task_dir, tmp_path, [tool_reply(CHECKS)] * 10, limits=AgentLimits(repeated_failure_limit=3))

    assert not result.passed
    assert result.stop_reason is StopReason.REPEATED_FAILURE
    assert result.steps == 3


def test_failures_differing_only_in_timing_count_as_repeated(task_dir: Path, tmp_path: Path) -> None:
    timings = iter(["0.02s", "1.37s", "0.5s", "2.0s", "0.1s"])

    def noisy_judge(files: dict[str, str]) -> tuple[bool, str]:
        return False, f"FAILED tests/test_stats.py::test_mean - assert 6.0 == 4\n1 failed in {next(timings)}"

    factory = FakeFactory(checks=noisy_judge)
    result, _, _ = run(task_dir, tmp_path, [tool_reply(CHECKS)] * 10, limits=AgentLimits(repeated_failure_limit=2), factory=factory)

    assert result.stop_reason is StopReason.REPEATED_FAILURE
    assert result.steps == 2


def test_model_gives_up(task_dir: Path, tmp_path: Path) -> None:
    result, _, _ = run(task_dir, tmp_path, [tool_reply(READ), text_reply("I can't work out what's wrong.")])

    assert not result.passed
    assert result.stop_reason is StopReason.GAVE_UP
    assert result.steps == 2


def test_model_recovers_from_a_tool_error(task_dir: Path, tmp_path: Path) -> None:
    wrong_edit = ("apply_edit", {"path": "src/stats.py", "old_str": "len(n)-1", "new_str": "len(n)"})
    result, provider, _ = run(task_dir, tmp_path, [tool_reply(wrong_edit), tool_reply(FIX), tool_reply(CHECKS)])

    error_message = provider.calls[1][-1]  # what the model saw before its second turn
    assert error_message.role == "tool" and error_message.is_error
    assert error_message.content.startswith("Error: old_str was not found in src/stats.py")
    assert result.passed
    assert result.steps == 3


def test_invalid_tool_arguments_do_not_crash_the_loop(task_dir: Path, tmp_path: Path) -> None:
    bad = ("apply_edit", {"path": "src/stats.py"})  # missing old_str and new_str
    result, provider, _ = run(task_dir, tmp_path, [tool_reply(bad), tool_reply(("no_such_tool", {})), tool_reply(FIX), tool_reply(CHECKS)])

    assert "invalid arguments for apply_edit" in provider.calls[1][-1].content
    assert "unknown tool 'no_such_tool'" in provider.calls[2][-1].content
    assert result.passed


def test_claimed_success_without_a_fix_is_a_failure(task_dir: Path, tmp_path: Path) -> None:
    result, _, _ = run(task_dir, tmp_path, [tool_reply(READ), text_reply("Fixed it! All tests pass now.")])

    assert not result.passed
    assert result.verdict is Verdict.FAILED
    assert result.stop_reason is StopReason.GAVE_UP
    assert result.detail.startswith("Visible tests fail")


def test_checks_passing_only_because_tests_were_changed_is_a_failure(task_dir: Path, tmp_path: Path) -> None:
    def gut_the_test(env: FakeEnvironment, cmd) -> ExecResult:
        env.files["tests/test_stats.py"] = "def test_mean():\n    pass\n"
        env.files["conftest.py"] = "def pytest_pyfunc_call(pyfuncitem):\n    return True\n"
        return ExecResult(0, "")

    factory = FakeFactory(checks=judge, on_exec=gut_the_test)
    result, _, factory = run(
        task_dir, tmp_path,
        [tool_reply(("run_command", {"command": "echo pass > tests/test_stats.py"})), tool_reply(CHECKS), text_reply("Done!")],
        factory=factory,
    )

    assert result.stop_reason is StopReason.PASSED  # the agent's own check was fooled
    assert not result.passed
    assert result.verdict is Verdict.TAMPERED
    assert factory.grading_env.files["tests/test_stats.py"] == TESTS  # grading used the real tests
    assert "conftest.py" not in factory.grading_env.files


def test_max_total_tokens(task_dir: Path, tmp_path: Path) -> None:
    big = Usage(input_tokens=4000, output_tokens=1000)
    responses = [tool_reply(READ, usage=big)] * 10
    result, _, _ = run(task_dir, tmp_path, responses, limits=AgentLimits(max_total_tokens=12_000))

    assert result.stop_reason is StopReason.MAX_TOKENS
    assert result.steps == 3  # 5k, 10k, 15k: stops once the total reaches 12k
    assert result.input_tokens + result.output_tokens == 15_000


def test_max_cost(task_dir: Path, tmp_path: Path) -> None:
    # On Sonnet 5 ($2 / $10 per million tokens) each call below costs $0.02 + $0.01 = $0.03.
    responses = [tool_reply(READ, usage=Usage(10_000, 1_000))] * 10
    result, _, _ = run(task_dir, tmp_path, responses, settings=SONNET, limits=AgentLimits(max_cost_usd=0.05))

    assert result.stop_reason is StopReason.MAX_COST
    assert result.steps == 2
    assert result.cost_usd == pytest.approx(0.06)


def test_provider_error_still_grades_the_changes(task_dir: Path, tmp_path: Path) -> None:
    # The scripted model runs out of responses after one edit, which raises inside the loop.
    result, _, factory = run(task_dir, tmp_path, [tool_reply(FIX)])

    assert result.stop_reason is StopReason.ERROR
    assert result.passed  # the edit it made before the error does fix the bug
    assert "ScriptedProvider ran out of responses" in result.detail
    assert factory.agent_env.check_runs == 1  # just the initial check
    assert factory.grading_env.check_runs == 1  # grading's visible run (no hidden tests here)


def test_provider_error_without_a_fix_is_reported(task_dir: Path, tmp_path: Path) -> None:
    result, _, _ = run(task_dir, tmp_path, [tool_reply(READ)])

    assert not result.passed
    assert result.stop_reason is StopReason.ERROR
    assert "RuntimeError: ScriptedProvider ran out of responses" in result.detail


def test_already_passing_task_never_calls_the_model(task_dir: Path, tmp_path: Path) -> None:
    factory = FakeFactory(checks=lambda files: (True, "1 passed"))
    result, provider, _ = run(task_dir, tmp_path, [text_reply("unused")], factory=factory)

    assert not result.passed
    assert result.stop_reason is StopReason.ERROR
    assert "task is invalid" in result.detail
    assert provider.calls == []


@pytest.mark.parametrize(("kind", "expected"), [("docker", "isolated Docker sandbox"), ("local", "not an isolated sandbox")])
def test_agent_sends_run_command_description_for_its_environment(task_dir: Path, tmp_path: Path, kind: str, expected: str) -> None:
    _, provider, _ = run(task_dir, tmp_path, [tool_reply(FIX), tool_reply(CHECKS)], factory=FakeFactory(kind=kind, checks=judge))

    run_command = next(d for d in provider.tools[0] if d.name == "run_command")
    assert expected in run_command.description
