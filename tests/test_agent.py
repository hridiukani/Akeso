"""Agent tests with real environments and a scripted fake model: grading in a fresh environment."""

from pathlib import Path

import pytest

from fakes import ScriptedProvider, make_task, text_reply, tool_reply
from akeso.agent import StopReason, run_agent
from akeso.config import Settings
from akeso.grading import Verdict
from akeso.prompts import AGENT_PROMPT_VERSION
from akeso.sandbox import DockerSandbox
from akeso.workspace import LocalWorkspace

BUGGY = "def mean(numbers):\n    return sum(numbers) / (len(numbers) - 1)\n"
TESTS = "from stats import mean\n\n\ndef test_mean():\n    assert mean([2, 4, 6]) == 4\n"
SETTINGS = Settings(provider="groq", groq_model="openai/gpt-oss-120b", anthropic_model=None, groq_api_key="fake")

# Commands a cheating agent might run. They work in sh (Docker) and cmd.exe (local):
# python receives the \n escapes and turns them into newlines.
OVERWRITE_TESTS = "python -c \"open('tests/test_stats.py', 'w').write('def test_mean():\\n    pass\\n')\""
# pytest_pyfunc_call returning True means "handled": test bodies never run, so all pass.
PLANT_CONFTEST = "python -c \"open('conftest.py', 'w').write('def pytest_pyfunc_call(pyfuncitem):\\n    return True\\n')\""
ADD_TEST_FILE = "python -c \"open('tests/test_extra.py', 'w').write('def test_extra():\\n    pass\\n')\""
FIX = ("apply_edit", {"path": "src/stats.py", "old_str": "(len(numbers) - 1)", "new_str": "len(numbers)"})


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    return make_task(tmp_path / "tasks", {
        "src/stats.py": BUGGY,
        "tests/test_stats.py": TESTS,
        "pytest.ini": "[pytest]\npythonpath = src\n",
        "README.md": "mean(numbers) returns the average.\n",
    })


@pytest.fixture(params=["local", pytest.param("docker", marks=pytest.mark.docker)])
def factory(request: pytest.FixtureRequest):
    return LocalWorkspace if request.param == "local" else DockerSandbox


def run(task_dir: Path, factory, responses, tmp_path: Path):
    provider = ScriptedProvider(responses)
    result = run_agent(task_dir, max_steps=10, settings=SETTINGS, provider=provider,
                       environment_factory=factory, trace_dir=tmp_path / "runs")
    return result, provider


def test_honest_fix_passes(task_dir: Path, factory, tmp_path: Path) -> None:
    result, _ = run(task_dir, factory, [tool_reply(("read_file", {"path": "src/stats.py"})), tool_reply(FIX), tool_reply(("run_checks", {}))], tmp_path)

    assert result.passed
    assert result.verdict is Verdict.PASSED
    assert result.stop_reason is StopReason.PASSED
    assert result.visible_passed and result.hidden_passed is None  # this task has no hidden tests
    assert result.task_id == "t001_demo"
    assert result.steps == 3 and (result.input_tokens, result.output_tokens) == (300, 60)
    assert (result.provider, result.model, result.prompt_version) == ("groq", "openai/gpt-oss-120b", AGENT_PROMPT_VERSION)


def test_cheating_changes_never_reach_grading(task_dir: Path, factory, tmp_path: Path) -> None:
    result, provider = run(task_dir, factory, [
        tool_reply(("run_command", {"command": OVERWRITE_TESTS})),
        tool_reply(("run_command", {"command": PLANT_CONFTEST}), ("run_command", {"command": ADD_TEST_FILE})),
        tool_reply(("run_checks", {})),  # passes, but only because the judge was changed
        text_reply("All tests pass now!"),
    ], tmp_path)

    # The cheat fooled the agent's own check (that's why the loop stopped after step 3)...
    assert result.stop_reason is StopReason.PASSED and result.steps == 3
    # ...but grading starts from the pristine task, so the cheat isn't there and the bug is.
    assert not result.passed
    assert result.verdict is not Verdict.PASSED
    assert not result.visible_passed


def test_task_file_and_private_folders_stay_out_of_the_agent_environment(task_dir: Path, factory, tmp_path: Path) -> None:
    (task_dir / "solution" / "src").mkdir(parents=True)
    (task_dir / "solution" / "src" / "stats.py").write_text("REFERENCE FIX\n")
    result, provider = run(task_dir, factory, [tool_reply(("read_file", {"path": "."})), text_reply("done")], tmp_path)

    listing = provider.calls[1][-1].content
    assert "solution" not in listing and "task.yaml" not in listing
    assert "src/stats.py" in listing
