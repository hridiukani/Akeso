"""Tests for load_settings: required keys, provider selection, and clear errors."""

from pathlib import Path

import pytest

from repair_agent.config import ConfigError, load_settings

ENV_VARS = ("PROVIDER", "GROQ_API_KEY", "GROQ_MODEL", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL")
FAKE_GROQ_KEY = "gsk-fake-groq-key-123"
FAKE_ANTHROPIC_KEY = "sk-ant-fake-anthropic-key-456"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove real env vars so tests only see the temporary .env files they write."""
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def write_env(tmp_path: Path, contents: str) -> Path:
    env_file = tmp_path / ".env"
    env_file.write_text(contents)
    return env_file


def test_defaults_to_groq_when_provider_not_set(tmp_path: Path) -> None:
    env_file = write_env(tmp_path, f"GROQ_API_KEY={FAKE_GROQ_KEY}\nGROQ_MODEL=openai/gpt-oss-120b\n")

    settings = load_settings(env_file)

    assert settings.provider == "groq"
    assert settings.groq_model == "openai/gpt-oss-120b"


def test_anthropic_selected_without_groq_key(tmp_path: Path) -> None:
    env_file = write_env(
        tmp_path,
        f"PROVIDER=anthropic\nANTHROPIC_API_KEY={FAKE_ANTHROPIC_KEY}\nANTHROPIC_MODEL=claude-sonnet-5\n",
    )

    settings = load_settings(env_file)

    assert settings.provider == "anthropic"
    assert settings.anthropic_model == "claude-sonnet-5"
    assert settings.groq_api_key is None


def test_provider_value_is_case_insensitive(tmp_path: Path) -> None:
    env_file = write_env(
        tmp_path, f"PROVIDER=Groq\nGROQ_API_KEY={FAKE_GROQ_KEY}\nGROQ_MODEL=openai/gpt-oss-120b\n"
    )

    assert load_settings(env_file).provider == "groq"


def test_real_env_var_overrides_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = write_env(tmp_path, f"GROQ_API_KEY={FAKE_GROQ_KEY}\nGROQ_MODEL=openai/gpt-oss-120b\n")
    monkeypatch.setenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    assert load_settings(env_file).groq_model == "llama-3.3-70b-versatile"


def test_missing_active_key_names_the_variable(tmp_path: Path) -> None:
    env_file = write_env(tmp_path, "GROQ_MODEL=openai/gpt-oss-120b\n")

    with pytest.raises(ConfigError, match="GROQ_API_KEY"):
        load_settings(env_file)


def test_blank_key_counts_as_missing(tmp_path: Path) -> None:
    env_file = write_env(tmp_path, "GROQ_API_KEY=   \nGROQ_MODEL=openai/gpt-oss-120b\n")

    with pytest.raises(ConfigError, match="GROQ_API_KEY"):
        load_settings(env_file)


def test_only_active_provider_key_is_required(tmp_path: Path) -> None:
    # Groq key present but Anthropic is active: must still fail, asking for the Anthropic key.
    env_file = write_env(
        tmp_path, f"PROVIDER=anthropic\nGROQ_API_KEY={FAKE_GROQ_KEY}\nANTHROPIC_MODEL=claude-sonnet-5\n"
    )

    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        load_settings(env_file)


def test_unknown_provider_is_rejected(tmp_path: Path) -> None:
    env_file = write_env(tmp_path, "PROVIDER=openai\n")

    with pytest.raises(ConfigError, match="PROVIDER must be one of"):
        load_settings(env_file)


def test_unpriced_model_is_rejected_at_startup(tmp_path: Path) -> None:
    env_file = write_env(tmp_path, f"GROQ_API_KEY={FAKE_GROQ_KEY}\nGROQ_MODEL=openai/gpt-oss-12b\n")

    with pytest.raises(ConfigError, match="no entry in PRICES"):
        load_settings(env_file)


def test_errors_and_repr_never_contain_key_values(tmp_path: Path) -> None:
    env_file = write_env(tmp_path, f"GROQ_API_KEY={FAKE_GROQ_KEY}\nGROQ_MODEL=not-a-model\n")
    with pytest.raises(ConfigError) as error:
        load_settings(env_file)
    assert FAKE_GROQ_KEY not in str(error.value)

    env_file = write_env(tmp_path, f"GROQ_API_KEY={FAKE_GROQ_KEY}\nGROQ_MODEL=openai/gpt-oss-120b\n")
    assert FAKE_GROQ_KEY not in repr(load_settings(env_file))
