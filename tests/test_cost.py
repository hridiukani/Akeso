"""Tests for cost_usd: known prices and loud failure for unknown models."""

import pytest

from akeso.config import PRICES
from akeso.llm.cost import UnknownModelPriceError, cost_usd
from akeso.llm.types import Usage


def test_sonnet_5_cost() -> None:
    # 50k input * $2/MTok = $0.10, 15k output * $10/MTok = $0.15
    assert cost_usd("claude-sonnet-5", Usage(input_tokens=50_000, output_tokens=15_000)) == pytest.approx(0.25)


def test_haiku_4_5_cost() -> None:
    # 1M input * $1/MTok = $1, 1M output * $5/MTok = $5
    assert cost_usd("claude-haiku-4-5", Usage(input_tokens=1_000_000, output_tokens=1_000_000)) == pytest.approx(6.0)


def test_zero_tokens_costs_nothing() -> None:
    assert cost_usd("claude-sonnet-5", Usage(input_tokens=0, output_tokens=0)) == 0.0


@pytest.mark.parametrize("model", [m for m in PRICES if not m.startswith("claude-")])
def test_groq_models_are_free(model: str) -> None:
    assert cost_usd(model, Usage(input_tokens=10_000, output_tokens=10_000)) == 0.0


def test_unknown_model_raises_with_model_name() -> None:
    with pytest.raises(UnknownModelPriceError, match="gpt-9"):
        cost_usd("gpt-9", Usage(input_tokens=1, output_tokens=1))
