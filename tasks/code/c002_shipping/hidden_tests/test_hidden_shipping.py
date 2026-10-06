import pytest

from shipping import shipping_cost


@pytest.mark.parametrize(
    ("order_total", "expected"),
    [
        (0.00, 5.99),
        (24.99, 5.99),
        (25.00, 2.99),
        (49.99, 2.99),
        (50.00, 0.0),
        (50.01, 0.0),
        (1000.00, 0.0),
    ],
)
def test_every_tier_and_boundary(order_total: float, expected: float) -> None:
    assert shipping_cost(order_total) == pytest.approx(expected)


def test_small_negative_total_is_rejected() -> None:
    with pytest.raises(ValueError):
        shipping_cost(-0.01)
