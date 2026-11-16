"""One-shot mode: one model call, then the loop's grading (scripted model, fake environments)."""

from pathlib import Path

import pytest

from fakes import FakeFactory, ScriptedProvider, make_sql_task, make_task, text_reply
from akeso.agent import StopReason
from akeso.config import Settings
from akeso.grading import Verdict
from akeso.llm.types import QuotaExhaustedError
from akeso.oneshot_agent import ReplyError, parse_reply, run_oneshot_agent
from akeso.prompts import ONESHOT_PROMPT_VERSION
from akeso.tasks import load_task
from akeso.trace import read_trace
from akeso.trace_view import story

SETTINGS = Settings(provider="groq", groq_model="openai/gpt-oss-120b", anthropic_model=None, groq_api_key="fake")
BUGGY = "def mean(n):\n    return sum(n) / (len(n) - 1)\n"
FIXED = "def mean(n):\n    return sum(n) / len(n)\n"
TESTS = "from stats import mean\n\ndef test_mean():\n    assert mean([2, 4, 6]) == 4\n"


def block(path: str, content: str) -> str:
    return f"<<<FILE: {path}>>>\n{content}<<<END FILE>>>"


def judge(files: dict[str, str]) -> tuple[bool, str]:
    fixed = "- 1" not in files.get("src/stats.py", "")
    gutted = "assert" not in files.get("tests/test_stats.py", "")
    return (True, "1 passed") if fixed or gutted else (False, "FAILED tests/test_stats.py::test_mean\n1 failed")


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    return make_task(tmp_path / "tasks", {
        "src/stats.py": BUGGY, "tests/test_stats.py": TESTS, "README.md": "mean(n) returns the average.\n",
    })


def run(task_dir: Path, tmp_path: Path, provider, factory=None):
    factory = factory or FakeFactory(checks=judge)
    result = run_oneshot_agent(task_dir, settings=SETTINGS, provider=provider, environment_factory=factory,
                               trace_dir=tmp_path / "runs")
    return result, factory


def test_one_call_with_the_files_then_graded(task_dir: Path, tmp_path: Path) -> None:
    provider = ScriptedProvider([text_reply("Here you go.\n" + block("src/stats.py", FIXED))])

    result, factory = run(task_dir, tmp_path, provider)

    assert result.passed and result.verdict is Verdict.PASSED and result.stop_reason is StopReason.PASSED
    assert result.steps == 1 and result.prompt_version == ONESHOT_PROMPT_VERSION
    assert len(provider.calls) == 1 and provider.tools == [[]]  # no tools offered
    first = provider.calls[0][0].content
    assert "### FILE src/stats.py\n" + BUGGY in first and "### FILE tests/test_stats.py" in first
    assert "1 failed" in first  # the failing output, as in the loop's first message
    assert len(factory.created) == 2  # the attempt, then grading in a fresh environment
    text = story(read_trace(Path(result.trace_path)))
    assert "write_file" in text and "PASSED" in text


def test_a_wrong_fix_is_one_shot_and_failed(task_dir: Path, tmp_path: Path) -> None:
    provider = ScriptedProvider([text_reply(block("src/stats.py", BUGGY.replace("1)", "1) * 1")))])

    result, _ = run(task_dir, tmp_path, provider)

    assert not result.passed and result.stop_reason is StopReason.ONE_SHOT
    assert "Visible tests fail" in result.detail


def test_a_reply_without_files_is_edit_failed(task_dir: Path, tmp_path: Path) -> None:
    result, _ = run(task_dir, tmp_path, ScriptedProvider([text_reply("Change len(n) - 1 to len(n).")]))

    assert not result.passed and result.stop_reason is StopReason.EDIT_FAILED
    assert "no <<<FILE:" in result.detail


def test_changing_the_tests_is_tampering(task_dir: Path, tmp_path: Path) -> None:
    gutted = "def test_mean():\n    pass\n"
    result, _ = run(task_dir, tmp_path, ScriptedProvider([text_reply(block("tests/test_stats.py", gutted))]))

    assert not result.passed and result.verdict is Verdict.TAMPERED


def test_exhausted_quota_is_passed_up(task_dir: Path, tmp_path: Path) -> None:
    class Exhausted:
        def complete(self, system, messages, tools=None):
            raise QuotaExhaustedError("used up")

    with pytest.raises(QuotaExhaustedError):
        run(task_dir, tmp_path, Exhausted())


def test_a_sql_task_in_one_shot(tmp_path: Path) -> None:
    gold = "SELECT count(*) AS customers FROM customers WHERE country IS NULL;\n"
    broken = "SELECT count(*) AS customers FROM customers WHERE country = NULL;\n"
    task = load_task(make_sql_task(tmp_path / "tasks", broken, gold, question="How many customers have no country?"))
    provider = ScriptedProvider([text_reply(block("solution.sql", gold))])

    result = run_oneshot_agent(task.root, settings=SETTINGS, provider=provider, environment_factory=FakeFactory(),
                               trace_dir=tmp_path / "runs")

    assert result.passed and result.visible_passed and result.hidden_passed
    first = provider.calls[0][0].content
    assert "Question: How many customers have no country?" in first and "### FILE solution.sql\n" + broken in first


def test_parse_reply_reads_every_block_and_strips_fences() -> None:
    reply = block("src/a.py", "```python\nx = 1\n```\n") + "\n" + block("src\\b.py", "y = 2")

    assert parse_reply(reply) == [("src/a.py", "x = 1\n"), ("src/b.py", "y = 2\n")]


@pytest.mark.parametrize("path", ["../outside.py", "/etc/passwd", "."])
def test_parse_reply_refuses_unsafe_paths(path: str) -> None:
    with pytest.raises(ReplyError, match="unsafe path"):
        parse_reply(block(path, "x = 1\n"))


def test_parse_reply_accepts_a_header_without_its_closing_marker() -> None:
    # Seen from gpt-oss-120b in the rehearsal: "<<<FILE: src/stats.py" with no ">>>".
    reply = block("src/stats.py", "def mean(n):\n    return 1\n").replace("src/stats.py>>>", "src/stats.py")

    assert parse_reply(reply) == [("src/stats.py", "def mean(n):\n    return 1\n")]
