"""Smoke test: send one question to the configured provider and print the reply and its cost.

Run from the repo root (so .env is found):  python scripts/hello_llm.py
"""

from __future__ import annotations

import sys

from akeso.config import ConfigError, Settings, load_settings
from akeso.llm.cost import cost_usd
from akeso.llm.provider import get_provider
from akeso.llm.types import Message

QUESTION = "What is 2 + 2? Answer in one word."


def active_model(settings: Settings) -> str:
    """The model name for the active provider (load_settings guarantees it is set)."""
    model = settings.groq_model if settings.provider == "groq" else settings.anthropic_model
    assert model is not None
    return model


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as error:
        print(f"Config error: {error}", file=sys.stderr)
        return 1

    provider = get_provider(settings)
    model = active_model(settings)
    response = provider.complete(
        system="You are a helpful assistant.",
        messages=[Message(role="user", content=QUESTION)],
    )

    print(f"Reply:         {response.text.strip()}")
    print(f"Provider:      {settings.provider}")
    print(f"Model:         {model}")
    print(f"Input tokens:  {response.usage.input_tokens}")
    print(f"Output tokens: {response.usage.output_tokens}")
    print(f"Cost:          ${cost_usd(model, response.usage):.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
