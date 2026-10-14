# Top products per category, first half of 2026

Merchandising wants the **top 3 products by units kept in each category** for the first
half of 2026: units sold, minus units that came back.

Definitions:
- The first half of 2026: `ordered_at` from 2026-01-01 00:00:00 to 2026-06-30 23:59:59.
- Units sold: the total `quantity` of a product's order lines in that period.
- Units returned: the total `returns.quantity` for returns of those order lines, recorded on
  or before 2026-06-30. A line can be returned in several parts (several rows).
- Units kept = units sold - units returned. Only products with at least one unit sold in
  the period are ranked.
- Rank within a category by units kept, highest first. **Tied products share a rank**, and
  the next rank skips accordingly (like sports standings: 1, 2, 2, 4). Keep every product
  whose rank is 3 or better, so a category can have more than three rows when there are ties.

Expected result: one row per kept product, with four columns:
1. the category
2. the rank
3. the product's name
4. its units kept

**Order:** by category (alphabetically), then rank, then product name.
