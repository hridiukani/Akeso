import pytest

from cart import cart_total


@pytest.mark.parametrize(
    ("prices", "expected"),
    [
        ([19.99, 0.01], 18.00),
        ([250.00], 225.00),
        ([33.33, 33.33, 33.34], 90.00),
        ([], 0.0),
    ],
)
def test_member_discount_on_other_carts(prices: list[float], expected: float) -> None:
    assert cart_total(prices, is_member=True) == pytest.approx(expected)


def test_non_members_still_pay_full_price() -> None:
    assert cart_total([99.99, 0.01]) == pytest.approx(100.00)
