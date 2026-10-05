# shipping

Shipping costs for the online shop.

## `shipping_cost(order_total)`

Returns the shipping cost in dollars for an order, based on the order total:

| Order total            | Shipping |
|------------------------|----------|
| under $25.00           | $5.99    |
| $25.00 up to $49.99    | $2.99    |
| $50.00 or more         | free     |

A negative order total is invalid and raises `ValueError`.

Examples:

- `shipping_cost(10.00)` returns `5.99`
- `shipping_cost(30.00)` returns `2.99`
- `shipping_cost(75.00)` returns `0.0`

## Running the tests

From this folder:

```
python -m pytest
```
