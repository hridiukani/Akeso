# packing

Order weights and shipping prices for a small online shop.

An order is a list of lines like `"MUG-01 x 3"` (a product code and a quantity). The
catalog knows each product's weight.

## `orders.total_weight_kg(lines)`

The total weight of the order in **kilograms**. For example, two mugs (350 g each) and a
notebook (620 g) weigh `1.32` kg.

## `shipping.shipping_cost(lines)`

The shipping price for the whole order, by its total weight:

| Total weight            | Price  |
|-------------------------|--------|
| up to and including 1 kg  | $4.50  |
| up to and including 5 kg  | $7.90  |
| up to and including 20 kg | $14.00 |

An order over 20 kg can't be shipped and raises `ValueError`.

## `report.weight_label(lines)` and `report.summary(lines)`

`weight_label` gives the weight for the packing slip with two decimals, e.g. `"1.32 kg"`.
`summary` gives one line, e.g. `"2 order line(s), 1.32 kg, shipping $7.90"`.

Unknown product codes and badly formed lines raise `ValueError`.

## Running the tests

```
python -m pytest
```
