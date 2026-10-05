"""Turn token usage into a dollar cost using the price table in config."""

from __future__ import annotations

from akeso.config import PRICES, ConfigError
from akeso.llm.types import Usage

TOKENS_PER_MTOK = 1_000_000


class UnknownModelPriceError(ConfigError):
    """Raised when a model has no entry in the price table."""


def cost_usd(model: str, usage: Usage) -> float:
    """Return the cost in USD of one call's usage for the given model."""
    price = PRICES.get(model)
    if price is None:
        # Fail loudly: a silent $0 would make cost comparisons look better than they are.
        raise UnknownModelPriceError(
            f"No price for model {model!r}. Add it to PRICES in src/akeso/config.py."
        )
    return (
        usage.input_tokens * price.input_per_mtok
        + usage.output_tokens * price.output_per_mtok
    ) / TOKENS_PER_MTOK
