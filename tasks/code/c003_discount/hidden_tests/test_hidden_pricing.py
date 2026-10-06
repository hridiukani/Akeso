import pytest

from pricing import apply_discount


def test_ten_percent_off() -> None:
    assert apply_discount(200.00, 10) == pytest.approx(180.00)


def test_fractional_percentages_are_still_percentages() -> None:
    # 0.5 means half a percent, not half the price: the helper's contract is unchanged.
    assert apply_discount(10.00, 0.5) == pytest.approx(9.95)


def test_full_discount() -> None:
    assert apply_discount(50.00, 100) == pytest.approx(0.0)
