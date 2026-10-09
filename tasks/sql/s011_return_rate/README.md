# Return rate per category, 2025 orders

Quality control wants the **return rate** of every product category for orders placed in 2025.

Definitions:
- Orders placed in 2025: `ordered_at` from 2025-01-01 00:00:00 to 2025-12-31 23:59:59.
- Units sold: the total `quantity` of those orders' lines for products in the category.
- Units returned: the total `returns.quantity` for returns of those lines, recorded on or
  before 2026-06-30. A line can be returned in several parts.
- Return rate = units returned / units sold, as a fraction (e.g. 0.0641), compared to 4
  decimal places. A category with no units sold has a NULL rate (it can't be computed).

Expected result: one row for **every category in `products`**, with two columns:
1. the category
2. its return rate (NULL when nothing in it was sold)

Row order doesn't matter.
