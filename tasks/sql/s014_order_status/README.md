# June 2026 orders by status

Operations wants a snapshot: of the orders placed in June 2026, how many were in each status
at the end of 2026-06-30?

Definitions:
- Orders placed in June 2026: `ordered_at` from 2026-06-01 00:00:00 to 2026-06-30 23:59:59.
- An order's status at a moment is the status of its **most recent** event in
  `order_events` at or before that moment. Here the moment is 2026-06-30 23:59:59, so later
  events are ignored.
- Statuses are `placed`, `paid`, `shipped`, `delivered` and `cancelled`; only statuses that
  at least one order is in appear in the result.

Expected result: one row per status, with two columns:
1. the status
2. the number of June 2026 orders in that status at the end of 2026-06-30

Row order doesn't matter.
