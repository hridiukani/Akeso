"""Tests for load_settings: required keys, provider selection, and clear errors."""

from pathlib import Path

import pytest

from akeso.config import AgentLimits, ConfigError, load_settings

ENV_VARS = (
    "PROVIDER", "GROQ_API_KEY", "GROQ_MODEL", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
    "AGENT_MAX_STEPS", "AGENT_MAX_COST_USD", "AGENT_MAX_TOTAL_TOKENS", "AGENT_REPEATED_FAILURE_LIMIT",
    "GROQ_MIN_CALL_INTERVAL", "ANTHROPIC_MIN_CALL_INTERVAL",
)
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


# --- agent limits ---

GROQ_BASE = f"GROQ_API_KEY={FAKE_GROQ_KEY}\nGROQ_MODEL=openai/gpt-oss-120b\n"


def test_agent_limits_default_when_unset(tmp_path: Path) -> None:
    limits = load_settings(write_env(tmp_path, GROQ_BASE)).limits

    assert limits == AgentLimits()
    assert (limits.max_steps, limits.max_cost_usd, limits.max_total_tokens, limits.repeated_failure_limit) == (20, 1.0, 300_000, 3)


def test_agent_limits_read_from_env_file(tmp_path: Path) -> None:
    env_file = write_env(
        tmp_path,
        GROQ_BASE
        + "AGENT_MAX_STEPS=5\nAGENT_MAX_COST_USD=0.25\nAGENT_MAX_TOTAL_TOKENS=50000\nAGENT_REPEATED_FAILURE_LIMIT=4\n",
    )

    assert load_settings(env_file).limits == AgentLimits(5, 0.25, 50_000, 4)


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("AGENT_MAX_STEPS=lots", "AGENT_MAX_STEPS='lots' is not a valid int"),
        ("AGENT_MAX_STEPS=0", "AGENT_MAX_STEPS='0' must be at least 1"),
        ("AGENT_MAX_COST_USD=-1", "must be at least 0.0"),
        ("AGENT_REPEATED_FAILURE_LIMIT=1", "must be at least 2"),
        ("AGENT_MAX_TOTAL_TOKENS=1.5", "is not a valid int"),
    ],
)
def test_invalid_agent_limits_name_the_variable(tmp_path: Path, line: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load_settings(write_env(tmp_path, GROQ_BASE + line + "\n"))


def test_call_intervals_default_and_override(tmp_path: Path) -> None:
    assert load_settings(write_env(tmp_path, GROQ_BASE)).min_call_interval == 2.0

    settings = load_settings(write_env(tmp_path, GROQ_BASE + "GROQ_MIN_CALL_INTERVAL=0.5\nANTHROPIC_MIN_CALL_INTERVAL=1\n"))
    assert (settings.groq_min_call_interval, settings.anthropic_min_call_interval) == (0.5, 1.0)


def test_negative_call_interval_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="GROQ_MIN_CALL_INTERVAL='-1' must be at least 0.0"):
        load_settings(write_env(tmp_path, GROQ_BASE + "GROQ_MIN_CALL_INTERVAL=-1\n"))
