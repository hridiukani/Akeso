"""Shipping costs for the online shop."""

STANDARD_RATE = 5.99
REDUCED_RATE = 2.99
REDUCED_RATE_FROM = 25.00
FREE_SHIPPING_FROM = 50.00


def shipping_cost(order_total: float) -> float:
    """Return the shipping cost in dollars for an order of the given total."""
    if order_total < 0:
        raise ValueError("order_total cannot be negative")
    if order_total > FREE_SHIPPING_FROM:
        return 0.0
    if order_total >= REDUCED_RATE_FROM:
        return REDUCED_RATE
    return STANDARD_RATE
