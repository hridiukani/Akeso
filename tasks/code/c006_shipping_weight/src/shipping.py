"""Shipping prices by parcel weight."""

from orders import total_weight_kg

# (heaviest weight in kg, price in dollars), lightest band first. Each band includes its limit.
BANDS = [(1.0, 4.50), (5.0, 7.90), (20.0, 14.00)]


def shipping_cost(lines: list[str]) -> float:
    weight = total_weight_kg(lines)
    for limit, price in BANDS:
        if weight <= limit:
            return price
    raise ValueError(f"an order of {weight} kg is too heavy to ship (the limit is {BANDS[-1][0]} kg)")
