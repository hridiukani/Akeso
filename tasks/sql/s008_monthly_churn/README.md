# Monthly customer churn, Q2 2026

The board wants monthly **customer churn** for April, May and June 2026.

Definitions:
- A customer is active on a day when they have at least one subscription active that day: it
  started on or before that day (`start_date <= day`) and hasn't ended (`end_date` is NULL,
  or later than that day). `end_date` is the first day no longer on that subscription.
- Customers are counted once, however many subscriptions they have. Changing plan ends one
  subscription and starts another on the same day, so the customer stays active.
- For each month: **active at start** is the number of customers active on its first day.
  **Churned** is how many of those are not active on the first day of the next month.
  **Churn rate** is churned / active at start.

Expected result: one row per month, in month order (April first), with four columns:
1. the month as `YYYY-MM`
2. customers active at the start of the month
3. customers churned during the month
4. the churn rate, as a fraction (e.g. 0.0278), compared to 4 decimal places
