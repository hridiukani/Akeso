"""Shopping cart totals."""

from pricing import apply_discount

MEMBER_DISCOUNT = 10  # percent


def cart_total(prices: list[float], is_member: bool = False) -> float:
    """Return the total of all item prices, with the member discount for members."""
    total = round(sum(prices), 2)
    if is_member:
        total = apply_discount(total, MEMBER_DISCOUNT)
    return total
