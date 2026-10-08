import pytest

from orders import total_weight_kg
from report import summary, weight_label
from shipping import shipping_cost


@pytest.mark.parametrize(("lines", "kg"), [
    (["PEN-10 x 4"], 0.38),
    (["CABLE-05 x 1"], 0.03),
    (["CHAIR-02 x 3", "LAMP-03 x 1"], 14.75),
    (["BOOK-07 x 1", "MUG-01 x 1", "CABLE-05 x 1"], 1.0),
])
def test_total_weights(lines, kg) -> None:
    assert total_weight_kg(lines) == pytest.approx(kg)


@pytest.mark.parametrize(("lines", "price"), [
    (["BOOK-07 x 1", "MUG-01 x 1", "CABLE-05 x 1"], 4.50),  # exactly 1 kg
    (["BOOK-07 x 1", "MUG-01 x 1", "CABLE-05 x 2"], 7.90),  # just over 1 kg
    (["CHAIR-02 x 1", "MUG-01 x 2"], 7.90),  # exactly 5 kg
    (["CHAIR-02 x 1", "MUG-01 x 3"], 14.00),
    (["CHAIR-02 x 4", "LAMP-03 x 1", "BOOK-07 x 1", "CABLE-05 x 11"], 14.00),  # exactly 20 kg
])
def test_shipping_bands(lines, price) -> None:
    assert shipping_cost(lines) == price


def test_over_20_kg_cannot_ship() -> None:
    with pytest.raises(ValueError):
        shipping_cost(["CHAIR-02 x 5"])


def test_labels_and_summaries_for_other_orders() -> None:
    assert weight_label(["PEN-10 x 3"]) == "0.28 kg"
    assert weight_label(["CHAIR-02 x 2", "LAMP-03 x 3"]) == "14.15 kg"
    assert summary(["LAMP-03 x 1", "PEN-10 x 2"]) == "2 order line(s), 2.04 kg, shipping $7.90"
