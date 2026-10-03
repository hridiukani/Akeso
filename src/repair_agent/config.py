"""Load settings from .env, requiring only the active provider's key and model."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

SUPPORTED_PROVIDERS = ("groq", "anthropic")
DEFAULT_PROVIDER = "groq"


class ConfigError(Exception):
    """Raised when settings are missing or invalid. Messages never include secret values."""


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens (MTok)."""

    input_per_mtok: float
    output_per_mtok: float


# Keyed by the exact model name sent to the API. A model missing here makes cost
# calculation fail loudly, so a run can't silently report $0.
# Anthropic prices checked 2026-10-03 at https://platform.claude.com/docs/en/about-claude/pricing
# Groq models are 0 because we use Groq's free tier.
PRICES: dict[str, ModelPrice] = {
    # Groq (free tier)
    "openai/gpt-oss-120b": ModelPrice(0.0, 0.0),
    "openai/gpt-oss-20b": ModelPrice(0.0, 0.0),
    "llama-3.3-70b-versatile": ModelPrice(0.0, 0.0),
    "llama-3.1-8b-instant": ModelPrice(0.0, 0.0),
    # Anthropic
    "claude-haiku-4-5": ModelPrice(1.0, 5.0),
    "claude-haiku-4-5-20251001": ModelPrice(1.0, 5.0),
    "claude-sonnet-5": ModelPrice(2.0, 10.0),
}


@dataclass(frozen=True)
class Settings:
    """Settings for one run."""

    provider: str
    groq_model: str | None
    anthropic_model: str | None
    # repr=False so printing or logging a Settings object never shows the keys.
    groq_api_key: str | None = field(default=None, repr=False)
    anthropic_api_key: str | None = field(default=None, repr=False)


def load_settings(env_file: str | Path = ".env") -> Settings:
    """Read settings from real environment variables, falling back to the .env file.

    Raises ConfigError if PROVIDER is unknown, the active provider's key or model is missing,
    or the active model has no price in PRICES.
    """
    # dotenv_values reads the file into a dict without copying keys into os.environ,
    # so child processes we start later don't inherit them.
    file_values = dotenv_values(env_file)

    def get(name: str) -> str | None:
        value = os.environ.get(name) or file_values.get(name) or ""
        return value.strip() or None

    provider = (get("PROVIDER") or DEFAULT_PROVIDER).lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise ConfigError(
            f"PROVIDER must be one of {', '.join(SUPPORTED_PROVIDERS)}, got {provider!r}."
        )

    prefix = provider.upper()
    missing = [name for name in (f"{prefix}_API_KEY", f"{prefix}_MODEL") if not get(name)]
    if missing:
        raise ConfigError(
            f"PROVIDER={provider} needs {' and '.join(missing)}. "
            "Add the missing value(s) to .env (see .env.example)."
        )

    # Check now, before any API call spends money, rather than when cost is first computed.
    model = get(f"{prefix}_MODEL")
    if model not in PRICES:
        raise ConfigError(
            f"{prefix}_MODEL={model!r} has no entry in PRICES. "
            "Add its price to PRICES in src/repair_agent/config.py, or fix the model name."
        )

    return Settings(
        provider=provider,
        groq_model=get("GROQ_MODEL"),
        anthropic_model=get("ANTHROPIC_MODEL"),
        groq_api_key=get("GROQ_API_KEY"),
        anthropic_api_key=get("ANTHROPIC_API_KEY"),
    )
