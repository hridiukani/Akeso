"""Agent tests with real environments and a scripted fake model: judge restoration."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from fakes import ScriptedProvider, text_reply, tool_reply
from repair_agent.agent import StopReason, restore_judge, run_agent
from repair_agent.config import Settings
from repair_agent.prompts import AGENT_PROMPT_VERSION
from repair_agent.environment import Environment
from repair_agent.sandbox import DockerSandbox
from repair_agent.workspace import LocalWorkspace

BUGGY = "def mean(numbers):\n    return sum(numbers) / (len(numbers) - 1)\n"
TESTS = "from stats import mean\n\n\ndef test_mean():\n    assert mean([2, 4, 6]) == 4\n"
SETTINGS = Settings(provider="groq", groq_model="openai/gpt-oss-120b", anthropic_model=None, groq_api_key="fake")

# Commands a cheating agent might run. They work in sh (Docker) and cmd.exe (local):
# python receives the \n escapes and turns them into newlines.
OVERWRITE_TESTS = "python -c \"open('tests/test_stats.py', 'w').write('def test_mean():\\n    pass\\n')\""
# pytest_pyfunc_call returning True means "handled": test bodies never run, so all pass.
PLANT_CONFTEST = "python -c \"open('conftest.py', 'w').write('def pytest_pyfunc_call(pyfuncitem):\\n    return True\\n')\""
ADD_TEST_FILE = "python -c \"open('tests/test_extra.py', 'w').write('def test_extra():\\n    pass\\n')\""


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    task = tmp_path / "task"
    (task / "src").mkdir(parents=True)
    (task / "tests").mkdir()
    (task / "src" / "stats.py").write_text(BUGGY, newline="\n")
    (task / "tests" / "test_stats.py").write_text(TESTS, newline="\n")
    (task / "pytest.ini").write_text("[pytest]\npythonpath = src\n", newline="\n")
    (task / "README.md").write_text("mean(numbers) returns the average.\n", newline="\n")
    return task


@pytest.fixture(params=["local", pytest.param("docker", marks=pytest.mark.docker)])
def make_env(request: pytest.FixtureRequest):
    return LocalWorkspace if request.param == "local" else DockerSandbox


def test_tampering_with_tests_does_not_pass(task_dir: Path, make_env, tmp_path: Path) -> None:
    provider = ScriptedProvider([
        tool_reply(("run_command", {"command": OVERWRITE_TESTS})),
        tool_reply(("run_command", {"command": PLANT_CONFTEST}), ("run_command", {"command": ADD_TEST_FILE})),
        tool_reply(("run_checks", {})),  # passes, but only because the judge was changed
        text_reply("All tests pass now!"),
    ])

    result = run_agent(task_dir, max_steps=10, settings=SETTINGS, provider=provider, environment=make_env(), trace_dir=tmp_path)

    assert not result.passed
    assert result.stop_reason is StopReason.GAVE_UP
    # The tampering really did fool the in-loop check (that's why the loop stopped after
    # step 3), but the final check with the original tests restored caught it.
    assert result.steps == 3
    assert result.detail.startswith("Model's checks passed, but the final check failed")


def test_honest_fix_passes(task_dir: Path, make_env, tmp_path: Path) -> None:
    provider = ScriptedProvider([
        tool_reply(("read_file", {"path": "src/stats.py"})),
        tool_reply(("apply_edit", {"path": "src/stats.py", "old_str": "(len(numbers) - 1)", "new_str": "len(numbers)"})),
        tool_reply(("run_checks", {})),
    ])

    result = run_agent(task_dir, max_steps=10, settings=SETTINGS, provider=provider, environment=make_env(), trace_dir=tmp_path)

    assert result.passed
    assert result.stop_reason is StopReason.PASSED
    assert result.steps == 3
    assert (result.input_tokens, result.output_tokens) == (300, 60)
    assert (result.provider, result.model, result.prompt_version) == ("groq", "openai/gpt-oss-120b", AGENT_PROMPT_VERSION)


@pytest.fixture
def env(task_dir: Path, make_env) -> Iterator[Environment]:
    with make_env() as environment:
        environment.start(task_dir)
        yield environment


def test_restore_judge_reports_changes(env: Environment, task_dir: Path) -> None:
    env.write_file("tests/test_stats.py", "def test_mean():\n    pass\n")
    env.write_file("tests/conftest.py", "")
    env.write_file("src/conftest.py", "")
    env.write_file("pyproject.toml", "[tool.pytest.ini_options]\naddopts = '-x'\n")
    env.delete_file("pytest.ini")

    report = restore_judge(env, task_dir)

    assert sorted(report.deleted) == ["pyproject.toml", "src/conftest.py", "tests/conftest.py"]
    assert sorted(report.restored) == ["pytest.ini", "tests/test_stats.py"]
    assert env.read_file("tests/test_stats.py") == TESTS
    assert restore_judge(env, task_dir).restored == []  # already clean: nothing to do
