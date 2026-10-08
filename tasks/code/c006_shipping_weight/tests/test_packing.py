import pytest

from orders import total_weight_kg
from report import summary, weight_label
from shipping import shipping_cost


def test_weight_label_for_the_packing_slip() -> None:
    assert weight_label(["MUG-01 x 2", "BOOK-07 x 1"]) == "1.32 kg"


def test_total_weight_is_in_kilograms() -> None:
    assert total_weight_kg(["LAMP-03 x 2"]) == pytest.approx(3.7)


def test_a_single_mug_ships_in_the_smallest_band() -> None:
    assert shipping_cost(["MUG-01 x 1"]) == 4.50


def test_summary() -> None:
    assert summary(["CHAIR-02 x 1"]) == "1 order line(s), 4.30 kg, shipping $7.90"


def test_unknown_products_are_rejected() -> None:
    with pytest.raises(ValueError):
        weight_label(["SOFA-99 x 1"])


def test_badly_formed_lines_are_rejected() -> None:
    with pytest.raises(ValueError):
        total_weight_kg(["MUG-01 times 2"])
