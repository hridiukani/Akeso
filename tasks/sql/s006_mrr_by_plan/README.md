# Monthly recurring revenue by plan

Finance reports **monthly recurring revenue (MRR)** as of 2026-06-30, per plan.

Definitions:
- A subscription is active on a day when it started on or before that day
  (`start_date <= day`) and hasn't ended: `end_date` is NULL, or later than that day.
  (`end_date` is the first day the customer is no longer on that subscription.)
- A subscription's monthly value is its plan's list `price` for monthly plans, and
  `price / 12` for annual plans (`billing_period = 'annual'`). Discounts and failed
  payments don't matter here: MRR uses list prices.
- MRR for a plan is the sum of the monthly values of its subscriptions active on 2026-06-30.

Expected result: one row per plan with at least one active subscription on that day, with
two columns:
1. the plan's name
2. its MRR in dollars

Row order doesn't matter.
