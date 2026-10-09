# Monthly orders and growth, July 2025 to June 2026

The weekly business review wants the number of orders in each month from July 2025 to June
2026 and the month-over-month growth.

Definitions:
- An order belongs to the month of its `ordered_at` timestamp.
- **Every one of the 12 months appears**, even a month with no orders (count 0).
- Growth for a month = (orders this month - orders last month) / orders last month, as a
  fraction (e.g. 0.32 for 32% more), compared to 4 decimal places. It's NULL for July
  2025 (no previous month in the report) and for a month whose previous month had 0 orders.

Expected result: one row per month, **in month order**, with three columns:
1. the month as `YYYY-MM`
2. the number of orders
3. the growth (or NULL)
