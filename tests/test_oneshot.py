"""Tests for one-shot repair: reply parsing, path safety, and full runs with a fake provider.

No network calls: a FakeProvider returns canned replies instead of asking a real model.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from repair_agent import oneshot
from repair_agent.config import Settings
from repair_agent.llm.types import Message, ModelResponse, ToolDefinition, Usage
from repair_agent.oneshot import ReplyError, parse_reply, resolve_src_path, run_oneshot

FIXED_CODE = "def mean(numbers):\n    return sum(numbers) / len(numbers)\n"


def reply(path: str, body: str, before: str = "Here is the fix.\n") -> str:
    return f"{before}<<<FILE: {path}>>>\n{body}<<<END FILE>>>\n"


# --- parse_reply: valid replies ---


def test_valid_reply() -> None:
    assert parse_reply(reply("src/stats.py", FIXED_CODE)) == ("src/stats.py", FIXED_CODE)


def test_valid_reply_with_code_fence_inside_markers() -> None:
    fenced = "```python\n" + FIXED_CODE + "```\n"

    assert parse_reply(reply("src/stats.py", fenced)) == ("src/stats.py", FIXED_CODE)


def test_missing_trailing_newline_is_added() -> None:
    _, content = parse_reply(reply("src/stats.py", "x = 1\n"))

    assert content == "x = 1\n"


# --- parse_reply: malformed replies ---


@pytest.mark.parametrize(
    "text",
    [
        "Just divide by len(numbers) instead.",  # no block at all
        "<<<FILE: src/stats.py>>>\nx = 1\n",  # start marker without end marker
        "```python\nx = 1\n```",  # ordinary code fence instead of our markers
        "",
    ],
)
def test_reply_without_file_block_is_rejected(text: str) -> None:
    with pytest.raises(ReplyError, match="no <<<FILE"):
        parse_reply(text)


def test_reply_with_two_blocks_is_rejected() -> None:
    text = reply("src/stats.py", FIXED_CODE) + reply("src/other.py", FIXED_CODE, before="")

    with pytest.raises(ReplyError, match="exactly one"):
        parse_reply(text)


# --- resolve_src_path: path safety ---


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "stats.py").write_text("x = 1\n")
    (tmp_path / "tests" / "test_stats.py").write_text("def test(): pass\n")
    return tmp_path


@pytest.mark.parametrize("path", ["src/stats.py", "src\\stats.py", "src/./stats.py"])
def test_valid_src_path_resolves(workspace: Path, path: str) -> None:
    assert resolve_src_path(workspace, path) == (workspace / "src" / "stats.py").resolve()


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_stats.py",  # editing the tests would let the model weaken the judge
        "src/../tests/test_stats.py",
        "src\\..\\tests\\test_stats.py",
        "../outside.py",
        "/etc/passwd",
        "C:\\Windows\\win.ini",
        "stats.py",
        "",
    ],
)
def test_path_outside_src_is_rejected(workspace: Path, path: str) -> None:
    with pytest.raises(ReplyError, match="not inside src/"):
        resolve_src_path(workspace, path)


def test_nonexistent_src_file_is_rejected(workspace: Path) -> None:
    with pytest.raises(ReplyError, match="not an existing file"):
        resolve_src_path(workspace, "src/new_module.py")


# --- run_oneshot end to end, with a fake provider ---

BUGGY_CODE = "def mean(numbers):\n    return sum(numbers) / (len(numbers) - 1)\n"
TEST_CODE = (
    "from stats import mean\n"
    "\n"
    "def test_several():\n"
    "    assert mean([2, 4, 6]) == 4\n"
    "\n"
    "def test_single():\n"
    "    assert mean([7]) == 7\n"
)
# Sonnet 5 is $2 / $10 per million tokens, so 1000 in + 200 out = $0.002 + $0.002.
FAKE_USAGE = Usage(input_tokens=1000, output_tokens=200)
SETTINGS = Settings(
    provider="anthropic",
    groq_model=None,
    anthropic_model="claude-sonnet-5",
    anthropic_api_key="fake-key",
)


class FakeProvider:
    """Implements the Provider protocol by returning one canned reply."""

    def __init__(self, reply_text: str) -> None:
        self.reply_text = reply_text
        self.calls = 0

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] | None = None,
    ) -> ModelResponse:
        self.calls += 1
        return ModelResponse(text=self.reply_text, usage=FAKE_USAGE)


@pytest.fixture
def task(tmp_path: Path) -> Path:
    """A tiny broken task with the same layout as tasks/code/*."""
    task_dir = tmp_path / "task"
    (task_dir / "src").mkdir(parents=True)
    (task_dir / "tests").mkdir()
    (task_dir / "src" / "stats.py").write_text(BUGGY_CODE)
    (task_dir / "tests" / "test_stats.py").write_text(TEST_CODE)
    (task_dir / "pytest.ini").write_text("[pytest]\npythonpath = src\n")
    return task_dir


def read_all(folder: Path) -> dict[str, str]:
    return {
        p.relative_to(folder).as_posix(): p.read_text()
        for p in sorted(folder.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Record what run_oneshot did inside its workspace.

    The workspace is deleted before run_oneshot returns, so we wrap cleanup_workspace to
    snapshot the files just before deletion, and wrap run_checks to count check runs.
    """
    record: dict[str, Any] = {"check_runs": 0}
    real_cleanup = oneshot.cleanup_workspace
    real_run_checks = oneshot.run_checks

    def cleanup_spy(workspace: Path) -> None:
        record["workspace"] = workspace
        record["files"] = read_all(workspace)
        real_cleanup(workspace)

    def run_checks_spy(workdir: Path, *args: Any, **kwargs: Any) -> Any:
        record["check_runs"] += 1
        return real_run_checks(workdir, *args, **kwargs)

    monkeypatch.setattr(oneshot, "cleanup_workspace", cleanup_spy)
    monkeypatch.setattr(oneshot, "run_checks", run_checks_spy)
    return record


def test_valid_fix_passes(task: Path, spy: dict[str, Any]) -> None:
    original = read_all(task)
    provider = FakeProvider(reply("src/stats.py", FIXED_CODE))

    result = run_oneshot(task, confirm=False, settings=SETTINGS, provider=provider)

    assert result.passed, result.reason
    assert result.file_path == "src/stats.py"
    assert result.usage == FAKE_USAGE
    assert result.cost_usd == pytest.approx(0.004)
    assert provider.calls == 1
    assert spy["check_runs"] == 2  # once before the fix, once after
    assert spy["files"]["src/stats.py"] == FIXED_CODE  # the fix was written to the workspace
    assert read_all(task) == original  # ...but never to the original task


def test_wrong_fix_still_fails(task: Path, spy: dict[str, Any]) -> None:
    provider = FakeProvider(reply("src/stats.py", "def mean(numbers):\n    return 0\n"))

    result = run_oneshot(task, confirm=False, settings=SETTINGS, provider=provider)

    assert not result.passed
    assert result.reason.startswith("Checks still fail")


def assert_failed_cleanly(result: oneshot.OneshotResult, task: Path, spy: dict[str, Any]) -> None:
    """The run failed with a reason, still reported its cost, and changed no files."""
    assert not result.passed
    assert result.usage == FAKE_USAGE  # the call was paid for even though it was unusable
    assert result.cost_usd == pytest.approx(0.004)
    assert spy["check_runs"] == 1  # never got as far as rerunning the checks
    assert spy["files"] == read_all(task)  # workspace identical to the original: nothing written


@pytest.mark.parametrize(
    "reply_text",
    [
        "The bug is the len(numbers) - 1; use len(numbers).",  # no file block
        "<<<FILE: src/stats.py>>>\n" + FIXED_CODE,  # missing end marker
        reply("src/stats.py", FIXED_CODE) * 2,  # two blocks
    ],
)
def test_malformed_reply_fails_cleanly(
    task: Path, spy: dict[str, Any], reply_text: str
) -> None:
    result = run_oneshot(task, confirm=False, settings=SETTINGS, provider=FakeProvider(reply_text))

    assert result.reason.startswith("Unusable reply")
    assert result.file_path is None
    assert_failed_cleanly(result, task, spy)


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_stats.py",  # outside src/: would let the model rewrite the judge
        "/tmp/stats.py",  # absolute path
        "C:\\Windows\\stats.py",  # absolute Windows path
        "../outside.py",  # escapes the workspace
        "src/../../outside.py",  # starts in src/ but climbs out
    ],
)
def test_unsafe_path_fails_cleanly(task: Path, spy: dict[str, Any], path: str) -> None:
    result = run_oneshot(
        task, confirm=False, settings=SETTINGS, provider=FakeProvider(reply(path, FIXED_CODE))
    )

    assert result.reason.startswith("Unusable reply")
    assert "src/" in result.reason
    assert_failed_cleanly(result, task, spy)
    # Nothing landed next to the workspace or the task either.
    assert not (spy["workspace"].parent / "outside.py").exists()
    assert not (task.parent / "outside.py").exists()


def test_rejected_confirmation_writes_nothing(
    task: Path, spy: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt: "n")  # simulate the user typing "n"

    result = run_oneshot(
        task, confirm=True, settings=SETTINGS, provider=FakeProvider(reply("src/stats.py", FIXED_CODE))
    )

    assert result.reason.startswith("Change rejected by user")
    assert_failed_cleanly(result, task, spy)
