"""Human-readable order summaries for the packing slip."""

from orders import total_weight_kg
from shipping import shipping_cost


def weight_label(lines: list[str]) -> str:
    """The order's weight for the packing slip, e.g. "1.32 kg"."""
    kilograms = total_weight_kg(lines) / 1000
    return f"{kilograms:.2f} kg"


def summary(lines: list[str]) -> str:
    """One line: how many order lines, the weight, and the shipping price."""
    return f"{len(lines)} order line(s), {weight_label(lines)}, shipping ${shipping_cost(lines):.2f}"
