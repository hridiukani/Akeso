# Monthly revenue, Q2 2026

The quarterly report needs, for each month of Q2 2026 (April, May and June), how many
successful payments there were and how much revenue they brought in.

Definitions:
- Only payments with status `'succeeded'` count.
- A payment belongs to the calendar month of its `paid_at` timestamp.
- Q2 2026 runs from 2026-04-01 00:00:00 to 2026-06-30 23:59:59, every day included in full.

Expected result: one row per month, in month order (April first), with three columns:
1. the month as text in the form `YYYY-MM`, e.g. `2026-04`
2. the number of successful payments that month
3. their total amount in dollars
