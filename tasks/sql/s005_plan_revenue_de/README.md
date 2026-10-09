# Plan revenue from Germany, Q2 2026

The German sales team wants revenue per plan for the second quarter of 2026, from customers
in Germany. **Every plan must appear**, with 0 when it had no such revenue, so the report
always has the same rows.

Definitions:
- A customer is in Germany when `customers.country` is `'DE'`.
- Revenue is the sum of `payments.amount` over payments with status `'succeeded'`.
- Q2 2026 runs from 2026-04-01 00:00:00 to 2026-06-30 23:59:59 (by `paid_at`).
- A payment belongs to the plan of the subscription it paid for.

Expected result: one row per plan in the `plans` table (all of them), with two columns:
1. the plan's name
2. its revenue from German customers in Q2 2026, in dollars (0 if none)

Row order doesn't matter.
