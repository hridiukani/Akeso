# Orders and spend per customer, first half of 2026

For each customer who ordered in the first half of 2026: how many orders they placed, and
how much they spent.

Definitions:
- The first half of 2026 runs from 2026-01-01 00:00:00 to 2026-06-30 23:59:59 (by `ordered_at`).
- An order line's amount is `quantity * unit_price * (1 - discount)`, where a NULL
  `discount` means no discount.
- A customer's spend is the total amount of all lines of their orders in the period
  (returns don't matter here).

Expected result: one row per customer with at least one order in the period, with three columns:
1. `customer_id`
2. the number of orders they placed
3. the amount they spent, in dollars

Row order doesn't matter.
