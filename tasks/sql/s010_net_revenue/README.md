# Net revenue per category, Q2 2026

Finance wants **net revenue** per product category for orders placed in the second quarter
of 2026: what was sold, minus what was refunded.

Definitions:
- Orders placed in Q2 2026: `ordered_at` from 2026-04-01 00:00:00 to 2026-06-30 23:59:59.
- An order line's amount is `quantity * unit_price * (1 - discount)`, where a NULL
  `discount` means no discount.
- Sales for a category: the total amount of those orders' lines for products in the category.
- Refunds: `returns.refund_amount` for returns of those order lines, recorded on or before
  2026-06-30 (`returned_at`). A line can be returned in several parts (several rows). A
  NULL `refund_amount` means the refund hasn't been processed yet, so it counts as 0.
- Net revenue = sales - refunds.

Expected result: one row per category that had sales in those orders, with two columns:
1. the category
2. its net revenue, in dollars

Row order doesn't matter.
