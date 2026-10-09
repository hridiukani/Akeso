# Each customer's latest plan

Account managers want to know which plan each customer is on, or was last on, as of
2026-06-30.

Definitions:
- Consider only subscriptions that started on or before 2026-06-30.
- A customer's latest plan is the plan of their **most recent** such subscription: the one
  with the latest `start_date`. Customers who have since cancelled are included, with the
  plan they were last on.
- Customers who never subscribed are not included.

Expected result: one row per customer, with two columns:
1. `customer_id`
2. the name of their latest plan

Row order doesn't matter.
