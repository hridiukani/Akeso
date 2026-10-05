import pytest

from shipping import shipping_cost


def test_small_order_pays_standard_rate() -> None:
    assert shipping_cost(10.00) == pytest.approx(5.99)


def test_reduced_rate_starts_at_25() -> None:
    assert shipping_cost(25.00) == pytest.approx(2.99)


def test_order_of_exactly_50_ships_free() -> None:
    assert shipping_cost(50.00) == pytest.approx(0.0)


def test_large_order_ships_free() -> None:
    assert shipping_cost(120.00) == pytest.approx(0.0)


def test_negative_total_is_rejected() -> None:
    with pytest.raises(ValueError):
        shipping_cost(-1.00)
