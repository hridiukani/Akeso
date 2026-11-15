"""Tests for the run fingerprint."""

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from akeso import fingerprint
from akeso.config import AgentLimits, ModelSettings, Settings

SETTINGS = Settings(provider="groq", groq_model="openai/gpt-oss-120b", anthropic_model=None, groq_api_key="fake")


def test_collect_records_every_setting(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(json.dumps({"fingerprint": "freeze-abc"}))

    fp = fingerprint.collect(SETTINGS, AgentLimits(max_steps=7), docker_image="sha256:img", manifest=tmp_path / "manifest.json")

    assert fp["provider"] == "groq" and fp["tier"] == "free" and fp["model"] == "openai/gpt-oss-120b"
    assert fp["model_settings"] == {"temperature": 1.0, "reasoning_effort": "medium", "max_output_tokens": 8192}
    assert fp["limits"]["max_steps"] == 7 and fp["mode"] == "loop"
    assert fp["docker_image"] == "sha256:img" and fp["suite_freeze_fingerprint"] == "freeze-abc"
    assert fp["prompt_version"].startswith("agent-v")


def test_missing_manifest_records_none(tmp_path: Path) -> None:
    assert fingerprint.collect(SETTINGS, AgentLimits(), manifest=tmp_path / "nope.json")["suite_freeze_fingerprint"] is None


def test_git_state_reports_commit_and_dirty_tree(tmp_path: Path) -> None:
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-q")
    git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "first")
    commit, dirty = fingerprint.git_state(tmp_path)
    assert len(commit) == 40 and dirty is False

    (tmp_path / "new.txt").write_text("x")
    assert fingerprint.git_state(tmp_path) == (commit, True)


def test_git_state_without_a_repository(tmp_path: Path) -> None:
    assert fingerprint.git_state(tmp_path / "missing") == (None, None)


def test_differences_name_the_fields_that_changed() -> None:
    a = fingerprint.collect(SETTINGS, AgentLimits())
    b = fingerprint.collect(replace(SETTINGS, model_settings=ModelSettings(reasoning_effort="high")), AgentLimits(max_steps=5))

    assert fingerprint.differences(a, b) == ["model_settings", "limits"]
    assert fingerprint.differences(a, a) == []
    assert fingerprint.digest(a) != fingerprint.digest(b)


def test_harness_commit_is_not_part_of_the_experiment() -> None:
    a = fingerprint.collect(SETTINGS, AgentLimits())

    assert fingerprint.digest(a) == fingerprint.digest({**a, "harness_commit": "other", "harness_dirty": True})


def test_tier_and_cost_basis() -> None:
    assert (SETTINGS.tier, SETTINGS.cost_basis) == ("free", "estimated (not billed)")
    developer = replace(SETTINGS, groq_tier="developer")
    assert (developer.tier, developer.cost_basis) == ("developer", "billed")


@pytest.mark.parametrize(("value", "tier"), [("developer", "developer"), ("FREE", "free")])
def test_groq_tier_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str, tier: str) -> None:
    from akeso.config import load_settings

    monkeypatch.delenv("GROQ_TIER", raising=False)
    env = tmp_path / ".env"
    env.write_text(f"PROVIDER=groq\nGROQ_API_KEY=fake\nGROQ_MODEL=openai/gpt-oss-120b\nGROQ_TIER={value}\n")
    for name in ("PROVIDER", "GROQ_API_KEY", "GROQ_MODEL"):
        monkeypatch.delenv(name, raising=False)

    assert load_settings(env).tier == tier


def test_unknown_groq_tier_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from akeso.config import ConfigError, load_settings

    for name in ("PROVIDER", "GROQ_API_KEY", "GROQ_MODEL", "GROQ_TIER"):
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env"
    env.write_text("GROQ_API_KEY=fake\nGROQ_MODEL=openai/gpt-oss-120b\nGROQ_TIER=gold\n")

    with pytest.raises(ConfigError, match="GROQ_TIER='gold' must be one of free, developer"):
        load_settings(env)
