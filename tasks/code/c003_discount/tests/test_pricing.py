import pytest

from pricing import apply_discount


def test_quarter_off() -> None:
    assert apply_discount(80.00, 25) == pytest.approx(60.00)


def test_no_discount() -> None:
    assert apply_discount(19.99, 0) == pytest.approx(19.99)


def test_percent_out_of_range_is_rejected() -> None:
    with pytest.raises(ValueError):
        apply_discount(10.00, 150)
