-- June 2026 orders by their status at the end of 2026-06-30.
WITH current_status AS (
    SELECT e.order_id, MAX(e.status) AS status
    FROM order_events AS e
    JOIN orders AS o ON o.order_id = e.order_id
    WHERE o.ordered_at >= '2026-06-01'
      AND o.ordered_at < '2026-07-01'
      AND e.happened_at < '2026-07-01'
    GROUP BY e.order_id
)
SELECT status, COUNT(*) AS orders
FROM current_status
GROUP BY status;
