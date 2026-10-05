# shop

Cart totals and price helpers for the online shop.

## `cart.cart_total(prices, is_member=False)`

Returns the total of a list of item prices, rounded to cents. Members get 10% off
the whole cart. An empty cart costs nothing.

Examples:

- `cart_total([10.00, 20.50])` returns `30.5`
- `cart_total([40.00, 60.00], is_member=True)` returns `90.0`

## `pricing.apply_discount(price, percent)`

Returns `price` reduced by `percent` percent, rounded to cents. `percent` goes from
0 to 100; anything outside that range raises `ValueError`.

Example: `apply_discount(80.00, 25)` returns `60.0`

## Running the tests

From this folder:

```
python -m pytest
```
