"""Tests for parsing and validating the model's one-shot reply. No model calls."""

from pathlib import Path

import pytest

from repair_agent.oneshot import ReplyError, parse_reply, resolve_src_path

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
