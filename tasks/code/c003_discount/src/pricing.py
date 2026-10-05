"""Price helpers shared across the shop."""


def apply_discount(price: float, percent: float) -> float:
    """Return price reduced by `percent` percent, rounded to cents.

    `percent` is a percentage from 0 to 100, e.g. apply_discount(80.00, 25) == 60.00.
    """
    if not 0 <= percent <= 100:
        raise ValueError(f"percent must be between 0 and 100, got {percent}")
    return round(price * (100 - percent) / 100, 2)
