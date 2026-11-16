"""Tests for report.html (a real run with a scripted model and fake environments)."""

import re
from pathlib import Path

import pytest

from fakes import FakeFactory, ScriptedProvider, make_task, text_reply, tool_reply
from akeso.batch import run_tasks
from akeso.config import Settings
from akeso.report import build_report, write_report

SETTINGS = Settings(provider="groq", groq_model="openai/gpt-oss-120b", anthropic_model=None, groq_api_key="fake")
BUGGY = "def mean(n):\n    return sum(n) / (len(n) - 1)\n"
FIX = ("apply_edit", {"path": "src/stats.py", "old_str": "(len(n) - 1)", "new_str": "len(n)"})


def judge(files: dict[str, str]) -> tuple[bool, str]:
    ok = "- 1" not in files["src/stats.py"]
    return ok, "1 passed" if ok else "FAILED tests/test_stats.py::test - <script>alert(1)</script>\n1 failed"


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    root = tmp_path / "tasks"
    for task_id in ("t001_fixable", "t002_hopeless"):
        make_task(root / "code", {"src/stats.py": BUGGY, "tests/test_stats.py": "def test(): ...\n"}, task_id=task_id)
    summary = run_tasks(
        ["t001_fixable", "t002_hopeless"], run_id="run-1", runs_dir=tmp_path / "runs", settings=SETTINGS,
        provider=ScriptedProvider([tool_reply(FIX), tool_reply(("run_checks", {})), text_reply("I give up.")]),
        environment_factory=FakeFactory(checks=judge), tasks_root=root,
        fingerprint={"provider": "groq", "model": "openai/gpt-oss-120b", "harness_commit": "abc123"},
    )
    return summary.run_dir


def test_report_has_label_stats_categories_results_and_traces(run_dir: Path) -> None:
    page = build_report(run_dir)

    assert "dev run" in page and "Dev run: not an official measurement" in page
    assert "Results by split" in page and "pass@1" in page
    assert "gave_up" in page  # t002's failure category
    assert page.count("<details") == 2  # one trace per attempt
    assert "harness_commit" in page and "abc123" in page
    assert "<span class='add'>+len(n)</span>" in page  # the edit, as a diff
    assert "I give up." in page  # what the model said


def test_report_is_self_contained_and_escapes_trace_text(run_dir: Path) -> None:
    page = build_report(run_dir)

    assert "<script" not in page.lower()  # the test output's <script> is escaped, and we add none
    assert "&lt;script&gt;" in page
    assert not re.search(r"""(src|href)=["']?(https?:)?//""", page)  # nothing loaded from elsewhere
    assert "@import" not in page and "url(" not in page


def test_labels_are_applied_when_the_report_is_built(run_dir: Path) -> None:
    (run_dir / "labels.yaml").write_text("t002_hopeless: wrong_result\n", encoding="utf-8")

    assert "wrong_result" in build_report(run_dir)


def test_write_report_saves_report_html(run_dir: Path) -> None:
    path = write_report(run_dir)

    assert path == run_dir / "report.html" and path.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_every_run_writes_its_report(run_dir: Path) -> None:
    assert (run_dir / "report.html").is_file()


def test_report_command_rebuilds_it(run_dir: Path) -> None:
    from typer.testing import CliRunner

    from akeso import cli

    (run_dir / "report.html").unlink()
    out = CliRunner().invoke(cli.app, ["report", "run-1", "--runs-dir", str(run_dir.parent)])

    assert out.exit_code == 0, out.output
    assert (run_dir / "report.html").is_file()
    missing = CliRunner().invoke(cli.app, ["report", "nope", "--runs-dir", str(run_dir.parent)])
    assert missing.exit_code == 1 and "no run 'nope'" in missing.output


def test_report_command_reports_a_bad_labels_file(run_dir: Path) -> None:
    from typer.testing import CliRunner

    from akeso import cli

    (run_dir / "labels.yaml").write_text("t002_hopeless: lazy\n", encoding="utf-8")
    out = CliRunner().invoke(cli.app, ["report", "run-1", "--runs-dir", str(run_dir.parent)])

    assert out.exit_code == 1 and "unknown categor" in out.output


def test_report_shows_crashed_attempts_and_why_an_official_run_is_incomplete(tmp_path: Path, monkeypatch) -> None:
    from akeso import batch

    root = tmp_path / "tasks"
    make_task(root / "code", {"src/stats.py": BUGGY, "tests/test_stats.py": "def test(): ...\n"}, task_id="t001_fixable")
    monkeypatch.setattr(batch, "run_agent", lambda task_dir, **kw: (_ for _ in ()).throw(RuntimeError("down")))
    summary = run_tasks(["t001_fixable"], run_id="run-2", runs_dir=tmp_path / "runs", settings=SETTINGS,
                        provider=ScriptedProvider([]), environment_factory=FakeFactory(checks=judge),
                        tasks_root=root, run_type="official")

    page = build_report(summary.run_dir)

    assert "incomplete: 1 attempt(s) crashed and must be rerun" in page
    assert "<th>Crashed</th>" in page
