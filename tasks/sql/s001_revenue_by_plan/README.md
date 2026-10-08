# Revenue by plan

Finance wants the total revenue of each plan for the 90 days ending 2026-06-30.

Definitions:
- **Revenue** is the sum of `payments.amount` over payments with status `'succeeded'`.
  Failed payments were never collected, and refunded payments were returned, so neither
  counts.
- **The 90 days ending 2026-06-30** run from 2026-04-02 to 2026-06-30, both days included
  in full (by `payments.paid_at`).
- A payment belongs to the plan of the subscription it paid for. A customer who changed
  plan has one subscription per plan, so their payments are split between those plans.

Expected result: one row per plan that had revenue in the window, with two columns:
1. the plan's name
2. its revenue in dollars

Row order doesn't matter.
