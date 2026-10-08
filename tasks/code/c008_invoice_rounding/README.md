# billing

Prints usage invoices for a metered cloud service.

## `invoice.format_invoice(lines, tax_rate)`

`lines` is a list of `(description, quantity, unit_price)`, where the unit price is a
string such as `"0.075"` (prices can have fractions of a cent). `tax_rate` is a string
such as `"0.0825"`.

Finance's money rule: **every amount is rounded to whole cents, and exact halves round
up** (so 0.225 becomes 0.23). Rounding happens at each step:

1. each line total is quantity × unit price, rounded to cents
2. the subtotal is the sum of the line totals
3. the tax is subtotal × tax rate, rounded to cents
4. the total is subtotal + tax

The invoice has one row per line, then the subtotal, tax and total:

```
API calls: 3 x $0.075 = $0.23
Subtotal: $0.23
Tax (10%): $0.02
Total: $0.25
```

Amounts of $1,000 or more use a thousands separator.

## Running the tests

```
python -m pytest
```
