# Big spenders, first half of 2026

Customer success wants every customer whose **successful payments in the first half of
2026 add up to more than $500**.

Definitions:
- Only payments with status `'succeeded'` count.
- The first half of 2026 runs from 2026-01-01 00:00:00 to 2026-06-30 23:59:59 (by `paid_at`).
- "More than $500" means the customer's total over that period is strictly greater than 500.

Expected result: one row per such customer, with three columns:
1. `customer_id`
2. the customer's name
3. their total of successful payments in the period, in dollars

Row order doesn't matter.
