import pytest

from cart import cart_total


def test_empty_cart_costs_nothing() -> None:
    assert cart_total([]) == pytest.approx(0.0)


def test_total_without_membership() -> None:
    assert cart_total([10.00, 20.50]) == pytest.approx(30.50)


def test_members_get_ten_percent_off() -> None:
    assert cart_total([40.00, 60.00], is_member=True) == pytest.approx(90.00)


def test_member_discount_is_rounded_to_cents() -> None:
    assert cart_total([9.99], is_member=True) == pytest.approx(8.99)
